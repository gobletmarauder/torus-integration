"""Typed failures raised by the Torus Integration Service core."""


class TISError(Exception):
    """Base class for expected service failures."""


class ExternalError(TISError):
    """An allowlisted external service failed after bounded handling."""


class EgressDenied(TISError):
    """An outbound request targeted a host outside the allowlist."""


class BudgetExceeded(TISError):
    """An external-write budget was exhausted."""


class KillSwitchOn(TISError):
    """The global kill switch blocked an external write."""


class DuplicateWrite(TISError):
    """An idempotency record shows that a write already succeeded."""
