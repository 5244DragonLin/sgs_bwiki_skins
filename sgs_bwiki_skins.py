"""
sgs_bwiki_skins — 从 Bwiki 三国杀 WIKI 批量下载皮肤图片

用法:
    python sgs_bwiki_skins.py                          # 下载全部皮肤到 ./output
    python sgs_bwiki_skins.py --static-only             # 仅下载静态图
    python sgs_bwiki_skins.py --dynamic-only            # 仅下载动态 GIF
    python sgs_bwiki_skins.py --concurrency 20          # 20 并发下载
    python sgs_bwiki_skins.py --output D:/skins         # 指定输出目录
    python sgs_bwiki_skins.py --faction 蜀,魏            # 仅下载指定势力
    python sgs_bwiki_skins.py --quality 传说,限定,史诗   # 仅下载指定品质
    python sgs_bwiki_skins.py --general 曹操,赵云        # 仅下载指定武将
    python sgs_bwiki_skins.py --group-by general         # 按武将名分文件夹

数据来源: https://wiki.biligame.com/sgs/皮肤
依赖: pip install requests
项目主页: https://github.com/yaenli/sgs_bwiki_skins
"""

import argparse
import json
import logging
import os
import random
import re
import time
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None  # type: ignore

logger = logging.getLogger("bwiki_sgs")


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="bwiki_sgs_scraper",
        description="从 Bwiki 三国杀 WIKI 批量下载皮肤图片",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
示例:
  python sgs_bwiki_skins.py                              # 下载全部皮肤
  python sgs_bwiki_skins.py --static-only                # 仅静态图
  python sgs_bwiki_skins.py --dynamic-only               # 仅动态 GIF
  python sgs_bwiki_skins.py --faction 蜀,吴 --quality 传说  # 蜀+吴传说皮
  python sgs_bwiki_skins.py --general 曹操,赵云             # 仅下载指定武将皮肤
