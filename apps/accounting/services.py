"""Services for minimal accounting core: double-entry ledger, postings, and reversals."""

from __future__ import annotations

import calendar
import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.accounting.events import (
    FiscalPeriodClosed,
    JournalEntryPosted,
    JournalEntryReversed,
)
from apps.accounting.exceptions import (
    AccountInactiveError,
    AccountNotFoundError,
    AlreadyReversedError,
    EmptyEntryError,
    InvalidEntryError,
    InvalidEntryStateError,
    PeriodClosed,
    UnbalancedEntryError,
)
from apps.accounting.models import (
    Account,
    AccountMapping,
    AccountType,
    FiscalPeriod,
    FiscalYear,
    JournalEntry,
    JournalLine,
)
from apps.core.events import publish
from apps.core.services import generate_next_number
from apps.tenancy.models import Organization

DECIMAL_ZERO = Decimal("0.0000")
FOUR_PLACES = Decimal("0.0001")
SIX_PLACES = Decimal("0.000001")


@dataclass
class JournalLineInput:
    """Input specification for a single debit or credit line in a journal entry."""

    account: Any  # Account instance, code str, or mapping key str
    debit: Decimal = DECIMAL_ZERO
    credit: Decimal = DECIMAL_ZERO
    memo: str = ""
    currency: str = "USD"
    fx_rate: Decimal = Decimal("1.000000")
    party_type: str = ""
    party_id: str = ""


def Dr(
    account: Any,
    amount: Decimal | str | int | float,
    *,
    memo: str = "",
    currency: str = "USD",
    fx_rate: Decimal | str | int | float = Decimal("1.000000"),
    party_type: str = "",
    party_id: str = "",
) -> JournalLineInput:
    """Construct a Debit line input helper."""
    return JournalLineInput(
        account=account,
        debit=Decimal(str(amount)),
        credit=DECIMAL_ZERO,
        memo=memo,
        currency=currency,
        fx_rate=Decimal(str(fx_rate)),
        party_type=party_type,
        party_id=party_id,
    )


def Cr(
    account: Any,
    amount: Decimal | str | int | float,
    *,
    memo: str = "",
    currency: str = "USD",
    fx_rate: Decimal | str | int | float = Decimal("1.000000"),
    party_type: str = "",
    party_id: str = "",
) -> JournalLineInput:
    """Construct a Credit line input helper."""
    return JournalLineInput(
        account=account,
        debit=DECIMAL_ZERO,
        credit=Decimal(str(amount)),
        memo=memo,
        currency=currency,
        fx_rate=Decimal(str(fx_rate)),
        party_type=party_type,
        party_id=party_id,
    )


def resolve_account(*, organization: Organization, account_ref: Any) -> Account:
    """Resolve an Account instance from an Account object, mapping key, or account code.

    Resolution order:
    1. Direct Account instance (validates same organization)
    2. AccountMapping by key (e.g. 'sales.revenue', 'ar', 'cogs')
    3. Account by exact code (e.g. '1010', '4000')
    """
    if isinstance(account_ref, Account):
        if account_ref.organization_id != organization.pk:
            raise AccountNotFoundError(f"Account '{account_ref.code}' belongs to a different organization.")
        if not account_ref.is_active:
            raise AccountInactiveError(f"Account '{account_ref.code}' is inactive.")
        return account_ref

    ref_str = str(account_ref).strip()
    if not ref_str:
        raise AccountNotFoundError("Account reference cannot be empty.")

    # 1. Try AccountMapping key
    mapping = (
        AccountMapping.all_tenants.filter(
            organization=organization,
            mapping_key=ref_str,
        )
        .select_related("account")
        .first()
    )
    if mapping is not None:
        if not mapping.account.is_active:
            raise AccountInactiveError(f"Account '{mapping.account.code}' is inactive.")
        return mapping.account

    # 2. Try exact code
    account = Account.all_tenants.filter(organization=organization, code=ref_str).first()
    if account is not None:
        if not account.is_active:
            raise AccountInactiveError(f"Account '{account.code}' is inactive.")
        return account

    raise AccountNotFoundError(
        f"Account or mapping key '{ref_str}' not found for organization {organization.name}."
    )


