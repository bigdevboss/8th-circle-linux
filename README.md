# 8th Circle Linux

![8th Circle Linux logo](logo.png)

Linux, but the first userland lives in the eighth circle.

**8th Circle Linux** is a small bootable Linux/initramfs distro experiment. The kernel is normal Linux. PID 1, the shell, and the tiny command set are printable M8 glyph programs, where M8 is our deliberately cursed Malbolge-derived VM. The C runtime handles VM execution, Linux syscall bridging, argv setup, and the unavoidable ABI glue.

This is not an ISO installer yet. Today the distro artifact is a Linux kernel plus a generated initramfs.

## Quick start

Needed on the build host:

- `make`
- `gcc`
- `python3`
- `qemu-system-x86_64` for booting and smoke tests
- a Linux kernel image, usually `/boot/vmlinuz-*`

On Debian or Ubuntu-ish systems:

```sh
sudo apt install build-essential python3 qemu-system-x86 linux-image-amd64
```

Build the runtime, printable userland images, MFS v0 image, rootfs, and initramfs:

```sh
make check
```

Boot it in QEMU:

```sh
make qemu
```

Run the automated boot test:

```sh
make qemu-smoke
```

If your kernel is not under `/boot/vmlinuz-*`, point the build at it:

```sh
QEMU_KERNEL=/path/to/vmlinuz make qemu
QEMU_KERNEL=/path/to/vmlinuz make qemu-smoke
```

## Build the distro bundle

For a handoff-style boot bundle, run:

```sh
make distro
```

That creates:

```text
build/distro/
  vmlinuz                       Linux kernel copied from the build host
  8th-circle-initramfs.cpio.gz   generated 8th Circle initramfs
  run-qemu.sh                    local boot script
  manifest.txt                   sizes and sha256 sums
  README.txt                     tiny bundle note
```

Run the bundle directly:

```sh
build/distro/run-qemu.sh
```

`make distro` does not compile Linux from source. It copies an existing kernel image from `QEMU_KERNEL` or the newest `/boot/vmlinuz-*`. Keep that bundle under `build/`; do not commit local kernel copies to `src/`.

The manual QEMU command is:

```sh
qemu-system-x86_64 \
  -m 512M \
  -accel tcg \
  -kernel build/distro/vmlinuz \
  -initrd build/distro/8th-circle-initramfs.cpio.gz \
  -append "console=ttyS0 rdinit=/init panic=1 oops=panic loglevel=7" \
  -nographic -no-reboot -monitor none
```

## What boots right now

The Linux kernel unpacks the initramfs and runs `/init`. In this distro, `/init` is the M8 runtime. With no image argument it auto-loads `/sbin/init.mb`.

Current boot path:

1. `/init` starts the M8 runtime.
2. The runtime loads `/sbin/init.mb`.
3. `init.mb` claims `/dev/console`, calls `setsid`, switches to `/`, and prints `/etc/issue`.
4. It mounts `/proc`, `/sys`, and `/dev` when the kernel allows it.
5. It forks and execs `/bin/m8 /bin/msh.mb`.
6. `msh.mb` gives you a tiny shell.
7. If the shell exits, PID 1 waits, sleeps for one second, and respawns it.

The shell banner should be:

```text
Welcome to 8th circle Linux! Type 'help' to see msh commands.
```

## What works

- M8 runtime in `src/runtime/m8.c`.
- M8 assembler in `tools/m8asm.py`.
- Printable, source-validated M8 glyph userland images in `src/userland/`.
- PID 1 scroll in `scrolls/init.m8a`.
- Shell scroll in `scrolls/msh.m8a`.
- External command scrolls in `scrolls/bin/*.m8a`.
- Pure-Python initramfs builder.
- QEMU boot through `make qemu`.
- PTY-driven QEMU smoke test through `make qemu-smoke`.
- Strict glyph audit through `make glyph-audit`.
- Negative loader checks through `make loader-tests`.
- MFS v0 image built from `src/mfs/root/` and shipped as `/mfs/root.mfs`.

Inside `msh`:

```text
help
exit
issue
echo TEXT...
cat PATH...
pwd
cd [PATH]
ls [PATH...]
mfsls
mfscat NAME
mfs.info
mfs.stat NAME
```

