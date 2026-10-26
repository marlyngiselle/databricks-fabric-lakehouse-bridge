# ADR 0002. Gold tables as external tables, split across two containers

Accepted on 2026-10-26.

## Context

A shortcut targets a storage path. Unity Catalog managed tables live under generated paths, and reading their files directly is not supported. The Fabric reader also needs read access to the files, and Azure Storage roles cannot be scoped below a container without ABAC conditions that are hard to review.

## Decision

Create every gold table as an external Delta table at `abfss://<container>@<account>.dfs.core.windows.net/<schema>/<table>`. Tables exposed to Fabric go to `gold-shared`, the others to `gold`. The Fabric reader holds `Storage Blob Data Reader` on `gold-shared` and nothing on `gold`.

## Consequences

- The contract decides the path, so `dctl` generates the `LOCATION` and Terraform generates the shortcut from the same fact.
- The storage boundary matches the contract boundary. Reviewing who can read what in Fabric means reading one role assignment.
- Exposing or withdrawing a table moves its files. The gate treats withdrawal as breaking, and the move is a planned change.
- External tables do not get predictive optimisation on their own location the way managed tables do, so maintenance jobs (`OPTIMIZE`, `VACUUM`) are scheduled by the pipelines.
