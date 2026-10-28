import pytest

from lms.dummies.collections_software import CollectionsSoftwareDummy
from lms.errors import ContractError
from lms.ports.collections_software import (
    CollectionsAcknowledgement,
    CollectionsDefaultFlag,
    CollectionsSoftware,
)
from tests.builders import collections_flag


def test_flag_is_acknowledged_without_notice_content() -> None:
    software = CollectionsSoftwareDummy.acknowledging()

    result = software.flag_collections_default(collections_flag())

    assert isinstance(software, CollectionsSoftware)
    assert isinstance(result, CollectionsAcknowledgement)
    assert result.acknowledged is True
    assert result.loan_number == "LN-1001"
    assert result.application_number == "APP-00000001"
    assert set(result.__dataclass_fields__) == {
        "loan_number",
        "application_number",
        "acknowledged",
    }


def test_silent_mode_returns_nothing() -> None:
    software = CollectionsSoftwareDummy.silent()

    assert software.flag_collections_default(collections_flag()) is None


def test_flag_carries_the_link_identifiers_and_not_contact_details() -> None:
    flag = collections_flag()

    assert set(flag.__dataclass_fields__) == {
        "loan_number",
        "application_number",
        "id_number",
    }
    with pytest.raises(ContractError):
        collections_flag(loan_number="")
    with pytest.raises(ContractError):
        collections_flag(application_number=" ")


def test_dummy_has_no_notice_operation() -> None:
    names = [name.lower() for name in dir(CollectionsSoftwareDummy)]
    assert not any("notice" in name for name in names)


def test_call_site_accepts_another_implementation() -> None:
    class ScriptedCollections:
        def flag_collections_default(
            self, flag: CollectionsDefaultFlag
        ) -> CollectionsAcknowledgement | None:
            return None

    def flag_account(
        software: CollectionsSoftware, flag: CollectionsDefaultFlag
    ) -> CollectionsAcknowledgement | None:
        return software.flag_collections_default(flag)

    assert flag_account(ScriptedCollections(), collections_flag()) is None
    acknowledged = flag_account(CollectionsSoftwareDummy.acknowledging(), collections_flag())
    assert acknowledged is not None
    assert acknowledged.loan_number == "LN-1001"