`msh` now keeps only shell jobs in the shell: prompt, input, command parsing, `cd`, `help`, `exit`, argv-vector building, `fork`, `execve`, and `wait4`. Most useful commands are separate printable M8 programs in `/bin`.

## Shell honesty note

`msh` is still small and weird, but it is now a launcher instead of a pile of builtins. The shell reads input through the normal Linux `read` syscall bridge, trims and parses commands in M8, splits up to eight whitespace-separated arguments, builds an `execve` argv vector in M8 memory, then launches external `.mb` images with `/bin/m8`.

The C runtime no longer provides shell-specific helper traps. It handles the VM, primitive M8 ops, process argv setup, and the Linux syscall bridge.

The shell now has a tiny PATH-like rule: a command named `NAME` launches `/bin/NAME.mb` with the parsed arguments. These command images are currently shipped:

```text
/bin/pwd.mb
/bin/issue.mb
/bin/echo.mb
/bin/cat.mb
/bin/ls.mb
/bin/mfs.ls.mb
/bin/mfs.cat.mb
/bin/mfs.info.mb
/bin/mfs.stat.mb
```

`echo.mb`, `cat.mb`, and `ls.mb` now handle multiple argv entries instead of only seeing one tail string. `cat.mb` and `echo.mb` use unrolled argv slot probes, and `cat.mb` has zero friendly arithmetic debt. `echo.mb` prints one byte per `trap write` and keeps a single `addi 1` for the source pointer. `ls.mb` calls `getdents64` and parses `linux_dirent64` records in M8. MFS commands read `/mfs/root.mfs`, walk the MFS v0 header/table, print metadata, and copy payload bytes in M8. The C6 pass replaced fixed-offset pointer arithmetic with label expressions such as `seta mfs_buf+512` and moved MFS name and payload output to byte-per-trap writes.

Friendly aliases remain:

```text
mfsls        -> /bin/m8 /bin/mfs.ls.mb
mfscat NAME  -> /bin/m8 /bin/mfs.cat.mb NAME
```

The dotted command names work through the generic rule too:

```text
mfs.info       -> /bin/m8 /bin/mfs.info.mb
mfs.stat NAME  -> /bin/m8 /bin/mfs.stat.mb NAME
```

## M8 in one paragraph

Classic Malbolge is intentionally hostile: 59049-word memory, ternary 10-trit words, three registers, self-encrypting code, and the famous crazy operation. M8 keeps the 10-trit words, A/C/D registers, Malbolge-style decoding, shared code/data memory, and the general bad idea energy. M8 adds extension ops for syscalls, jumps, branches, and small data moves because this thing has to boot Linux userland rather than win an esolang purity contest and die immediately.

## What `.mb` means now

`.mb` files are printable M8 source, not decimal object dumps.

The runtime loads them like cursed source:

- Whitespace is skipped.
- Every loaded cell must be printable ASCII, `33..126`.
- Every loaded cell must decode at its address to a known M8 operation.
- Old decimal memory images are rejected, even if they have the old header.
- Remaining memory is filled with the Malbolge-style crazy operation.
- Executed instruction cells self-cipher through `xlat2`.

M8 inline frame words use five printable base-94 cells. The assembler chooses frame glyphs that also decode as valid M8 source at their addresses, so syscall numbers and labels are not smuggled in as arbitrary printable junk.

Data still has to exist. Strings, pointer vectors, and numeric words are created by generated startup materializer code before the real program starts. Large buffers are reserved as printable filler and then overwritten by syscalls or M8 copy code.

One ugly runtime bridge remains on purpose: extension instruction cells keep their original M8 meaning across encrypted generations, so loops can re-enter mutated trap and branch cells. C4 tightened that bridge: the runtime now marks extension lineage by structurally walking the loaded source and skipping inline frames, instead of blindly treating every extension-looking frame or filler glyph as executable lineage.

## Userland image convention

There is no separate `raw/` directory. The generated M8 programs are distro userland and live in `src/userland/`. Human-editable source scrolls live in `scrolls/`.

