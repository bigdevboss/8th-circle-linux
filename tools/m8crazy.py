#!/usr/bin/env python3
"""Small Malbolge/M8 crazy-op laboratory.

This is not part of the boot path. It is a research helper for C5 work: learn
which transforms are cheap before replacing friendly arithmetic with proper
ternary/crazy rituals.
"""
from __future__ import annotations

import argparse
from collections import deque
from dataclasses import dataclass
from itertools import product
from typing import Callable, Iterable

WORD_MOD = 59049
TRITS = 10
POW3_9 = 19683
CRAZY_TABLE = (
    (1, 0, 0),
    (1, 0, 2),
    (2, 2, 1),
)
DEFAULT_SEARCH_CONSTANTS = (
    0,
    1,
    2,
    3,
    10,
    26,
    80,
    94,
    255,
    256,
    512,
    1024,
    19683,
    29524,
    59048,
)


@dataclass(frozen=True)
class SearchNode:
    value: int
    steps: tuple[str, ...]


@dataclass(frozen=True)
class CrazySolve:
    source: int
    target: int
    choices: tuple[tuple[int, ...], ...]
    blockers: tuple[tuple[int, int, int], ...]

    @property
    def possible(self) -> bool:
        return not self.blockers

    @property
    def mask_count(self) -> int:
        if self.blockers:
            return 0
        count = 1
        for opts in self.choices:
            count *= len(opts)
        return count


@dataclass(frozen=True)
class RouteStep:
    op: str
    value: int
    role: str


@dataclass(frozen=True)
class RouteRow:
    index: int
    c: int
    d: int
    op: str
    value: int
    role: str
    a_before: int
    a_after: int


def mod_word(x: int) -> int:
    return x % WORD_MOD


def to_trits(value: int, width: int = TRITS) -> list[int]:
    value = mod_word(value)
    out: list[int] = []
    for _ in range(width):
        out.append(value % 3)
        value //= 3
    return out


def from_trits(trits: list[int] | tuple[int, ...]) -> int:
    value = 0
    place = 1
    for trit in trits:
        if trit not in (0, 1, 2):
            raise ValueError(f"bad trit {trit!r}")
        value += trit * place
        place *= 3
    return mod_word(value)


def fmt_trits(value: int, width: int = TRITS) -> str:
    return "0t" + "".join(str(t) for t in reversed(to_trits(value, width)))


def crazy(a: int, d: int) -> int:
    a = mod_word(a)
    d = mod_word(d)
    out = 0
    place = 1
    for _ in range(TRITS):
        at = a % 3
        dt = d % 3
        out += CRAZY_TABLE[dt][at] * place
        a //= 3
        d //= 3
        place *= 3
    return out


