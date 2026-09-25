"""Domain errors, translated to HTTP status codes at the API boundary."""

from __future__ import annotations


class DomainError(Exception):
    code = "domain_error"


class NotFoundError(DomainError):
    code = "not_found"


class PermissionDeniedError(DomainError):
    code = "permission_denied"


class ConflictError(DomainError):
    """The request conflicts with the current state (e.g. editing a finalised assessment)."""

    code = "conflict"


class InvalidRequestError(DomainError):
    code = "invalid_request"
