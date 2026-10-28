"""Staff administration for campaigns, elections, compliance, and ceilings.

Statement generation is not part of this package. Consumer registration
stays on the Enigma redirect.
"""

from lms.staff.api import dispatch
from lms.staff.service import StaffOffice

__all__ = ["StaffOffice", "dispatch"]
