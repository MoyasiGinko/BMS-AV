"""Services for minimal accounting core: double-entry ledger, postings, and reversals."""

from __future__ import annotations

import calendar
import datetime
from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.accounting.events import (
    BankAccountCreated,
    BankReconciliationCompleted,
    ExchangeRateUpdated,
    ExpenseCreated,
    ExpensePosted,
    ExpenseVoided,
    FiscalPeriodClosed,
    JournalEntryPosted,
    JournalEntryReversed,
)
from apps.accounting.exceptions import (
    AccountInactiveError,
    AccountNotFoundError,
    AlreadyReversedError,
    EmptyEntryError,
    ExpenseAlreadyPostedError,
    ExpenseAlreadyVoidError,
    InvalidEntryError,
    InvalidEntryStateError,
    PeriodClosed,
    UnbalancedEntryError,
)
from apps.accounting.models import (
    Account,
    AccountMapping,
    AccountType,
    BankAccount,
    BankReconciliation,
    BankReconciliationStatus,
    BankTransaction,
    BankTransactionType,
    ExchangeRate,
    Expense,
    ExpenseCategory,
    ExpensePaymentMethod,
    ExpenseStatus,
    FiscalPeriod,
    FiscalYear,
    JournalEntry,
    JournalLine,
    TaxPeriodSummary,
    TaxSummaryStatus,
)
from apps.approvals.models import ApprovalRequest, ApprovalRuleType, ApprovalStatus
from apps.approvals.services import evaluate_approval_required, request_approval
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


# =============================================================================
# CHART OF ACCOUNTS & MANUAL JOURNALS
# =============================================================================


