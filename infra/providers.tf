# Every provider authenticates from the environment: Azure CLI or OIDC in CI.
# Nothing in this stack holds a long-lived credential except the write-only
# secret of the Fabric connection, which comes in through an ephemeral variable.

provider "azurerm" {
  features {}
  subscription_id     = local.storage.subscription_id
  storage_use_azuread = true
}

provider "databricks" {
  host = var.databricks_host
}

provider "fabric" {}
