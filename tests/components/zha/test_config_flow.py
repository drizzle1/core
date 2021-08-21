"""Tests for ZHA config flow."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import serial.tools.list_ports
import zigpy.config

from homeassistant import setup
from homeassistant.components.ssdp import (
    ATTR_SSDP_LOCATION,
    ATTR_UPNP_MANUFACTURER_URL,
    ATTR_UPNP_SERIAL,
)
from homeassistant.components.zha import config_flow
from homeassistant.components.zha.core.const import CONF_RADIO_TYPE, DOMAIN, RadioType
from homeassistant.config_entries import (
    SOURCE_SSDP,
    SOURCE_USB,
    SOURCE_USER,
    SOURCE_ZEROCONF,
)
from homeassistant.const import CONF_SOURCE
from homeassistant.data_entry_flow import RESULT_TYPE_CREATE_ENTRY, RESULT_TYPE_FORM

from tests.common import MockConfigEntry


def com_port():
    """Mock of a serial port."""
    port = serial.tools.list_ports_common.ListPortInfo("/dev/ttyUSB1234")
    port.serial_number = "1234"
    port.manufacturer = "Virtual serial port"
    port.device = "/dev/ttyUSB1234"
    port.description = "Some serial port"

    return port


@patch("homeassistant.components.zha.async_setup_entry", AsyncMock(return_value=True))
@patch("zigpy_znp.zigbee.application.ControllerApplication.probe", return_value=True)
async def test_discovery(detect_mock, hass):
    """Test zeroconf flow -- radio detected."""
    service_info = {
        "host": "192.168.1.200",
        "port": 6053,
        "hostname": "_tube_zb_gw._tcp.local.",
        "properties": {"name": "tube_123456"},
    }
    flow = await hass.config_entries.flow.async_init(
        "zha", context={"source": SOURCE_ZEROCONF}, data=service_info
    )
    result = await hass.config_entries.flow.async_configure(
        flow["flow_id"], user_input={}
    )

    assert result["type"] == RESULT_TYPE_CREATE_ENTRY
    assert result["title"] == "socket://192.168.1.200:6638"
    assert result["data"] == {
        "device": {
            "baudrate": 115200,
            "flow_control": None,
            "path": "socket://192.168.1.200:6638",
        },
        CONF_RADIO_TYPE: "znp",
    }


@patch("zigpy_znp.zigbee.application.ControllerApplication.probe", return_value=True)
async def test_discovery_via_usb(detect_mock, hass):
    """Test usb flow -- radio detected."""
    discovery_info = {
        "device": "/dev/ttyZIGBEE",
        "pid": "AAAA",
        "vid": "AAAA",
        "serial_number": "1234",
        "description": "zigbee radio",
        "manufacturer": "test",
    }
    result = await hass.config_entries.flow.async_init(
        "zha", context={"source": SOURCE_USB}, data=discovery_info
    )
    await hass.async_block_till_done()
    assert result["type"] == RESULT_TYPE_FORM
    assert result["step_id"] == "confirm"

    with patch("homeassistant.components.zha.async_setup_entry"):
        result2 = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input={}
        )
        await hass.async_block_till_done()

    assert result2["type"] == RESULT_TYPE_CREATE_ENTRY
    assert "zigbee radio" in result2["title"]
    assert result2["data"] == {
        "device": {
            "baudrate": 115200,
            "flow_control": None,
            "path": "/dev/ttyZIGBEE",
        },
        CONF_RADIO_TYPE: "znp",
    }


@patch("zigpy_znp.zigbee.application.ControllerApplication.probe", return_value=False)
async def test_discovery_via_usb_no_radio(detect_mock, hass):
    """Test usb flow -- no radio detected."""
    discovery_info = {
        "device": "/dev/null",
        "pid": "AAAA",
        "vid": "AAAA",
        "serial_number": "1234",
        "description": "zigbee radio",
        "manufacturer": "test",
    }
    result = await hass.config_entries.flow.async_init(
        "zha", context={"source": SOURCE_USB}, data=discovery_info
    )
    await hass.async_block_till_done()
    assert result["type"] == "abort"
    assert result["reason"] == "not_zha_device"


@patch("zigpy_znp.zigbee.application.ControllerApplication.probe", return_value=True)
async def test_discovery_via_usb_rejects_nortek_zwave(detect_mock, hass):
    """Test usb flow -- reject the nortek zwave radio."""
    discovery_info = {
        "device": "/dev/null",
        "vid": "10C4",
        "pid": "8A2A",
        "serial_number": "612020FD",
        "description": "HubZ Smart Home Controller - HubZ Z-Wave Com Port",
        "manufacturer": "Silicon Labs",
    }
    result = await hass.config_entries.flow.async_init(
        "zha", context={"source": SOURCE_USB}, data=discovery_info
    )
    await hass.async_block_till_done()
    assert result["type"] == "abort"
    assert result["reason"] == "not_zha_device"


@patch("zigpy_znp.zigbee.application.ControllerApplication.probe", return_value=True)
async def test_discovery_via_usb_already_setup(detect_mock, hass):
    """Test usb flow -- already setup."""
    await setup.async_setup_component(hass, "persistent_notification", {})
    MockConfigEntry(domain=DOMAIN, data={"usb_path": "/dev/ttyUSB1"}).add_to_hass(hass)

    discovery_info = {
        "device": "/dev/ttyZIGBEE",
        "pid": "AAAA",
        "vid": "AAAA",
        "serial_number": "1234",
        "description": "zigbee radio",
        "manufacturer": "test",
    }
    result = await hass.config_entries.flow.async_init(
        "zha", context={"source": SOURCE_USB}, data=discovery_info
    )
    await hass.async_block_till_done()

    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"


@patch("zigpy_znp.zigbee.application.ControllerApplication.probe", return_value=True)
async def test_discovery_via_usb_deconz_already_discovered(detect_mock, hass):
    """Test usb flow -- deconz discovered."""
    result = await hass.config_entries.flow.async_init(
        "deconz",
        data={
            ATTR_SSDP_LOCATION: "http://1.2.3.4:80/",
            ATTR_UPNP_MANUFACTURER_URL: "http://www.dresden-elektronik.de",
            ATTR_UPNP_SERIAL: "0000000000000000",
        },
        context={"source": SOURCE_SSDP},
    )
    await hass.async_block_till_done()
    discovery_info = {
        "device": "/dev/ttyZIGBEE",
        "pid": "AAAA",
        "vid": "AAAA",
        "serial_number": "1234",
        "description": "zigbee radio",
        "manufacturer": "test",
    }
    result = await hass.config_entries.flow.async_init(
        "zha", context={"source": SOURCE_USB}, data=discovery_info
    )
    await hass.async_block_till_done()

    assert result["type"] == "abort"
    assert result["reason"] == "not_zha_device"


@patch("homeassistant.components.zha.async_setup_entry", AsyncMock(return_value=True))
@patch("zigpy_znp.zigbee.application.ControllerApplication.probe", return_value=True)
async def test_discovery_already_setup(detect_mock, hass):
    """Test zeroconf flow -- radio detected."""
    service_info = {
        "host": "192.168.1.200",
        "port": 6053,
        "hostname": "_tube_zb_gw._tcp.local.",
        "properties": {"name": "tube_123456"},
    }
    await setup.async_setup_component(hass, "persistent_notification", {})
    MockConfigEntry(domain=DOMAIN, data={"usb_path": "/dev/ttyUSB1"}).add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        "zha", context={"source": SOURCE_ZEROCONF}, data=service_info
    )
    await hass.async_block_till_done()

    assert result["type"] == "abort"
    assert result["reason"] == "single_instance_allowed"


@patch("serial.tools.list_ports.comports", MagicMock(return_value=[com_port()]))
@patch(
    "homeassistant.components.zha.config_flow.detect_radios",
    return_value={CONF_RADIO_TYPE: "test_radio"},
)
async def test_user_flow(detect_mock, hass):
    """Test user flow -- radio detected."""

    port = com_port()
    port_select = f"{port}, s/n: {port.serial_number} - {port.manufacturer}"

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_USER},
        data={zigpy.config.CONF_DEVICE_PATH: port_select},
    )
    assert result["type"] == RESULT_TYPE_CREATE_ENTRY
    assert result["title"].startswith(port.description)
    assert result["data"] == {CONF_RADIO_TYPE: "test_radio"}
    assert detect_mock.await_count == 1
    assert detect_mock.await_args[0][0] == port.device


@patch("serial.tools.list_ports.comports", MagicMock(return_value=[com_port()]))
@patch(
    "homeassistant.components.zha.config_flow.detect_radios",
    return_value=None,
)
async def test_user_flow_not_detected(detect_mock, hass):
    """Test user flow, radio not detected."""

    port = com_port()
    port_select = f"{port}, s/n: {port.serial_number} - {port.manufacturer}"

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_USER},
        data={zigpy.config.CONF_DEVICE_PATH: port_select},
    )

    assert result["type"] == RESULT_TYPE_FORM
    assert result["step_id"] == "pick_radio"
    assert detect_mock.await_count == 1
    assert detect_mock.await_args[0][0] == port.device


@patch("serial.tools.list_ports.comports", MagicMock(return_value=[com_port()]))
async def test_user_flow_show_form(hass):
    """Test user step form."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_USER},
    )

    assert result["type"] == RESULT_TYPE_FORM
    assert result["step_id"] == "user"


