class BackendOfflineError(RuntimeError):
    """Raised when register_by_ip probe fails — caller chose this backend explicitly."""
