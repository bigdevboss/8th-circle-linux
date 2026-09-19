#define _GNU_SOURCE
#include <ctype.h>
#include <dirent.h>
#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mount.h>
#include <sys/resource.h>
#include <sys/stat.h>
#include <sys/syscall.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#define MEM_SIZE 59049
#define WORD_MOD 59049
#define ARG_A (WORD_MOD - 2)  // special trap argument: substitute current accumulator A
#define FRAME_WORDS 6
#define ENC_WORD_CELLS 5
#define POW3_9 19683
#define DEFAULT_MAX_STEPS 10000000UL
#define M8_ABI_ARGC 58000
#define M8_ABI_ARGV 58001
#define M8_ABI_ARGVEC 58016
#define M8_ABI_STRINGS 58100
#define M8_ABI_MAX_ARGS 32

static const char XLAT1[] =
    "+b(29e*j1VMEKLyC})8&m#~W>qxdRp0wkrUo[D7,XTcA\"lI\\"
    "v%{gJh4G\\-=O@5`_3i<?Z';FNQuY]szf$!BS/|t:Pn6^Ha";

static const char XLAT2[] =
    "5z]&gqtyfr$(we4{WP)H-Zn,[%\\3dL+Q;>U!pJS72FhOA1C"
    "B6v^=I_0/8|jsb9m<.TVac`uY*MK'X~xDl}REokN:#?G\"i@";

typedef struct VM {
    int mem[MEM_SIZE];
    int A, C, D;
    int halted;
    int exit_code;
    int trace;
    int last_error;
    int encoded_frames;
    unsigned char ext_seed_op[MEM_SIZE];
    unsigned char ext_expected_cell[MEM_SIZE];
} VM;

static int mod_word(long x) {
    long r = x % WORD_MOD;
    if (r < 0) r += WORD_MOD;
    return (int)r;
}


static int crazy(int a, int d) {
    static const int table[3][3] = {
        {1, 0, 0},
        {1, 0, 2},
        {2, 2, 1},
    };
    int out = 0;
    int place = 1;
    for (int i = 0; i < 10; i++) {
        int at = a % 3;
        int dt = d % 3;
        out += table[dt][at] * place;
        a /= 3;
        d /= 3;
        place *= 3;
    }
    return out;
}

static int rotate_right_trit(int x) {
    int low = x % 3;
    return (x / 3) + low * POW3_9;
}

static void fill_tail_classic(VM *vm, int loaded) {
    if (loaded < 2) return;
    for (int i = loaded; i < MEM_SIZE; i++) {
        vm->mem[i] = crazy(vm->mem[i - 1], vm->mem[i - 2]);
    }
}

static char decode_op_cell(int cell, int address) {
    if (cell < 33 || cell > 126) return '\0';
    return XLAT1[(cell - 33 + address) % 94];
}

static int is_valid_decoded_op(char op, int m8_mode) {
    switch (op) {
        case 'j': case 'i': case '*': case 'p':
        case '/': case '<': case 'v': case 'o':
            return 1;
        case '@': case '!': case '?': case '=': case '~':
        case '#': case '+': case '-': case '[': case ']':
        case ':': case '^': case '$': case '`':
            return m8_mode;
        default:
            return 0;
    }
}

static int is_m8_extension_op(char op) {
    switch (op) {
        case '@': case '!': case '?': case '=': case '~':
        case '#': case '+': case '-': case '[': case ']':
        case ':': case '^': case '$': case '`':
            return 1;
        default:
            return 0;
    }
}

static void prepare_extension_lineage(VM *vm, int m8_mode) {
    memset(vm->ext_seed_op, 0, sizeof vm->ext_seed_op);
    memset(vm->ext_expected_cell, 0, sizeof vm->ext_expected_cell);
    if (!m8_mode) return;
    for (int i = 0; i < MEM_SIZE; i++) {
        int cell = vm->mem[i];
        if (cell < 33 || cell > 126) continue;
        char op = decode_op_cell(cell, i);
        if (is_m8_extension_op(op)) {
            vm->ext_seed_op[i] = (unsigned char)op;
            vm->ext_expected_cell[i] = (unsigned char)cell;
        }
    }
}

