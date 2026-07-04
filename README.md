# sgs_bwiki_skins

从 Bwiki 三国杀 WIKI 批量下载皮肤图片、故事与台词。基于 SMW + MediaWiki 双 API，支持静态/大图/动态 GIF 三种资源、势力/品质筛选、全流程进度条、并发下载与 URL 增量缓存。

## 为什么需要这个工具？

- 想拿三国杀皮肤图片做二创，却不知道去哪里找图片
- 三国杀 WIKI 收录 1900+ 个皮肤，浏览器逐个保存效率极低
- 皮肤图片分散在 5000+ 个 MediaWiki 文件页中，手动提取直链不现实
- WIKI 定期更新新皮肤，需要增量下载而非全量重新爬取
- 图片默认命名不含武将信息，需要自动归类到势力目录
- 皮肤故事与台词分散在各皮肤页面中，手动收集繁琐

**sgs_bwiki_skins 解决这些问题**：一条命令完成全量下载与归类，增量更新时自动复用缓存，仅解析新皮肤 URL；可选爬取故事台词一并存档。

## ⭐亮点

- **双 API 协作**：SMW API 获取元数据，MediaWiki API 批量解析 50 个/次直链 URL
- **增量缓存**：URL 缓存到 `.url_cache.json`，新皮肤才调 API，旧皮肤秒级跳过
- **Cloudflare 反限流**：浏览器指纹头 + 随机 UA 轮换 + 渐进退避（30s→300s）+ 随机抖动
- **三种资源类型**：静态 PNG、大图、动态 GIF，可按类型独立下载
- **多维筛选**：按势力、品质、武将名任意组合过滤，按指定维度自动分目录
- **品质分级下载**：低品质（原画/普通/稀有/史诗）跳过不存在的文件类型，日志干净、请求经济
- **皮肤故事与台词爬取**：可选同时爬取每个皮肤的故事文本和语音台词，保存为结构化 JSON
- **双策略元数据解析**：先尝试 raw Wikitext 快速解析，纯模板页面（经典皮肤）自动回退 HTML 渲染解析
- **全流程进度条**：URL 解析、图片下载、元数据爬取三阶段均使用 tqdm 进度条，替代原始逐行日志
- **并发下载**：`--concurrency 20` 控制并行数，自动跳过已存在文件

## 📸效果预览

全量运行（1906 皮肤，3469 个文件）：

```text
$ python sgs_bwiki_skins.py -o E:/三国杀皮肤/BWIKI

16:05:19 [INFO] 正在初始化会话...
16:05:24 [INFO] 共获取 1906 条皮肤记录
16:05:24 [INFO] 获取到 675 个武将势力映射
16:05:25 [INFO] 15 个皮肤缺少势力信息，正在补全...
16:05:25 [INFO] 补全后仍有 0 个皮肤势力未知 (无)
16:05:25 [INFO] 筛选后 1906 条皮肤 (共 1906 条)
16:05:25 [INFO] 待解析文件: 3496 个
16:05:25 [INFO] 并发解析 70 个 batch (workers=5)...
16:05:32 [INFO] 缓存已保存: 2951 条 URL → .url_cache.json
16:05:32 [INFO] 解析成功: 2951 / 3492
16:05:35 [INFO] 开始下载 2951 个文件 (并发 10)...
下载: 100%|███████████████████████| 2951/2951
16:13:35 [INFO] 下载完成: 成功 2951, 跳过 0, 失败 0
```

输出目录结构：

```text
output/sgs_skins/
├── .url_cache.json          ← URL 解析缓存
├── metadata.json            ← 皮肤故事+台词（--with-metadata）
├── general_factions.json    ← 武将→势力映射缓存
├── 蜀/                      ← 按势力自动归类
├── 魏/
│   ├── 惊鸿倩影-曹金玉-静态.png
│   ├── 惊鸿倩影-曹金玉-大图.png
│   ├── 惊鸿倩影-曹金玉-动态.gif
│   ├── 经典形象-曹金玉.png   ← 原画仅1文件
│   └── 慧光玉颜-曹金玉-静态.png  ← 史诗仅静态
├── 吴/
├── 群/
└── 神/
```

使用 `--with-metadata` 后，`metadata.json` 内容示例：

```json
{
  "惊鸿倩影*曹金玉": {
    "story": "金乡公主曹金玉近日有些闷闷不乐。人人都道自己得了一桩天赐的好婚事...",
    "voice_lines": {
      "隅泣": ["泪眼婆娑泣，伊人憔悴消。", "柔情愁肠断，寂寞梧桐落。"],
      "善身": ["天子之家，需守心静身。", "心清则明，积善则安。"],
      "娴静": ["娴雅淑静，冰清玉洁。", "媖娴美好，典雅温蕴。"],
      "阵亡": ["余香空留此，玉指轻揉散。"]
    }
  }
}
```

