#define _GNU_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <linux/landlock.h>
#include <seccomp.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <unistd.h>

#ifndef LANDLOCK_ACCESS_FS_REFER
#define LANDLOCK_ACCESS_FS_REFER (1ULL << 13)
#endif
#ifndef LANDLOCK_ACCESS_FS_TRUNCATE
#define LANDLOCK_ACCESS_FS_TRUNCATE (1ULL << 14)
#endif
#ifndef LANDLOCK_ACCESS_FS_IOCTL_DEV
#define LANDLOCK_ACCESS_FS_IOCTL_DEV (1ULL << 15)
#endif

static const uint64_t read_access =
    LANDLOCK_ACCESS_FS_READ_FILE | LANDLOCK_ACCESS_FS_READ_DIR;
static const uint64_t write_access =
    LANDLOCK_ACCESS_FS_WRITE_FILE | LANDLOCK_ACCESS_FS_REMOVE_DIR |
    LANDLOCK_ACCESS_FS_REMOVE_FILE | LANDLOCK_ACCESS_FS_MAKE_CHAR |
    LANDLOCK_ACCESS_FS_MAKE_DIR | LANDLOCK_ACCESS_FS_MAKE_REG |
    LANDLOCK_ACCESS_FS_MAKE_SOCK | LANDLOCK_ACCESS_FS_MAKE_FIFO |
    LANDLOCK_ACCESS_FS_MAKE_BLOCK | LANDLOCK_ACCESS_FS_MAKE_SYM |
    LANDLOCK_ACCESS_FS_REFER | LANDLOCK_ACCESS_FS_TRUNCATE |
    LANDLOCK_ACCESS_FS_IOCTL_DEV;

static void fail(const char *message) {
    fprintf(stderr, "shinka sandbox: %s: %s\n", message, strerror(errno));
    exit(125);
}

static void reject(const char *message) {
    fprintf(stderr, "shinka sandbox: %s\n", message);
    exit(125);
}

static bool starts_with(const char *value, const char *prefix) {
    return strncmp(value, prefix, strlen(prefix)) == 0;
}

static bool is_beneath(const char *value, const char *directory) {
    size_t length = strlen(directory);
    return starts_with(value, directory) &&
           (value[length] == '/' || value[length] == '\0');
}

static void add_path_rule(int ruleset_fd, const char *path, uint64_t access,
                          bool required) {
    int path_fd = open(path, O_PATH | O_CLOEXEC);
    if (path_fd < 0) {
        if (!required && errno == ENOENT) {
            return;
        }
        fail(path);
    }
    struct landlock_path_beneath_attr rule = {
        .allowed_access = access,
        .parent_fd = path_fd,
    };
    if (syscall(SYS_landlock_add_rule, ruleset_fd,
                LANDLOCK_RULE_PATH_BENEATH, &rule, 0) < 0) {
        close(path_fd);
        fail("landlock_add_rule");
    }
    close(path_fd);
}

static void install_landlock(const char *scratch, const char *worker) {
    int abi = (int)syscall(SYS_landlock_create_ruleset, NULL, 0,
                           LANDLOCK_CREATE_RULESET_VERSION);
    if (abi < 5) {
        reject("Landlock ABI 5 or newer is required");
    }

    struct landlock_ruleset_attr ruleset = {
        .handled_access_fs = read_access | write_access |
                             LANDLOCK_ACCESS_FS_EXECUTE,
    };
    int ruleset_fd = (int)syscall(SYS_landlock_create_ruleset, &ruleset,
                                  sizeof(ruleset), 0);
    if (ruleset_fd < 0) {
        fail("landlock_create_ruleset");
    }

    const uint64_t library_access = read_access | LANDLOCK_ACCESS_FS_EXECUTE;
    add_path_rule(ruleset_fd, "/lib", library_access, true);
    add_path_rule(ruleset_fd, "/lib64", library_access, false);
    add_path_rule(ruleset_fd, "/usr/lib", library_access, true);
    add_path_rule(ruleset_fd, "/usr/lib64", library_access, false);
    add_path_rule(ruleset_fd, "/etc/ld.so.cache", LANDLOCK_ACCESS_FS_READ_FILE,
                  false);
    add_path_rule(ruleset_fd, "/dev/null",
                  LANDLOCK_ACCESS_FS_READ_FILE |
                      LANDLOCK_ACCESS_FS_WRITE_FILE,
                  true);
    add_path_rule(ruleset_fd, "/dev/urandom", LANDLOCK_ACCESS_FS_READ_FILE,
                  true);
    add_path_rule(ruleset_fd, "/sys/devices/system/cpu", read_access, false);
    add_path_rule(ruleset_fd, worker,
                  LANDLOCK_ACCESS_FS_READ_FILE |
                      LANDLOCK_ACCESS_FS_EXECUTE,
                  true);
    add_path_rule(ruleset_fd, scratch, read_access | write_access, true);

    if (syscall(SYS_landlock_restrict_self, ruleset_fd, 0) < 0) {
        close(ruleset_fd);
        fail("landlock_restrict_self");
    }
    close(ruleset_fd);
}

