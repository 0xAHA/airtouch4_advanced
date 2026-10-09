"""AirTouch4 manual damper override switch entities."""

import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODE_NONITC_FAN
from .coordinator import AirtouchDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a ManualDamperSwitch for every zone except MODE_NONITC_FAN zones."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AirtouchDataUpdateCoordinator = data["coordinator"]

    setup_mode = entry.options.get("setup_mode") or entry.data.get("setup_mode", "default")
    if setup_mode == MODE_NONITC_FAN:
        _LOGGER.debug("switch.py: MODE_NONITC_FAN — no manual damper switches created")
        return

    entities = [
        ManualDamperSwitch(coordinator, group_dict["group_number"])
        for group_dict in coordinator.data.get("groups", [])
    ]

    if entities:
        _LOGGER.debug("Adding manual damper switch entities: %s", entities)
        async_add_entities(entities)


class ManualDamperSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """Switch that pauses automatic damper control for a zone.

    When ON, async_adjust_fan_speed() skips this zone and
    AirtouchGroup.async_set_temperature() is a no-op, giving the
    ManualDamperNumber entity exclusive control over damper position.
    """

    def __init__(self, coordinator: AirtouchDataUpdateCoordinator, group_number: int):
        super().__init__(coordinator)
        self._group_number = group_number
        self._is_on = False

        group_obj = coordinator.airtouch.GetGroupByGroupNumber(group_number)
        zone_name = getattr(group_obj, "GroupName", f"Zone {group_number}")
        self._attr_name = f"{zone_name} Manual Damper"
        self._attr_unique_id = f"manual_damper_switch_{group_number}"

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        self._is_on = last is not None and last.state == STATE_ON
        self.hass.data.setdefault(DOMAIN, {}).setdefault("manual_overrides", {})[
            self._group_number
        ] = self._is_on
        _LOGGER.debug(
            "ManualDamperSwitch group %s restored to %s",
            self._group_number,
            self._is_on,
        )

    @callback
    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()

    @property
    def is_on(self) -> bool:
        return self._is_on

    async def async_turn_on(self, **kwargs) -> None:
        self._is_on = True
        self.hass.data[DOMAIN].setdefault("manual_overrides", {})[self._group_number] = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        self._is_on = False
        self.hass.data[DOMAIN].setdefault("manual_overrides", {})[self._group_number] = False
        self.async_write_ha_state()