static char effective_op(VM *vm, int address, int cell, char *direct_out, int *lineage_out) {
    char direct = decode_op_cell(cell, address);
    int lineage = 0;
    if (vm->ext_seed_op[address] && vm->ext_expected_cell[address] == (unsigned char)cell) {
        direct = (char)vm->ext_seed_op[address];
        lineage = 1;
    }
    if (direct_out) *direct_out = decode_op_cell(cell, address);
    if (lineage_out) *lineage_out = lineage;
    return direct;
}

static void self_cipher_executed_cell(VM *vm, int address, int cell, int lineage) {
    if (cell < 33 || cell > 126) return;
    int ciphered = (unsigned char)XLAT2[cell - 33];
    vm->mem[address] = ciphered;
    if (lineage && vm->ext_seed_op[address]) {
        vm->ext_expected_cell[address] = (unsigned char)ciphered;
    }
}

static int frame_span(const VM *vm) {
    return vm->encoded_frames ? ENC_WORD_CELLS : 1;
}

static int decode_frame_word(const VM *vm, int pos) {
    if (!vm->encoded_frames) {
        return vm->mem[pos % MEM_SIZE];
    }
    long value = 0;
    long place = 1;
    for (int i = 0; i < ENC_WORD_CELLS; i++) {
        int cell = vm->mem[(pos + i) % MEM_SIZE];
        if (cell < 33 || cell > 126) {
            return 0;
        }
        value += (long)(cell - 33) * place;
        place *= 94;
    }
    return mod_word(value);
}

static int frame_word_at(const VM *vm, int oldC, int index) {
    return decode_frame_word(vm, oldC + 1 + index * frame_span(vm));
}

static void die_usage(const char *argv0) {
    fprintf(stderr,
            "usage: %s [--trace] [--max-steps N] IMAGE.mb\n"
            "       %s --classic SOURCE.mb\n",
            argv0, argv0);
    exit(2);
}

static int load_numeric_image(VM *vm, const char *path, const char *text) {
    vm->encoded_frames = 0;
    char *copy = strdup(text ? text : "");
    if (!copy) return -1;
    int n = 0;
    char *save = NULL;
    for (char *line = strtok_r(copy, "\n", &save); line; line = strtok_r(NULL, "\n", &save)) {
        char *p = line;
        while (isspace((unsigned char)*p)) p++;
        if (*p == '\0' || *p == '#') continue;
        errno = 0;
        char *endp = NULL;
        long v = strtol(p, &endp, 0);
        if (errno || endp == p) {
            fprintf(stderr, "%s: bad word near: %s\n", path, line);
            free(copy);
            return -1;
        }
        if (n >= MEM_SIZE) {
            fprintf(stderr, "%s: image too large for v0 memory\n", path);
            free(copy);
            return -1;
        }
        vm->mem[n++] = mod_word(v);
    }
    free(copy);
    return n;
}

static int load_glyph_image(VM *vm, const char *path, const char *text) {
    vm->encoded_frames = 1;
    int n = 0;
    for (const unsigned char *p = (const unsigned char *)text; *p; p++) {
        if (isspace(*p)) continue;
        if (*p < 33 || *p > 126) {
            fprintf(stderr, "%s: non-graphic character in glyph source\n", path);
            return -1;
        }
        if (n >= MEM_SIZE) {
            fprintf(stderr, "%s: source too large\n", path);
            return -1;
        }
        char op = decode_op_cell(*p, n);
        if (!is_valid_decoded_op(op, 1)) {
            fprintf(stderr, "%s: invalid glyph %c at cell %d decodes to %c\n", path, *p, n, op ? op : '?');
            return -1;
        }
        vm->mem[n++] = *p;
    }
    fill_tail_classic(vm, n);
    return n;
}

static int load_image(VM *vm, const char *path) {
    FILE *f = fopen(path, "rb");
    if (!f) {
        perror(path);
        return -1;
    }
    if (fseek(f, 0, SEEK_END) != 0) {
        perror(path);
        fclose(f);
        return -1;
    }
    long size = ftell(f);
    if (size < 0) {
        perror(path);
        fclose(f);
        return -1;
    }
    if (fseek(f, 0, SEEK_SET) != 0) {
        perror(path);
        fclose(f);
        return -1;
    }
    char *text = calloc((size_t)size + 1, 1);
    if (!text) {
        fclose(f);
        return -1;
    }
    if (fread(text, 1, (size_t)size, f) != (size_t)size) {
        perror(path);
        free(text);
        fclose(f);
        return -1;
    }
    fclose(f);

    int loaded;
    if (strncmp(text, "# M8 raw memory image", 21) == 0) {
        loaded = load_numeric_image(vm, path, text);
    } else {
        loaded = load_glyph_image(vm, path, text);
    }
    free(text);
    return loaded;
}

