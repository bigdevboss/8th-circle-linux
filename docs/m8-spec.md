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

`msh.mb` handles prompt, command parsing, `cd`, `help`, `exit`, `fork`, `execve`, and `wait4`. For external commands it builds `/bin/NAME.mb` in VM memory, checks that it can open that image, then launches `/bin/m8 /bin/NAME.mb [ARG]`.

Friendly aliases map `mfsls` to `/bin/mfs.ls.mb` and `mfscat` to `/bin/mfs.cat.mb`.

`ls.mb` calls the Linux `getdents64` bridge and parses `linux_dirent64` records in M8. `mfs.ls.mb` and `mfs.cat.mb` read `/mfs/root.mfs`, walk the fixed 128-byte MFS v0 entry table, and copy file payload bytes from the image buffer.

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

Human-readable source scrolls live in `src/scrolls/`. Generated printable userland lives in `src/userland/`.

```text
src/scrolls/init.m8a      -> src/userland/init.mb      printable M8 glyph program
src/scrolls/msh.m8a       -> src/userland/msh.mb       printable M8 glyph program
src/scrolls/bin/*.m8a     -> src/userland/*.mb         printable M8 glyph programs
src/mfs/root/             -> src/userland/root.mfs     MFS v0 image
```

## Philosophical rule

If a decision belongs to the OS or userland, put it in M8.
If a decision belongs to making M8 executable at all, put it in the runtime.
