"""Staff screens that call the existing staff and collection-campaign routes.

Consumer registration, collection notices, and the push provider are not
in this package.
"""

from lms.staff_ui.app import StaffApp, build_app

__all__ = ["StaffApp", "build_app"]
