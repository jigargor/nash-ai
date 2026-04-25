class ReviewError(Exception):
    """Base class for all review pipeline failures."""


class ReviewRetryableError(ReviewError):
    """Transient failure that the worker should retry (e.g. GitHub 5xx, Anthropic rate limit)."""


class ReviewFatalError(ReviewError):
    """Permanent failure that should not be retried (e.g. bad config, PR not found)."""
