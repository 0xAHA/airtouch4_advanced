from typing import List, Dict, Any
import logging
import voluptuous as vol
import socket
import re
from homeassistant import config_entries
from homeassistant.const import CONF_HOST
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import DOMAIN, MODE_DEFAULT, MODE_NONITC_FAN, MODE_NONITC_CLIMATE
from .coordinator import AirtouchDataUpdateCoordinator

_LOGGER = logging.getLogger(__name__)

class AirtouchConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for AirTouch4 with automatic discovery."""

    VERSION = 2

    def __init__(self):
        self._discovered_ips = []  # List of discovered IPs
        self._current_ip_index = 0  # Index to track current IP
        self._host = None  # IP address of the currently configured device
        self._discovered_zones = []  # List of discovered zones
        self._non_itc_zones = []  # List of non-ITC zones
        self._setup_mode = MODE_DEFAULT  # Default setup mode
        self._temp_sensors = {}  # Dictionary to store temperature sensors
        self._zone_name_to_id = {}  # For mapping between zone names and IDs

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Return an options flow handler."""
        return AirtouchOptionsFlow(config_entry)

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
        errors = {}

        if user_input is not None:
            # Manual IP entry
            self._host = user_input[CONF_HOST]
            return await self.async_step_validate_device()

        _LOGGER.debug("Starting discovery process...")
        self._discovered_ips = await self.async_discover_devices()

        if not self._discovered_ips:
            return self.async_show_form(
                step_id="user",
                data_schema=vol.Schema({vol.Required(CONF_HOST): str}),
                errors=errors,
                description_placeholders={"error_info": "No devices found automatically. Enter IP manually."},
            )

        self._current_ip_index = 0
        self._host = self._discovered_ips[self._current_ip_index]
        return await self.async_step_validate_device()

    async def async_step_validate_device(
        self, user_input: dict[str, Any] | None = None
    ):
        """Validate connection to the current AirTouch4 device."""
        errors = {}

        if user_input is not None:
            # If user provided input (for manual retry), use that
            return await self.async_step_zone_mode()

        try:
            _LOGGER.debug("Validating AirTouch device at %s", self._host)
            # Replace with your actual method to create an AirTouch instance
            from airtouch4pyapi.airtouch import AirTouch, AirTouchStatus
            
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
        """Prompt user for a temperature sensor for each non-ITC zone."""
        errors = {}
        
        # Setup the zone name to ID mapping
        self._zone_name_to_id = {}
        for z in self._non_itc_zones:
            self._zone_name_to_id[z.GroupName] = str(z.GroupNumber)
        
        if user_input is not None:
            try:
                _LOGGER.debug("Processing user input for sensors: %s", user_input)
                
                # Check if any sensors are missing
                missing_sensor = False
                for zone_name in self._zone_name_to_id.keys():
                    if zone_name not in user_input or not user_input[zone_name]:
                        missing_sensor = True
                        break

                if missing_sensor:
                    errors["base"] = "missing_sensor"
                else:
                    # Map zone names to zone IDs and store the sensor values
                    for zone_name, zone_id in self._zone_name_to_id.items():
                        if zone_name in user_input and user_input[zone_name]:
                            self._temp_sensors[zone_id] = user_input[zone_name]
                    
                    _LOGGER.debug("Sensor mapping created: %s", self._temp_sensors)
                    return await self.async_step_finish()

            except Exception as e:
                _LOGGER.exception("Error in nonitc_sensors step: %s", e)
                errors["base"] = "unknown"

        # Define form schema dynamically using zone names as keys
        schema_dict = {}
        for zone_name, zone_id in self._zone_name_to_id.items():
            schema_dict[vol.Required(zone_name)] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["sensor"],
                    device_class=["temperature"],
                    multiple=False,
                )
            )

        return self.async_show_form(
            step_id="nonitc_sensors",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={
                "title": "Temperature Sensors for Non-ITC Zones",
                "description": "Each non-ITC zone requires a temperature sensor for proper temperature control."
            }
        )

    async def async_step_finish(self, user_input: dict[str, Any] | None = None):
        """Final step: Create config entry and move to the next device if any remain."""
        _LOGGER.info(f"Creating config entry for {self._host}")

        # Create the configuration entry for the current device
        await self.async_set_unique_id(f"airtouch4_{self._host}")
        self._abort_if_unique_id_configured()
        
        # Create the entry with all necessary data
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

