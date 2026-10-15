"""Typed JSON schemas for extraction and QA."""
from __future__ import annotations
from typing import Literal, Optional
from pydantic import BaseModel, Field


class LineItem(BaseModel):
    description: str = ""
    quantity: float = 0
    unit_price: float = 0
    amount: float = 0


class InvoiceExtract(BaseModel):
    doc_type: Literal["invoice"] = "invoice"
    invoice_number: Optional[str] = None
    vendor: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = None
    subtotal: Optional[float] = None
    tax: Optional[float] = None
    total: Optional[float] = None
    po_number: Optional[str] = None
    line_items: list[LineItem] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PolicyExtract(BaseModel):
    doc_type: Literal["policy"] = "policy"
    title: Optional[str] = None
    effective_date: Optional[str] = None
    approval_threshold: Optional[float] = None
    requires_po: Optional[bool] = None
    max_tax_rate: Optional[float] = None
    key_clauses: list[str] = Field(default_factory=list)
    missing_fields: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    doc_id: str
    page: int = 1
    passage: str
    score: float = 0.0


class QAResponse(BaseModel):
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    grounded: bool = False
    refused: bool = False
    latency_ms: int = 0
    model: str = "deterministic-fallback"


class RuleFinding(BaseModel):
    rule: str
    passed: bool
    detail: str


class IngestResponse(BaseModel):
    doc_id: str
    filename: str
    doc_type: str
    pages: int
    chars: int
    ocr_used: bool
    extraction: dict
    rules: list[RuleFinding]
    needs_review: bool
    latency_ms: int
