"""Sample fixtures to generate demo PDFs/TXTs + testset source texts."""
SAMPLE_INVOICE = """ACME Cloud Services Ltd
Vendor: ACME Cloud Services Ltd
Invoice Number: INV-2026-0481
Invoice Date: 2026-09-14
Due Date: 2026-10-14
PO Number: PO-7781
Currency: USD

Compute credits 100 x 12.50 = 1250.00
Support plan 1 x 300.00 = 300.00

Subtotal: $1550.00
Tax (8%): $124.00
Grand Total: $1674.00
"""

SAMPLE_POLICY = """Global Expense Policy
Effective Date: 2026-01-01

All invoices above the approval threshold of $10000.00 require director approval.
A purchase order is required for every invoice (PO is required).
Maximum allowable tax rate is 25%.
Invoices must state invoice number, vendor, date, total and currency.
"""
BAD_INVOICE = """Some random receipt
paid cash, thanks, no details at all, total unknown
"""
