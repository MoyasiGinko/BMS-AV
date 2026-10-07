---
name: ledger-posting
description: Implement any business document that moves money or stock (sale, purchase, return, payment, expense, payroll, adjustment) with atomic stock, journal, balance and event effects.
---
# Ledger-posting recipe

```python
@transaction.atomic
def confirm_sale(*, sale_id: int, actor: User) -> Sale:
    sale = Sale.objects.select_for_update().get(pk=sale_id)          # lock the document
    require(actor, "sales.confirm", scope=sale.branch)               # role + scope
    sale.assert_transition("confirmed")                              # state machine
    movements = inventory_services.issue_stock(                      # stock ledger (+ cost)
        lines=[(l.product_id, sale.warehouse_id, l.quantity) for l in sale.lines.all()],
        reference=sale, actor=actor)
    invoice = invoicing.create_invoice_for(sale)                     # document numbers via NumberSequence (locked)
    accounting_services.post_entry(                                  # balanced journal, period-open check
        organization=sale.organization, date=invoice.date, source=invoice,
        lines=[Dr("ar", total), Cr("sales.revenue", net), Cr("tax.output", tax),
               Dr("cogs", cost), Cr("inventory.asset", cost)])
    customers_services.apply_charge(customer=sale.customer, amount=total, source=invoice)
    sale.mark("confirmed"); sale.save(update_fields=["status", "updated_at"])
    events.publish(SaleConfirmed(sale_id=sale.pk, organization_id=sale.organization_id))
    return sale
```

Checklist
- Numbering: gapless per-org sequences (`NumberSequence` row locked with `select_for_update`).
- Never mutate posted rows; `reverse_*` services create reversing entries/movements and credit notes.
- Idempotent against double submission (state machine guard + optional idempotency key).
- Tests: happy path; insufficient stock; closed period; unbalanced entry rejected; double confirm rejected; rollback leaves no partial
  stock/journal/balance rows; hypothesis invariant (debits==credits; stock==ledger; subledgers==control accounts).
