"""Bankserv (ACB) collections file, the standard South African debit-order layout.

Field positions follow the FNB Online Banking Enterprise collections Bankserv
file format: 180-character records, record identifiers 02, 04, 50, 52, 92
and 94, amounts in cents. The published note that the record is 181 characters
including CR and LF does not match the field table, which sums to 180. This
module writes 180 characters and then CRLF.

Record identifiers 50 and 60 are both described only as "collections". The
layout does not assign one of them to DebiCheck. Both EFT debit orders and
DebiCheck collections use record 50. DebiCheck is carried in the two places
the layout leaves for the collector: the first 14 characters of the user
reference (mandate or agreement number) and the free-format 6 characters
after them. Tracking days stay on the LMS instruction. They are not written
into a filler the layout says must be zero.

The hash total is the sum of the homing account numbers modulo 10**12, which
is the width of the 12-digit trailer field. The layout page does not state
the algorithm.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from lms.payments.errors import PaymentRailError

RECORD_LENGTH = 180
_LINE_ENDING = "\r\n"
_HASH_MODULUS = 10**12


@dataclass(frozen=True)
class BankservTransaction:
    user_branch: str
    user_account: str
    sequence: int
    homing_branch: str
    homing_account: str
    account_type: str
    amount_cents: int
    abbreviated_name: str
    user_reference: str
    homing_name: str


def render_collections_file(
    transactions: tuple[BankservTransaction, ...],
    *,
    action_date: date,
) -> str:
    """One user data set: installation header, user header, transactions, contra, trailers."""
    if not transactions:
        raise PaymentRailError(
            "nothing-to-collect",
            "A Bankserv collections file needs at least one transaction with a positive amount.",
        )
    if action_date.year < 2000 or action_date.year > 2099:
        raise PaymentRailError(
            "action-date",
            "The Bankserv action date is YYMMDD. A year outside 2000–2099 is not written.",
        )
    lines = [
        _record("02", "0" * 178),
        _record("04", "0" * 178),
    ]
    account_total = 0
    first = transactions[0]
    for transaction in transactions:
        if transaction.user_branch != first.user_branch or transaction.user_account != first.user_account:
            raise PaymentRailError(
                "nominated-account",
                "This file uses one nominated account. A second account would need its own contra.",
            )
        lines.append(_transaction(transaction))
        account_total += _account_integer(transaction.homing_account)
    lines.append(
        _contra(
            user_branch=first.user_branch,
            user_account=first.user_account,
            action_date=action_date,
        )
    )
    lines.append(_user_trailer(account_total % _HASH_MODULUS))
    lines.append(_record("94", "0" * 178))
    return _LINE_ENDING.join(lines) + _LINE_ENDING


def user_reference(*, scheme: str, purpose: str, reference: str) -> str:
    """20 characters: 14 for the mandate or loan number, 6 free-format for scheme and purpose.

    The collections layout says the first 14 characters must reflect the debit-order
    mandate or agreement number, and the remaining 6 are free format.
    """
    marker = {
        ("eft", "loan_instalment"): "DO-LN ",
        ("eft", "credit_life_premium"): "DO-CL ",
        ("debicheck", "loan_instalment"): "DC-LN ",
        ("debicheck", "credit_life_premium"): "DC-CL ",
    }.get((scheme, purpose))
    if marker is None:
        raise PaymentRailError(
            "scheme-unset",
            "The collection scheme must be eft or debicheck, and the purpose must be "
            "the loan instalment or the credit-life premium.",
        )
    head = _text(reference, 14, truncate=False)
    return head + marker


def _transaction(transaction: BankservTransaction) -> str:
    if transaction.amount_cents <= 0:
        raise PaymentRailError("amount", "A Bankserv collection amount must be a positive number of cents.")
    if transaction.sequence < 1 or transaction.sequence > 999_999:
        raise PaymentRailError("sequence", "The Bankserv user sequence is six digits and starts at 1.")
    homing_field, non_standard = _split_account(transaction.homing_account)
    body = "".join(
        (
            _exact_digits(transaction.user_branch, 6, "user branch"),
            _digits(transaction.user_account, 11, "nominated account"),
            "0000",
            f"{transaction.sequence:06d}",
            _exact_digits(transaction.homing_branch, 6, "homing branch"),
            homing_field,
            _digits(transaction.account_type, 1, "account type"),
            f"{transaction.amount_cents:011d}",
            "00000000",
            "0",
            "00",
            "0",
            _text(transaction.abbreviated_name, 10, truncate=False),
            _text(transaction.user_reference, 20, truncate=False),
            _text(transaction.homing_name, 15, truncate=True),
            "0" * 15,
            non_standard,
            "0" * 30,
        )
    )
    return _record("50", body)


def _contra(*, user_branch: str, user_account: str, action_date: date) -> str:
    """Contra record 52. The action date sits at positions 59–64 so the collection can be future-dated."""
    body = "".join(
        (
            _exact_digits(user_branch, 6, "user branch"),
            _digits(user_account, 11, "nominated account"),
            "0" * 39,
            action_date.strftime("%y%m%d"),
            "0" * 116,
        )
    )
    return _record("52", body)


def _user_trailer(hash_total: int) -> str:
    body = "".join(("0" * 70, f"{hash_total:012d}", "0" * 96))
    return _record("92", body)


def _record(identifier: str, body: str) -> str:
    record = identifier + body
    if len(record) != RECORD_LENGTH:
        raise PaymentRailError(
            "record-length",
            f"A Bankserv record must be {RECORD_LENGTH} characters. This one is {len(record)}.",
        )
    return record


def _split_account(account_number: str) -> tuple[str, str]:
    digits = _digits(account_number, 20, "homing account")
    if len(account_number) <= 11:
        return account_number.zfill(11), "0" * 20
    return "0" * 11, digits.zfill(20) if len(digits) < 20 else digits


def _account_integer(account_number: str) -> int:
    return int(_digits(account_number, 20, "homing account"))


def _exact_digits(value: str, length: int, label: str) -> str:
    if not value.isdigit() or len(value) != length:
        raise PaymentRailError(
            "account-field",
            f"The {label} must be exactly {length} digits.",
        )
    return value


def _digits(value: str, length: int, label: str) -> str:
    if not value.isdigit() or len(value) > length or not value:
        raise PaymentRailError(
            "account-field",
            f"The {label} must be 1–{length} digits. LOCKED_DECISIONS §21 does not supply a substitute.",
        )
    return value.zfill(length)


def _text(value: str, length: int, *, truncate: bool) -> str:
    if any(ord(character) < 32 or ord(character) > 126 for character in value):
        raise PaymentRailError("reference", "A Bankserv text field must be printable ASCII.")
    if len(value) > length:
        if not truncate:
            raise PaymentRailError(
                "reference",
                f"A Bankserv text field is {length} characters. The value is longer and is not truncated.",
            )
        value = value[:length]
    return value.ljust(length)
