output "catalog_name" {
  description = "Unity Catalog catalog that holds the gold layer."
  value       = databricks_catalog.gold.name
}

output "schemas" {
  description = "Gold schemas, one per domain, with their owner group."
  value       = { for k, s in databricks_schema.domain : k => s.owner }
}

output "external_locations" {
  description = "Storage URLs of the internal and the shared gold locations."
  value = {
    internal = databricks_external_location.internal.url
    shared   = databricks_external_location.shared.url
  }
}

output "fabric_reader_principal" {
  description = "Application ID the grants and the storage role assignment refer to."
  value       = databricks_service_principal.fabric_reader.application_id
}

output "fabric_workspace_id" {
  description = "Fabric workspace that consumes the gold layer."
  value       = fabric_workspace.bridge.id
}

output "fabric_workspace_identity" {
  description = "Application ID of the workspace identity, for trusted workspace access if the storage firewall is closed."
  value       = fabric_workspace.bridge.identity.application_id
}

output "lakehouse_id" {
  description = "Schema-enabled lakehouse that holds the shortcuts."
  value       = fabric_lakehouse.gold.id
}

output "sql_endpoint" {
  description = "SQL analytics endpoint of the lakehouse, used by the Direct Lake model."
  value       = fabric_lakehouse.gold.properties.sql_endpoint_properties.connection_string
}

output "shortcuts" {
  description = "OneLake path of every shortcut, keyed by contract id."
  value       = { for k, s in fabric_shortcut.gold : k => "${s.path}/${s.name}" }
}

output "semantic_model_id" {
  description = "ID of the Direct Lake semantic model, null until deploy_semantic_model is true."
  value       = one(fabric_semantic_model.gold[*].id)
}
