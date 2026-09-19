#!/usr/bin/env python3
"""Print the printable VM words at selected addresses as glyphs."""
from __future__ import annotations
import sys
from pathlib import Path

if len(sys.argv) < 2:
    print(f"usage: {sys.argv[0]} IMAGE.m8i [addr ...]", file=sys.stderr)
    raise SystemExit(2)

words = []
for line in Path(sys.argv[1]).read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#"):
        words.append(int(line))

if len(sys.argv) > 2:
    addrs = [int(x, 0) for x in sys.argv[2:]]
else:
    addrs = list(range(min(len(words), 96)))

for i in addrs:
    if i >= len(words):
        continue
    w = words[i]
    glyph = chr(w) if 33 <= w <= 126 else "·"
    print(f"{i:04d}: {w:05d} {glyph!r}")
