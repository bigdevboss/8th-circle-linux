#!/usr/bin/env python3
"""Create a gzip-compressed Linux initramfs in `newc` cpio format.

No external cpio binary and no root privileges are required. We synthesize
/dev/console and /dev/null as cpio character-device records.
"""
from __future__ import annotations

import argparse
import gzip
import os
import stat
import time
from dataclasses import dataclass
from pathlib import Path

CPIO_MAGIC = "070701"


@dataclass
class Entry:
    name: str
    mode: int
    data: bytes = b""
    uid: int = 0
    gid: int = 0
    nlink: int = 1
    mtime: int = int(time.time())
    devmajor: int = 0
    devminor: int = 0
    rdevmajor: int = 0
    rdevminor: int = 0


def pad4(buf: bytearray) -> None:
    while len(buf) % 4:
        buf.append(0)


def write_entry(buf: bytearray, ino: int, e: Entry) -> None:
    name_b = e.name.encode() + b"\0"
    filesize = len(e.data)
    fields = [
        ino,
        e.mode,
        e.uid,
        e.gid,
        e.nlink,
        e.mtime,
        filesize,
        e.devmajor,
        e.devminor,
        e.rdevmajor,
        e.rdevminor,
        len(name_b),
        0,  # check
    ]
    header = CPIO_MAGIC + "".join(f"{x & 0xFFFFFFFF:08x}" for x in fields)
    buf.extend(header.encode("ascii"))
    buf.extend(name_b)
    pad4(buf)
    buf.extend(e.data)
    pad4(buf)


def collect(root: Path) -> list[Entry]:
    entries: list[Entry] = []

    # Root directory record.
    st_root = root.lstat()
    entries.append(
        Entry(
            name=".",
            mode=(stat.S_IFDIR | (st_root.st_mode & 0o7777)),
            nlink=2,
            mtime=int(st_root.st_mtime),
        )
    )

    paths = sorted(root.rglob("*"), key=lambda p: str(p.relative_to(root)))
    for p in paths:
        rel = str(p.relative_to(root))
        st = p.lstat()
        mode_bits = st.st_mode & 0o7777
        mtime = int(st.st_mtime)
        if stat.S_ISDIR(st.st_mode):
            entries.append(Entry(rel, stat.S_IFDIR | mode_bits, nlink=2, mtime=mtime))
        elif stat.S_ISLNK(st.st_mode):
            target = os.readlink(p).encode()
            entries.append(Entry(rel, stat.S_IFLNK | mode_bits, data=target, mtime=mtime))
        elif stat.S_ISREG(st.st_mode):
            entries.append(Entry(rel, stat.S_IFREG | mode_bits, data=p.read_bytes(), mtime=mtime))

    # Device nodes injected without root.
    entries.append(Entry("dev/console", stat.S_IFCHR | 0o600, nlink=1, rdevmajor=5, rdevminor=1))
    entries.append(Entry("dev/null", stat.S_IFCHR | 0o666, nlink=1, rdevmajor=1, rdevminor=3))
    entries.append(Entry("dev/zero", stat.S_IFCHR | 0o666, nlink=1, rdevmajor=1, rdevminor=5))
    entries.append(Entry("dev/tty", stat.S_IFCHR | 0o666, nlink=1, rdevmajor=5, rdevminor=0))
    return entries


def build_newc(root: Path) -> bytes:
    buf = bytearray()
    ino = 1
    for e in collect(root):
        write_entry(buf, ino, e)
        ino += 1
    write_entry(buf, ino, Entry("TRAILER!!!", 0))
    return bytes(buf)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("-o", "--output", required=True, type=Path)
    args = ap.parse_args()

    payload = build_newc(args.root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(args.output, "wb", compresslevel=9) as f:
        f.write(payload)
    print(f"initramfs ready: {args.output} ({args.output.stat().st_size} bytes gz, {len(payload)} bytes raw)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