static int load_classic(VM *vm, const char *path, int m8_mode) {
    vm->encoded_frames = 0;
    FILE *f = fopen(path, "rb");
    if (!f) {
        perror(path);
        return -1;
    }
    int n = 0;
    int ch;
    while ((ch = fgetc(f)) != EOF) {
        if (isspace((unsigned char)ch)) continue;
        if (ch < 33 || ch > 126) {
            fprintf(stderr, "%s: non-graphic character in source\n", path);
            fclose(f);
            return -1;
        }
        if (n >= MEM_SIZE) {
            fprintf(stderr, "%s: source too large\n", path);
            fclose(f);
            return -1;
        }
        char op = decode_op_cell(ch, n);
        if (!is_valid_decoded_op(op, m8_mode)) {
            fprintf(stderr, "%s: invalid source char %c at cell %d decodes to %c\n", path, ch, n, op);
            fclose(f);
            return -1;
        }
        vm->mem[n++] = ch;
    }
    fclose(f);
    fill_tail_classic(vm, n);
    return n;
}

static int vm_read_cstr(VM *vm, int ptr, char *buf, size_t cap) {
    if (cap == 0) return -1;
    size_t i = 0;
    while (i + 1 < cap) {
        int w = vm->mem[(ptr + (int)i) % MEM_SIZE];
        if (w == 0) break;
        buf[i++] = (char)(w & 0xff);
    }
    buf[i] = '\0';
    return (int)i;
}


static char **vm_read_strv(VM *vm, int ptr, int max_items) {
    // A VM argv/envp vector is an array of VM pointers to NUL-terminated
    // strings, terminated by word 0. Address 0 is reserved as NULL in
    // pointer-vector context.
    if (ptr == 0) {
        return calloc(1, sizeof(char *));
    }
    if (max_items <= 0) max_items = 1;
    char **out = calloc((size_t)max_items + 1, sizeof(char *));
    if (!out) return NULL;

    for (int i = 0; i < max_items; i++) {
        int sptr = vm->mem[(ptr + i) % MEM_SIZE];
        if (sptr == 0) {
            out[i] = NULL;
            return out;
        }
        char tmp[4096];
        vm_read_cstr(vm, sptr % MEM_SIZE, tmp, sizeof tmp);
        out[i] = strdup(tmp);
        if (!out[i]) {
            for (int j = 0; j < i; j++) free(out[j]);
            free(out);
            return NULL;
        }
    }
    out[max_items] = NULL;
    return out;
}

static void free_strv(char **v) {
    if (!v) return;
    for (int i = 0; v[i]; i++) free(v[i]);
    free(v);
}

static pid_t vm_pid_arg(int word) {
    // Common M8 encoding for -1 is 59048. Other negative pids are not needed yet.
    if (word == WORD_MOD - 1) return (pid_t)-1;
    return (pid_t)word;
}

static void vm_install_argv(VM *vm, int argc, char **argv) {
    if (argc < 0) argc = 0;
    if (argc > M8_ABI_MAX_ARGS) argc = M8_ABI_MAX_ARGS;

    vm->mem[M8_ABI_ARGC] = argc;
    vm->mem[M8_ABI_ARGV] = M8_ABI_ARGVEC;
    for (int i = 0; i <= M8_ABI_MAX_ARGS; i++) {
        vm->mem[(M8_ABI_ARGVEC + i) % MEM_SIZE] = 0;
    }

    int cursor = M8_ABI_STRINGS;
    for (int i = 0; i < argc; i++) {
        const char *s = argv[i] ? argv[i] : "";
        size_t len = strlen(s);
        if (cursor + (int)len + 1 >= MEM_SIZE) {
            break;
        }
        vm->mem[(M8_ABI_ARGVEC + i) % MEM_SIZE] = cursor;
        for (size_t j = 0; j < len; j++) {
            vm->mem[(cursor + (int)j) % MEM_SIZE] = (unsigned char)s[j];
        }
        cursor += (int)len;
        vm->mem[cursor % MEM_SIZE] = 0;
        cursor++;
    }
}

