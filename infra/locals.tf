locals {
  # The contracts are the single source: schemas, owners, shortcuts and tags all derive from them.
  contract_files = fileset("${path.module}/../contracts", "*.yaml")
  contracts = {
    for f in local.contract_files : trimsuffix(f, ".yaml") => yamldecode(file("${path.module}/../contracts/${f}"))
  }

  catalog_name = "${var.catalog_prefix}_${var.environment}"

  # One schema per domain. Every contract in a schema must name the same owner group.
  schemas = {
    for s in distinct([for c in local.contracts : c.table.schema]) : s => {
      owners  = distinct([for c in local.contracts : c.owner.group if c.table.schema == s])
      domains = distinct([for c in local.contracts : c.domain if c.table.schema == s])
      shared  = anytrue([for c in local.contracts : c.consumers.fabric.exposure == "shortcut" if c.table.schema == s])
    }
  }

  shared_tables = {
    for id, c in local.contracts : id => {
      schema          = c.table.schema
      name            = c.table.name
      classifications = [for col in c.columns : col.classification]
    } if c.consumers.fabric.exposure == "shortcut"
  }

  storage = {
    subscription_id = split("/", var.storage_account_id)[2]
    account_name    = element(split("/", var.storage_account_id), length(split("/", var.storage_account_id)) - 1)
  }
  dfs_endpoint = "https://${local.storage.account_name}.dfs.core.windows.net"
  internal_url = "abfss://${var.internal_container}@${local.storage.account_name}.dfs.core.windows.net/"
  shared_url   = "abfss://${var.shared_container}@${local.storage.account_name}.dfs.core.windows.net/"

  semantic_model_dir = "${path.module}/../generated/semantic_model"
}