## 🚀快速开始

### 1. 克隆项目

```bash
# Gitee 镜像（国内访问快）
git clone https://gitee.com/yhl5244/sgs_bwiki_skins.git
cd sgs_bwiki_skins

# GitHub 原仓库
git clone https://github.com/5244DragonLin/sgs_bwiki_skins.git
cd sgs_bwiki_skins
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 运行

```bash
# 下载全部皮肤
python sgs_bwiki_skins.py

# 只下蜀国传说皮
python sgs_bwiki_skins.py --faction 蜀 --quality 传说

# 只下曹操和赵云的皮肤
python sgs_bwiki_skins.py --general 曹操,赵云

# 按武将名分文件夹
python sgs_bwiki_skins.py --group-by general

# 同时爬取皮肤故事和台词
python sgs_bwiki_skins.py --general 曹金玉 --with-metadata

# 测试：先下 3 个看看
python sgs_bwiki_skins.py --max-skins 3

# 仅预览不下载
python sgs_bwiki_skins.py --max-skins 3 --dry-run
```

## ⌨️CLI 模式

```
python sgs_bwiki_skins.py [选项]
```

### 筛选选项

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--faction` | 势力筛选，逗号分隔（魏,蜀,吴,群,神） | 全部 |
| `--quality` | 品质筛选，逗号分隔（传说,限定,史诗,原画） | 全部 |
| `--general` | 武将筛选，逗号分隔（曹操,赵云,诸葛亮） | 全部 |
| `--max-skins` | 最大下载皮肤数（0=不限制，用于测试） | `0` |

### 类型选项

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--static-only` | 仅下载静态 PNG | 关闭 |
| `--dynamic-only` | 仅下载动态 GIF | 关闭 |
| `--big-only` | 仅下载大图 | 关闭 |

### 元数据选项

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `--with-metadata` | 同时爬取皮肤故事和皮肤台词，保存为 `metadata.json` | 关闭 |

### 输出选项

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `-o, --output` | 输出根目录 | `output/sgs_skins` |
| `--group-by` | 分组方式：faction(势力)/general(武将)/quality(品质)/none(不分组) | `faction` |
| `-c, --concurrency` | 并发下载数 | `10` |
| `--delay` | API 请求间隔（秒） | `1.0` |
| `--no-cache` | 不使用 URL 缓存，强制重新解析 | 关闭 |
| `--cache-file` | 自定义缓存路径 | `{output}/.url_cache.json` |
| `--dry-run` | 仅列出可下载皮肤，不实际下载 | 关闭 |

## 📂项目结构

```text
sgs_bwiki_skins/
├── sgs_bwiki_skins.py    # 主脚本（单文件，无外部模块依赖）
├── requirements.txt        # pip install -r requirements.txt
├── README.md
├── LICENSE
└── .gitignore
```

## ❓️FAQ

**增量下载怎么用？**

直接重复运行同一命令即可。脚本会自动对比 `.url_cache.json`，旧皮肤 URL 直接复用，仅对 WIKI 新增的皮肤调用 API 解析。如果确认 WIKI 更新了已有皮肤的图片文件，使用 `--no-cache` 强制重新解析全部 URL。

**下载中断了怎么办？**

重新运行相同命令。已下载的文件会自动跳过（`skip_existing=True`），URL 缓存也不会丢失，从中断处继续。

**遇到 567 限流怎么办？**

脚本内置了渐进退避重试（最多 5 次，间隔 30s→60s→120s→180s→300s + 随机抖动）。如果持续失败，可以加大 `--delay`（如 `--delay 2.0`）或降低 `--concurrency`。

**下载速度太慢？**

瓶颈在 WIKI CDN 的下载带宽，不是并发数。建议 `--concurrency 5`，过于激进反而容易触发限流。

**为什么有些皮肤只下了静态图？**

这是品质分级策略——普通/稀有/史诗品质的皮肤一般没有独立的大图和动态图，脚本不生成无效文件请求以节省时间。传说/限定品质则会同时下载大图和动态（如有）。

## 🤝贡献

欢迎提 Issue 和 PR！

### 已知问题 / 待改进点

- [ ] BWIKI 中缺失大部分低品质皮肤（普通、稀有等），需要额外寻找数据源。

### 贡献流程

Fork → 创建分支 → 提交修改 → 发起 Pull Request。

## 📋更新日志

### v1.0

- 首个可用版本

## ☕捐赠

你的支持是我坚持开源的动力。

| 支付宝 | 微信 |
|--------|------|
| ![支付宝](https://gitee.com/yhl5244/images/raw/master/donate_alipay.jpg) | ![微信](https://gitee.com/yhl5244/images/raw/master/donate_wechat.jpg) |

## 📃许可证

MIT
