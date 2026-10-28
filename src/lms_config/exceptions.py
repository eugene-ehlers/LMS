"""Failures the calculation engine must not paper over."""


class CalculationInputError(Exception):
    """A required input is missing, inconsistent, or outside Day-1 scope.

    Callers fail the posting. They do not substitute a statutory maximum
    for a missing contractual term, and they do not invent a rand amount
    the regulations do not state.
    """