def check_fiscal_period_open(*, organization: Organization, posting_date: datetime.date) -> None:
    """Verify that posting_date does not fall into a closed fiscal period or year."""
    # Check closed fiscal period
    closed_period = FiscalPeriod.all_tenants.filter(
        organization=organization,
        start_date__lte=posting_date,
        end_date__gte=posting_date,
        status=FiscalPeriod.STATUS_CLOSED,
    ).first()
    if closed_period is not None:
        raise PeriodClosed(
            f"Cannot post to date {posting_date}: fiscal period '{closed_period.name}' is closed."
        )

    # Check closed fiscal year
    closed_year = FiscalYear.all_tenants.filter(
        organization=organization,
        start_date__lte=posting_date,
        end_date__gte=posting_date,
        is_closed=True,
    ).first()
    if closed_year is not None:
        raise PeriodClosed(f"Cannot post to date {posting_date}: fiscal year '{closed_year.name}' is closed.")


def _parse_line(
    *,
    idx: int,
    line: JournalLineInput | dict[str, Any],
    organization: Organization,
) -> dict[str, Any]:
    """Parse and validate a single journal entry line."""
    if isinstance(line, JournalLineInput):
        acc_ref = line.account
        debit_val = line.debit
        credit_val = line.credit
        line_memo = line.memo
        line_curr = line.currency or organization.base_currency or "USD"
        line_fx = line.fx_rate
        party_type = line.party_type
        party_id = line.party_id
    elif isinstance(line, dict):
        acc_ref = line.get("account")
        debit_val = line.get("debit", DECIMAL_ZERO)
        credit_val = line.get("credit", DECIMAL_ZERO)
        line_memo = line.get("memo", "")
        line_curr = line.get("currency") or organization.base_currency or "USD"
        line_fx = line.get("fx_rate", Decimal("1.000000"))
        party_type = line.get("party_type", "")
        party_id = line.get("party_id", "")
    else:
        raise InvalidEntryError(f"Unsupported line type: {type(line)}")

    account = resolve_account(organization=organization, account_ref=acc_ref)

    debit = Decimal(str(debit_val)).quantize(FOUR_PLACES)
    credit = Decimal(str(credit_val)).quantize(FOUR_PLACES)
    fx_rate = Decimal(str(line_fx)).quantize(SIX_PLACES)

    if debit < DECIMAL_ZERO or credit < DECIMAL_ZERO:
        raise InvalidEntryError(f"Line {idx}: Debit and credit amounts must be non-negative.")

    if debit > DECIMAL_ZERO and credit > DECIMAL_ZERO:
        raise InvalidEntryError(f"Line {idx}: Line cannot have both debit and credit amounts.")

    if debit == DECIMAL_ZERO and credit == DECIMAL_ZERO:
        raise InvalidEntryError(f"Line {idx}: Line must have either a debit or credit amount.")

    base_amt = ((debit - credit) * fx_rate).quantize(FOUR_PLACES)

    return {
        "line_number": idx,
        "account": account,
        "debit": debit,
        "credit": credit,
        "currency": line_curr,
        "fx_rate": fx_rate,
        "base_amount": base_amt,
        "memo": line_memo,
        "party_type": party_type,
        "party_id": party_id,
    }


