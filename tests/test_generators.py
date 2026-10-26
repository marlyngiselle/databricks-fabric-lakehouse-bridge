from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from conftest import CONTRACTS, GENERATED, build, column
from dctl.generators import ddl, docs, expectations, render_all, tmdl
from dctl.target import Target
from dctl.validate import load_contracts

TARGET = Target()


def rendered() -> dict[Path, str]:
    contracts, problems = load_contracts([CONTRACTS])
    assert problems == {}
    return render_all(contracts, TARGET)


@pytest.mark.parametrize("relative", sorted(rendered()), ids=str)
def test_golden_file_matches(relative: Path) -> None:
    """generated/ is the golden copy. Regenerate with `dctl generate` after an intended change."""
    golden = GENERATED / relative
    assert golden.is_file(), f"missing golden file {golden}"
    assert rendered()[relative] == golden.read_text(encoding="utf-8")


def test_no_orphan_golden_files() -> None:
    on_disk = {p.relative_to(GENERATED) for p in GENERATED.rglob("*") if p.is_file()}
    assert on_disk == set(rendered())


def test_rendering_is_deterministic() -> None:
    assert rendered() == rendered()


# Expectations


def test_key_columns_fail_and_other_columns_drop(kpis_doc: dict[str, Any]) -> None:
    by_name = {e.name: e for e in expectations.build(build(kpis_doc))}
    assert by_name["asset_id_not_null"].action == "fail"
    assert by_name["kpi_date_not_null"].action == "fail"
    assert by_name["site_code_not_null"].action == "drop"
    assert by_name["oee_in_range"].predicate == "oee BETWEEN 0 AND 1"
    assert by_name["oee_is_product_of_factors"].action == "warn"


def test_nullable_column_accepts_null(energy_doc: dict[str, Any]) -> None:
    by_name = {e.name: e for e in expectations.build(build(energy_doc))}
    assert by_name["asset_id_pattern"].predicate == "asset_id IS NULL OR asset_id RLIKE '^AST-[0-9]{6}$'"
    assert "asset_id_not_null" not in by_name


def test_quotes_and_backslashes_are_escaped(kpis_doc: dict[str, Any]) -> None:
    column(kpis_doc, "site_code")["checks"] = {"pattern": r"^O'K\d$"}
    by_name = {e.name: e for e in expectations.build(build(kpis_doc))}
    assert by_name["site_code_pattern"].predicate == r"site_code RLIKE '^O\'K\\d$'"


def test_only_min_or_only_max(kpis_doc: dict[str, Any]) -> None:
    column(kpis_doc, "oee")["checks"] = {"max": 1.5}
    by_name = {e.name: e for e in expectations.build(build(kpis_doc))}
    assert by_name["oee_max"].predicate == "oee <= 1.5"
    assert by_name["units_produced_min"].predicate == "units_produced >= 0"


def test_expectation_module_is_valid_python(kpis_doc: dict[str, Any]) -> None:
    source = expectations.render(build(kpis_doc))
    namespace: dict[str, Any] = {}
    exec(compile(ast.parse(source), "<expectations>", "exec"), namespace)
    assert namespace["CONTRACT_VERSION"] == "1.2.0"
    assert set(namespace["EXPECT"]) == {"oee_is_product_of_factors"}
    assert len(namespace["EXPECT_OR_FAIL"]) == 2


# DDL


def test_ddl_carries_key_location_tags_and_constraints(quality_doc: dict[str, Any]) -> None:
    sql = ddl.render(build(quality_doc), TARGET)
    assert "CREATE TABLE IF NOT EXISTS gold_dev.quality.quality_events (" in sql
    assert "CONSTRAINT quality_events_pk PRIMARY KEY (event_id) NOT ENFORCED" in sql
    assert "LOCATION 'abfss://gold-shared@stbridgedev.dfs.core.windows.net/quality/quality_events'" in sql
    assert "ALTER COLUMN inspector_pseudo_id SET TAGS ('classification' = 'confidential', 'pii' = 'true')" in sql
    assert "'contains_pii' = 'true'" in sql
    assert "ADD CONSTRAINT severity_allowed CHECK (severity IN ('minor', 'major', 'critical'))" in sql


