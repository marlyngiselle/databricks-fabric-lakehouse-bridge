# Data contracts

A contract is a YAML file in `contracts/`, one per gold table. Its shape is inspired by the Open Data Contract Standard and reduced to what the generators and the gate need. The JSON schema is [`src/contracts/dctl/schema/data-contract.schema.json`](../src/contracts/dctl/schema/data-contract.schema.json).

## Sections

| Section | Holds | Used by |
| --- | --- | --- |
| `id`, `version`, `status` | Identity and semantic version | The gate, the DDL table properties |
| `owner` | Team, owner group, steward group | Terraform schema owners and grants, DDL owner and tags |
| `table` | Schema, name, primary key, clustering | Terraform schemas and shortcuts, DDL |
| `columns` | Type, nullability, description, classification, personal data flag, checks | Every generator |
| `quality` | Table level SQL predicates with `warn`, `drop` or `fail` | Expectations, CHECK constraints |
| `sla` | Freshness column and delay, frequency, availability, retention | DDL tags, docs, the gate |
| `consumers.fabric` | Exposure and DAX measures | Terraform shortcuts, TMDL |

## What `dctl validate` checks beyond the schema

- The table name matches the contract id.
- Primary key columns exist and are not nullable.
- Clustering and freshness columns exist, and the freshness column is a date or a timestamp.
- Ranges apply to numeric columns, patterns and allowed values to string columns, and every pattern compiles.
- Personal data is classified `confidential` or `restricted`.
- A table exposed through a shortcut has no `restricted` column.
- Measures need exposure, and every `'table'[column]` they reference exists.
- Quality rules are single predicates, and ids are unique across files.

## What gets generated

| Output | Path | Content |
| --- | --- | --- |
| Expectations | `generated/lakeflow/<id>_expectations.py` | Three dictionaries for `expect_all_or_fail`, `expect_all_or_drop` and `expect_all` |
| DDL | `generated/ddl/<id>.sql` | `CREATE TABLE` with comments, informational primary key, location and properties, then owner, table and column tags, then CHECK constraints |
| Semantic model | `generated/semantic_model/` | TMDL for a Direct Lake model, one table per shared contract, with measures and classification annotations |
| Data docs | `generated/docs/` | One page per contract and an index |

Key columns fail the update when null. Other column checks drop the row. Table rules keep the action the contract sets. CHECK constraints repeat the drop and fail rules on the table itself, except rules that call a non deterministic function such as `current_timestamp()`, which Delta does not accept in a constraint.

## Breaking changes

`dctl diff old.yaml new.yaml` and `dctl check-breaking --base-ref origin/main` classify every change from the consumer side. A breaking change needs a new major version, any change needs a new version, and a contract cannot be deleted before it has been released as `deprecated`.

| Breaking | Compatible |
| --- | --- |
| Column removed or renamed | Column added |
| Type changed, except widening | Type widened, for example `int` to `bigint`, or more decimal precision at the same scale |
| Column becomes nullable | Column becomes required |
| Classification raised, or column becomes personal data | Classification lowered |
| Range widened or removed, pattern changed | Range narrowed, pattern added |
| New allowed value, or allowed values removed | An allowed value withdrawn |
| Primary key changed, table moved to another schema or name | Clustering changed |
| Freshness delay increased, availability or retention lowered | Freshness tightened |
| Table withdrawn from Fabric, measure removed | Measure added or its DAX changed, quality rule added or removed, description edited |

A new allowed value is breaking on purpose. A report that filters on the known values silently drops the rows that carry the new one.
