from __future__ import annotations

import shutil
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from conftest import CONTRACTS, GENERATED, ROOT, column
from dctl.cli import main


def test_validate_repository(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(CONTRACTS)]) == 0
    assert "3 valid, 0 finding(s)" in capsys.readouterr().out


def test_validate_reports_findings(
    kpis_doc: dict[str, Any], write_yaml: Callable[[str, dict[str, Any]], Path], capsys: pytest.CaptureFixture[str]
) -> None:
    column(kpis_doc, "kpi_date")["nullable"] = True
    path = write_yaml("bad.yaml", kpis_doc)
    assert main(["validate", str(path)]) == 1
    assert "must not be nullable" in capsys.readouterr().out


def test_github_annotations(
    kpis_doc: dict[str, Any],
    write_yaml: Callable[[str, dict[str, Any]], Path],
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    kpis_doc.pop("owner")
    path = write_yaml("bad.yaml", kpis_doc)
    assert main(["validate", str(path)]) == 1
    assert f"::error file={path}::" in capsys.readouterr().out


def test_generate_check_passes_on_the_repository(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["generate", "--contracts", str(CONTRACTS), "--out", str(GENERATED), "--check"]) == 0
    assert "17 generated files up to date" in capsys.readouterr().out


def test_generate_then_check_detects_drift(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out"
    assert main(["generate", "--contracts", str(CONTRACTS), "--out", str(out)]) == 0
    assert main(["generate", "--contracts", str(CONTRACTS), "--out", str(out), "--check"]) == 0
    (out / "ddl" / "quality_events.sql").write_text("-- edited by hand\n", encoding="utf-8")
    (out / "ddl" / "leftover.sql").write_text("", encoding="utf-8")
    assert main(["generate", "--contracts", str(CONTRACTS), "--out", str(out), "--check"]) == 1
    printed = capsys.readouterr().out
    assert "stale  " in printed and "quality_events.sql" in printed
    assert "orphan " in printed and "leftover.sql" in printed


def test_generate_targets_another_environment(tmp_path: Path) -> None:
    out = tmp_path / "prod"
    args = ["generate", "--contracts", str(CONTRACTS), "--out", str(out)]
    assert main([*args, "--catalog", "gold_prod", "--storage-account", "stbridgeprod"]) == 0
    sql = (out / "ddl" / "asset_daily_kpis.sql").read_text(encoding="utf-8")
    assert "gold_prod.operations.asset_daily_kpis" in sql
    assert "@stbridgeprod.dfs.core.windows.net/" in sql


def test_generate_refuses_invalid_contracts(
    kpis_doc: dict[str, Any], write_yaml: Callable[[str, dict[str, Any]], Path], tmp_path: Path
) -> None:
    kpis_doc["version"] = "one"
    path = write_yaml("contracts/asset_daily_kpis.yaml", kpis_doc)
    assert main(["generate", "--contracts", str(path.parent), "--out", str(tmp_path / "out")]) == 1
    assert not (tmp_path / "out").exists()


def test_diff_command(
    kpis_doc: dict[str, Any], write_yaml: Callable[[str, dict[str, Any]], Path], capsys: pytest.CaptureFixture[str]
) -> None:
    old = write_yaml("old.yaml", kpis_doc)
    kpis_doc["columns"] = [c for c in kpis_doc["columns"] if c["name"] != "performance"]
    kpis_doc["version"] = "1.3.0"
    new = write_yaml("new.yaml", kpis_doc)
    assert main(["diff", str(old), str(new)]) == 1
    printed = capsys.readouterr().out
    assert "[breaking] columns/performance: removed" in printed
    assert "BLOCKED 1 breaking change(s) need a new major version" in printed


def test_diff_with_an_invalid_side(kpis_doc: dict[str, Any], write_yaml: Callable[[str, dict[str, Any]], Path]) -> None:
    old = write_yaml("old.yaml", kpis_doc)
    kpis_doc.pop("sla")
    new = write_yaml("new.yaml", kpis_doc)
    assert main(["diff", str(old), str(new)]) == 2


# check-breaking runs against a real git history in a throwaway repository.


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    if shutil.which("git") is None:
        pytest.skip("git is not installed")
    shutil.copytree(CONTRACTS, tmp_path / "contracts")
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "-c", "user.name=ci", "-c", "user.email=ci@example.invalid", "add", ".")
    _git(tmp_path, "-c", "user.name=ci", "-c", "user.email=ci@example.invalid", "commit", "-q", "-m", "base")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _edit(repo: Path, name: str, change: Callable[[dict[str, Any]], object]) -> None:
    path = repo / "contracts" / f"{name}.yaml"
    doc = yaml.safe_load(path.read_text(encoding="utf-8"))
    change(doc)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


def test_gate_passes_without_changes(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["check-breaking", "--base-ref", "main"]) == 0
    assert "breaking change gate: passed" in capsys.readouterr().out


def test_gate_blocks_a_breaking_change_without_major_bump(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    def narrow(doc: dict[str, Any]) -> None:
        column(doc, "consumption_kwh")["type"] = "decimal(10,3)"
        doc["version"] = "2.1.0"

    _edit(repo, "energy_consumption", narrow)
    assert main(["check-breaking", "--base-ref", "main"]) == 1
    printed = capsys.readouterr().out
    assert "[breaking] columns/consumption_kwh: type decimal(18,3) to decimal(10,3)" in printed
    assert "breaking change gate: failed" in printed


def test_gate_accepts_the_same_change_with_a_major_bump(repo: Path) -> None:
    def narrow(doc: dict[str, Any]) -> None:
        column(doc, "consumption_kwh")["type"] = "decimal(10,3)"
        doc["version"] = "3.0.0"

    _edit(repo, "energy_consumption", narrow)
    assert main(["check-breaking", "--base-ref", "main"]) == 0


def test_gate_blocks_a_deleted_contract(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (repo / "contracts" / "quality_events.yaml").unlink()
    assert main(["check-breaking", "--base-ref", "main"]) == 1
    assert "contract deleted" in capsys.readouterr().out


def test_gate_accepts_a_new_contract(repo: Path, capsys: pytest.CaptureFixture[str]) -> None:
    doc = yaml.safe_load((repo / "contracts" / "quality_events.yaml").read_text(encoding="utf-8"))
    doc["id"] = doc["table"]["name"] = "rework_orders"
    doc["consumers"]["fabric"]["measures"] = []
    (repo / "contracts" / "rework_orders.yaml").write_text(yaml.safe_dump(doc), encoding="utf-8")
    assert main(["check-breaking", "--base-ref", "main"]) == 0
    assert "new contract rework_orders 1.0.0" in capsys.readouterr().out


def test_module_entry_point() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "dctl", "--version"], cwd=ROOT, capture_output=True, text=True, check=False
    )
    assert result.returncode == 0
    assert result.stdout.startswith("dctl ")


def test_readme_example_is_blocked(capsys: pytest.CaptureFixture[str]) -> None:
    """The example in the README must keep producing the output it shows."""
    proposed = ROOT / "examples" / "asset_daily_kpis.proposed.yaml"
    assert main(["diff", str(CONTRACTS / "asset_daily_kpis.yaml"), str(proposed)]) == 1
    printed = capsys.readouterr().out
    assert printed.count("[breaking]") == 3
    assert printed.count("[compatible]") == 1
    assert "BLOCKED 3 breaking change(s) need a new major version, 1.2.0 to 2.0.0" in printed
