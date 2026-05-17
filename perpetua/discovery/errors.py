class BackendOfflineError(RuntimeError):
    """Raised when register_by_ip probe fails — caller chose this backend explicitly."""


class NoBackendAvailableError(RuntimeError):
    """No registered backend satisfies the given routing constraints."""
