"""AirTouch4 manual damper cover entities."""

import logging

from homeassistant.components.cover import (
    CoverDeviceClass,
    CoverEntity,
    CoverEntityFeature,
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
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create a ManualDamperCover for every zone except MODE_NONITC_FAN zones."""
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator: AirtouchDataUpdateCoordinator = data["coordinator"]

    setup_mode = entry.options.get("setup_mode") or entry.data.get("setup_mode", "default")
    if setup_mode == MODE_NONITC_FAN:
        _LOGGER.debug("cover.py: MODE_NONITC_FAN — no manual damper covers created")
        return

    entities = [
        ManualDamperCover(coordinator, group_dict["group_number"])
        for group_dict in coordinator.data.get("groups", [])
    ]

    if entities:
        _LOGGER.debug("Adding manual damper cover entities: %s", entities)
        async_add_entities(entities)


class ManualDamperCover(CoordinatorEntity, CoverEntity):
    """Cover entity representing a zone's damper position.

    Uses CoverDeviceClass.DAMPER so HA renders it with damper semantics.
    The SET_POSITION feature enables the native tile card cover-position
    inline slider — no custom card needed.

    Most useful when the companion ManualDamperSwitch is ON, which pauses
    the automatic fan-speed adjustment loop so this entity has exclusive
    control over damper position.
    """

    _attr_device_class = CoverDeviceClass.DAMPER
    _attr_supported_features = (
        CoverEntityFeature.SET_POSITION
        | CoverEntityFeature.OPEN
        | CoverEntityFeature.CLOSE
    )

    def __init__(self, coordinator: AirtouchDataUpdateCoordinator, group_number: int):
        super().__init__(coordinator)
        self._group_number = group_number
        self._airtouch = coordinator.airtouch

        group_obj = coordinator.airtouch.GetGroupByGroupNumber(group_number)
        zone_name = getattr(group_obj, "GroupName", f"Zone {group_number}")
        self._attr_name = f"{zone_name} Damper"
        self._attr_unique_id = f"manual_damper_cover_{group_number}"

    @callback
    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()

    @property
    def current_cover_position(self) -> int:
        """Return current damper open percentage (0 = closed, 100 = fully open)."""
        groups = self.coordinator.data.get("groups", [])
        group_data = next(
            (g for g in groups if g["group_number"] == self._group_number), {}
        )
        return group_data.get("open_percent", 0)

    @property
    def is_closed(self) -> bool:
        return self.current_cover_position == 0

    async def async_set_cover_position(self, **kwargs) -> None:
        position = int(kwargs.get("position", 0))
        _LOGGER.debug(
            "ManualDamperCover: setting group %s to %s%%",
            self._group_number,
            position,
        )
        await self._airtouch.SetGroupToPercentage(self._group_number, position)
        self.async_write_ha_state()

    async def async_open_cover(self, **kwargs) -> None:
        await self._airtouch.SetGroupToPercentage(self._group_number, 100)
        self.async_write_ha_state()

    async def async_close_cover(self, **kwargs) -> None:
        await self._airtouch.SetGroupToPercentage(self._group_number, 0)
        self.async_write_ha_state()
