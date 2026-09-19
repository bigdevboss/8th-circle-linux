#!/usr/bin/env python3
"""Boot 8th Circle Linux in QEMU and interact with msh over serial.

This is a smoke test, not a full integration test. It waits for the msh prompt,
sends a few commands, captures QEMU output to build/qemu-smoke.log, and passes
if the init/msh markers appear before timeout.
"""
from __future__ import annotations

import os
import pty
import select
import signal
import subprocess
import sys
import time
from pathlib import Path


def find_kernel() -> str:
    env = os.environ.get("QEMU_KERNEL")
    if env:
        return env
    candidates = sorted(Path("/boot").glob("vmlinuz-*"))
    if candidates:
        return str(candidates[-1])
    for p in [Path("/vmlinuz"), Path("/boot/vmlinuz")]:
        if p.exists():
            return str(p)
    raise SystemExit("no kernel found; install linux-image-amd64 or set QEMU_KERNEL=/path/to/vmlinuz")


def terminate(proc: subprocess.Popen[str]) -> None:
    if proc.poll() is not None:
        return
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    initramfs = root / "build/8th-circle-initramfs.cpio.gz"
    if not initramfs.exists():
        raise SystemExit(f"missing {initramfs}; run make initramfs first")

    kernel = find_kernel()
    log_path = root / "build/qemu-smoke.log"
    timeout_s = int(os.environ.get("QEMU_SMOKE_TIMEOUT", "60"))

    cmd = [
        "qemu-system-x86_64",
        "-m", os.environ.get("QEMU_MEMORY", "512M"),
        "-accel", os.environ.get("QEMU_ACCEL", "tcg"),
        "-kernel", kernel,
        "-initrd", str(initramfs),
        "-append", "console=ttyS0 rdinit=/init panic=1 oops=panic loglevel=7",
        "-nographic",
        "-no-reboot",
        "-monitor", "none",
    ]

    print("[8CL:qemu-smoke] kernel:", kernel)
    print("[8CL:qemu-smoke] initramfs:", initramfs)
    print("[8CL:qemu-smoke] command:", " ".join(cmd))

    master_fd, slave_fd = pty.openpty()
    proc = subprocess.Popen(
        cmd,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=subprocess.STDOUT,
        cwd=root,
        close_fds=True,
    )
    os.close(slave_fd)

    commands = ["help", "pwd", "ls /", "issue", "cat /etc/issue", "echo from the eighth circle", "mfsls", "mfscat etc/issue", "exit"]
    sent = 0
    output_parts: list[str] = []
    raw = bytearray()
    deadline = time.time() + timeout_s
    last_prompt_seen_at = 0

    required = [
        "[8CL:init] entering the eighth circle",
        "8th Circle Linux / M8 initramfs",
        "[8CL:init] spawning msh through /bin/m8",
        "Welcome to 8th circle Linux! Type 'help' to see msh commands.",
        "8th Circle Linux msh builtins",
        "External M8 commands",
        "bin",
        "POSIX was not painful enough",
        "from the eighth circle",
        "etc/issue",
        "8th Circle Linux MFS image",
        "[8CL:msh] exiting; PID 1 will reopen the circle.",
    ]

    try:
        while time.time() < deadline:
            if proc.poll() is not None:
                break
            r, _, _ = select.select([master_fd], [], [], 0.25)
            if master_fd in r:
                try:
                    chunk = os.read(master_fd, 4096)
                except OSError:
                    break
                if not chunk:
                    break
                raw.extend(chunk)
                text = chunk.decode("utf-8", "replace")
                output_parts.append(text)
                sys.stdout.write(text)
                sys.stdout.flush()

            output = "".join(output_parts)
            # Send one command per newly observed prompt. Delay a hair so the
            # shell is really blocked in its input loop, not just printing the prompt.
            prompt_count = output.count("msh>")
            if sent < len(commands) and prompt_count > last_prompt_seen_at:
                last_prompt_seen_at = prompt_count
                time.sleep(0.1)
                line = commands[sent] + "\n"
                os.write(master_fd, line.encode())
                sent += 1

            if sent >= len(commands) and all(m in output for m in required):
                break
    finally:
        terminate(proc)
        os.close(master_fd)

    output = bytes(raw).decode("utf-8", "replace")
    log_path.write_text(output, errors="replace")
    print(f"\n[8CL:qemu-smoke] wrote {log_path}")

    missing = [m for m in required if m not in output]
    if missing:
        print("[8CL:qemu-smoke] missing markers:", missing, file=sys.stderr)
        print("[8CL:qemu-smoke] log tail:\n" + "\n".join(output.splitlines()[-120:]))
        return 1
    print("[8CL:qemu-smoke] boot smoke passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
