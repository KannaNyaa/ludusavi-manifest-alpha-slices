# ludusavi-manifest-alpha-slices

[中文](README.md) | [English](README.en.md) · [GitHub repository](https://github.com/KannaNyaa/ludusavi-manifest-alpha-slices)

A [ludusavi-manifest](https://github.com/mtkennerly/ludusavi-manifest) mirror sliced by the first
character of each game name: the upstream single-file `manifest.yaml` becomes `a.yaml` … `z.yaml`
(26 letter shards) plus `digits.yaml`, `unicode.yaml`, `symbols.yaml`, and an `info.yaml` index.
Entry format, schema and directory naming are inherited unchanged — only the file names are divided.

## Development note

The scripts, CI configuration and documentation in this repository were generated with
**WorkBuddy** (an AI coding agent) running the **DeepSeek-V4.1-Flash** model, then reviewed and
adjusted by the repository maintainer. The data itself comes from the upstream project and
contains nothing AI-generated.

## What this repository is for

Upstream keeps every game in one `manifest.yaml`. The bigger that file gets, the worse the
practical problems become: every data change lands in the same file, diffs are noisy and hard to
review, and a consumer that needs one game by name still has to download everything.

Slicing the same data by first character addresses three things:

* **Fetch only what you need** — looking for games starting with H? Take `h.yaml`. Not sure which
  shard you need? Read `info.yaml` first.
* **Readable diffs** — an upstream update usually touches a handful of shards, so reviewers and
  mirrors only look at the files that changed.
* **Verifiable incremental sync** — `info.yaml` records a sha256 per shard plus a digest of the
  whole manifest, so a client can decide whether to update at all, and which shards to pull.

This repository deliberately does **not**:

* crawl PCGamingWiki or produce game data — it only consumes what upstream publishes;
* edit, extend or reorder any entry — the format is exactly upstream's.

## Split rule

Only the **first character** of the game name matters, case-insensitive:

| First character | File | Notes |
|---|---|---|
| `a` – `z` | `a.yaml` … `z.yaml` (26 files) | ASCII letters |
| `0` – `9` | `digits.yaml` | leading digit |
| non-ASCII letter/digit | `unicode.yaml` | accented Latin, Cyrillic, Greek, CJK, … |
| anything else | `symbols.yaml` | `!` `'` `$` `¡` `★` `《` `＜` … |

Entry counts and byte sizes change over time; treat [`info.yaml`](data/manifest/info.yaml) as the
source of truth. The original upstream file lives in
[mtkennerly/ludusavi-manifest](https://github.com/mtkennerly/ludusavi-manifest) at
[`data/manifest.yaml`](https://github.com/mtkennerly/ludusavi-manifest/blob/master/data/manifest.yaml).

The rule has exactly one implementation — `shard_for()` in `scripts/shardlib.py`, a dozen lines that
are trivial to port to any language.

Every shard is itself a **valid Ludusavi manifest** (a top-level `game name → entry` mapping) and
can be fed to any tool that understands the format.

## Why it is a safe replacement

Splitting is done **line by line**, not by parsing and re-serializing: top-level keys start in
column 0 and entry bodies are indented, so each shard is literally the corresponding slice of the
original file. Quoting, indentation, escapes and key order are never rewritten.

Concatenating the 26 letter shards and the three special shards in game-name order reproduces the
upstream `data/manifest.yaml` **byte for byte**. That round-trip check runs on every split and again
in CI, so using the shards instead of the single file does not risk content drift.

## Repository layout

```
.
├── data/
│   ├── manifest/                 # sharded output (tracked)
│   │   ├── info.yaml             # index: build time, counts, per-shard sha256
│   │   ├── a.yaml … z.yaml
│   │   ├── digits.yaml
│   │   ├── unicode.yaml
│   │   └── symbols.yaml
│   ├── manifest.yaml             # upstream single file (untracked, downloaded by sync)
│   ├── manifest-override.yaml    # kept as-is from upstream
│   ├── schema.yaml               # kept as-is from upstream (entry format)
│   ├── schema.strict.yaml        # kept as-is from upstream
│   ├── missing.md                # kept as-is from upstream (games without save info)
│   └── wiki-malformed.md         # kept as-is from upstream
├── scripts/
│   ├── sync_manifest.py          # download upstream (ETag / sha256 short-circuit)
│   ├── split_manifest.py         # split + write info.yaml + verify round-trip
│   ├── merge_manifest.py         # merge shards back into one file
│   ├── verify_shards.py          # assert shards match info.yaml
│   ├── update.py                 # one-shot: sync → split
│   └── shardlib.py               # shared logic (rule, splitting, merging)
├── examples/pull_shards.py       # consumer example: on-demand sync + sha256 cache
└── .github/workflows/
    ├── sync.yaml                 # scheduled sync → split → commit
    └── check.yaml                # pull-request self-check
```

Files under `data/` map one-to-one onto upstream; only `manifest.yaml` became a `manifest/`
directory. The Rust importer that crawls PCGamingWiki (`src/`, `Cargo.toml`) is intentionally not
vendored here.

## info.yaml fields

`data/manifest/info.yaml` is the only index a client needs to read:

| Field | Type | Meaning |
|---|---|---|
| `formatVersion` | int | index format version |
| `generatedAt` | string | when the data itself last changed (UTC, ISO 8601) |
| `generator` | string | generator identifier |
| `source.repository` / `source.ref` | string | upstream repository and branch |
| `source.url` | string | URL of the upstream single file |
| `source.etag` / `source.lastModified` | string | upstream cache headers, usable with `If-None-Match` |
| `source.sha256` | string | sha256 of the upstream manifest |
| `source.sizeBytes` / `source.lines` | int | upstream file size and line count |
| `manifest.games` | int | total entries |
| `manifest.shards` | int | number of shards |
| `manifest.files` | int | number of files including `info.yaml` |
| `manifest.bytes` | int | sum of all shard sizes |
| `manifest.withSaveTag` | int | entries carrying a `save` tag |
| `manifest.sections` | map | entries per section (`files`, `registry`, `steam`, …) |
| `sharding.rule` / `sharding.description` | string | active rule identifier and description |
| `shards` | list | per-shard table, fields below |
| `shards[].path` | string | relative path, e.g. `a.yaml` |
| `shards[].key` / `shards[].group` | string | shard key; group is `letter` / `digits` / `unicode` / `symbols` |
| `shards[].games` / `shards[].bytes` | int | entries and size of that shard |
| `shards[].sha256` | string | shard digest, enables incremental sync |
| `shards[].first` / `shards[].last` | string | first and last entry name in that shard |

Typical client flow: fetch `info.yaml`, compare `source.sha256` (or `generatedAt`); if nothing
changed, stop — otherwise download only the shards whose `sha256` differs.

Re-splitting identical content does not touch `generatedAt`, so a rebuild never fabricates a change
and `git status` stays clean.

## Consuming the data

Swap `h.yaml` for whichever shard you need:

| Method | URL |
|---|---|
| GitHub Raw | `https://raw.githubusercontent.com/KannaNyaa/ludusavi-manifest-alpha-slices/main/data/manifest/h.yaml` |
| jsDelivr CDN | `https://cdn.jsdelivr.net/gh/KannaNyaa/ludusavi-manifest-alpha-slices@main/data/manifest/h.yaml` |

```bash
# just the games starting with H
curl -O https://raw.githubusercontent.com/KannaNyaa/ludusavi-manifest-alpha-slices/main/data/manifest/h.yaml

# check the index first to see whether an update is needed
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

A complete example with sha256 caching that only downloads changed shards lives in
[`examples/pull_shards.py`](examples/pull_shards.py) (dependency-free, runnable as-is).

If a tool needs the single file back, merge locally:

```bash
python scripts/merge_manifest.py --out manifest.yaml
```

## Automated updates

[`.github/workflows/sync.yaml`](.github/workflows/sync.yaml) runs four times a day
(03:17 / 09:17 / 15:17 / 21:17 UTC):

1. `sync_manifest.py` sends `If-None-Match`; if the ETag still matches, it exits immediately;
2. only on change does it download, then `split_manifest.py` re-splits and rewrites `info.yaml`;
3. the shards are merged back and compared **byte for byte** — any mismatch fails the run;
4. an entry-count drop beyond the threshold (5% by default) is refused, guarding against upstream
   breakage;
5. `verify_shards.py` asserts that shards and `info.yaml` agree exactly;
6. a commit is pushed only when content actually changed.

Manual run: Actions → **Sync** → Run workflow, with optional `force` (ignore the ETag) and
`allow_shrink` (accept a large drop).

## Local development

Python 3.10+ only; splitting and merging have no third-party dependencies:

```bash
python scripts/update.py            # download upstream → split
python scripts/update.py --local    # re-split the existing data/manifest.yaml
python scripts/verify_shards.py     # assert shards match info.yaml
python scripts/merge_manifest.py --out out.yaml        # merge back to one file
```

Useful flags:

| Script | Flag | Effect |
|---|---|---|
| `split_manifest.py` | `--allow-shrink` | accept a large drop in entry count |
| | `--drop-limit` | change the guard threshold (default `0.05`) |
| | `--no-prune` | keep obsolete shard files |
| | `--no-verify` | skip the merge round-trip check |
| `sync_manifest.py` | `--repo` / `--ref` / `--url` | use a different upstream |
| | `--force` | download even when the ETag matches |
| | `--with-missing` | also refresh `data/missing.md` |
| `merge_manifest.py` | `--expect <file>` | compare with a file, fail on mismatch |

### Changing the rule

To use a different partition (two leading letters, for example), edit `shard_for()` in
`scripts/shardlib.py` — the authoritative implementation. Then run
`python scripts/update.py --local`; obsolete shards are pruned automatically. `info.yaml` records
the active rule in its `sharding` section so clients can adapt.

## Data source and license

* Data comes from [PCGamingWiki](https://www.pcgamingwiki.com/) and the Steam API, maintained by
  [mtkennerly/ludusavi-manifest](https://github.com/mtkennerly/ludusavi-manifest). This repository
  only re-shards it.
* Code is released under the [MIT LICENSE](LICENSE). Attribution and licensing of the data itself
  follow the wiki's content license.
* Shards are generated artifacts — **do not edit them by hand**. Fix the wiki instead; upstream
  picks changes up on its own schedule.
