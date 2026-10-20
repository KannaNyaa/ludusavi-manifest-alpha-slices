#!/usr/bin/env python3
"""示例：按需同步分片，并利用 info.yaml 的 sha256 做增量更新。

    python examples/pull_shards.py --base ./data/manifest --cache ./cache h digits
    python examples/pull_shards.py --base https://raw.githubusercontent.com/KannaNyaa/ludusavi-manifest-alpha-slices/main/data/manifest --cache ./cache "Hades II"

第一次运行会下载 info.yaml 和所需分片；之后只拉 sha256 变化的分片。
本脚本不依赖任何 YAML 库（只做下载、校验、缓存和条目计数），
真正解析条目时用你项目里已有的 YAML 库读取缓存下来的分片即可。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path


def is_ascii_letter(ch: str) -> bool:
    return "a" <= ch <= "z" or "A" <= ch <= "Z"


def shard_for(name: str) -> str:
    """与 scripts/shardlib.py 完全一致的分片规则。"""
    s = name.strip()
    if not s:
        return "symbols.yaml"
    first = s[0]
    if is_ascii_letter(first):
        return f"{first.lower()}.yaml"
    if first.isascii() and first.isdigit():
        return "digits.yaml"
    if first.isalnum():
        return "unicode.yaml"
    return "symbols.yaml"


def fetch(base: str, name: str) -> bytes:
    if "://" in base:
        url = f"{base}/{name}"
        request = urllib.request.Request(url, headers={"User-Agent": "manifest-shards-example"})
        with urllib.request.urlopen(request, timeout=60) as response:
            return response.read()
    return (Path(base) / name).read_bytes()


def read_info(raw: bytes) -> dict:
    """只取 info.yaml 里需要的字段，避免额外依赖。"""
    meta: dict[str, str] = {}
    shards: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    section = ""
    in_shards = False
    for line in raw.decode("utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if not line[0].isspace():
            section = line.split(":", 1)[0].strip()
            in_shards = section == "shards"
            rest = line.split(":", 1)[1].strip() if ":" in line else ""
            if rest:
                meta[section] = rest.strip("'\"")
            continue
        if in_shards:
            item = line.strip()
            if item.startswith("- "):
                current = {}
                shards.append(current)
                item = item[2:]
            if current is not None and ":" in item:
                key, value = item.split(":", 1)
                current[key.strip()] = value.strip().strip("'\"")
        elif line.startswith("  ") and not line.startswith("    "):
            key, _, value = line[2:].partition(":")
            if value.strip():
                meta[f"{section}.{key.strip()}"] = value.strip().strip("'\"")
    return {"meta": meta, "shards": shards}


def count_games(raw: bytes) -> int:
    """统计顶层键数量（分片顶层就是 游戏名: 条目）。"""
    total = 0
    for line in raw.decode("utf-8").splitlines():
        if not line or line[0] in " \t#-":
            continue
        if line.rstrip().endswith(":"):
            total += 1
    return total


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--base", required=True, help="分片目录 URL，或本地 data/manifest 路径")
    ap.add_argument("--cache", type=Path, default=Path("cache"), help="本地缓存目录")
    ap.add_argument("targets", nargs="+", help="字母（h）、特殊分片名（digits/unicode/symbols）或游戏名")
    args = ap.parse_args()

    base = args.base.rstrip("/")
    cache: Path = args.cache
    cache.mkdir(parents=True, exist_ok=True)

    info_raw = fetch(base, "info.yaml")
    info = read_info(info_raw)
    (cache / "info.yaml").write_bytes(info_raw)
    print(f"info : {info['meta'].get('manifest.games', '?')} games, built {info['meta'].get('generatedAt', '?')}")

    known = {row["path"]: row.get("sha256", "") for row in info["shards"]}

    wanted: set[str] = set()
    for target in args.targets:
        if target in known:
            wanted.add(target)
        elif len(target) == 1:
            wanted.add(f"{target.lower()}.yaml")
        elif f"{target.lower()}.yaml" in known:
            wanted.add(f"{target.lower()}.yaml")  # e.g. "digits" / "unicode" / "symbols"
        else:
            wanted.add(shard_for(target))

    total = 0
    for shard in sorted(wanted):
        if shard not in known:
            print(f"skip : {shard} is not listed in info.yaml")
            continue
        local = cache / shard
        remote_sha = known[shard]
        if local.exists() and hashlib.sha256(local.read_bytes()).hexdigest() == remote_sha:
            print(f"keep : {shard} (sha256 unchanged)")
        else:
            data = fetch(base, shard)
            digest = hashlib.sha256(data).hexdigest()
            if remote_sha and digest != remote_sha:
                print(f"warn : {shard} sha256 {digest[:12]} != info.yaml {remote_sha[:12]}")
            local.write_bytes(data)
            print(f"get  : {shard} ({len(data):,} bytes)")
        games = count_games(local.read_bytes())
        total += games
        print(f"       {shard}: {games:,} games")

    (cache / "summary.json").write_text(
        json.dumps({"generatedAt": info["meta"].get("generatedAt", ""), "games": total}, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"\n{total:,} games cached in {cache}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
