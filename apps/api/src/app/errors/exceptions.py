from app.errors.envelope import ErrorAction, ErrorFamily


class AppError(Exception):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        family: ErrorFamily,
        retryable: bool = False,
        action: ErrorAction = "none",
        details: dict[str, object] | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.family = family
        self.retryable = retryable
        self.action = action
        self.details = details
        self.headers = headers


class DependencyUnavailableError(AppError):
    def __init__(
        self,
        *,
        dependency: str,
        message: str,
        code: str = "DEPENDENCY_UNAVAILABLE",
        retryable: bool = True,
        action: ErrorAction = "retry",
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=503,
            family="dependency",
            retryable=retryable,
            action=action,
            details={"dependency": dependency},
        )


class SecurityError(AppError):
    def __init__(self, *, code: str, message: str, status_code: int = 401) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=status_code,
            family="security",
            retryable=False,
            action="none",
        )
