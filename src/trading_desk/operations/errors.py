"""Sanitized operations-domain errors."""


class OperationsError(Exception):
    pass


class OperationsDisabledError(OperationsError):
    pass


class OperationsQueryError(OperationsError):
    pass
