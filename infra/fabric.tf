# Fabric side: one workspace, one schema-enabled lakehouse, one shortcut per exposed table.

resource "fabric_workspace" "bridge" {
  display_name = "lakehouse-bridge-${var.environment}"
  description  = "Consumes the gold data products of ${local.catalog_name} through OneLake shortcuts. Managed by Terraform."
  capacity_id  = var.fabric_capacity_id

  identity = {
    type = "SystemAssigned"
  }
}

resource "fabric_workspace_role_assignment" "bridge" {
  for_each = { for r in var.fabric_workspace_roles : "${r.principal_type}-${r.principal_id}" => r }

  workspace_id = fabric_workspace.bridge.id
  role         = each.value.role

  principal = {
    id   = each.value.principal_id
    type = each.value.principal_type
  }
}

resource "fabric_lakehouse" "gold" {
  workspace_id = fabric_workspace.bridge.id
  display_name = local.catalog_name
  description  = "Shortcuts to the Delta tables Databricks writes. No data is copied."

  configuration = {
    enable_schemas = true
  }
}

resource "fabric_connection" "gold_shared" {
  display_name      = "adls-${local.storage.account_name}-${var.shared_container}"
  connectivity_type = "ShareableCloud"
  privacy_level     = "Organizational"

  connection_details = {
    type            = "AzureDataLakeStorage"
    creation_method = "AzureDataLakeStorage"
    parameters = [
      { name = "server", value = "${local.storage.account_name}.dfs.core.windows.net" },
      { name = "path", value = "/${var.shared_container}" },
    ]
  }

  credential_details = {
    credential_type       = "ServicePrincipal"
    connection_encryption = "NotEncrypted"
    single_sign_on_type   = "None"
    skip_test_connection  = false

    service_principal_credentials = {
      tenant_id                = var.entra_tenant_id
      client_id                = var.fabric_reader.application_id
      client_secret_wo         = var.fabric_reader_secret
      client_secret_wo_version = var.fabric_reader_secret_version
    }
  }

  depends_on = [azurerm_role_assignment.fabric_reader_shared_container]
}

resource "fabric_shortcut" "gold" {
  for_each = local.shared_tables

  workspace_id = fabric_workspace.bridge.id
  item_id      = fabric_lakehouse.gold.id
  path         = "Tables/${each.value.schema}"
  name         = each.value.name

  target = {
    adls_gen2 = {
      connection_id = fabric_connection.gold_shared.id
      location      = local.dfs_endpoint
      subpath       = "/${var.shared_container}/${each.value.schema}/${each.value.name}"
    }
  }

  lifecycle {
    # Second line of defence behind `dctl validate`: a shortcut reads files, not Unity
    # Catalog, so row filters and column masks do not apply on the Fabric side.
    precondition {
      condition     = !contains(each.value.classifications, "restricted")
      error_message = "Contract ${each.key} has restricted columns and cannot be exposed through a shortcut."
    }
  }
}

resource "fabric_semantic_model" "gold" {
  count = var.deploy_semantic_model ? 1 : 0

  workspace_id = fabric_workspace.bridge.id
  display_name = "${local.catalog_name}_model"
  description  = "Direct Lake model generated from the contracts by dctl."
  format       = "TMDL"

  definition = {
    for f in fileset(local.semantic_model_dir, "**") : f => {
      source = "${local.semantic_model_dir}/${f}"
      tokens = {
        SqlEndpoint   = fabric_lakehouse.gold.properties.sql_endpoint_properties.connection_string
        SqlEndpointId = fabric_lakehouse.gold.properties.sql_endpoint_properties.id
      }
    }
  }

  depends_on = [fabric_shortcut.gold]
}
