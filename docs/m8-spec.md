# M8: 8th Circle Malbolge dialect

M8 is the Malbolge-derived VM used by 8th Circle Linux userland. It is cursed on purpose, but it has enough ABI surface to act as PID 1, run a shell, and talk to Linux syscalls through a small runtime. Generated `.mb` files are printable glyph streams loaded into VM memory, not decimal word dumps.

## Goals

- Preserve enough Malbolge DNA that this is not just a themed bytecode VM.
- Keep OS policy and userland behavior in M8 images.
- Keep the C runtime small, boring, and mostly limited to execution plus syscall bridging.
- Make printable `.mb` glyph programs reproducible from human-readable `.m8a` scrolls.

## Non-goals

- Classic Malbolge compatibility at all costs.
- Performance.
- Developer comfort. Obviously.

## Machine model v0

- Word size: 10 trits, decimal range `0..59048`.
- Memory size: `59049` cells.
- Registers:
  - `A`: accumulator.
  - `C`: code pointer.
  - `D`: data pointer.
- Initial state: `A = C = D = 0`.
- Code and data share the same memory image.

## Source loading

`.mb` is a printable source stream. The loader skips whitespace, then loads each graphic ASCII character directly into VM memory. For each loaded source cell, the runtime checks:

```text
33 <= mem[address] <= 126
op = xlat1[(mem[address] - 33 + address) mod 94]
op is a known classic or M8 extension operation
```

After the source stream ends, remaining memory is filled with the Malbolge-style crazy operation.

Strict `.mb` mode does not accept old decimal memory images. A file starting with the old raw-image header is a loader error, not a compatibility path. `--classic SOURCE` remains only as a runtime convenience for loading plain printable Malbolge/M8 source directly.

## Instruction decoding

A cell at `C` must be printable ASCII, `33..126`, to execute as code.

```text
op = xlat1[(mem[C] - 33 + C) mod 94]
```

The runtime supports classic decoded operations plus M8 extension ops `@`, `!`, `?`, `=`, `~`, `#`, `+`, `-`, `[`, `]`, `:`, `^`, `$`, and `` ` ``.

## Classic operations

| op | Meaning |
| --- | --- |
| `j` | `D = mem[D]` |
| `i` | `C = mem[D]` |
| `*` | rotate `mem[D]` right by one trit, store to `mem[D]` and `A` |
| `p` | crazy-op `A` with `mem[D]`, store to `mem[D]` and `A` |
| `/` | input byte to `A`, EOF = `59048` |
| `<` | output `A % 256` |
| `v` | halt |
| `o` | nop |

Classic operations self-cipher the executed instruction cell with `xlat2`, then advance `C` and `D`.

## Extension cipher generations

M8 extension ops self-cipher too:

```text
@ ! ? = ~ # + - [ ] : ^ $ `
```

After any printable instruction cell executes, the runtime replaces that cell with `xlat2[mem[C] - 33]`. For extension cells, the runtime records the original decoded operation and the expected encrypted cell generation when the image is loaded. If a loop reaches the same extension instruction again, the current encrypted glyph still dispatches as the original M8 op, then advances to the next encrypted generation.

C4 narrowed this bridge. The runtime no longer scans all memory cells and tags every extension-looking glyph. It structurally walks the loaded source from cell 0, marks extension opcode cells, and skips their inline frame cells using the same frame widths the executor uses. That means printable frame glyphs stay source-valid, but they are not treated as extension instruction lineage just because their address-dependent decode happens to look like `@` or `?`.

That keeps the visible memory behavior close to Malbolge - code mutates after execution - without forcing every shell loop to rewrite its own trap and branch cells by hand.

## Printable frame encoding

`.mb` files are printable source streams. A raw M8 word can be any `0..59048` value, so inline frame words are encoded as five printable base-94 cells:

```text
word = (cell0 - 33)
     + 94 * (cell1 - 33)
     + 94^2 * (cell2 - 33)
     + 94^3 * (cell3 - 33)
     + 94^4 * (cell4 - 33)
