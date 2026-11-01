"""Exceptions for the Point of Sale (POS) module."""


class POSError(Exception):
    """Base exception for Point of Sale operations."""


class RegisterNotFoundError(POSError):
    """Raised when a specified register does not exist."""


class RegisterInactiveError(POSError):
    """Raised when attempting an operation on an inactive register."""


class ShiftNotFoundError(POSError):
    """Raised when a requested shift cannot be found."""


class NoOpenShiftError(POSError):
    """Raised when attempting a checkout or sale without an open shift."""


class ShiftAlreadyOpenError(POSError):
    """Raised when attempting to open a shift on a register that already has an open shift."""


class ShiftAlreadyClosedError(POSError):
    """Raised when attempting to close or modify an already closed shift."""


class EmptyCartError(POSError):
    """Raised when attempting checkout on an empty cart."""


class InvalidPaymentTenderError(POSError):
    """Raised when payment tender amounts are invalid or do not balance."""


class InsufficientTenderError(POSError):
    """Raised when total payment tendered is less than the sale total."""


class HeldCartNotFoundError(POSError):
    """Raised when a held cart cannot be found to resume."""


class SequenceBlockExhaustedError(POSError):
    """Raised when an allocated sequence block has consumed all numbers."""
