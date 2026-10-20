"""Shared helpers for splitting the Ludusavi manifest into per-prefix shards.

The manifest is a single YAML mapping whose keys are game names. Instead of
parsing and re-serializing it (slow, and it would rewrite quoting/escaping),
we split it *textually*: a top-level key line starts in column 0 and the rest
of the entry is indented. That keeps every shard byte-for-byte identical to
the corresponding slice of the source file, so merging the shards back
reproduces the original manifest exactly.

Zero third-party dependencies on purpose: this runs in CI and locally.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

FORMAT_VERSION = 1
GENERATOR = "ludusavi-manifest-shards"
INFO_FILENAME = "info.yaml"

DIGITS_SHARD = "digits.yaml"
SYMBOLS_SHARD = "symbols.yaml"
UNICODE_SHARD = "unicode.yaml"


# ---------------------------------------------------------------------------
# Naming rule
# ---------------------------------------------------------------------------

def _is_ascii_letter(ch: str) -> bool:
    return "a" <= ch <= "z" or "A" <= ch <= "Z"


def _is_ascii_digit(ch: str) -> bool:
    return "0" <= ch <= "9"


@dataclass(frozen=True)
class Shard:
    """Where a game belongs and how the shard is labelled."""

    path: str  # relative posix path inside the manifest directory
    key: str  # "A", "0-9", "UNICODE", "SYMBOLS"
    group: str  # "letter" | "digits" | "unicode" | "symbols"


def shard_for(name: str) -> Shard:
    """Map a game name to its shard by its first character.

    Rule (kept deliberately trivial so any client can re-implement it):

    * first char is an ASCII letter -> ``<letter>.yaml`` (26 files);
    * first char is an ASCII digit -> ``digits.yaml``;
    * first char is a non-ASCII letter/digit -> ``unicode.yaml``;
    * anything else (punctuation, symbols) -> ``symbols.yaml``.
    """
    s = name.strip()
    if not s:
        return Shard(SYMBOLS_SHARD, "SYMBOLS", "symbols")

    first = s[0]
    if _is_ascii_letter(first):
        letter = first.lower()
        return Shard(f"{letter}.yaml", letter.upper(), "letter")
    if _is_ascii_digit(first):
        return Shard(DIGITS_SHARD, "0-9", "digits")
    if first.isalnum():
        return Shard(UNICODE_SHARD, "UNICODE", "unicode")
    return Shard(SYMBOLS_SHARD, "SYMBOLS", "symbols")


# ---------------------------------------------------------------------------
# YAML key decoding (only used for classification and for reporting names)
# ---------------------------------------------------------------------------

_ESCAPES = {
    "0": "\0",
    "a": "\a",
    "b": "\b",
    "t": "\t",
    "\t": "\t",
    "n": "\n",
    "v": "\v",
    "f": "\f",
    "r": "\r",
    "e": "\x1b",
    " ": " ",
    '"': '"',
    "/": "/",
    "\\": "\\",
    "N": "\x85",
    "_": "\xa0",
    "L": "\u2028",
    "P": "\u2029",
}


def _decode_double_quoted(body: str) -> str:
    out: list[str] = []
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch != "\\" or i + 1 >= n:
            out.append(ch)
            i += 1
            continue
        esc = body[i + 1]
        if esc in _ESCAPES:
            out.append(_ESCAPES[esc])
            i += 2
        elif esc in "xuU":
            width = {"x": 2, "u": 4, "U": 8}[esc]
            digits = body[i + 2 : i + 2 + width]
            try:
                out.append(chr(int(digits, 16)))
                i += 2 + width
            except ValueError:
                out.append(ch)
                i += 1
        else:
            out.append(esc)
            i += 2
    return "".join(out)


def decode_key(raw: str) -> str:
    """Decode a raw top-level mapping key line (``"Foo Bar":``) into ``Foo Bar``."""
    k = raw.strip()
    if k.endswith(":"):
        k = k[:-1].rstrip()
    if len(k) >= 2 and k[0] == '"' and k[-1] == '"':
        return _decode_double_quoted(k[1:-1])
    if len(k) >= 2 and k[0] == "'" and k[-1] == "'":
        return k[1:-1].replace("''", "'")
    return k


def quote(value: str) -> str:
    """Render a string as a safe YAML double-quoted scalar (JSON is a subset)."""
    return json.dumps(value, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------

@dataclass
class Entry:
    name: str
    raw_key: str  # the exact key text from the source, without the newline
    text: str  # whole block, including the key line and its indented body
    sections: frozenset[str]
    has_save_tag: bool


_SECTION_RE = re.compile(r"^  ([A-Za-z][A-Za-z0-9_]*):")


def _is_key_line(line: str) -> bool:
    if not line or not line.strip():
        return False
    head = line[0]
    if head in (" ", "\t", "#", "-"):
        return False
    stripped = line.rstrip("\r\n")
    return stripped.endswith(":") and not stripped.startswith(("{", "["))


def iter_entries(text: str) -> tuple[str, list[Entry]]:
    """Split manifest text into a preamble and a list of entries.

    The preamble holds anything before the first key (typically ``---``).
    """
    preamble_parts: list[str] = []
    entries: list[Entry] = []

    cur_key: str | None = None
    cur_parts: list[str] = []
    cur_sections: set[str] = set()
    cur_save = False

    def flush() -> None:
        nonlocal cur_key, cur_parts, cur_sections, cur_save
        if cur_key is not None:
            entries.append(
                Entry(
                    name=decode_key(cur_key),
                    raw_key=cur_key,
                    text="".join(cur_parts),
                    sections=frozenset(cur_sections),
                    has_save_tag=cur_save,
                )
            )
        cur_key = None
        cur_parts = []
        cur_sections = set()
        cur_save = False

    for line in text.splitlines(keepends=True):
        if _is_key_line(line):
            flush()
            cur_key = line.rstrip("\r\n")
            cur_parts = [line]
            continue
        if cur_key is None:
            preamble_parts.append(line)
            continue
        cur_parts.append(line)
        m = _SECTION_RE.match(line)
        if m:
            cur_sections.add(m.group(1))
        elif "- save" in line and line.strip() in ("- save", "- save #"):
            cur_save = True

    flush()
    return "".join(preamble_parts), entries


def detect_eol(preamble: str) -> str:
    return "\r\n" if "\r\n" in preamble else "\n"


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_if_changed(path: Path, data: bytes) -> bool:
    """Write ``data`` unless the file already has identical content."""
    if path.exists():
        try:
            if path.stat().st_size == len(data) and path.read_bytes() == data:
                return False
        except OSError:
            pass
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return True


def iter_shard_files(manifest_dir: Path) -> list[Path]:
    """All shard files in a manifest directory, in a stable order."""
    files = [
        p
        for p in manifest_dir.rglob("*.yaml")
        if p.name != INFO_FILENAME and p.is_file()
    ]
    return sorted(files, key=lambda p: p.relative_to(manifest_dir).as_posix())


def read_info_meta(manifest_dir: Path) -> dict[str, str]:
    """Best-effort read of the scalar fields from info.yaml.

    Deliberately line-based: this module has no YAML parser, and info.yaml is
    written by :mod:`split_manifest`, so the shape is known.
    """
    path = manifest_dir / INFO_FILENAME
    meta: dict[str, str] = {}
    if not path.exists():
        return meta
    section = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if not line[0].isspace():
            key, _, rest = line.partition(":")
            section = key.strip()
            rest = rest.strip()
            if rest:
                meta[section] = _unquote(rest)
            continue
        if line.startswith("  ") and not line.startswith("    ") and not line.startswith("  - "):
            key, _, rest = line[2:].partition(":")
            rest = rest.strip()
            if rest:
                meta[f"{section}.{key.strip()}"] = _unquote(rest)
    return meta


def read_info_shards(manifest_dir: Path) -> list[dict[str, str]]:
    """Parse the ``shards:`` table from info.yaml."""
    path = manifest_dir / INFO_FILENAME
    if not path.exists():
        return []
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_shards = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        if not line[0].isspace():
            in_shards = line.strip() == "shards:"
            continue
        if not in_shards:
            continue
        stripped = line.strip()
        if stripped.startswith("- "):
            current = {}
            rows.append(current)
            stripped = stripped[2:]
        if current is None:
            continue
        key, _, rest = stripped.partition(":")
        current[key.strip()] = _unquote(rest.strip())
    return rows


def _unquote(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == '"' and value[-1] == '"':
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value[1:-1]
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value


# ---------------------------------------------------------------------------
# Merging
# ---------------------------------------------------------------------------

def merge_shards(manifest_dir: Path, *, preamble: str = "---\n") -> bytes:
    """Rebuild the full manifest from a shard directory.

    Entries are sorted by their decoded name (UTF-8 byte order), which is the
    order the upstream manifest uses, so the result is byte-identical to the
    source file.
    """
    entries: list[tuple[bytes, str]] = []
    for path in iter_shard_files(manifest_dir):
        text = path.read_text(encoding="utf-8")
        _, items = iter_entries(text)
        for item in items:
            entries.append((item.name.encode("utf-8"), item.text))
    entries.sort(key=lambda pair: pair[0])
    body = "".join(text for _, text in entries)
    return (preamble + body).encode("utf-8")
