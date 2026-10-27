"""NCR number gate.

The number is an LMS tenant attribute. Enigma does not hold it. Communications and compliance
extracts for NCA-covered products require it. Pure hosting, BNPL/laybye, and laybye-as-security
do not.
"""

from __future__ import annotations

from lms.enigma.models import LAYBYE_PRODUCTS, NCA_PRODUCTS


def ncr_number_required(*, product_code: str | None, pure_hosting: bool) -> bool:
    if pure_hosting or product_code is None:
        return False
    if product_code in LAYBYE_PRODUCTS:
        return False
    if product_code in NCA_PRODUCTS:
        return True
    # An unclassified product is not treated as exempt.
    return True
