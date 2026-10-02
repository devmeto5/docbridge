"""Single-job subprocess: no API key, no network sockets, bounded CPU/output."""
import ctypes
import errno
import json
import os
import sys
from pathlib import Path


def restrict_linux():
    if sys.platform != 'linux':
        return
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (150, 155))
    resource.setrlimit(resource.RLIMIT_FSIZE, (80 * 1024 * 1024,) * 2)
    resource.setrlimit(resource.RLIMIT_NOFILE, (128, 128))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    # The API's sockets are closed by subprocess.Popen(close_fds=True).
    # The worker and all its children can create local Unix sockets only.
    seccomp = ctypes.CDLL('libseccomp.so.2', use_errno=True)
    class Comparison(ctypes.Structure):
        _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_uint),
                    ('datum_a', ctypes.c_uint64), ('datum_b', ctypes.c_uint64)]
    seccomp.seccomp_init.argtypes = [ctypes.c_uint32]
    seccomp.seccomp_init.restype = ctypes.c_void_p
    seccomp.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    seccomp.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32,
                                              ctypes.c_int, ctypes.c_uint,
                                              ctypes.POINTER(Comparison)]
    seccomp.seccomp_load.argtypes = [ctypes.c_void_p]
    seccomp.seccomp_release.argtypes = [ctypes.c_void_p]
    ctx = seccomp.seccomp_init(0x7FFF0000)  # SCMP_ACT_ALLOW
    if not ctx:
        raise RuntimeError('Cannot initialize worker isolation.')
    try:
        # SCMP_CMP_NE: reject socket(domain != AF_UNIX).
        comparison = Comparison(0, 1, 1, 0)
        syscall = seccomp.seccomp_syscall_resolve_name(b'socket')
        if syscall < 0 or seccomp.seccomp_rule_add_array(ctx, 0x00050000 | errno.EPERM,
                                                        syscall, 1, ctypes.byref(comparison)):
            raise RuntimeError('Cannot restrict worker networking.')
        if seccomp.seccomp_load(ctx):
            raise RuntimeError('Cannot activate worker isolation.')
    finally:
        seccomp.seccomp_release(ctx)


def main():
    work = Path(sys.argv[1]).resolve()
    try:
        restrict_linux()
        from docbridge.engine import convert, ConversionError
        options = json.loads((work / 'request.json').read_text())
        output, metadata = convert(work / ('input.' + options['source']),
                                   work=work, **options)
        result = {'ok': True, 'filename': output.name, **metadata}
    except Exception as exc:
        from docbridge.engine import ConversionError
        result = {'ok': False, 'error': str(exc) if isinstance(exc, ConversionError)
                  else 'Invalid, damaged, or unsupported document.'}
    (work / 'response.json').write_text(json.dumps(result), encoding='utf-8')


if __name__ == '__main__':
    main()