```text
scrolls/init.m8a      -> src/userland/init.mb
scrolls/msh.m8a       -> src/userland/msh.mb
scrolls/bin/*.m8a     -> src/userland/*.mb
src/mfs/root/             -> src/userland/root.mfs
```

Regenerate and audit them with:

```sh
make raw
make glyph-audit
```

`make check` runs the audit and the negative loader tests, so accidental numeric `.mb` files should fail before QEMU ever boots.

## MFS v0 seed

MFS is the cursed filesystem direction for the project. The current version is an image, not a mounted kernel filesystem.

```sh
make mfs
```

The source tree is intentionally tiny:

```text
src/mfs/root/etc/issue
```

The generated image is:

```text
src/userland/root.mfs
```

The initramfs ships it as:

```text
/mfs/root.mfs
```

Inside QEMU:

```text
msh> mfsls
etc/issue
msh> mfs.info
MFS8 v0 image
entries: 1
image-size: 1099
entry-size: 128
files:
etc/issue
msh> mfs.stat etc/issue
name: etc/issue
size: 75
offset: 1024
msh> mfscat etc/issue
8th Circle Linux MFS image
The filesystem is not sane, and neither are we.
```

## Repository layout

```text
src/
  runtime/      M8 VM/runtime, currently C
  userland/     generated printable .mb programs shipped by the distro
  mfs/root/     source tree for the MFS v0 image
scrolls/        human-readable .m8a source scrolls
scrolls/bin/    external command source scrolls
tools/          assembler, MFS builder, initramfs builder, QEMU tooling
docs/           M8 dialect spec
build/          generated build artifacts, ignored by git
```

Important files:

- `src/runtime/m8.c` - prototype runtime for M8.
- `tools/m8asm.py` - assembler that emits printable M8 glyph programs.
- `tools/m8audit.py` - strict `.mb` glyph/source audit.
- `tools/m8_loader_tests.py` - negative tests for bad `.mb` files.
- `tools/m8crazy.py` - crazy-op, ternary exploration, and C5 planner helper.
- `tools/m8_arith_audit.py` - counts friendly arithmetic debt in scrolls.
- `tools/mkmfs.py` - MFS v0 image builder.
- `tools/mkinitramfs.py` - pure-Python `newc` initramfs packer.
- `tools/mkdistro.py` - copies a kernel and initramfs into a local boot bundle.
- `tools/qemu_smoke.py` - serial-console QEMU smoke test.
- `src/userland/init.mb` - printable M8 init program shipped as `/sbin/init.mb`.
- `src/userland/msh.mb` - printable M8 shell program shipped as `/bin/msh.mb`.
- `src/userland/{pwd,issue,echo,cat,ls,mfs.ls,mfs.cat,mfs.info,mfs.stat}.mb` - external command images shipped under `/bin`.
- `src/userland/root.mfs` - MFS v0 image shipped as `/mfs/root.mfs`.
- `docs/m8-spec.md` - current M8 dialect and trap ABI notes.

## Crazy-op groundwork

Classic Malbolge does not have friendly integer arithmetic. Its real data ritual is ternary rotation plus the crazy operation. M8 still has helper ops such as `addi`, `subi`, `addm`, `subm`, and `cmpm` because the shell and MFS tools need to work. C5 starts by measuring that debt instead of ripping it out blindly.

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

`arithmetic-audit` counts helper-op usage in `scrolls/`. `arithmetic-audit-details` prints the exact lines. `arithmetic-audit-budget` currently fails above `133`, so C5 through C7 debt reductions do not silently regress. `crazy-lab` prints the crazy table, word transforms, rotations, and a tiny byte-target search. `crazy-word-lab` tries exact 10-trit word targets in the older toy graph.

`crazy-planner-lab` is stricter. It separates generated D-runway steps from direct cell rewrites. The runway model says `p seed=N` computes `crazy(A, N)` from a generated seed cell and `* seed=N` rotates that seed into `A`. The direct rewrite model solves one final `p` on a mutable cell. For example, it proves that cell value `58017` can become `58018` with A mask `27`, then shows a four-step runway to materialize that mask. It also shows why this is not a generic pointer increment yet: values such as `58019 -> 58020` are blocked by the trit table.

