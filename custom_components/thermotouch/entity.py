"""Shared base entity."""
from __future__ import annotations

from homeassistant.helpers.device_info import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, MODEL


class ThermoTouchEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, entry):
        super().__init__(coordinator)
        self._entry = entry
        mac = coordinator.mac
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, mac)},
            connections={("mac", mac.lower())},
            name=entry.title,
            manufacturer=MANUFACTURER,
            model=MODEL,
        )

    @property
    def _state(self) -> dict:
        return self.coordinator.data or {}

    def _uid(self, suffix: str) -> str:
        return f"{self.coordinator.mac}_{suffix}"
