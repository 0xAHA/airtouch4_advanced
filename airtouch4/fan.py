"""AirTouch 4 component to control non-ITC zones as fans."""

import logging
from homeassistant.components.fan import (
    FanEntity,
    FanEntityFeature,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MODE_NONITC_FAN
from .coordinator import AirtouchDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback
) -> None:
    """
    Set up the Airtouch 4 fan entities if user chooses non-ITC zones as fans.
    """
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AirtouchDataUpdateCoordinator = data["coordinator"]

    setup_mode = entry.data.get("setup_mode", "default")
    if setup_mode != MODE_NONITC_FAN:
        _LOGGER.debug("No fan setup because setup_mode=%s", setup_mode)
        return

    info = coordinator.data  # e.g. {"acs": [...], "groups": [...]}
    fan_entities = []

    for group_dict in info.get("groups", []):
        # Check if this group is PercentageControl
        control_method = group_dict.get("control_method", "")
        group_number = group_dict["group_number"]
        if control_method == "PercentageControl":
            fan_entities.append(AirtouchFan(coordinator, group_number))

    if fan_entities:
        _LOGGER.debug("Adding fan entities: %s", fan_entities)
        async_add_entities(fan_entities)


class AirtouchFan(CoordinatorEntity, FanEntity):
    """
    Representation of a non-ITC zone as a fan,
    reading the 'open_percent' and 'power_state' from coordinator.data["groups"].
    """

    _attr_supported_features = (
        FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
        | FanEntityFeature.SET_SPEED
    )

    def __init__(self, coordinator: AirtouchDataUpdateCoordinator, group_number: int):
        super().__init__(coordinator)
        self._group_number = group_number
        self._airtouch = coordinator.airtouch

        # We'll store the coordinator's dict data for easy access.
        self._dict_unit = {}

        # Use the library to get the default name, then slugify it for a friendly entity_id.
        group_obj = self._airtouch.GetGroupByGroupNumber(group_number)
        default_name = getattr(group_obj, "GroupName", f"Zone {group_number}")
        from homeassistant.util import slugify  # import here to generate a safe string
        slug_name = slugify(default_name) or f"zone_{group_number}"

        self._attr_name = default_name
        self.entity_id = f"fan.{slug_name}"
        self._attr_unique_id = f"fan_{group_number}"

    @callback
    def _handle_coordinator_update(self):
        """
        Pull fresh dictionary data for this group from coordinator.data["groups"].
        Then store it in self._dict_unit so is_on/percentage reflect the same values.
        """
        all_groups = self.coordinator.data.get("groups", [])
        fresh_unit = next(
            (g for g in all_groups if g["group_number"] == self._group_number),
            None
        )
        if not fresh_unit:
            _LOGGER.warning("Fan group %s not found in coordinator data", self._group_number)
            return

        self._dict_unit = fresh_unit

        # Update the friendly name from the data if available
        self._attr_name = fresh_unit.get("group_name", self._attr_name)

        _LOGGER.debug(
            "Fan group %s updated: power_state=%s, open_percent=%s, name=%s",
            self._group_number,
            fresh_unit.get("power_state"),
            fresh_unit.get("open_percent"),
            fresh_unit.get("group_name"),
        )
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return True if fan is on (power_state == 'On')."""
        return self._dict_unit.get("power_state") == "On"

    @property
    def percentage(self) -> int | None:
        """Return the current fan speed as a percentage (open_percent)."""
        return self._dict_unit.get("open_percent", 0)

    @property
    def percentage_step(self) -> int:
        """Return a 5% increment."""
        return 5

    async def async_turn_on(self, percentage: int | None = None, preset_mode: str | None = None, **kwargs):
        """Turn the fan on, optionally with a specific percentage."""
        _LOGGER.debug(
            "Turning ON fan zone %s, requested speed=%s%%, preset_mode=%s",
            self._group_number,
            percentage,
            preset_mode,
        )
        await self._airtouch.TurnGroupOn(self._group_number)
        if percentage is not None:
            await self.async_set_percentage(percentage)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs):
        """Turn the fan off."""
        _LOGGER.debug("Turning OFF fan zone %s", self._group_number)
        await self._airtouch.TurnGroupOff(self._group_number)
        self.async_write_ha_state()

    async def async_set_percentage(self, percentage: int):
        """Set fan speed as a percentage, or turn off if 0%."""
        if percentage == 0:
            _LOGGER.debug("Requested 0%% => turning OFF fan zone %s", self._group_number)
            await self.async_turn_off()
        else:
            _LOGGER.debug("Setting fan zone %s to %s%%", self._group_number, percentage)
            await self._airtouch.SetGroupToPercentage(self._group_number, int(percentage))
        self.async_write_ha_state()