static long m8_trap(VM *vm, int oldC) {
    int sysno = frame_word_at(vm, oldC, 0);
    int raw0 = frame_word_at(vm, oldC, 1);
    int raw1 = frame_word_at(vm, oldC, 2);
    int raw2 = frame_word_at(vm, oldC, 3);
    int raw3 = frame_word_at(vm, oldC, 4);
    int raw4 = frame_word_at(vm, oldC, 5);
    int a0 = (raw0 == ARG_A) ? vm->A : raw0;
    int a1 = (raw1 == ARG_A) ? vm->A : raw1;
    int a2 = (raw2 == ARG_A) ? vm->A : raw2;
    int a3 = (raw3 == ARG_A) ? vm->A : raw3;
    int a4 = (raw4 == ARG_A) ? vm->A : raw4;
    (void)a3;
    (void)a4;

    if (vm->trace) {
        if (raw0 == ARG_A || raw1 == ARG_A || raw2 == ARG_A || raw3 == ARG_A || raw4 == ARG_A) {
            fprintf(stderr, "trap sys=%d args=[%d,%d,%d,%d,%d] raw=[%d,%d,%d,%d,%d]\n",
                    sysno, a0, a1, a2, a3, a4, raw0, raw1, raw2, raw3, raw4);
        } else {
            fprintf(stderr, "trap sys=%d args=[%d,%d,%d,%d,%d]\n", sysno, a0, a1, a2, a3, a4);
        }
    }

    switch (sysno) {
        case 0: { // read(fd, vm_ptr, len)
            int fd = a0;
            int ptr = a1 % MEM_SIZE;
            int len = a2;
            if (len < 0) len = 0;
            char *buf = calloc((size_t)len ? (size_t)len : 1, 1);
            if (!buf) return -ENOMEM;
            ssize_t r = read(fd, buf, (size_t)len);
            if (r > 0) {
                for (ssize_t i = 0; i < r; i++) {
                    vm->mem[(ptr + (int)i) % MEM_SIZE] = (unsigned char)buf[i];
                }
            }
            free(buf);
            return r < 0 ? -errno : r;
        }
        case 1: { // write(fd, vm_ptr, len)
            int fd = a0;
            int ptr = a1 % MEM_SIZE;
            int len = a2;
            if (len < 0) len = 0;
            char *buf = malloc((size_t)len ? (size_t)len : 1);
            if (!buf) return -ENOMEM;
            for (int i = 0; i < len; i++) {
                buf[i] = (char)(vm->mem[(ptr + i) % MEM_SIZE] & 0xff);
            }
            ssize_t r = write(fd, buf, (size_t)len);
            free(buf);
            return r < 0 ? -errno : r;
        }
        case 2: { // open(path_ptr, flags, mode)
            char path[4096];
            vm_read_cstr(vm, a0 % MEM_SIZE, path, sizeof path);
            int fd = open(path, a1, (mode_t)a2);
            return fd < 0 ? -errno : fd;
        }
        case 3: { // close(fd)
            int r = close(a0);
            return r < 0 ? -errno : r;
        }
        case 33: { // dup2(oldfd, newfd)
            int r = dup2(a0, a1);
            return r < 0 ? -errno : r;
        }
        case 34: { // pause()
            int r = pause();
            return r < 0 ? -errno : r;
        }
        case 35: { // nanosleep(seconds, nanoseconds)
            struct timespec req;
            req.tv_sec = a0;
            req.tv_nsec = a1;
            if (req.tv_nsec < 0) req.tv_nsec = 0;
            if (req.tv_nsec > 999999999L) req.tv_nsec = 999999999L;
            int r = nanosleep(&req, NULL);
            return r < 0 ? -errno : 0;
        }
        case 39: { // getpid()
            return (long)getpid();
        }
        case 57: { // fork()
            pid_t r = fork();
            return r < 0 ? -errno : (long)r;
        }
        case 59: { // execve(path_ptr, argv_ptr, envp_ptr)
            char path[4096];
            vm_read_cstr(vm, a0 % MEM_SIZE, path, sizeof path);
            char **argv = vm_read_strv(vm, a1 % MEM_SIZE, 64);
            char **envp = vm_read_strv(vm, a2 % MEM_SIZE, 64);
            if (!argv || !envp) {
                free_strv(argv);
                free_strv(envp);
                return -ENOMEM;
            }
            execve(path, argv, envp);
            int err = errno;
            free_strv(argv);
            free_strv(envp);
            return -err;
        }
        case 61: { // wait4(pid, status_ptr_or_0, options, rusage_ptr_ignored)
            int status = 0;
            pid_t pid = vm_pid_arg(a0);
            pid_t r = wait4(pid, &status, a2, NULL);
            if (r < 0) return -errno;
            if (a1 != 0) {
                vm->mem[a1 % MEM_SIZE] = mod_word(status);
            }
            return (long)r;
        }
        case 79: { // getcwd(vm_ptr, max_len)
            int ptr = a0 % MEM_SIZE;
            int max_len = a1;
            if (max_len <= 0) return -EINVAL;
            char *buf = calloc((size_t)max_len, 1);
            if (!buf) return -ENOMEM;
            if (!getcwd(buf, (size_t)max_len)) {
                int err = errno;
                free(buf);
                return -err;
            }
            int n = (int)strlen(buf);
            for (int i = 0; i <= n && i < max_len; i++) {
                vm->mem[(ptr + i) % MEM_SIZE] = (unsigned char)buf[i];
            }
            free(buf);
            return n;
        }
        case 80: { // chdir(path_ptr)
            char path[4096];
            vm_read_cstr(vm, a0 % MEM_SIZE, path, sizeof path);
            int r = chdir(path);
            return r < 0 ? -errno : r;
        }
        case 83: { // mkdir(path_ptr, mode)
            char path[4096];
            vm_read_cstr(vm, a0 % MEM_SIZE, path, sizeof path);
            int r = mkdir(path, (mode_t)a1);
            return r < 0 ? -errno : r;
        }
        case 112: { // setsid()
            pid_t r = setsid();
            return r < 0 ? -errno : (long)r;
        }
        case 165: { // mount(source_ptr, target_ptr, fstype_ptr, flags, data_ptr_or_0)
            char source[4096];
            char target[4096];
            char fstype[256];
            char data[4096];
            vm_read_cstr(vm, a0 % MEM_SIZE, source, sizeof source);
            vm_read_cstr(vm, a1 % MEM_SIZE, target, sizeof target);
            vm_read_cstr(vm, a2 % MEM_SIZE, fstype, sizeof fstype);
            const void *data_ptr = NULL;
            if (a4 != 0) {
                vm_read_cstr(vm, a4 % MEM_SIZE, data, sizeof data);
                data_ptr = data;
            }
            int r = mount(source, target, fstype, (unsigned long)a3, data_ptr);
            return r < 0 ? -errno : r;
        }
        case 217: { // getdents64(fd, vm_ptr, max_len)
            int fd = a0;
            int ptr = a1 % MEM_SIZE;
            int max_len = a2;
            if (max_len <= 0) return 0;
            if (max_len > MEM_SIZE) max_len = MEM_SIZE;
            unsigned char *buf = calloc((size_t)max_len, 1);
            if (!buf) return -ENOMEM;
            long r = syscall(SYS_getdents64, fd, buf, (unsigned int)max_len);
            if (r < 0) {
                int err = errno;
                free(buf);
                return -err;
            }
            for (long i = 0; i < r; i++) {
                vm->mem[(ptr + (int)i) % MEM_SIZE] = buf[i];
            }
            free(buf);
            return r;
        }
        case 60: { // exit(code)
            vm->halted = 1;
            vm->exit_code = a0 & 0xff;
            return a0;
        }
        default:
            fprintf(stderr, "m8: unsupported syscall/trap number %d\n", sysno);
            return -ENOSYS;
    }
}

