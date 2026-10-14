class CorvoError(Exception):
    """A business error. The business logic raises it, knowing nothing of HTTP."""


class NotFoundError(CorvoError):
    """What was asked for does not exist."""


class ConflictError(CorvoError):
    """The request clashes with the current state."""
