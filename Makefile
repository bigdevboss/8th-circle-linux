CC ?= gcc
CFLAGS ?= -std=c11 -Wall -Wextra -O2

RUNTIME = build/m8
TOOLS = tools
ASM = $(TOOLS)/m8asm.py
GLYPHS = $(TOOLS)/m8glyphs.py
ROOTFS_BUILDER = $(TOOLS)/build_rootfs.py
INITRAMFS_BUILDER = $(TOOLS)/mkinitramfs.py
MFS_BUILDER = $(TOOLS)/mkmfs.py
QEMU_SMOKE = $(TOOLS)/qemu_smoke.py
DIST_BUILDER = $(TOOLS)/mkdistro.py
AUDIT = $(TOOLS)/m8audit.py
LOADER_TESTS = $(TOOLS)/m8_loader_tests.py
CRAZY = $(TOOLS)/m8crazy.py
ARITH_AUDIT = $(TOOLS)/m8_arith_audit.py

SCROLLS = scrolls
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
MB_IMAGES = $(INIT_IMG) $(MSH_IMG) $(BIN_IMAGES)
RAW_IMAGES = $(MB_IMAGES) $(MFS_IMG)

TESTS = scrolls/tests
TEST_DEMO_SRC = $(TESTS)/crazy_inc_demo.m8a
TEST_MACRO_SRC = $(TESTS)/crazy_inc_macro.m8a
TEST_MID_SRC = $(TESTS)/crazy_inc_mid.m8a
TEST_CELL_SRC = $(TESTS)/crazy_cell_demo.m8a
TEST_CHASE_SRC = $(TESTS)/chase_demo.m8a
TEST_DEMO_IMG = build/tests/crazy_inc_demo.mb
TEST_MACRO_IMG = build/tests/crazy_inc_macro.mb
TEST_MID_IMG = build/tests/crazy_inc_mid.mb
TEST_CELL_IMG = build/tests/crazy_cell_demo.mb
TEST_CHASE_IMG = build/tests/chase_demo.mb

ROOTFS = build/rootfs
ROOTFS_STAMP = $(ROOTFS)/.stamp
INITRAMFS = build/8th-circle-initramfs.cpio.gz
DIST = build/distro

.PHONY: all raw mfs glyph-audit loader-tests arithmetic-audit arithmetic-audit-details arithmetic-audit-budget crazy-lab crazy-word-lab crazy-planner-lab crazy-route-lab crazy-entry-lab crazy-ritual-test msh-demo init-demo init-trace trace clean distclean check glyphs rootfs initramfs distro qemu qemu-smoke tree

all: $(RUNTIME) raw

raw: $(RAW_IMAGES)

mfs: $(MFS_IMG)

glyph-audit: $(MB_IMAGES) $(INIT_DEMO_IMG) $(AUDIT)
	python3 $(AUDIT) $(MB_IMAGES) $(INIT_DEMO_IMG)

loader-tests: $(RUNTIME) $(LOADER_TESTS)
	python3 $(LOADER_TESTS) $(RUNTIME)

arithmetic-audit: $(ARITH_AUDIT)
	python3 $(ARITH_AUDIT) $(SCROLLS)

arithmetic-audit-details: $(ARITH_AUDIT)
	python3 $(ARITH_AUDIT) --details $(SCROLLS)

arithmetic-audit-budget: $(ARITH_AUDIT)
	python3 $(ARITH_AUDIT) --fail-above 133 $(SCROLLS)

crazy-lab: $(CRAZY)
	python3 $(CRAZY) table
	python3 $(CRAZY) word 0 0
	python3 $(CRAZY) rotate 59048 --steps 3
	python3 $(CRAZY) search-byte 65 --max-depth 4 --limit 3

crazy-word-lab: $(CRAZY)
	python3 $(CRAZY) search-word 321 --start 0 --max-depth 4 --limit 1
	python3 $(CRAZY) search-word 58018 --start 58017 --max-depth 7 --limit 1
	python3 $(CRAZY) profile --start 58017 --target 58018 --max-depth 7

