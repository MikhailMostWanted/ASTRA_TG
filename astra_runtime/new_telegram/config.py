from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class NewTelegramRuntimeConfig:
    enabled: bool
    session_path: Path
    device_name: str
    product_surfaces_enabled: bool = False

    @classmethod
    def from_settings(cls, settings) -> "NewTelegramRuntimeConfig":
        return cls(
            enabled=bool(settings.runtime_new_enabled),
            session_path=Path(settings.runtime_new_session_path).expanduser(),
            device_name=settings.runtime_new_device_name,
            product_surfaces_enabled=bool(settings.runtime_new_product_surfaces_enabled),
        )

    def to_payload(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "sessionPath": str(self.session_path),
            "deviceName": self.device_name,
            "productSurfacesEnabled": self.product_surfaces_enabled,
        }
