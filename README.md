# ludusavi-manifest-alpha-slices

[中文](README.md) | [English](README.en.md) · [GitHub 仓库](https://github.com/KannaNyaa/ludusavi-manifest-alpha-slices)

按游戏名首字符切分的 [ludusavi-manifest](https://github.com/mtkennerly/ludusavi-manifest) 镜像：
把上游那个单文件的 `manifest.yaml` 拆成 `a.yaml` … `z.yaml` 26 个字母分片，外加
`digits.yaml`、`unicode.yaml`、`symbols.yaml` 三个特殊分片和一份 `info.yaml` 索引。
条目格式、schema、目录命名完全沿用上游，唯一的变化是文件名划分。

## 开发说明

本仓库的脚本、CI 配置与文档由 **WorkBuddy**（AI 编程助手）使用 **DeepSeek-V4.1-Flash** 模型生成，
再由仓库维护者审阅与调整。数据本身来自上游项目，不含任何 AI 生成内容。

## 这个仓库用来做什么

上游把所有游戏放在一个 `manifest.yaml` 里。文件越大，问题越明显：任何一次数据变动都落在同一个文件里，
diff 噪音大、逐条审阅困难；下游只想按游戏名查几条数据，却必须整包下载。

本仓库把同一份数据按首字符切开，解决三件事：

* **按需下载** —— 只想查 H 开头的游戏，就只取 `h.yaml`；不知道要哪一份，先看 `info.yaml`。
* **干净的 diff** —— 上游一次更新通常只改动少数分片，审阅和镜像都只看变化的那几个文件。
* **可验证的增量同步** —— `info.yaml` 记录每个分片的 sha256 与上游整体摘要，客户端据此判断要不要拉、拉哪几个。

本仓库**不做**这些事：

* 不爬取 PCGamingWiki，也不生成游戏数据 —— 只消费上游发布的产物；
* 不修改、不补充任何条目内容，条目格式与上游完全一致。

## 分片规则

只看游戏名的**首字符**，大小写不敏感：

| 首字符 | 文件 | 说明 |
|---|---|---|
| `a` – `z` | `a.yaml` … `z.yaml`（26 个） | 英文字母 |
| `0` – `9` | `digits.yaml` | 数字开头 |
| 非 ASCII 字母/数字 | `unicode.yaml` | 带变音符号的拉丁字母、西里尔字母、希腊字母、CJK 等 |
| 其它（符号） | `symbols.yaml` | `!` `'` `$` `¡` `★` `《` `＜` 等 |

每个分片的条目数量与字节数随时在变，请以 [`info.yaml`](data/manifest/info.yaml) 为准。
上游原始文件见 [mtkennerly/ludusavi-manifest](https://github.com/mtkennerly/ludusavi-manifest) 的
[`data/manifest.yaml`](https://github.com/mtkennerly/ludusavi-manifest/blob/master/data/manifest.yaml)。

规则实现只有一处：`scripts/shardlib.py` 的 `shard_for()`，十几行，任何语言都能照抄。

每个分片本身就是**合法的 Ludusavi manifest**（顶层仍是 `游戏名 → 条目`），
可以直接喂给任何支持该格式的工具。

## 为什么可以放心替换

切分是**逐行文本切分**，不是「解析再序列化」：顶层键行顶格、条目内容缩进，
所以每个分片就是原文件里对应的那一段，不会改写引号、缩进、转义或键顺序。

把 26 个字母分片和三个特殊分片按游戏名排序拼接，得到的文件与上游 `data/manifest.yaml`
**字节级完全一致**。这个回转校验在每次切分时自动执行，CI 里也会再验一遍，
所以用分片替代原文件不需要担心内容漂移。

## 仓库结构

```
.
├── data/
│   ├── manifest/                 # 分片产物（入库）
│   │   ├── info.yaml             # 索引：构建时间、计数、每个分片的 sha256
│   │   ├── a.yaml … z.yaml
│   │   ├── digits.yaml
│   │   ├── unicode.yaml
│   │   └── symbols.yaml
│   ├── manifest.yaml             # 上游完整文件（不入库，由 sync 下载）
│   ├── manifest-override.yaml    # 上游原样保留
│   ├── schema.yaml               # 上游原样保留（条目格式校验）
│   ├── schema.strict.yaml        # 上游原样保留
│   ├── missing.md                # 上游原样保留（尚无存档信息的游戏）
│   └── wiki-malformed.md         # 上游原样保留
├── scripts/
│   ├── sync_manifest.py          # 下载上游 manifest（ETag / sha256 短路）
│   ├── split_manifest.py         # 切分 + 生成 info.yaml + 无损自校验
│   ├── merge_manifest.py         # 分片合回单文件
│   ├── verify_shards.py          # 校验分片与 info.yaml 完全对应
│   ├── update.py                 # 一键：sync → split
│   └── shardlib.py               # 共用逻辑（分片规则、切分、合并）
├── examples/pull_shards.py       # 消费方示例：按需同步 + sha256 增量
└── .github/workflows/
    ├── sync.yaml                 # 定时同步 → 切分 → 提交
    └── check.yaml                # PR 自检
```

`data/` 下文件与上游一一对应，只有 `manifest.yaml` 变成了 `manifest/` 目录。
上游那个爬 PCGamingWiki 的 Rust 程序（`src/`、`Cargo.toml`）没有搬进来。

## info.yaml 字段

`data/manifest/info.yaml` 是唯一需要读的索引，结构如下：

| 字段 | 类型 | 说明 |
|---|---|---|
| `formatVersion` | int | 索引格式版本 |
| `generatedAt` | string | 这份数据最近一次**内容变化**的时间（UTC，ISO 8601） |
| `generator` | string | 生成器标识 |
| `source.repository` / `source.ref` | string | 上游仓库与分支 |
| `source.url` | string | 上游完整文件地址 |
| `source.etag` / `source.lastModified` | string | 上游 HTTP 缓存头，可配合 `If-None-Match` |
| `source.sha256` | string | 上游完整 manifest 的 sha256 |
| `source.sizeBytes` / `source.lines` | int | 上游文件的字节数与行数 |
| `manifest.games` | int | 条目总数 |
| `manifest.shards` | int | 分片数量 |
| `manifest.files` | int | 含 `info.yaml` 的文件数量 |
| `manifest.bytes` | int | 全部分片字节数之和 |
| `manifest.withSaveTag` | int | 带 `save` 标签的条目数 |
| `manifest.sections` | map | 各字段出现的条目数（`files`、`registry`、`steam`…） |
| `sharding.rule` / `sharding.description` | string | 当前分片规则标识与文字说明 |
| `shards` | list | 逐分片清单，字段见下 |
| `shards[].path` | string | 相对路径，如 `a.yaml` |
| `shards[].key` / `shards[].group` | string | 分片键；类别为 `letter` / `digits` / `unicode` / `symbols` |
| `shards[].games` / `shards[].bytes` | int | 该分片的条目数与字节数 |
| `shards[].sha256` | string | 该分片内容摘要，用于增量同步 |
| `shards[].first` / `shards[].last` | string | 该分片首、末条目名 |

同步方的典型做法：先取 `info.yaml`，比对 `source.sha256` 或 `generatedAt`；
没变就跳过，变了再只拉 `sha256` 不一样的那几个分片。

内容没有变化时重复切分不会改动 `generatedAt`，所以「重跑一次」不会制造假变更，
`git status` 也保持干净。

## 怎么用

把链接里的 `h.yaml` 换成需要的分片即可：

| 方式 | URL |
|---|---|
| GitHub Raw | `https://raw.githubusercontent.com/KannaNyaa/ludusavi-manifest-alpha-slices/main/data/manifest/h.yaml` |
| jsDelivr CDN | `https://cdn.jsdelivr.net/gh/KannaNyaa/ludusavi-manifest-alpha-slices@main/data/manifest/h.yaml` |

```bash
# 只要 H 开头的游戏
curl -O https://raw.githubusercontent.com/KannaNyaa/ludusavi-manifest-alpha-slices/main/data/manifest/h.yaml

# 先看索引，判断要不要更新
curl -s https://raw.githubusercontent.com/KannaNyaa/ludusavi-manifest-alpha-slices/main/data/manifest/info.yaml | head -20
```

```python
import urllib.request, yaml

BASE = "https://raw.githubusercontent.com/KannaNyaa/ludusavi-manifest-alpha-slices/main/data/manifest"
info = yaml.safe_load(urllib.request.urlopen(f"{BASE}/info.yaml"))
saves = yaml.safe_load(urllib.request.urlopen(f"{BASE}/h.yaml"))

print(info["manifest"]["games"], "games in total")
print(len(saves), "games starting with H")
```

带 sha256 缓存、只拉变化分片的完整示例见
[`examples/pull_shards.py`](examples/pull_shards.py)（零依赖，可直接运行）。

需要单文件的地方（老工具）本地合一下即可：

```bash
python scripts/merge_manifest.py --out manifest.yaml
```

## 自动更新

[`.github/workflows/sync.yaml`](.github/workflows/sync.yaml) 每天 4 次
（UTC 03:17 / 09:17 / 15:17 / 21:17）执行：

1. `sync_manifest.py` 带 `If-None-Match` 请求上游，ETag 未变就直接结束；
2. 内容变了才下载，`split_manifest.py` 重新切分并生成 `info.yaml`；
3. 合并回单文件做**字节级比对**，不一致则失败，不提交；
4. 条目数骤降超过阈值（默认 5%）会被拦下，防止上游异常把数据写坏；
5. `verify_shards.py` 校验分片与 `info.yaml` 完全对应；
6. 只有内容真的变了才 commit 并 push。

手动触发：Actions → **Sync** → Run workflow，可选 `force`（忽略 ETag 强制重下）与
`allow_shrink`（允许条目数大幅下降）。

## 本地开发

只依赖 Python 3.10+，切分与合并全部零第三方库：

```bash
python scripts/update.py            # 下载上游 → 切分
python scripts/update.py --local    # 已有 data/manifest.yaml 时，只重切分
python scripts/verify_shards.py     # 校验分片与 info.yaml
python scripts/merge_manifest.py --out out.yaml        # 合回单文件
```

常用参数：

| 脚本 | 参数 | 作用 |
|---|---|---|
| `split_manifest.py` | `--allow-shrink` | 允许条目数大幅下降 |
| | `--drop-limit` | 调整骤降告警阈值（默认 `0.05`） |
| | `--no-prune` | 保留已废弃的分片文件 |
| | `--no-verify` | 跳过合并回转校验 |
| `sync_manifest.py` | `--repo` / `--ref` / `--url` | 换上游来源 |
| | `--force` | 忽略 ETag 重新下载 |
| | `--with-missing` | 顺带更新 `data/missing.md` |
| `merge_manifest.py` | `--expect <file>` | 与给定文件比对，不一致则报错 |

### 改分片规则

想换成别的划分（比如首两个字母），只需改 `scripts/shardlib.py` 的 `shard_for()`
—— 唯一权威实现。然后 `python scripts/update.py --local` 重跑，旧分片会被自动清理。
`info.yaml` 的 `sharding` 字段会记录当前规则，方便同步方判断。

## 数据来源与许可

* 数据来自 [PCGamingWiki](https://www.pcgamingwiki.com/) 与 Steam API，
  由 [mtkennerly/ludusavi-manifest](https://github.com/mtkennerly/ludusavi-manifest) 维护，
  本仓库只做重新分片。
* 代码遵循 [MIT LICENSE](LICENSE)。数据本身的署名与许可要求以 Wiki 内容许可为准。
* 分片是自动生成的产物，**不要手改**：条目有误请直接去改 Wiki，上游会周期性同步过来。
