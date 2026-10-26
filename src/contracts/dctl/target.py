"""Where a contract lands: catalog, storage account and containers of one environment."""

from __future__ import annotations

from dataclasses import dataclass

from dctl.model import Contract


@dataclass(frozen=True)
class Target:
    catalog: str = "gold_dev"
    storage_account: str = "stbridgedev"
    internal_container: str = "gold"
    shared_container: str = "gold-shared"

    def container(self, contract: Contract) -> str:
        """Tables exposed to Fabric live in the shared container, the only one Fabric can read."""
        return self.shared_container if contract.exposure == "shortcut" else self.internal_container

    def location(self, contract: Contract) -> str:
        return (
            f"abfss://{self.container(contract)}@{self.storage_account}.dfs.core.windows.net/"
            f"{contract.schema}/{contract.table}"
        )

    def full_name(self, contract: Contract) -> str:
        return f"{self.catalog}.{contract.schema}.{contract.table}"
