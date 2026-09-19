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
- M8 assembler in `src/toolchain/m8asm.py`.
- Printable, source-validated M8 glyph userland images in `src/userland/`.
- PID 1 scroll in `src/scrolls/init.m8a`.
- Shell scroll in `src/scrolls/msh.m8a`.
- External command scrolls in `src/scrolls/bin/*.m8a`.
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

`echo.mb`, `cat.mb`, and `ls.mb` now loop over argv instead of only seeing one tail string. `ls.mb` calls `getdents64` and parses `linux_dirent64` records in M8. MFS commands read `/mfs/root.mfs`, walk the MFS v0 header/table, print metadata, and copy payload bytes in M8.

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

There is no separate `raw/` directory. The generated M8 programs are distro userland and live in `src/userland/`. Human-editable source scrolls live in `src/scrolls/`.

```text
src/scrolls/init.m8a      -> src/userland/init.mb
src/scrolls/msh.m8a       -> src/userland/msh.mb
src/scrolls/bin/*.m8a     -> src/userland/*.mb
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
  toolchain/    assembler, MFS builder, initramfs builder, QEMU tooling
  scrolls/      human-readable .m8a source scrolls
  scrolls/bin/  external command source scrolls
  userland/     generated printable .mb programs shipped by the distro
  mfs/root/     source tree for the MFS v0 image
docs/           M8 dialect spec
build/          generated build artifacts, ignored by git
```

Important files:

- `src/runtime/m8.c` - prototype runtime for M8.
- `src/toolchain/m8asm.py` - assembler that emits printable M8 glyph programs.
- `src/toolchain/m8audit.py` - strict `.mb` glyph/source audit.
- `src/toolchain/m8_loader_tests.py` - negative tests for bad `.mb` files.
- `src/toolchain/mkmfs.py` - MFS v0 image builder.
- `src/toolchain/mkinitramfs.py` - pure-Python `newc` initramfs packer.
- `src/toolchain/mkdistro.py` - copies a kernel and initramfs into a local boot bundle.
- `src/toolchain/qemu_smoke.py` - serial-console QEMU smoke test.
- `src/userland/init.mb` - printable M8 init program shipped as `/sbin/init.mb`.
- `src/userland/msh.mb` - printable M8 shell program shipped as `/bin/msh.mb`.
- `src/userland/{pwd,issue,echo,cat,ls,mfs.ls,mfs.cat,mfs.info,mfs.stat}.mb` - external command images shipped under `/bin`.
- `src/userland/root.mfs` - MFS v0 image shipped as `/mfs/root.mfs`.
- `docs/m8-spec.md` - current M8 dialect and trap ABI notes.

## Development commands

```sh
make raw          # rebuild printable .mb programs and root.mfs
make glyph-audit  # verify .mb files are printable valid-source glyph streams
make loader-tests # verify bad .mb formats are rejected by the runtime
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

## License

GPLv3. See `LICENSE`.
