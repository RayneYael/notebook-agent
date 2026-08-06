"""Fail-closed channel identity errors."""


class IdentityError(RuntimeError):
    pass


class UnboundIdentity(IdentityError):
    pass


class DisabledIdentity(IdentityError):
    pass


class InvalidLinkToken(IdentityError):
    pass


class ExpiredLinkToken(InvalidLinkToken):
    pass


class UsedLinkToken(InvalidLinkToken):
    pass


class IdentityConflict(IdentityError):
    pass
