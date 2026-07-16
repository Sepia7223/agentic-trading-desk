"""Safe execution-domain exceptions."""


class ExecutionError(Exception):
    """Base exception that never carries raw broker request data."""


class ExecutionConfigurationError(ExecutionError):
    pass


class ExecutionPolicyViolation(ExecutionError):
    pass


class ExecutionBrokerError(ExecutionError):
    def __init__(
        self,
        message: str,
        *,
        operation: str,
        http_status: int | None = None,
        error_code: str | None = None,
        request_id: str | None = None,
        ambiguous: bool = False,
    ) -> None:
        self.operation = operation
        self.http_status = http_status
        self.error_code = error_code
        self.request_id = request_id
        self.ambiguous = ambiguous
        details = [f"operation={operation}"]
        if http_status is not None:
            details.append(f"status={http_status}")
        if error_code is not None:
            details.append(f"error_code={error_code}")
        if request_id is not None:
            details.append(f"request_id={request_id}")
        super().__init__(f"{message} ({', '.join(details)})")
