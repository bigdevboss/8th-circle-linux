#!/usr/bin/env python3
"""Create a bootable 8th Circle Linux QEMU bundle.

The bundle is an initramfs plus a Linux kernel image. We do not build Linux
here; we copy an existing kernel from QEMU_KERNEL, --kernel, or /boot/vmlinuz-*.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
from pathlib import Path


def find_kernel(cli_kernel: Path | None) -> Path:
    if cli_kernel is not None:
        p = cli_kernel
        if p.exists():
            return p
        raise SystemExit(f"kernel not found: {p}")

    env = os.environ.get("QEMU_KERNEL")
    if env:
        p = Path(env)
        if p.exists():
            return p
        raise SystemExit(f"QEMU_KERNEL does not exist: {p}")

    candidates = sorted(Path("/boot").glob("vmlinuz-*"))
    if candidates:
        return candidates[-1]

    for p in [Path("/vmlinuz"), Path("/boot/vmlinuz")]:
        if p.exists():
            return p

    raise SystemExit("no Linux kernel found; set QEMU_KERNEL=/path/to/vmlinuz")


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_run_script(path: Path) -> None:
    path.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "DIR=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "exec qemu-system-x86_64 \\\n"
        "  -m \"${QEMU_MEMORY:-512M}\" \\\n"
        "  -accel \"${QEMU_ACCEL:-tcg}\" \\\n"
        "  -kernel \"$DIR/vmlinuz\" \\\n"
        "  -initrd \"$DIR/8th-circle-initramfs.cpio.gz\" \\\n"
        "  -append \"console=ttyS0 rdinit=/init panic=1 oops=panic loglevel=7\" \\\n"
        "  -nographic -no-reboot -monitor none\n"
    )
    path.chmod(0o755)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--initramfs", required=True, type=Path)
    ap.add_argument("--kernel", type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    if not args.initramfs.exists():
        raise SystemExit(f"initramfs not found: {args.initramfs}")

    kernel = find_kernel(args.kernel)
    out = args.out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    kernel_out = out / "vmlinuz"
    initramfs_out = out / "8th-circle-initramfs.cpio.gz"
    shutil.copy2(kernel, kernel_out)
    shutil.copy2(args.initramfs, initramfs_out)
    write_run_script(out / "run-qemu.sh")

    files = [kernel_out, initramfs_out, out / "run-qemu.sh"]
    manifest_lines = [
        "8th Circle Linux boot bundle",
        f"kernel_source={kernel}",
        "",
    ]
    for p in files[:2]:
        manifest_lines.append(f"sha256 {sha256(p)}  {p.name}  {p.stat().st_size} bytes")
    (out / "manifest.txt").write_text("\n".join(manifest_lines) + "\n")

    (out / "README.txt").write_text(
        "8th Circle Linux boot bundle\n"
        "\n"
        "This directory is a generated boot artifact. It pairs the generated\n"
        "initramfs with a Linux kernel copied from the build host.\n"
        "\n"
        "Run it with:\n"
        "\n"
        "  ./run-qemu.sh\n"
        "\n"
        "Or manually:\n"
        "\n"
        "  qemu-system-x86_64 -m 512M -accel tcg -kernel vmlinuz \\\n"
        "    -initrd 8th-circle-initramfs.cpio.gz \\\n"
        "    -append \"console=ttyS0 rdinit=/init panic=1 oops=panic loglevel=7\" \\\n"
        "    -nographic -no-reboot -monitor none\n"
        "\n"
        "Do not commit this local kernel copy. The source repo keeps the M8\n"
        "runtime, scrolls, generated printable userland, and build tools.\n"
    )

    print(f"distro bundle ready: {out}")
    print(f"  kernel: {kernel_out}")
    print(f"  initramfs: {initramfs_out}")
    print(f"  run: {out / 'run-qemu.sh'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
