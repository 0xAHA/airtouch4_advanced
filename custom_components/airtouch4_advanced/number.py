"""AirTouch4 manual damper position number entities."""

import logging

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODE_NONITC_FAN
from .coordinator import AirtouchDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a ManualDamperNumber for every zone except MODE_NONITC_FAN zones."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AirtouchDataUpdateCoordinator = data["coordinator"]

    setup_mode = entry.options.get("setup_mode") or entry.data.get("setup_mode", "default")
    if setup_mode == MODE_NONITC_FAN:
        _LOGGER.debug("number.py: MODE_NONITC_FAN — no manual damper numbers created")
        return

    entities = [
        ManualDamperNumber(coordinator, group_dict["group_number"])
        for group_dict in coordinator.data.get("groups", [])
    ]

    if entities:
        _LOGGER.debug("Adding manual damper number entities: %s", entities)
        async_add_entities(entities)


class ManualDamperNumber(CoordinatorEntity, NumberEntity):
    """Number entity for direct damper percentage control.

    Reads the live open_percent from the coordinator and writes via
    SetGroupToPercentage(). Most useful when the companion ManualDamperSwitch
    is ON, which pauses the automatic fan-speed adjustment loop.
    """

    _attr_native_min_value = 0.0
    _attr_native_max_value = 100.0
    _attr_native_step = 5.0
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_mode = NumberMode.SLIDER

    def __init__(self, coordinator: AirtouchDataUpdateCoordinator, group_number: int):
        super().__init__(coordinator)
        self._group_number = group_number
        self._airtouch = coordinator.airtouch

        group_obj = coordinator.airtouch.GetGroupByGroupNumber(group_number)
        zone_name = getattr(group_obj, "GroupName", f"Zone {group_number}")
        self._attr_name = f"{zone_name} Damper"
        self._attr_unique_id = f"manual_damper_number_{group_number}"

    @callback
    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()

    @property
    def native_value(self) -> float:
        groups = self.coordinator.data.get("groups", [])
        group_data = next(
            (g for g in groups if g["group_number"] == self._group_number), {}
        )
        return float(group_data.get("open_percent", 0))

    async def async_set_native_value(self, value: float) -> None:
        pct = int(value)
        _LOGGER.debug(
            "ManualDamperNumber: setting group %s damper to %s%%",
            self._group_number,
            pct,
        )
        await self._airtouch.SetGroupToPercentage(self._group_number, pct)
        self.async_write_ha_state()
