"""Restructure path.

A restructure changes the contractual term or the contractual instalment.
The decision engine supplies the new rate, term, and instalment. This package
stores those values and does not re-decide them.
"""

from lms.restructure.api import dispatch
from lms.restructure.service import RestructureService

__all__ = ["RestructureService", "dispatch"]
