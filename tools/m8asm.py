#!/usr/bin/env python3
"""Tiny assembler/code generator for M8, the 8th Circle Malbolge dialect.

The main output is a printable Malbolge-ish glyph stream. Source cells are
loaded exactly as printable ASCII and are chosen so they decode to valid M8
operations at their addresses. M8 inline frame words are encoded as five
printable base-94 cells that are also valid source cells. Data directives are
materialized at program startup by generated M8 code, so strings and numeric
words still become real VM words before user code runs.
"""
from __future__ import annotations

import argparse
import ast
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

XLAT1 = (
    "+b(29e*j1VMEKLyC})8&m#~W>qxdRp0wkrUo[D7,XTcA\"lI\\"
    "v%{gJh4G\\-=O@5`_3i<?Z';FNQuY]szf$!BS/|t:Pn6^Ha"
)

WORD_MOD = 59049
FRAME_WORDS = 6
ENC_WORD_CELLS = 5
VALID_DECODED_OPS = set("ji*p/<vo@!?=~#+-[]:^$`")
_FRAME_CACHE: dict[tuple[int, int], tuple[int, ...]] = {}
ARG_A = WORD_MOD - 2
M8_ARGC = 58000
M8_ARGV = 58001
M8_ARGVEC = 58016
M8_ARG_STRINGS = 58100

SYSCALLS = {
    "read": 0,
    "write": 1,
    "open": 2,
    "close": 3,
    "dup2": 33,
    "pause": 34,
    "nanosleep": 35,
    "getpid": 39,
    "fork": 57,
    "execve": 59,
    "exit": 60,
    "wait4": 61,
    "getcwd": 79,
    "chdir": 80,
    "mkdir": 83,
    "setsid": 112,
    "mount": 165,
    "getdents64": 217,
}

BRANCH_MODES = {
    "branch": 0,
    "branchz": 1,
    "branchnz": 2,
    "brancherr": 3,
    "branchok": 4,
}

EXT_OPS = {
    "seta": "#",
    "addi": "+",
    "subi": "-",
    "addm": "[",
    "subm": "]",
    "cmpm": ":",
    "loadi": "^",
    "storei": "$",
    "jumpm": "`",
}

SPECIALS = {
    "A": ARG_A,
    "ACC": ARG_A,
    "M8_ARGC": M8_ARGC,
    "M8_ARGV": M8_ARGV,
    "M8_ARGVEC": M8_ARGVEC,
    "M8_ARG_STRINGS": M8_ARG_STRINGS,
}


@dataclass
class Item:
    kind: str
    args: list[str]
    line_no: int
    raw: str
    address: int = 0


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


def parse_string(token: str) -> bytes:
    try:
        return bytes(token, "utf-8").decode("unicode_escape").encode("utf-8")
    except Exception as exc:
        raise SystemExit(f"bad string {token!r}: {exc}") from exc


def encoded_frame_cells(word_count: int) -> int:
    return word_count * ENC_WORD_CELLS


def item_size(kind: str, args: list[str], line_no: int) -> int:
    if kind == "trap":
        return 1 + encoded_frame_cells(FRAME_WORDS)
    if kind == "jump":
        return 1 + encoded_frame_cells(1)
    if kind in BRANCH_MODES:
        return 1 + encoded_frame_cells(2)
    if kind in ("storea", "loada") or kind in EXT_OPS:
        return 1 + encoded_frame_cells(1)
    if kind == "ascii":
        if len(args) != 1:
            raise SystemExit(f"line {line_no}: ascii expects one string")
        return len(parse_string(args[0]))
    if kind == "cstring":
        if len(args) != 1:
            raise SystemExit(f"line {line_no}: cstring expects one string")
        return len(parse_string(args[0])) + 1
    if kind == "word":
        return len(args)
    if kind == "ptr":
        return len(args)
    if kind == "ptrv":
        return len(args) + 1
    if kind == "zero":
        if len(args) != 1:
            raise SystemExit(f"line {line_no}: zero expects one count")
        count = int(args[0], 0)
        if count < 0:
            raise SystemExit(f"line {line_no}: zero count must be non-negative")
        return count
    if kind == "op":
        return 1
    raise SystemExit(f"line {line_no}: unknown directive/instruction {kind!r}")


def parse_source(text: str) -> tuple[list[Item], dict[str, int]]:
    items: list[Item] = []
    labels: dict[str, int] = {}
    pc = 0

    for line_no, original in enumerate(text.splitlines(), 1):
        line = strip_comment(original)
        if not line:
            continue
        while True:
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_]*):\s*(.*)$", line)
            if not m:
                break
            label, rest = m.group(1), m.group(2)
            if label in labels:
                raise SystemExit(f"line {line_no}: duplicate label {label!r}")
            labels[label] = pc
            line = rest.strip()
            if not line:
                break
        if not line:
            continue

        lex = shlex.shlex(line, posix=True)
        lex.whitespace_split = True
        lex.commenters = ""
        parts = list(lex)
        if not parts:
            continue
        op = parts[0].lower()
        args = parts[1:]
        if op.startswith("."):
            op = op[1:]
        if op == "jmp":
            op = "jump"
        elif op == "sta":
            op = "storea"
        elif op == "lda":
            op = "loada"

        size = item_size(op, args, line_no)
        item = Item(op, args, line_no, original, pc)
        items.append(item)
        pc += size

    return items, labels