static void deny_syscall(scmp_filter_ctx context, const char *name) {
    int number = seccomp_syscall_resolve_name(name);
    if (number == __NR_SCMP_ERROR) {
        return;
    }
    if (seccomp_rule_add(context, SCMP_ACT_ERRNO(EPERM), number, 0) < 0) {
        reject("could not add seccomp rule");
    }
}

static void install_seccomp(void) {
    static const char *const denied[] = {
        "socket",           "socketpair",        "connect",
        "bind",             "listen",            "accept",
        "accept4",          "sendto",            "recvfrom",
        "sendmsg",          "recvmsg",           "sendmmsg",
        "recvmmsg",         "shutdown",          "setsockopt",
        "getsockopt",       "ptrace",            "process_vm_readv",
        "process_vm_writev", "pidfd_getfd",      "open_by_handle_at",
        "name_to_handle_at", "bpf",              "perf_event_open",
        "userfaultfd",      "keyctl",            "add_key",
        "request_key",      "mount",             "umount2",
        "pivot_root",       "chroot",            "setns",
        "unshare",          "init_module",       "finit_module",
        "delete_module",    "reboot",            "swapon",
        "swapoff",          "kexec_load",        "kexec_file_load",
        "fsopen",           "fsconfig",          "fsmount",
        "open_tree",        "move_mount",        "mount_setattr",
        "io_uring_setup",   "io_uring_enter",    "io_uring_register",
    };

    scmp_filter_ctx context = seccomp_init(SCMP_ACT_ALLOW);
    if (context == NULL) {
        reject("could not initialize seccomp");
    }
    for (size_t index = 0; index < sizeof(denied) / sizeof(denied[0]); ++index) {
        deny_syscall(context, denied[index]);
    }
    if (seccomp_load(context) < 0) {
        seccomp_release(context);
        reject("could not load seccomp filter");
    }
    seccomp_release(context);
}

static void validate_contract(int argc, char **argv, const char **scratch,
                              int *worker_index) {
    if (argc != 18 || strcmp(argv[1], "--ro-bind") != 0 ||
        strcmp(argv[2], "/") != 0 || strcmp(argv[3], "/") != 0 ||
        strcmp(argv[4], "--dev") != 0 || strcmp(argv[5], "/dev") != 0 ||
        strcmp(argv[6], "--proc") != 0 || strcmp(argv[7], "/proc") != 0 ||
        strcmp(argv[8], "--bind") != 0 || strcmp(argv[9], argv[10]) != 0 ||
        strcmp(argv[11], "--unshare-net") != 0 ||
        strcmp(argv[12], "--unshare-pid") != 0 ||
        strcmp(argv[13], "--die-with-parent") != 0) {
        reject("unsupported bubblewrap invocation");
    }
    *scratch = argv[9];
    *worker_index = 14;
    const char *worker = argv[*worker_index];
    const char *ready = argv[*worker_index + 2];
    const char *proof = argv[*worker_index + 3];
    if (!starts_with(*scratch, "/data/shinka/") ||
        !starts_with(worker, "/data/shinka/eval-worktrees/") ||
        !is_beneath(ready, *scratch) || !is_beneath(proof, *scratch)) {
        reject("sandbox paths are outside the Shinka evaluation roots");
    }
    char *end = NULL;
    long log2_size = strtol(argv[*worker_index + 1], &end, 10);
    if (end == NULL || *end != '\0' || log2_size < 8 || log2_size > 20) {
        reject("invalid worker size");
    }
}

int main(int argc, char **argv) {
    if (argc == 2 && strcmp(argv[1], "--version") == 0) {
        puts("shinka-landlock-bwrap 1");
        return 0;
    }

    const char *scratch = NULL;
    int worker_index = 0;
    validate_contract(argc, argv, &scratch, &worker_index);
    if (prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) < 0) {
        fail("PR_SET_NO_NEW_PRIVS");
    }
    if (prctl(PR_SET_DUMPABLE, 0, 0, 0, 0) < 0) {
        fail("PR_SET_DUMPABLE");
    }
    if (chdir(scratch) < 0) {
        fail("chdir scratch");
    }
    install_landlock(scratch, argv[worker_index]);
    install_seccomp();
    execv(argv[worker_index], &argv[worker_index]);
    fail("exec worker");
}
