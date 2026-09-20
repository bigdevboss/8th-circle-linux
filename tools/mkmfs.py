#!/usr/bin/env python3
"""Build an MFS v1 image plus its scroll manifest.

MFS v1 layout:

- 512-byte superblock
- fixed 16-slot entry table (128 bytes per entry), zero-filled
- contiguous file payloads starting at byte 2560
- read-only

The fixed slot count is the sentinel contract: tools walk all 16 static
slot bases and unused slots have empty names, so no runtime entry count
or stride arithmetic is needed.

The manifest is a generated M8 assembly fragment. It defines per-slot
words (payload source, payload end, size, offset) that reference the
including scroll's mfs_buf label. MFS tools include it and get static
payload bounds with zero runtime arithmetic. The manifest is part of
the MFS distribution, like a DTB shipped beside a kernel image.

This builder is a toolchain convenience. The long-term goal is to grow
M8/MFS tools that can create and mutate these images from inside
8th Circle Linux.
"""
from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path

MAGIC = b"MFS8V1\0\0"
BLOCK_SIZE = 512
HEADER_SIZE = 512
ENTRY_SIZE = 128
NAME_SIZE = 96
SLOTS = 16


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


def build(root: Path) -> tuple[bytes, list[Entry]]:
    entries = collect(root)
    if len(entries) > SLOTS:
        raise SystemExit(f"too many MFS entries ({len(entries)} > {SLOTS})")

    table_offset = HEADER_SIZE
    data_offset = HEADER_SIZE + SLOTS * ENTRY_SIZE
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

    table = bytearray(SLOTS * ENTRY_SIZE)
    for i, e in enumerate(entries):
        off = i * ENTRY_SIZE
        name_b = e.name.encode("utf-8")
        table[off : off + len(name_b)] = name_b
        struct.pack_into("<III", table, off + NAME_SIZE, e.offset, len(e.data), 0)

    out = bytearray()
    out.extend(header)
    out.extend(table)
    out.extend(payload)
    return bytes(out), entries


def manifest(entries: list[Entry]) -> str:
    lines: list[str] = []
    for k in range(SLOTS):
        if k < len(entries):
            e = entries[k]
            size = len(e.data)
            lines.append(f"mfs_entry_{k}_src:")
            lines.append(f"    word mfs_buf+{e.offset}")
            lines.append(f"mfs_entry_{k}_end:")
            lines.append(f"    word mfs_buf+{e.offset + size}")
            lines.append(f"mfs_entry_{k}_size:")
            lines.append(f"    word {size}")
            lines.append(f"mfs_entry_{k}_offset:")
            lines.append(f"    word {e.offset}")
        else:
            lines.append(f"mfs_entry_{k}_src:")
            lines.append("    word mfs_buf")
            lines.append(f"mfs_entry_{k}_end:")
            lines.append("    word mfs_buf")
            lines.append(f"mfs_entry_{k}_size:")
            lines.append("    word 0")
            lines.append(f"mfs_entry_{k}_offset:")
            lines.append("    word 0")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("-o", "--output", required=True, type=Path)
    ap.add_argument("--manifest", type=Path, default=None)
    args = ap.parse_args()

    image, entries = build(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(image)
    print(f"mfs image ready: {args.output} ({len(image)} bytes, {len(entries)} entries)")

    if args.manifest is not None:
        args.manifest.parent.mkdir(parents=True, exist_ok=True)
        args.manifest.write_text(manifest(entries))
        print(f"mfs manifest ready: {args.manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
