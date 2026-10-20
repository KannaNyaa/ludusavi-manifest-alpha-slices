#!/usr/bin/env python3
"""Check that the shards on disk agree with info.yaml.

Catches the failures that matter for downstream consumers:
  * a shard whose content no longer matches the recorded sha256/size/count,
  * a shard missing from info.yaml (or listed but absent),
  * a game sitting in the wrong shard,
  * duplicated game names across shards,
  * an entry count that disagrees with info.yaml.

Exits non-zero on the first category of problem found, so CI can gate on it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import shardlib as lib

DEFAULT_DIR = Path("data/manifest")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR)
    ap.add_argument("--quiet", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_dir: Path = args.dir
    if not manifest_dir.is_dir():
        print(f"error: no shard directory at {manifest_dir}", file=sys.stderr)
        return 2

    meta = lib.read_info_meta(manifest_dir)
    declared = lib.read_info_shards(manifest_dir)
    if not declared:
        print("error: info.yaml has no shard table", file=sys.stderr)
        return 2

    problems: list[str] = []
    declared_paths = set()
    seen_names: dict[str, str] = {}
    total = 0
    total_bytes = 0

    for row in declared:
        rel = row.get("path", "")
        path = manifest_dir / rel
        declared_paths.add(rel)
        if not path.exists():
            problems.append(f"{rel}: listed in info.yaml but missing on disk")
            continue
        data = path.read_bytes()
        total_bytes += len(data)
        if row.get("bytes") and int(row["bytes"]) != len(data):
            problems.append(f"{rel}: bytes {len(data):,} != info.yaml {int(row['bytes']):,}")
        digest = lib.sha256_bytes(data)
        if row.get("sha256") and row["sha256"] != digest:
            problems.append(f"{rel}: sha256 mismatch")

        _, entries = lib.iter_entries(data.decode("utf-8"))
        total += len(entries)
        if row.get("games") and int(row["games"]) != len(entries):
            problems.append(f"{rel}: {len(entries):,} games != info.yaml {int(row['games']):,}")
        if entries:
            expected = lib.shard_for(entries[0].name).path
            if expected != rel:
                problems.append(f"{rel}: first entry '{entries[0].name}' belongs in {expected}")
        for entry in entries:
            if not entry.name:
                problems.append(f"{rel}: entry with an empty name")
                continue
            actual = lib.shard_for(entry.name).path
            if actual != rel:
                problems.append(f"{rel}: '{entry.name}' belongs in {actual}")
            other = seen_names.get(entry.name)
            if other:
                problems.append(f"duplicate name '{entry.name}' in {rel} and {other}")
            else:
                seen_names[entry.name] = rel

    for path in lib.iter_shard_files(manifest_dir):
        rel = path.relative_to(manifest_dir).as_posix()
        if rel not in declared_paths:
            problems.append(f"{rel}: on disk but not listed in info.yaml")

    expected_total = meta.get("manifest.games", "")
    if expected_total.isdigit() and int(expected_total) != total:
        problems.append(f"total games {total:,} != info.yaml {int(expected_total):,}")

    if not args.quiet:
        print(f"shards : {len(declared_paths)}")
        print(f"games  : {total:,}")
        print(f"bytes  : {total_bytes:,}")

    if problems:
        print(f"\n{len(problems)} problem(s):", file=sys.stderr)
        for problem in problems[:40]:
            print(f"  - {problem}", file=sys.stderr)
        if len(problems) > 40:
            print(f"  ... and {len(problems) - 40} more", file=sys.stderr)
        return 1

    if not args.quiet:
        print("ok: every shard matches info.yaml")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
