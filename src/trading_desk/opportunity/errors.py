"""Fail-closed Opportunity Engine errors."""


class OpportunityError(RuntimeError):
    pass


class OpportunityConfigurationError(OpportunityError):
    pass


class OpportunityStateError(OpportunityError):
    pass
