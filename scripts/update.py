#!/usr/bin/env python3
"""One-shot pipeline: sync upstream -> split into shards.

    python scripts/update.py            # normal run (used by CI)
    python scripts/update.py --local    # re-split the local data/manifest.yaml
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--local", action="store_true", help="skip the download, reuse data/manifest.yaml")
    ap.add_argument("--force", action="store_true", help="download even if the ETag matches")
    ap.add_argument("--allow-shrink", action="store_true", help="accept a large drop in entry count")
    ap.add_argument("--repo", default=None, help="upstream repository (owner/name)")
    ap.add_argument("--ref", default=None, help="upstream branch or tag")
    return ap.parse_args(argv)


def run(script: str, *extra: str) -> int:
    cmd = [sys.executable, str(SCRIPTS / script), *extra]
    print(f"\n$ {' '.join(cmd[1:])}", flush=True)
    return subprocess.call(cmd)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.local:
        extra: list[str] = ["--with-missing"]
        if args.force:
            extra.append("--force")
        if args.repo:
            extra += ["--repo", args.repo]
        if args.ref:
            extra += ["--ref", args.ref]
        code = run("sync_manifest.py", *extra)
        if code != 0:
            return code

    split_args: list[str] = []
    if args.allow_shrink:
        split_args.append("--allow-shrink")
    code = run("split_manifest.py", *split_args)
    if code != 0:
        return code

    print("\ndone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
