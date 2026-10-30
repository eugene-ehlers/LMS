"""Append-only in-memory store. There is no update of a transaction."""

from __future__ import annotations

from lms.ledger.errors import LedgerError
from lms.ledger.models import LoanAccount, Transaction


class LedgerStore:
    def __init__(self) -> None:
        self._accounts: dict[tuple[str, str], LoanAccount] = {}
        self._transactions: list[Transaction] = []
        self._sequence: dict[str, int] = {}
        self._statements: set[tuple[str, str, object, object]] = set()

    def add(self, account: LoanAccount) -> None:
        key = (account.organisation_id, account.loan_id)
        if key in self._accounts:
            raise LedgerError("duplicate", "This loan is already booked for the organisation.")
        self._accounts[key] = account

    def get(self, organisation_id: str, loan_id: str) -> LoanAccount:
        account = self._accounts.get((organisation_id, loan_id))
        if account is None:
            raise LedgerError("not-found", "No loan with that id is visible for this organisation.")
        return account

    def accounts_for(self, organisation_id: str) -> tuple[LoanAccount, ...]:
        return tuple(
            account
            for (org, _), account in self._accounts.items()
            if org == organisation_id
        )

    def next_sequence(self, organisation_id: str) -> int:
        sequence = self._sequence.get(organisation_id, 0) + 1
        self._sequence[organisation_id] = sequence
        return sequence

    def append(self, transaction: Transaction) -> None:
        if any(existing.transaction_id == transaction.transaction_id for existing in self._transactions):
            raise LedgerError("duplicate", "A ledger transaction id cannot be reused.")
        self._transactions.append(transaction)

    def transactions_for(
        self,
        organisation_id: str,
        loan_id: str | None = None,
    ) -> tuple[Transaction, ...]:
        return tuple(
            transaction
            for transaction in self._transactions
            if transaction.organisation_id == organisation_id
            and (loan_id is None or transaction.loan_id == loan_id)
        )

    def get_transaction(self, organisation_id: str, transaction_id: str) -> Transaction:
        for transaction in self._transactions:
            if (
                transaction.organisation_id == organisation_id
                and transaction.transaction_id == transaction_id
            ):
                return transaction
        raise LedgerError("not-found", "No transaction with that id is visible for this organisation.")

    def remember_statement(self, key: tuple[str, str, object, object]) -> None:
        if key in self._statements:
            raise LedgerError(
                "statement-exists",
                "LOCKED_DECISIONS §12: one statement per client per credit-provider organisation.",
            )
        self._statements.add(key)

    def statement_keys(self, organisation_id: str, person_id: str) -> tuple[tuple[object, object], ...]:
        return tuple(
            (start, end)
            for org, person, start, end in self._statements
            if org == organisation_id and person == person_id
        )
