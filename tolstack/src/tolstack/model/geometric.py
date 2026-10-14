"""Geometric tolerance records (ISO GPS / ASME Y14.5).

Phase 1 stores every geometric tolerance with its full specification for traceability, but propagates
only cylindricity, and only for a diametral clearance/interference of one hole–shaft pair. See
docs/formulation.md §5 for the derivation and limits of that model. Nothing here converts a tolerance
zone into a linear tolerance automatically.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

from .distributions import Distribution

GeometricType = Literal[
    "straightness", "flatness", "circularity", "cylindricity", "parallelism", "perpendicularity",
    "angularity", "position", "circular_runout", "total_runout",
]

FORM_TYPES = {"straightness", "flatness", "circularity", "cylindricity"}
NEEDS_DATUM = {"parallelism", "perpendicularity", "angularity", "circular_runout", "total_runout"}

# Unicode symbols (ISO 1101 / ASME Y14.5) as they appear when a PDF carries them as text.
SYMBOLS = {
    "⏤": "straightness", "⏥": "flatness", "○": "circularity", "⌭": "cylindricity",
    "∥": "parallelism", "⫽": "parallelism", "⟂": "perpendicularity", "⊥": "perpendicularity",
    "∠": "angularity", "⌖": "position", "↗": "circular_runout", "⌰": "total_runout",
}

KEYWORDS = {
    "STRAIGHTNESS": "straightness", "RETILINEIDADE": "straightness",
    "FLATNESS": "flatness", "PLANEZA": "flatness", "PLANICIDADE": "flatness",
    "CIRCULARITY": "circularity", "ROUNDNESS": "circularity", "CIRCULARIDADE": "circularity",
    "CYLINDRICITY": "cylindricity", "CILINDRICIDADE": "cylindricity",
    "PARALLELISM": "parallelism", "PARALELISMO": "parallelism",
    "PERPENDICULARITY": "perpendicularity", "PERPENDICULARIDADE": "perpendicularity",
    "ANGULARITY": "angularity", "ANGULARIDADE": "angularity",
    "POSITION": "position", "POSICAO": "position", "POSIÇÃO": "position",
    "CIRCULAR RUNOUT": "circular_runout", "BATIMENTO CIRCULAR": "circular_runout",
    "TOTAL RUNOUT": "total_runout", "BATIMENTO TOTAL": "total_runout",
}

SizePrinciple = Literal["envelope", "independency"]


class GeometricTolerance(BaseModel):
    model_config = {"extra": "forbid"}
    id: str
    type: GeometricType
    feature_id: str  # controlled feature
    value: float = Field(ge=0)  # tolerance zone size
    unit: str
    diameter_zone: bool = False
    datums: list[str] = Field(default_factory=list)
    material_modifier: Optional[Literal["MMC", "LMC", "RFS"]] = None
    standard: Optional[Literal["ISO_GPS", "ASME_Y14.5"]] = None
    # Size/form relationship of the controlled feature: envelope (ISO Ⓔ / ASME Rule #1) or
    # independency (ISO 8015 default). None = not declared -> Insufficient Information when propagated.
    size_principle: Optional[SizePrinciple] = None
    # Distribution of the form-induced effect for statistical methods; must be declared, never inferred.
    effect_distribution: Optional[Distribution] = None
    source_callout: Optional[str] = None
    notes: str = ""

    def zone_description(self) -> str:
        z = ("Ø" if self.diameter_zone else "") + f"{self.value:g} {self.unit}"
        d = (" | " + " | ".join(self.datums)) if self.datums else ""
        m = f" {self.material_modifier}" if self.material_modifier else ""
        return f"{self.type} {z}{m}{d}"
