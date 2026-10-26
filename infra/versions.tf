terraform {
  # 1.11 brings ephemeral variables and write-only arguments, so the client secret
  # of the Fabric connection never lands in the plan or the state.
  required_version = ">= 1.11"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.40"
    }
    databricks = {
      source  = "databricks/databricks"
      version = "~> 1.90"
    }
    fabric = {
      source  = "microsoft/fabric"
      version = "~> 1.14"
    }
  }
}
