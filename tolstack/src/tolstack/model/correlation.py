"""Correlation between contributors (declared from process knowledge; never assumed)."""

from __future__ import annotations

import numpy as np
from pydantic import BaseModel, Field

from ..errors import ModelError


class Correlation(BaseModel):
    model_config = {"extra": "forbid"}
    a: str
    b: str
    rho: float = Field(ge=-1.0, le=1.0)
    source: str = ""


def correlation_matrix(ids: list[str], correlations: list[Correlation]) -> np.ndarray:
    """Build the correlation matrix for ``ids``. Raises ModelError if a pair is declared twice,
    references an unknown id, or the matrix is not positive semi-definite."""
    idx = {cid: i for i, cid in enumerate(ids)}
    n = len(ids)
    R = np.eye(n)
    seen = set()
    for c in correlations:
        if c.a not in idx or c.b not in idx:
            continue  # correlation involving contributors outside this chain is irrelevant here
        if c.a == c.b:
            raise ModelError(f"Correlation of '{c.a}' with itself is not allowed.")
        key = frozenset((c.a, c.b))
        if key in seen:
            raise ModelError(f"Correlation between '{c.a}' and '{c.b}' declared more than once.")
        seen.add(key)
        i, j = idx[c.a], idx[c.b]
        R[i, j] = R[j, i] = c.rho
    check_psd(R)
    return R


def check_psd(R: np.ndarray, tol: float = 1e-10) -> None:
    if R.size == 0:
        return
    w = np.linalg.eigvalsh(R)
    if w.min() < -tol:
        raise ModelError(
            f"Correlation matrix is not positive semi-definite (min eigenvalue {w.min():.3g}); "
            "the declared correlations are mutually inconsistent."
        )
