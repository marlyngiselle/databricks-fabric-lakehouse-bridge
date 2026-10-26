from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from conftest import build, column, repo_doc
from dctl.diff import BREAKING, COMPATIBLE, diff, is_widening
from dctl.model import DataType

Mutation = Callable[[dict[str, Any]], object]


def changes_after(doc: dict[str, Any], mutate: Mutation, version: str) -> tuple[list[str], list[str]]:
    old = build(doc)
    mutate(doc)
    doc["version"] = version
    report = diff(old, build(doc))
    return [f"{c.kind} {c.path} {c.message}" for c in report.changes], report.gate_errors()


def drop_column(name: str) -> Mutation:
    return lambda d: d.update(columns=[c for c in d["columns"] if c["name"] != name])


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (drop_column("performance"), "breaking columns/performance removed"),
        (lambda d: column(d, "kpi_date").update(type="string"), "breaking columns/kpi_date type date to string"),
        (lambda d: column(d, "units_produced").update(type="int"), "breaking columns/units_produced type"),
        (lambda d: column(d, "oee").update(nullable=True), "breaking columns/oee now nullable"),
        (lambda d: column(d, "oee").update(classification="confidential"), "breaking columns/oee classification"),
        (
            lambda d: column(d, "oee").update(classification="confidential", pii=True),
            "breaking columns/oee now flagged",
        ),
        (lambda d: column(d, "oee")["checks"].update(max=1.2), "breaking columns/oee max 1 to 1.2"),
        (lambda d: column(d, "oee")["checks"].pop("min"), "breaking columns/oee min 0 to None"),
        (lambda d: column(d, "asset_id")["checks"].update(pattern="^A[0-9]+$"), "breaking columns/asset_id pattern"),
        (lambda d: d["table"].update(primary_key=["asset_id"]), "breaking table/primary_key"),
        (lambda d: d["table"].update(schema="plant"), "breaking table moved"),
        (lambda d: d["sla"]["freshness"].update(max_delay_hours=48), "breaking sla/freshness loosened"),
        (lambda d: d["sla"].update(availability_percent=99.0), "breaking sla service levels changed"),
        (lambda d: d["consumers"].update(fabric={"exposure": "none"}), "breaking consumers/fabric/exposure"),
        (lambda d: d["consumers"]["fabric"]["measures"].pop(0), "breaking consumers/fabric/measures/Average OEE"),
    ],
    ids=[
        "column-removed",
        "type-changed",
        "type-narrowed",
        "now-nullable",
        "classification-raised",
        "now-pii",
        "range-widened",
        "min-dropped",
        "pattern-changed",
        "key-changed",
        "table-moved",
        "freshness-loosened",
        "availability-lowered",
        "withdrawn-from-fabric",
        "measure-removed",
    ],
)
def test_breaking_changes_need_a_major_version(kpis_doc: dict[str, Any], mutate: Mutation, expected: str) -> None:
    changes, errors = changes_after(kpis_doc, mutate, "1.3.0")
    assert any(c.startswith(expected) for c in changes), changes
    assert any("need a new major version, 1.2.0 to 2.0.0" in e for e in errors)


def test_breaking_change_with_major_bump_passes(kpis_doc: dict[str, Any]) -> None:
    changes, errors = changes_after(kpis_doc, drop_column("performance"), "2.0.0")
    assert changes[0].startswith(BREAKING)
    assert errors == []


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (
            lambda d: d["columns"].append(
                {
                    "name": "shift_count",
                    "type": "int",
                    "nullable": True,
                    "description": "Shifts run that day.",
                    "classification": "internal",
                }
            ),
            "compatible columns/shift_count added",
        ),
        (lambda d: column(d, "planned_runtime_min").update(type="bigint"), "compatible columns/planned_runtime_min"),
        (lambda d: column(d, "oee")["checks"].update(max=0.99), "compatible columns/oee max 1 to 0.99"),
        (lambda d: d["sla"]["freshness"].update(max_delay_hours=12), "compatible sla/freshness tightened"),
        (lambda d: d["table"].update(cluster_by=["kpi_date"]), "compatible table/cluster_by"),
        (lambda d: d["quality"].pop(), "compatible quality/oee_is_product_of_factors removed"),
        (lambda d: d.update(description="A clearer description of the daily KPI table."), "compatible description"),
        (
            lambda d: d["consumers"]["fabric"]["measures"].append({"name": "Max OEE", "expression": "MAX(1)"}),
            "compatible consumers/fabric/measures/Max OEE added",
        ),
    ],
    ids=[
        "column-added",
        "type-widened",
        "range-narrowed",
        "freshness-tightened",
        "clustering",
        "rule-removed",
        "description",
        "measure-added",
    ],
)
def test_compatible_changes_pass_with_a_minor_version(
    kpis_doc: dict[str, Any], mutate: Mutation, expected: str
) -> None:
    changes, errors = changes_after(kpis_doc, mutate, "1.3.0")
    assert any(c.startswith(expected) for c in changes), changes
    assert not any(c.startswith(BREAKING) for c in changes)
    assert errors == []


def test_new_allowed_value_is_breaking_and_removed_value_is_not(energy_doc: dict[str, Any]) -> None:
    def add(d: dict[str, Any]) -> None:
        column(d, "energy_carrier")["checks"]["allowed_values"].append("hydrogen")

    changes, errors = changes_after(energy_doc, add, "2.1.0")
    assert any("new allowed values ['hydrogen']" in c for c in changes)
    assert errors

    def remove(d: dict[str, Any]) -> None:
        column(d, "energy_carrier")["checks"]["allowed_values"].remove("steam")

    changes, errors = changes_after(repo_doc("energy_consumption"), remove, "2.1.0")
    assert changes == ["compatible columns/energy_carrier allowed values narrowed"]
    assert errors == []


def test_any_change_needs_a_new_version(kpis_doc: dict[str, Any]) -> None:
    _, errors = changes_after(kpis_doc, lambda d: d["sla"].update(retention_days=2000), "1.2.0")
    assert errors == ["the contract changed but its version is still 1.2.0"]


def test_version_cannot_go_backwards(kpis_doc: dict[str, Any]) -> None:
    _, errors = changes_after(kpis_doc, lambda d: None, "1.1.9")
    assert errors == ["version went backwards from 1.2.0 to 1.1.9"]


def test_identical_contracts_produce_no_change(kpis_doc: dict[str, Any]) -> None:
    changes, errors = changes_after(kpis_doc, lambda d: None, "1.2.0")
    assert changes == [] and errors == []


def test_breaking_changes_are_listed_first(kpis_doc: dict[str, Any]) -> None:
    def both(d: dict[str, Any]) -> None:
        d["table"]["cluster_by"] = ["kpi_date"]
        d["columns"] = [c for c in d["columns"] if c["name"] != "performance"]

    changes, _ = changes_after(kpis_doc, both, "2.0.0")
    assert [c.split()[0] for c in changes] == [BREAKING, COMPATIBLE]


@pytest.mark.parametrize(
    ("old", "new", "widening"),
    [
        ("int", "bigint", True),
        ("bigint", "int", False),
        ("decimal(18,3)", "decimal(20,3)", True),
        ("decimal(18,3)", "decimal(20,4)", False),
        ("int", "decimal(12,2)", True),
        ("int", "decimal(9,0)", False),
        ("date", "timestamp", True),
        ("double", "decimal(38,6)", False),
    ],
)
def test_type_widening(old: str, new: str, widening: bool) -> None:
    assert is_widening(DataType.parse(old), DataType.parse(new)) is widening