@transaction.atomic
def post_entry(
    *,
    organization: Organization,
    date: datetime.date,
    lines: Sequence[JournalLineInput | dict[str, Any]],
    actor: Any = None,
    memo: str = "",
    source: Any = None,
    source_type: str = "",
    source_id: str = "",
    entry_number: str = "",
) -> JournalEntry:
    """Post a balanced double-entry transaction to the general ledger.

    Enforces:
    1. Open fiscal period/year check.
    2. Account resolution and active status.
    3. Non-negative, mutually-exclusive debit and credit on each line.
    4. Mathematical balance: sum(debits) == sum(credits) > 0.
    5. Minimum 2 lines.
    6. Transactional Outbox domain event emission.
    """
    check_fiscal_period_open(organization=organization, posting_date=date)

    if len(lines) < 2:
        raise InvalidEntryError("Journal entry must contain at least 2 lines.")

    resolved_lines = [
        _parse_line(idx=idx, line=line, organization=organization) for idx, line in enumerate(lines, start=1)
    ]

    total_debit = sum((item["debit"] for item in resolved_lines), DECIMAL_ZERO)
    total_credit = sum((item["credit"] for item in resolved_lines), DECIMAL_ZERO)

    if total_debit <= DECIMAL_ZERO:
        raise EmptyEntryError("Journal entry total debit must be greater than zero.")

    if total_debit != total_credit:
        raise UnbalancedEntryError(
            f"Journal entry is unbalanced: debits ({total_debit}) != credits ({total_credit})."
        )

    # Resolve document number
    if not entry_number:
        entry_number = generate_next_number(
            organization_id=organization.pk,
            name="Journal Entries",
            prefix="JE-",
            padding=5,
            actor=actor,
            current_date=date,
        )

    # Determine source metadata
    src_type = source_type
    src_id = source_id
    if source is not None:
        if not src_type:
            src_type = source.__class__.__name__.lower()
        if not src_id:
            src_id = str(getattr(source, "pk", ""))

    entry = JournalEntry.objects.create(
        organization=organization,
        entry_number=entry_number,
        date=date,
        memo=memo,
        status=JournalEntry.STATUS_POSTED,
        source_type=src_type,
        source_id=src_id,
        total_debit=total_debit,
        total_credit=total_credit,
        posted_at=timezone.now(),
        posted_by=actor if getattr(actor, "is_authenticated", False) else None,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    lines_to_create = [
        JournalLine(
            organization=organization,
            entry=entry,
            line_number=item["line_number"],
            account=item["account"],
            debit=item["debit"],
            credit=item["credit"],
            currency=item["currency"],
            fx_rate=item["fx_rate"],
            base_amount=item["base_amount"],
            memo=item["memo"],
            party_type=item["party_type"],
            party_id=item["party_id"],
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )
        for item in resolved_lines
    ]
    JournalLine.objects.bulk_create(lines_to_create)

    # If source has journal_entry foreign key attribute, link it
    if source is not None and hasattr(source, "journal_entry"):
        source.journal_entry = entry
        if hasattr(source, "save"):
            source.save(update_fields=["journal_entry"])

    publish(
        JournalEntryPosted(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            entry_id=entry.pk,
            entry_number=entry.entry_number,
            entry_date=str(date),
            total_amount=str(total_debit),
            source_type=src_type,
            source_id=src_id,
        )
    )

    return entry


@transaction.atomic
def reverse_entry(
    *,
    organization: Organization,
    entry: JournalEntry,
    actor: Any = None,
    date: datetime.date | None = None,
    reason: str = "",
) -> JournalEntry:
    """Reverse an existing posted journal entry by posting symmetrical opposite lines."""
    locked_entry = (
        JournalEntry.all_tenants.select_for_update().filter(pk=entry.pk, organization=organization).first()
    )
    if locked_entry is None:
        raise InvalidEntryStateError("Journal entry not found.")

    if locked_entry.reversed_by is not None:
        raise AlreadyReversedError(f"Journal entry {locked_entry.entry_number} has already been reversed.")

    if locked_entry.status != JournalEntry.STATUS_POSTED:
        raise InvalidEntryStateError(
            f"Cannot reverse journal entry in status '{locked_entry.status}'. Must be 'posted'."
        )

    reversal_date = date or timezone.now().date()
    check_fiscal_period_open(organization=organization, posting_date=reversal_date)

    # Invert debits and credits
    reversed_lines: list[JournalLineInput] = []
    lines_to_reverse = (
        JournalLine.all_tenants.filter(entry=locked_entry, organization=organization)
        .select_related("account")
        .order_by("line_number")
    )
    for line in lines_to_reverse:
        reversed_lines.append(
            JournalLineInput(
                account=line.account,
                debit=line.credit,
                credit=line.debit,
                memo=f"Reversal of {line.memo}".strip() if line.memo else "Reversal line",
                currency=line.currency,
                fx_rate=line.fx_rate,
                party_type=line.party_type,
                party_id=line.party_id,
            )
        )

    reversal_memo = f"Reversal of {locked_entry.entry_number}"
    if reason:
        reversal_memo = f"{reversal_memo}: {reason}"

    reversal_entry = post_entry(
        organization=organization,
        date=reversal_date,
        lines=reversed_lines,
        actor=actor,
        memo=reversal_memo,
        source=locked_entry,
        source_type="reversal",
        source_id=str(locked_entry.pk),
    )

    locked_entry.reversed_by = reversal_entry
    locked_entry.status = JournalEntry.STATUS_REVERSED
    locked_entry.reversal_reason = reason
    locked_entry.save(update_fields=["reversed_by", "status", "reversal_reason", "updated_at"])

    publish(
        JournalEntryReversed(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            entry_id=locked_entry.pk,
            reversal_entry_id=reversal_entry.pk,
            entry_number=locked_entry.entry_number,
            reversal_number=reversal_entry.entry_number,
            reason=reason,
        )
    )

    return reversal_entry


@transaction.atomic
def close_fiscal_period(
    *,
    organization: Organization,
    period: FiscalPeriod,
    actor: Any = None,
) -> FiscalPeriod:
    """Close a fiscal period against any further postings."""
    period.status = FiscalPeriod.STATUS_CLOSED
    period.closed_at = timezone.now()
    period.closed_by = actor if getattr(actor, "is_authenticated", False) else None
    period.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])

    publish(
        FiscalPeriodClosed(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            period_id=period.pk,
            period_name=period.name,
            fiscal_year_id=period.fiscal_year_id,
        )
    )
    return period