def encode_op(op: str, address: int) -> int:
    if len(op) != 1:
        raise ValueError(f"op must be one char, got {op!r}")
    idx = XLAT1.find(op)
    if idx < 0:
        raise ValueError(f"decoded op {op!r} does not exist in xlat1")
    return 33 + ((idx - address) % 94)


def decode_op_from_digit(digit: int, address: int) -> str:
    return XLAT1[(digit + address) % 94]


def digit_is_valid_source(digit: int, address: int) -> bool:
    return decode_op_from_digit(digit, address) in VALID_DECODED_OPS


def encode_frame_word(value: int, start_address: int) -> list[int]:
    """Encode one M8 word as printable cells that are also valid M8 source.

    The runtime decodes the base-94 value modulo WORD_MOD. Five cells give many
    alternate spellings for the same word, so we pick one where every frame cell
    would decode to a valid M8 instruction at its own address. The frame is still
    skipped as data during normal execution, but the loaded glyph stream now
    satisfies Malbolge-style source validation instead of being arbitrary
    printable junk.
    """
    want = value % WORD_MOD
    key = (want, start_address % 94)
    cached = _FRAME_CACHE.get(key)
    if cached is not None:
        return list(cached)

    cap = 94 ** ENC_WORD_CELLS
    encoded = want
    while encoded < cap:
        t = encoded
        cells: list[int] = []
        ok = True
        for i in range(ENC_WORD_CELLS):
            digit = t % 94
            t //= 94
            if not digit_is_valid_source(digit, start_address + i):
                ok = False
                break
            cells.append(33 + digit)
        if ok:
            _FRAME_CACHE[key] = tuple(cells)
            return cells
        encoded += WORD_MOD

    raise SystemExit(
        f"cannot encode frame word {want} at address {start_address}: "
        "no valid-source base-94 spelling found"
    )


def eval_expr(expr: str, labels: dict[str, int]) -> int:
    expr = expr.strip()
    if expr in SYSCALLS:
        return SYSCALLS[expr]
    if expr in SPECIALS:
        return SPECIALS[expr]

    node = ast.parse(expr, mode="eval")

    def rec(n: ast.AST) -> int:
        if isinstance(n, ast.Expression):
            return rec(n.body)
        if isinstance(n, ast.Constant) and isinstance(n.value, int):
            return int(n.value)
        if isinstance(n, ast.Name):
            if n.id in SYSCALLS:
                return SYSCALLS[n.id]
            if n.id in SPECIALS:
                return SPECIALS[n.id]
            if n.id not in labels:
                raise SystemExit(f"unknown label/name {n.id!r} in expression {expr!r}")
            return labels[n.id]
        if isinstance(n, ast.BinOp) and isinstance(n.op, (ast.Add, ast.Sub)):
            left, right = rec(n.left), rec(n.right)
            return left + right if isinstance(n.op, ast.Add) else left - right
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            return -rec(n.operand)
        raise SystemExit(f"unsupported expression {expr!r}")

    return rec(node)


def count_initializers(items: list[Item]) -> int:
    n = 0
    for item in items:
        if item.kind == "ascii":
            n += len(parse_string(item.args[0]))
        elif item.kind == "cstring":
            n += len(parse_string(item.args[0])) + 1
        elif item.kind == "word":
            n += len(item.args)
        elif item.kind == "ptr":
            n += len(item.args)
        elif item.kind == "ptrv":
            n += len(item.args) + 1
    return n


def append_filler(mem: list[int], address: int, count: int) -> None:
    for i in range(count):
        mem.append(encode_op("o", address + i))


