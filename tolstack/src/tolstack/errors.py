"""Structured exceptions. Every error carries a message meant for the engineer, not a stack trace."""


class TolstackError(Exception):
    """Base class for all tolstack errors."""


class UnitError(TolstackError):
    """Unknown, ambiguous or incompatible unit."""


class ModelError(TolstackError):
    """The engineering model is malformed (bad ids, contradictory data, out-of-range values)."""


class InsufficientInformation(TolstackError):
    """The inputs do not allow the requested evaluation."""


class UnsupportedFeature(TolstackError):
    """The requested case is outside the implemented scope (stated explicitly, never approximated silently)."""


class AnalysisBlocked(TolstackError):
    """Analysis refused because the selected chain is Invalid, lacks information, or was rejected."""
