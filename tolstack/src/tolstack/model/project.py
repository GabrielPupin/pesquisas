"""Project: the complete, serialisable engineering model."""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
from typing import Literal, Optional

from pydantic import BaseModel, Field, model_validator

from ..drawing.review import DrawingRecord
from ..errors import ModelError
from .characteristic import FunctionalCharacteristic
from .contributor import Contributor
from .correlation import Correlation
from .distributions import StatisticalAssumption
from .geometric import GeometricTolerance

SCHEMA_VERSION = "1.0"


class Component(BaseModel):
    model_config = {"extra": "forbid"}
    id: str
    name: str = ""
    part_number: str = ""
    drawing: str = ""
    revision: str = ""


class Feature(BaseModel):
    model_config = {"extra": "forbid"}
    id: str
    component: str
    name: str = ""
    kind: Literal["plane", "cylinder", "axis", "point", "other"] = "plane"
    role: Literal["hole", "shaft", "none"] = "none"  # internal/external feature of size


class Contact(BaseModel):
    """Assembly interface: two features assumed coincident along the stack axis (zero-length link)."""

    model_config = {"extra": "forbid"}
    id: str
    feature_a: str
    feature_b: str
    assumption: str = ""  # why contact is maintained (preload, gravity, assembly procedure ...)


class Approval(BaseModel):
    model_config = {"extra": "forbid"}
    state: Literal["pending", "approved", "rejected"] = "pending"
    reviewer: str = ""
    timestamp: str = ""
    comment: str = ""
    status_at_review: str = ""
    diagnostics_snapshot: list[dict] = Field(default_factory=list)


class Chain(BaseModel):
    """A candidate stack-up path: ordered contributor ids from the start to the end boundary."""

    model_config = {"extra": "forbid"}
    id: str
    name: str = ""
    contributor_ids: list[str]
    rationale: str = ""  # engineering reasoning for this path
    approval: Approval = Field(default_factory=Approval)


class AnalysisSettings(BaseModel):
    model_config = {"extra": "forbid"}
    mc_samples: int = Field(default=200_000, ge=1_000, le=20_000_000)
    seed: int = 12345
    rss_k: float = Field(default=3.0, gt=0)  # report mean ± k·σ
    percentiles: list[float] = Field(default_factory=lambda: [0.135, 1, 5, 50, 95, 99, 99.865])
    confidence: float = Field(default=0.95, gt=0.5, lt=1.0)


class Project(BaseModel):
    model_config = {"extra": "forbid"}
    schema_version: str = SCHEMA_VERSION
    project_id: str
    name: str
    revision: str = "A"
    author: str = ""
    description: str = ""
    base_unit: str = "mm"
    standard: Optional[Literal["ISO_GPS", "ASME_Y14.5"]] = None
    components: list[Component] = Field(default_factory=list)
    features: list[Feature] = Field(default_factory=list)
    contacts: list[Contact] = Field(default_factory=list)
    contributors: list[Contributor] = Field(default_factory=list)
    geometric_tolerances: list[GeometricTolerance] = Field(default_factory=list)
    characteristic: Optional[FunctionalCharacteristic] = None
    chains: list[Chain] = Field(default_factory=list)
    correlations: list[Correlation] = Field(default_factory=list)
    statistical_assumption: StatisticalAssumption = Field(default_factory=StatisticalAssumption)
    settings: AnalysisSettings = Field(default_factory=AnalysisSettings)
    drawings: list[DrawingRecord] = Field(default_factory=list)
    history: list[dict] = Field(default_factory=list)

    @model_validator(mode="after")
    def _unique_ids(self):
        for label, items in (("component", self.components), ("feature", self.features),
                             ("contact", self.contacts), ("contributor", self.contributors),
                             ("geometric tolerance", self.geometric_tolerances), ("chain", self.chains),
                             ("drawing", self.drawings)):
            ids = [i.id for i in items]
            dup = {i for i in ids if ids.count(i) > 1}
            if dup:
                raise ModelError(f"Duplicate {label} id(s): {sorted(dup)}")
        return self

    # Lookups ---------------------------------------------------------------------------------
    def contributor(self, cid: str) -> Contributor:
        for c in self.contributors:
            if c.id == cid:
                return c
        raise ModelError(f"Unknown contributor '{cid}'.")

    def feature(self, fid: str) -> Optional[Feature]:
        return next((f for f in self.features if f.id == fid), None)

    def geometric(self, gid: str) -> Optional[GeometricTolerance]:
        return next((g for g in self.geometric_tolerances if g.id == gid), None)

    def chain(self, chain_id: Optional[str] = None) -> Chain:
        if not self.chains:
            raise ModelError("Project has no stack-up chain.")
        if chain_id is None:
            if len(self.chains) > 1:
                raise ModelError("Project has several chains; select one explicitly.")
            return self.chains[0]
        for ch in self.chains:
            if ch.id == chain_id:
                return ch
        raise ModelError(f"Unknown chain '{chain_id}'.")

    def drawing(self, did: str) -> DrawingRecord:
        for d in self.drawings:
            if d.id == did:
                return d
        raise ModelError(f"Unknown drawing '{did}'.")

    def fingerprint(self) -> str:
        """SHA-256 of the model content (excluding history) — printed on every result and report."""
        data = self.model_dump(mode="json", exclude={"history"})
        blob = json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
        return hashlib.sha256(blob).hexdigest()

    def log(self, action: str, **details) -> None:
        self.history.append({
            "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "action": action, **details,
        })
