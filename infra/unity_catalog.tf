# Unity Catalog side: Databricks produces the gold layer.

resource "databricks_storage_credential" "gold" {
  name    = "gold-${var.environment}"
  comment = "Access connector managed identity for the gold containers. Managed by Terraform."
  owner   = var.platform_admins_group

  azure_managed_identity {
    access_connector_id = var.access_connector_id
  }
}

resource "databricks_external_location" "internal" {
  name            = "gold-internal-${var.environment}"
  url             = local.internal_url
  credential_name = databricks_storage_credential.gold.name
  owner           = var.platform_admins_group
  comment         = "Gold tables that stay inside Databricks, and the catalog managed storage."
}

resource "databricks_external_location" "shared" {
  name            = "gold-shared-${var.environment}"
  url             = local.shared_url
  credential_name = databricks_storage_credential.gold.name
  owner           = var.platform_admins_group
  comment         = "Gold tables exposed to Fabric through OneLake shortcuts. Paths are set by the contracts."
}

resource "databricks_catalog" "gold" {
  name         = local.catalog_name
  comment      = "Gold data products governed by data contracts. Databricks writes, Fabric reads."
  owner        = var.platform_admins_group
  storage_root = databricks_external_location.internal.url

  properties = {
    layer       = "gold"
    environment = var.environment
    managed_by  = "terraform"
  }
}

resource "databricks_schema" "domain" {
  for_each = local.schemas

  catalog_name = databricks_catalog.gold.name
  name         = each.key
  owner        = one(each.value.owners)
  comment      = "Gold tables of the ${join(", ", each.value.domains)} domain. Columns, keys and SLAs live in contracts/."

  properties = {
    domain          = join(",", each.value.domains)
    fabric_exposure = each.value.shared ? "shortcut" : "none"
  }

  lifecycle {
    precondition {
      condition     = length(each.value.owners) == 1
      error_message = "Every contract in schema ${each.key} must name the same owner group, found: ${join(", ", each.value.owners)}."
    }
  }
}

resource "databricks_entity_tag_assignment" "catalog_layer" {
  entity_type = "catalogs"
  entity_name = databricks_catalog.gold.name
  tag_key     = "data_layer"
  tag_value   = "gold"
}

resource "databricks_entity_tag_assignment" "schema_exposure" {
  for_each = databricks_schema.domain

  entity_type = "schemas"
  entity_name = each.value.id
  tag_key     = "fabric_exposure"
  tag_value   = local.schemas[each.key].shared ? "shortcut" : "none"
}
