#!/usr/bin/env python3
"""Split the monolithic Ludusavi manifest into one file per leading character.

Input : data/manifest.yaml (upstream layout, ~17 MB / ~53k entries)
Output: data/manifest/<letter>.yaml, digits.yaml, unicode.yaml, symbols.yaml
        data/manifest/info.yaml   (build metadata + per-shard counts/digests)

The split is textual, so every shard is byte-identical to the corresponding
slice of the source. After writing, the shards are merged again and compared
to the source file; a mismatch aborts the run.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import shardlib as lib

DEFAULT_SOURCE = Path("data/manifest.yaml")
DEFAULT_OUT = Path("data/manifest")
META_FILE = Path("data/.sync-meta.json")
DEFAULT_DROP_LIMIT = 0.05


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE, help="full manifest to split")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="directory for the shards")
    ap.add_argument("--no-prune", action="store_true", help="keep stale shard files")
    ap.add_argument("--no-verify", action="store_true", help="skip the merge round-trip check")
    ap.add_argument("--allow-shrink", action="store_true", help="accept a large drop in entry count")
    ap.add_argument("--drop-limit", type=float, default=DEFAULT_DROP_LIMIT, help="allowed relative drop (default 0.05)")
    ap.add_argument("--min-games", type=int, default=0, help="abort if fewer entries than this")
    ap.add_argument("--quiet", action="store_true")
    return ap.parse_args(argv)


def log(msg: str, quiet: bool = False) -> None:
    if not quiet:
        print(msg, flush=True)


def read_source_meta() -> dict:
    if not META_FILE.exists():
        return {}
    try:
        return json.loads(META_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def previous_game_count(out_dir: Path) -> int | None:
    meta = lib.read_info_meta(out_dir)
    raw = meta.get("manifest.games") or meta.get("totals.games")
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def build_info(
    *,
    source_bytes: bytes,
    preamble: str,
    groups: dict[str, list[lib.Entry]],
    source_meta: dict,
    eol: str,
) -> tuple[dict, list[dict]]:
    total_games = sum(len(v) for v in groups.values())
    section_counts: dict[str, int] = {}
    with_save = 0
    for entries in groups.values():
        for entry in entries:
            for section in entry.sections:
                section_counts[section] = section_counts.get(section, 0) + 1
            if entry.has_save_tag:
                with_save += 1

    shard_rows: list[dict] = []
    for path, entries in groups.items():
        if not entries:
            continue
        shard = lib.shard_for(entries[0].name)
        body = (preamble + "".join(e.text for e in entries)).encode("utf-8")
        names = [e.name for e in entries]
        shard_rows.append(
            {
                "path": path,
                "key": shard.key,
                "group": shard.group,
                "games": len(entries),
                "bytes": len(body),
                "sha256": lib.sha256_bytes(body),
                "first": names[0],
                "last": names[-1],
            }
        )
    shard_rows.sort(key=lambda r: r["path"])

    repo = source_meta.get("repository", "mtkennerly/ludusavi-manifest")
    ref = source_meta.get("ref", "master")
    info = {
        "formatVersion": lib.FORMAT_VERSION,
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "generator": lib.GENERATOR,
        "source": {
            "repository": repo,
            "ref": ref,
            "file": "data/manifest.yaml",
            "url": source_meta.get(
                "url", f"https://raw.githubusercontent.com/{repo}/{ref}/data/manifest.yaml"
            ),
            "etag": source_meta.get("etag", ""),
            "lastModified": source_meta.get("lastModified", ""),
            "sha256": lib.sha256_bytes(source_bytes),
            "sizeBytes": len(source_bytes),
            "lines": source_bytes.count(eol.encode("utf-8")) if eol else 0,
        },
        "manifest": {
            "games": total_games,
            "shards": len(shard_rows),
            "files": len(shard_rows) + 1,
            "bytes": sum(r["bytes"] for r in shard_rows),
            "sections": dict(sorted(section_counts.items())),
            "withSaveTag": with_save,
        },
        "sharding": {
            "rule": "first-character",
            "description": (
                "ASCII letter -> <letter>.yaml; ASCII digit -> digits.yaml; "
                "non-ASCII letter/digit -> unicode.yaml; other -> symbols.yaml"
            ),
            "files": len(shard_rows) + 1,
        },
        "shards": shard_rows,
    }
    return info, shard_rows


def render_info(info: dict) -> str:
    q = lib.quote
    src = info["source"]
    man = info["manifest"]
    sharding = info["sharding"]

    out: list[str] = []
    out.append("# Ludusavi manifest shard index - generated file, do not edit.")
    out.append("# https://github.com/mtkennerly/ludusavi-manifest for the source data.")
    out.append(f"formatVersion: {info['formatVersion']}")
    out.append(f"generatedAt: {q(info['generatedAt'])}")
    out.append(f"generator: {q(info['generator'])}")
    out.append("")
    out.append("source:")
    for key in ("repository", "ref", "file", "url", "etag", "lastModified", "sha256"):
        out.append(f"  {key}: {q(src[key])}")
    out.append(f"  sizeBytes: {src['sizeBytes']}")
    out.append(f"  lines: {src['lines']}")
    out.append("")
    out.append("manifest:")
    out.append(f"  games: {man['games']}")
    out.append(f"  shards: {man['shards']}")
    out.append(f"  files: {man['files']}")
    out.append(f"  bytes: {man['bytes']}")
    out.append(f"  withSaveTag: {man['withSaveTag']}")
    out.append("  sections:")
    for name, count in man["sections"].items():
        out.append(f"    {name}: {count}")
    out.append("")
    out.append("sharding:")
    out.append(f"  rule: {q(sharding['rule'])}")
    out.append(f"  description: {q(sharding['description'])}")
    out.append(f"  files: {sharding['files']}")
    out.append("")
    out.append("shards:")
    for row in info["shards"]:
        out.append(f"  - path: {q(row['path'])}")
        out.append(f"    key: {q(row['key'])}")
        out.append(f"    group: {q(row['group'])}")
        out.append(f"    games: {row['games']}")
        out.append(f"    bytes: {row['bytes']}")
        out.append(f"    sha256: {q(row['sha256'])}")
        out.append(f"    first: {q(row['first'])}")
        out.append(f"    last: {q(row['last'])}")
    out.append("")
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.source.exists():
        print(f"error: source manifest not found: {args.source}", file=sys.stderr)
        print("hint: run scripts/sync_manifest.py first (or scripts/update.py)", file=sys.stderr)
        return 2

    raw = args.source.read_bytes()
    text = raw.decode("utf-8")
    preamble, entries = lib.iter_entries(text)
    if not entries:
        print(f"error: no entries found in {args.source}", file=sys.stderr)
        return 2
    eol = lib.detect_eol(preamble or text[:4096])
    if not preamble.endswith(eol) and preamble:
        preamble += eol

    log(f"source : {args.source} ({len(raw):,} bytes, {len(entries):,} games)")

    # --- guards -----------------------------------------------------------
    if args.min_games and len(entries) < args.min_games:
        print(f"error: {len(entries):,} games < --min-games {args.min_games:,}", file=sys.stderr)
        return 3
    prev = previous_game_count(args.out)
    if prev and not args.allow_shrink:
        limit = int(prev * (1 - args.drop_limit))
        if len(entries) < limit:
            print(
                f"error: entry count dropped from {prev:,} to {len(entries):,} "
                f"(more than {args.drop_limit:.0%}); refusing to publish",
                file=sys.stderr,
            )
            print("hint: re-run with --allow-shrink if the drop is expected", file=sys.stderr)
            return 3

    # --- group ------------------------------------------------------------
    groups: dict[str, list[lib.Entry]] = {}
    for entry in entries:
        shard = lib.shard_for(entry.name)
        groups.setdefault(shard.path, []).append(entry)

    # --- write ------------------------------------------------------------
    args.out.mkdir(parents=True, exist_ok=True)
    produced = set(groups)
    changed: list[str] = []
    for path, items in sorted(groups.items()):
        body = (preamble + "".join(e.text for e in items)).encode("utf-8")
        if lib.write_if_changed(args.out / path, body):
            changed.append(path)
    if changed:
        log(f"wrote  : {len(changed)} shard(s) changed: {', '.join(changed)}")
    else:
        log("wrote  : no shard content changed")

    if not args.no_prune:
        stale = [
            p
            for p in args.out.glob("*.yaml")
            if p.is_file() and p.name != lib.INFO_FILENAME and p.name not in produced
        ]
        for p in stale:
            p.unlink()
            log(f"pruned : {p.name}")

    # --- verify round-trip ------------------------------------------------
    if not args.no_verify:
        merged = lib.merge_shards(args.out, preamble=preamble)
        if merged == raw:
            log("verify : shards merge back to a byte-identical manifest")
        else:
            rebuilt = merged.decode("utf-8", "replace")
            _, rebuilt_entries = lib.iter_entries(rebuilt)
            detail = []
            if len(rebuilt_entries) != len(entries):
                detail.append(f"games {len(entries):,} -> {len(rebuilt_entries):,}")
            src_map = {e.raw_key: e.text for e in entries}
            new_map = {e.raw_key: e.text for e in rebuilt_entries}
            lost = sorted(set(src_map) - set(new_map))[:3]
            extra = sorted(set(new_map) - set(src_map))[:3]
            if lost:
                detail.append(f"missing e.g. {lost}")
            if extra:
                detail.append(f"unexpected e.g. {extra}")
            if not detail:
                detail.append("content differs (whitespace or ordering)")
            print(f"error: round-trip check failed: {'; '.join(detail)}", file=sys.stderr)
            return 4

    # --- info.yaml --------------------------------------------------------
    info, shard_rows = build_info(
        source_bytes=raw,
        preamble=preamble,
        groups=groups,
        source_meta=read_source_meta(),
        eol=eol,
    )

    # `generatedAt` marks when this data last changed, not when the script last
    # ran: an identical re-split keeps the old timestamp so rebuilds stay clean.
    info_path = args.out / lib.INFO_FILENAME
    previous = lib.read_info_meta(args.out)
    kept_timestamp = False
    if previous.get("generatedAt") and previous.get("source.sha256") == info["source"]["sha256"]:
        candidate = render_info({**info, "generatedAt": previous["generatedAt"]})
        if info_path.exists() and candidate == info_path.read_text(encoding="utf-8"):
            info["generatedAt"] = previous["generatedAt"]
            kept_timestamp = True

    info_text = render_info(info)
    if lib.write_if_changed(info_path, info_text.encode("utf-8")):
        log(f"info   : updated {info_path}")
    elif kept_timestamp:
        log(f"info   : unchanged (generatedAt kept at {info['generatedAt']})")
    else:
        log("info   : unchanged")

    # --- summary ----------------------------------------------------------
    letters = [r for r in shard_rows if r["group"] == "letter"]
    specials = {r["group"]: r for r in shard_rows if r["group"] != "letter"}
    log("")
    log(f"games  : {info['manifest']['games']:,}")
    log(f"shards : {len(shard_rows)} (+1 info.yaml)")
    log(f"letters: {len(letters)} files, {sum(r['games'] for r in letters):,} games")
    for group in ("digits", "unicode", "symbols"):
        row = specials.get(group)
        if row:
            log(f"  {row['path']:<12} {row['games']:>7,} games, {row['bytes']:>10,} bytes")
    largest = max(shard_rows, key=lambda r: r["bytes"])
    log(f"largest: {largest['path']} ({largest['bytes']:,} bytes, {largest['games']:,} games)")

    print(f"changed={'true' if changed else 'false'}")
    print(f"games={info['manifest']['games']}")
    print(f"shards={len(shard_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
