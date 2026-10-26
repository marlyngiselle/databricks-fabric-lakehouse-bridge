"""Compare two versions of a contract from the point of view of its consumers.

A change is breaking when a query, a pipeline or a report written against the old
version can fail or return different meaning against the new one. Breaking changes
need a new major version. Any change needs a new version.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from dctl.model import CLASSIFICATION_RANK, Column, Contract, DataType

BREAKING = "breaking"
COMPATIBLE = "compatible"

_WIDENING = {("int", "bigint"), ("int", "double"), ("int", "decimal"), ("bigint", "decimal"), ("date", "timestamp")}


@dataclass(frozen=True)
class Change:
    kind: str
    path: str
    message: str

    def __str__(self) -> str:
        return f"[{self.kind}] {self.path}: {self.message}"


@dataclass
class DiffReport:
    contract_id: str
    old_version: str
    new_version: str
    changes: list[Change] = field(default_factory=list)

    @property
    def breaking(self) -> list[Change]:
        return [c for c in self.changes if c.kind == BREAKING]

    def gate_errors(self) -> list[str]:
        """Why this change cannot be merged. Empty when the gate passes."""
        old = _semver(self.old_version)
        new = _semver(self.new_version)
        errors = []
        if new < old:
            errors.append(f"version went backwards from {self.old_version} to {self.new_version}")
        elif self.changes and new == old:
            errors.append(f"the contract changed but its version is still {self.new_version}")
        if self.breaking and new[0] <= old[0]:
            errors.append(
                f"{len(self.breaking)} breaking change(s) need a new major version, "
                f"{self.old_version} to {old[0] + 1}.0.0"
            )
        return errors

    @property
    def passed(self) -> bool:
        return not self.gate_errors()


def _semver(version: str) -> tuple[int, int, int]:
    major, minor, patch = (int(p) for p in version.split("."))
    return major, minor, patch


def is_widening(old: DataType, new: DataType) -> bool:
    if old == new:
        return True
    if old.name == "decimal" and new.name == "decimal":
        assert old.precision is not None and old.scale is not None
        assert new.precision is not None and new.scale is not None
        return new.scale == old.scale and new.precision > old.precision
    if (old.name, new.name) == ("int", "decimal"):
        return new.precision is not None and new.scale is not None and new.precision - new.scale >= 10
    if (old.name, new.name) == ("bigint", "decimal"):
        return new.precision is not None and new.scale is not None and new.precision - new.scale >= 19
    return (old.name, new.name) in _WIDENING


def _column_changes(old: Column, new: Column) -> list[Change]:
    path = f"columns/{new.name}"
    out: list[Change] = []
    if old.type != new.type:
        kind = COMPATIBLE if is_widening(old.type, new.type) else BREAKING
        out.append(Change(kind, path, f"type {old.type} to {new.type}"))
    if old.nullable != new.nullable:
        if new.nullable:
            out.append(Change(BREAKING, path, "now nullable, consumers may receive NULL"))
        else:
            out.append(Change(COMPATIBLE, path, "no longer nullable"))
    old_rank = CLASSIFICATION_RANK[old.classification]
    new_rank = CLASSIFICATION_RANK[new.classification]
    if new_rank > old_rank:
        out.append(Change(BREAKING, path, f"classification raised from {old.classification} to {new.classification}"))
    elif new_rank < old_rank:
        out.append(
            Change(COMPATIBLE, path, f"classification lowered from {old.classification} to {new.classification}")
        )
    if new.pii and not old.pii:
        out.append(Change(BREAKING, path, "now flagged as personal data"))
    elif old.pii and not new.pii:
        out.append(Change(COMPATIBLE, path, "no longer flagged as personal data"))

    oc, nc = old.checks, new.checks
    if nc.min != oc.min:
        widened = nc.min is None or (oc.min is not None and nc.min < oc.min)
        out.append(Change(BREAKING if widened else COMPATIBLE, path, f"min {oc.min} to {nc.min}"))
    if nc.max != oc.max:
        widened = nc.max is None or (oc.max is not None and nc.max > oc.max)
        out.append(Change(BREAKING if widened else COMPATIBLE, path, f"max {oc.max} to {nc.max}"))
    if nc.pattern != oc.pattern:
        kind = COMPATIBLE if oc.pattern is None else BREAKING
        out.append(Change(kind, path, f"pattern {oc.pattern!r} to {nc.pattern!r}"))
    added = set(nc.allowed_values) - set(oc.allowed_values)
    removed = set(oc.allowed_values) - set(nc.allowed_values)
    if oc.allowed_values and not nc.allowed_values:
        out.append(Change(BREAKING, path, "allowed values no longer restricted"))
    elif added and oc.allowed_values:
        out.append(Change(BREAKING, path, f"new allowed values {sorted(added)}"))
    elif removed or (added and not oc.allowed_values):
        out.append(Change(COMPATIBLE, path, "allowed values narrowed"))
    if old.description != new.description:
        out.append(Change(COMPATIBLE, path, "description updated"))
    return out


def diff(old: Contract, new: Contract) -> DiffReport:
    report = DiffReport(new.id, old.version, new.version)
    changes = report.changes

    if (old.schema, old.table) != (new.schema, new.table):
        changes.append(Change(BREAKING, "table", f"moved from {old.schema}.{old.table} to {new.schema}.{new.table}"))
    if old.primary_key != new.primary_key:
        changes.append(Change(BREAKING, "table/primary_key", f"{list(old.primary_key)} to {list(new.primary_key)}"))
    if old.cluster_by != new.cluster_by:
        changes.append(Change(COMPATIBLE, "table/cluster_by", f"{list(old.cluster_by)} to {list(new.cluster_by)}"))

    old_columns = {c.name: c for c in old.columns}
    new_columns = {c.name: c for c in new.columns}
    for name in old_columns.keys() - new_columns.keys():
        changes.append(Change(BREAKING, f"columns/{name}", "removed"))
    for name in new_columns.keys() - old_columns.keys():
        changes.append(Change(COMPATIBLE, f"columns/{name}", "added"))
    for name in old_columns.keys() & new_columns.keys():
        changes += _column_changes(old_columns[name], new_columns[name])

    old_rules = {q.name: q for q in old.quality}
    new_rules = {q.name: q for q in new.quality}
    for name in old_rules.keys() ^ new_rules.keys():
        verb = "added" if name in new_rules else "removed"
        changes.append(Change(COMPATIBLE, f"quality/{name}", verb))
    for name in old_rules.keys() & new_rules.keys():
        if old_rules[name] != new_rules[name]:
            changes.append(Change(COMPATIBLE, f"quality/{name}", "rule changed"))

    if new.max_delay_hours > old.max_delay_hours:
        changes.append(
            Change(BREAKING, "sla/freshness", f"loosened from {old.max_delay_hours:g} h to {new.max_delay_hours:g} h")
        )
    elif new.max_delay_hours < old.max_delay_hours:
        changes.append(
            Change(
                COMPATIBLE, "sla/freshness", f"tightened from {old.max_delay_hours:g} h to {new.max_delay_hours:g} h"
            )
        )
    if old.freshness_column != new.freshness_column:
        changes.append(Change(COMPATIBLE, "sla/freshness", f"measured on {new.freshness_column}"))
    if (old.update_frequency, old.availability_percent, old.retention_days) != (
        new.update_frequency,
        new.availability_percent,
        new.retention_days,
    ):
        lowered = (new.availability_percent or 0) < (old.availability_percent or 0) or (new.retention_days or 0) < (
            old.retention_days or 0
        )
        changes.append(Change(BREAKING if lowered else COMPATIBLE, "sla", "service levels changed"))

    if old.exposure == "shortcut" and new.exposure != "shortcut":
        changes.append(Change(BREAKING, "consumers/fabric/exposure", "table withdrawn from Fabric"))
    elif old.exposure != new.exposure:
        changes.append(Change(COMPATIBLE, "consumers/fabric/exposure", f"{old.exposure} to {new.exposure}"))

    old_measures = {m.name: m for m in old.measures}
    new_measures = {m.name: m for m in new.measures}
    for name in old_measures.keys() - new_measures.keys():
        changes.append(Change(BREAKING, f"consumers/fabric/measures/{name}", "removed"))
    for name in new_measures.keys() - old_measures.keys():
        changes.append(Change(COMPATIBLE, f"consumers/fabric/measures/{name}", "added"))
    for name in old_measures.keys() & new_measures.keys():
        if old_measures[name] != new_measures[name]:
            changes.append(Change(COMPATIBLE, f"consumers/fabric/measures/{name}", "definition changed"))

    meta = ("status", "domain", "description", "owner_team", "owner_group", "steward_group")
    for attr in meta:
        if getattr(old, attr) != getattr(new, attr):
            changes.append(Change(COMPATIBLE, attr, "updated"))

    changes.sort(key=lambda c: (c.kind != BREAKING, c.path, c.message))
    return report
