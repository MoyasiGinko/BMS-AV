"""Domain events published by the automation engine."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from apps.core.events import DomainEvent


@dataclass(frozen=True)
class AutomationRuleCreated(DomainEvent):
    event_type: ClassVar[str] = "automation.rule.created"
    rule_id: int = 0
    rule_name: str = ""
    trigger_type: str = ""
    trigger_event: str = ""


@dataclass(frozen=True)
class AutomationRuleUpdated(DomainEvent):
    event_type: ClassVar[str] = "automation.rule.updated"
    rule_id: int = 0
    rule_name: str = ""


@dataclass(frozen=True)
class AutomationRuleDeleted(DomainEvent):
    event_type: ClassVar[str] = "automation.rule.deleted"
    rule_id: int = 0
    rule_name: str = ""


@dataclass(frozen=True)
class AutomationRuleToggled(DomainEvent):
    event_type: ClassVar[str] = "automation.rule.toggled"
    rule_id: int = 0
    is_active: bool = False


@dataclass(frozen=True)
class AutomationRuleExecuted(DomainEvent):
    event_type: ClassVar[str] = "automation.rule.executed"
    run_id: int = 0
    rule_id: int = 0
    status: str = ""
    trigger_event_type: str = ""
    execution_time_ms: int = 0
