"""Schema validation plus the semantic rules a JSON schema cannot express."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from dctl.model import Contract, from_document, load_document


@dataclass(frozen=True)
class Finding:
    """A problem found in a contract. Every finding blocks the contract."""

    path: str
    message: str

    def __str__(self) -> str:
        return f"{self.path}: {self.message}"


@cache
def _validator() -> Draft202012Validator:
    text = resources.files("dctl").joinpath("schema/data-contract.schema.json").read_text(encoding="utf-8")
    schema = json.loads(text)
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def schema_findings(doc: dict[str, Any]) -> list[Finding]:
    errors = sorted(_validator().iter_errors(doc), key=lambda e: [str(p) for p in e.absolute_path])
    return [Finding("/".join(str(p) for p in e.absolute_path) or "(root)", e.message) for e in errors]


def semantic_findings(contract: Contract) -> list[Finding]:
    findings: list[Finding] = []
    names = [c.name for c in contract.columns]
    known = set(names)

    duplicates = sorted({n for n in names if names.count(n) > 1})
    findings += [Finding("columns", f"column '{n}' is declared more than once") for n in duplicates]

    if contract.table != contract.id:
        findings.append(Finding("table/name", f"must match the contract id '{contract.id}'"))

    for key in contract.primary_key:
        column = contract.column(key)
        if column is None:
            findings.append(Finding("table/primary_key", f"unknown column '{key}'"))
        elif column.nullable:
            findings.append(Finding("table/primary_key", f"column '{key}' is part of the key and must not be nullable"))

    findings += [Finding("table/cluster_by", f"unknown column '{c}'") for c in contract.cluster_by if c not in known]

    freshness = contract.column(contract.freshness_column)
    if freshness is None:
        findings.append(Finding("sla/freshness/column", f"unknown column '{contract.freshness_column}'"))
    elif freshness.type.name not in {"timestamp", "date"}:
        findings.append(Finding("sla/freshness/column", "must be a date or timestamp column"))

    for column in contract.columns:
        where = f"columns/{column.name}"
        checks = column.checks
        if (checks.min is not None or checks.max is not None) and not column.type.is_numeric:
            findings.append(Finding(where, "min and max only apply to numeric columns"))
        if checks.min is not None and checks.max is not None and checks.min > checks.max:
            findings.append(Finding(where, "min is greater than max"))
        if (checks.pattern or checks.allowed_values) and column.type.name != "string":
            findings.append(Finding(where, "pattern and allowed_values only apply to string columns"))
        if checks.pattern:
            try:
                re.compile(checks.pattern)
            except re.error as exc:
                findings.append(Finding(where, f"pattern does not compile: {exc}"))
        if column.pii and column.classification in {"public", "internal"}:
            findings.append(Finding(where, "a pii column must be classified confidential or restricted"))

    if contract.exposure == "shortcut":
        restricted = [c.name for c in contract.columns if c.classification == "restricted"]
        if restricted:
            findings.append(
                Finding(
                    "consumers/fabric/exposure",
                    "a shortcut reads the Delta files directly and bypasses Unity Catalog masks, "
                    f"so restricted columns cannot be exposed: {', '.join(restricted)}",
                )
            )
    elif contract.measures:
        findings.append(Finding("consumers/fabric/measures", "measures need exposure 'shortcut'"))

    for rule in contract.quality:
        if ";" in rule.expression:
            findings.append(Finding(f"quality/{rule.name}", "an expression must be a single SQL predicate"))

    measure_names = [m.name for m in contract.measures]
    findings += [
        Finding("consumers/fabric/measures", f"measure '{n}' is declared more than once")
        for n in sorted({n for n in measure_names if measure_names.count(n) > 1})
    ]
    column_ref = re.compile(r"'" + re.escape(contract.table) + r"'\[([A-Za-z0-9_]+)\]")
    for measure in contract.measures:
        for ref in column_ref.findall(measure.expression):
            if ref not in known:
                findings.append(Finding(f"consumers/fabric/measures/{measure.name}", f"unknown column '{ref}'"))
    return findings


def validate_document(doc: dict[str, Any], source: Path | None = None) -> tuple[Contract | None, list[Finding]]:
    """Validate one document. The contract is returned only when there is no finding."""
    findings = schema_findings(doc)
    if findings:
        return None, findings
    contract = from_document(doc, source)
    findings = semantic_findings(contract)
    return (None if findings else contract), findings


def validate_file(path: Path) -> tuple[Contract | None, list[Finding]]:
    try:
        doc = load_document(path)
    except (OSError, ValueError) as exc:
        return None, [Finding("(file)", str(exc))]
    except Exception as exc:  # yaml errors carry their own position
        return None, [Finding("(yaml)", str(exc).splitlines()[0])]
    return validate_document(doc, path)


def contract_files(paths: list[Path]) -> list[Path]:
    """Expand directories to the YAML files they hold, sorted for stable output."""
    files: list[Path] = []
    for path in paths:
        if path.is_dir():
            files += sorted(p for p in path.iterdir() if p.suffix in {".yaml", ".yml"})
        else:
            files.append(path)
    return files


def load_contracts(paths: list[Path]) -> tuple[list[Contract], dict[Path, list[Finding]]]:
    contracts: list[Contract] = []
    problems: dict[Path, list[Finding]] = {}
    for path in contract_files(paths):
        contract, findings = validate_file(path)
        if contract is None:
            problems[path] = findings
        else:
            contracts.append(contract)
    ids = [c.id for c in contracts]
    for contract in contracts:
        if ids.count(contract.id) > 1 and contract.source is not None:
            problems.setdefault(contract.source, []).append(
                Finding("id", f"'{contract.id}' is used by another contract")
            )
    return [c for c in contracts if c.source not in problems], problems
