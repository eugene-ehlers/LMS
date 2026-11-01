"""Stubs whose results are the payloads Servicing already accepts."""

from lms.stubs.debit_file import DebitFileStub, FailureReceipt, SuccessReceipt
from lms.stubs.decision_quote import DecisionQuoteStub, QuoteApproval, QuoteRequest
from lms.stubs.wire import apply_debit_receipts, book_quoted

__all__ = [
    "DebitFileStub",
    "DecisionQuoteStub",
    "FailureReceipt",
    "QuoteApproval",
    "QuoteRequest",
    "SuccessReceipt",
    "apply_debit_receipts",
    "book_quoted",
]
