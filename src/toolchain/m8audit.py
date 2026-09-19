#!/usr/bin/env python3
"""Audit printable M8 .mb glyph streams.

This is intentionally stricter than "is printable". It checks the same source
contract the C runtime cares about: whitespace is ignored, every source cell is
graphic ASCII, and every source cell decodes to a known classic or M8 operation
at its address. It also rejects old decimal memory-image shapes so generated
userland cannot quietly slide back into numeric dumps.
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

XLAT1 = (
    "+b(29e*j1VMEKLyC})8&m#~W>qxdRp0wkrUo[D7,XTcA\"lI\\"
    "v%{gJh4G\\-=O@5`_3i<?Z';FNQuY]szf$!BS/|t:Pn6^Ha"
)
CLASSIC_OPS = set("ji*p/<vo")
EXT_OPS = set("@!?=~#+-[]:^$`")
VALID_OPS = CLASSIC_OPS | EXT_OPS
OLD_RAW_HEADER = "# M8 raw memory image"
DECIMAL_LINE_RE = re.compile(r"^[+-]?(?:0|[1-9][0-9]*)$")


@dataclass
class AuditResult:
    path: Path
    cells: int
    classic_cells: int
    extension_cells: int


def collect_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for path in paths:
        if path.is_dir():
            out.extend(sorted(path.rglob("*.mb")))
        else:
            out.append(path)
    return out


def looks_like_decimal_dump(text: str) -> bool:
    if text.startswith(OLD_RAW_HEADER):
        return True
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if len(lines) < 2:
        return False
    # Allow a leading comment only for detecting the old shape. The runtime does
    # not accept comments in strict .mb source.
    payload = [line for line in lines if not line.startswith("#")]
    return len(payload) >= 2 and all(DECIMAL_LINE_RE.match(line) for line in payload)


def audit_one(path: Path) -> AuditResult:
    text = path.read_text()
    if looks_like_decimal_dump(text):
        raise ValueError("looks like an old decimal M8 memory image")

    cells = 0
    classic = 0
    ext = 0
    for line_no, line in enumerate(text.splitlines(True), 1):
        for col, ch in enumerate(line, 1):
            if ch.isspace():
                continue
            o = ord(ch)
            if o < 33 or o > 126:
                raise ValueError(f"non-graphic character U+{o:04X} at line {line_no}, column {col}")
            op = XLAT1[(o - 33 + cells) % 94]
            if op not in VALID_OPS:
                raise ValueError(
                    f"invalid decoded op {op!r} from glyph {ch!r} at cell {cells} "
                    f"line {line_no}, column {col}"
                )
            if op in CLASSIC_OPS:
                classic += 1
            else:
                ext += 1
            cells += 1

    if cells == 0:
        raise ValueError("empty glyph source")
    return AuditResult(path=path, cells=cells, classic_cells=classic, extension_cells=ext)


def main() -> int:
    parser = argparse.ArgumentParser(description="audit printable M8 .mb glyph streams")
    parser.add_argument("paths", nargs="+", type=Path, help=".mb file or directory containing .mb files")
    parser.add_argument("--quiet", action="store_true", help="print only errors")
    args = parser.parse_args()

    if len(XLAT1) != 94:
        print(f"internal error: XLAT1 has length {len(XLAT1)}, expected 94", file=sys.stderr)
        return 99

    paths = collect_paths(args.paths)
    if not paths:
        print("m8audit: no .mb files found", file=sys.stderr)
        return 2

    ok = True
    results: list[AuditResult] = []
    for path in paths:
        try:
            results.append(audit_one(path))
        except Exception as exc:
            ok = False
            print(f"m8audit: {path}: {exc}", file=sys.stderr)

    if ok and not args.quiet:
        for r in results:
            print(
                f"{r.path}: ok cells={r.cells} "
                f"classic={r.classic_cells} ext={r.extension_cells}"
            )
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
