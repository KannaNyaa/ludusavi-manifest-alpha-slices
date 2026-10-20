#!/usr/bin/env python3
"""Rebuild the full single-file manifest from the shards.

Useful for tools that still expect one ``manifest.yaml``, and as an integrity
check: the merged output should be byte-identical to the upstream file.
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
    ap.add_argument("--dir", type=Path, default=DEFAULT_DIR, help="shard directory")
    ap.add_argument("--out", type=Path, default=None, help="output file (stdout when omitted)")
    ap.add_argument("--expect", type=Path, default=None, help="compare the result with this file")
    ap.add_argument("--quiet", action="store_true")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.dir.is_dir():
        print(f"error: no shard directory at {args.dir}", file=sys.stderr)
        return 2

    merged = lib.merge_shards(args.dir)
    _, entries = lib.iter_entries(merged.decode("utf-8"))
    if not args.quiet:
        print(
            f"merged {len(lib.iter_shard_files(args.dir))} shard(s), "
            f"{len(entries):,} games, {len(merged):,} bytes",
            file=sys.stderr,
        )

    if args.expect:
        expected = args.expect.read_bytes()
        if merged != expected:
            print(f"error: merged output differs from {args.expect}", file=sys.stderr)
            _, expected_entries = lib.iter_entries(expected.decode("utf-8"))
            print(
                f"       games: merged={len(entries):,} expected={len(expected_entries):,}",
                file=sys.stderr,
            )
            return 3
        if not args.quiet:
            print(f"ok: identical to {args.expect}", file=sys.stderr)

    if args.out:
        changed = lib.write_if_changed(args.out, merged)
        if not args.quiet:
            print(f"{'wrote' if changed else 'unchanged'}: {args.out}", file=sys.stderr)
    else:
        sys.stdout.buffer.write(merged)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
