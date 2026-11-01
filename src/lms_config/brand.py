"""Brand rows for screen headers and footers.

The columns are the ones on ``lms.cfg_brand``: display name, support
contacts, logo key, and statement footer. This is presentation only.
The calculation engine does not read it.

Which row is used is the rule already written for this table. No rows:
no logo and no footer. One row: that row's logo key and statement footer.
More than one row for the organisation: nothing is chosen.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Brand:
    organisation_id: str
    brand_code: str
    display_name: str
    support_phone: str | None = None
    support_email: str | None = None
    logo_object_key: str | None = None
    statement_footer: str | None = None


@dataclass(frozen=True, slots=True)
class BrandChrome:
    """The logo and footer a screen may paint. ``status`` is none, one, or many."""

    status: str
    logo_object_key: str | None = None
    statement_footer: str | None = None


class BrandStore:
    def __init__(self) -> None:
        self._rows: dict[tuple[str, str], Brand] = {}

    def put(self, brand: Brand) -> Brand:
        if not brand.organisation_id or not brand.organisation_id.strip():
            raise ValueError("A brand row needs an organisation id.")
        if not brand.brand_code or not brand.brand_code.strip():
            raise ValueError("A brand row needs a brand code.")
        if not isinstance(brand.display_name, str) or not brand.display_name.strip():
            raise ValueError("A brand row needs a display name.")
        self._rows[(brand.organisation_id, brand.brand_code)] = brand
        return brand

    def presentation(self, organisation_id: str) -> BrandChrome:
        rows = [row for (org, _code), row in self._rows.items() if org == organisation_id]
        if len(rows) == 0:
            return BrandChrome("none")
        if len(rows) > 1:
            return BrandChrome("many")
        row = rows[0]
        logo = row.logo_object_key.strip() if isinstance(row.logo_object_key, str) else ""
        footer = row.statement_footer if isinstance(row.statement_footer, str) else None
        return BrandChrome("one", logo or None, footer)