`crazy-route-lab` is the C5.5 routing layer. It places the planned runway on straight-line C/D tracks and prints the code cells, data cells, overlap status, A before and after each step, and the required initial memory values. The sample route uses code cells `1000..1004` and data cells `3000..3004`, with the final mutable cell at `3004`. It proves the small value rewrite without pretending we have solved entry jumps, live ABI-cell placement, loops, or self-cipher-safe re-entry.

`crazy-entry-lab` is the C5.6 entry planner. It plans the whole straight-line scroll, not just the ritual segment: D tick accounting from the very first instruction, seed placement into dead cells behind C, junk `seta` padding, the runway, the final `p`, and two proof chains. `plan-entry 58017 --emit-scroll` prints a ready-to-assemble `.m8a` that rewrites `58017` to `58018` and prints `OK`.

`crazy-ritual-test` is the C5.7/C5.8/C6.1 proof. It assembles four test scrolls, audits them, and runs them under the real runtime:

- `scrolls/tests/crazy_inc_demo.m8a` - planner-emitted scroll; rewrites a cell from `58017` to `58018` using only classic `p` ops, then proves the result. One crazy chain prints `O` from the final A, and a `~` load plus a second chain prints `K` from the rewritten cell. Output `OK`.
- `scrolls/tests/crazy_inc_macro.m8a` - the same ritual from a single `crazyinc 58017` line. The assembler expands the macro at assemble time through the same planner, and the image is byte-identical to the demo scroll.
- `scrolls/tests/crazy_inc_mid.m8a` - the macro placed after real instructions and data, proving the planner adapts to the surrounding tick and cell context. Output `8COK`.
- `scrolls/tests/crazy_cell_demo.m8a` - the live-cell variant. `crazyinc-cell live_cell 58017` rewrites a cell declared in the same scroll instead of a planner-placed dead cell. A classic `j` hop reads a stored pointer word and lands D directly on the live cell, the final `p` rewrites it, and the proof chains run from seeds in neighboring caller scratch cells. Output `OK`.

All four scrolls have zero friendly-arithmetic debt: no `addi`, `subi`, `addm`, `subm`, or `cmpm`. The rewrite itself is pure classic `p` work. Extension ops appear only in the seed setup and the verification readout, none of them audited arithmetic.

The first C5 cleanup moved `cat`, `echo`, and `ls` to argv-vector cursors instead of index-plus-compare loops. The next small cleanup made `cat.m8a` zero-debt by unrolling the runtime argv slots instead of stepping a pointer with `addi 1`. Friendly arithmetic debt dropped from `191` to `180` without changing the runtime ABI or the boot path. C5.4 added planner evidence, C5.5 added straight-line C/D route evidence, and C5.6 through C5.8 added the first real executable crazy ritual: planned, assembled, and proven under the runtime, with an assembler macro on top.

C6 lowered the debt from `180` to `150` with three layout idioms: unrolled argv slot probes plus byte-per-trap output in `echo.m8a` (`5` to `1`), label arithmetic such as `seta mfs_buf+512` and direct slot loads `loada M8_ARGVEC+1` in the MFS tools, and byte-per-trap name and payload output. `mfs.ls` went `9` to `4`, `mfs.cat` `27` to `19`, `mfs.info` `33` to `26`, and `mfs.stat` `40` to `34`. The metric is honest about what moved: these wins come from unrolling, layout, and syscall patterns, not from new crazy math. The crazy side of C6 proves the machinery instead: `crazyinc-cell` rewrites a live program cell through a classic `j` hop, under the same runtime and the same audit as the debt work. Merging the two, for example a crazy-driven pointer walk, is later work.

C7 continued with layout work aimed at the shell. `msh.m8a` dropped from `49` to `33` debt lines by replacing index-plus-limit loops with write cursors and static end-pointer words (`line_end`, `cmd_end`, `arg_end`), comparing strings directly against NUL sentinels instead of carrying compare lengths, and walking the exec argument vector through a NUL-terminated `arg_ptrs` table instead of a counted loop. `read_line` now rejects CR and LF at read time, so the old trim routine is gone. `mfs.cat` uses the same cursor pattern for its argument copy (`18` debt). The only remaining arithmetic in `msh` is `addi` stepping, one `subm` for the command length, and `cmpm` bounds; the `addm` and `subi` helpers are gone from the shell. Total debt: `133`.

