"""Provider error hierarchy. Retryability is decided by type, not by message."""


class ProviderError(Exception):
    """Base class for all provider failures."""

    retryable = False


class ProviderTimeoutError(ProviderError):
    retryable = True


class ProviderRateLimitError(ProviderError):
    """The marketplace asked us to slow down."""

    retryable = True

    def __init__(self, message: str = "Rate limited by provider", retry_after: float | None = None):
        super().__init__(message)
        self.retry_after = retry_after


class ProviderUnavailableError(ProviderError):
    """Temporary outage (5xx, connection reset)."""

    retryable = True


class ProviderAuthError(ProviderError):
    """Credentials rejected. Retrying cannot help."""


class ProviderInvalidDataError(ProviderError):
    """The provider returned data we cannot trust or parse."""


class ProviderNotImplementedError(ProviderError):
    """A real integration exists as a skeleton only."""


class CircuitOpenError(ProviderError):
    """Calls are being short-circuited after repeated failures."""
