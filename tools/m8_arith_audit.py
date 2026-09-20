#!/usr/bin/env python3
"""Count friendly arithmetic operations in M8 scrolls.

C5 wants to move selected data manipulation toward Malbolge-style crazy/rotate
rituals. This tool measures the current debt without changing semantics.
"""
from __future__ import annotations

import argparse
import re
import shlex
from collections import Counter
from pathlib import Path

ARITH_OPS = ("addi", "subi", "addm", "subm", "cmpm")
ALL_TRACKED = ARITH_OPS + ("seta", "loada", "storea", "loadi", "storei")
LABEL_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$")


def strip_comment(line: str) -> str:
    in_str = False
    esc = False
    out: list[str] = []
    for ch in line:
        if esc:
            out.append(ch)
            esc = False
            continue
        if ch == "\\" and in_str:
            out.append(ch)
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            out.append(ch)
            continue
        if ch == ";" and not in_str:
            break
        out.append(ch)
    return "".join(out).strip()


def mnemonic(line: str) -> str | None:
    line = strip_comment(line)
    while line:
        m = LABEL_RE.match(line)
        if not m:
            break
        line = m.group(2).strip()
    if not line:
        return None
    lex = shlex.shlex(line, posix=True)
    lex.whitespace_split = True
    lex.commenters = ""
    parts = list(lex)
    if not parts:
        return None
    op = parts[0].lower()
    if op.startswith("."):
        op = op[1:]
    if op == "jmp":
        op = "jump"
    elif op == "sta":
        op = "storea"
    elif op == "lda":
        op = "loada"
    return op


def collect(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    for path in paths:
        if path.is_dir():
            out.extend(sorted(path.rglob("*.m8a")))
        else:
            out.append(path)
    return out


def audit_file(path: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    for line in path.read_text().splitlines():
        op = mnemonic(line)
        if op:
            counts[op] += 1
    return counts


def detail_lines(path: Path) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    for line_no, raw in enumerate(path.read_text().splitlines(), 1):
        op = mnemonic(raw)
        if op in ARITH_OPS:
            out.append((line_no, op, raw.strip()))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="count friendly arithmetic operations in .m8a scrolls")
    parser.add_argument("paths", nargs="*", type=Path, default=[Path("scrolls")])
    parser.add_argument("--tracked", action="store_true", help="also show non-arithmetic tracked M8 ops")
    parser.add_argument("--details", action="store_true", help="show line-level arithmetic helper usage")
    parser.add_argument("--fail-above", type=int, help="fail if arithmetic total is above this number")
    args = parser.parse_args()

    files = collect(args.paths)
    if not files:
        print("m8-arith-audit: no .m8a files found")
        return 2

    per_file: list[tuple[Path, Counter[str]]] = []
    total: Counter[str] = Counter()
    for path in files:
        counts = audit_file(path)
        per_file.append((path, counts))
        total.update(counts)

    ops = ALL_TRACKED if args.tracked else ARITH_OPS
    print("M8 arithmetic debt")
    print("totals:")
    for op in ops:
        print(f"  {op:7s} {total[op]:5d}")
    arith_total = sum(total[op] for op in ARITH_OPS)
    print(f"  {'arith-total':7s} {arith_total:5d}")
    print()
    print("per file:")
    header = "file".ljust(34) + " " + " ".join(f"{op:>5s}" for op in ARITH_OPS) + " total"
    print(header)
    print("-" * len(header))
    for path, counts in sorted(per_file, key=lambda item: str(item[0])):
        subtotal = sum(counts[op] for op in ARITH_OPS)
        values = " ".join(f"{counts[op]:5d}" for op in ARITH_OPS)
        print(f"{str(path):34s} {values} {subtotal:5d}")

    if args.details:
        print()
        print("details:")
        for path, _counts in sorted(per_file, key=lambda item: str(item[0])):
            rows = detail_lines(path)
            if not rows:
                continue
            print(f"{path}:")
            for line_no, op, raw in rows:
                print(f"  {line_no:4d}: {op:5s} {raw}")

    if args.fail_above is not None and arith_total > args.fail_above:
        print(f"arithmetic total {arith_total} is above limit {args.fail_above}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
