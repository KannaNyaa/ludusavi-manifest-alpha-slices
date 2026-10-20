#!/usr/bin/env python3
"""Download the upstream Ludusavi manifest (mirror of PCGamingWiki data).

Skips the download body when the ETag still matches, and reports whether the
content actually changed so CI can avoid empty commits.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import shardlib as lib

DEFAULT_REPO = "mtkennerly/ludusavi-manifest"
DEFAULT_REF = "master"
DEFAULT_OUT = Path("data/manifest.yaml")
DEFAULT_MISSING = Path("data/missing.md")
META_FILE = Path("data/.sync-meta.json")
INFO_DIR = Path("data/manifest")
USER_AGENT = "ludusavi-manifest-shards (+https://github.com)"

RAW_URL = "https://raw.githubusercontent.com/{repo}/{ref}/{path}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=DEFAULT_REPO, help=f"upstream repository (default {DEFAULT_REPO})")
    ap.add_argument("--ref", default=DEFAULT_REF, help=f"upstream branch/tag (default {DEFAULT_REF})")
    ap.add_argument("--url", default=None, help="override the manifest URL entirely")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="where to write the full manifest")
    ap.add_argument("--with-missing", action="store_true", help="also refresh data/missing.md")
    ap.add_argument("--missing-out", type=Path, default=DEFAULT_MISSING)
    ap.add_argument("--force", action="store_true", help="re-write the file even if unchanged")
    ap.add_argument("--timeout", type=float, default=120.0)
    return ap.parse_args(argv)


def log(msg: str) -> None:
    print(msg, flush=True)


def read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def fetch(url: str, etag: str | None, timeout: float) -> tuple[int, bytes | None, dict]:
    headers = {"User-Agent": USER_AGENT}
    if etag:
        headers["If-None-Match"] = etag
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read(), dict(response.headers)
    except urllib.error.HTTPError as exc:
        if exc.code == 304:
            return 304, None, dict(exc.headers or {})
        raise


def previous_state(out: Path) -> dict:
    """Previous sha/etag, from the local state file or the committed info.yaml."""
    state = read_json(META_FILE)
    if state.get("sha256"):
        return state
    info = lib.read_info_meta(INFO_DIR)
    return {
        "sha256": info.get("source.sha256", ""),
        "etag": info.get("source.etag", ""),
        "url": info.get("source.url", ""),
        "ref": info.get("source.ref", ""),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    url = args.url or RAW_URL.format(repo=args.repo, ref=args.ref, path="data/manifest.yaml")
    prev = previous_state(args.out)
    etag = "" if args.force else (prev.get("etag") or None)

    log(f"fetch  : {url}")
    try:
        status, body, headers = fetch(url, etag, args.timeout)
    except urllib.error.URLError as exc:
        print(f"error: download failed: {exc}", file=sys.stderr)
        return 2

    changed = False
    remote_etag = headers.get("ETag", "") or ""
    last_modified = headers.get("Last-Modified", "") or ""
    digest = prev.get("sha256", "")

    if status == 304:
        log("status : 304 not modified (etag matched)")
    elif body is not None:
        digest = lib.sha256_bytes(body)
        if digest == prev.get("sha256") and args.out.exists() and not args.force:
            log(f"status : unchanged content (sha256 {digest[:12]}...)")
        else:
            args.out.parent.mkdir(parents=True, exist_ok=True)
            tmp = args.out.with_name(args.out.name + ".tmp")
            tmp.write_bytes(body)
            os.replace(tmp, args.out)
            changed = True
            log(f"status : updated ({len(body):,} bytes, sha256 {digest[:12]}...)")

    if args.with_missing:
        missing_url = RAW_URL.format(repo=args.repo, ref=args.ref, path="data/missing.md")
        try:
            m_status, m_body, _ = fetch(missing_url, None, args.timeout)
            if m_body is not None:
                if lib.write_if_changed(args.missing_out, m_body):
                    changed = True
                    log(f"missing: updated ({len(m_body):,} bytes)")
                else:
                    log("missing: unchanged")
        except urllib.error.URLError as exc:
            log(f"missing: skipped ({exc})")

    META_FILE.parent.mkdir(parents=True, exist_ok=True)
    META_FILE.write_text(
        json.dumps(
            {
                "repository": args.repo,
                "ref": args.ref,
                "url": url,
                "etag": remote_etag or prev.get("etag", ""),
                "lastModified": last_modified or prev.get("lastModified", ""),
                "sha256": digest,
                "sizeBytes": args.out.stat().st_size if args.out.exists() else 0,
                "fetchedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    print(f"changed={'true' if changed else 'false'}")
    print(f"sha256={digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
