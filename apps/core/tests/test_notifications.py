"""Unit tests for Core Email Adapters and pure Notification functions."""

from __future__ import annotations

from apps.core import notifications


def test_fake_email_adapter_recording_and_clearing() -> None:
    """Verify FakeEmailAdapter records dispatched emails into in-memory outbox."""
    adapter = notifications.FakeEmailAdapter()
    adapter.clear()
    assert len(adapter.outbox) == 0

    success = adapter.send_mail(
        subject="Welcome to Business OS",
        message="Hello World!",
        recipient_list=["client@example.com"],
        from_email="no-reply@bos.local",
    )

    assert success is True
    assert len(adapter.outbox) == 1
    record = adapter.outbox[0]
    assert record.subject == "Welcome to Business OS"
    assert "client@example.com" in record.to

    adapter.clear()
    assert len(adapter.outbox) == 0


def test_get_and_set_email_adapter() -> None:
    """Verify runtime adapter override and reset."""
    custom_adapter = notifications.FakeEmailAdapter()
    notifications.set_email_adapter(custom_adapter)
    assert notifications.get_email_adapter() is custom_adapter
