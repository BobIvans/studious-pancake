"""Platform-conditional compatibility helpers shared across file-backed stores.

Every helper keeps POSIX behavior byte-identical and provides a documented,
conservative win32 branch instead of a bare POSIX-only import, so modules can
run unchanged on both platforms (R11 follow-up: shared flock compat module).
"""
