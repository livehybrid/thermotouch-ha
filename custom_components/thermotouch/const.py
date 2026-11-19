"""Constants for the ThermoTouch integration."""

DOMAIN = "thermotouch"

CONF_MAC = "mac"
CONF_TOKEN = "token"
CONF_TEMPLATE = "command_template"
CONF_HOST = "host"
CONF_PORT = "port"
CONF_SCAN_INTERVAL = "scan_interval"

DEFAULT_HOST = "18.197.22.220"        # etop3.etopcontrols.com
DEFAULT_PORT = 2026
DEFAULT_SCAN_INTERVAL = 300           # seconds; heating is slow and reads use a cloud session

MODES = ["comfort", "eco", "manual", "holiday", "schedule"]
RAIL_OPTIONS = ["off", "on", "timer", "1h", "2h", "4h"]

MANUFACTURER = "ETOP / Thermogroup"
MODEL = "ThermoTouch"
