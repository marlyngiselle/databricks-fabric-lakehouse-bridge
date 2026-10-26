from __future__ import annotations

import copy
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from dctl.model import Contract
from dctl.validate import validate_document

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
GENERATED = ROOT / "generated"


def repo_doc(name: str) -> dict[str, Any]:
    with (CONTRACTS / f"{name}.yaml").open(encoding="utf-8") as handle:
        data: dict[str, Any] = yaml.safe_load(handle)
    return copy.deepcopy(data)


def build(doc: dict[str, Any]) -> Contract:
    contract, findings = validate_document(doc)
    assert contract is not None, [str(f) for f in findings]
    return contract


def column(doc: dict[str, Any], name: str) -> dict[str, Any]:
    found: dict[str, Any] = next(c for c in doc["columns"] if c["name"] == name)
    return found


@pytest.fixture
def kpis_doc() -> dict[str, Any]:
    return repo_doc("asset_daily_kpis")


@pytest.fixture
def energy_doc() -> dict[str, Any]:
    return repo_doc("energy_consumption")


@pytest.fixture
def quality_doc() -> dict[str, Any]:
    return repo_doc("quality_events")


@pytest.fixture
def write_yaml(tmp_path: Path) -> Callable[[str, dict[str, Any]], Path]:
    def _write(name: str, doc: dict[str, Any]) -> Path:
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        return path

    return _write
