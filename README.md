# sgs_skin_scraper

从 Bwiki 三国杀 WIKI 批量下载皮肤图片。基于 SMW + MediaWiki 双 API，支持静态/大图/动态 GIF 三种资源、势力/品质筛选、并发下载与 URL 增量缓存。

## 为什么需要这个工具？

- 想拿三国杀皮肤图片做二创，却不知道去哪里找图片
- 三国杀 WIKI 收录 1900+ 个皮肤，浏览器逐个保存效率极低
- 皮肤图片分散在 5000+ 个 MediaWiki 文件页中，手动提取直链不现实
- WIKI 定期更新新皮肤，需要增量下载而非全量重新爬取
- 图片默认命名不含武将信息，需要自动归类到势力目录

**sgs_skin_scraper 解决这些问题**：一条命令完成全量下载与归类，增量更新时自动复用缓存，仅解析新皮肤 URL。

## ⭐亮点

- **双 API 协作**：SMW API 获取元数据，MediaWiki API 批量解析 50 个/次直链 URL
- **增量缓存**：URL 缓存到 `.url_cache.json`，新皮肤才调 API，旧皮肤秒级跳过
- **Cloudflare 反限流**：浏览器指纹头 + 随机 UA 轮换 + 渐进退避（30s→300s）+ 随机抖动
- **三种资源类型**：静态 PNG、大图、动态 GIF，可按类型独立下载
- **多维筛选**：按势力、品质、武将名任意组合过滤，按指定维度自动分目录
- **并发下载**：`--concurrency 20` 控制并行数，自动跳过已存在文件
- **自动归类**：输出按势力分目录，文件名格式 `{皮肤名}-{武将名}-{类型}.png|gif`

## 📸效果预览

CLI 运行效果：

```text
$ python sgs_skin_scraper.py --max-skins 5

22:15:01 [INFO] 正在初始化会话（访问 wiki 首页获取 Cookie）...
22:15:03 [INFO] 会话初始化成功 (status: 200, cookies: 3)
22:15:04 [INFO] 正在获取皮肤列表...
22:15:06 [INFO] 已获取 500 条皮肤 (offset=0)
22:15:07 [INFO] 已获取 1000 条皮肤 (offset=500)
22:15:08 [INFO] 已获取 1500 条皮肤 (offset=1000)
22:15:09 [INFO] 已获取 1901 条皮肤 (offset=1500)
22:15:09 [INFO] 共获取 1901 条皮肤记录
22:15:09 [INFO] 筛选后 5 条皮肤 (共 1901 条)
22:15:09 [INFO] 待解析文件: 11 个
22:15:09 [INFO] 缓存命 0 / 未命 11 / 失效 0，仅解析 11 个新文件
22:15:10 [INFO] 缓存已保存: 11 条 URL → output/sgs_skins/.url_cache.json
22:15:10 [INFO] 解析成功: 11 / 11
22:15:10 [INFO] 开始下载 11 个文件 (并发 10)...
22:15:18 [INFO] 完成: 成功 11, 跳过 0, 失败 0
22:15:18 [INFO] 输出目录: D:\info\sgs_skin_scraper\output\sgs_skins
```

输出目录结构：

```text
output/sgs_skins/
├── .url_cache.json
├── 蜀/
│   ├── 轻舞花烛-孙尚香-静态.png
│   ├── 轻舞花烛-孙尚香-大图.png
│   └── 轻舞花烛-孙尚香-动态.gif
├── 魏/
├── 吴/
├── 群/
├── 神/
└── 未知/
```

## 🚀快速开始

### 1. 克隆项目

```bash
# Gitee 镜像（国内访问快）
git clone https://gitee.com/yhl5244/sgs_skin_scraper.git
cd sgs_skin_scraper

# GitHub 原仓库
git clone https://github.com/5244DragonLin/sgs_skin_scraper.git
cd sgs_skin_scraper
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 运行

```bash
# 下载全部皮肤
python sgs_skin_scraper.py

# 只下蜀国传说皮
python sgs_skin_scraper.py --faction 蜀 --quality 传说

# 只下曹操和赵云的皮肤
python sgs_skin_scraper.py --general 曹操,赵云

# 按武将名分文件夹
python sgs_skin_scraper.py --group-by general

# 测试：先下 3 个看看
python sgs_skin_scraper.py --max-skins 3

# 仅预览不下载
python sgs_skin_scraper.py --max-skins 3 --dry-run
```

## ⌨️CLI 模式

```
python sgs_skin_scraper.py [选项]
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
sgs_skin_scraper/
├── sgs_skin_scraper.py    # 主脚本（单文件，无外部模块依赖）
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

## 🤝贡献

欢迎提 Issue 和 PR！

### 已知问题 / 待改进点

暂无。

### 贡献流程

Fork → 创建分支 → 提交修改 → 发起 Pull Request。

## 📋更新日志

### v1.1

- 新增 `--general` 参数，支持按武将名筛选
- 新增 `--group-by` 参数，支持按势力/武将/品质分文件夹

### v1.0

- 首个可用版本

## 📃许可证

MIT