@transaction.atomic
def reopen_fiscal_period(
    *,
    organization: Organization,
    period: FiscalPeriod,
    actor: Any = None,
) -> FiscalPeriod:
    """Reopen a previously closed fiscal period."""
    period.status = FiscalPeriod.STATUS_OPEN
    period.closed_at = None
    period.closed_by = None
    period.save(update_fields=["status", "closed_at", "closed_by", "updated_at"])
    return period


# ---------------------------------------------------------------------------
# Chart of Accounts Seed Template
# ---------------------------------------------------------------------------

STANDARD_CHART_OF_ACCOUNTS: list[dict[str, Any]] = [
    # Assets (1000 - 1999)
    {
        "code": "1010",
        "name": "Cash on Hand",
        "type": AccountType.ASSET,
        "description": "Cash held in registers and petty cash",
    },
    {
        "code": "1020",
        "name": "Operating Bank Account",
        "type": AccountType.ASSET,
        "description": "Primary checking / operating bank account",
    },
    {
        "code": "1100",
        "name": "Accounts Receivable",
        "type": AccountType.ASSET,
        "is_control": True,
        "description": "Amounts owed by customers on credit",
    },
    {
        "code": "1200",
        "name": "Inventory Asset",
        "type": AccountType.ASSET,
        "is_control": True,
        "description": "Value of merchandise and materials on hand",
    },
    {
        "code": "1300",
        "name": "Undeposited Funds",
        "type": AccountType.ASSET,
        "description": "Funds received awaiting bank deposit",
    },
    {
        "code": "1500",
        "name": "Property, Plant & Equipment",
        "type": AccountType.ASSET,
        "description": "Fixed capital assets",
    },
    # Liabilities (2000 - 2999)
    {
        "code": "2000",
        "name": "Accounts Payable",
        "type": AccountType.LIABILITY,
        "is_control": True,
        "description": "Amounts owed to suppliers and vendors",
    },
    {
        "code": "2100",
        "name": "Sales Tax / VAT Output",
        "type": AccountType.LIABILITY,
        "description": "Tax collected from customers payable to authorities",
    },
    {
        "code": "2110",
        "name": "Tax / VAT Input",
        "type": AccountType.ASSET,
        "description": "Tax paid on purchases recoverable from authorities",
    },
    {
        "code": "2200",
        "name": "Payroll Liabilities",
        "type": AccountType.LIABILITY,
        "description": "Wages, deductions, and payroll taxes payable",
    },
    {
        "code": "2300",
        "name": "Accrued Expenses",
        "type": AccountType.LIABILITY,
        "description": "Expenses incurred but not yet invoiced or paid",
    },
    # Equity (3000 - 3999)
    {
        "code": "3000",
        "name": "Owner's Equity",
        "type": AccountType.EQUITY,
        "description": "Capital contributed by owners/shareholders",
    },
    {
        "code": "3100",
        "name": "Retained Earnings",
        "type": AccountType.EQUITY,
        "description": "Cumulative net income retained in business",
    },
    {
        "code": "3200",
        "name": "Owner's Drawings",
        "type": AccountType.EQUITY,
        "description": "Distributions taken by owners",
    },
    # Revenue (4000 - 4999)
    {
        "code": "4000",
        "name": "Sales Revenue",
        "type": AccountType.REVENUE,
        "description": "Revenue from sale of merchandise and goods",
    },
    {
        "code": "4100",
        "name": "Service Revenue",
        "type": AccountType.REVENUE,
        "description": "Revenue from professional services delivered",
    },
    {
        "code": "4200",
        "name": "Sales Discounts",
        "type": AccountType.REVENUE,
        "description": "Contra-revenue account for sales discounts allowed",
    },
    {
        "code": "4900",
        "name": "Other Income",
        "type": AccountType.REVENUE,
        "description": "Incidental or non-operating income",
    },
    # Expenses (5000 - 6999)
    {
        "code": "5000",
        "name": "Cost of Goods Sold",
        "type": AccountType.EXPENSE,
        "description": "Direct cost of products sold to customers",
    },
    {
        "code": "5100",
        "name": "Freight & Delivery Expense",
        "type": AccountType.EXPENSE,
        "description": "Shipping, logistics, and delivery costs",
    },
    {
        "code": "6000",
        "name": "Salaries & Wages Expense",
        "type": AccountType.EXPENSE,
        "description": "Employee wages, salaries, and bonuses",
    },
    {
        "code": "6100",
        "name": "Rent Expense",
        "type": AccountType.EXPENSE,
        "description": "Premises and warehouse rental expense",
    },
    {
        "code": "6200",
        "name": "Utilities Expense",
        "type": AccountType.EXPENSE,
        "description": "Electricity, water, gas, internet",
    },
    {
        "code": "6300",
        "name": "Office Supplies Expense",
        "type": AccountType.EXPENSE,
        "description": "Office consumables and materials",
    },
    {
        "code": "6400",
        "name": "Marketing & Advertising",
        "type": AccountType.EXPENSE,
        "description": "Promotional and advertising expenses",
    },
    {
        "code": "6500",
        "name": "Bank & Payment Processing Fees",
        "type": AccountType.EXPENSE,
        "description": "Bank charges, POS merchant fees, transfer charges",
    },
    {
        "code": "6600",
        "name": "Depreciation Expense",
        "type": AccountType.EXPENSE,
        "description": "Amortization and depreciation of fixed assets",
    },
    {
        "code": "9999",
        "name": "Suspense / Clearing Account",
        "type": AccountType.EXPENSE,
        "description": "Temporary clearing account for unclassified transactions",
    },
]

