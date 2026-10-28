"""NCR number gate for regulatory extracts.

Locked decision 21. The number is an LMS tenant attribute. Enigma does not
hold it. A blank number blocks a micro or unsecured personal extract. It
does not block booking, and this module does not book.

The ledger classifications are ``short_term`` and ``unsecured``. The Day-1
templates that publish those classifications are named ``micro_short_term``
and ``unsecured_personal``. Decision 21 says "micro" and "unsecured
personal" and does not name the classification strings. The mapping below
is that template reading. It is recorded as gap RX24.
"""

from __future__ import annotations

from lms.regulatory.errors import RegulatoryError
from lms_config.compliance import ComplianceStore
from lms_config.validate import CPA_LAYBY, SHORT_TERM, UNSECURED, ZERO_COST

# Decision 21: not required for Laybye/BNPL. These are the Day-1
# classifications of ``bnpl_zero`` and ``layby_goods``.
_NCR_NOT_REQUIRED = frozenset({ZERO_COST, CPA_LAYBY})

# Decision 21: required for micro and unsecured personal, unless the tenant
# is pure hosting. ``short_term`` is the classification of ``micro_short_term``.
_NCR_REQUIRED = frozenset({SHORT_TERM, UNSECURED})


def ncr_number_required(*, classification: str, pure_hosting: bool) -> bool:
    """Decision 21. ``pure_hosting`` must already be true or false."""
    if pure_hosting:
        return False
    if classification in _NCR_NOT_REQUIRED:
        return False
    if classification in _NCR_REQUIRED:
        return True
    # An unclassified product is not treated as exempt.
    return True


def read_ncr_number(compliance: ComplianceStore, organisation_id: str) -> str | None:
    """Decision 15 and 21. Read the LMS compliance row. Do not call Enigma.

    A missing row or a blank number is ``None``. No number is invented.
    """
    record = compliance.find(organisation_id)
    if record is None:
        return None
    number = record.ncr_registration_number.strip()
    # A test number of all zeros is a real value (decision 21). Only a blank is missing.
    if not number:
        return None
    return number


def require_ncr_for_extract(
    compliance: ComplianceStore,
    *,
    organisation_id: str,
    classifications: tuple[str, ...],
    pure_hosting: bool | None,
) -> str | None:
    """Return the NCR number the extract may carry.

    When no classification in the extract requires the number, a missing
    number stays ``None``. When one does, a missing number fails closed
    (decision 21). ``pure_hosting`` has no column on the compliance row
    (gap RX23). ``None`` fails closed when a requiring classification is
    present. It is not read as false.
    """
    if pure_hosting is None:
        if any(ncr_number_required(classification=code, pure_hosting=False) for code in classifications):
            raise RegulatoryError(
                "pure-hosting-unset",
                "Decision 21: pure hosting is not stored on the LMS compliance row. "
                "The extract does not assume the tenant is a credit provider.",
            )
        return read_ncr_number(compliance, organisation_id)
    if not isinstance(pure_hosting, bool):
        raise RegulatoryError(
            "pure-hosting-unset",
            "Decision 21: pure hosting must be true or false. The extract does not coerce it.",
        )

    required = any(
        ncr_number_required(classification=code, pure_hosting=pure_hosting) for code in classifications
    )
    number = read_ncr_number(compliance, organisation_id)
    if required and number is None:
        raise RegulatoryError(
            "ncr-number-unset",
            "Decision 21: a blank NCR number blocks a micro or unsecured personal extract. "
            "The number is read from LMS tenant configuration.",
        )
    return number