@transaction.atomic
def create_account(
    *,
    organization: Organization,
    code: str,
    name: str,
    type: str,
    parent: Account | None = None,
    currency: str = "",
    is_control: bool = False,
    is_active: bool = True,
    description: str = "",
    actor: Any = None,
) -> Account:
    """Create a new Account in the organization's Chart of Accounts."""
    if Account.all_tenants.filter(organization=organization, code=code).exists():
        raise InvalidEntryError(f"Account with code '{code}' already exists.")
    if parent and parent.organization_id != organization.pk:
        raise AccountNotFoundError("Parent account belongs to a different organization.")

    account = Account.objects.create(
        organization=organization,
        code=code,
        name=name,
        type=type,
        parent=parent,
        currency=currency,
        is_control=is_control,
        is_active=is_active,
        description=description,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return account


@transaction.atomic
def update_account(
    *,
    organization: Organization,
    account: Account,
    name: str | None = None,
    parent: Account | None = None,
    is_active: bool | None = None,
    description: str | None = None,
    actor: Any = None,
) -> Account:
    """Update editable properties of an existing chart of accounts entry."""
    target = Account.all_tenants.select_for_update().get(pk=account.pk, organization=organization)
    update_fields = ["updated_at"]
    if name is not None:
        target.name = name
        update_fields.append("name")
    if parent is not None:
        if parent.pk == target.pk:
            raise InvalidEntryError("An account cannot be its own parent.")
        if parent.organization_id != organization.pk:
            raise AccountNotFoundError("Parent account belongs to a different organization.")
        target.parent = parent
        update_fields.append("parent")
    if is_active is not None:
        target.is_active = is_active
        update_fields.append("is_active")
    if description is not None:
        target.description = description
        update_fields.append("description")

    target.save(update_fields=update_fields)
    return target


@transaction.atomic
def create_manual_journal_entry(
    *,
    organization: Organization,
    date: datetime.date,
    memo: str,
    lines: Sequence[JournalLineInput | dict[str, Any]],
    actor: Any = None,
) -> JournalEntry:
    """Post a manual journal entry to the general ledger."""
    return post_entry(
        organization=organization,
        date=date,
        memo=memo,
        lines=lines,
        source_type="manual_journal",
        source_id="",
        actor=actor,
    )


# =============================================================================
# BANK ACCOUNTS & RECONCILIATION
# =============================================================================


@transaction.atomic
def create_bank_account(
    *,
    organization: Organization,
    name: str,
    account_number: str,
    bank_name: str,
    gl_account: Account,
    currency: str = "USD",
    opening_balance: Decimal = DECIMAL_ZERO,
    routing_number: str = "",
    swift_bic: str = "",
    notes: str = "",
    actor: Any = None,
) -> BankAccount:
    """Create a new Bank Account and optionally post its opening balance."""
    if gl_account.organization_id != organization.pk:
        raise AccountNotFoundError("GL account belongs to a different organization.")

    opening_bal = Decimal(str(opening_balance)).quantize(FOUR_PLACES)
    bank_account = BankAccount.objects.create(
        organization=organization,
        name=name,
        account_number=account_number,
        bank_name=bank_name,
        routing_number=routing_number,
        swift_bic=swift_bic,
        currency=currency,
        current_balance=opening_bal,
        gl_account=gl_account,
        is_active=True,
        notes=notes,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    if opening_bal > DECIMAL_ZERO:
        # Create initial deposit transaction and GL posting
        try:
            equity_acct = resolve_account(organization=organization, account_ref="equity")
        except AccountNotFoundError:
            try:
                equity_acct = resolve_account(organization=organization, account_ref="3000")
            except AccountNotFoundError:
                equity_acct = resolve_account(organization=organization, account_ref="retained_earnings")

        entry = post_entry(
            organization=organization,
            date=timezone.now().date(),
            memo=f"Opening balance for {bank_account.name}",
            lines=[
                Dr(gl_account, opening_bal, memo="Opening balance"),
                Cr(equity_acct, opening_bal, memo="Opening equity balance"),
            ],
            source_type="bank_account",
            source_id=str(bank_account.pk),
            actor=actor,
        )
        BankTransaction.objects.create(
            organization=organization,
            bank_account=bank_account,
            date=timezone.now().date(),
            amount=opening_bal,
            transaction_type=BankTransactionType.DEPOSIT,
            reference="OPENING_BAL",
            payee="Opening Balance",
            description=f"Opening balance for {bank_account.name}",
            is_reconciled=True,
            reconciled_at=timezone.now(),
            journal_entry=entry,
            created_by=actor if getattr(actor, "is_authenticated", False) else None,
        )

    publish(
        BankAccountCreated(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            bank_account_id=bank_account.pk,
            name=bank_account.name,
            account_number=bank_account.account_number,
        )
    )
    return bank_account


@transaction.atomic
def record_bank_transaction(
    *,
    organization: Organization,
    bank_account: BankAccount,
    date: datetime.date,
    amount: Decimal | str | float,
    transaction_type: str,
    reference: str = "",
    payee: str = "",
    description: str = "",
    journal_entry: JournalEntry | None = None,
    actor: Any = None,
) -> BankTransaction:
    """Record a deposit or withdrawal against a bank account and adjust its balance."""
    target_ba = BankAccount.all_tenants.select_for_update().get(pk=bank_account.pk, organization=organization)
    tx_amount = Decimal(str(amount)).quantize(FOUR_PLACES)
    if tx_amount <= DECIMAL_ZERO:
        raise InvalidEntryError("Transaction amount must be positive.")

    if transaction_type == BankTransactionType.DEPOSIT:
        target_ba.current_balance += tx_amount
    elif transaction_type == BankTransactionType.WITHDRAWAL:
        target_ba.current_balance -= tx_amount
    else:
        raise InvalidEntryError(f"Invalid transaction type '{transaction_type}'.")

    target_ba.save(update_fields=["current_balance", "updated_at"])

    tx = BankTransaction.objects.create(
        organization=organization,
        bank_account=target_ba,
        date=date,
        amount=tx_amount,
        transaction_type=transaction_type,
        reference=reference,
        payee=payee,
        description=description,
        is_reconciled=False,
        journal_entry=journal_entry,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )
    return tx


@transaction.atomic
def reconcile_bank_statement(
    *,
    organization: Organization,
    bank_account: BankAccount,
    statement_date: datetime.date,
    statement_ending_balance: Decimal | str | float,
    cleared_transaction_ids: list[int],
    actor: Any = None,
) -> BankReconciliation:
    """Reconcile bank statement line items against book transactions."""
    target_ba = BankAccount.all_tenants.select_for_update().get(pk=bank_account.pk, organization=organization)
    ending_bal = Decimal(str(statement_ending_balance)).quantize(FOUR_PLACES)

    txs = list(
        BankTransaction.all_tenants.select_for_update().filter(
            organization=organization,
            bank_account=target_ba,
            pk__in=cleared_transaction_ids,
        )
    )
    now = timezone.now()
    for tx in txs:
        tx.is_reconciled = True
        tx.reconciled_at = now
        tx.save(update_fields=["is_reconciled", "reconciled_at", "updated_at"])

    book_balance = target_ba.current_balance
    difference = (ending_bal - book_balance).quantize(FOUR_PLACES)
    is_balanced = difference == DECIMAL_ZERO

    reconciliation = BankReconciliation.objects.create(
        organization=organization,
        bank_account=target_ba,
        statement_date=statement_date,
        statement_ending_balance=ending_bal,
        book_balance=book_balance,
        reconciled_balance=ending_bal if is_balanced else book_balance,
        difference=difference,
        status=(BankReconciliationStatus.COMPLETED if is_balanced else BankReconciliationStatus.IN_PROGRESS),
        reconciled_at=now if is_balanced else None,
        reconciled_by=actor if getattr(actor, "is_authenticated", False) else None,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    publish(
        BankReconciliationCompleted(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            reconciliation_id=reconciliation.pk,
            bank_account_id=target_ba.pk,
            statement_date=str(statement_date),
            statement_ending_balance=str(ending_bal),
        )
    )
    return reconciliation


# =============================================================================
# EXPENSES & EXPENSE CATEGORIES
# =============================================================================


@transaction.atomic
def create_expense_category(
    *,
    organization: Organization,
    name: str,
    code: str,
    gl_account: Account,
    description: str = "",
    actor: Any = None,
) -> ExpenseCategory:
    """Create an expense category linked to a general ledger expense account."""
    if gl_account.organization_id != organization.pk:
        raise AccountNotFoundError("GL account belongs to a different organization.")

    return ExpenseCategory.objects.create(
        organization=organization,
        name=name,
        code=code.upper(),
        gl_account=gl_account,
        description=description,
        is_active=True,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )


@transaction.atomic
def create_expense(
    *,
    organization: Organization,
    category: ExpenseCategory,
    paid_from_account: Account,
    date: datetime.date,
    amount: Decimal | str | float,
    tax_rate: Decimal | str | float = DECIMAL_ZERO,
    currency: str = "USD",
    exchange_rate: Decimal | str | float = Decimal("1.000000"),
    bank_account: BankAccount | None = None,
    payment_method: str = ExpensePaymentMethod.CASH,
    vendor_name: str = "",
    reference: str = "",
    notes: str = "",
    receipt: Any = None,
    actor: Any = None,
) -> Expense:
    """Create a draft expense record."""
    if category.organization_id != organization.pk:
        raise InvalidEntryError("Expense category belongs to a different organization.")
    if paid_from_account.organization_id != organization.pk:
        raise AccountNotFoundError("Paid from account belongs to a different organization.")
    if bank_account and bank_account.organization_id != organization.pk:
        raise InvalidEntryError("Bank account belongs to a different organization.")

    amt = Decimal(str(amount)).quantize(FOUR_PLACES)
    t_rate = Decimal(str(tax_rate if tax_rate is not None else 0)).quantize(FOUR_PLACES)
    fx = Decimal(str(exchange_rate if exchange_rate is not None else 1)).quantize(SIX_PLACES)
    if amt <= DECIMAL_ZERO:
        raise InvalidEntryError("Expense amount must be positive.")

    tax_amt = (amt * (t_rate / Decimal("100.0000"))).quantize(FOUR_PLACES)
    tot_amt = (amt + tax_amt).quantize(FOUR_PLACES)
    base_amt = (tot_amt * fx).quantize(FOUR_PLACES)

    num = generate_next_number(
        organization_id=organization.pk,
        name="EXPENSE",
        prefix="EXP-",
        padding=5,
    )

    expense = Expense.objects.create(
        organization=organization,
        expense_number=num,
        category=category,
        bank_account=bank_account,
        paid_from_account=paid_from_account,
        date=date,
        amount=amt,
        tax_amount=tax_amt,
        total_amount=tot_amt,
        tax_rate=t_rate,
        currency=currency,
        exchange_rate=fx,
        base_amount=base_amt,
        payment_method=payment_method,
        vendor_name=vendor_name,
        reference=reference,
        notes=notes,
        receipt=receipt,
        status=ExpenseStatus.DRAFT,
        created_by=actor if getattr(actor, "is_authenticated", False) else None,
    )

    publish(
        ExpenseCreated(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            expense_id=expense.pk,
            expense_number=expense.expense_number,
            total_amount=str(expense.total_amount),
            vendor_name=expense.vendor_name,
        )
    )

    rule = evaluate_approval_required(
        organization=organization,
        document_type=ApprovalRuleType.EXPENSE,
        amount=expense.total_amount,
    )
    if rule:
        desc = f"Expense {expense.expense_number} - {expense.vendor_name or expense.category.name}"
        request_approval(
            organization=organization,
            actor=actor,
            document_type=ApprovalRuleType.EXPENSE,
            document_id=expense.pk,
            document_reference=expense.expense_number,
            document_title=f"{desc} (${expense.total_amount})",
            amount=expense.total_amount,
            rule=rule,
        )

    return expense


@transaction.atomic
def post_expense(
    *,
    organization: Organization,
    expense: Expense,
    actor: Any = None,
) -> Expense:
    """Post an expense to the general ledger and adjust cash/bank ledger balance."""
    target_exp = Expense.all_tenants.select_for_update().get(pk=expense.pk, organization=organization)
    if target_exp.status != ExpenseStatus.DRAFT:
        raise ExpenseAlreadyPostedError(f"Expense '{target_exp.expense_number}' is not in draft status.")

    rule = evaluate_approval_required(
        organization=organization,
        document_type=ApprovalRuleType.EXPENSE,
        amount=target_exp.total_amount,
    )
    if rule:
        app_req = ApprovalRequest.all_tenants.filter(
            organization=organization,
            document_type=ApprovalRuleType.EXPENSE,
            document_id=str(target_exp.pk),
        ).first()
        if not app_req or app_req.status != ApprovalStatus.APPROVED:
            raise ValidationError(
                _("Expense %(num)s requires approval before posting to general ledger.")
                % {"num": target_exp.expense_number}
            )

    check_fiscal_period_open(organization=organization, posting_date=target_exp.date)

    memo_str = f"Expense {target_exp.expense_number} - {target_exp.vendor_name or target_exp.category.name}"
    lines: list[JournalLineInput] = [
        Dr(
            account=target_exp.category.gl_account,
            amount=target_exp.amount,
            memo=memo_str,
            currency=target_exp.currency,
            fx_rate=target_exp.exchange_rate,
        )
    ]
    if target_exp.tax_amount > DECIMAL_ZERO:
        lines.append(
            Dr(
                account="tax.input",
                amount=target_exp.tax_amount,
                memo=f"Input tax for expense {target_exp.expense_number}",
                currency=target_exp.currency,
                fx_rate=target_exp.exchange_rate,
            )
        )
    lines.append(
        Cr(
            account=target_exp.paid_from_account,
            amount=target_exp.total_amount,
            memo=f"Payment for expense {target_exp.expense_number}",
            currency=target_exp.currency,
            fx_rate=target_exp.exchange_rate,
        )
    )

    entry = post_entry(
        organization=organization,
        date=target_exp.date,
        memo=f"Expense {target_exp.expense_number} - {target_exp.vendor_name}",
        lines=lines,
        source_type="expense",
        source_id=str(target_exp.pk),
        actor=actor,
    )

    if target_exp.bank_account:
        record_bank_transaction(
            organization=organization,
            bank_account=target_exp.bank_account,
            date=target_exp.date,
            amount=target_exp.total_amount,
            transaction_type=BankTransactionType.WITHDRAWAL,
            reference=target_exp.expense_number,
            payee=target_exp.vendor_name,
            description=target_exp.notes or f"Expense {target_exp.expense_number}",
            journal_entry=entry,
            actor=actor,
        )

    target_exp.status = ExpenseStatus.POSTED
    target_exp.journal_entry = entry
    target_exp.save(update_fields=["status", "journal_entry", "updated_at"])

    publish(
        ExpensePosted(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            expense_id=target_exp.pk,
            expense_number=target_exp.expense_number,
            journal_entry_id=entry.pk,
            total_amount=str(target_exp.total_amount),
        )
    )
    return target_exp


@transaction.atomic
def void_expense(
    *,
    organization: Organization,
    expense: Expense,
    actor: Any = None,
) -> Expense:
    """Void an expense and reverse its general ledger entry."""
    target_exp = Expense.all_tenants.select_for_update().get(pk=expense.pk, organization=organization)
    if target_exp.status == ExpenseStatus.VOID:
        raise ExpenseAlreadyVoidError(f"Expense '{target_exp.expense_number}' is already void.")

    if target_exp.status == ExpenseStatus.POSTED and target_exp.journal_entry:
        reverse_entry(
            organization=organization,
            entry=target_exp.journal_entry,
            date=timezone.now().date(),
            reason=f"Voided expense {target_exp.expense_number}",
            actor=actor,
        )

        if target_exp.bank_account:
            record_bank_transaction(
                organization=organization,
                bank_account=target_exp.bank_account,
                date=timezone.now().date(),
                amount=target_exp.total_amount,
                transaction_type=BankTransactionType.DEPOSIT,
                reference=f"VOID-{target_exp.expense_number}",
                payee=target_exp.vendor_name,
                description=f"Void reversal for {target_exp.expense_number}",
                actor=actor,
            )

    target_exp.status = ExpenseStatus.VOID
    target_exp.save(update_fields=["status", "updated_at"])

    publish(
        ExpenseVoided(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            expense_id=target_exp.pk,
            expense_number=target_exp.expense_number,
        )
    )
    return target_exp


# =============================================================================
# MULTI-CURRENCY & EXCHANGE RATES
# =============================================================================


@transaction.atomic
def record_exchange_rate(
    *,
    organization: Organization,
    from_currency: str,
    to_currency: str,
    rate: Decimal | str | float,
    effective_date: datetime.date,
    source: str = "manual",
    actor: Any = None,
) -> ExchangeRate:
    """Record a foreign exchange rate between two currency codes."""
    from_c = from_currency.upper().strip()
    to_c = to_currency.upper().strip()
    rate_val = Decimal(str(rate)).quantize(SIX_PLACES)
    if rate_val <= DECIMAL_ZERO:
        raise InvalidEntryError("Exchange rate must be positive.")

    rate_obj, _created = ExchangeRate.objects.update_or_create(
        organization=organization,
        from_currency=from_c,
        to_currency=to_c,
        effective_date=effective_date,
        defaults={
            "rate": rate_val,
            "source": source,
            "created_by": actor if getattr(actor, "is_authenticated", False) else None,
        },
    )

    publish(
        ExchangeRateUpdated(
            organization_id=organization.pk,
            actor_id=getattr(actor, "pk", None),
            rate_id=rate_obj.pk,
            from_currency=from_c,
            to_currency=to_c,
            rate=str(rate_val),
            effective_date=str(effective_date),
        )
    )
    return rate_obj


def get_exchange_rate(
    *,
    organization: Organization | None = None,
    organization_id: int | None = None,
    from_currency: str,
    to_currency: str,
    effective_date: datetime.date | None = None,
    as_of_date: datetime.date | None = None,
) -> Decimal:
    """Retrieve the exchange rate for a currency pair on or before effective date."""
    from_c = from_currency.upper().strip()
    to_c = to_currency.upper().strip()
    if from_c == to_c:
        return Decimal("1.000000")

    date_filter = effective_date or as_of_date

    filter_kwargs: dict[str, Any] = {"from_currency": from_c, "to_currency": to_c}
    if organization is not None:
        filter_kwargs["organization"] = organization
    elif organization_id is not None:
        filter_kwargs["organization_id"] = organization_id

    query = ExchangeRate.all_tenants.filter(**filter_kwargs)
    if date_filter:
        query = query.filter(effective_date__lte=date_filter)

    latest = query.order_by("-effective_date").first()
    if latest:
        return latest.rate

    inv_kwargs: dict[str, Any] = {"from_currency": to_c, "to_currency": from_c}
    if organization is not None:
        inv_kwargs["organization"] = organization
    elif organization_id is not None:
        inv_kwargs["organization_id"] = organization_id

    inv_query = ExchangeRate.all_tenants.filter(**inv_kwargs)
    if date_filter:
        inv_query = inv_query.filter(effective_date__lte=date_filter)
    inv_latest = inv_query.order_by("-effective_date").first()
    if inv_latest and inv_latest.rate > DECIMAL_ZERO:
        return (Decimal("1.000000") / inv_latest.rate).quantize(SIX_PLACES)

    return Decimal("1.000000")


# =============================================================================
# TAX SUMMARY & FILING
# =============================================================================


@transaction.atomic
def calculate_tax_period_summary(
    *,
    organization: Organization,
    period_start: datetime.date,
    period_end: datetime.date,
    save: bool = False,
    notes: str = "",
    actor: Any = None,
) -> TaxPeriodSummary:
    """Calculate input and output VAT/sales tax totals across posted transactions."""
    output_tax_acct = resolve_account(organization=organization, account_ref="tax.output")
    input_tax_acct = resolve_account(organization=organization, account_ref="tax.input")

    output_lines = JournalLine.all_tenants.filter(
        organization=organization,
        account=output_tax_acct,
        entry__date__gte=period_start,
        entry__date__lte=period_end,
        entry__status=JournalEntry.STATUS_POSTED,
    )
    tot_output = output_lines.aggregate(cr=models.Sum("credit"), dr=models.Sum("debit"))
    output_tax = ((tot_output["cr"] or DECIMAL_ZERO) - (tot_output["dr"] or DECIMAL_ZERO)).quantize(
        FOUR_PLACES
    )

    input_lines = JournalLine.all_tenants.filter(
        organization=organization,
        account=input_tax_acct,
        entry__date__gte=period_start,
        entry__date__lte=period_end,
        entry__status=JournalEntry.STATUS_POSTED,
    )
    tot_input = input_lines.aggregate(dr=models.Sum("debit"), cr=models.Sum("credit"))
    input_tax = ((tot_input["dr"] or DECIMAL_ZERO) - (tot_input["cr"] or DECIMAL_ZERO)).quantize(FOUR_PLACES)

    net_tax_payable = (output_tax - input_tax).quantize(FOUR_PLACES)

    sales_lines = JournalLine.all_tenants.filter(
        organization=organization,
        account__type=AccountType.REVENUE,
        entry__date__gte=period_start,
        entry__date__lte=period_end,
        entry__status=JournalEntry.STATUS_POSTED,
    )
    taxable_sales = sales_lines.aggregate(cr=models.Sum("credit"), dr=models.Sum("debit"))
    tot_sales = ((taxable_sales["cr"] or DECIMAL_ZERO) - (taxable_sales["dr"] or DECIMAL_ZERO)).quantize(
        FOUR_PLACES
    )

    purchases_lines = JournalLine.all_tenants.filter(
        organization=organization,
        account__type=AccountType.EXPENSE,
        entry__date__gte=period_start,
        entry__date__lte=period_end,
        entry__status=JournalEntry.STATUS_POSTED,
    )
    taxable_purchases = purchases_lines.aggregate(dr=models.Sum("debit"), cr=models.Sum("credit"))
    tot_purchases = (
        (taxable_purchases["dr"] or DECIMAL_ZERO) - (taxable_purchases["cr"] or DECIMAL_ZERO)
    ).quantize(FOUR_PLACES)

    if save:
        summary, _created = TaxPeriodSummary.objects.update_or_create(
            organization=organization,
            period_start=period_start,
            period_end=period_end,
            defaults={
                "taxable_sales": tot_sales,
                "output_tax": output_tax,
                "taxable_purchases": tot_purchases,
                "input_tax": input_tax,
                "net_tax_payable": net_tax_payable,
                "notes": notes,
                "created_by": actor if getattr(actor, "is_authenticated", False) else None,
            },
        )
        return summary

    return TaxPeriodSummary(
        organization=organization,
        period_start=period_start,
        period_end=period_end,
        taxable_sales=tot_sales,
        output_tax=output_tax,
        taxable_purchases=tot_purchases,
        input_tax=input_tax,
        net_tax_payable=net_tax_payable,
        status=TaxSummaryStatus.DRAFT,
        notes=notes,
    )


@transaction.atomic
def file_tax_period_summary(
    *,
    organization: Organization,
    summary: TaxPeriodSummary,
    actor: Any = None,
) -> TaxPeriodSummary:
    """Mark a tax period summary as officially filed."""
    target = TaxPeriodSummary.all_tenants.select_for_update().get(pk=summary.pk, organization=organization)
    target.status = TaxSummaryStatus.FILED
    target.filed_at = timezone.now()
    target.filed_by = actor if getattr(actor, "is_authenticated", False) else None
    target.save(update_fields=["status", "filed_at", "filed_by", "updated_at"])
    return target


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
    ("equity", "3000", "Default owner's equity capital account"),
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
