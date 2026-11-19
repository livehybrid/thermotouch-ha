"""Sensors: room temperature and mode."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTemperature

from .const import DOMAIN, MODES
from .entity import ThermoTouchEntity


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        ThermoTouchRoom(coordinator, entry),
        ThermoTouchMode(coordinator, entry),
    ])


class ThermoTouchRoom(ThermoTouchEntity, SensorEntity):
    _attr_name = "Room temperature"
    _attr_device_class = SensorDeviceClass.TEMPERATURE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = UnitOfTemperature.CELSIUS

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = self._uid("room")

    @property
    def native_value(self):
        return self._state.get("room_c")


class ThermoTouchMode(ThermoTouchEntity, SensorEntity):
    _attr_name = "Mode"
    _attr_icon = "mdi:thermostat"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = MODES

    def __init__(self, coordinator, entry):
        super().__init__(coordinator, entry)
        self._attr_unique_id = self._uid("mode")

    @property
    def native_value(self):
        return self._state.get("mode")
