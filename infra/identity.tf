# The Fabric reader is one Entra service principal with two narrow rights:
#   1. read the shared container in Azure Storage, which is what a OneLake shortcut uses;
#   2. read the shared schemas in Unity Catalog, which a mirrored catalog would use.
# It cannot read the internal container and it cannot write anywhere.

resource "databricks_service_principal" "fabric_reader" {
  application_id        = var.fabric_reader.application_id
  display_name          = "fabric-reader-${var.environment}"
  workspace_access      = false
  databricks_sql_access = false
  allow_cluster_create  = false
}

resource "azurerm_role_assignment" "fabric_reader_shared_container" {
  scope                = "${var.storage_account_id}/blobServices/default/containers/${var.shared_container}"
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = var.fabric_reader.object_id
  principal_type       = "ServicePrincipal"
  description          = "Fabric reads the gold tables exposed by contract, through OneLake shortcuts."
}
