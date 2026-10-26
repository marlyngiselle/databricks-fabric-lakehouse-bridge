from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from conftest import CONTRACTS, column
from dctl.validate import load_contracts, validate_document, validate_file


def messages(doc: dict[str, Any]) -> list[str]:
    contract, findings = validate_document(doc)
    assert contract is None
    return [str(f) for f in findings]


def test_every_repository_contract_is_valid() -> None:
    contracts, problems = load_contracts([CONTRACTS])
    assert problems == {}
    assert sorted(c.id for c in contracts) == ["asset_daily_kpis", "energy_consumption", "quality_events"]


def test_repository_contracts_cover_three_domains() -> None:
    contracts, _ = load_contracts([CONTRACTS])
    assert {c.schema for c in contracts} == {"operations", "energy", "quality"}
    assert all(c.exposure == "shortcut" for c in contracts)


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: d.pop("owner"), "'owner' is a required property"),
        (lambda d: d.update(version="1.2"), "does not match"),
        (lambda d: d.update(status="live"), "is not one of"),
        (lambda d: d.update(unexpected=True), "Additional properties are not allowed"),
        (lambda d: column(d, "asset_id").update(type="varchar(20)"), "does not match"),
        (lambda d: column(d, "asset_id").update(classification="secret"), "is not one of"),
        (lambda d: column(d, "asset_id").pop("description"), "'description' is a required property"),
        (lambda d: d["sla"]["freshness"].update(max_delay_hours=0), "less than or equal to the minimum"),
        (lambda d: d["consumers"]["fabric"].update(exposure="mirror"), "is not one of"),
        (lambda d: d["owner"].update(group="Ops Owners"), "does not match"),
    ],
    ids=[
        "missing-owner",
        "bad-semver",
        "bad-status",
        "unknown-key",
        "unsupported-type",
        "bad-classification",
        "missing-description",
        "zero-freshness",
        "bad-exposure",
        "bad-principal",
    ],
)
def test_schema_rejects(kpis_doc: dict[str, Any], mutate: Callable[[dict[str, Any]], object], expected: str) -> None:
    mutate(kpis_doc)
    assert any(expected in m for m in messages(kpis_doc))


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda d: column(d, "kpi_date").update(nullable=True), "must not be nullable"),
        (lambda d: d["table"].update(primary_key=["asset_id", "day"]), "unknown column 'day'"),
        (lambda d: d["table"].update(cluster_by=["plant"]), "unknown column 'plant'"),
        (lambda d: d["table"].update(name="kpis"), "must match the contract id"),
        (lambda d: d["sla"]["freshness"].update(column="oee"), "must be a date or timestamp"),
        (lambda d: d["sla"]["freshness"].update(column="loaded_at"), "unknown column 'loaded_at'"),
        (lambda d: column(d, "site_code").update(checks={"min": 1}), "only apply to numeric"),
        (lambda d: column(d, "oee").update(checks={"pattern": "^1$"}), "only apply to string"),
        (lambda d: column(d, "oee").update(checks={"min": 2, "max": 1}), "min is greater than max"),
        (lambda d: column(d, "site_code").update(checks={"pattern": "([A-Z"}), "does not compile"),
        (lambda d: column(d, "site_code").update(pii=True), "must be classified confidential"),
        (lambda d: d["columns"].append(dict(d["columns"][0])), "declared more than once"),
        (lambda d: d["quality"].append({"name": "x", "expression": "a > 1; DROP", "on_violation": "fail"}), "single"),
    ],
    ids=[
        "nullable-key",
        "unknown-key-column",
        "unknown-cluster-column",
        "table-name-mismatch",
        "freshness-not-temporal",
        "freshness-unknown",
        "range-on-string",
        "pattern-on-number",
        "inverted-range",
        "bad-regex",
        "pii-internal",
        "duplicate-column",
        "multi-statement-rule",
    ],
)
def test_semantic_rules_reject(
    kpis_doc: dict[str, Any], mutate: Callable[[dict[str, Any]], object], expected: str
) -> None:
    mutate(kpis_doc)
    assert any(expected in m for m in messages(kpis_doc))


def test_restricted_column_cannot_be_shared_through_a_shortcut(quality_doc: dict[str, Any]) -> None:
    column(quality_doc, "inspector_pseudo_id").update(classification="restricted")
    found = messages(quality_doc)
    assert any("bypasses Unity Catalog masks" in m and "inspector_pseudo_id" in m for m in found)


def test_restricted_column_is_fine_when_the_table_stays_in_databricks(quality_doc: dict[str, Any]) -> None:
    column(quality_doc, "inspector_pseudo_id").update(classification="restricted")
    quality_doc["consumers"]["fabric"] = {"exposure": "none"}
    contract, findings = validate_document(quality_doc)
    assert findings == []
    assert contract is not None and contract.max_classification == "restricted"


def test_measures_need_a_shortcut(energy_doc: dict[str, Any]) -> None:
    energy_doc["consumers"]["fabric"]["exposure"] = "none"
    assert any("measures need exposure 'shortcut'" in m for m in messages(energy_doc))


def test_measure_referencing_an_unknown_column(energy_doc: dict[str, Any]) -> None:
    energy_doc["consumers"]["fabric"]["measures"][0]["expression"] = "SUM('energy_consumption'[kwh])"
    assert any("unknown column 'kwh'" in m for m in messages(energy_doc))


def test_duplicate_ids_across_files(
    kpis_doc: dict[str, Any], write_yaml: Callable[[str, dict[str, Any]], Path]
) -> None:
    first = write_yaml("a/one.yaml", kpis_doc)
    write_yaml("a/two.yaml", kpis_doc)
    contracts, problems = load_contracts([first.parent])
    assert contracts == []
    assert len(problems) == 2


def test_yaml_that_is_not_a_mapping(tmp_path: Path) -> None:
    path = tmp_path / "list.yaml"
    path.write_text("- a\n- b\n", encoding="utf-8")
    contract, findings = validate_file(path)
    assert contract is None
    assert "must be a YAML mapping" in str(findings[0])


def test_broken_yaml_is_reported_not_raised(tmp_path: Path) -> None:
    path = tmp_path / "broken.yaml"
    path.write_text("id: [unclosed\n", encoding="utf-8")
    contract, findings = validate_file(path)
    assert contract is None
    assert findings[0].path == "(yaml)"
