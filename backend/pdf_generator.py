"""Backward-compat shim. New PDF code lives in `pdf/` package."""
from pdf.invoice import build_invoice_pdf
from pdf.ledger  import build_ledger_pdf
from pdf.lr      import build_lr_pdf
from pdf.owner   import build_owner_statement_pdf
from pdf._base   import _fmt, _num_to_words_inr

__all__ = [
    "build_invoice_pdf", "build_ledger_pdf",
    "build_lr_pdf", "build_owner_statement_pdf",
    "_fmt", "_num_to_words_inr",
]