def rotate_right(value: int) -> int:
    value = mod_word(value)
    low = value % 3
    return (value // 3) + low * POW3_9


def normalize_constants(values: Iterable[int] | None) -> tuple[int, ...]:
    raw = DEFAULT_SEARCH_CONSTANTS if values is None else tuple(values)
    out: list[int] = []
    seen: set[int] = set()
    for value in raw:
        word = mod_word(value)
        if word in seen:
            continue
        seen.add(word)
        out.append(word)
    return tuple(out)


def toy_next_states(value: int, constants: tuple[int, ...]) -> list[tuple[int, str]]:
    """Toy graph used by the first C5 experiments.

    `rotA` is an abstract rotate of the current value. It is useful for looking
    at the word graph, but it is not by itself a faithful codegen model because
    classic `*` rotates mem[D], not A directly.
    """
    out: list[tuple[int, str]] = [(rotate_right(value), "rotA")]
    for c in constants:
        out.append((crazy(value, c), f"crazy A,{c}"))
    return out


def runway_next_states(value: int, constants: tuple[int, ...]) -> list[tuple[int, str]]:
    """Generated D-runway model for classic `p` and `*`.

    Each step consumes one generated seed cell under D:

    - `p seed=N` means mem[D] starts as N, then p computes crazy(A, N).
    - `* seed=N` means mem[D] starts as N, then * rotates that seed into A.

    This still does not solve C/D routing or self-cipher layout. It is stricter
    than the toy graph because it no longer pretends that A can rotate itself.
    """
    out: list[tuple[int, str]] = []
    for c in constants:
        out.append((crazy(value, c), f"p seed={c}"))
    for c in constants:
        out.append((rotate_right(c), f"* seed={c}"))
    return out


def print_word(label: str, value: int) -> None:
    value = mod_word(value)
    print(f"{label}: dec={value} trits={fmt_trits(value)} byte={value % 256}")


def bfs_find(
    *,
    start: int,
    max_depth: int,
    limit: int,
    constants: tuple[int, ...],
    predicate: Callable[[int], bool],
    transitions: Callable[[int, tuple[int, ...]], list[tuple[int, str]]] = toy_next_states,
    allow_empty: bool = False,
) -> tuple[list[SearchNode], int]:
    queue: deque[SearchNode] = deque([SearchNode(mod_word(start), ())])
    seen = {mod_word(start)}
    found: list[SearchNode] = []

    while queue and len(found) < limit:
        node = queue.popleft()
        if predicate(node.value) and (allow_empty or node.steps):
            found.append(node)
            continue
        if len(node.steps) >= max_depth:
            continue

        for value, label in transitions(node.value, constants):
            if value in seen:
                continue
            seen.add(value)
            queue.append(SearchNode(value, node.steps + (label,)))

    return found, len(seen)


def print_solutions(solutions: list[SearchNode]) -> None:
    for found, node in enumerate(solutions, 1):
        print_word(f"solution {found} value", node.value)
        if not node.steps:
            print("  0: already there")
        for i, step in enumerate(node.steps, 1):
            print(f"  {i}: {step}")


def solve_crazy(source: int, target: int) -> CrazySolve:
    source = mod_word(source)
    target = mod_word(target)
    choices: list[tuple[int, ...]] = []
    blockers: list[tuple[int, int, int]] = []
    for pos, (dt, tt) in enumerate(zip(to_trits(source), to_trits(target))):
        opts = tuple(at for at in (0, 1, 2) if CRAZY_TABLE[dt][at] == tt)
        if not opts:
            blockers.append((pos, dt, tt))
        choices.append(opts)
    return CrazySolve(source, target, tuple(choices), tuple(blockers))


def masks_for_solve(solve: CrazySolve, limit: int | None = None) -> list[int]:
    if not solve.possible:
        return []
    masks = sorted(from_trits(combo) for combo in product(*solve.choices))
    if limit is not None:
        return masks[: max(0, limit)]
    return masks


def short_blocker(solve: CrazySolve) -> str:
    if not solve.blockers:
        return ""
    pos, dt, tt = solve.blockers[0]
    return f"trit {pos}: D={dt} target={tt}"


def find_runway_plan_to_any(
    *,
    start_a: int,
    targets: set[int],
    max_depth: int,
    constants: tuple[int, ...],
) -> tuple[SearchNode | None, int]:
    solutions, seen_count = bfs_find(
        start=start_a,
        max_depth=max_depth,
        limit=1,
        constants=constants,
        predicate=lambda value: value in targets,
        transitions=runway_next_states,
        allow_empty=True,
    )
    return (solutions[0] if solutions else None), seen_count


def find_runway_plan_for_masks(
    *,
    start_a: int,
    masks: list[int],
    max_depth: int,
    constants: tuple[int, ...],
) -> tuple[SearchNode | None, int]:
    """Find a runway plan, preferring lower masks from an already sorted list."""
    total_seen = 0
    for mask in masks:
        node, seen_count = find_runway_plan_to_any(
            start_a=start_a,
            targets={mask},
            max_depth=max_depth,
            constants=constants,
        )
        total_seen += seen_count
        if node is not None:
            return node, total_seen
    return None, total_seen


def parse_runway_step(step: str) -> RouteStep:
    if step.startswith("p seed="):
        return RouteStep("p", mod_word(int(step.split("=", 1)[1])), "seed")
    if step.startswith("* seed="):
        return RouteStep("*", mod_word(int(step.split("=", 1)[1])), "seed")
    raise ValueError(f"cannot route planner step {step!r}")


def route_rows(
    *,
    steps: list[RouteStep],
    start_a: int,
    c_start: int,
    d_start: int,
) -> list[RouteRow]:
    rows: list[RouteRow] = []
    a = mod_word(start_a)
    c_start = mod_word(c_start)
    d_start = mod_word(d_start)
    for idx, step in enumerate(steps):
        before = a
        if step.op == "p":
            a = crazy(a, step.value)
        elif step.op == "*":
            a = rotate_right(step.value)
        else:
            raise ValueError(f"bad route op {step.op!r}")
        rows.append(
            RouteRow(
                index=idx,
                c=mod_word(c_start + idx),
                d=mod_word(d_start + idx),
                op=step.op,
                value=step.value,
                role=step.role,
                a_before=before,
                a_after=a,
            )
        )
    return rows


def span_cells(start: int, count: int) -> set[int]:
    return {mod_word(start + i) for i in range(max(0, count))}


def fmt_span(start: int, count: int) -> str:
    if count <= 0:
        return "empty"
    end = mod_word(start + count - 1)
    if start + count - 1 < WORD_MOD:
        return f"{start}..{end}"
    return f"{start}..{WORD_MOD - 1},0..{end}"


def print_route(rows: list[RouteRow], c_start: int, d_start: int) -> None:
    code_cells = span_cells(c_start, len(rows))
    data_cells = span_cells(d_start, len(rows))
    overlap = sorted(code_cells & data_cells)
    print(
        f"layout: code-start={mod_word(c_start)} d-start={mod_word(d_start)} "
        f"steps={len(rows)} delta={(mod_word(d_start) - mod_word(c_start)) % WORD_MOD}"
    )
    print(f"code-span: {fmt_span(mod_word(c_start), len(rows))}")
    print(f"data-span: {fmt_span(mod_word(d_start), len(rows))}")
    if overlap:
        sample = " ".join(str(x) for x in overlap[:8])
        suffix = " ..." if len(overlap) > 8 else ""
        print(f"overlap: yes cells={sample}{suffix}")
    else:
        print("overlap: no")
    print("idx      C      D op role       value A_before  A_after")
    print("--- ------ ------ -- ------- -------- -------- --------")
    for row in rows:
        print(
            f"{row.index:3d} {row.c:6d} {row.d:6d} {row.op:2s} "
            f"{row.role:7s} {row.value:8d} {row.a_before:8d} {row.a_after:8d}"
        )


ALL_TWOS = 59048  # 0t2222222222: reachable from any word in one p step, reaches any word in one p step
M8_ABI_ARGC = 58000


class EntryBlocked(Exception):
    """Raised when a value cannot be planned as a straight-line ritual."""


@dataclass(frozen=True)
class ChainStep:
    seed: int
    result: int


@dataclass(frozen=True)
class EntryOp:
    kind: str  # seta | storea | op | loada
    value: int = 0  # seta value, loada target, op char code
    target: int = 0  # storea absolute target
    note: str = ""


@dataclass(frozen=True)
class EntryRow:
    n: int  # 1-based global instruction number
    kind: str
    cell: int  # absolute cell of the instruction op glyph
    d_at: int  # D during execution
    a_before: int
    a_after: int
    note: str


@dataclass
class EntryPlan:
    value: int
    target: int
    mask: int
    runway: tuple[RouteStep, ...]
    chain_a: tuple[ChainStep, ...]
    chain_b: tuple[ChainStep, ...]
    ok_chars: str
    d_entry: int
    cell_base: int
    junk: int
    block_start: int
    block_values: tuple[int, ...]
    ops: tuple[EntryOp, ...]
    rows: tuple[EntryRow, ...]
    checks: tuple[str, ...]
    sections: dict[str, int]
    margin: int
    cell_addr: int | None = None
    neighbor_seeds: tuple[tuple[int, int], ...] = ()

    @property
    def mutable_addr(self) -> int:
        if self.cell_addr is not None:
            return self.cell_addr
        return self.block_start + len(self.runway)

    @property
    def block_len(self) -> int:
        return len(self.block_values)

    @property
    def cell_count(self) -> int:
        return sum(6 if op.kind in ("seta", "storea", "loada") else 1 for op in self.ops)

    @property
    def tick_count(self) -> int:
        return len(self.ops)


def solve_seed(a: int, target: int) -> tuple[tuple[int, ...], ...]:
    """Per-trit row options for seeds with crazy(a, seed) = target.

    A p step computes A = crazy(A, mem[D]), so the seed under D selects the
    crazy table row and the current A selects the column.
    """
    a = mod_word(a)
    target = mod_word(target)
    choices = []
    for at, tt in zip(to_trits(a), to_trits(target)):
        opts = tuple(dt for dt in (0, 1, 2) if CRAZY_TABLE[dt][at] == tt)
        choices.append(opts)
    return tuple(choices)


def smallest_seed(a: int, target: int) -> int | None:
    choices = solve_seed(a, target)
    if any(not opts for opts in choices):
        return None
    return from_trits(tuple(min(opts) for opts in choices))


def chain_to_target(start: int, target: int) -> list[ChainStep]:
    """Chain of p seeds from start to target.

    One step when possible, otherwise two: every word can reach 0t2222222222
    in one p step (row 1 or 2 covers each source trit), and 0t2222222222 can
    reach every word in one p step (column 2 covers each target trit).
    """
    seed = smallest_seed(start, target)
    if seed is not None:
        return [ChainStep(seed, target)]
    first = smallest_seed(start, ALL_TWOS)
    second = smallest_seed(ALL_TWOS, target)
    if first is None or second is None:
        raise EntryBlocked(f"no crazy chain from {start} to {target}")
    return [ChainStep(first, ALL_TWOS), ChainStep(second, target)]


def plan_entry(
    value: int,
    *,
    ok_chars: str = "OK",
    start_a: int = 0,
    max_depth: int = 4,
    mask_limit: int = 16,
    constants: tuple[int, ...] | None = None,
    d_entry: int = 1,
    cell_base: int = 6,
    cell_addr: int | None = None,
) -> EntryPlan:
    """Plan a full straight-line scroll that rewrites value -> value+1.

    d_entry is the number of instructions executed before this block runs
    (for a standalone scroll that is the 1-instruction materializer jump).
    cell_base is the absolute cell where the block's first op glyph lands
    (for a standalone scroll that is 6, right after the materializer).

    Block mode (cell_addr is None): the mutable cell is the last cell of the
    planner-placed seed block and D walks straight into it.

    Cell mode (cell_addr is set): the final rewrite targets a caller-owned
    live cell at that absolute address. A classic j hop at the end of the
    runway sends D to that cell, the final p rewrites it, and the proof-chain
    seeds sit in caller-owned scratch cells right after it.
    """
    value = mod_word(value)
    target = mod_word(value + 1)
    if len(ok_chars) != 2 or not all(33 <= ord(c) <= 126 for c in ok_chars):
        raise EntryBlocked(f"ok_chars must be two printable chars, got {ok_chars!r}")

    solve = solve_crazy(value, target)
    if not solve.possible:
        blocker = "; ".join(f"trit {pos}: D={dt} target={tt}" for pos, dt, tt in solve.blockers)
        raise EntryBlocked(f"direct final p impossible for {value} -> {target} ({blocker})")

    consts = normalize_constants(constants)
    masks = masks_for_solve(solve, max(1, mask_limit))
    node, _seen = find_runway_plan_for_masks(
        start_a=start_a, masks=masks, max_depth=max_depth, constants=consts
    )
    if node is None:
        raise EntryBlocked(f"no runway materializer found for the first {len(masks)} masks")

    runway = tuple(parse_runway_step(step) for step in node.steps)
    chain_a = tuple(chain_to_target(target, ord(ok_chars[0])))
    chain_b = tuple(chain_to_target(target, ord(ok_chars[1])))

    if cell_addr is None:
        block_values: list[int] = [step.value for step in runway] + [value]
        block_values += [step.seed for step in chain_a]
        block_values += [0, 0]  # scratch cells D walks over during print and loada
        block_values += [step.seed for step in chain_b]
        neighbor_seeds: list[tuple[int, int]] = []
    else:
        cell_addr = mod_word(cell_addr)
        block_values = [step.value for step in runway] + [mod_word(cell_addr - 1)]
        neighbor_seeds = [(cell_addr + 1 + i, step.seed) for i, step in enumerate(chain_a)]
        base_b = cell_addr + len(chain_a) + 3
        neighbor_seeds += [(base_b + i, step.seed) for i, step in enumerate(chain_b)]

    total_pairs = len(block_values) + len(neighbor_seeds)
    block_pair_count = total_pairs if cell_addr is None else len(runway) + 1

    junk = None
    margin = 0
    for k in range(0, 256):
        start = d_entry + k + 2 * total_pairs + 1
        worst = None
        for j in range(1, block_pair_count + 1):
            storea_cell = cell_base + 6 * k + 12 * (j - 1) + 6
            slack = storea_cell - (start + (j - 1))
            if worst is None or slack < worst:
                worst = slack
            if slack <= 0:
                break
        if worst is not None and worst > 0:
            junk = k
            margin = worst
            break
    if junk is None:
        raise EntryBlocked("no junk count satisfies dead-cell seed placement")

    block_start = d_entry + junk + 2 * total_pairs + 1
    if block_start + block_pair_count - 1 >= M8_ABI_ARGC:
        raise EntryBlocked(
            f"seed block {block_start}..{block_start + block_pair_count - 1} would reach the argv ABI region"
        )
    mutable = cell_addr if cell_addr is not None else block_start + len(runway)

    ops: list[EntryOp] = []
    for _ in range(junk):
        ops.append(EntryOp("seta", 0, note="entry junk: one D tick plus six dead cells"))
    for offset, seed_value in enumerate(block_values):
        cell = block_start + offset
        ops.append(EntryOp("seta", seed_value, note=f"seed value for cell {cell}"))
        ops.append(EntryOp("storea", seed_value, cell, note=f"write seed cell {cell}"))
    for addr, seed_value in neighbor_seeds:
        ops.append(EntryOp("seta", seed_value, note=f"chain seed value for neighbor cell {addr}"))
        ops.append(EntryOp("storea", seed_value, addr, note=f"write chain seed cell {addr}"))
    ops.append(EntryOp("seta", 0, note="reset A for the runway"))
    section_indices: dict[str, int] = {}
    section_indices["ritual"] = len(ops)
    for step in runway:
        ops.append(EntryOp("op", ord(step.op), note=f"runway {step.op} seed={step.value}"))
    if cell_addr is not None:
        hop_cell = block_start + len(runway)
        ops.append(EntryOp("op", ord("j"), note=f"hop: D = mem[{hop_cell}] + 1 = {cell_addr}"))
    ops.append(EntryOp("op", ord("p"), note=f"final p rewrites cell {mutable}"))
    final_p_index = len(ops) - 1
    section_indices["verify_a"] = len(ops)
    for step in chain_a:
        ops.append(EntryOp("op", ord("p"), note=f"a-proof chain seed={step.seed}"))
    ops.append(EntryOp("op", ord("<"), note=f"print {ok_chars[0]!r}: A proof"))
    section_indices["verify_cell"] = len(ops)
    ops.append(EntryOp("loada", mutable, note=f"cell proof: A = mem[{mutable}]"))
    for step in chain_b:
        ops.append(EntryOp("op", ord("p"), note=f"cell-proof chain seed={step.seed}"))
    ops.append(EntryOp("op", ord("<"), note=f"print {ok_chars[1]!r}: cell proof"))
    section_indices["finish"] = len(ops)
    ops.append(EntryOp("seta", 10, note="newline"))
    ops.append(EntryOp("op", ord("<"), note="print newline"))
    ops.append(EntryOp("op", ord("v"), note="halt"))

    sections = section_indices

    if cell_addr is not None:
        plan_cells = sum(6 if op.kind in ("seta", "storea", "loada") else 1 for op in ops)
        span_lo = cell_base
        span_hi = cell_base + plan_cells
        live_targets = [cell_addr] + [addr for addr, _seed in neighbor_seeds]
        for addr in live_targets:
            if span_lo <= addr < span_hi:
                raise EntryBlocked(f"live target cell {addr} collides with the macro's own code span")
            if addr >= M8_ABI_ARGC:
                raise EntryBlocked(f"live target cell {addr} would reach the argv ABI region")
            if block_start <= addr <= block_start + block_pair_count - 1:
                raise EntryBlocked(f"live target cell {addr} collides with the planner seed block")

    known: dict[int, int] = {}
    for offset, seed_value in enumerate(block_values):
        known[block_start + offset] = seed_value
    if cell_addr is not None:
        known[cell_addr] = value
    for addr, seed_value in neighbor_seeds:
        known[addr] = seed_value

    rows: list[EntryRow] = []
    a = mod_word(start_a)
    cell = cell_base
    d = d_entry
    for index, op in enumerate(ops):
        before = a
        if op.kind == "seta":
            a = mod_word(op.value)
            span = 6
        elif op.kind == "storea":
            span = 6
        elif op.kind == "loada":
            a = mod_word(known.get(op.value, 0))
            span = 6
        else:
            glyph = chr(op.value)
            if glyph == "j":
                d = mod_word(known[d])
            elif glyph == "p":
                a = crazy(a, known[d])
                known[d] = a
            elif glyph == "*":
                a = rotate_right(known[d])
                known[d] = a
            span = 1
        rows.append(EntryRow(d_entry + index + 1, op.kind, cell, d, before, a, op.note))
        cell += span
        d = mod_word(d + 1)

    final_row = rows[final_p_index]
    if cell_addr is None:
        checks = [
            f"D at first runway p is {block_start}, the first seed cell",
            f"worst seed write lands {margin} cell(s) below its own storea, inside dead cells",
            f"seed block {fmt_span(block_start, len(block_values))} stays below live code and below {M8_ABI_ARGC}",
            f"final A equals {target}",
            f"loada {mutable} returns {target}, proving the mutable cell was rewritten",
            f"expected program output: {ok_chars} + newline, exit code 0",
        ]
    else:
        neighbor_list = " ".join(str(addr) for addr, _seed in neighbor_seeds)
        checks = [
            f"D at first runway p is {block_start}, the first seed cell",
            f"hop cell {block_start + len(runway)} holds {mod_word(cell_addr - 1)}, so j sends D to live cell {cell_addr}",
            f"worst block seed write lands {margin} cell(s) below its own storea, inside dead cells",
            f"chain seed cells [{neighbor_list}] sit outside the macro code span, in caller scratch",
            f"final A equals {target}",
            f"loada {cell_addr} returns {target}, proving the live cell was rewritten",
            f"expected program output: {ok_chars} + newline, exit code 0",
        ]
    if final_row.a_after != target:
        raise EntryBlocked(f"internal simulation mismatch: A={final_row.a_after} want {target}")

    return EntryPlan(
        value=value,
        target=target,
        mask=node.value,
        runway=runway,
        chain_a=tuple(chain_a),
        chain_b=tuple(chain_b),
        ok_chars=ok_chars,
        d_entry=d_entry,
        cell_base=cell_base,
        junk=junk,
        block_start=block_start,
        block_values=tuple(block_values),
        ops=tuple(ops),
        rows=tuple(rows),
        checks=tuple(checks),
        sections=sections,
        margin=margin,
        cell_addr=cell_addr,
        neighbor_seeds=tuple(neighbor_seeds),
    )


def print_entry_report(plan: EntryPlan) -> None:
    mode = f" live-cell={plan.cell_addr}" if plan.cell_addr is not None else ""
    print(
        f"plan-entry value={plan.value} target={plan.target} ok={plan.ok_chars} "
        f"d-entry={plan.d_entry} cell-base={plan.cell_base}{mode}"
    )
    if plan.cell_addr is not None:
        print(
            "model: full straight-line scroll in live-cell mode: D ticks, dead-frame runway seeds, "
            "j hop to the caller's cell, final p, proof chains in neighbor scratch"
        )
    else:
        print(
            "model: full straight-line scroll: D ticks from program start, dead-frame seed cells, "
            "runway, final p, proof chains"
        )
    print_word("value", plan.value)
    print_word("target", plan.target)
    print_word("chosen mask", plan.mask)
    print(f"runway depth={len(plan.runway)} junk={plan.junk} block={fmt_span(plan.block_start, plan.block_len)}")
    print("runway steps:")
    for i, step in enumerate(plan.runway, 1):
        print(f"  {i}: {step.op} seed={step.value}")
    print("a-proof chain (from final A):")
    a = plan.target
    for step in plan.chain_a:
        print(f"  crazy({a}, {step.seed}) = {step.result}")
        a = step.result
    print(f"cell-proof chain (from loada {plan.mutable_addr}):")
    a = plan.target
    for step in plan.chain_b:
        print(f"  crazy({a}, {step.seed}) = {step.result}")
        a = step.result
    print("block cells:")
    if plan.cell_addr is None:
        roles = (
            [f"runway seed {i}" for i in range(len(plan.runway))]
            + ["mutable cell"]
            + [f"chain-a seed {i}" for i in range(len(plan.chain_a))]
            + ["scratch (print tick)", "scratch (loada tick)"]
            + [f"chain-b seed {i}" for i in range(len(plan.chain_b))]
        )
    else:
        roles = [f"runway seed {i}" for i in range(len(plan.runway))] + [
            f"hop pointer: j sends D to live cell {plan.cell_addr}"
        ]
    for offset, seed_value in enumerate(plan.block_values):
        print(f"  mem[{plan.block_start + offset}] = {seed_value:5d}  ({roles[offset]})")
    if plan.cell_addr is not None:
        print("live neighbor seed cells (caller scratch):")
        for addr, seed_value in plan.neighbor_seeds:
            print(f"  mem[{addr}] = {seed_value:5d}")
    print("instructions:")
    print("   n kind       cell     D  A_before  A_after  note")
    for row in plan.rows:
        print(
            f"{row.n:4d} {row.kind:8s} {row.cell:6d} {row.d_at:5d} {row.a_before:8d} "
            f"{row.a_after:8d}  {row.note}"
        )
    print("checks:")
    for check in plan.checks:
        print(f"  ok: {check}")
    print("not proven here: loops or re-entry, self-cipher-safe placement beyond one pass,")
    print("live ABI cells as the mutable target, entry by jump instead of fall-through")


def emit_entry_scroll(plan: EntryPlan) -> str:
    lines = ["start:"]
    for index, op in enumerate(plan.ops):
        for label in ("ritual", "verify_a", "verify_cell", "finish"):
            if plan.sections.get(label) == index:
                lines.append(f"{label}:")
        if op.kind == "seta":
            lines.append(f"    seta {op.value}")
        elif op.kind == "storea":
            lines.append(f"    storea {op.target}")
        elif op.kind == "loada":
            lines.append(f"    loada {op.value}")
        else:
            lines.append(f"    op {chr(op.value)}")
    return "\n".join(lines) + "\n"


def cmd_plan_entry(args: argparse.Namespace) -> int:
    try:
        plan = plan_entry(
            args.value,
            ok_chars=args.ok_str,
            start_a=args.start_a,
            max_depth=args.max_depth,
            mask_limit=args.mask_limit,
            constants=args.constants,
            cell_addr=args.cell_addr,
        )
    except EntryBlocked as exc:
        print(f"plan-entry value={mod_word(args.value)}: {exc}")
        print("physical note: use a layout rewrite, a multi-stage cell transform, or keep friendly arithmetic here")
        return 0
    if args.emit_scroll:
        print(emit_entry_scroll(plan), end="")
    else:
        print_entry_report(plan)
    return 0


def cmd_table(_args: argparse.Namespace) -> int:
    print("crazy(A, D) per trit")
    print("        A trit")
    print("D trit   0  1  2")
    for d, row in enumerate(CRAZY_TABLE):
        print(f"   {d}     {row[0]}  {row[1]}  {row[2]}")
    return 0


def cmd_trits(args: argparse.Namespace) -> int:
    print_word("value", args.value)
    return 0


def cmd_word(args: argparse.Namespace) -> int:
    a = mod_word(args.a)
    d = mod_word(args.d)
    result = crazy(a, d)
    print_word("A", a)
    print_word("D", d)
    print_word("crazy(A,D)", result)
    return 0


def cmd_rotate(args: argparse.Namespace) -> int:
    value = mod_word(args.value)
    print_word("start", value)
    for step in range(1, args.steps + 1):
        value = rotate_right(value)
        print_word(f"rot{step}", value)
    return 0


def cmd_search_byte(args: argparse.Namespace) -> int:
    constants = normalize_constants(args.constants)
    target = args.target % 256
    max_depth = max(0, args.max_depth)
    limit = max(1, args.limit)

    print(f"search-byte target={target} start={mod_word(args.start)} max_depth={max_depth}")
    print("model: toy A graph with rotA plus crazy(A, constant)")
    print("constants:", " ".join(str(c) for c in constants))

    solutions, seen_count = bfs_find(
        start=args.start,
        max_depth=max_depth,
        limit=limit,
        constants=constants,
        predicate=lambda value: value % 256 == target,
    )
    print_solutions(solutions)
    if not solutions:
        print("no sequence found within depth")
    print(f"seen={seen_count}")
    return 0


def cmd_search_word(args: argparse.Namespace) -> int:
    constants = normalize_constants(args.constants)
    target = mod_word(args.target)
    max_depth = max(0, args.max_depth)
    limit = max(1, args.limit)

    print(f"search-word target={target} start={mod_word(args.start)} max_depth={max_depth}")
    print("model: toy A graph with rotA plus crazy(A, constant)")
    print("constants:", " ".join(str(c) for c in constants))

    solutions, seen_count = bfs_find(
        start=args.start,
        max_depth=max_depth,
        limit=limit,
        constants=constants,
        predicate=lambda value: value == target,
    )
    print_solutions(solutions)
    if not solutions:
        print("no sequence found within depth")
    print(f"seen={seen_count}")
    return 0


def cmd_profile(args: argparse.Namespace) -> int:
    constants = normalize_constants(args.constants)
    start = mod_word(args.start)
    max_depth = max(0, args.max_depth)
    target = None if args.target is None else mod_word(args.target)
    seen = {start}
    layer = [start]
    target_depth = 0 if target == start else None

    print(f"profile start={start} max_depth={max_depth}")
    print("model: toy A graph with rotA plus crazy(A, constant)")
    if target is not None:
        print(f"target={target}")
    print("constants:", " ".join(str(c) for c in constants))
    mark = " target" if target_depth == 0 else ""
    print(f"depth 0: new=1 total=1{mark}")

    for depth in range(1, max_depth + 1):
        next_layer: list[int] = []
        for value in layer:
            for new_value, _label in toy_next_states(value, constants):
                if new_value in seen:
                    continue
                seen.add(new_value)
                next_layer.append(new_value)
        if target is not None and target_depth is None and target in next_layer:
            target_depth = depth
        mark = " target" if target_depth == depth else ""
        print(f"depth {depth}: new={len(next_layer)} total={len(seen)}{mark}")
        layer = next_layer
        if not layer:
            break

    if target is not None:
        if target_depth is None:
            print("target not reached within depth")
        else:
            print(f"target reached at depth {target_depth}")
    return 0


def cmd_solve_crazy(args: argparse.Namespace) -> int:
    solve = solve_crazy(args.source, args.target)
    limit = max(1, args.limit)
    print(f"solve-crazy source={solve.source} target={solve.target}")
    print_word("source", solve.source)
    print_word("target", solve.target)
    if not solve.possible:
        print("no one-p mask exists")
        for pos, dt, tt in solve.blockers:
            print(f"  blocked trit {pos}: D={dt} target={tt}")
        return 0

    print(f"one-p masks={solve.mask_count} showing={min(limit, solve.mask_count)}")
    for idx, mask in enumerate(masks_for_solve(solve, limit), 1):
        print_word(f"mask {idx}", mask)
        print(f"  check crazy(mask, source)={crazy(mask, solve.source)}")
    return 0


def cmd_runway_word(args: argparse.Namespace) -> int:
    constants = normalize_constants(args.constants)
    target = mod_word(args.target)
    max_depth = max(0, args.max_depth)
    limit = max(1, args.limit)

    print(f"runway-word target={target} start-A={mod_word(args.start_a)} max_depth={max_depth}")
    print("model: generated D-runway with p seed=N and * seed=N")
    print("constants:", " ".join(str(c) for c in constants))
    solutions, seen_count = bfs_find(
        start=args.start_a,
        max_depth=max_depth,
        limit=limit,
        constants=constants,
        predicate=lambda value: value == target,
        transitions=runway_next_states,
        allow_empty=True,
    )
    print_solutions(solutions)
    if not solutions:
        print("no runway sequence found within depth")
    print(f"seen={seen_count}")
    return 0


def cmd_plan_increment(args: argparse.Namespace) -> int:
    constants = normalize_constants(args.constants)
    source = mod_word(args.value)
    target = mod_word(source + 1)
    solve = solve_crazy(source, target)
    mask_limit = max(1, args.mask_limit)
    max_depth = max(0, args.max_depth)

    print(f"plan-increment cell={source} target={target} start-A={mod_word(args.start_a)}")
    print("model: materialize A on a generated D-runway, then one final p on the mutable cell")
    print_word("cell", source)
    print_word("target", target)

    if not solve.possible:
        print("direct final p is impossible")
        for pos, dt, tt in solve.blockers:
            print(f"  blocked trit {pos}: D={dt} target={tt}")
        print("physical note: use a layout rewrite, a multi-stage cell transform, or keep friendly arithmetic here")
        return 0

    all_masks = masks_for_solve(solve)
    shown_masks = all_masks[:mask_limit]
    print(f"direct final p masks={solve.mask_count} searching first={len(shown_masks)} max_depth={max_depth}")
    node, seen_count = find_runway_plan_for_masks(
        start_a=args.start_a,
        masks=shown_masks,
        max_depth=max_depth,
        constants=constants,
    )
    if node is None:
        print(f"no runway materializer found for the searched masks; seen={seen_count}")
        return 0

    print_word("chosen mask", node.value)
    print(f"runway depth={len(node.steps)} seen={seen_count}")
    if not node.steps:
        print("  0: A already has the chosen mask")
    for i, step in enumerate(node.steps, 1):
        print(f"  {i}: {step}")
    print("final p:")
    print(f"  precondition: D points at the mutable cell containing {source}")
    print(f"  result: crazy({node.value}, {source}) = {crazy(node.value, source)}")
    print("physical note: C/D routing and self-cipher-safe placement are not solved by this planner yet")
    return 0


def cmd_increment_profile(args: argparse.Namespace) -> int:
    constants = normalize_constants(args.constants)
    start = mod_word(args.start)
    count = max(1, args.count)
    max_depth = max(0, args.max_depth)
    mask_limit = max(1, args.mask_limit)
    direct = 0
    planned = 0

    print(f"increment-profile start={start} count={count} start-A={mod_word(args.start_a)} max_depth={max_depth}")
    print("model: one final p on the mutable cell, optional generated runway for A mask")
    for offset in range(count):
        source = mod_word(start + offset)
        target = mod_word(source + 1)
        solve = solve_crazy(source, target)
        if not solve.possible:
            print(f"{source:5d} -> {target:5d}: direct-p no  blocked {short_blocker(solve)}")
            continue
        direct += 1
        masks = masks_for_solve(solve, mask_limit)
        node, _seen_count = find_runway_plan_for_masks(
            start_a=args.start_a,
            masks=masks,
            max_depth=max_depth,
            constants=constants,
        )
        if node is None:
            print(f"{source:5d} -> {target:5d}: direct-p yes masks={solve.mask_count:<4d} runway no")
            continue
        planned += 1
        print(
            f"{source:5d} -> {target:5d}: direct-p yes masks={solve.mask_count:<4d} "
            f"mask={node.value:<5d} runway-depth={len(node.steps)}"
        )

    print(f"summary: direct-p={direct}/{count} runway-planned={planned}/{count}")
    return 0


def cmd_route_window(args: argparse.Namespace) -> int:
    steps = max(1, args.steps)
    c_start = mod_word(args.c_start)
    d_start = mod_word(args.d_start)
    code_cells = span_cells(c_start, steps)
    data_cells = span_cells(d_start, steps)
    overlap = sorted(code_cells & data_cells)
    print(f"route-window c-start={c_start} d-start={d_start} steps={steps}")
    print("model: straight-line C and D, both advance by one after every executed instruction")
    print(f"code-span: {fmt_span(c_start, steps)}")
    print(f"data-span: {fmt_span(d_start, steps)}")
    print("overlap:", "no" if not overlap else "yes " + " ".join(str(x) for x in overlap[:8]))
    print("idx      C      D")
    print("--- ------ ------")
    for idx in range(steps):
        print(f"{idx:3d} {mod_word(c_start + idx):6d} {mod_word(d_start + idx):6d}")
    return 0


def cmd_route_plan_increment(args: argparse.Namespace) -> int:
    constants = normalize_constants(args.constants)
    source = mod_word(args.value)
    target = mod_word(source + 1)
    solve = solve_crazy(source, target)
    mask_limit = max(1, args.mask_limit)
    max_depth = max(0, args.max_depth)
    c_start = mod_word(args.c_start)

    print(f"route-plan-increment value={source} target={target} start-A={mod_word(args.start_a)}")
    print("model: straight-line C/D route for generated runway steps plus one final mutable-cell p")
    print_word("value", source)
    print_word("target", target)

    if not solve.possible:
        print("direct final p is impossible")
        for pos, dt, tt in solve.blockers:
            print(f"  blocked trit {pos}: D={dt} target={tt}")
        print("routing note: this value needs a mixed strategy before C/D layout matters")
        return 0

    masks = masks_for_solve(solve, mask_limit)
    node, seen_count = find_runway_plan_for_masks(
        start_a=args.start_a,
        masks=masks,
        max_depth=max_depth,
        constants=constants,
    )
    if node is None:
        print(f"no runway materializer found for first {len(masks)} masks; seen={seen_count}")
        return 0

    runway = [parse_runway_step(step) for step in node.steps]
    steps = runway + [RouteStep("p", source, "mutable")]
    if args.mutable_addr is None:
        d_start = mod_word(args.d_start)
        mutable_addr = mod_word(d_start + len(runway))
    else:
        mutable_addr = mod_word(args.mutable_addr)
        d_start = mod_word(mutable_addr - len(runway))

    rows = route_rows(steps=steps, start_a=args.start_a, c_start=c_start, d_start=d_start)
    print_word("chosen mask", node.value)
    print(f"runway depth={len(runway)} seen={seen_count}")
    print(f"mutable-address={mutable_addr}")
    print_route(rows, c_start, d_start)
    print("requirements:")
    for row in rows:
        code_req = f"code[{row.c}] decoded-op {row.op}"
        data_req = f"mem[{row.d}] starts as {row.value}"
        print(f"  step {row.index}: {code_req}; {data_req} ({row.role})")
    final = rows[-1]
    print("result:")
    print(f"  final A={final.a_after}")
    print(f"  mutable cell {mutable_addr} becomes {final.a_after}")
    if final.a_after != target:
        print("  warning: route did not reach target")
    print("routing note: this proves a straight segment only; entering it with the right C and D is still a codegen job")
    print("routing note: loops and re-entry also need self-cipher-safe placement")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="explore M8/Malbolge crazy operation")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("table", help="print the trit-level crazy table")
    p.set_defaults(func=cmd_table)

    p = sub.add_parser("trits", help="show decimal, ternary, and low byte")
    p.add_argument("value", type=lambda s: int(s, 0))
    p.set_defaults(func=cmd_trits)

    p = sub.add_parser("word", help="compute crazy(A, D)")
    p.add_argument("a", type=lambda s: int(s, 0))
    p.add_argument("d", type=lambda s: int(s, 0))
    p.set_defaults(func=cmd_word)

    p = sub.add_parser("rotate", help="rotate a 10-trit word right")
    p.add_argument("value", type=lambda s: int(s, 0))
    p.add_argument("--steps", type=int, default=1)
    p.set_defaults(func=cmd_rotate)

    p = sub.add_parser("search-byte", help="toy BFS for values whose low byte matches target")
    p.add_argument("target", type=lambda s: int(s, 0))
    p.add_argument("--start", type=lambda s: int(s, 0), default=0)
    p.add_argument("--max-depth", type=int, default=4)
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--constants", type=lambda s: int(s, 0), nargs="*")
    p.set_defaults(func=cmd_search_byte)

    p = sub.add_parser("search-word", help="toy BFS for one exact 10-trit target word")
    p.add_argument("target", type=lambda s: int(s, 0))
    p.add_argument("--start", type=lambda s: int(s, 0), default=0)
    p.add_argument("--max-depth", type=int, default=5)
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--constants", type=lambda s: int(s, 0), nargs="*")
    p.set_defaults(func=cmd_search_word)

    p = sub.add_parser("profile", help="count exact words reachable by depth in the toy transform graph")
    p.add_argument("--start", type=lambda s: int(s, 0), default=0)
    p.add_argument("--target", type=lambda s: int(s, 0))
    p.add_argument("--max-depth", type=int, default=5)
    p.add_argument("--constants", type=lambda s: int(s, 0), nargs="*")
    p.set_defaults(func=cmd_profile)

    p = sub.add_parser("solve-crazy", help="invert one crazy(A, source) = target rewrite")
    p.add_argument("source", type=lambda s: int(s, 0))
    p.add_argument("target", type=lambda s: int(s, 0))
    p.add_argument("--limit", type=int, default=5)
    p.set_defaults(func=cmd_solve_crazy)

    p = sub.add_parser("runway-word", help="BFS in the generated D-runway model")
    p.add_argument("target", type=lambda s: int(s, 0))
    p.add_argument("--start-a", type=lambda s: int(s, 0), default=0)
    p.add_argument("--max-depth", type=int, default=5)
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--constants", type=lambda s: int(s, 0), nargs="*")
    p.set_defaults(func=cmd_runway_word)

    p = sub.add_parser("plan-increment", help="plan x -> x+1 through an A mask plus one final p")
    p.add_argument("value", type=lambda s: int(s, 0))
    p.add_argument("--start-a", type=lambda s: int(s, 0), default=0)
    p.add_argument("--max-depth", type=int, default=5)
    p.add_argument("--mask-limit", type=int, default=32)
    p.add_argument("--constants", type=lambda s: int(s, 0), nargs="*")
    p.set_defaults(func=cmd_plan_increment)

    p = sub.add_parser("increment-profile", help="profile x -> x+1 direct-p masks across a range")
    p.add_argument("start", type=lambda s: int(s, 0))
    p.add_argument("--count", type=int, default=16)
    p.add_argument("--start-a", type=lambda s: int(s, 0), default=0)
    p.add_argument("--max-depth", type=int, default=5)
    p.add_argument("--mask-limit", type=int, default=32)
    p.add_argument("--constants", type=lambda s: int(s, 0), nargs="*")
    p.set_defaults(func=cmd_increment_profile)

    p = sub.add_parser("route-window", help="show straight-line C/D cells for a generated segment")
    p.add_argument("--c-start", type=lambda s: int(s, 0), default=1000)
    p.add_argument("--d-start", type=lambda s: int(s, 0), default=3000)
    p.add_argument("--steps", type=int, default=5)
    p.set_defaults(func=cmd_route_window)

    p = sub.add_parser("route-plan-increment", help="layout a planned x -> x+1 ritual on straight-line C/D")
    p.add_argument("value", type=lambda s: int(s, 0))
    p.add_argument("--start-a", type=lambda s: int(s, 0), default=0)
    p.add_argument("--max-depth", type=int, default=5)
    p.add_argument("--mask-limit", type=int, default=32)
    p.add_argument("--c-start", type=lambda s: int(s, 0), default=1000)
    p.add_argument("--d-start", type=lambda s: int(s, 0), default=3000)
    p.add_argument("--mutable-addr", type=lambda s: int(s, 0))
    p.add_argument("--constants", type=lambda s: int(s, 0), nargs="*")
    p.set_defaults(func=cmd_route_plan_increment)

    p = sub.add_parser("plan-entry", help="plan a full straight-line scroll that rewrites x -> x+1")
    p.add_argument("value", type=lambda s: int(s, 0))
    p.add_argument("--ok-str", default="OK")
    p.add_argument("--start-a", type=lambda s: int(s, 0), default=0)
    p.add_argument("--max-depth", type=int, default=4)
    p.add_argument("--mask-limit", type=int, default=16)
    p.add_argument("--cell-addr", type=lambda s: int(s, 0), help="target a caller-owned live cell instead of a planner-placed block cell")
    p.add_argument("--constants", type=lambda s: int(s, 0), nargs="*")
    p.add_argument("--emit-scroll", action="store_true")
    p.set_defaults(func=cmd_plan_entry)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