def assemble_program(items: list[Item], labels: dict[str, int], base: int) -> tuple[list[int], list[tuple[int, int]], dict[str, int]]:
    final_labels = {k: v + base for k, v in labels.items()}
    mem: list[int] = []
    init: list[tuple[int, int]] = []

    def cur_addr(item: Item) -> int:
        return base + item.address

    def add_frame(value: int) -> None:
        mem.extend(encode_frame_word(value, base + len(mem)))

    for item in items:
        expected = item.address
        if len(mem) != expected:
            raise AssertionError((len(mem), expected, item.raw))
        addr = cur_addr(item)

        if item.kind == "trap":
            if not item.args:
                raise SystemExit(f"line {item.line_no}: trap expects syscall name/number")
            sysno = eval_expr(item.args[0], final_labels)
            args = [eval_expr(a, final_labels) for a in item.args[1:]]
            if len(args) > 5:
                raise SystemExit(f"line {item.line_no}: trap accepts at most 5 args")
            args += [0] * (5 - len(args))
            mem.append(encode_op("@", addr))
            for v in [sysno, *args]:
                add_frame(v)
        elif item.kind == "jump":
            if len(item.args) != 1:
                raise SystemExit(f"line {item.line_no}: jump expects one target label/expression")
            mem.append(encode_op("!", addr))
            add_frame(eval_expr(item.args[0], final_labels))
        elif item.kind in BRANCH_MODES:
            if len(item.args) != 1:
                raise SystemExit(f"line {item.line_no}: {item.kind} expects one target label/expression")
            mem.append(encode_op("?", addr))
            add_frame(eval_expr(item.args[0], final_labels))
            add_frame(BRANCH_MODES[item.kind])
        elif item.kind == "storea":
            if len(item.args) != 1:
                raise SystemExit(f"line {item.line_no}: storea expects one target label/expression")
            mem.append(encode_op("=", addr))
            add_frame(eval_expr(item.args[0], final_labels))
        elif item.kind == "loada":
            if len(item.args) != 1:
                raise SystemExit(f"line {item.line_no}: loada expects one source label/expression")
            mem.append(encode_op("~", addr))
            add_frame(eval_expr(item.args[0], final_labels))
        elif item.kind in EXT_OPS:
            if len(item.args) != 1:
                raise SystemExit(f"line {item.line_no}: {item.kind} expects one label/expression")
            mem.append(encode_op(EXT_OPS[item.kind], addr))
            add_frame(eval_expr(item.args[0], final_labels))
        elif item.kind == "ascii":
            data = parse_string(item.args[0])
            append_filler(mem, addr, len(data))
            init.extend((addr + i, b) for i, b in enumerate(data))
        elif item.kind == "cstring":
            data = parse_string(item.args[0]) + b"\0"
            append_filler(mem, addr, len(data))
            init.extend((addr + i, b) for i, b in enumerate(data))
        elif item.kind == "word":
            append_filler(mem, addr, len(item.args))
            for i, a in enumerate(item.args):
                init.append((addr + i, eval_expr(a, final_labels) % WORD_MOD))
        elif item.kind == "ptr":
            if not item.args:
                raise SystemExit(f"line {item.line_no}: ptr expects at least one expression")
            append_filler(mem, addr, len(item.args))
            for i, a in enumerate(item.args):
                init.append((addr + i, eval_expr(a, final_labels) % WORD_MOD))
        elif item.kind == "ptrv":
            if not item.args:
                raise SystemExit(f"line {item.line_no}: ptrv expects at least one expression")
            append_filler(mem, addr, len(item.args) + 1)
            for i, a in enumerate(item.args):
                init.append((addr + i, eval_expr(a, final_labels) % WORD_MOD))
            init.append((addr + len(item.args), 0))
        elif item.kind == "zero":
            count = int(item.args[0], 0)
            append_filler(mem, addr, count)
        elif item.kind == "op":
            if len(item.args) != 1:
                raise SystemExit(f"line {item.line_no}: op expects one decoded op char")
            mem.append(encode_op(item.args[0], addr))
        else:
            raise AssertionError(item)
    return mem, init, final_labels


def build_materializer(init: list[tuple[int, int]], start_addr: int) -> list[int]:
    mem: list[int] = []

    def add_frame(value: int) -> None:
        mem.extend(encode_frame_word(value, len(mem)))

    for target, value in init:
        addr = len(mem)
        mem.append(encode_op("#", addr))
        add_frame(value)
        addr = len(mem)
        mem.append(encode_op("=", addr))
        add_frame(target)
    addr = len(mem)
    mem.append(encode_op("!", addr))
    add_frame(start_addr)
    return mem


def assemble_glyph(items: list[Item], labels: dict[str, int]) -> tuple[list[int], dict[str, int], int]:
    init_count = count_initializers(items)
    prefix_len = init_count * (2 * (1 + ENC_WORD_CELLS)) + (1 + ENC_WORD_CELLS)
    program, init, final_labels = assemble_program(items, labels, prefix_len)
    start_addr = final_labels.get("start", prefix_len)
    materializer = build_materializer(init, start_addr)
    if len(materializer) != prefix_len:
        raise AssertionError((len(materializer), prefix_len))
    image = materializer + program
    if len(image) > WORD_MOD:
        raise SystemExit(f"image too large for v0 memory: {len(image)} cells")
    for i, word in enumerate(image):
        if word < 33 or word > 126:
            raise AssertionError((i, word))
    return image, final_labels, prefix_len


def wrap_glyphs(words: list[int], width: int = 94) -> str:
    text = "".join(chr(w) for w in words)
    return "\n".join(text[i : i + width] for i in range(0, len(text), width)) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("input", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--dump-labels", action="store_true")
    parser.add_argument("--dump-prefix", action="store_true")
    args = parser.parse_args()

    if len(XLAT1) != 94:
        raise SystemExit(f"internal error: XLAT1 has length {len(XLAT1)}, expected 94")

    text = args.input.read_text()
    items, labels = parse_source(text)
    image, final_labels, prefix_len = assemble_glyph(items, labels)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(wrap_glyphs(image))

    if args.dump_labels:
        if args.dump_prefix:
            print(f"__materializer_cells={prefix_len}")
        for k, v in sorted(final_labels.items(), key=lambda kv: kv[1]):
            print(f"{k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
