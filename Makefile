CC ?= gcc
CFLAGS ?= -std=c11 -Wall -Wextra -O2

RUNTIME = build/m8
ASM = src/toolchain/m8asm.py
GLYPHS = src/toolchain/m8glyphs.py
ROOTFS_BUILDER = src/toolchain/build_rootfs.py
INITRAMFS_BUILDER = src/toolchain/mkinitramfs.py
MFS_BUILDER = src/toolchain/mkmfs.py
QEMU_SMOKE = src/toolchain/qemu_smoke.py
DIST_BUILDER = src/toolchain/mkdistro.py

SCROLLS = src/scrolls
RAW = src/userland

INIT_SRC = $(SCROLLS)/init.m8a
INIT_IMG = $(RAW)/init.mb
INIT_DEMO_SRC = $(SCROLLS)/init_demo.m8a
INIT_DEMO_IMG = build/init_demo.mb
MSH_SRC = $(SCROLLS)/msh.m8a
MSH_IMG = $(RAW)/msh.mb
BIN_SRCS := $(wildcard $(SCROLLS)/bin/*.m8a)
BIN_IMAGES := $(patsubst $(SCROLLS)/bin/%.m8a,$(RAW)/%.mb,$(BIN_SRCS))

MFS_ROOT = src/mfs/root
MFS_SRC_FILES := $(shell find $(MFS_ROOT) -type f 2>/dev/null)
MFS_IMG = $(RAW)/root.mfs
RAW_IMAGES = $(INIT_IMG) $(MSH_IMG) $(BIN_IMAGES) $(MFS_IMG)

ROOTFS = build/rootfs
ROOTFS_STAMP = $(ROOTFS)/.stamp
INITRAMFS = build/8th-circle-initramfs.cpio.gz
DIST = build/distro

.PHONY: all raw mfs msh-demo init-demo init-trace trace clean distclean check glyphs rootfs initramfs distro qemu qemu-smoke tree

all: $(RUNTIME) raw

raw: $(RAW_IMAGES)

mfs: $(MFS_IMG)

$(RUNTIME): src/runtime/m8.c | build
	$(CC) $(CFLAGS) -o $@ $<

build:
	mkdir -p build

$(RAW):
	mkdir -p $(RAW)

$(INIT_IMG): $(INIT_SRC) $(ASM) | $(RAW)
	python3 $(ASM) $< -o $@ --dump-labels

$(MSH_IMG): $(MSH_SRC) $(ASM) | $(RAW)
	python3 $(ASM) $< -o $@ --dump-labels

$(RAW)/%.mb: $(SCROLLS)/bin/%.m8a $(ASM) | $(RAW)
	python3 $(ASM) $< -o $@ --dump-labels

$(MFS_IMG): $(MFS_BUILDER) $(MFS_SRC_FILES) | $(RAW)
	python3 $(MFS_BUILDER) $(MFS_ROOT) -o $@

$(INIT_DEMO_IMG): $(INIT_DEMO_SRC) $(ASM) | build
	python3 $(ASM) $< -o $@ --dump-labels

msh-demo: $(RUNTIME) $(MSH_IMG)
	printf 'help\ncd src\ncd /\nwat\nexit\n' | $(RUNTIME) $(MSH_IMG)

init-demo: $(RUNTIME) $(INIT_DEMO_IMG)
	$(RUNTIME) $(INIT_DEMO_IMG)

init-trace: $(RUNTIME) $(INIT_IMG)
	$(RUNTIME) --trace $(INIT_IMG)

trace: $(RUNTIME) $(MSH_IMG)
	$(RUNTIME) --trace $(MSH_IMG)

glyphs: $(INIT_IMG)
	python3 $(GLYPHS) $(INIT_IMG) 0 7 14 21 28 35 42 49 56 63 70 77 84 91 98 105 112 119 126 133 140

$(ROOTFS_STAMP): $(RUNTIME) $(INIT_IMG) $(MSH_IMG) $(BIN_IMAGES) $(MFS_IMG) $(ROOTFS_BUILDER)
	python3 $(ROOTFS_BUILDER) --runtime $(RUNTIME) --init-image $(INIT_IMG) --msh-image $(MSH_IMG) --mfs-image $(MFS_IMG) --userland-dir $(RAW) --out $(ROOTFS)
	touch $@

rootfs: $(ROOTFS_STAMP)

$(INITRAMFS): $(ROOTFS_STAMP) $(INITRAMFS_BUILDER)
	python3 $(INITRAMFS_BUILDER) $(ROOTFS) -o $@

initramfs: $(INITRAMFS)

distro: initramfs $(DIST_BUILDER)
	python3 $(DIST_BUILDER) --initramfs $(INITRAMFS) --out $(DIST)

qemu: initramfs
	@KERNEL="$${QEMU_KERNEL:-$$(ls -1 /boot/vmlinuz-* 2>/dev/null | sort -V | tail -1)}"; \
	if [ -z "$$KERNEL" ]; then echo "No kernel found. Install linux-image-amd64 or set QEMU_KERNEL=/path/to/vmlinuz"; exit 1; fi; \
	echo "Booting 8th Circle Linux with $$KERNEL"; \
	qemu-system-x86_64 -m $${QEMU_MEMORY:-512M} -accel $${QEMU_ACCEL:-tcg} \
		-kernel "$$KERNEL" -initrd $(INITRAMFS) \
		-append "console=ttyS0 rdinit=/init panic=1 oops=panic loglevel=7" \
		-nographic -no-reboot -monitor none

qemu-smoke: initramfs $(QEMU_SMOKE)
	python3 $(QEMU_SMOKE)

tree:
	find . -maxdepth 4 -type f | sort

check: raw msh-demo init-demo initramfs
	@echo "ok"

clean:
	rm -rf build

distclean: clean
	rm -f $(RAW_IMAGES) src/userland/*.m8i
