"""Records of drawing extraction and of the engineer's confirmation of each extracted value.

Extracted values are proposals. A value enters a calculation only through a ``Confirmation`` with
decision ``confirmed``; edits keep the original interpretation so the report can show both.
"""

from __future__ import annotations

import datetime as _dt
from typing import Literal, Optional

from pydantic import BaseModel, Field

CalloutStatus = Literal["parsed", "ambiguous", "unparsed", "unsupported"]
CalloutCategory = Literal["dimension", "geometric", "note"]


class ParsedCallout(BaseModel):
    model_config = {"extra": "forbid"}
    kind: Literal["linear", "diameter", "radius", "angle", "geometric"]
    count: int = 1
    nominal: Optional[float] = None
    upper: Optional[float] = None
    lower: Optional[float] = None
    unit: Optional[str] = None  # None = not declared on the drawing
    tolerance_origin: Optional[str] = None  # bilateral, deviations, limits, iso286, basic, general, none
    designation: str = ""  # as written, e.g. "H7", "±0.1"
    fit: Optional[tuple[str, str]] = None  # ("H7", "g6") for a fit callout
    basic: bool = False
    envelope: bool = False
    # geometric
    geometric_type: Optional[str] = None
    geometric_value: Optional[float] = None
    diameter_zone: bool = False
    datums: list[str] = Field(default_factory=list)
    material_modifier: Optional[str] = None


class ExtractedCallout(BaseModel):
    model_config = {"extra": "forbid"}
    id: str
    page: int
    bbox: tuple[float, float, float, float]  # x0, top, x1, bottom in PDF points (top-left origin)
    raw_text: str
    category: CalloutCategory = "dimension"
    status: CalloutStatus
    parsed: Optional[ParsedCallout] = None
    issues: list[str] = Field(default_factory=list)


class Confirmation(BaseModel):
    model_config = {"extra": "forbid"}
    callout_id: str
    decision: Literal["confirmed", "rejected"]
    values: Optional[ParsedCallout] = None  # confirmed (possibly edited) interpretation
    edited: bool = False
    original: Optional[ParsedCallout] = None
    reviewer: str
    timestamp: str = Field(default_factory=lambda: _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"))
    comment: str = ""


class TitleBlockCandidate(BaseModel):
    model_config = {"extra": "forbid"}
    field: Literal["drawing_number", "revision", "unit", "general_tolerance", "standard", "size_principle"]
    value: str
    raw_text: str
    page: int
    bbox: tuple[float, float, float, float]
    confirmed: bool = False


class DrawingRecord(BaseModel):
    model_config = {"extra": "forbid"}
    id: str
    file_name: str
    sha256: str
    pages: int
    text_available: bool
    extractor_version: str
    extracted_at: str
    title_block: list[TitleBlockCandidate] = Field(default_factory=list)
    callouts: list[ExtractedCallout] = Field(default_factory=list)
    confirmations: list[Confirmation] = Field(default_factory=list)
    messages: list[str] = Field(default_factory=list)

    def confirmed_title(self, field: str) -> Optional[str]:
        for c in self.title_block:
            if c.field == field and c.confirmed:
                return c.value
        return None

    def confirmation_for(self, callout_id: str) -> Optional[Confirmation]:
        found = [c for c in self.confirmations if c.callout_id == callout_id]
        return found[-1] if found else None

    def callout(self, callout_id: str) -> ExtractedCallout:
        for c in self.callouts:
            if c.id == callout_id:
                return c
        raise KeyError(callout_id)
