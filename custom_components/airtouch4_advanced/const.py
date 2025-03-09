DOMAIN = "airtouch4"

# Setup modes from the config flow
MODE_DEFAULT = "default"
MODE_NONITC_FAN = "nonitc_fan"
MODE_NONITC_CLIMATE = "nonitc_climate"

# AC Fan speed mapping (for AC climate entities)
FAN_SPEED_MAPPING = {
    "Turbo": 100,
    "Powerful": 100,
    "High": 80,
    "Medium": 50,
    "Low": 30,
    "Quiet": 20,
    "Auto": 50,  # default for Auto if needed
}

# Constants for manual (non-ITC) climate zones
MIN_FAN_SPEED = 20    # Even when target is reached, run at this minimum speed
MAX_FAN_SPEED = 100   # Maximum fan open percentage (for Turbo/Powerful)
AUTO_MAX_TEMP = 40.0  # For COOL mode: when current reaches this, run at MAX_FAN_SPEED
AUTO_MIN_TEMP = 15.0  # For HEAT mode: when current reaches this, run at MAX_FAN_SPEED
