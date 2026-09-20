#!/usr/bin/env python3
"""Create the msh filesystem equality oracle tree.

msh classifies input bytes and compares builtin-name characters with
open(2) probes instead of arithmetic helpers: a path built from the byte
opens successfully only when the matching magic file exists. The tree is
shipped in the rootfs image by build_rootfs.py; this CLI exists so host
test runs can materialize the same tree at / (needs write access).
"""
from __future__ import annotations

import argparse
from pathlib import Path

# Separator oracle: hot test dir "x" holds all three separator-named
# files; "n"/"r"/"s" distinguish which separator a byte is.
SEPARATOR_FILES = {
    "x": [b"\nx", b"\rx", b" x"],
    "n": [b"\nx"],
    "r": [b"\rx"],
    "s": [b" x"],
}

# Builtin command names whose characters get equality files
# /.m8/eq/<C>/<C>e.
BUILTIN_NAMES = ["help", "exit", "cd", "mfsls", "mfscat"]


def make_tree(root: Path) -> list[Path]:
    root = Path(root)
    made: list[Path] = []
    for sub, names in SEPARATOR_FILES.items():
        d = root / ".m8" / sub
        d.mkdir(parents=True, exist_ok=True)
        made.append(d)
        for n in names:
            f = d / n.decode("latin1")
            f.write_bytes(b"")
            made.append(f)
    chars = sorted({ch for name in BUILTIN_NAMES for ch in name})
    for ch in chars:
        d = root / ".m8" / "eq" / ch
        d.mkdir(parents=True, exist_ok=True)
        made.append(d)
        f = d / (ch + "e")
        f.write_bytes(b"")
        made.append(f)
    return made


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", nargs="?", default="/", help="root to create /.m8 under")
    args = ap.parse_args()
    made = make_tree(args.root)
    print(f"oracle tree ready under {args.root}/.m8 ({len(made)} entries)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