STANDARD_ACCOUNT_MAPPINGS: list[tuple[str, str, str]] = [
    ("sales.revenue", "4000", "Default sales revenue account for goods sold"),
    ("sales.service", "4100", "Default service revenue account"),
    ("sales.discount", "4200", "Default discounts allowed contra-revenue account"),
    ("inventory.asset", "1200", "Default inventory asset valuation control account"),
    ("cogs", "5000", "Default cost of goods sold expense account"),
    ("ar", "1100", "Default accounts receivable control account"),
    ("ap", "2000", "Default accounts payable control account"),
    ("tax.output", "2100", "Default sales tax / VAT output liability account"),
    ("tax.input", "2110", "Default tax / VAT input recoverable account"),
    ("cash", "1010", "Default cash on hand asset account"),
    ("bank", "1020", "Default operating bank account"),
    ("undeposited_funds", "1300", "Default undeposited customer funds clearing account"),
    ("payroll.expense", "6000", "Default salaries and wages expense account"),
    ("payroll.liability", "2200", "Default payroll liabilities payable account"),
    ("retained_earnings", "3100", "Default retained earnings equity account"),
    ("suspense", "9999", "Default suspense / clearing account"),
]


@transaction.atomic
def seed_chart_of_accounts(
    *,
    organization: Organization,
    template: str = "standard",
) -> dict[str, Account]:
    """Seed standard chart of accounts and default account mappings for an organization."""
    accounts: dict[str, Account] = {}

    for item in STANDARD_CHART_OF_ACCOUNTS:
        acc, _ = Account.all_tenants.get_or_create(
            organization=organization,
            code=item["code"],
            defaults={
                "name": item["name"],
                "type": item["type"],
                "is_control": item.get("is_control", False),
                "description": item.get("description", ""),
                "currency": organization.base_currency or "USD",
            },
        )
        accounts[item["code"]] = acc

    for mapping_key, account_code, desc in STANDARD_ACCOUNT_MAPPINGS:
        if account_code in accounts:
            AccountMapping.all_tenants.get_or_create(
                organization=organization,
                mapping_key=mapping_key,
                defaults={
                    "account": accounts[account_code],
                    "description": desc,
                },
            )

    return accounts


