"""Generators turn a validated contract into files. Each one is a pure function of its inputs."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from dctl.generators import ddl, docs, expectations, tmdl
from dctl.model import Contract
from dctl.target import Target

HEADER_SOURCE = "contracts/{id}.yaml"


def render_all(contracts: Iterable[Contract], target: Target) -> dict[Path, str]:
    """Every generated file, keyed by its path relative to the output directory."""
    ordered = sorted(contracts, key=lambda c: c.id)
    files: dict[Path, str] = {}
    for contract in ordered:
        files[Path("lakeflow") / f"{contract.id}_expectations.py"] = expectations.render(contract)
        files[Path("ddl") / f"{contract.id}.sql"] = ddl.render(contract, target)
        files[Path("docs") / f"{contract.id}.md"] = docs.render(contract, target)
    files[Path("docs") / "README.md"] = docs.render_index(ordered, target)
    files.update({Path("semantic_model") / p: text for p, text in tmdl.render(ordered).items()})
    return files
