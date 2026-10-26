"""A Direct Lake semantic model skeleton in TMDL, one table per contract exposed to Fabric.

The connection to the lakehouse SQL endpoint is left as two Go template tokens,
SqlEndpoint and SqlEndpointId, which the fabric_semantic_model resource fills in.
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Iterable

from dctl.model import Contract, DataType

_NAMESPACE = uuid.UUID("6f1c2a52-8d0b-4c5e-9f3a-2b7d4e1a9c60")
EXPRESSION = "DatabaseQuery"


def lineage_tag(*parts: str) -> str:
    """Stable across runs, so regenerating the model does not break report bindings."""
    return str(uuid.uuid5(_NAMESPACE, "/".join(parts)))


def tmdl_type(data_type: DataType) -> str:
    return {
        "string": "string",
        "int": "int64",
        "bigint": "int64",
        "double": "double",
        "decimal": "decimal",
        "boolean": "boolean",
        "date": "dateTime",
        "timestamp": "dateTime",
    }[data_type.name]


def _name(name: str) -> str:
    return name if name.replace("_", "").isalnum() else "'" + name.replace("'", "''") + "'"


def render_table(contract: Contract) -> str:
    t = contract.table
    lines = [f"/// {contract.description}", f"table {t}", f"\tlineageTag: {lineage_tag(t)}", ""]
    for measure in contract.measures:
        lines.append(f"\tmeasure {_name(measure.name)} = {measure.expression}")
        if measure.format:
            lines.append(f"\t\tformatString: {measure.format}")
        lines.append(f"\t\tlineageTag: {lineage_tag(t, 'measure', measure.name)}")
        lines.append("")
    for column in contract.columns:
        lines.append(f"\t/// {column.description}")
        lines.append(f"\tcolumn {column.name}")
        lines.append(f"\t\tdataType: {tmdl_type(column.type)}")
        if column.type.name == "date":
            lines.append("\t\tformatString: yyyy-mm-dd")
        lines.append(f"\t\tlineageTag: {lineage_tag(t, 'column', column.name)}")
        lines.append("\t\tsummarizeBy: none")
        lines.append(f"\t\tsourceColumn: {column.name}")
        lines.append("")
        lines.append(f"\t\tannotation classification = {column.classification}")
        if column.pii:
            lines.append("\t\tannotation pii = true")
        lines.append("")
    lines += [
        f"\tpartition {t} = entity",
        "\t\tmode: directLake",
        "\t\tsource",
        f"\t\t\tentityName: {t}",
        f"\t\t\tschemaName: {contract.schema}",
        f"\t\t\texpressionSource: {EXPRESSION}",
        "",
        f"\tannotation contract_version = {contract.version}",
        "",
    ]
    return "\n".join(lines)


def render(contracts: Iterable[Contract]) -> dict[str, str]:
    exposed = [c for c in contracts if c.exposure == "shortcut"]
    files: dict[str, str] = {}
    files["definition.pbism"] = json.dumps({"version": "4.0", "settings": {}}, indent=2) + "\n"
    files["definition/database.tmdl"] = "database\n\tcompatibilityLevel: 1604\n"
    model = [
        "model Model",
        "\tculture: en-US",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tsourceQueryCulture: en-US",
        "",
    ]
    model += [f"ref table {c.table}" for c in exposed]
    files["definition/model.tmdl"] = "\n".join(model) + "\n"
    files["definition/expressions.tmdl"] = "\n".join(
        [
            f"expression {EXPRESSION} =",
            "\t\tlet",
            '\t\t    database = Sql.Database("{{ .SqlEndpoint }}", "{{ .SqlEndpointId }}")',
            "\t\tin",
            "\t\t    database",
            f"\tlineageTag: {lineage_tag('expression', EXPRESSION)}",
            "",
        ]
    )
    for contract in exposed:
        files[f"definition/tables/{contract.table}.tmdl"] = render_table(contract)
    return files