class AirtouchOptionsFlow(config_entries.OptionsFlow):
    """Handle the options flow for AirTouch4 integration."""
    
    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry
        self.host = config_entry.data.get(CONF_HOST)
        # Get setup mode from options first, fall back to data if not in options
        self.setup_mode = config_entry.options.get("setup_mode") or config_entry.data.get("setup_mode")
        # Get existing sensor mapping from options first, fall back to data if not in options
        self.existing_sensors = config_entry.options.get("nonitc_sensors") or config_entry.data.get("nonitc_sensors", {})
        self._non_itc_zones = []
        # For mapping between zone names and IDs
        self._zone_name_to_id = {}

    async def async_step_init(self, user_input=None):
        """Handle options flow initialization."""
        _LOGGER.debug("Entering options flow init for %s", self.host)
        _LOGGER.debug("Current setup mode: %s", self.setup_mode)
        _LOGGER.debug("Current sensor mapping: %s", self.existing_sensors)
        
        # Only allow reconfiguration in non_itc_climate mode
        if self.setup_mode != MODE_NONITC_CLIMATE:
            _LOGGER.debug("Reconfiguration not supported in mode %s", self.setup_mode)
            return self.async_abort(
                reason="reconfigure_not_supported",
                description_placeholders={
                    "title": "Reconfiguration Not Supported",
                    "description": "Reconfiguration is not available in the current mode."
                }
            )
        
        # Proceed with non_itc_climate reconfiguration
        try:
            # Get the coordinator from hass data
            coordinator = self.hass.data[DOMAIN][self.config_entry.entry_id]["coordinator"]
            
            # Debug the data structure
            _LOGGER.debug("Coordinator data structure type: %s", type(coordinator.data))
            
            # Try to get the airtouch object directly
            airtouch = coordinator.airtouch
            _LOGGER.debug("AirTouch instance available: %s", airtouch is not None)
            
            # Force a refresh to ensure we have the latest data
            await coordinator.async_request_refresh()
            
            # Get zones from the airtouch object
            all_zones = airtouch.GetGroups()
            _LOGGER.debug("Found %d total zones from airtouch.GetGroups()", len(all_zones))
            
            # Filter for non-ITC zones
            self._non_itc_zones = [
                z for z in all_zones 
                if hasattr(z, "ControlMethod") and z.ControlMethod == "PercentageControl"
            ]
            
            _LOGGER.debug("Found %d non-ITC zones with PercentageControl", len(self._non_itc_zones))
            
            # If we found non-ITC zones, go directly to the sensor configuration
            if self._non_itc_zones:
                return await self.async_step_nonitc_sensors()
            else:
                _LOGGER.warning("No non-ITC zones found despite being in non_itc_climate mode")
                return self.async_abort(reason="no_zones")
        
        except Exception as e:
            _LOGGER.exception("Error in options flow init: %s", e)
            return self.async_abort(reason="unexpected_error")
        
    async def async_step_nonitc_sensors(self, user_input=None):
        """Configure temperature sensors for non-ITC zones."""
        errors = {}
        
        # Create a mapping between zone names and zone IDs for processing user input
        self._zone_name_to_id = {}
        for zone in self._non_itc_zones:
            zone_id = str(zone.GroupNumber)
            zone_name = zone.GroupName
            self._zone_name_to_id[zone_name] = zone_id
        
        if user_input is not None:
            try:
                # Process the user input to create a new sensor mapping
                new_sensors = {}
                
                # Match zone names with selected sensors using our mapping
                for zone_name, zone_id in self._zone_name_to_id.items():
                    if zone_name in user_input and user_input[zone_name]:
                        new_sensors[zone_id] = user_input[zone_name]
                    elif zone_id in self.existing_sensors:
                        # Keep existing mapping if no new selection
                        new_sensors[zone_id] = self.existing_sensors[zone_id]
                
                _LOGGER.debug("New sensor mapping: %s", new_sensors)
                
                # Create the complete options data
                new_options = {
                    "setup_mode": self.setup_mode,
                    "nonitc_sensors": new_sensors
                }
                
                # Create entry to save the options
                return self.async_create_entry(title="", data=new_options)
                
            except Exception as e:
                _LOGGER.exception("Error processing sensor configuration: %s", e)
                errors["base"] = "unknown"
        
        # Handle the case where there are no non-ITC zones
        if not self._non_itc_zones:
            _LOGGER.warning("No non-ITC zones found for sensor configuration")
            return self.async_show_form(
                step_id="nonitc_sensors",
                data_schema=vol.Schema({}),
                errors={"base": "no_zones"},
                description_placeholders={
                    "title": "No Non-ITC Zones Found", 
                    "description": "No zones requiring temperature sensors were found. Please check your system configuration."
                }
            )
        
        # Create the form schema with all non-ITC zones, using zone names as field keys
        schema = {}
        for zone_name, zone_id in self._zone_name_to_id.items():
            # Pre-populate with existing sensor if available
            default_value = self.existing_sensors.get(zone_id, "")
            
            # Use the zone name as the field key
            schema[vol.Required(
                zone_name,  # Use the actual zone name as the field key
                default=default_value
            )] = selector.EntitySelector(
                selector.EntitySelectorConfig(
                    domain=["sensor"],
                    device_class=["temperature"],
                    multiple=False,
                )
            )
        
        # Show the form with zone names as field keys
        return self.async_show_form(
            step_id="nonitc_sensors",
            data_schema=vol.Schema(schema),
            errors=errors,
            description_placeholders={
                "title": "Configure Temperature Sensors",
                "description": "Select temperature sensors for non-ITC zones. These sensors will be used for temperature readings in climate entities."
            }
        )