class CorvoError(Exception):
    """A business error. The services raise it, knowing nothing of HTTP."""


class NotFoundError(CorvoError):
    """What was asked for does not exist."""


class ConflictError(CorvoError):
    """The request clashes with the current state."""
