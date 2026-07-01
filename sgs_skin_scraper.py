"""
sgs_skin_scraper — 从 Bwiki 三国杀 WIKI 批量下载皮肤图片

用法:
    python sgs_skin_scraper.py                          # 下载全部皮肤到 ./output
    python sgs_skin_scraper.py --static-only             # 仅下载静态图
    python sgs_skin_scraper.py --dynamic-only            # 仅下载动态 GIF
    python sgs_skin_scraper.py --concurrency 20          # 20 并发下载
    python sgs_skin_scraper.py --output D:/skins         # 指定输出目录
    python sgs_skin_scraper.py --faction 蜀,魏            # 仅下载指定势力
    python sgs_skin_scraper.py --quality 传说,限定,史诗   # 仅下载指定品质

数据来源: https://wiki.biligame.com/sgs/皮肤
依赖: pip install requests
项目主页: https://github.com/yaenli/sgs_skin_scraper
"""

import argparse
import json
import logging
import os
import random
import re
import time
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
  python sgs_skin_scraper.py                              # 下载全部皮肤
  python sgs_skin_scraper.py --static-only                # 仅静态图
  python sgs_skin_scraper.py --dynamic-only               # 仅动态 GIF
  python sgs_skin_scraper.py --faction 蜀,吴 --quality 传说  # 蜀+吴传说皮
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

    Returns:
        [(文件:名称, 本地保存文件名), ...]
    """
    sn = skin["skin_name"]
    gn = skin["general"]
    morph = skin.get("morphology", "")

    files = []

    # 静态图（所有皮肤都有）
    static_file = f"文件:{sn}-{gn}-静态.png"
    local_static = f"{sn}-{gn}-静态.png"
    files.append((static_file, local_static))

    # 大图（大部分皮肤有）
    big_file = f"文件:{sn}-{gn}-大图.png"
    local_big = f"{sn}-{gn}-大图.png"
    files.append((big_file, local_big))

    # 动态 GIF（仅动态皮肤有）
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
            if done % max(1, len(batches) // 10) == 0:
                logger.info("URL 解析进度: %d / %d", done, len(batches))
            time.sleep(delay * 0.1)  # 批次间轻量间隔防止限流

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

    session = create_session()

    # Step 1: 获取全部皮肤列表
    logger.info("正在获取皮肤列表...")
    all_skins = fetch_all_skins(session, delay=args.delay)

    # Step 2: 筛选
    filtered = []
    for s in all_skins:
        if faction_filter and s["faction"] not in faction_filter:
            continue
        if quality_filter and s["quality"] not in quality_filter:
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

        # 目标路径: output/势力/皮肤名-武将名-xx.png
        faction_dir = skin["faction"] or "未知"
        dest = output_root / faction_dir / local_name
        downloads.append((file_title, url, dest))

    if not downloads:
        logger.warning("没有可下载的文件")
        return

    logger.info("开始下载 %d 个文件 (并发 %d)...", len(downloads), args.concurrency)

    ok, skip, fail = 0, 0, 0
    failed_titles: List[str] = []

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
            if total % 50 == 0 or total == len(downloads):
                logger.info("进度: 成功 %d, 跳过 %d, 失败 %d", ok, skip, fail)

    logger.info("完成: 成功 %d, 跳过 %d, 失败 %d", ok, skip, fail)
    logger.info("输出目录: %s", output_root.resolve())

    # 从缓存中移除下载失败的文件 URL，下次运行可重新解析
    if failed_titles and use_cache:
        evict_cache_keys(cache_path, failed_titles)


if __name__ == "__main__":
    main()
