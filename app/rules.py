"""Deterministic business rules. No model involved."""
from __future__ import annotations
from app.schemas import InvoiceExtract, RuleFinding


def run_rules(inv: InvoiceExtract, policy_threshold: float = 10000.0,
              policy_requires_po: bool = True, max_tax_rate: float = 0.25) -> list[RuleFinding]:
    findings: list[RuleFinding] = []
    if inv.subtotal is not None and inv.tax is not None and inv.total is not None:
        expected = round(inv.subtotal + inv.tax, 2)
        ok = abs(expected - inv.total) < 0.02
        findings.append(RuleFinding(rule="totals_match", passed=ok,
            detail=f"subtotal {inv.subtotal} + tax {inv.tax} = {expected}, stated total {inv.total}"))
    else:
        findings.append(RuleFinding(rule="totals_match", passed=False,
            detail="Cannot verify: subtotal/tax/total incomplete"))
    if inv.subtotal and inv.tax is not None and inv.subtotal:
        rate = inv.tax / inv.subtotal
        findings.append(RuleFinding(rule="tax_rate_plausible", passed=0 <= rate <= max_tax_rate,
            detail=f"tax rate {rate:.2%} vs allowed max {max_tax_rate:.0%}"))
    if inv.total is not None:
        findings.append(RuleFinding(rule="approval_threshold", passed=inv.total <= policy_threshold,
            detail=f"total {inv.total} vs approval threshold {policy_threshold}"))
    else:
        findings.append(RuleFinding(rule="approval_threshold", passed=False, detail="total missing"))
    if policy_requires_po:
        findings.append(RuleFinding(rule="po_present", passed=bool(inv.po_number),
            detail=f"PO {'present: ' + inv.po_number if inv.po_number else 'missing (required by policy)'}"))
    if not inv.missing_fields:
        findings.append(RuleFinding(rule="required_fields", passed=True, detail="all required fields present"))
    else:
        findings.append(RuleFinding(rule="required_fields", passed=False,
            detail="missing: " + ", ".join(inv.missing_fields)))
    return findings
