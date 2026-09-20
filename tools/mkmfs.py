#!/usr/bin/env python3
"""Build an MFS v0 image.

MFS v0 is intentionally tiny:

- 512-byte superblock
- fixed 128-byte file entries
- contiguous file payloads
- read-only for now

This builder is a toolchain convenience. The long-term goal is to grow M8/MFS
tools that can create and mutate these images from inside 8th Circle Linux.
"""
from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"MFS8V0\0\0"
BLOCK_SIZE = 512
HEADER_SIZE = 512
ENTRY_SIZE = 128
NAME_SIZE = 96


@dataclass
class Entry:
    name: str
    data: bytes
    offset: int = 0


def align(n: int, a: int = BLOCK_SIZE) -> int:
    return (n + a - 1) // a * a


def collect(root: Path) -> list[Entry]:
    entries: list[Entry] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        if rel.startswith("/") or ".." in rel.split("/"):
            raise SystemExit(f"bad MFS path: {rel}")
        raw = rel.encode("utf-8")
        if len(raw) >= NAME_SIZE:
            raise SystemExit(f"MFS path too long ({len(raw)} >= {NAME_SIZE}): {rel}")
        entries.append(Entry(rel, p.read_bytes()))
    return entries


def build(root: Path) -> bytes:
    entries = collect(root)
    table_offset = HEADER_SIZE
    data_offset = align(HEADER_SIZE + len(entries) * ENTRY_SIZE)
    cursor = data_offset
    payload = bytearray()

    for e in entries:
        cursor = align(cursor)
        if len(payload) < cursor - data_offset:
            payload.extend(b"\0" * (cursor - data_offset - len(payload)))
        e.offset = cursor
        payload.extend(e.data)
        cursor += len(e.data)

    image_size = data_offset + len(payload)

    header = bytearray(HEADER_SIZE)
    header[0:8] = MAGIC
    struct.pack_into("<IIIIII", header, 8, BLOCK_SIZE, len(entries), table_offset, data_offset, image_size, ENTRY_SIZE)

    table = bytearray(align(len(entries) * ENTRY_SIZE))
    for i, e in enumerate(entries):
        off = i * ENTRY_SIZE
        name_b = e.name.encode("utf-8")
        table[off : off + len(name_b)] = name_b
        struct.pack_into("<III", table, off + NAME_SIZE, e.offset, len(e.data), 0)

    out = bytearray()
    out.extend(header)
    out.extend(table)
    if len(out) < data_offset:
        out.extend(b"\0" * (data_offset - len(out)))
    out.extend(payload)
    return bytes(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("-o", "--output", required=True, type=Path)
    args = ap.parse_args()

    image = build(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)
    print(f"mfs image ready: {args.output} ({len(image)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
