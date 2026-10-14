"""Functional characteristic: the output the stack-up is meant to control."""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

CharacteristicType = Literal[
    # 1D loop characteristics: y = pos(end_feature) - pos(start_feature) along the stack axis
    "axial_clearance", "axial_gap", "axial_stack_height",
    # 1D fit characteristics of one hole–shaft pair (start_feature = hole, end_feature = shaft)
    "diametral_clearance", "diametral_interference",
    # scalar defined by the engineer with declared sensitivities
    "user_defined_scalar",
    # recognised but not supported in Phase 1 (need 2D/3D models)
    "radial_alignment", "angular_misalignment", "position_deviation", "hole_pattern_fit",
]

LOOP_TYPES = {"axial_clearance", "axial_gap", "axial_stack_height"}
FIT_TYPES = {"diametral_clearance", "diametral_interference"}
UNSUPPORTED_TYPES = {"radial_alignment", "angular_misalignment", "position_deviation", "hole_pattern_fit"}


class FunctionalCharacteristic(BaseModel):
    model_config = {"extra": "forbid"}
    id: str
    name: str
    type: CharacteristicType
    start_feature: Optional[str] = None
    end_feature: Optional[str] = None
    unit: str = "mm"
    lsl: Optional[float] = None  # lower specification (allowable minimum)
    usl: Optional[float] = None  # upper specification (allowable maximum)
    nominal_declared: Optional[float] = None
    axis: str = "+X"  # stack axis / coordinate system description
    configuration: str = ""  # assembly configuration (e.g. "shaft pushed to the left by preload spring")
    output_kind: Literal["scalar"] = "scalar"
    description: str = ""