def test_non_deterministic_and_warn_rules_are_not_check_constraints(energy_doc: dict[str, Any]) -> None:
    sql = ddl.render(build(energy_doc), TARGET)
    assert "reading_not_in_future" not in sql
    assert "emissions_need_consumption" not in sql
    assert "ADD CONSTRAINT co2e_kg_min CHECK (co2e_kg >= 0)" in sql
    assert ddl.is_deterministic("a > b")
    assert not ddl.is_deterministic("ts <= CURRENT_TIMESTAMP ()")


def test_internal_tables_land_in_the_internal_container(quality_doc: dict[str, Any]) -> None:
    quality_doc["consumers"]["fabric"] = {"exposure": "none"}
    sql = ddl.render(build(quality_doc), Target(catalog="gold_prod", storage_account="stbridgeprod"))
    assert "LOCATION 'abfss://gold@stbridgeprod.dfs.core.windows.net/quality/quality_events'" in sql
    assert "gold_prod.quality.quality_events" in sql


def test_decimal_type_is_kept(energy_doc: dict[str, Any]) -> None:
    sql = ddl.render(build(energy_doc), TARGET)
    assert "consumption_kwh         DECIMAL(18,3) NOT NULL" in sql


# TMDL


def test_semantic_model_lists_only_shared_tables(kpis_doc: dict[str, Any], quality_doc: dict[str, Any]) -> None:
    quality_doc["consumers"]["fabric"] = {"exposure": "none"}
    files = tmdl.render([build(kpis_doc), build(quality_doc)])
    assert "definition/tables/asset_daily_kpis.tmdl" in files
    assert "definition/tables/quality_events.tmdl" not in files
    assert files["definition/model.tmdl"].strip().endswith("ref table asset_daily_kpis")


def test_semantic_model_uses_direct_lake_and_template_tokens(kpis_doc: dict[str, Any]) -> None:
    files = tmdl.render([build(kpis_doc)])
    table = files["definition/tables/asset_daily_kpis.tmdl"]
    assert "\t\tmode: directLake" in table
    assert "\t\t\tschemaName: operations" in table
    assert "measure 'Average OEE' = AVERAGE('asset_daily_kpis'[oee])" in table
    assert "compatibilityLevel: 1604" in files["definition/database.tmdl"]
    assert "{{ .SqlEndpoint }}" in files["definition/expressions.tmdl"]


def test_lineage_tags_are_stable_and_unique(kpis_doc: dict[str, Any]) -> None:
    table = tmdl.render([build(kpis_doc)])["definition/tables/asset_daily_kpis.tmdl"]
    tags = [line.split(": ")[1] for line in table.splitlines() if "lineageTag:" in line]
    assert len(tags) == len(set(tags)) == 1 + 3 + 12
    assert tmdl.lineage_tag("a", "b") == tmdl.lineage_tag("a", "b")


@pytest.mark.parametrize(
    ("logical", "expected"),
    [("string", "string"), ("bigint", "int64"), ("decimal(18,3)", "decimal"), ("date", "dateTime")],
)
def test_tmdl_types(logical: str, expected: str) -> None:
    from dctl.model import DataType

    assert tmdl.tmdl_type(DataType.parse(logical)) == expected


def test_pii_annotation(quality_doc: dict[str, Any]) -> None:
    table = tmdl.render([build(quality_doc)])["definition/tables/quality_events.tmdl"]
    assert "annotation pii = true" in table


# Docs


def test_docs_page_and_index(energy_doc: dict[str, Any]) -> None:
    contract = build(energy_doc)
    page = docs.render(contract, TARGET)
    assert page.startswith("# energy.energy_consumption")
    assert "| Freshness | `ingested_at` no older than 3 hours |" in page
    assert "one of `electricity`, `natural_gas`, `steam`, `compressed_air`" in page
    index = docs.render_index([contract], TARGET)
    assert "[energy.energy_consumption](energy_consumption.md)" in index
