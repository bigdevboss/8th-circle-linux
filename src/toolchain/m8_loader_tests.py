#!/usr/bin/env python3
"""Negative tests for strict .mb loading."""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

XLAT1 = (
    "+b(29e*j1VMEKLyC})8&m#~W>qxdRp0wkrUo[D7,XTcA\"lI\\"
    "v%{gJh4G\\-=O@5`_3i<?Z';FNQuY]szf$!BS/|t:Pn6^Ha"
)
VALID_OPS = set("ji*p/<vo@!?=~#+-[]:^$`")


def invalid_glyph_at(address: int) -> str:
    for code in range(33, 127):
        op = XLAT1[(code - 33 + address) % 94]
        if op not in VALID_OPS:
            return chr(code)
    raise AssertionError("every glyph decoded as valid, which should not happen")


def run_bad(runtime: Path, path: Path, label: str) -> None:
    proc = subprocess.run(
        [str(runtime), "--max-steps", "50", str(path)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 2:
        raise SystemExit(
            f"loader negative test failed for {label}: expected exit 2, got {proc.returncode}\n"
            f"stdout:\n{proc.stdout}\n"
            f"stderr:\n{proc.stderr}"
        )
    print(f"strict-loader rejects {label}: ok")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("runtime", type=Path)
    parser.add_argument("--workdir", type=Path, default=Path("build/loader-tests"))
    args = parser.parse_args()

    workdir = args.workdir
    workdir.mkdir(parents=True, exist_ok=True)

    cases = {
        "old decimal memory image": "# M8 raw memory image v0\n1\n2\n3\n",
        "plain decimal lines": "1\n2\n3\n",
        "non-graphic byte": "\x01\n",
        "invalid decoded glyph": invalid_glyph_at(0) + "\n",
        "empty source": "\n\t\n",
    }
    for label, content in cases.items():
        path = workdir / (label.replace(" ", "-") + ".mb")
        path.write_text(content)
        run_bad(args.runtime, path, label)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
