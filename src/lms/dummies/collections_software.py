"""Collections-software dummy. It acknowledges a flag and generates no notice."""

from __future__ import annotations

from lms.errors import ContractError
from lms.ports.collections_software import CollectionsAcknowledgement, CollectionsDefaultFlag


class CollectionsSoftwareDummy:
    """Return a fixed acknowledgement, or nothing. There is no notice method."""

    def __init__(self, *, acknowledge: bool = True) -> None:
        if not isinstance(acknowledge, bool):
            raise ContractError("acknowledge must be a boolean")
        self._acknowledge = acknowledge

    @classmethod
    def acknowledging(cls) -> CollectionsSoftwareDummy:
        return cls(acknowledge=True)

    @classmethod
    def silent(cls) -> CollectionsSoftwareDummy:
        return cls(acknowledge=False)

    def flag_collections_default(
        self, flag: CollectionsDefaultFlag
    ) -> CollectionsAcknowledgement | None:
        if not isinstance(flag, CollectionsDefaultFlag):
            raise ContractError("flag must be a CollectionsDefaultFlag")
        if not self._acknowledge:
            return None
        return CollectionsAcknowledgement(
            loan_number=flag.loan_number,
            application_number=flag.application_number,
        )
