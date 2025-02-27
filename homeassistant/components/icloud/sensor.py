"""Support for iCloud sensors."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import DEVICE_CLASS_BATTERY, PERCENTAGE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.icon import icon_for_battery_level

from .account import IcloudAccount, IcloudDevice
from .const import DOMAIN


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities
) -> None:
    """Set up device tracker for iCloud component."""
    account = hass.data[DOMAIN][entry.unique_id]
    tracked = set()

    @callback
    def update_account():
        """Update the values of the account."""
        add_entities(account, async_add_entities, tracked)

    account.listeners.append(
        async_dispatcher_connect(hass, account.signal_device_new, update_account)
    )

    update_account()


@callback
def add_entities(account, async_add_entities, tracked):
    """Add new tracker entities from the account."""
    new_tracked = []

    for dev_id, device in account.devices.items():
        if dev_id in tracked or device.battery_level is None:
            continue

        new_tracked.append(IcloudDeviceBatterySensor(account, device))
        tracked.add(dev_id)

    if new_tracked:
        async_add_entities(new_tracked, True)


class IcloudDeviceBatterySensor(SensorEntity):
    """Representation of a iCloud device battery sensor."""

    _attr_device_class = DEVICE_CLASS_BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE

    def __init__(self, account: IcloudAccount, device: IcloudDevice) -> None:
        """Initialize the battery sensor."""
        self._account = account
        self._device = device
        self._unsub_dispatcher = None

    @property
    def unique_id(self) -> str:
        """Return a unique ID."""
        return f"{self._device.unique_id}_battery"

    @property
    def name(self) -> str:
        """Sensor name."""
        return f"{self._device.name} battery state"

    @property
    def native_value(self) -> int:
        """Battery state percentage."""
        return self._device.battery_level

    @property
    def icon(self) -> str:
        """Battery state icon handling."""
        return icon_for_battery_level(
            battery_level=self._device.battery_level,
            charging=self._device.battery_status == "Charging",
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return default attributes for the iCloud device entity."""
        return self._device.extra_state_attributes

    @property
    def device_info(self) -> DeviceInfo:
        """Return the device information."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._device.unique_id)},
            manufacturer="Apple",
            model=self._device.device_model,
            name=self._device.name,
        )

    @property
    def should_poll(self) -> bool:
        """No polling needed."""
        return False

    async def async_added_to_hass(self):
        """Register state update callback."""
        self._unsub_dispatcher = async_dispatcher_connect(
            self.hass, self._account.signal_device_update, self.async_write_ha_state
        )

    async def async_will_remove_from_hass(self):
        """Clean up after entity before removal."""
        self._unsub_dispatcher()
