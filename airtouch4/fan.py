"""AirTouch 4 component to control non-ITC zones as fans."""

import logging
from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the Airtouch 4 fan entities."""
    coordinator = config_entry.runtime_data
    info = coordinator.data

    fan_entities = [
        AirtouchFan(coordinator, group["group_number"], info)
        for group in info["groups"]
        if coordinator.airtouch.GetGroupByGroupNumber(
            group["group_number"]
        ).ControlMethod
        == "PercentageControl"
    ]

    if fan_entities:
        async_add_entities(fan_entities)


class AirtouchFan(CoordinatorEntity, FanEntity):
    """Representation of an AirTouch 4 non-ITC zone as a fan."""

    _attr_has_entity_name = True
    _attr_supported_features = FanEntityFeature.SET_SPEED | FanEntityFeature.TURN_ON | FanEntityFeature.TURN_OFF

    def __init__(self, coordinator, group_number, info):
        """Initialize the fan entity."""
        super().__init__(coordinator)
        self._group_number = group_number
        self._airtouch = coordinator.airtouch
        self._unit = self._airtouch.GetGroupByGroupNumber(group_number)
        self._attr_unique_id = f"fan_{group_number}"
        self._attr_name = self._unit.GroupName
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"fan_{group_number}")},
            manufacturer="Airtouch",
            model="Airtouch 4",
            name=self._unit.GroupName,
        )

    @callback
    def _handle_coordinator_update(self):
        """Fetch updated data from Home Assistant's coordinator."""
        all_groups = self.coordinator.data["groups"]

        # Validate group exists
        if self._group_number >= len(all_groups):
            _LOGGER.error(
                "_handle_coordinator_update: Group %s is out of range (Total groups: %s)",
                self._group_number,
                len(all_groups),
            )
            return  # Prevent crash

        fresh_unit = all_groups[self._group_number]

        power_state = fresh_unit.get("power_state", "Unknown")
        if power_state == "Unknown":
            _LOGGER.error("PowerState missing for Group %s. Data: %s", self._group_number, fresh_unit)

        # Set is_on correctly
        is_on = power_state == "On"

        _LOGGER.debug(
            "_handle_coordinator_update: Group %s, PowerState=%s, OpenPercent=%s, is_on=%s",
            self._group_number,
            power_state,
            fresh_unit.get("open_percent", "Unknown"),
            is_on
        )

        self._unit = {
            "group_number": fresh_unit["group_number"],
            "group_name": fresh_unit["group_name"],
            "power_state": fresh_unit.get("power_state", "Off"),
            "open_percent": fresh_unit.get("open_percent", 0),
        }
        self.async_write_ha_state()

    @property
    def is_on(self):
        """Return True if fan is on."""
        if not isinstance(self._unit, dict):
            return False
        return self._unit.get("power_state", "Off") == "On"

    @property
    def percentage(self):
        """Return the fan speed as a percentage."""
        return self._unit.get("open_percent", 0)  # Use dictionary key safely

    @property
    def percentage_step(self):
        """Force fan speed to 5% increments."""
        return 5

    async def async_turn_on(self, percentage=None, preset_mode=None, **kwargs):
        """Turn the fan on with optional speed."""
        _LOGGER.debug(
            "async_turn_on called with percentage=%s, preset_mode=%s, kwargs=%s",
            percentage,
            preset_mode,
            kwargs
        )

        await self._airtouch.TurnGroupOn(self._group_number)

        if percentage is not None:
            await self.async_set_percentage(percentage)

    async def async_turn_off(self, **kwargs):
        """Turn the fan off."""
        await self._airtouch.TurnGroupOff(self._group_number)

    async def async_set_percentage(self, percentage):
        """Set fan speed as a percentage, turning off if 0% is selected."""
        if percentage == 0:
            _LOGGER.debug("Turning off fan %s due to 0% speed", self._group_number)
            await self.async_turn_off()
        else:
            _LOGGER.debug(
                "Setting fan speed of %s to %s", self._group_number, percentage
            )
            await self._airtouch.SetGroupToPercentage(
                self._group_number, int(percentage)
            )

        self.async_write_ha_state()
