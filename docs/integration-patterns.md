# Shortcuts, mirroring or copy

There are three ways to make a Unity Catalog table readable in Fabric. They differ in who pays for storage, how fresh the data is, which security model applies and what can be managed as code.

## Decision matrix

| Criterion | OneLake shortcut to ADLS | Mirrored Azure Databricks catalog | Copy into OneLake |
| --- | --- | --- | --- |
| Data copied | No | No, Fabric shortcuts the table files | Yes |
| Latency after a Databricks write | Next read of the Delta log | Next metadata sync | Next scheduled copy |
| Extra storage cost | None | None | A second copy |
| Unit of exposure | One table path at a time | A catalog, with schema and table selection | Whatever the pipeline copies |
| Schema changes reach Fabric | Automatically, from the Delta log | Automatically, from Unity Catalog | Only if the copy handles them |
| Unity Catalog grants apply in Fabric | No, storage RBAC applies | Partly, the identity needs `EXTERNAL_USE_SCHEMA` and `SELECT` | No |
| Row filters and column masks | Not enforced | Not enforced | Not enforced, unless the copy applies them |
| Works with managed tables | No, the path is not addressable | Yes | Yes |
| Managed as code in this stack | Yes, `fabric_shortcut` | No, see below | Yes, with a pipeline or copy job item |
| Direct Lake on top | Yes | Yes | Yes |
| Fabric can write back | No, reader role only | No | Yes, to its own copy |

## What the provider supports, measured

With `microsoft/fabric` 1.14.0, the version this stack locks, the provider offers `fabric_shortcut` with an `adls_gen2` target and a `fabric_connection` with service principal credentials. It also offers `fabric_mirrored_catalog`, but its definition format targets Iceberg REST catalogs. A mirrored Azure Databricks catalog is a different item type that the provider does not expose. Mirroring therefore stays a portal or REST API step for now, which is why the shortcut is the default here.

The stack is ready for mirroring anyway. The Fabric reader already holds `USE_CATALOG`, `USE_SCHEMA`, `SELECT` and `EXTERNAL_USE_SCHEMA` on the shared schemas, which is what a mirrored catalog needs from Unity Catalog.

## The choice for this repository

Shortcuts, for tables whose contract says `exposure: shortcut`. They are zero copy, managed in Terraform resource by resource, and their access boundary is a storage container that the contract decides. The cost is that gold tables must be external tables at known paths and that masking cannot be relied upon, which the classification policy turns into a hard rule.

Copy is the right answer for a restricted table that must still reach Fabric. A pipeline can apply the masking on the way and land a sanitised table in OneLake, which then has its own contract.

Mirroring becomes the better default once it can be declared in code, because it follows Unity Catalog metadata and works with managed tables. [ADR 0001](adr/0001-onelake-shortcuts-as-the-default-integration.md) records the trigger to revisit.