@patch("serial.tools.list_ports.comports", MagicMock(return_value=[]))
async def test_user_flow_show_manual(hass):
    """Test user flow manual entry when no comport detected."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_USER},
    )

    assert result["type"] == RESULT_TYPE_FORM
    assert result["step_id"] == "pick_radio"


async def test_user_flow_manual(hass):
    """Test user flow manual entry."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: SOURCE_USER},
        data={zigpy.config.CONF_DEVICE_PATH: config_flow.CONF_MANUAL_PATH},
    )
    assert result["type"] == RESULT_TYPE_FORM
    assert result["step_id"] == "pick_radio"


@pytest.mark.parametrize("radio_type", RadioType.list())
async def test_pick_radio_flow(hass, radio_type):
    """Test radio picker."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={CONF_SOURCE: "pick_radio"}, data={CONF_RADIO_TYPE: radio_type}
    )
    assert result["type"] == RESULT_TYPE_FORM
    assert result["step_id"] == "port_config"


async def test_user_flow_existing_config_entry(hass):
    """Test if config entry already exists."""
    MockConfigEntry(domain=DOMAIN, data={"usb_path": "/dev/ttyUSB1"}).add_to_hass(hass)
    await setup.async_setup_component(hass, "persistent_notification", {})
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={CONF_SOURCE: SOURCE_USER}
    )

    assert result["type"] == "abort"


@patch("zigpy_cc.zigbee.application.ControllerApplication.probe", return_value=False)
@patch(
    "zigpy_deconz.zigbee.application.ControllerApplication.probe", return_value=False
)
@patch(
    "zigpy_zigate.zigbee.application.ControllerApplication.probe", return_value=False
)
@patch("zigpy_xbee.zigbee.application.ControllerApplication.probe", return_value=False)
async def test_probe_radios(xbee_probe, zigate_probe, deconz_probe, cc_probe, hass):
    """Test detect radios."""
    app_ctrl_cls = MagicMock()
    app_ctrl_cls.SCHEMA_DEVICE = zigpy.config.SCHEMA_DEVICE
    app_ctrl_cls.probe = AsyncMock(side_effect=(True, False))

    p1 = patch(
        "bellows.zigbee.application.ControllerApplication.probe",
        side_effect=(True, False),
    )
    with p1 as probe_mock:
        res = await config_flow.detect_radios("/dev/null")
        assert probe_mock.await_count == 1
        assert res[CONF_RADIO_TYPE] == "ezsp"
        assert zigpy.config.CONF_DEVICE in res
        assert (
            res[zigpy.config.CONF_DEVICE][zigpy.config.CONF_DEVICE_PATH] == "/dev/null"
        )

        res = await config_flow.detect_radios("/dev/null")
        assert res is None
        assert xbee_probe.await_count == 1
        assert zigate_probe.await_count == 1
        assert deconz_probe.await_count == 1
        assert cc_probe.await_count == 1


@patch("bellows.zigbee.application.ControllerApplication.probe", return_value=False)
async def test_user_port_config_fail(probe_mock, hass):
    """Test port config flow."""

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: "pick_radio"},
        data={CONF_RADIO_TYPE: RadioType.ezsp.description},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={zigpy.config.CONF_DEVICE_PATH: "/dev/ttyUSB33"},
    )
    assert result["type"] == RESULT_TYPE_FORM
    assert result["step_id"] == "port_config"
    assert result["errors"]["base"] == "cannot_connect"
    assert probe_mock.await_count == 1


@patch("homeassistant.components.zha.async_setup_entry", AsyncMock(return_value=True))
@patch("bellows.zigbee.application.ControllerApplication.probe", return_value=True)
async def test_user_port_config(probe_mock, hass):
    """Test port config."""
    await setup.async_setup_component(hass, "persistent_notification", {})

    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={CONF_SOURCE: "pick_radio"},
        data={CONF_RADIO_TYPE: RadioType.ezsp.description},
    )

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={zigpy.config.CONF_DEVICE_PATH: "/dev/ttyUSB33"},
    )

    assert result["type"] == "create_entry"
    assert result["title"].startswith("/dev/ttyUSB33")
    assert (
        result["data"][zigpy.config.CONF_DEVICE][zigpy.config.CONF_DEVICE_PATH]
        == "/dev/ttyUSB33"
    )
    assert result["data"][CONF_RADIO_TYPE] == "ezsp"
    assert probe_mock.await_count == 1
