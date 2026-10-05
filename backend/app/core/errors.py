"""Application errors. The API layer turns these into the standard response envelope."""


class AppError(Exception):
    status_code = 400

    def __init__(self, message: str, errors: list[str] | None = None, headers: dict[str, str] | None = None):
        super().__init__(message)
        self.message = message
        self.errors = errors or []
        self.headers = headers or {}


class ValidationFailed(AppError):
    status_code = 422


class UnauthorizedError(AppError):
    status_code = 401

    def __init__(self, message: str = "Authentication required"):
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"})


class ForbiddenError(AppError):
    status_code = 403


class NotFoundError(AppError):
    status_code = 404


class ConflictError(AppError):
    status_code = 409


class ServiceUnavailableError(AppError):
    status_code = 503


class RateLimitedError(AppError):
    status_code = 429

    def __init__(self, retry_after: int):
        super().__init__("Too many requests. Please slow down.", headers={"Retry-After": str(retry_after)})
