"""Statement brand row. Presentation only. The calculation engine does not read it.

The columns match ``lms.cfg_brand``: one row per organisation and brand code.
A statement copies the header and footer at issue. A later edit does not
rewrite a stored statement. More than one row for an organisation is
ambiguous; the statement store does not pick one.
"""

from __future__ import annotations

from dataclasses import dataclass

from lms_config.exceptions import CalculationInputError


@dataclass(frozen=True, slots=True)
class Brand:
    organisation_id: str
    brand_code: str
    display_name: str
    support_phone: str | None = None
    support_email: str | None = None
    logo_object_key: str | None = None
    statement_footer: str | None = None


class BrandStore:
    """In-memory ``lms.cfg_brand``. Keyed by organisation and brand code."""

    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], Brand] = {}

    def put(self, brand: Brand) -> None:
        if not brand.organisation_id or not brand.organisation_id.strip():
            raise CalculationInputError("A brand row needs an organisation id.")
        if not brand.brand_code or not brand.brand_code.strip():
            raise CalculationInputError("A brand row needs a brand code.")
        if not brand.display_name or not brand.display_name.strip():
            raise CalculationInputError(
                "LOCKED_DECISIONS §12: a brand header needs a display name. A blank name is not stored."
            )
        self._rows[(brand.organisation_id, brand.brand_code)] = brand

    def for_organisation(self, organisation_id: str) -> tuple[Brand, ...]:
        return tuple(
            brand
            for (org, _code), brand in sorted(self._rows.items())
            if org == organisation_id
        )