""",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="输出根目录，默认当前目录下的 output/sgs_skins",
    )
    parser.add_argument(
        "--concurrency", "-c",
        type=int,
        default=10,
        help="并发下载数，默认 10",
    )
    parser.add_argument(
        "--static-only",
        action="store_true",
        help="仅下载静态图（PNG）",
    )
    parser.add_argument(
        "--dynamic-only",
        action="store_true",
        help="仅下载动态图（GIF）",
    )
    parser.add_argument(
        "--big-only",
        action="store_true",
        help="仅下载大图",
    )
    parser.add_argument(
        "--faction",
        default=None,
        help="筛选势力，逗号分隔，如: 魏,蜀,吴,群,神",
    )
    parser.add_argument(
        "--quality",
        default=None,
        help="筛选品质，逗号分隔，如: 传说,限定,史诗,原画",
    )
    parser.add_argument(
        "--general",
        default=None,
        help="筛选武将，逗号分隔，如: 曹操,赵云,诸葛亮",
    )
    parser.add_argument(
        "--max-skins",
        type=int,
        default=0,
        help="最大下载皮肤数（0=不限制，用于测试），默认 0",
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=1.0,
        help="每次 API 请求间隔秒数，默认 1.0（Cloudflare 限流严格，不建议低于此值）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="仅列出可下载皮肤，不实际下载",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="不使用 URL 缓存，强制重新解析所有文件 URL",
    )
    parser.add_argument(
        "--cache-file",
        default=None,
        help="缓存文件路径，默认 {output}/.url_cache.json",
    )
    parser.add_argument(
        "--url-concurrency",
        type=int,
        default=5,
        help="URL 解析阶段的内部并发数，默认 5（0=串行，兼容旧行为）",
    )
    parser.add_argument(
        "--group-by",
        default="faction",
        choices=["faction", "general", "quality", "none"],
        help="输出目录分组方式: faction=按势力, general=按武将, quality=按品质, none=不分组 (默认 faction)",
    )
    parser.add_argument(
        "--with-metadata",
        action="store_true",
        help="同时爬取皮肤故事和皮肤台词，保存为 metadata.json",
    )
    return parser.parse_args(argv)


_UA_LIST = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36 Edg/130.0.0.0",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:133.0) Gecko/20100101 Firefox/133.0",
]


def _make_session_headers(ua: str, is_html: bool = False) -> dict:
    """构建请求头。"""
    headers = {
        "User-Agent": ua,
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://wiki.biligame.com/sgs/",
    }
    if is_html:
        headers["Accept"] = "text/html,application/xhtml+xml,*/*"
    else:
        headers.update({
            "Accept": "application/json, text/plain, */*",
            "Accept-Encoding": "gzip, deflate, br",
            "Origin": "https://wiki.biligame.com",
            "Sec-Fetch-Dest": "empty",
            "Sec-Fetch-Mode": "cors",
            "Sec-Fetch-Site": "same-origin",
            "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Windows"',
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        })
    return headers


def _create_base_session() -> requests.Session:
    """创建带重试配置的基础 Session。"""
    session = requests.Session()
    # 优化 Retry 配置：明确处理连接错误、读取错误和限流
    retry = Retry(
        total=5,  # 增加总重试次数
        connect=3,  # 连接错误重试 3 次
        read=3,  # 读取错误重试 3 次
        backoff_factor=2.0,  # 退避因子：2s, 4s, 8s...
        backoff_max=60,  # 最大退避时间 60s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET", "HEAD"],  # 仅重试安全的 HTTP 方法
    )
    adapter = HTTPAdapter(
        max_retries=retry,
        pool_connections=10,  # 降低连接池大小，避免过多连接
        pool_maxsize=10,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def create_session() -> requests.Session:
    """创建带完整浏览器指纹的 Session，初始化 Cookie。"""
    session = _create_base_session()
    ua = random.choice(_UA_LIST)
    session.headers.update(_make_session_headers(ua))

    # 先访问 wiki 首页获取 Cookie（Cloudflare 会在此时下发验证 Cookie）
    try:
        logger.info("正在初始化会话（访问 wiki 首页获取 Cookie）...")
        resp = session.get(
            "https://wiki.biligame.com/sgs/",
            headers=_make_session_headers(ua, is_html=True),
            timeout=30,
        )
        if resp.status_code == 567:
            logger.warning("首页也触发限流，等待 30s 后重试...")
            time.sleep(30)
            resp = session.get("https://wiki.biligame.com/sgs/",
                               headers=_make_session_headers(ua, is_html=True),
                               timeout=30)
        if resp.status_code == 200:
            logger.info("会话初始化成功 (status: %d, cookies: %d)",
                        resp.status_code, len(session.cookies))
        else:
            logger.warning("首页访问返回 %d，后续 API 可能受限", resp.status_code)
    except Exception as e:
        logger.warning("初始化会话时出错: %s，继续尝试", e)

    return session


def create_download_session() -> requests.Session:
    """创建轻量下载 Session（不访问首页，仅下载直链用）。"""
    session = _create_base_session()
    session.headers.update({
        "User-Agent": random.choice(_UA_LIST),
        "Accept": "*/*",
        "Accept-Encoding": "gzip, deflate, br",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://wiki.biligame.com/sgs/",
        "Cache-Control": "no-cache",
    })
    return session


def _fetch_classic_image_url(session: requests.Session, general_name: str) -> str:
    """从武将页 HTML 中提取经典形象图片直链。

    经典皮肤图片在 BWIKI 武将页中通常以缩略图形式嵌入 HTML，
    原图 URL 可以通过缩略图 URL 推导得到。

    缩略图格式:
        .../thumb/XX/YY/HASH.png/NNNpx-武将名-经典形象.png
    原图格式:
        .../XX/YY/HASH.png
    """
    try:
        page_url = f"https://wiki.biligame.com/sgs/{general_name}"
        r = session.get(page_url, timeout=30)
        if r.status_code != 200:
            logger.debug("武将页 %s 返回 %d", general_name, r.status_code)
            return ""
    except Exception as e:
        logger.debug("武将页请求失败 %s: %s", general_name, e)
        return ""

    # 策略 1：在页面中找包含武将名的经典形象缩略图 → 转为原图 URL
    # 匹配格式: //patchwiki.biligame.com/images/sgs/thumb/X/Y/HASH.png/NNNpx-武将名-经典形象.png
    # 按优先级匹配: "经典形象" > "经典" > "原画"
    for label in ("经典形象", "经典", "原画"):
        thumb_pattern = re.compile(
            rf'//patchwiki\.biligame\.com/images/sgs/thumb/'
            rf'[0-9a-f]/[0-9a-f]/[0-9a-z]+\.(?:png|jpg|webp)/'
            rf'\d+px-[^"\'\s]*{re.escape(general_name)}[^"\'\s]*'
            rf'{re.escape(label)}[^"\'\s]*\.(?:png|jpg|webp)'
        )
        m = thumb_pattern.search(r.text)
        if m:
            thumb_url = m.group(0)
            # 缩略图: //patchwiki.biligame.com/images/sgs/thumb/X/Y/HASH.png/NNNpx-NAME.png
            # 原图:   //patchwiki.biligame.com/images/sgs/X/Y/HASH.png
            orig_url = re.sub(
                r'^//patchwiki\.biligame\.com/images/sgs/thumb/',
                'https://patchwiki.biligame.com/images/sgs/',
                thumb_url,
            )
            orig_url = re.sub(r'/\d+px-[^/]+$', '', orig_url)
            logger.debug("经典图片 %s → %s (通过缩略图)", general_name, orig_url[:120])
            return orig_url

    # 策略 2（兜底）：找非缩略图 URL（兼容旧版页面或无经典标签的武将）
    pattern2 = re.compile(
        rf'//patchwiki\.biligame\.com/images/sgs/'
        rf'[0-9a-f]/[0-9a-f]/[0-9a-z]+\.(?:png|jpg|webp)'
    )
    matches2 = pattern2.findall(r.text)
    for m in matches2:
        url = f"https:{m}"
        if "/thumb/" not in url:
            logger.debug("经典图片(兜底) %s → %s", general_name, url[:100])
            return url

    logger.debug("经典图片未找到: %s", general_name)
    return ""


def _parse_voice_lines(raw_text: str) -> Dict[str, List[str]]:
    """从皮肤页 Wikitext 中解析台词。

    Wikitext 格式:
        {{新版台词|隅泣:line1./line2.;善身:line1./line2.;阵亡:line.|NN}}
    Returns:
        {"隅泣": ["line1.", "line2."], "善身": [...], "阵亡": ["line."]}
    """
    m = re.search(r'\{\{新版台词\|(.+?)\|', raw_text, re.DOTALL)
    if not m:
        return {}

    result = {}
    parts = m.group(1).split(';')
    for part in parts:
        part = part.strip()
        if ':' not in part:
            continue
        skill, lines_text = part.split(':', 1)
        lines = [l.strip() for l in lines_text.split('/') if l.strip()]
        if lines:
            result[skill.strip()] = lines

    return result


def _parse_skin_story(raw_text: str) -> str:
    """从皮肤页 Wikitext 中提取皮肤故事。

    Wikitext 格式:
        |皮肤故事=第一段。<br>第二段。<br>...
    """
    m = re.search(r'\|皮肤故事=(.+?)(?=\n\||\n\}\})', raw_text, re.DOTALL)
    if not m:
        return ""
    story = m.group(1).strip()
    # 替换 <br> 为换行，清理空格
    story = re.sub(r'<br\s*/?>', '\n', story)
    story = re.sub(r'\n{3,}', '\n\n', story)
    return story.strip()


def fetch_skin_metadata(session: requests.Session, skin: dict) -> dict:
    """爬取单个皮肤页面的故事和台词。

    分两步：
    1. 优先尝试 raw Wikitext（常规皮肤快速解析）
    2. raw 为纯模板（如 {{初始皮肤}}）则回退到渲染 HTML 解析

    Returns:
        {"story": "...", "voice_lines": {"隅泣": [...], "阵亡": [...]}}
    """
    page_title = skin.get("skin_name", "") + "*" + skin.get("general", "")

    # 策略 1：从 raw Wikitext 解析（常规皮肤）
    raw_url = (
        "https://wiki.biligame.com/sgs/index.php"
        f"?title={urllib.parse.quote(page_title)}&action=raw"
    )
    try:
        r = session.get(raw_url, timeout=30)
        if r.status_code == 200:
            raw_text = r.text
            # 检查是否包含实际数据（非纯模板）
            if '|皮肤故事=' in raw_text or '{{新版台词|' in raw_text:
                return {
                    "story": _parse_skin_story(raw_text),
                    "voice_lines": _parse_voice_lines(raw_text),
                }
    except Exception as e:
        logger.debug("皮肤页 raw 请求失败 %s: %s", page_title, e)

    # 策略 2：从渲染后的 HTML 解析（初始皮肤模板等经典皮肤）
    html_url = f"https://wiki.biligame.com/sgs/{urllib.parse.quote(page_title)}"
    try:
        r = session.get(html_url, timeout=30)
        if r.status_code == 200:
            html = r.text
            story = _parse_story_from_html(html)
            voice_lines = _parse_voice_lines_from_html(html)
            if story or voice_lines:
                return {"story": story, "voice_lines": voice_lines}
    except Exception as e:
        logger.debug("皮肤页 HTML 获取失败 %s: %s", page_title, e)

    return {"story": "", "voice_lines": {}}


def _parse_story_from_html(html: str) -> str:
    """从渲染后的 HTML 中提取皮肤故事。"""
    # h2 格式: <h2><span class="mw-headline" id="皮肤故事">... (class 在 span 上)
    section_pat = re.compile(
        r'<h2[^>]*>.*?<span[^>]*?id="皮肤故事"[^>]*?>.*?</span>.*?</h2>\s*'
        r'(.*?)(?=<h2[> ]|$)',
        re.DOTALL,
    )
    m = section_pat.search(html)
    if not m:
        return ""
    content = m.group(1)
    content = re.sub(r'<br\s*/?>', '\n', content)
    content = re.sub(r'<[^>]+>', '', content)
    content = re.sub(r'\s*\n\s*', '\n', content)
    content = re.sub(r'\n{3,}', '\n\n', content)
    content = content.strip()
    # 去掉开头的"皮肤故事"标题（section 内可能重复出现）
    content = re.sub(r'^皮肤故事[\s\S]*?\n', '', content)
    return content.strip()


def _parse_voice_lines_from_html(html: str) -> Dict[str, List[str]]:
    """从渲染后的 HTML 中提取皮肤台词。

    经典皮肤页面用 div 结构组织台词：
        <div class="basic-info-row-label"><a ...>隅泣</a></div>
        <div>语音行1。/语音行2。</div>
    常规皮肤页面用 p 标签：
        <p><a ...>隅泣</a></p>
        <p>line1.</p>
        <p>/line2.</p>
    """
    section_pat = re.compile(
        r'<h2[^>]*>.*?<span[^>]*?id="皮肤台词"[^>]*?>.*?</span>.*?</h2>\s*'
        r'(.*?)(?=<h2[> ]|$)',
        re.DOTALL,
    )
    m = section_pat.search(html)
    if not m:
        return {}
    section_html = m.group(1)

    # 尝试用 <a> 标签定位技能名 + 后续 <p> 或 <div> 中的语音
    result = {}

    # 处理带 <a> 标签的技能（隅泣、善身、娴静等）
    item_pat = re.compile(
        r'<a[^>]*>(.*?)</a>\s*</div>\s*'
        r'<div[^>]*style="align-self:\s*center;?"[^>]*>\s*(.*?)\s*</div>',
        re.DOTALL,
    )
    for item_m in item_pat.finditer(section_html):
        skill = item_m.group(1).strip()
        # 移除 skill name 中的 HTML 标签（部分皮肤在 a 内部有 span）
        skill = re.sub(r'<[^>]+>', '', skill).strip()
        lines_text = item_m.group(2).strip()
        # 移除 audio 按钮标签
        lines_text = re.sub(r'<span[^>]*class="bikit-audio[^"]*"[^>]*>.*?</span>', '', lines_text)
        lines_text = re.sub(r'<[^>]+>', '', lines_text)
        lines_text = lines_text.strip()
        lines = [l.strip() for l in re.split(r'\s*/\s*', lines_text) if l.strip()]
        if skill and lines:
            result[skill] = lines

    # 处理阵亡（无 <a> 标签的纯文本）
    dead_pat = re.compile(
        r'<div[^>]*>\s*阵亡\s*</div>\s*'
        r'<div[^>]*style="align-self:\s*center;?"[^>]*>\s*(.*?)\s*</div>',
        re.DOTALL,
    )
    dm = dead_pat.search(section_html)
    if dm:
        dead_text = re.sub(r'<[^>]+>', '', dm.group(1)).strip()
        if dead_text:
            result['阵亡'] = [dead_text]

    # 纯文本兜底解析（常规皮肤的 p 标签结构）
    if not result:
        p_pat = re.compile(r'<p[^>]*>(.*?)</p>', re.DOTALL)
        paragraphs = p_pat.findall(section_html)
        current_skill = None
        for p_text in paragraphs:
            strip_text = re.sub(r'<[^>]+>', '', p_text).strip()
            if not strip_text:
                continue
            a_tag = re.search(r'<a[^>]*>(.*?)</a>', p_text)
            if a_tag:
                skill = a_tag.group(1).strip()
                if skill:
                    current_skill = skill
                    result[current_skill] = []
                    continue
            if strip_text == '阵亡':
                current_skill = '阵亡'
                result[current_skill] = []
                continue
            if current_skill is not None and strip_text:
                if strip_text.startswith('/'):
                    strip_text = strip_text[1:]
                if strip_text:
                    result[current_skill].append(strip_text)

    return result


def _load_classic_cdn_map(output_root) -> dict:
    """自动查找 xsjs 爬虫输出的 heroes_skins.json，提取经典皮肤CDN映射。

    查找顺序: output目录同级的 sgs_xsjs_scraper/output/heroes_skins.json
    """
    import glob
    candidates = [
        os.path.join(os.path.dirname(output_root), "..", "sgs_xsjs_scraper", "output", "heroes_skins.json"),
        os.path.join(output_root, "..", "..", "sgs_xsjs_scraper", "output", "heroes_skins.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                mapping = {}
                for h in data.get("heroes", []):
                    name = h.get("name", "")
                    for s in h.get("skins", []):
                        if "经典形象" in s.get("skin_name", "") and s.get("skin_img"):
                            mapping[name] = s["skin_img"]
                            break
                logger.info("从 xsjs 数据加载 %d 个经典皮肤CDN映射 (%s)", len(mapping), path)
                return mapping
            except Exception as e:
                logger.debug("读取 xsjs 数据失败: %s", e)
    logger.debug("未找到 xsjs 参考数据，经典皮肤无法自动回退")
    return {}


def extract_quality(quality_html: str) -> str:
    """从 HTML 提取品质文本。"""
    # 匹配 badge div 内的文本，如 <div class="badge" ...>传说</div>
    m = re.search(r'"badge"[^>]*>([^<]+)</div>', quality_html)
    if m:
        return m.group(1)
    # 兜底：match iteminfo 如 ▇=传说
    item_map = {"▃": "原画", "▆": "史诗", "▇": "传说", "▉▇": "限定", "▉▉": "限定至臻"}
    for symbol, name in item_map.items():
        if symbol in quality_html:
            return name
    return "未知"


# 硬编码的遗漏武将→势力映射（BWIKI 分类:武将 未收录时使用）
# 当 _match_general_faction 所有匹配策略都失败时，会尝试从武将页 HTML 抓取
# 此处仅保留少量已知的边缘武将作为最后兜底
_FACTION_OVERRIDE = {
    "孟节": "群",
    "张温": "吴",
    "鲍三娘": "蜀",
}


def _fetch_general_faction_from_page(session: requests.Session, general: str) -> str:
    """从武将页 HTML 中提取势力。"""
    try:
        url = f"https://wiki.biligame.com/sgs/{urllib.parse.quote(general)}"
        r = session.get(url, timeout=30)
        if r.status_code != 200:
            return ""
        # HTML 格式: <p class="gold-title-color" ...>势力</p>群</div>
        patterns = [
            re.compile(r'>势力</p>(\S+?)</div>'),
            re.compile(r'势力[^<]*</th>\s*<td[^>]*>\s*(\S+?)\s*</td>'),
        ]
        for pat in patterns:
            m = pat.search(r.text)
            if m:
                fac = m.group(1).strip()
                if fac in ("魏", "蜀", "吴", "群", "神", "晋", "汉"):
                    return fac
    except Exception:
        pass
    return ""


def _match_general_faction(general_name: str, faction_map: dict,
                           session: Optional[requests.Session] = None) -> str:
    """从势力映射表中匹配武将的势力，支持多种匹配策略。"""
    if not general_name:
        return ""

    name = general_name.strip()

    # 1. 精确匹配
    if name in faction_map:
        return faction_map[name]

    # 2. 硬编码覆盖
    if name in _FACTION_OVERRIDE:
        return _FACTION_OVERRIDE[name]

    # 3. 去除前缀后匹配（前缀列表按长度降序，优先匹配长前缀）
    prefixes = sorted(["SP", "界", "谋", "神", "族", "星", "诸葛"], key=len, reverse=True)
    for prefix in prefixes:
        if name.startswith(prefix):
            stripped = name[len(prefix):]
            if stripped in faction_map:
                return faction_map[stripped]

    # 4. 后缀匹配（如 "界赵云" → 匹配 map 中的 "赵云"）
    for known, fac in faction_map.items():
        if name.endswith(known) or known.endswith(name):
            return fac

    # 5. 子串匹配
    for known, fac in faction_map.items():
        if known in name or name in known:
            return fac

    # 6. 从武将页 HTML 抓取（最后兜底）
    if session is not None:
        fac = _fetch_general_faction_from_page(session, name)
        if fac:
            logger.debug("从武将页抓取势力: %s → %s", name, fac)
            return fac

    return ""


def fetch_general_factions(session: requests.Session, cache_dir: str = "") -> dict:
    """查询 BWIKI 获取武将→势力映射表（优先读缓存文件）。

    Args:
        session: HTTP 会话
        cache_dir: 缓存文件存放目录，空字符串则不缓存

    Returns:
        {"夏侯惇": "魏", "诸葛亮": "蜀", ...}
    """
    cache_path = os.path.join(cache_dir, "general_factions.json") if cache_dir else ""

    # 优先读缓存
    if cache_path and os.path.exists(cache_path):
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                mapping = json.load(f)
            logger.info("从缓存加载 %d 个武将势力映射", len(mapping))
            return mapping
        except (json.JSONDecodeError, IOError):
            pass

    api_url = "https://wiki.biligame.com/sgs/api.php"
    mapping = {}
    offset = 0
    batch_size = 500

    logger.info("正在获取武将势力映射表...")
    while True:
        query = f"[[分类:武将]]|?势力|limit={batch_size}|offset={offset}"
        params = {"action": "ask", "query": query, "format": "json"}
        try:
            r = session.get(api_url, params=params, timeout=30)
            r.raise_for_status()
            data = r.json()
        except Exception as e:
            logger.warning("获取武将势力失败: %s", e)
            break

        results = data.get("query", {}).get("results", {})
        cont = data.get("query-continue-offset")
        if not results and cont is None:
            break

        # results 是 {title: {printouts: {...}}, ...} 格式
        if isinstance(results, dict):
            for title, info in results.items():
                po = info.get("printouts", {})
                faction_list = po.get("势力", [])
                if faction_list and faction_list[0]:
                    mapping[title] = faction_list[0]

        offset += batch_size
        if cont is None:
            break
        time.sleep(0.1)

    logger.info("获取到 %d 个武将势力映射", len(mapping))

    # 保存缓存
    if cache_path and mapping:
        os.makedirs(cache_dir, exist_ok=True)
        with open(cache_path, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
        logger.info("势力映射已缓存: %s", cache_path)

    return mapping


def fetch_all_skins(session: requests.Session, delay: float = 0.1) -> List[dict]:
    """通过 SMW API 分页获取全部皮肤列表。

    Returns:
        [{skin_name, general, faction, quality, morphology, page_url}, ...]
    """
    api_url = "https://wiki.biligame.com/sgs/api.php"
    all_skins = []
    offset = 0
    batch_size = 500

    while True:
        query = f"[[分类:皮肤]]|?皮肤名|?所属武将|?势力|?品质展示|?形态|?上线时间|limit={batch_size}|offset={offset}"
        params = {
            "action": "ask",
            "query": query,
            "format": "json",
            "api_version": "3",
        }
        for retry_count in range(5):
            try:
                resp = session.get(api_url, params=params, timeout=60)
                if resp.status_code == 567:
                    # 渐进退避: 30s / 60s / 120s / 180s / 300s + 随机抖动 0-15s
                    base = min(30 << retry_count, 300)
                    wait = base + random.uniform(0, min(base * 0.5, 30))
                    logger.warning(
                        "遭限流 (567)，第 %d/5 次重试，等待 %.0fs...",
                        retry_count + 1, wait,
                    )
                    time.sleep(wait)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except requests.HTTPError as e:
                if retry_count < 4:
                    wait = (retry_count + 1) * 15 + random.uniform(0, 10)
                    logger.warning("HTTP 错误: %s，等待 %.0fs 重试...", e, wait)
                    time.sleep(wait)
                else:
                    raise
            except Exception as e:
                if retry_count < 4:
                    wait = (retry_count + 1) * 10 + random.uniform(0, 5)
                    logger.warning("API 请求失败: %s，等待 %.0fs 重试...", e, wait)
                    time.sleep(wait)
                else:
                    raise

        results = data.get("query", {}).get("results", [])
        cont = data.get("query-continue-offset")
        # 仅在无结果且无续传标记时才退出
        if not results and cont is None:
            break

        for item in results:
            for title, info in item.items():
                po = info.get("printouts", {})
                skins = {
                    "skin_name": (po.get("皮肤名") or [""])[0],
                    "general": (po.get("所属武将") or [""])[0],
                    "faction": (po.get("势力") or [""])[0],
                    "quality_raw": (po.get("品质展示") or [""])[0],
                    "morphology": (po.get("形态") or [""])[0],
                    "page_url": info.get("fullurl", ""),
                }
                skins["quality"] = extract_quality(skins["quality_raw"])
                all_skins.append(skins)

        logger.info("已获取 %d 条皮肤 (offset=%d)", len(all_skins), offset)
        offset += batch_size

        if cont is None:
            break

        time.sleep(delay)

    logger.info("共获取 %d 条皮肤记录", len(all_skins))
    return all_skins


def build_file_names(skin: dict) -> List[Tuple[str, str]]:
    """根据皮肤信息构建要下载的文件名列表。

    注意：经典原画皮肤在 wiki 上的文件命名规范不同——
    常规皮肤: {皮肤名}-{武将名}-{类型}.png
    经典原画: {武将名}-{皮肤名}.png（无 静态/大图 之分，仅一张图）

    Returns:
        [(文件:名称, 本地保存文件名), ...]
    """
    sn = skin["skin_name"]
    gn = skin["general"]
    morph = skin.get("morphology", "")
    quality = skin.get("quality", "")

    files = []

    # 经典原画皮肤：文件名为 {武将名}-{皮肤名}.png，仅一张图（无静态/大图区分）
    if quality in ("原画", "经典形象") or sn == "经典形象":
        file_title = f"文件:{gn}-{sn}.png"
        local_name = f"{sn}-{gn}.png"
        files.append((file_title, local_name))
        return files

    # 常规皮肤：{皮肤名}-{武将名}-{类型}.png
    # 根据品质分级决定生成哪些文件——
    #   普通/稀有/史诗: 仅静态图（低品质一般没有大图和动态图）
    #   传说/限定:      静态 + 大图（大图率高），动态依形态字段
    static_file = f"文件:{sn}-{gn}-静态.png"
    local_static = f"{sn}-{gn}-静态.png"
    files.append((static_file, local_static))

    # 仅传说/限定品质生成大图
    if quality in ("传说", "限定"):
        big_file = f"文件:{sn}-{gn}-大图.png"
        local_big = f"{sn}-{gn}-大图.png"
        files.append((big_file, local_big))

    # 动态 GIF — 仅当形态包含"动态"时生成
    if "动态" in morph:
        gif_file = f"文件:{sn}-{gn}-动态.gif"
        local_gif = f"{sn}-{gn}-动态.gif"
        files.append((gif_file, local_gif))

    return files


def _resolve_url_batch(
    session: requests.Session, batch: List[str], api_url: str
) -> Dict[str, Optional[str]]:
    """解析一批文件名为直链 URL（内部函数，供并发调用）。"""
    batch_result = {}
    params = {
        "action": "query",
        "titles": "|".join(batch),
        "prop": "imageinfo",
        "iiprop": "url",
        "format": "json",
    }
    for retry_count in range(5):
        try:
            resp = session.get(api_url, params=params, timeout=60)
            if resp.status_code == 567:
                base = min(30 << retry_count, 180)
                wait = base + random.uniform(0, min(base * 0.3, 20))
                logger.warning(
                    "批量解析遭限流，第 %d/5 次重试，等待 %.0fs...",
                    retry_count + 1, wait,
                )
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            for pid, pinfo in data.get("query", {}).get("pages", {}).items():
                title = pinfo.get("title", "")
                ii = pinfo.get("imageinfo", [])
                url = ii[0]["url"] if ii else None
                batch_result[title] = url
            break
        except requests.HTTPError:
            if retry_count < 4:
                time.sleep(10 << retry_count)
                continue
            else:
                logger.warning("批量解析最终失败 (batch_size=%d)", len(batch))
                for t in batch:
                    batch_result[t] = None
        except Exception as e:
            if retry_count < 4:
                logger.warning("批量解析异常: %s，重试中...", e)
                time.sleep(5)
                continue
            else:
                logger.warning("批量解析最终异常: %s", e)
                for t in batch:
                    batch_result.setdefault(t, None)
    return batch_result


def resolve_urls_batch(
    session: requests.Session, file_titles: List[str],
    delay: float = 0.05, concurrency: int = 5,
) -> Dict[str, Optional[str]]:
    """批量解析文件名为直链 URL（支持内部并发）。

    Args:
        file_titles: 文件标题列表，如 ["文件:xxx-静态.png", ...]
        delay: API 请求间隔
        concurrency: 内部并发解析数，<=1 或文件总量小时退化为串行

    Returns:
        {title: url or None}
    """
    api_url = "https://wiki.biligame.com/sgs/api.php"
    batch_size = 50  # MediaWiki API 限制
    batches = [file_titles[i:i + batch_size] for i in range(0, len(file_titles), batch_size)]

    if not batches:
        return {}

    result = {}

    # 文件量小 → 串行（兼容旧行为，避免小批量多线程开销）
    if concurrency <= 1 or len(batches) <= 1:
        batch_iter = range(len(batches))
        progress = (
            tqdm(batch_iter, total=len(batches), desc="解析 URL",
                 unit="batch", ncols=80)
            if tqdm else batch_iter
        )
        for i in progress:
            result.update(_resolve_url_batch(session, batches[i], api_url))
            time.sleep(delay)
        return result

    # 并发模式
    actual_workers = min(concurrency, len(batches))
    logger.info("并发解析 %d 个 batch (workers=%d)...", len(batches), actual_workers)

    # 并发用 tqdm 进度条
    pbar = (
        tqdm(total=len(batches), desc="解析 URL", unit="batch", ncols=70, leave=False)
        if tqdm else None
    )

    with ThreadPoolExecutor(max_workers=actual_workers) as executor:
        futures = {
            executor.submit(_resolve_url_batch, session, batch, api_url): i
            for i, batch in enumerate(batches)
        }
        done = 0
        for future in as_completed(futures):
            batch_result = future.result()
            result.update(batch_result)
            done += 1
            if pbar:
                pbar.update(1)
            else:
                if done % max(1, len(batches) // 10) == 0:
                    logger.info("URL 解析进度: %d / %d", done, len(batches))
            time.sleep(delay * 0.1)

    if pbar:
        pbar.close()  # 批次间轻量间隔防止限流

    return result


def load_cache(cache_path: Path) -> Dict[str, str]:
    """加载 URL 缓存。返回 {file_title: url}。"""
    if cache_path.exists():
        try:
            with open(cache_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                logger.info("已加载缓存: %d 条 URL", len(data))
                return data
        except Exception as e:
            logger.warning("缓存文件损坏 (%s), 将忽略", e)
    return {}


def save_cache(cache_path: Path, url_map: Dict[str, Optional[str]]) -> None:
    """保存 URL 缓存，跳过 None 值。"""
    clean = {k: v for k, v in url_map.items() if v}
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with open(cache_path, "w", encoding="utf-8") as f:
        json.dump(clean, f, ensure_ascii=False, indent=2)
    logger.info("缓存已保存: %d 条 URL → %s", len(clean), cache_path)


def evict_cache_keys(cache_path: Path, keys: List[str]) -> None:
    """从缓存文件中移除指定的 key（用于失效 URL 自动清理）。"""
    if not keys:
        return
    try:
        cached = load_cache(cache_path)
        removed = 0
        for k in keys:
            if k in cached:
                del cached[k]
                removed += 1
        if removed:
            save_cache(cache_path, cached)
            logger.info("已从缓存清除 %d 个失效 key，下次将重新解析", removed)
    except Exception as e:
        logger.warning("清理缓存失败: %s", e)


def resolve_urls_with_cache(
    session: requests.Session,
    file_titles: List[str],
    cache_path: Path,
    use_cache: bool,
    delay: float,
    concurrency: int = 5,
) -> Dict[str, Optional[str]]:
    """带缓存的 URL 解析：旧 title 复用缓存，仅解析新 title。

    Returns:
        {file_title: url or None}  含缓存命中和新解析结果。
    """
    if not use_cache:
        logger.info("--no-cache 模式：跳过缓存，全量解析 %d 个文件", len(file_titles))
        return resolve_urls_batch(session, file_titles, delay=delay, concurrency=concurrency)

    cached = load_cache(cache_path)

    # 找出需要解析的新 title
    new_titles = [t for t in file_titles if t not in cached]
    missing_from_cache = [t for t in file_titles if t in cached and cached[t] is None]

    if not new_titles and not missing_from_cache:
        logger.info("全部 %d 个文件命中缓存，无需 API 解析", len(file_titles))
        return {t: cached[t] for t in file_titles}

    to_resolve = new_titles + missing_from_cache
    logger.info(
        "缓存命 %d / 未命 %d / 失效 %d，仅解析 %d 个新文件",
        len(file_titles) - len(to_resolve), len(new_titles),
        len(missing_from_cache), len(to_resolve),
    )

    new_map = resolve_urls_batch(session, to_resolve, delay=delay, concurrency=concurrency)

    # 合并并写回缓存
    merged = {**cached, **new_map}
    save_cache(cache_path, merged)

    return {t: merged.get(t) for t in file_titles}


def download_one(
    url: str,
    dest_path: Path,
    skip_existing: bool = True,
) -> str:
    """下载单个文件，独立创建 Session，带重试和限流处理。返回 'ok' / 'skip' / 'fail'。"""
    if skip_existing and dest_path.exists():
        return "skip"

    session = create_download_session()

    for retry_count in range(3):
        try:
            resp = session.get(url, timeout=120, stream=True)
            if resp.status_code == 567:
                wait = (retry_count + 1) * 30 + random.uniform(0, 15)
                logger.debug("下载限流 %s，等待 %.0fs...", dest_path.name, wait)
                time.sleep(wait)
                continue
            if resp.status_code != 200:
                if retry_count < 2:
                    time.sleep(5 << retry_count)
                    continue
                return "fail"

            dest_path.parent.mkdir(parents=True, exist_ok=True)
            # 先写临时文件，保证下载完成后再原子重命名
            tmp_path = dest_path.with_suffix(dest_path.suffix + ".tmp")
            with open(tmp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            # 验证文件大小（防止下载到空/错误页）
            if tmp_path.stat().st_size < 1000:
                tmp_path.unlink(missing_ok=True)
                return "fail"

            # 原子重命名
            tmp_path.rename(dest_path)
            return "ok"
        except Exception as e:
            if retry_count < 2:
                time.sleep(3)
            else:
                logger.debug("下载失败 %s: %s", url, e)
                return "fail"

    return "fail"


def main(argv: Optional[List[str]] = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    output_root = Path(args.output) if args.output else Path("output") / "sgs_skins"
    faction_filter = set(f.strip() for f in args.faction.split(",")) if args.faction else None
    quality_filter = set(q.strip() for q in args.quality.split(",")) if args.quality else None
    general_filter = set(g.strip() for g in args.general.split(",")) if args.general else None

    session = create_session()

    # Step 1: 获取全部皮肤列表
    logger.info("正在获取皮肤列表...")
    all_skins = fetch_all_skins(session, delay=args.delay)

    # Step 1.5: 补全缺失的势力（BWIKI 皮肤页可能未填写势力字段）
    # 始终加载势力映射表，不仅用于补空，也用于强化匹配
    faction_map = fetch_general_factions(session, str(output_root))

    empty_faction = [s for s in all_skins if not s["faction"]]
    newly_mapped: Dict[str, str] = {}
    if empty_faction:
        logger.info("%d 个皮肤缺少势力信息，正在补全...", len(empty_faction))
        for s in empty_faction:
            gen = s.get("general", "")
            fac = _match_general_faction(gen, faction_map, session)
            if fac:
                s["faction"] = fac
                if gen not in faction_map and gen not in newly_mapped:
                    newly_mapped[gen] = fac
        still_empty = sum(1 for s in all_skins if not s["faction"])
        still_generals = sorted(set(
            s["general"] for s in all_skins if not s["faction"]
        ))
        logger.info("补全后仍有 %d 个皮肤势力未知 (%s)",
                    still_empty, "、".join(still_generals) if still_generals else "无")

    # 将 HTML 回退抓取到的势力写回缓存，下次不用重复请求
    if newly_mapped:
        faction_map.update(newly_mapped)
        cache_path_faction = os.path.join(str(output_root), "general_factions.json")
        try:
            with open(cache_path_faction, "w", encoding="utf-8") as f:
                json.dump(faction_map, f, ensure_ascii=False, indent=2)
            logger.info("势力映射已更新: %d 个武将补入缓存 (%s)",
                        len(newly_mapped), "、".join(sorted(newly_mapped.keys())))
        except Exception as e:
            logger.debug("势力缓存写入失败: %s", e)

    # Step 2: 筛选
    filtered = []
    for s in all_skins:
        if faction_filter and s["faction"] not in faction_filter:
            continue
        if quality_filter and s["quality"] not in quality_filter:
            continue
        if general_filter and s["general"] not in general_filter:
            continue
        filtered.append(s)

    if args.max_skins > 0:
        filtered = filtered[:args.max_skins]

    logger.info("筛选后 %d 条皮肤 (共 %d 条)", len(filtered), len(all_skins))

    # Step 3: 构建文件名列表
    all_file_names: List[Tuple[str, str, dict]] = []  # (file_title, local_name, skin)
    for skin in filtered:
        for file_title, local_name in build_file_names(skin):
            # 根据筛选条件跳过
            if args.static_only and ("动态" in local_name or "大图" in local_name):
                continue
            if args.dynamic_only and "动态" not in local_name:
                continue
            if args.big_only and "大图" not in local_name:
                continue
            all_file_names.append((file_title, local_name, skin))

    logger.info("待解析文件: %d 个", len(all_file_names))

    # Step 4: 批量解析 URL（带缓存，支持内部并发）
    unique_titles = list(set(ft for ft, _, _ in all_file_names))
    cache_path = Path(args.cache_file) if args.cache_file else output_root / ".url_cache.json"
    use_cache = not args.no_cache

    logger.info("正在解析 %d 个文件 URL...", len(unique_titles))
    url_map = resolve_urls_with_cache(
        session, unique_titles, cache_path, use_cache,
        delay=args.delay, concurrency=args.url_concurrency,
    )

    resolved = sum(1 for u in url_map.values() if u)
    logger.info("解析成功: %d / %d", resolved, len(unique_titles))

    # Step 5.5: 经典皮肤回退 — BWIKI文件页不存在的，从武将页HTML提取图片
    classic_missing = [
        (ft, ln, sk) for ft, ln, sk in all_file_names
        if not url_map.get(ft) and sk.get("quality") in ("原画", "经典形象")
    ]
    if classic_missing:
        # 按武将去重，只请求一次武将页
        generals_needed = list(set(sk["general"] for _, _, sk in classic_missing))
        classic_urls = {}
        for gen in generals_needed:
            url = _fetch_classic_image_url(session, gen)
            if url:
                classic_urls[gen] = url
        if classic_urls:
            patched = 0
            for ft, ln, sk in classic_missing:
                gen = sk["general"]
                if gen in classic_urls:
                    url_map[ft] = classic_urls[gen]
                    patched += 1
            logger.info("经典皮肤回退: 从武将页HTML补全 %d/%d 张图片",
                        patched, len(classic_missing))

    # Step 5: dry-run 模式
    if args.dry_run:
        print(f"\n{'皮肤名':<20} {'武将':<12} {'势力':<6} {'品质':<8} {'形态':<8} {'文件':<40} {'URL状态':<10}")
        print("-" * 110)
        for file_title, local_name, skin in all_file_names:
            url = url_map.get(file_title)
            status = "有" if url else "无"
            print(f"{skin['skin_name']:<20} {skin['general']:<12} {skin['faction']:<6} "
                  f"{skin['quality']:<8} {skin['morphology']:<8} {local_name:<40} {status:<10}")
        return

    # Step 6: 并发下载（每个下载线程使用独立 Session，避免线程安全问题）
    downloads: List[Tuple[str, str, Path]] = []  # (file_title, url, dest)
    for file_title, local_name, skin in all_file_names:
        url = url_map.get(file_title)
        if not url:
            continue

        # 目标路径: output/{分组}/皮肤名-武将名-xx.png
        group = skin["faction"] or "未知"
        if args.group_by == "general":
            group = skin["general"] or "未知"
        elif args.group_by == "quality":
            group = skin["quality"] or "未知"
        elif args.group_by == "none":
            group = ""
        dest = output_root / group / local_name if group else output_root / local_name
        downloads.append((file_title, url, dest))

    if not downloads:
        logger.warning("没有可下载的文件")
        return

    logger.info("开始下载 %d 个文件 (并发 %d)...", len(downloads), args.concurrency)

    ok, skip, fail = 0, 0, 0
    failed_titles: List[str] = []

    dl_pbar = (
        tqdm(total=len(downloads), desc="下载", unit="个", ncols=70, leave=False)
        if tqdm else None
    )

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = {
            executor.submit(download_one, url, dest): file_title
            for file_title, url, dest in downloads
        }
        for future in as_completed(futures):
            file_title = futures[future]
            try:
                result = future.result()
                if result == "ok":
                    ok += 1
                elif result == "skip":
                    skip += 1
                else:
                    fail += 1
                    failed_titles.append(file_title)
            except Exception:
                fail += 1
                failed_titles.append(file_title)

            total = ok + skip + fail
            if dl_pbar:
                dl_pbar.set_postfix_str(f"成功{ok} 失败{fail}" if fail else f"成功{ok}")
                dl_pbar.update(1)
            else:
                actual = ok + fail
                if total == len(downloads):
                    logger.info("完成: 成功 %d, 跳过 %d, 失败 %d", ok, skip, fail)
                elif actual > 0 and actual % 10 == 0:
                    logger.info("进度: 成功 %d, 失败 %d", ok, fail)

    if dl_pbar:
        dl_pbar.close()

    logger.info("下载完成: 成功 %d, 跳过 %d, 失败 %d", ok, skip, fail)

    logger.info("输出目录: %s", output_root.resolve())

    # Step 6.5: 二次扫描「未知」文件夹，用势力映射表自动归类
    unknown_dir = output_root / "未知"
    if args.group_by == "none":
        pass  # 不分组时无"未知"文件夹
    elif unknown_dir.is_dir():
        # 收集 all_skins 中武将→势力的映射（含已补全的）
        skin_faction_map: Dict[str, str] = {}
        for s in all_skins:
            gen = s.get("general", "")
            fac = s.get("faction", "")
            if gen and fac and gen not in skin_faction_map:
                skin_faction_map[gen] = fac

        moved = 0
        for f in sorted(unknown_dir.iterdir()):
            if not f.is_file():
                continue
            # 从文件名提取武将名：常规格式 "皮肤名-武将名-类型.ext" 或原画 "武将名-皮肤名"
            name = f.stem
            # 优先尝试匹配已知武将名（从后往前匹配，因武将名通常在后半段）
            matched_gen = None
            for gen in sorted(skin_faction_map.keys(), key=len, reverse=True):
                if gen in name:
                    matched_gen = gen
                    break
            if matched_gen:
                fac = skin_faction_map[matched_gen]
                dest_dir = output_root / fac
                dest_dir.mkdir(parents=True, exist_ok=True)
                dest = dest_dir / f.name
                if not dest.exists():
                    f.rename(dest)
                    moved += 1
                else:
                    # 目标已存在，删除"未知"中的副本
                    f.unlink()

        if moved:
            logger.info("二次归类: 从「未知」移动 %d 个文件到对应势力目录", moved)
            # 如果"未知"变空了就删除文件夹
            if not any(unknown_dir.iterdir()):
                unknown_dir.rmdir()
                logger.info("「未知」文件夹已清空删除")

    # Step 7: 爬取皮肤故事和台词（可选）
    if args.with_metadata:
        logger.info("正在爬取 %d 个皮肤的故事和台词...", len(filtered))
        metadata = {}

        pbar = tqdm(
            total=len(filtered),
            desc="皮肤元数据",
            unit="个",
            ncols=70,
            leave=False,
        ) if tqdm else None

        for skin in filtered:
            skin_key = f"{skin['skin_name']}*{skin['general']}"
            if skin_key not in metadata:
                data = fetch_skin_metadata(session, skin)
                if data["story"] or data["voice_lines"]:
                    metadata[skin_key] = data
            if pbar:
                pbar.update(1)

        if pbar:
            pbar.close()

        if metadata:
            meta_path = output_root / "metadata.json"
            with open(meta_path, "w", encoding="utf-8") as f:
                json.dump(metadata, f, ensure_ascii=False, indent=2)
            logger.info("元数据已保存: %s (%d 条)", meta_path, len(metadata))

    # 从缓存中移除下载失败的文件 URL，下次运行可重新解析
    if failed_titles and use_cache:
        evict_cache_keys(cache_path, failed_titles)


if __name__ == "__main__":
    main()
