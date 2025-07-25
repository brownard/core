"""Constants used by Tesla Fleet integration."""

from __future__ import annotations

from enum import StrEnum
import logging

from tesla_fleet_api.const import Scope

DOMAIN = "tesla_fleet"

CONF_DOMAIN = "domain"
CONF_REFRESH_TOKEN = "refresh_token"

LOGGER = logging.getLogger(__package__)

AUTHORIZE_URL = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/authorize"
TOKEN_URL = "https://fleet-auth.prd.vn.cloud.tesla.com/oauth2/v3/token"

SCOPES = [
    Scope.OPENID,
    Scope.OFFLINE_ACCESS,
    Scope.VEHICLE_DEVICE_DATA,
    Scope.VEHICLE_LOCATION,
    Scope.VEHICLE_CMDS,
    Scope.VEHICLE_CHARGING_CMDS,
    Scope.ENERGY_DEVICE_DATA,
    Scope.ENERGY_CMDS,
]

MODELS = {
    "S": "Model S",
    "3": "Model 3",
    "X": "Model X",
    "Y": "Model Y",
    "C": "Cybertruck",
    "T": "Tesla Semi",
}

ENERGY_HISTORY_FIELDS = [
    "solar_energy_exported",
    "generator_energy_exported",
    "grid_energy_imported",
    "grid_services_energy_imported",
    "grid_services_energy_exported",
    "grid_energy_exported_from_solar",
    "grid_energy_exported_from_generator",
    "grid_energy_exported_from_battery",
    "battery_energy_exported",
    "battery_energy_imported_from_grid",
    "battery_energy_imported_from_solar",
    "battery_energy_imported_from_generator",
    "consumer_energy_imported_from_grid",
    "consumer_energy_imported_from_solar",
    "consumer_energy_imported_from_battery",
    "consumer_energy_imported_from_generator",
    "total_home_usage",
    "total_battery_charge",
    "total_battery_discharge",
    "total_solar_generation",
    "total_grid_energy_exported",
]


class TeslaFleetState(StrEnum):
    """Teslemetry Vehicle States."""

    ONLINE = "online"
    ASLEEP = "asleep"
    OFFLINE = "offline"


class TeslaFleetClimateSide(StrEnum):
    """Tesla Fleet Climate Keeper Modes."""

    DRIVER = "driver_temp"
    PASSENGER = "passenger_temp"
