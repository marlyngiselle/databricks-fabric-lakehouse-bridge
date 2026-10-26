variable "environment" {
  description = "Short environment name. Drives the catalog and workspace names."
  type        = string

  validation {
    condition     = contains(["dev", "test", "prod"], var.environment)
    error_message = "environment must be dev, test or prod."
  }
}

variable "databricks_host" {
  description = "URL of the Azure Databricks workspace that writes the gold layer."
  type        = string

  validation {
    condition     = can(regex("^https://adb-[0-9]+\\.[0-9]+\\.azuredatabricks\\.net/?$", var.databricks_host))
    error_message = "databricks_host must look like https://adb-<workspace id>.<n>.azuredatabricks.net."
  }
}

variable "catalog_prefix" {
  description = "Prefix of the gold catalog. The environment is appended, for example gold_dev."
  type        = string
  default     = "gold"

  validation {
    condition     = can(regex("^[a-z][a-z0-9_]{1,30}$", var.catalog_prefix))
    error_message = "catalog_prefix must be lower case letters, digits and underscores, starting with a letter."
  }
}

variable "access_connector_id" {
  description = "Resource ID of the Azure Databricks access connector whose managed identity reads and writes the gold containers."
  type        = string

  validation {
    condition     = can(regex("^/subscriptions/[0-9a-f-]{36}/resourceGroups/[^/]+/providers/Microsoft\\.Databricks/accessConnectors/[^/]+$", var.access_connector_id))
    error_message = "access_connector_id must be the full resource ID of a Microsoft.Databricks/accessConnectors resource."
  }
}

variable "storage_account_id" {
  description = "Resource ID of the ADLS Gen2 account that holds the gold containers."
  type        = string

  validation {
    condition     = can(regex("^/subscriptions/[0-9a-f-]{36}/resourceGroups/[^/]+/providers/Microsoft\\.Storage/storageAccounts/[a-z0-9]{3,24}$", var.storage_account_id))
    error_message = "storage_account_id must be the full resource ID of a Microsoft.Storage/storageAccounts resource."
  }
}

variable "internal_container" {
  description = "Container for gold tables that stay inside Databricks. It doubles as the catalog managed storage."
  type        = string
  default     = "gold"

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$", var.internal_container))
    error_message = "internal_container must be a valid storage container name."
  }
}

variable "shared_container" {
  description = "Container for gold tables exposed to Fabric. The only container the Fabric identity can read."
  type        = string
  default     = "gold-shared"

  validation {
    condition     = can(regex("^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$", var.shared_container))
    error_message = "shared_container must be a valid storage container name."
  }
}

variable "platform_admins_group" {
  description = "Account group that owns the catalog, the external locations and the Fabric workspace."
  type        = string
  default     = "platform-admins"
}

variable "pipeline_principal" {
  description = "Application ID of the service principal that runs the gold pipelines and writes the tables."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.pipeline_principal))
    error_message = "pipeline_principal must be an application (client) ID in GUID form."
  }
}

variable "analysts_group" {
  description = "Account group of Databricks SQL users who read the gold layer."
  type        = string
  default     = "data-analysts"
}

variable "entra_tenant_id" {
  description = "Microsoft Entra tenant of the Fabric reader service principal."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.entra_tenant_id))
    error_message = "entra_tenant_id must be a GUID."
  }
}

variable "fabric_reader" {
  description = "Entra service principal Fabric uses to read the shared container and, when mirroring is enabled, Unity Catalog."
  type = object({
    application_id = string
    object_id      = string
  })

  validation {
    condition = alltrue([
      for v in values(var.fabric_reader) : can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", v))
    ])
    error_message = "fabric_reader.application_id and fabric_reader.object_id must be GUIDs."
  }
}

variable "fabric_reader_secret" {
  description = "Client secret of the Fabric reader. Ephemeral and write-only: it reaches the Fabric connection and nothing else."
  type        = string
  sensitive   = true
  ephemeral   = true
}

variable "fabric_reader_secret_version" {
  description = "Increase by one to push a rotated fabric_reader_secret to the Fabric connection."
  type        = number
  default     = 1

  validation {
    condition     = var.fabric_reader_secret_version >= 1 && floor(var.fabric_reader_secret_version) == var.fabric_reader_secret_version
    error_message = "fabric_reader_secret_version must be a positive whole number."
  }
}

variable "fabric_capacity_id" {
  description = "ID of the Fabric capacity the workspace runs on. Direct Lake needs an F or P capacity."
  type        = string

  validation {
    condition     = can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", var.fabric_capacity_id))
    error_message = "fabric_capacity_id must be a GUID."
  }
}

variable "fabric_workspace_roles" {
  description = "Entra principals and their role on the Fabric workspace. Prefer groups over users."
  type = list(object({
    principal_id   = string
    principal_type = string
    role           = string
  }))
  default = []

  validation {
    condition = alltrue([
      for r in var.fabric_workspace_roles : contains(["Admin", "Member", "Contributor", "Viewer"], r.role)
    ])
    error_message = "role must be Admin, Member, Contributor or Viewer."
  }

  validation {
    condition = alltrue([
      for r in var.fabric_workspace_roles : contains(["Group", "ServicePrincipal", "ServicePrincipalProfile", "User"], r.principal_type)
    ])
    error_message = "principal_type must be Group, ServicePrincipal, ServicePrincipalProfile or User."
  }

  validation {
    condition = alltrue([
      for r in var.fabric_workspace_roles : can(regex("^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", r.principal_id))
    ])
    error_message = "principal_id must be the object ID of the principal, in GUID form."
  }
}

variable "deploy_semantic_model" {
  description = "Deploy the Direct Lake semantic model generated by dctl. Off until the shortcuts hold data."
  type        = bool
  default     = false
}
