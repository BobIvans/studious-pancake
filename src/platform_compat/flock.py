"""Shared POSIX-exact ``fcntl.flock`` binding for file-backed stores.

Single owner of the ``msvcrt.locking``-based shim first merged in R11
(src/qualification_campaign/evidence.py).  Consumers bind the module-level
``fcntl`` name once:

    from src.platform_compat.flock import fcntl

On POSIX this is the standard-library ``fcntl`` module itself; on win32 it is
the shim instance below, which replicates the exact flock operations those
stores perform on dedicated never-written lock files.  For whole-file locks on
live (written) files whose bytes other handles must still read and write,
consumers call ``flock_live_file`` instead (see its win32 rationale: msvcrt
byte-range locks are mandatory for other-handle I/O and would starve SQLite,
while POSIX flock is advisory).  No try/except-ImportError fallback is used
anywhere: platform selection is a ``sys.platform`` guard so static analysis
stays platform-conditional (mypy analyzes only the win32 branch on win32 and
only the POSIX branch on POSIX).
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

    # -- flock_live_file: advisory whole-file lock on live (written) files. --
    #
    # msvcrt byte-range locks are mandatory for every other handle's I/O on
    # the locked range, unlike POSIX flock which never blocks read/write.
    # Locking a written file from offset 0 starves its other handles, and no
    # anchored range can avoid that in general: verified natively,
    # sqlite3.connect on the same file fails with "disk I/O error" while any
    # msvcrt.locking lock is held on it (SQLite takes its own byte-range
    # locks at the 1 GiB region when opening a WAL database, CRT _locking
    # cannot address beyond 32-bit offsets, and any other range collides
    # with file data once the file grows past it).  The faithful Windows
    # equivalent of advisory flock for such files is a named mutex: no lock
    # file is created, no handle loses I/O access, contention maps to
    # flock's semantics (WAIT_TIMEOUT -> BlockingIOError = EWOULDBLOCK,
    # WAIT_ABANDONED -> acquired = flock's release-on-fd-close, INFINITE
    # wait = flock's indefinite blocking).  Because Windows mutexes are
    # thread-owned and would re-grant the owning thread, a per-process
    # registry keyed by mutex name restores flock's per-open-file-description
    # scope: a second handle -- same thread included -- is rejected like a
    # second POSIX flock on a fresh open() of the same file.  The mutex is
    # keyed by the sha256 of the absolute path (inode aliases are not
    # unified, unlike flock; the consumers use one canonical path) in the
    # Global\\ namespace for machine-wide scope like the POSIX kernel.  A
    # hostile local process could pre-own the mutex name, but that is the
    # same denial it could inflict by holding the POSIX flock itself.
    import ctypes
    import hashlib
    import threading
    import weakref
    from ctypes import wintypes

    _WAIT_OBJECT_0 = 0x00000000
    _WAIT_ABANDONED = 0x00000080
    _WAIT_TIMEOUT = 0x00000102
    _INFINITE = 0xFFFFFFFF

    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _CreateMutexW = _kernel32.CreateMutexW
    _CreateMutexW.argtypes = (wintypes.LPCWSTR, wintypes.BOOL, wintypes.LPCWSTR)
    _CreateMutexW.restype = wintypes.HANDLE
    _WaitForSingleObject = _kernel32.WaitForSingleObject
    _WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
    _WaitForSingleObject.restype = wintypes.DWORD
    _ReleaseMutex = _kernel32.ReleaseMutex
    _ReleaseMutex.argtypes = (wintypes.HANDLE,)
    _ReleaseMutex.restype = wintypes.BOOL
    _CloseHandle = _kernel32.CloseHandle
    _CloseHandle.argtypes = (wintypes.HANDLE,)
    _CloseHandle.restype = wintypes.BOOL

    class _LiveFileMutexOwner:
        """One open file description's ownership of the named mutex."""

        __slots__ = ("_handle",)

        def __init__(self, name):
            handle = _CreateMutexW(None, False, name)
            if not handle:
                raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
            self._handle = handle

        def acquire(self, blocking):
            result = _WaitForSingleObject(self._handle, _INFINITE if blocking else 0)
            if result in (_WAIT_OBJECT_0, _WAIT_ABANDONED):
                # WAIT_ABANDONED: the previous owner released by closing its
                # handle (crash or GC) instead of ReleaseMutex; ownership is
                # granted, mirroring flock's release-on-fd-close.
                return True
            if result == _WAIT_TIMEOUT:
                return False
            raise OSError(ctypes.get_last_error(), "WaitForSingleObject failed")

        def release(self):
            handle, self._handle = self._handle, None
            if handle is None:
                return
            # ReleaseMutex succeeds only on the owning thread; from any other
            # thread (GC finalizer) closing the last handle marks the mutex
            # abandoned, which the next acquirer accepts as ownership.
            _ReleaseMutex(handle)
            _CloseHandle(handle)

    _registry_guard = threading.Lock()
    _registry_owners: dict[str, tuple[weakref.ref, _LiveFileMutexOwner]] = {}

    def _live_file_mutex_name(fd):
        path = getattr(fd, "name", None)
        if not isinstance(path, str):
            raise TypeError(
                "flock_live_file requires a named file object, got "
                f"{type(fd).__name__}"
            )
        digest = hashlib.sha256(
            os.path.abspath(path).encode("utf-8", "surrogatepass")
        ).hexdigest()
        return f"Global\\studious-pancake-flock-live-{digest}"

    def _register_live_file_owner(fd, name, owner):
        entry = (weakref.ref(fd), owner)

        def _finalize(name=name, entry=entry):
            # Release only if this entry is still the registered owner; a
            # later explicit unlock may already have replaced it.
            with _registry_guard:
                if _registry_owners.get(name) is entry:
                    del _registry_owners[name]
            entry[1].release()

        weakref.finalize(fd, _finalize)
        with _registry_guard:
            _registry_owners[name] = entry

    def _unlock_live_file(fd, name):
        with _registry_guard:
            entry = _registry_owners.get(name)
            if entry is None or entry[0]() is not fd:
                # Not held by this open file description: POSIX flock(LOCK_UN)
                # on such an fd is a no-op.
                return
            del _registry_owners[name]
        entry[1].release()

    def flock_live_file(fd, operation):
        """``fcntl.flock`` equivalent for a live file other handles must use.

        POSIX: plain advisory ``fcntl.flock``; the file's regular I/O is
        unaffected because flock only arbitrates among cooperating flock
        callers.  win32: named-mutex acquisition with per-open-file-description
        registry scope (see the block comment above); ``LOCK_SH`` is
        conservatively mapped to exclusive (no weakening, unused here).
        """
        name = _live_file_mutex_name(fd)
        if operation & fcntl.LOCK_UN:
            _unlock_live_file(fd, name)
            return
        if operation & fcntl.LOCK_NB:
            with _registry_guard:
                entry = _registry_owners.get(name)
                if entry is not None and entry[0]() is fd:
                    # Same open file description already holds it; flock is
                    # idempotent there.
                    return
                if entry is not None and entry[0]() is not None:
                    raise BlockingIOError(
                        errno.EAGAIN, "resource temporarily unavailable"
                    )
            owner = _LiveFileMutexOwner(name)
            try:
                acquired = owner.acquire(blocking=False)
            except BaseException:
                owner.release()
                raise
            if not acquired:
                owner.release()
                raise BlockingIOError(errno.EAGAIN, "resource temporarily unavailable")
            _register_live_file_owner(fd, name, owner)
            return
        while True:
            with _registry_guard:
                entry = _registry_owners.get(name)
                if entry is None or entry[0]() is fd or entry[0]() is None:
                    break
            time.sleep(0.002)
        if entry is not None and entry[0]() is fd:
            return
        owner = _LiveFileMutexOwner(name)
        try:
            acquired = owner.acquire(blocking=True)
        except BaseException:
            owner.release()
            raise
        if acquired:
            _register_live_file_owner(fd, name, owner)

else:
    import fcntl

    def flock_live_file(fd, operation):
        """``fcntl.flock`` equivalent for a live file other handles must use.

        POSIX: plain advisory ``fcntl.flock``; the file's regular I/O is
        unaffected because flock only arbitrates among cooperating flock
        callers.
        """
        fcntl.flock(fd, operation)
