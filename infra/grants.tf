# databricks_grants is authoritative: anything granted by hand on these securables
# is revoked on the next apply. Changes go through code review.

locals {
  domain_owners   = distinct(flatten([for s in local.schemas : s.owners]))
  domain_stewards = distinct([for c in local.contracts : c.owner.steward])
}

resource "databricks_grants" "storage_credential" {
  storage_credential = databricks_storage_credential.gold.id

  grant {
    principal  = var.platform_admins_group
    privileges = ["ALL_PRIVILEGES"]
  }
}

resource "databricks_grants" "external_locations" {
  for_each = {
    internal = databricks_external_location.internal.id
    shared   = databricks_external_location.shared.id
  }

  external_location = each.value

  grant {
    principal  = var.platform_admins_group
    privileges = ["ALL_PRIVILEGES"]
  }

  grant {
    principal  = var.pipeline_principal
    privileges = ["READ_FILES", "WRITE_FILES", "CREATE_EXTERNAL_TABLE"]
  }
}

resource "databricks_grants" "catalog" {
  catalog = databricks_catalog.gold.name

  grant {
    principal  = var.platform_admins_group
    privileges = ["ALL_PRIVILEGES"]
  }

  grant {
    principal  = var.pipeline_principal
    privileges = ["USE_CATALOG"]
  }

  grant {
    principal  = var.analysts_group
    privileges = ["USE_CATALOG"]
  }

  grant {
    principal  = databricks_service_principal.fabric_reader.application_id
    privileges = ["USE_CATALOG"]
  }

  dynamic "grant" {
    for_each = toset(concat(local.domain_owners, local.domain_stewards))
    content {
      principal  = grant.value
      privileges = ["USE_CATALOG"]
    }
  }
}

resource "databricks_grants" "schema" {
  for_each = databricks_schema.domain

  schema = each.value.id

  grant {
    principal  = var.pipeline_principal
    privileges = ["USE_SCHEMA", "CREATE_TABLE", "MODIFY", "SELECT"]
  }

  grant {
    principal  = var.analysts_group
    privileges = ["USE_SCHEMA", "SELECT"]
  }

  # EXTERNAL_USE_SCHEMA lets an engine outside Databricks read through Unity Catalog
  # credential vending. Only schemas with tables exposed by contract get it.
  dynamic "grant" {
    for_each = local.schemas[each.key].shared ? [databricks_service_principal.fabric_reader.application_id] : []
    content {
      principal  = grant.value
      privileges = ["USE_SCHEMA", "SELECT", "EXTERNAL_USE_SCHEMA"]
    }
  }

  dynamic "grant" {
    for_each = toset([for c in local.contracts : c.owner.steward if c.table.schema == each.key])
    content {
      principal  = grant.value
      privileges = ["USE_SCHEMA", "SELECT", "APPLY_TAG"]
    }
  }
}
