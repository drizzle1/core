"""The Mazda Connected Services integration."""
from datetime import timedelta
import logging

import async_timeout
from pymazda import (
    Client as MazdaAPI,
    MazdaAccountLockedException,
    MazdaAPIEncryptionException,
    MazdaAuthenticationException,
    MazdaException,
    MazdaTokenExpiredException,
)
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_EMAIL, CONF_PASSWORD, CONF_REGION
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    HomeAssistantError,
)
from homeassistant.helpers import aiohttp_client, device_registry
import homeassistant.helpers.config_validation as cv
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)

from .const import DATA_CLIENT, DATA_COORDINATOR, DATA_VEHICLES, DOMAIN, SERVICES

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["device_tracker", "lock", "sensor"]


async def with_timeout(task, timeout_seconds=10):
    """Run an async task with a timeout."""
    async with async_timeout.timeout(timeout_seconds):
        return await task


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Mazda Connected Services from a config entry."""
    email = entry.data[CONF_EMAIL]
    password = entry.data[CONF_PASSWORD]
    region = entry.data[CONF_REGION]

    websession = aiohttp_client.async_get_clientsession(hass)
    mazda_client = MazdaAPI(
        email, password, region, websession=websession, use_cached_vehicle_list=True
    )

    try:
        await mazda_client.validate_credentials()
    except MazdaAuthenticationException as ex:
        raise ConfigEntryAuthFailed from ex
    except (
        MazdaException,
        MazdaAccountLockedException,
        MazdaTokenExpiredException,
        MazdaAPIEncryptionException,
    ) as ex:
        _LOGGER.error("Error occurred during Mazda login request: %s", ex)
        raise ConfigEntryNotReady from ex

    async def async_handle_service_call(service_call=None):
        """Handle a service call."""
        # Get device entry from device registry
        dev_reg = device_registry.async_get(hass)
        device_id = service_call.data["device_id"]
        device_entry = dev_reg.async_get(device_id)

        # Get vehicle VIN from device identifiers
        mazda_identifiers = (
            identifier
            for identifier in device_entry.identifiers
            if identifier[0] == DOMAIN
        )
        vin_identifier = next(mazda_identifiers)
        vin = vin_identifier[1]

        # Get vehicle ID and API client from hass.data
        vehicle_id = 0
        api_client = None
        for entry_data in hass.data[DOMAIN].values():
            for vehicle in entry_data[DATA_VEHICLES]:
                if vehicle["vin"] == vin:
                    vehicle_id = vehicle["id"]
                    api_client = entry_data[DATA_CLIENT]
                    break

        if vehicle_id == 0 or api_client is None:
            raise HomeAssistantError("Vehicle ID not found")

        api_method = getattr(api_client, service_call.service)
        try:
            if service_call.service == "send_poi":
                latitude = service_call.data["latitude"]
                longitude = service_call.data["longitude"]
                poi_name = service_call.data["poi_name"]
                await api_method(vehicle_id, latitude, longitude, poi_name)
            else:
                await api_method(vehicle_id)
        except Exception as ex:
            raise HomeAssistantError(ex) from ex

    def validate_mazda_device_id(device_id):
        """Check that a device ID exists in the registry and has at least one 'mazda' identifier."""
        dev_reg = device_registry.async_get(hass)

        if (device_entry := dev_reg.async_get(device_id)) is None:
            raise vol.Invalid("Invalid device ID")

        mazda_identifiers = [
            identifier
            for identifier in device_entry.identifiers
            if identifier[0] == DOMAIN
        ]
        if not mazda_identifiers:
            raise vol.Invalid("Device ID is not a Mazda vehicle")

        return device_id

    service_schema = vol.Schema(
        {vol.Required("device_id"): vol.All(cv.string, validate_mazda_device_id)}
    )

    service_schema_send_poi = service_schema.extend(
        {
            vol.Required("latitude"): cv.latitude,
            vol.Required("longitude"): cv.longitude,
            vol.Required("poi_name"): cv.string,
        }
    )

    async def async_update_data():
        """Fetch data from Mazda API."""
        try:
            vehicles = await with_timeout(mazda_client.get_vehicles())

            # The Mazda API can throw an error when multiple simultaneous requests are
            # made for the same account, so we can only make one request at a time here
            for vehicle in vehicles:
                vehicle["status"] = await with_timeout(
                    mazda_client.get_vehicle_status(vehicle["id"])
                )

            hass.data[DOMAIN][entry.entry_id][DATA_VEHICLES] = vehicles

            return vehicles
        except MazdaAuthenticationException as ex:
            raise ConfigEntryAuthFailed("Not authenticated with Mazda API") from ex
        except Exception as ex:
            _LOGGER.exception(
                "Unknown error occurred during Mazda update request: %s", ex
            )
            raise UpdateFailed(ex) from ex

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name=DOMAIN,
        update_method=async_update_data,
        update_interval=timedelta(seconds=180),
    )

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_CLIENT: mazda_client,
        DATA_COORDINATOR: coordinator,
        DATA_VEHICLES: [],
    }

    # Fetch initial data so we have data when entities subscribe
    await coordinator.async_config_entry_first_refresh()

    # Setup components
    hass.config_entries.async_setup_platforms(entry, PLATFORMS)

    # Register services
    for service in SERVICES:
        if service == "send_poi":
            hass.services.async_register(
                DOMAIN,
                service,
                async_handle_service_call,
                schema=service_schema_send_poi,
            )
        else:
            hass.services.async_register(
                DOMAIN, service, async_handle_service_call, schema=service_schema
            )

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    # Only remove services if it is the last config entry
    if len(hass.data[DOMAIN]) == 1:
        for service in SERVICES:
            hass.services.async_remove(DOMAIN, service)

    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok


class MazdaEntity(CoordinatorEntity):
    """Defines a base Mazda entity."""

    def __init__(self, client, coordinator, index):
        """Initialize the Mazda entity."""
        super().__init__(coordinator)
        self.client = client
        self.index = index
        self.vin = self.coordinator.data[self.index]["vin"]
        self.vehicle_id = self.coordinator.data[self.index]["id"]

    @property
    def data(self):
        """Shortcut to access coordinator data for the entity."""
        return self.coordinator.data[self.index]

    @property
    def device_info(self):
        """Return device info for the Mazda entity."""
        return {
            "identifiers": {(DOMAIN, self.vin)},
            "name": self.get_vehicle_name(),
            "manufacturer": "Mazda",
            "model": f"{self.data['modelYear']} {self.data['carlineName']}",
        }

    def get_vehicle_name(self):
        """Return the vehicle name, to be used as a prefix for names of other entities."""
        if "nickname" in self.data and len(self.data["nickname"]) > 0:
            return self.data["nickname"]
        return f"{self.data['modelYear']} {self.data['carlineName']}"