```

The runtime reduces that value modulo `59049`. Five cells give the assembler enough alternate spellings for each word to choose glyphs that decode to valid M8 operations at their own addresses. This keeps syscall numbers, pointers, labels, and constants inside a Malbolge-looking source stream instead of a decimal dump.

## `@` trap

Decoded instruction `@` invokes the runtime syscall bridge. It has a fixed six-word inline frame. In the `.mb` file each frame word occupies five printable cells:

```text
C + 0: encoded @ instruction cell
C + 1..5: syscall number
C + 6..10: arg0
C + 11..15: arg1
C + 16..20: arg2
C + 21..25: arg3
C + 26..30: arg4
```

After the trap, execution resumes at `C + 31`. The return value is placed in `A` modulo `59049`. The runtime also stores whether the previous trap returned a host error, so branch modes can test it.

Trap arguments may use assembler symbol `A` or `ACC`. The assembler emits reserved word `59047`, and the runtime substitutes the current accumulator value before dispatch.

Example:

```text
trap open issue_path 0 0
trap read A issue_buf 512
trap write 1 issue_buf A
```

## `!` jump

Decoded instruction `!` performs an absolute jump. Its target is one printable encoded frame word, so the instruction occupies six cells.

Execution resumes exactly at `target`.

## `?` branch

Decoded instruction `?` performs a conditional absolute jump. Its target and mode are encoded frame words, so the instruction occupies eleven cells.

| mode | assembler | condition |
| ---: | --- | --- |
| `0` | `branch` | always |
| `1` | `branchz` | `A == 0` |
| `2` | `branchnz` | `A != 0` |
| `3` | `brancherr` | previous trap returned a Linux error |
| `4` | `branchok` | previous trap did not return a Linux error |

## `=` store and `~` load

These convenience ops move values between `A` and VM memory:

```text
storea label
loada label
```

`storea label` stores `A` into `mem[label]`.
`loada label` loads `mem[label]` into `A`.

## Small data/control ops

These ops exist so shell parsing can be written in M8 instead of as C helper traps.

| assembler | decoded op | effect |
| --- | --- | --- |
| `seta X` | `#` | `A = X` |
| `addi X` | `+` | `A = A + X` |
| `subi X` | `-` | `A = A - X` |
| `addm label` | `[` | `A = A + mem[label]` |
| `subm label` | `]` | `A = A - mem[label]` |
| `cmpm label` | `:` | `A = 0` if `A == mem[label]`, else `1` |
| `loadi label` | `^` | `A = mem[mem[label]]` |
| `storei label` | `$` | `mem[mem[label]] = A` |
| `jumpm label` | `` ` `` | `C = mem[label]` |

The first real consumers are `msh` and the early command images. They trim input, check command names, copy arguments, parse directory entries, and parse MFS records in M8 code.

## Implemented trap surface v0

Linux syscall numbers are used where practical. Shell-specific helper traps have been removed from the current shell path.

| number | name | args | status |
| ---: | --- | --- | --- |
| `0` | `read` | `fd, vm_ptr, len` | Linux syscall bridge |
| `1` | `write` | `fd, vm_ptr, len` | Linux syscall bridge |
| `2` | `open` | `path_ptr, flags, mode` | Linux syscall bridge |
| `3` | `close` | `fd` | Linux syscall bridge |
| `33` | `dup2` | `oldfd, newfd` | Linux syscall bridge |
| `34` | `pause` | none | Linux syscall bridge |
| `35` | `nanosleep` | `seconds, nanoseconds` | Linux syscall bridge |
| `39` | `getpid` | none | Linux syscall bridge |
| `57` | `fork` | none | Linux syscall bridge |
| `59` | `execve` | `path_ptr, argv_ptr, envp_ptr` | Linux syscall bridge |
| `60` | `exit` | `code` | VM/runtime exit path |
| `61` | `wait4` | `pid, status_ptr_or_0, options, rusage_ptr_ignored` | Linux syscall bridge |
| `79` | `getcwd` | `vm_ptr, max_len` | Linux syscall bridge |
| `80` | `chdir` | `path_ptr` | Linux syscall bridge |
| `83` | `mkdir` | `path_ptr, mode` | Linux syscall bridge |
| `112` | `setsid` | none | Linux syscall bridge |
| `165` | `mount` | `source_ptr, target_ptr, fstype_ptr, flags, data_ptr_or_0` | Linux syscall bridge |
| `217` | `getdents64` | `fd, vm_ptr, max_len` | Linux syscall bridge |


## Startup materializer

Human-readable `.m8a` scrolls still contain strings, words, pointer vectors, and reserved buffers. The assembler keeps the final `.mb` printable by generating startup code before the real program:

```text
seta VALUE
storea ADDRESS
...
jump start
```

That materializer writes initialized data cells into VM memory. Large `zero N` buffers are reserved as printable filler and are usually overwritten later by syscalls or M8 copy routines, so the assembler does not emit thousands of pointless zero stores.

## Process argv ABI

When the runtime starts an M8 image, it writes a small argv block near the top of VM memory:

| symbol | address | meaning |
| --- | ---: | --- |
| `M8_ARGC` | `58000` | argument count |
| `M8_ARGV` | `58001` | pointer to the argv pointer vector |
| `M8_ARGVEC` | `58016` | start of the argv pointer vector |
| `M8_ARG_STRINGS` | `58100` | start of argv string storage |

For `/bin/m8 /bin/cat.mb /etc/issue`, an M8 program sees:

```text
argc = 2
argv[0] = "/bin/cat.mb"
argv[1] = "/etc/issue"
```

The assembler exposes those addresses as symbols. Current command images use this to read their arguments without a special C helper.

## Shell purity notes

The current `msh.mb` path does not use shell-specific C helper traps. Input is read through the normal `read` syscall bridge in a one-byte loop and trimmed in M8 code.

`msh.mb` handles prompt, command parsing, `cd`, `help`, `exit`, argv-vector building, `fork`, `execve`, and `wait4`. For external commands it builds `/bin/NAME.mb` in VM memory, checks that it can open that image, splits up to eight whitespace-separated arguments, then launches `/bin/m8 /bin/NAME.mb [ARGS...]`.

Friendly aliases map `mfsls` to `/bin/mfs.ls.mb` and `mfscat` to `/bin/mfs.cat.mb`.

`echo.mb` and `ls.mb` loop over the runtime argv ABI in M8. `cat.mb` walks the same argv vector through unrolled slot probes, which costs more source cells but no friendly arithmetic helpers. `ls.mb` calls the Linux `getdents64` bridge and parses `linux_dirent64` records in M8. MFS commands read `/mfs/root.mfs` and parse the MFS v0 header/table in M8:

- `mfs.ls.mb` lists entry names.
- `mfs.cat.mb NAME` copies payload bytes from the image buffer.
- `mfs.info.mb` prints entry count, image size, entry size, and file names.
- `mfs.stat.mb NAME` prints name, size, and payload offset.

The M8 readers currently consume low 16-bit little-endian fields, which is enough for the tiny 8192-byte bootstrap image buffer. Larger MFS work should grow proper multiword integer handling instead of pretending this is enough forever.

## Crazy-op groundwork

Classic Malbolge gets data motion mostly from two hostile primitives:

- `*` rotates the current `D` cell in ternary and copies it to `A`.
- `p` writes `crazy(A, mem[D])` back to `mem[D]` and `A`.

The crazy operation is tritwise. For each trit position:

```text
        A trit
