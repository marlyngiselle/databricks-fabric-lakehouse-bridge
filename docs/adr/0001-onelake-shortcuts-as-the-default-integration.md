# ADR 0001. OneLake shortcuts as the default integration

Accepted on 2026-10-26.

## Context

Gold tables are produced in Azure Databricks and governed by Unity Catalog. Analysts work in Microsoft Fabric and Power BI. The data must reach Fabric without a second copy to keep in sync, and the integration must be reviewable as code like the rest of the platform.

## Decision

Expose each gold table that its contract marks `exposure: shortcut` through a OneLake shortcut to its Delta folder in ADLS Gen2, declared with `fabric_shortcut` and a `fabric_connection` that authenticates as a dedicated reader service principal.

## Consequences

- No data is copied, and Fabric sees a Databricks write at its next read.
- The access boundary in Fabric is the storage container plus the workspace roles. Unity Catalog row filters and column masks do not apply, so restricted columns cannot be shared this way.
- Gold tables must be external tables at predictable paths (ADR 0002).
- The reader also receives the Unity Catalog grants a mirrored catalog needs, so switching does not wait on a grant change.

## Revisit when

The Fabric provider can declare a mirrored Azure Databricks catalog. Mirroring follows Unity Catalog metadata and supports managed tables, which would remove the constraint of ADR 0002.
