# ADR 0003. Contracts drive code generation and the CI gate

Accepted on 2026-10-26.

## Context

The same facts about a table used to live in five places: the pipeline expectations, the DDL, the Unity Catalog tags, the semantic model and the documentation. They drift, and the drift is found by a broken report.

## Decision

Write each fact once, in a contract validated by a JSON schema and semantic rules. Generate expectations, DDL with tags and constraints, a Direct Lake TMDL skeleton and data docs from it with `dctl`. Commit the generated files, fail CI when they are stale, and fail a pull request that makes a breaking change without a new major version.

## Consequences

- A reviewer reads the contract diff and the generated diff side by side, and the gate output says which changes are breaking.
- Terraform reads the same YAML for schemas, owners and shortcuts, so the platform and the data product cannot disagree on a table name.
- Generators are pure functions with golden files, so a change in the generator itself shows up as a diff in `generated/`.
- Contracts cover what tooling can enforce. Business definitions beyond a description and DAX measures stay with the stewards.
