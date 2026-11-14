"""Shared POSIX-exact ``fcntl.flock`` binding for file-backed stores.

Single owner of the ``msvcrt.locking``-based shim first merged in R11
(src/qualification_campaign/evidence.py).  Consumers bind the module-level
``fcntl`` name once:

    from src.platform_compat.flock import fcntl

On POSIX this is the standard-library ``fcntl`` module itself; on win32 it is
the shim instance below, which replicates the exact flock operations those
stores perform on dedicated never-written lock files.  No try/except-ImportError
fallback is used anywhere: platform selection is a ``sys.platform`` guard so
static analysis stays platform-conditional (mypy analyzes only the win32 branch
on win32 and only the POSIX branch on POSIX).
"""

import errno
import sys
import time
import os

if sys.platform == "win32":
    # win32: emulate the flock operations used by consumers of this module.  A
    # sys.platform guard (not try/except ImportError) keeps static analysis
    # platform-conditional: mypy analyzes this branch only on win32 and the
    # POSIX branch below only on POSIX, so msvcrt attributes are never checked
    # against POSIX typeshed.  Runtime selection is unchanged: win32 uses the
    # shim, every other platform imports real fcntl.
    import msvcrt

    class _PosixFlockShim:
        """``fcntl.flock``-compatible whole-file advisory lock for Windows.

        Replicates, via ``msvcrt.locking`` over the fixed byte range
        ``[0, 2**31 - 1)`` anchored at offset 0, the exact operations the
        adopting modules perform on dedicated never-written lock files:
        blocking ``LOCK_EX`` acquire (flock blocks indefinitely, so
        ``LK_NBLCK`` is retried instead of ``LK_LOCK``'s bounded 10s wait)
        and ``LOCK_UN`` release of a held lock.  ``LOCK_NB`` contention
        raises ``BlockingIOError`` like POSIX ``EWOULDBLOCK``.  Locks are
        per open handle, matching flock's per-open-file-description scope,
        so two handles (processes or threads) exclude each other.  Because
        the lock file is never written, locking from offset 0 is
        equivalent to flock's whole-file lock for cooperating processes,
        and the advisory-versus-mandatory distinction is unobservable.
        ``LOCK_SH`` is unavailable in ``msvcrt`` and is conservatively
        mapped to the exclusive lock (no weakening; unused by consumers).
        The constants carry the POSIX fcntl values.  POSIX hosts take the
        POSIX branch below and never enter this branch.
        """

        LOCK_SH = 0x01
        LOCK_EX = 0x02
        LOCK_NB = 0x04
        LOCK_UN = 0x08

        _RANGE_LENGTH = 2**31 - 1

        @staticmethod
        def _fileno(fd):
            return fd.fileno() if hasattr(fd, "fileno") else fd

        def _locked_range_call(self, handle, mode):
            previous = os.lseek(handle, 0, os.SEEK_CUR)
            try:
                os.lseek(handle, 0, os.SEEK_SET)
                msvcrt.locking(handle, mode, self._RANGE_LENGTH)
            finally:
                os.lseek(handle, previous, os.SEEK_SET)

        def flock(self, fd, operation):
            handle = self._fileno(fd)
            if operation & self.LOCK_UN:
                self._locked_range_call(handle, msvcrt.LK_UNLCK)
                return
            nonblocking = bool(operation & self.LOCK_NB)
            if nonblocking:
                try:
                    self._locked_range_call(handle, msvcrt.LK_NBLCK)
                except OSError as error:
                    raise BlockingIOError(
                        errno.EAGAIN, "resource temporarily unavailable"
                    ) from error
                return
            while True:
                try:
                    self._locked_range_call(handle, msvcrt.LK_NBLCK)
                    return
                except OSError:
                    time.sleep(0.002)

    # Deliberate rebinding of the fcntl module name to the shim instance on
    # win32 only.  No type: ignore is needed: mypy treats the two
    # platform-conditional branches as independent first bindings, so no
    # [assignment] error is raised (and with warn_unused_ignores enabled an
    # ignore here would itself error under win32 analysis).
    fcntl = _PosixFlockShim()
else:
    import fcntl
