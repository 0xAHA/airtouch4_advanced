import asyncio
import logging
import socket
import re
from typing import Any, Dict, List

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers import selector

from airtouch4pyapi import AirTouch, AirTouchStatus
from .const import DOMAIN, MODE_DEFAULT, MODE_NONITC_FAN, MODE_NONITC_CLIMATE

_LOGGER = logging.getLogger(__name__)


class AirtouchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AirTouch4 with automatic discovery."""

    VERSION = 2

    def __init__(self):
        self._discovered_ips: List[str] = []
        self._current_ip_index = 0
        self._host = None
        self._discovered_zones = []
        self._non_itc_zones = []
        self._setup_mode = MODE_DEFAULT
        self._temp_sensors: Dict[int, str] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return an options flow if needed (not implemented here)."""
        return None

    async def async_discover_devices(self) -> List[str]:
        """Discover all available AirTouch4 devices on the network."""
        broadcast_message = b"HF-A11ASSISTHREAD"
        broadcast_port = 49004

        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("", broadcast_port))
        sock.settimeout(3)

        discovered_devices = []

        try:
            sock.sendto(broadcast_message, ("<broadcast>", broadcast_port))
            _LOGGER.debug("Broadcast message sent, waiting for response...")

            while True:
                try:
                    data, addr = sock.recvfrom(1024)
                    decoded_data = data.decode("utf-8", errors="ignore")
                    match = re.search(
                        r"(\d+\.\d+\.\d+\.\d+),([0-9A-Fa-f:]+),AirTouch4,(\d+)",
                        decoded_data,
                    )

                    if match:
                        ip_address, _, _ = match.groups()
                        if ip_address not in discovered_devices:
                            _LOGGER.info(
                                f"Discovered AirTouch 4 Device at {ip_address}"
                            )
                            discovered_devices.append(ip_address)
                except socket.timeout:
                    break
        except Exception as e:
            _LOGGER.error(f"Error during discovery: {e}")
        finally:
            sock.close()

        return discovered_devices

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        """First step: Discover devices and iterate over each one."""
        _LOGGER.debug("Starting discovery process...")
        self._discovered_ips = await self.async_discover_devices()

        if not self._discovered_ips:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
                errors={"base": "no_devices_found"},
            )

        self._current_ip_index = 0
        self._host = self._discovered_ips[self._current_ip_index]
        return await self.async_step_validate_device()

    async def async_step_validate_device(
        self, user_input: dict[str, Any] | None = None
    ):
        """Validate connection to the current AirTouch4 device."""
        errors = {}

        try:
            _LOGGER.debug("Validating AirTouch device at %s", self._host)
            airtouch = AirTouch(self._host)
            await airtouch.UpdateInfo()

            if airtouch.Status != AirTouchStatus.OK:
                errors["base"] = "cannot_connect"
            else:
                self._discovered_zones = airtouch.GetGroups()
                self._non_itc_zones = [
                    z
                    for z in self._discovered_zones
                    if z.ControlMethod == "PercentageControl"
                ]
                return await self.async_step_zone_mode()
        except Exception as e:
            _LOGGER.exception("Error validating device: %s", e)
            errors["base"] = "cannot_connect"

        return self.async_show_form(
            step_id="validate_device",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"ip": self._host},
        )

    async def async_step_zone_mode(self, user_input: dict[str, Any] | None = None):
        """Step where the user selects zone mode."""
        errors = {}

        if user_input is not None:
            self._setup_mode = user_input["setup_mode"]

            if self._setup_mode == MODE_NONITC_CLIMATE and self._non_itc_zones:
                return await self.async_step_nonitc_sensors()

            return await self.async_step_finish()

        return self.async_show_form(
            step_id="zone_mode",
            data_schema=vol.Schema(
                {
                    vol.Required(
                        "setup_mode", default=MODE_DEFAULT
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "label": "Default Mode (All zones as climate)",
                                    "value": MODE_DEFAULT,
                                },
                                {
                                    "label": "Non-ITC Zones as Fans",
                                    "value": MODE_NONITC_FAN,
                                },
                                {
                                    "label": "Non-ITC Zones as Climate (Requires Temperature Sensor)",
                                    "value": MODE_NONITC_CLIMATE,
                                },
                            ],
                            multiple=False,
                            translation_key="setup_mode",
                        )
                    )
                }
            ),
            errors=errors,
            description_placeholders={
                "ip": self._host,
                "mode_description": "Choose how your zones should be handled.",
            },
        )

    async def async_step_nonitc_sensors(self, user_input: dict[str, Any] | None = None):
        """Prompt user for a temperature sensor for each non-ITC zone with proper translations."""
        errors = {}

        if user_input is not None:
            try:
                for z in self._non_itc_zones:
                    safe_name = z.GroupName.lower().replace(" ", "_").replace("-", "_")
                    key = f"{safe_name}_sensor"
                    if key not in user_input or not user_input[key]:
                        errors["base"] = "missing_sensor"
                        break

                if not errors:
                    for z in self._non_itc_zones:
                        safe_name = (
                            z.GroupName.lower().replace(" ", "_").replace("-", "_")
                        )
                        key = f"{safe_name}_sensor"
                        self._temp_sensors[z.GroupNumber] = user_input[key]
                    return await self.async_step_finish()

            except Exception as e:
                _LOGGER.exception("Error in nonitc_sensors step: %s", e)
                errors["base"] = "unknown"

        # Define form schema dynamically
        schema_dict = {}
        placeholders = {}
        for z in self._non_itc_zones:
            safe_name = z.GroupName.lower().replace(" ", "_").replace("-", "_")
            key = f"{safe_name}_sensor"

            # Use a dynamically generated user-friendly name
            friendly_label = f"Select sensor for {z.GroupName}"

            schema_dict[vol.Required(key)] = selector.selector(
                {
                    "entity": {
                        "domain": ["sensor"],
                        "device_class": ["temperature"],
                        "multiple": False,
                    }
                }
            )
            placeholders[key] = friendly_label  # Store placeholders for UI descriptions

        return self.async_show_form(
            step_id="nonitc_sensors",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders=placeholders,  # This applies friendly field names
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None):
        """Final step: Create config entry and move to the next device if any remain."""
        _LOGGER.info(f"Creating config entry for {self._host}")

        # Create the configuration entry for the current device
        entry = self.async_create_entry(
            title=f"AirTouch4 ({self._host})",
            data={
                CONF_HOST: self._host,
                "setup_mode": self._setup_mode,
                "nonitc_sensors": self._temp_sensors,
            },
        )

        # Move to next device if available
        self._current_ip_index += 1
        if self._current_ip_index < len(self._discovered_ips):
            self._host = self._discovered_ips[self._current_ip_index]
            return await self.async_step_validate_device()

        # If all devices are configured, end the flow
        return entry
