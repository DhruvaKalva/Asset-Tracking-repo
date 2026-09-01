"""Domain errors. The API layer maps these to status codes; the domain stays
framework-free so it can be unit-tested and reused by workers and the CLI."""


class DomainError(Exception):
    status_code = 400


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    status_code = 409
