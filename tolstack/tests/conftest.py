import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = ROOT / "examples"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, EXAMPLES / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def demos():
    return _load("build_demo_projects")


@pytest.fixture
def axial_project(demos):
    return demos.axial_demo()


@pytest.fixture
def fit_project(demos):
    return demos.fit_demo()


@pytest.fixture(scope="session")
def drawings(tmp_path_factory):
    """Generate the demo PDFs into a temp dir; returns (dir, ground_truth dict)."""
    mod = _load("make_demo_drawings")
    out = tmp_path_factory.mktemp("drawings")
    truth = {}
    for name, fn in (("TS-100_housing.pdf", mod.housing), ("TS-110_spacer.pdf", mod.spacer),
                     ("TS-120_shaft.pdf", mod.shaft)):
        callouts, tb = fn(out / name)
        truth[name] = {"callouts": callouts, "title_block": tb}
    mod.no_text(out / "outlined_text.pdf")
    return out, truth
