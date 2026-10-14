"""Project persistence as versioned JSON."""

from __future__ import annotations

import json
from pathlib import Path

from ..errors import ModelError
from ..model.project import SCHEMA_VERSION, Project


def load_project(path: str | Path) -> Project:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return project_from_dict(data)


def project_from_dict(data: dict) -> Project:
    ver = data.get("schema_version", SCHEMA_VERSION)
    if ver.split(".")[0] != SCHEMA_VERSION.split(".")[0]:
        raise ModelError(f"Project schema {ver} is not compatible with this version ({SCHEMA_VERSION}).")
    return Project.model_validate(data)


def save_project(project: Project, path: str | Path) -> None:
    Path(path).write_text(project_to_json(project), encoding="utf-8")


def project_to_json(project: Project) -> str:
    return json.dumps(project.model_dump(mode="json", exclude_none=True), indent=2, ensure_ascii=False)
