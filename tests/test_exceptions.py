from apps.core.exceptions import (
    BusinessOSException,
    ConflictError,
    InvalidTransitionError,
    PermissionDeniedError,
    PlanEntitlementError,
    RecordNotFoundError,
    TenantAccessError,
    ValidationError,
)


def test_business_os_exception_defaults() -> None:
    exc = BusinessOSException()
    assert str(exc) == "An unexpected business exception occurred."
    assert exc.code == "business_error"
    assert exc.details == {}


def test_business_os_exception_custom() -> None:
    exc = BusinessOSException("Custom message", code="custom_code", details={"field": "error"})
    assert str(exc) == "Custom message"
    assert exc.code == "custom_code"
    assert exc.details == {"field": "error"}


def test_subclass_exceptions() -> None:
    assert isinstance(TenantAccessError(), BusinessOSException)
    assert isinstance(PermissionDeniedError(), BusinessOSException)
    assert isinstance(PlanEntitlementError(), BusinessOSException)
    assert isinstance(InvalidTransitionError(), BusinessOSException)
    assert isinstance(ValidationError(), BusinessOSException)
    assert isinstance(RecordNotFoundError(), BusinessOSException)
    assert isinstance(ConflictError(), BusinessOSException)
