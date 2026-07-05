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
- **语音音频下载**：基于 BWIKI 前端拼音转换算法推导官方音频直链，自动下载台词对应 .mp3 语音文件
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
├── .url_cache.json              ← URL 解析缓存
├── metadata.json                ← 皮肤故事+台词+音频直链（--with-metadata --with-audio）
├── general_factions.json        ← 武将→势力映射缓存
├── 蜀/                          ← 按势力自动归类
├── 魏/
│   ├── 惊鸿倩影-曹金玉-静态.png
│   ├── 惊鸿倩影-曹金玉-大图.png
│   ├── 惊鸿倩影-曹金玉-动态.gif
│   ├── 经典形象-曹金玉.png      ← 原画仅1文件
│   ├── 慧光玉颜-曹金玉-静态.png ← 史诗仅静态
│   ├── 惊鸿倩影-曹金玉-audio/      ← 音频文件（--download-audio）
│   │   ├── 隅泣_01.mp3
│   │   ├── 隅泣_02.mp3
│   │   ├── 善身_01.mp3
│   │   ├── 善身_02.mp3
│   │   ├── 娴静_01.mp3
│   │   ├── 娴静_02.mp3
│   │   └── 阵亡_01.mp3
│   ├── 慧光玉颜-曹金玉-audio/
│   │   └── ...
├── 吴/
├── 群/
└── 神/
```

使用 `--with-metadata --with-audio` 后，`metadata.json` 内容示例：

```json
{
  "惊鸿倩影*曹金玉": {
    "story": "金乡公主曹金玉近日有些闷闷不乐...",
    "quality": "传说",
    "所属收藏册": "喜乐锦年",
    "画师": "DH",
    "静态获取方式": "累计参与新春夺宝120次（消耗新春夺宝券*600）",
    "动态获取方式": "累计消费达到88888元宝",
    "voice_lines": {
      "隅泣": ["泪眼婆娑泣，伊人憔悴消。", "柔情愁肠断，寂寞梧桐落。"],
      "善身": ["天子之家，需守心静身。", "心清则明，积善则安。"],
      "娴静": ["娴雅淑静，冰清玉洁。", "媖娴美好，典雅温蕴。"],
      "阵亡": ["余香空留此，玉指轻揉散。"]
    },
    "audio": {
      "隅泣": [
        "https://web.sanguosha.com/10/pc/res/assets/runtime/voice/skin/caojinyu02/CaoJinYu_YuQi_01.mp3",
        "https://web.sanguosha.com/10/pc/res/assets/runtime/voice/skin/caojinyu02/CaoJinYu_YuQi_02.mp3"
      ],
      "善身": ["https://web.sanguosha.com/10/pc/res/assets/runtime/voice/skin/caojinyu02/CaoJinYu_ShanShen_01.mp3"],
      "阵亡": ["https://web.sanguosha.com/10/pc/res/assets/runtime/voice/skin/caojinyu02/CaoJinYu_Dead.mp3"]
    }
  }
}
```

注意：`quality`、`所属收藏册`、`画师`、`上线时间`、`静态获取方式`、`动态获取方式` 自动从皮肤页面抓取，字段值为空时自动省略。`audio` 中的 URL 为官方直链，可直接用于播放或下载。

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

# 写入语音音频直链到 metadata.json（需与 --with-metadata 共用）
python sgs_bwiki_skins.py --general 谋关羽 --with-metadata --with-audio

# 仅下载语音音频文件（不写 metadata.json）
python sgs_bwiki_skins.py --general 谋关羽 --download-audio

# 写入直链 + 下载音频
python sgs_bwiki_skins.py --general 谋关羽 --with-metadata --with-audio --download-audio

# 强制全量刷新元数据（忽略已有缓存）
python sgs_bwiki_skins.py --with-metadata --refresh-metadata

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
| `--with-audio` | 在 `metadata.json` 中写入语音台词对应的官方音频直链（需与 `--with-metadata` 共用） | 关闭 |
| `--download-audio` | 下载语音台词对应的 .mp3 音频文件到 `audio/` 子目录；可与 `--with-audio` 组合使用 | 关闭 |
| `--refresh-metadata` | 强制重新爬取全部皮肤元数据，忽略已有 metadata.json（配合 `--with-metadata` 使用） | 关闭 |

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
├── sgs_bwiki_skins.py    # 主脚本（基于 requests + pypinyin）
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

**--with-audio 下载的是哪个来源的音频？**

语音音频来自三国杀官方服务器 `web.sanguosha.com`。URL 通过 BWIKI 页面中 `bikit-audio` 元素的 `data-src` 属性，经拼音转换算法推导而成。音频文件命名规则为 `{技能名}_{序号}.mp3`，存放在 `{输出目录}/{分组}/{皮肤名}-{武将名}-audio/` 下。

**--with-audio 和 --with-metadata 有什么区别？**

`--with-metadata` 只爬取故事文本和台词文字内容；`--with-audio` 将官方音频直链写入 `metadata.json`（需与 `--with-metadata` 共用）；`--download-audio` 将 .mp3 文件下载到磁盘。三者可任意组合：仅记录直链不下载，或仅下载不记录。

**--download-audio 和 --with-audio 同时使用会重复爬取吗？**

不会。当 `--with-metadata --with-audio` 先运行时，音频直链已写入 `metadata.json`，`--download-audio` 阶段会复用元数据结果，不会重复请求皮肤页面。

## 🤝贡献

欢迎提 Issue 和 PR！

### 已知问题 / 待改进点

- [x] 战场荣耀/战场绝版系列皮肤名带赛季后缀 `(S19)` 等，SMW 返回的所属武将去掉了后缀，导致 key 冲突被覆盖 — **已修复**：改用 SMW 原始页面标题作为 key，保留赛季后缀区分不同版本。
- [x] 部分皮肤有"动态登场"（动态入场动画）文件类型（如 `战场绝版-徐氏-动态登场(S19).gif`），目前仅下载静态/大图/动态三种，未支持动态登场 — **已修复**：形态含"动态"时额外生成 `动态登场.gif` 文件。
- [x] 增量更新模式下，如果 WIKI 后续更新了皮肤的所属收藏册、画师、获取方式等信息（如某皮肤最初不在收藏册内，后来被加入），metadata 中的旧字段不会自动刷新。 — **已修复**：使用 `--refresh-metadata` 参数可强制全量重新爬取。
- [ ] BWIKI 中缺失大部分低品质皮肤（普通、稀有等），需要额外寻找数据源。
- [ ] 部分皮肤的语音音频在官方服务器上不存在（返回 404），此时 `--download-audio` 会自动跳过。
- [ ] 低画质皮肤、GIF 画质增强。

### 贡献流程

Fork → 创建分支 → 提交修改 → 发起 Pull Request。

## 📋更新日志

### v1.1
- 新增 `--with-audio` 参数：在 metadata.json 中写入官方音频直链（需与 `--with-metadata` 共用）
- 新增 `--download-audio` 参数：下载语音台词对应的官方 .mp3 音频文件，与 `--with-audio` 分离，可独立使用
- `--with-audio` 和 `--download-audio` 可组合使用，实现"先记直链再下载"的完整流程
- metadata.json 自动保存：每爬取 100 条即写盘一次，避免中途崩溃丢数据
- metadata.json 增量更新：自动复用已有元数据，只抓取新增或缺失的皮肤，不再全量覆盖
- metadata.json 新增字段：`品质`、 `所属收藏册`、`画师`、`上线时间`、`静态获取方式`、`动态获取方式`，空字段自动省略
- 修复战场荣耀/战场绝版系列赛季后缀 key 冲突：改用 SMW 原始页面标题作为 metadata key，`战场绝版*徐氏(S19)` 与 `战场绝版*徐氏(S9)` 不再被互相覆盖
- 新增 `--refresh-metadata` 参数：强制全量重新爬取元数据，忽略已有缓存

### v1.0

- 首个可用版本

## ☕捐赠

你的支持是我坚持开源的动力。

| 支付宝 | 微信 |
|--------|------|
| ![支付宝](https://gitee.com/yhl5244/images/raw/master/donate_alipay.jpg) | ![微信](https://gitee.com/yhl5244/images/raw/master/donate_wechat.jpg) |

## ⚠️免责声明

本工具仅供学习交流使用，不得用于任何违反法律法规或侵犯第三方权益的用途。
因使用本工具产生的一切后果由使用者自行承担，作者不承担任何法律责任。

## 📃许可证

MIT