crazy-planner-lab: $(CRAZY)
	python3 $(CRAZY) solve-crazy 58017 58018 --limit 3
	python3 $(CRAZY) runway-word 27 --start-a 0 --max-depth 4 --limit 1
	python3 $(CRAZY) plan-increment 58017 --max-depth 4 --mask-limit 16
	python3 $(CRAZY) increment-profile 58017 --count 8 --max-depth 4 --mask-limit 16

crazy-route-lab: $(CRAZY)
	python3 $(CRAZY) route-window --c-start 1000 --d-start 3000 --steps 5
	python3 $(CRAZY) route-plan-increment 58017 --max-depth 4 --mask-limit 16 --c-start 1000 --mutable-addr 3004
	python3 $(CRAZY) route-plan-increment 58019 --max-depth 4 --mask-limit 16 --c-start 1000 --mutable-addr 3004

crazy-entry-lab: $(CRAZY)
	python3 $(CRAZY) plan-entry 58017
	python3 $(CRAZY) plan-entry 58017 --emit-scroll
	python3 $(CRAZY) plan-entry 58019
	python3 $(CRAZY) plan-entry 58017 --cell-addr 5000

$(TEST_DEMO_IMG): $(TEST_DEMO_SRC) $(ASM) | build
	mkdir -p build/tests
	python3 $(ASM) $< -o $@

$(TEST_MACRO_IMG): $(TEST_MACRO_SRC) $(ASM) | build
	mkdir -p build/tests
	python3 $(ASM) $< -o $@

$(TEST_MID_IMG): $(TEST_MID_SRC) $(ASM) | build
	mkdir -p build/tests
	python3 $(ASM) $< -o $@

$(TEST_CELL_IMG): $(TEST_CELL_SRC) $(ASM) | build
	mkdir -p build/tests
	python3 $(ASM) $< -o $@

$(TEST_CHASE_IMG): $(TEST_CHASE_SRC) $(ASM) | build
	mkdir -p build/tests
	python3 $(ASM) $< -o $@

chase-test: $(RUNTIME) $(TEST_CHASE_IMG) $(AUDIT)
	python3 $(AUDIT) $(TEST_CHASE_IMG)
	@out=`$(RUNTIME) $(TEST_CHASE_IMG)` || exit 1; \
	if [ "$$out" != "OK!" ]; then \
		echo "chase demo output mismatch: $$out"; exit 1; \
	fi; \
	echo "chase test passed: $$out"

crazy-ritual-test: $(RUNTIME) $(TEST_DEMO_IMG) $(TEST_MACRO_IMG) $(TEST_MID_IMG) $(TEST_CELL_IMG) $(AUDIT)
	python3 $(AUDIT) $(TEST_DEMO_IMG) $(TEST_MACRO_IMG) $(TEST_MID_IMG) $(TEST_CELL_IMG)
	cmp $(TEST_DEMO_IMG) $(TEST_MACRO_IMG)
	@out1=`$(RUNTIME) $(TEST_DEMO_IMG)` || exit 1; \
	out2=`$(RUNTIME) $(TEST_MACRO_IMG)` || exit 1; \
	out3=`$(RUNTIME) $(TEST_MID_IMG)` || exit 1; \
	out4=`$(RUNTIME) $(TEST_CELL_IMG)` || exit 1; \
	if [ "$$out1" != "OK" ] || [ "$$out2" != "OK" ] || [ "$$out3" != "8COK" ] || [ "$$out4" != "OK" ]; then \
		echo "crazy ritual output mismatch: demo=$$out1 macro=$$out2 mid=$$out3 cell=$$out4"; exit 1; \
	fi; \
	echo "crazy ritual passed: demo=$$out1 macro=$$out2 mid=$$out3 cell=$$out4"

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

check: raw glyph-audit loader-tests msh-demo init-demo crazy-ritual-test chase-test initramfs
	@echo "ok"

clean:
	rm -rf build

distclean: clean
	rm -f $(RAW_IMAGES)