D trit   0  1  2
   0     1  0  0
   1     1  0  2
   2     2  2  1
```

Current M8 still has friendly arithmetic helpers:

```text
addi subi addm subm cmpm
```

Those helpers are arithmetic debt. They keep `msh`, argv parsing, directory walking, MFS parsing, and decimal printing practical while the distro is still young. C5 does not remove them blindly. Instead, `tools/m8crazy.py` explores ternary/crazy transforms and `tools/m8_arith_audit.py` measures helper usage so future work can lower selected routines into generated crazy/rotate rituals safely.

The first low-risk reduction switched `cat`, `echo`, and `ls` from argv index arithmetic to argv-vector cursors. A second small reduction made `cat.m8a` zero-debt by unrolling the runtime argv slots instead of stepping an argv pointer with `addi 1`. That is not crazy-op lowering yet, but it removes avoidable arithmetic scaffolding before the harder work begins.

C6 lowered the measured total from `180` to `150` with three idioms that are layout work, not new math. Label arithmetic folds fixed offsets into addressing: `seta mfs_buf` followed by `addi 12` becomes one `seta mfs_buf+12`. Direct slot loads read the argv vector without stepping it: `loada M8_ARGVEC+1` fetches the first argument pointer, replacing the `M8_ARGC` compare plus `M8_ARGV` walk. Byte-per-trap output replaces buffer copies: each byte goes out through its own `trap write 1 scratch 1`, which removes destination pointers, index counters, and length limits such as the old 95-byte name cap and the 4096-byte payload cap. The remaining debt is dominated by runtime-value pointer stepping, decimal printing, and directory parsing, which need compare primitives or mixed per-value masks that do not exist yet.

C7 added four more layout idioms, all proven in `msh.m8a` and `mfs.cat.m8a`. Write cursors replace index arithmetic: instead of `seta buf` plus `addm idx` per byte, a cursor cell starts at `seta buf` and advances with `addi 1` after each store. End-pointer words replace limit counters: `line_end`, `cmd_end`, and `arg_end` are static words such as `word line_buf+256`, and the loop compares the cursor against the end cell with one `cmpm`. NUL-bound compares replace counted string equality: `cmd_eq` walks both strings until they disagree or both hit zero, so compare lengths and index counters are gone. Sentinel-terminated pointer tables replace counted vector copies: `arg_ptrs` always holds a `0` slot one past the last argument, so `build_exec_argv` copies with `loadi`/`storei` until it loads the sentinel. `read_line` drops CR and LF at read time, which deleted the trim routine entirely.

The same pass produced the pointer-chase idiom in `scrolls/tests/chase_demo.m8a`. A chain of cells where each cell holds the absolute address of the next one advances with `loadi cur` plus `storea cur` and terminates on a stored `0`, with no arithmetic at all. The payload is the address itself: nodes sit at addresses whose low byte is the character to print, because `trap write` emits `mem[cell] & 0xff`. The demo nodes live at `591` (`O`), `587` (`K`), and `545` (`!`), reached with `zero` padding computed from the assembler label dump. `make chase-test` runs it and expects `OK!`. This is the template for linked structures in later MFS work: a manifest of pointer words turns table walks into pure chases.

Current C5 tools:

```sh
make arithmetic-audit
make arithmetic-audit-details
make arithmetic-audit-budget
make crazy-lab
make crazy-word-lab
make crazy-planner-lab
make crazy-route-lab
make crazy-entry-lab
make crazy-ritual-test
```

`crazy-word-lab` keeps the first exact-word search and reachability profile. It is a toy graph: it can rotate the current value directly, which helps exploration but does not map one-to-one to classic code because `*` rotates `mem[D]`, not `A`.

`crazy-planner-lab` is stricter. It has two small models:

- generated D-runway: each step consumes a generated seed under D. `p seed=N` computes `crazy(A, N)`. `* seed=N` rotates that seed into `A`.
- direct cell rewrite: solve `crazy(mask, current_cell) = target_cell` for the final `p` that mutates a live cell under D.

For the actual argv cursor value `58017`, the solver finds masks for `58017 -> 58018`; the smallest is `27`, and the runway planner can materialize A=`27` in four `p seed` steps. But `58019 -> 58020` is blocked at trit 0 because a source trit `2` cannot crazy into target trit `0`. So a generic `addi 1` loop cannot be replaced by one naive final `p`.

`crazy-route-lab` adds the C5.5 straight-line C/D layer. In M8, as in classic Malbolge, every executed instruction advances D by one. A generated ritual therefore needs both a code track and a data track. The sample route lays code cells at `1000..1004` and data cells at `3000..3004`; the first four data cells are runway seeds and the final data cell is the mutable value. The tool prints overlap status and per-step A values. It proves a straight segment only. Entering that segment with the right C and D, placing it on a real live cell, and making loop re-entry self-cipher-safe are still future codegen work.

`crazy-entry-lab` is the C5.6 entry planner, and it closes the gap between the abstract route and a real scroll. `plan-entry VALUE` plans a complete straight-line program that rewrites a cell from VALUE to VALUE+1 and prints `OK`:

- D tick accounting starts at the very first executed instruction. With no data directives the startup materializer is a single `! start` jump, so D is 1 when user code begins.
- Every six-cell frame instruction (`#`, `=`, `~`, `!`, `?`, `@`) advances C by six cells but D by only one, so D trails C by five cells per frame instruction. Linear padding never closes that gap; it shifts both positions together.
- The planner exploits the trailing D instead of fighting it. Seed cells live inside the dead frames of already executed instructions behind C. Each `seta`/`storea` pair writes one seed into that dead region, and junk `seta 0` instructions pad D forward until D lands on the first seed exactly when the first ritual `p` executes.
- Every seed write is checked against its own execution time: the target cell must already be consumed when the store runs. The report prints the worst margin.
- After the final `p` rewrites the mutable cell, two proof chains verify the result. Any word reaches `0t2222222222` in one `p` step, and `0t2222222222` reaches any word in one `p` step, so each chain needs at most two seeds. One chain prints the first character from the final A; a `~` load of the mutable cell plus the second chain prints the second character. `OK` means both the accumulator and the rewritten cell held the target value.