@transaction.atomic
def seed_fiscal_calendar(
    *,
    organization: Organization,
    year: int | None = None,
) -> FiscalYear:
    """Seed the current fiscal year and 12 monthly open fiscal periods."""
    target_year = year or timezone.now().year
    start_date = datetime.date(target_year, 1, 1)
    end_date = datetime.date(target_year, 12, 31)

    fy, _ = FiscalYear.all_tenants.get_or_create(
        organization=organization,
        name=f"FY {target_year}",
        defaults={
            "start_date": start_date,
            "end_date": end_date,
            "is_closed": False,
        },
    )

    for month in range(1, 13):
        last_day = calendar.monthrange(target_year, month)[1]
        p_start = datetime.date(target_year, month, 1)
        p_end = datetime.date(target_year, month, last_day)
        p_name = f"{target_year}-{month:02d}"

        FiscalPeriod.all_tenants.get_or_create(
            organization=organization,
            fiscal_year=fy,
            period_number=month,
            defaults={
                "name": p_name,
                "start_date": p_start,
                "end_date": p_end,
                "status": FiscalPeriod.STATUS_OPEN,
            },
        )

    return fy


def provision_accounting(ctx: Any) -> None:
    """Provisioning hook called during tenant organization creation."""
    org = ctx.organization
    seed_chart_of_accounts(organization=org)
    seed_fiscal_calendar(organization=org)
