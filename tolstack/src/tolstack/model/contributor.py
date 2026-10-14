"""Stack-up contributors and their traceability to source documents."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .distributions import Distribution
from .tolerance import ToleranceSpec

ContributorKind = Literal["dimension", "size", "geometric", "user_declared_equivalent"]


class SourceRef(BaseModel):
    """Where a value came from. For drawing-extracted values the callout id links to the confirmation record."""

    model_config = {"extra": "forbid"}
    document: str = ""  # drawing number or file name
    revision: str = ""
    page: Optional[int] = None
    bbox: Optional[tuple[float, float, float, float]] = None  # x0, top, x1, bottom (PDF points)
    callout_id: Optional[str] = None
    raw_text: str = ""
    entered_by: str = ""


class Contributor(BaseModel):
    """One term of the stack-up equation.

    kind
      dimension                 distance between two features (from_feature -> to_feature)
      size                      size of one feature (diameter/width); from_feature is that feature
      geometric                 effect of a geometric tolerance (geometric_id); bounds derived, not entered
      user_declared_equivalent  engineer-declared linear equivalent of a geometric effect; requires
                                justification and is always reported as an unverified assumption
    direction
      +1 if to_feature lies in the +axis direction from from_feature, -1 otherwise (dimension kind only).
    sensitivity
      Optional declared coefficient. For loop/fit characteristics the sign is derived from topology and a
      declared value is only cross-checked; for user-defined characteristics it is required.
    """

    model_config = {"extra": "forbid"}
    id: str
    name: str = ""
    component: str = ""
    kind: ContributorKind = "dimension"
    from_feature: Optional[str] = None
    to_feature: Optional[str] = None
    direction: Optional[Literal[-1, 1]] = None
    tolerance: Optional[ToleranceSpec] = None
    geometric_id: Optional[str] = None
    sensitivity: Optional[float] = None
    distribution: Optional[Distribution] = None
    justification: str = ""
    source: Optional[SourceRef] = None
    notes: str = ""
    tags: list[str] = Field(default_factory=list)