`plan-entry 58017 --emit-scroll` prints the assemble-ready source. `plan-entry 58019` reports the blocked trit and refuses to plan.

`crazy-ritual-test` is the C5.7 executable proof, extended in C6.1. It builds the four test scrolls under `build/tests/`, audits them, and runs each under `build/m8`, requiring the expected output and exit code 0. The rewrite itself uses only classic `p` ops; `seta`, `storea`, and `loada` appear in setup and readout only, and the scroll contains none of the audited arithmetic helpers (`addi`, `subi`, `addm`, `subm`, `cmpm`).

C5.8 adds the `crazyinc` codegen macro to `tools/m8asm.py`:

```m8a
start:
    crazyinc 58017
```

The macro is not a new VM op. The assembler expands it at assemble time through the same planner, emitting the junk, seed pairs, ritual, proof chains, print, and halt as real M8 cells. For the standalone one-line scroll the image is byte-identical to the planner-emitted demo. The macro also works after preceding instructions and data (`scrolls/tests/crazy_inc_mid.m8a` prints `8COK`): the assembler tracks materializer ticks, per-item tick costs, and cell positions, then passes the entry state, meaning D ticks so far and the absolute cell base, to the planner, which adapts the layout.

Macro contract and limits:

- The macro assumes straight-line fall-through execution from program start through the preceding code. Branches or loops before the macro invalidate the tick model.
- The value must be a literal int; label expressions are not resolved at expansion time yet.
- In the base form the mutable cell is a planner-placed dead cell. The `crazyinc-cell` form added in C6.1 targets a live cell declared by the surrounding scroll; see below.
- The ritual is single-pass. Loops, re-entry, and self-cipher-safe placement beyond one pass are not solved by this macro.
- Blocked transitions (for example `58019 -> 58020`) fail at assemble time with the blocked trit.

