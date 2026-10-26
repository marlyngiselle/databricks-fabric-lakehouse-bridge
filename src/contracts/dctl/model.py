"""Typed view of a data contract, built after the JSON schema has accepted the document."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

CLASSIFICATION_RANK = {"public": 0, "internal": 1, "confidential": 2, "restricted": 3}

_DECIMAL = re.compile(r"^decimal\((\d+),(\d+)\)$")


@dataclass(frozen=True)
class DataType:
    """A logical column type. Decimals keep precision and scale."""

    name: str
    precision: int | None = None
    scale: int | None = None

    @classmethod
    def parse(cls, raw: str) -> DataType:
        match = _DECIMAL.match(raw)
        if match:
            return cls("decimal", int(match.group(1)), int(match.group(2)))
        return cls(raw)

    @property
    def is_numeric(self) -> bool:
        return self.name in {"int", "bigint", "double", "decimal"}

    def __str__(self) -> str:
        if self.name == "decimal":
            return f"decimal({self.precision},{self.scale})"
        return self.name


@dataclass(frozen=True)
class Checks:
    min: float | None = None
    max: float | None = None
    pattern: str | None = None
    allowed_values: tuple[str, ...] = ()


@dataclass(frozen=True)
class Column:
    name: str
    type: DataType
    nullable: bool
    description: str
    classification: str
    pii: bool = False
    checks: Checks = field(default_factory=Checks)


@dataclass(frozen=True)
class QualityRule:
    name: str
    expression: str
    on_violation: str


@dataclass(frozen=True)
class Measure:
    name: str
    expression: str
    format: str | None = None


@dataclass(frozen=True)
class Contract:
    id: str
    version: str
    status: str
    domain: str
    description: str
    owner_team: str
    owner_group: str
    steward_group: str
    schema: str
    table: str
    primary_key: tuple[str, ...]
    cluster_by: tuple[str, ...]
    columns: tuple[Column, ...]
    quality: tuple[QualityRule, ...]
    freshness_column: str
    max_delay_hours: float
    update_frequency: str
    availability_percent: float | None
    retention_days: int | None
    exposure: str
    measures: tuple[Measure, ...]
    source: Path | None = None

    @property
    def major(self) -> int:
        return int(self.version.split(".")[0])

    @property
    def max_classification(self) -> str:
        return max((c.classification for c in self.columns), key=CLASSIFICATION_RANK.__getitem__)

    @property
    def contains_pii(self) -> bool:
        return any(c.pii for c in self.columns)

    def column(self, name: str) -> Column | None:
        return next((c for c in self.columns if c.name == name), None)


def load_document(path: Path) -> dict[str, Any]:
    """Read a YAML contract as plain data, for schema validation."""
    with path.open(encoding="utf-8") as handle:
        data = yaml.safe_load(handle)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: a contract must be a YAML mapping")
    return data


def from_document(doc: dict[str, Any], source: Path | None = None) -> Contract:
    """Build a Contract from a document that already passed schema validation."""
    table = doc["table"]
    sla = doc["sla"]
    fabric = doc["consumers"]["fabric"]
    columns = tuple(
        Column(
            name=c["name"],
            type=DataType.parse(c["type"]),
            nullable=c["nullable"],
            description=c["description"].strip(),
            classification=c["classification"],
            pii=c.get("pii", False),
            checks=Checks(
                min=c.get("checks", {}).get("min"),
                max=c.get("checks", {}).get("max"),
                pattern=c.get("checks", {}).get("pattern"),
                allowed_values=tuple(c.get("checks", {}).get("allowed_values", ())),
            ),
        )
        for c in doc["columns"]
    )
    return Contract(
        id=doc["id"],
        version=doc["version"],
        status=doc["status"],
        domain=doc["domain"],
        description=" ".join(doc["description"].split()),
        owner_team=doc["owner"]["team"],
        owner_group=doc["owner"]["group"],
        steward_group=doc["owner"]["steward"],
        schema=table["schema"],
        table=table["name"],
        primary_key=tuple(table["primary_key"]),
        cluster_by=tuple(table.get("cluster_by", ())),
        columns=columns,
        quality=tuple(
            QualityRule(q["name"], q["expression"].strip(), q["on_violation"]) for q in doc.get("quality", ())
        ),
        freshness_column=sla["freshness"]["column"],
        max_delay_hours=sla["freshness"]["max_delay_hours"],
        update_frequency=sla["update_frequency"],
        availability_percent=sla.get("availability_percent"),
        retention_days=sla.get("retention_days"),
        exposure=fabric["exposure"],
        measures=tuple(
            Measure(m["name"], m["expression"].strip(), m.get("format")) for m in fabric.get("measures", ())
        ),
        source=source,
    )
