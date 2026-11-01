"""Staff and self-service screens.

Staff screens call the existing staff routes, the collections view, and the
collections write-off. Registration and sign-on direct the consumer to
Enigma. Statement and settlement-quote screens paint what is already stored.
"""

from lms.staff_ui.app import StaffApp, build_app

__all__ = ["StaffApp", "build_app"]