C6.1 adds the live-cell form:

```m8a
live_cell:
    word 58017
    word 0
    word 0
    word 0
    word 0
    word 0
    word 0
start:
    crazyinc-cell live_cell 58017
```

The planner still owns the ritual, but the mutable target is now a real cell from the calling scroll. Three things change. The runway block ends with a stored pointer word holding `live_cell - 1`, followed by a classic `j` op: `j` sets D to `mem[D] + 1`, so D lands exactly on the live cell when the final `p` executes. The proof-chain seeds move from the ritual's own dead frames into scratch cells after the live cell, because the print and `~` load ticks now walk past the live cell instead of the old block. And the span and collision checks verify that the hop pointer, the seeds, the live cell, and the macro code never overlap. `plan-entry 58017 --cell-addr 5000` prints a standalone cell-mode report; `scrolls/tests/crazy_cell_demo.m8a` is the assemble-and-run proof and prints `OK`.

The contract matches `crazyinc`, plus two points. `ADDR` may be a label: the assembler sizes the expansion with a canary plan at a fixed address, then re-plans with the resolved label and asserts the size did not change. And the caller must reserve the neighbor scratch cells after the live cell, because the planner writes chain seeds there.

## Assembly source v0

The assembler is intentionally small. Example:

```text
start:
    trap write 1 msg msg_end-msg
    trap exit 0

msg:
    ascii "hello from the eighth circle\n"
msg_end:
```

