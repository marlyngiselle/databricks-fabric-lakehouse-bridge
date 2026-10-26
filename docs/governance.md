# Governance and access model

Access is declared in two places that must agree. Unity Catalog grants govern who reads through Databricks. Azure Storage role assignments govern who reads the files, which is what a OneLake shortcut does. This stack writes both.

## Who can do what

| Principal | Catalog `gold_<env>` | Domain schemas | `gold` container | `gold-shared` container | Fabric workspace |
| --- | --- | --- | --- | --- | --- |
| `platform-admins` | Owner, `ALL_PRIVILEGES` | Inherited | Location owner | Location owner | Admin (by object ID) |
| Pipeline service principal | `USE_CATALOG` | `USE_SCHEMA`, `CREATE_TABLE`, `MODIFY`, `SELECT` | Read, write, create external table | Read, write, create external table | None |
| Domain owner group, from the contract | `USE_CATALOG` | Schema owner, table owner | None | None | None |
| Domain steward group, from the contract | `USE_CATALOG` | `USE_SCHEMA`, `SELECT`, `APPLY_TAG` | None | None | None |
| `data-analysts` | `USE_CATALOG` | `USE_SCHEMA`, `SELECT` | None | None | Viewer (by object ID) |
| Fabric reader service principal | `USE_CATALOG` | `USE_SCHEMA`, `SELECT`, `EXTERNAL_USE_SCHEMA` on shared schemas | None | `Storage Blob Data Reader` | None |
| Fabric workspace identity | None | None | None | None | Created with the workspace |

`databricks_grants` is authoritative. A privilege granted by hand on a securable this stack manages is revoked on the next apply.

## Classification policy

Every column carries one of four levels. The contract validator and Terraform both enforce the one rule that matters for the bridge.

| Level | Meaning | Can be shared through a shortcut |
| --- | --- | --- |
| `public` | Safe to publish | Yes |
| `internal` | Any employee with a business need | Yes |
| `confidential` | Named groups only, includes pseudonymised personal data | Yes, the Fabric workspace roles become the boundary |
| `restricted` | Direct identifiers, data that needs masking | No |

The reason is mechanical. A shortcut reads the Delta files with a storage identity, so Unity Catalog row filters and column masks never run on the Fabric side. A restricted column would reach every Fabric user with read access to the lakehouse. `dctl validate` refuses such a contract, and the `fabric_shortcut` resource carries a precondition that refuses it again at plan time.

A column flagged `pii: true` must be `confidential` or `restricted`. The DDL tags it `pii = true` in Unity Catalog and the semantic model annotates it, so the flag follows the data into Power BI.

## Secrets

The stack holds one secret, the client secret of the Fabric reader, which the Fabric connection needs. It enters through `fabric_reader_secret`, an ephemeral variable, and reaches the connection through the write-only argument `client_secret_wo`. It never appears in the plan or the state. To rotate it, export the new value and increase `fabric_reader_secret_version` by one.

Every provider authenticates from the environment, with the Azure CLI on a workstation or OIDC federation in a pipeline.

## Ownership

| Artefact | Changed by | Reviewed by |
| --- | --- | --- |
| A contract | The domain team | The steward group and the platform team |
| Generated files | Nobody by hand, `dctl generate` | CI, `generate --check` |
| Terraform | The platform team | The platform team, plan attached to the pull request |
| Workspace roles in Fabric | The platform team, through `fabric_workspace_roles` | The platform team |
