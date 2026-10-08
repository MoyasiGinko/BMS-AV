"""Exceptions for the Sales and Invoicing module."""


class SalesError(Exception):
    """Base exception for all sales errors."""


class DocumentNotFoundError(SalesError):
    """Raised when a requested sales document is not found."""


class InvalidStateTransitionError(SalesError):
    """Raised when an illegal status change is attempted on a sales document."""


class DocumentLockedError(SalesError):
    """Raised when attempting to edit a posted or finalized sales document."""


class CustomerSuspendedError(SalesError):
    """Raised when attempting to post sales for a suspended customer."""


class CreditLimitExceededError(SalesError):
    """Raised when a sale would breach the customer's approved credit limit."""


class InsufficientStockError(SalesError):
    """Raised when required inventory is unavailable to fulfill a sale."""


class AccountingPeriodClosedError(SalesError):
    """Raised when posting a sales document into a closed accounting fiscal period."""


class InvoiceAlreadyPostedError(SalesError):
    """Raised when attempting to re-post an already posted invoice."""


class CreditNoteAlreadyPostedError(SalesError):
    """Raised when attempting to re-post an already posted credit note."""


class VoidNotAllowedError(SalesError):
    """Raised when a document cannot be voided due to payments or invalid state."""


class EmptyDocumentError(SalesError):
    """Raised when attempting to post or confirm a document with no line items."""


class WarehouseRequiredError(SalesError):
    """Raised when a warehouse is required for inventory tracking but none is specified or found."""


class PaymentError(SalesError):
    """Base exception for payment processing errors."""


class PaymentNotFoundError(PaymentError):
    """Raised when a payment cannot be found."""


class PaymentAlreadyPostedError(PaymentError):
    """Raised when attempting to re-post an already posted payment."""


class PaymentAlreadyVoidError(PaymentError):
    """Raised when attempting to void or modify an already void payment."""


class InsufficientUnallocatedPaymentError(PaymentError):
    """Raised when attempting to allocate or refund more than the unallocated payment balance."""


class InvalidAllocationError(PaymentError):
    """Raised when an allocation amount is invalid or exceeds invoice balance due."""


class InvoiceNotPayableError(PaymentError):
    """Raised when attempting to allocate payment to an unpaid/unposted/void invoice."""