This emits a printable `.mb` glyph stream. Code cells are Malbolge-encoded printable ASCII values. Inline frame words are valid-source printable base-94 groups. Data cells start as printable filler and are written to their intended raw VM values by the generated startup materializer.

Supported data helpers:

- `ascii "text"` emits bytes without a zero terminator.
- `cstring "text"` emits bytes plus a zero terminator.
- `word N` emits a single VM word.
- `ptr label` emits one or more VM pointer words.
- `ptrv a b c` emits a NULL-terminated pointer vector.
- `zero N` reserves N cells as printable filler. It is for buffers that later get overwritten by syscalls or M8 copy code.
- `crazyinc N` is a codegen macro, not data: it expands at assemble time into a planned classic-op ritual that rewrites a cell from N to N+1, proves the result, prints `OK`, and halts. See the C5.6-C5.8 notes above for the contract.
- `crazyinc-cell ADDR VALUE` is the live-cell codegen macro: it expands into a planned ritual that rewrites the cell at `ADDR`, a label or expression, from `VALUE` to `VALUE+1`, landing D on the live cell with a classic `j` hop. See the C6.1 notes above for the contract.

## Pointer vectors for `execve`

`execve` reads VM pointer vectors and converts them to host `char **` arrays. In pointer-vector context, word `0` is NULL.

```text
path:
    cstring "/bin/m8"
image:
    cstring "/bin/msh.mb"
argv:
    ptrv path image
envp:
    word 0
```

## Userland image convention

Human-readable source scrolls live in `scrolls/`. Generated printable userland lives in `src/userland/`.

```text
scrolls/init.m8a      -> src/userland/init.mb      printable M8 glyph program
scrolls/msh.m8a       -> src/userland/msh.mb       printable M8 glyph program
scrolls/bin/*.m8a     -> src/userland/*.mb         printable M8 glyph programs
src/mfs/root/             -> src/userland/root.mfs     MFS v0 image
```


## Format audit

`tools/m8audit.py` checks the generated `.mb` files without running them. It rejects:

- non-graphic source cells
- cells that decode to unknown operations at their addresses
- empty files
- old decimal memory-image shapes

`make glyph-audit` runs that check over `src/userland/*.mb` plus the host-side demo image. `make loader-tests` creates bad `.mb` files under `build/loader-tests/` and verifies that the runtime exits during loading.

## Philosophical rule

If a decision belongs to the OS or userland, put it in M8.
If a decision belongs to making M8 executable at all, put it in the runtime.
