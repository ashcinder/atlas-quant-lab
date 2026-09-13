"""One disposable, unprivileged strategy process. Receives no signing/KMS key."""
import ctypes
import json
import os
import resource
import sys

# Load before locking syscalls. The parent launches this via python -I.
lib = ctypes.CDLL('libseccomp.so.2')
lib.seccomp_init.restype = ctypes.c_void_p
lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
lib.seccomp_load.argtypes = [ctypes.c_void_p]
lib.seccomp_release.argtypes = [ctypes.c_void_p]
lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]

def main():
    request = json.loads(sys.stdin.buffer.readline(512_000))
    # No root privileges, network, child processes, ptrace, mounts or NSM ioctl.
    resource.setrlimit(resource.RLIMIT_AS, (256 * 1024**2, 256 * 1024**2))
    resource.setrlimit(resource.RLIMIT_CPU, (2, 2))
    resource.setrlimit(resource.RLIMIT_FSIZE, (128, 128))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    os.setgroups([])
    os.setgid(65532)
    os.setuid(65532)
    ctx = lib.seccomp_init(0x7fff0000)  # default ALLOW; blocked syscalls kill process
    if not ctx:
        raise RuntimeError()
    for name in ('socket', 'socketpair', 'connect', 'bind', 'listen', 'accept', 'accept4',
                 'clone', 'clone3', 'fork', 'vfork', 'execve', 'execveat', 'ptrace',
                 'process_vm_readv', 'process_vm_writev', 'mount', 'ioctl', 'bpf',
                 'io_uring_setup', 'userfaultfd', 'setns', 'unshare'):
        number = lib.seccomp_syscall_resolve_name(name.encode())
        if number >= 0 and lib.seccomp_rule_add(ctx, 0x80000000, number, 0) != 0:
            raise RuntimeError()
    if lib.seccomp_load(ctx) != 0:
        raise RuntimeError()
    lib.seccomp_release(ctx)
    scope = {}
    exec(compile(request['source'], '<strategy>', 'exec'), scope)
    target = str(scope['decide'](request['context']))
    sys.stdout.write(target)

if __name__ == '__main__':
    try:
        main()
    except BaseException:
        os._exit(1)