`scrolls/tests/chase_demo.m8a` is the C7 pointer-chase proof. A chain of cells holds the absolute address of the next cell, so `loadi cur` plus `storea cur` advances the cursor with zero arithmetic, and a stored `0` ends the walk. The payload lives in the addresses themselves: each node sits at an address whose low byte is the character it prints, `591` for `O`, `587` for `K`, `545` for `!`, written out as one byte through `trap write`. `make chase-test` builds, audits, and runs it, expecting `OK!`.

## Development commands

```sh
make raw          # rebuild printable .mb programs and root.mfs
make glyph-audit  # verify .mb files are printable valid-source glyph streams
make loader-tests # verify bad .mb formats are rejected by the runtime
make arithmetic-audit # count add/sub/compare helper usage in scrolls
make arithmetic-audit-details # show line-level arithmetic helper usage
make arithmetic-audit-budget # fail if helper debt rises above the C6 budget
make crazy-lab    # print crazy-op table and a few ternary probes
make crazy-word-lab # try toy exact-word searches and reachability profiles
make crazy-planner-lab # run stricter D-runway and direct-p planning probes
make crazy-route-lab # lay a planned ritual onto straight-line C/D tracks
make crazy-entry-lab # plan a full straight-line entry scroll for 58017 -> 58018, plus a live-cell plan
make crazy-ritual-test # build and run real crazy-ritual test scrolls
make chase-test   # build and run the zero-arithmetic pointer-chase demo
make mfs          # rebuild only root.mfs
make msh-demo     # run msh on the host through the runtime
make init-demo    # run a small host-side init demo
make initramfs    # build build/8th-circle-initramfs.cpio.gz
make distro       # create build/distro with kernel plus initramfs
make qemu         # boot interactively
make qemu-smoke   # boot and validate the shell over serial
make clean        # remove build/
make distclean    # remove build/ and generated printable userland images
```

## Current status

Current checkpoint:

- The project builds from source with `make check`.
- The initramfs boots in QEMU.
- PID 1 does not exit.
- `msh` is usable enough for basic navigation, file reads, and multi-argument external commands.
- MFS v0 exists and is visible from `msh`.
- The QEMU smoke test passes. It validates `pwd`, multi-path `ls`, multi-file `cat`, multi-word `echo`, `issue`, `mfsls`, `mfs.info`, `mfs.stat`, and `mfscat`.

Still cursed and unfinished:

- The kernel is not built by this repo yet.
- There is no ISO, installer, package manager, or real disk image.
- MFS v0 is read-only, but `mfs.ls.mb`, `mfs.cat.mb`, `mfs.info.mb`, and `mfs.stat.mb` are now standalone command images.
- The shell no longer uses shell-specific C helper traps; it relies on the normal syscall bridge and primitive M8 ops.
- `.mb` userland is printable, source-validated M8 glyph source now, not numeric VM dumps.
- The runtime no longer accepts old decimal `.mb` memory images in normal mode.
- Command lookup is PATH-lite: `NAME` maps to `/bin/NAME.mb`, with up to eight parsed arguments and special aliases for `mfsls` and `mfscat`.
- C5 through C7 ritual and layout work has landed: `make arithmetic-audit` tracks friendly arithmetic helper debt, `make arithmetic-audit-details` shows exact lines, `make arithmetic-audit-budget` guards the current `133` budget, and `make crazy-lab`, `make crazy-word-lab`, `make crazy-planner-lab`, `make crazy-route-lab`, and `make crazy-entry-lab` explore Malbolge-style crazy/rotate transforms. `make crazy-ritual-test` builds and runs the zero-debt crazy ritual scrolls, the `crazyinc` assembler macro, and the `crazyinc-cell` live-cell variant. `make chase-test` runs the zero-arithmetic pointer-chase demo. C6 and C7 lowered userland debt from `180` to `133` through unrolled argv slots, label arithmetic, byte-per-trap output, write cursors, NUL sentinels, and end-pointer compares.

## License

GPLv3. See `LICENSE`.
