from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class NewTelegramRuntimeConfig:
    enabled: bool
    session_path: Path
    device_name: str
    asset_session_files: tuple[Path, ...] = ()
    api_id: int | None = None
    api_hash: str | None = None
    phone: str | None = None
    product_surfaces_enabled: bool = False

    @classmethod
    def from_settings(cls, settings) -> "NewTelegramRuntimeConfig":
        return cls(
            enabled=bool(settings.runtime_new_enabled),
            api_id=settings.runtime_new_api_id,
            api_hash=settings.runtime_new_api_hash,
            phone=settings.runtime_new_phone,
            session_path=settings.runtime_new_session_file,
            device_name=settings.runtime_new_device_name,
            asset_session_files=(
                settings.runtime_new_session_file,
                settings.fullaccess_session_file,
            ),
            product_surfaces_enabled=bool(settings.runtime_new_product_surfaces_enabled),
        )

    @property
    def api_credentials_configured(self) -> bool:
        return self.api_id is not None and bool(self.api_hash)

    @property
    def phone_configured(self) -> bool:
        return bool(self.phone and self.phone.strip())

    def to_payload(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "apiIdConfigured": self.api_id is not None,
            "apiHashConfigured": bool(self.api_hash),
            "phoneConfigured": self.phone_configured,
            "sessionPath": str(self.session_path),
            "deviceName": self.device_name,
            "assetSessionFiles": [str(path) for path in self.asset_session_files],
            "productSurfacesEnabled": self.product_surfaces_enabled,
        }