static int step(VM *vm) {
    int oldC = vm->C;
    int cell = vm->mem[oldC];
    if (cell < 33 || cell > 126) {
        fprintf(stderr, "m8: attempted to execute non-code cell at C=%d value=%d\n", oldC, cell);
        vm->halted = 1;
        vm->exit_code = 127;
        return -1;
    }

    char direct_op = '\0';
    int lineage_op = 0;
    char op = effective_op(vm, oldC, cell, &direct_op, &lineage_op);
    int trap_skip = 0;
    int exact_c = 0;

    if (vm->trace) {
        if (lineage_op && direct_op != op) {
            fprintf(stderr, "C=%05d D=%05d A=%05d cell=%03d op=%c direct=%c cipher-gen\n", vm->C, vm->D, vm->A, cell, op, direct_op ? direct_op : '?');
        } else {
            fprintf(stderr, "C=%05d D=%05d A=%05d cell=%03d op=%c\n", vm->C, vm->D, vm->A, cell, op ? op : '?');
        }
    }

    switch (op) {
        case 'j':
            vm->D = vm->mem[vm->D] % MEM_SIZE;
            break;
        case 'i':
            vm->C = vm->mem[vm->D] % MEM_SIZE;
            break;
        case '*':
            vm->mem[vm->D] = rotate_right_trit(vm->mem[vm->D]);
            vm->A = vm->mem[vm->D];
            break;
        case 'p':
            vm->mem[vm->D] = crazy(vm->A, vm->mem[vm->D]);
            vm->A = vm->mem[vm->D];
            break;
        case '/': {
            int ch = getchar();
            vm->A = (ch == EOF) ? 59048 : (unsigned char)ch;
            break;
        }
        case '<':
            if (vm->A != 59048) putchar(vm->A & 0xff);
            break;
        case 'v':
            vm->halted = 1;
            break;
        case 'o':
            break;
        case '@': {
            long r = m8_trap(vm, oldC);
            vm->last_error = (r < 0);
            vm->A = mod_word(r);
            trap_skip = FRAME_WORDS * frame_span(vm);
            break;
        }
        case '!': { // M8 absolute jump: inline frame [target]
            vm->C = frame_word_at(vm, oldC, 0) % MEM_SIZE;
            exact_c = 1;
            break;
        }
        case '?': { // M8 branch: inline frame [target, mode]
            int target = frame_word_at(vm, oldC, 0) % MEM_SIZE;
            int mode = frame_word_at(vm, oldC, 1);
            int take = 0;
            switch (mode) {
                case 0: take = 1; break;
                case 1: take = (vm->A == 0); break;
                case 2: take = (vm->A != 0); break;
                case 3: take = vm->last_error; break;
                case 4: take = !vm->last_error; break;
                default:
                    fprintf(stderr, "m8: unknown branch mode %d at C=%d\n", mode, oldC);
                    take = 0;
                    break;
            }
            vm->C = take ? target : ((oldC + 1 + 2 * frame_span(vm)) % MEM_SIZE);
            exact_c = 1;
            break;
        }
        case '=': { // M8 store accumulator: inline frame [target]
            int target = frame_word_at(vm, oldC, 0) % MEM_SIZE;
            vm->mem[target] = mod_word(vm->A);
            vm->C = (oldC + 1 + frame_span(vm)) % MEM_SIZE;
            exact_c = 1;
            break;
        }
        case '~': { // M8 load accumulator: inline frame [source]
            int source = frame_word_at(vm, oldC, 0) % MEM_SIZE;
            vm->A = vm->mem[source];
            vm->C = (oldC + 1 + frame_span(vm)) % MEM_SIZE;
            exact_c = 1;
            break;
        }
        case '#': { // M8 set accumulator: inline frame [value]
            vm->A = mod_word(frame_word_at(vm, oldC, 0));
            vm->C = (oldC + 1 + frame_span(vm)) % MEM_SIZE;
            exact_c = 1;
            break;
        }
        case '+': { // M8 add immediate: inline frame [value]
            vm->A = mod_word((long)vm->A + frame_word_at(vm, oldC, 0));
            vm->C = (oldC + 1 + frame_span(vm)) % MEM_SIZE;
            exact_c = 1;
            break;
        }
        case '-': { // M8 subtract immediate: inline frame [value]
            vm->A = mod_word((long)vm->A - frame_word_at(vm, oldC, 0));
            vm->C = (oldC + 1 + frame_span(vm)) % MEM_SIZE;
            exact_c = 1;
            break;
        }
        case '[': { // M8 add memory word: inline frame [source]
            int source = frame_word_at(vm, oldC, 0) % MEM_SIZE;
            vm->A = mod_word((long)vm->A + vm->mem[source]);
            vm->C = (oldC + 1 + frame_span(vm)) % MEM_SIZE;
            exact_c = 1;
            break;
        }
        case ']': { // M8 subtract memory word: inline frame [source]
            int source = frame_word_at(vm, oldC, 0) % MEM_SIZE;
            vm->A = mod_word((long)vm->A - vm->mem[source]);
            vm->C = (oldC + 1 + frame_span(vm)) % MEM_SIZE;
            exact_c = 1;
            break;
        }
        case ':': { // M8 compare with memory word: A = 0 if equal, else 1
            int source = frame_word_at(vm, oldC, 0) % MEM_SIZE;
            vm->A = (vm->A == vm->mem[source]) ? 0 : 1;
            vm->C = (oldC + 1 + frame_span(vm)) % MEM_SIZE;
            exact_c = 1;
            break;
        }
        case '^': { // M8 indirect load: A = mem[mem[source]]
            int source = frame_word_at(vm, oldC, 0) % MEM_SIZE;
            int ptr = vm->mem[source] % MEM_SIZE;
            vm->A = vm->mem[ptr];
            vm->C = (oldC + 1 + frame_span(vm)) % MEM_SIZE;
            exact_c = 1;
            break;
        }
        case '$': { // M8 indirect store: mem[mem[target]] = A
            int target = frame_word_at(vm, oldC, 0) % MEM_SIZE;
            int ptr = vm->mem[target] % MEM_SIZE;
            vm->mem[ptr] = mod_word(vm->A);
            vm->C = (oldC + 1 + frame_span(vm)) % MEM_SIZE;
            exact_c = 1;
            break;
        }
        case '`': { // M8 jump through memory word: C = mem[source]
            int source = frame_word_at(vm, oldC, 0) % MEM_SIZE;
            vm->C = vm->mem[source] % MEM_SIZE;
            exact_c = 1;
            break;
        }
        default:
            // Runtime NOP, matching Malbolge's "decoded non-instruction = nop" execution behavior.
            break;
    }

    self_cipher_executed_cell(vm, oldC, cell, lineage_op);

    if (!vm->halted) {
        if (trap_skip) {
            vm->C = (oldC + 1 + trap_skip) % MEM_SIZE;
        } else if (exact_c) {
            vm->C %= MEM_SIZE;
        } else {
            vm->C = (vm->C + 1) % MEM_SIZE;
        }
        vm->D = (vm->D + 1) % MEM_SIZE;
    }
    return 0;
}

