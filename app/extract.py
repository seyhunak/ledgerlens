"""Deterministic regex extraction + required-field checks."""
from __future__ import annotations
import re
from app.schemas import InvoiceExtract, LineItem, PolicyExtract

REQUIRED_INVOICE_FIELDS = ["invoice_number", "vendor", "invoice_date", "total", "currency"]

MONEY = r"(\$|USD|EUR|GBP|€|£)?\s*([\d,]+\.\d{2})"


def _money_near(text: str, keywords: list[str]) -> float | None:
    for kw in keywords:
        m = re.search(r"\b" + kw + r"\b[\s\S]{0,40}?" + MONEY, text, re.IGNORECASE)
        if m:
            try:
                return float(m.group(2).replace(",", ""))
            except Exception:
                pass
    return None


def _field(pattern: str, text: str) -> str | None:
    m = re.search(pattern, text, re.IGNORECASE | re.MULTILINE)
    return m.group(1).strip() if m else None


def extract_invoice(text: str) -> InvoiceExtract:
    inv_no = _field(r"invoice\s*(?:no|number|#|id)\s*[:\-]?\s*([A-Za-z0-9\-\/]+)", text)
    vendor = _field(r"(?:vendor|seller|from|billed by)\s*[:\-]?\s*([A-Za-z0-9 .,&'\-]+)", text)
    if not vendor:
        # fallback: first non-empty line that looks like a company
        for line in text.splitlines()[:8]:
            s = line.strip()
            if len(s) > 3 and not re.search(r"invoice|total|date|page", s, re.I):
                vendor = s[:80]
                break
    inv_date = _field(r"invoice\s*date\s*[:\-]?\s*(\d{4}-\d{2}-\d{2}|\d{2}[\/\-]\d{2}[\/\-]\d{4})", text)
    due_date = _field(r"due\s*date\s*[:\-]?\s*(\d{4}-\d{2}-\d{2}|\d{2}[\/\-]\d{2}[\/\-]\d{4})", text)
    po = _field(r"\b(?:PO|purchase order)\b\s*(?:no|number|#)?\s*[:\-]?\s*([A-Za-z0-9\-\/]+)", text)
    curr_m = re.search(r"\b(USD|EUR|GBP|TRY|AUD)\b|\$|€|£", text)
    currency = None
    if curr_m:
        raw = curr_m.group(0)
        currency = {"$": "USD", "€": "EUR", "£": "GBP"}.get(raw, raw)
    subtotal = _money_near(text, ["subtotal", "sub-total", "net amount"])
    tax = _money_near(text, ["tax", "VAT", "GST"])
    total = _money_near(text, ["total due", "grand total", "amount due", "total"])
    line_items: list[LineItem] = []
    for m in re.finditer(
        r"^(.{3,60}?)\s+(\d+(?:\.\d+)?)\s*[x×]\s*([\d,]+\.\d{2})\s*=?\s*([\d,]+\.\d{2})",
        text, re.MULTILINE,
    ):
        try:
            line_items.append(LineItem(
                description=m.group(1).strip(),
                quantity=float(m.group(2)),
                unit_price=float(m.group(3).replace(",", "")),
                amount=float(m.group(4).replace(",", "")),
            ))
        except ValueError:
            continue
    inv = InvoiceExtract(
        invoice_number=inv_no, vendor=vendor, invoice_date=inv_date,
        due_date=due_date, currency=currency, subtotal=subtotal,
        tax=tax, total=total, po_number=po, line_items=line_items,
    )
    missing = [f for f in REQUIRED_INVOICE_FIELDS if not getattr(inv, f)]
    inv.missing_fields = missing
    return inv


def extract_policy(text: str) -> PolicyExtract:
    title = None
    for line in text.splitlines()[:5]:
        if line.strip():
            title = line.strip()[:120]
            break
    eff = _field(r"effective\s*(?:date)?\s*[:\-]?\s*(\d{4}-\d{2}-\d{2}|\d{2}[\/\-]\d{2}[\/\-]\d{4})", text)
    thr = _money_near(text, ["approval threshold", "approval required above", "requires approval above"])
    requires_po = None
    if re.search(r"purchase order required|PO is required|PO mandatory", text, re.I):
        requires_po = True
    elif re.search(r"no purchase order|PO not required|PO optional", text, re.I):
        requires_po = False
    tax_m = re.search(r"max\w* tax[^\d]{0,20}(\d+(?:\.\d+)?)\s*%", text, re.I)
    max_tax = float(tax_m.group(1)) / 100 if tax_m else None
    clauses = [s.strip()[:300] for s in re.split(r"\n", text) if len(s.strip()) > 40][:10]
    missing = [k for k, v in {"title": title, "effective_date": eff}.items() if not v]
    return PolicyExtract(title=title, effective_date=eff, approval_threshold=thr,
                         requires_po=requires_po, max_tax_rate=max_tax,
                         key_clauses=clauses, missing_fields=missing)


def classify(text: str) -> str:
    t = text.lower()
    invoice_hits = sum(1 for k in ["invoice", "invoice number", "total due", "line item", "po number"] if k in t)
    policy_hits = sum(1 for k in ["policy", "approval threshold", "expense policy", "effective date", "clause"] if k in t)
    return "policy" if policy_hits > invoice_hits else "invoice"
