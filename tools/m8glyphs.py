#!/usr/bin/env python3
"""Print loaded M8 cells at selected addresses."""
from __future__ import annotations

import sys
from pathlib import Path

XLAT1 = (
    "+b(29e*j1VMEKLyC})8&m#~W>qxdRp0wkrUo[D7,XTcA\"lI\\"
    "v%{gJh4G\\-=O@5`_3i<?Z';FNQuY]szf$!BS/|t:Pn6^Ha"
)

if len(sys.argv) < 2:
    print(f"usage: {sys.argv[0]} IMAGE.mb [addr ...]", file=sys.stderr)
    raise SystemExit(2)

text = Path(sys.argv[1]).read_text()
words = [ord(ch) for ch in text if not ch.isspace()]

if len(sys.argv) > 2:
    addrs = [int(x, 0) for x in sys.argv[2:]]
else:
    addrs = list(range(min(len(words), 96)))

for i in addrs:
    if i >= len(words):
        continue
    w = words[i]
    glyph = chr(w) if 33 <= w <= 126 else "·"
    op = XLAT1[(w - 33 + i) % 94] if 33 <= w <= 126 else "?"
    print(f"{i:04d}: {w:05d} {glyph!r} op={op}")