static int run(VM *vm, unsigned long max_steps) {
    for (unsigned long i = 0; !vm->halted && i < max_steps; i++) {
        step(vm);
    }
    if (!vm->halted) {
        fprintf(stderr, "m8: max steps exceeded (%lu)\n", max_steps);
        return 124;
    }
    return vm->exit_code;
}

int main(int argc, char **argv) {
    if (strlen(XLAT1) != 94 || strlen(XLAT2) != 94) {
        fprintf(stderr, "internal error: xlat table lengths are %zu and %zu, expected 94\n",
                strlen(XLAT1), strlen(XLAT2));
        return 99;
    }

    int classic = 0;
    unsigned long max_steps = DEFAULT_MAX_STEPS;
    VM vm;
    memset(&vm, 0, sizeof vm);

    const char *path = NULL;
    int image_arg_index = -1;
    for (int i = 1; i < argc; i++) {
        if (!path && strcmp(argv[i], "--trace") == 0) {
            vm.trace = 1;
        } else if (!path && strcmp(argv[i], "--classic") == 0) {
            classic = 1;
        } else if (!path && strcmp(argv[i], "--max-steps") == 0) {
            if (++i >= argc) die_usage(argv[0]);
            max_steps = strtoul(argv[i], NULL, 10);
        } else if (!path && argv[i][0] == '-') {
            die_usage(argv[0]);
        } else {
            path = argv[i];
            image_arg_index = i;
            break;
        }
    }
    if (!path) {
        const char *env_path = getenv("M8_INIT_IMAGE");
        if (env_path && *env_path) {
            path = env_path;
        } else if (access("/sbin/init.mb", R_OK) == 0) {
            path = "/sbin/init.mb";
        } else if (access("/sbin/init.m8i", R_OK) == 0) {
            // Backwards compatibility for older initramfs images.
            path = "/sbin/init.m8i";
        } else {
            die_usage(argv[0]);
        }
    }

    int loaded = classic ? load_classic(&vm, path, 1) : load_image(&vm, path);
    if (loaded < 0) return 2;
    prepare_extension_lineage(&vm, 1);
    if (image_arg_index >= 0) {
        vm_install_argv(&vm, argc - image_arg_index, &argv[image_arg_index]);
    } else {
        char *default_argv[] = {(char *)path, NULL};
        vm_install_argv(&vm, 1, default_argv);
    }
    if (vm.trace) fprintf(stderr, "loaded %d cells\n", loaded);

    return run(&vm, max_steps);
}
