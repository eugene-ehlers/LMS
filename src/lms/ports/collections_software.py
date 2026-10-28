"""Collections-software port.

The LMS flags an account that is in collections default. The software may
acknowledge the flag. It is not asked to generate collection notices, and this
port has no notice operation. The LMS does not send collection notices.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from lms.errors import ContractError
from lms.validation import require_optional_text, require_text


@dataclass(frozen=True)
class CollectionsDefaultFlag:
    """An account is in collections default.

    ``application_number`` is the link the collections software uses to reach
    the client database. The LMS does not attach contact details.
    """

    loan_number: str
    application_number: str
    id_number: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "loan_number", require_text(self.loan_number, "loan_number"))
        object.__setattr__(
            self,
            "application_number",
            require_text(self.application_number, "application_number"),
        )
        object.__setattr__(self, "id_number", require_optional_text(self.id_number, "id_number"))


@dataclass(frozen=True)
class CollectionsAcknowledgement:
    """The collections software received the flag. There is no notice content."""

    loan_number: str
    application_number: str
    acknowledged: Literal[True] = True

    def __post_init__(self) -> None:
        if self.acknowledged is not True:
            raise ContractError("an acknowledgement is only returned when the flag was received")
        object.__setattr__(self, "loan_number", require_text(self.loan_number, "loan_number"))
        object.__setattr__(
            self,
            "application_number",
            require_text(self.application_number, "application_number"),
        )


@runtime_checkable
class CollectionsSoftware(Protocol):
    """LMS call site: ``collections.flag_collections_default(flag)``."""

    def flag_collections_default(
        self, flag: CollectionsDefaultFlag
    ) -> CollectionsAcknowledgement | None:
        """Accept a collections-default flag. Return an acknowledgement, or nothing."""
