import json
import logging
import os
import tempfile
from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from qsticky.config import HealthStatus, ServiceStatus
from qsticky.health import HealthManager
from qsticky.manager import PortManager


@pytest.fixture
def health_status():
    return HealthStatus()


@pytest.fixture
def temp_health_file():
    fd, path = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def logger():
    return logging.getLogger('test_qsticky')


@pytest.fixture
def health_manager(health_status, temp_health_file, logger):
    return HealthManager(
        health_status=health_status,
        health_file=temp_health_file,
        logger=logger
    )


@pytest.fixture
def mock_settings():
    with patch('qsticky.manager.Settings') as mock:
        instance = mock.return_value
        instance.log_level = 'ERROR'
        instance.check_interval = 30
        instance.gluetun_host = 'localhost'
        instance.gluetun_port = 8000
        instance.gluetun_auth_type = 'apikey'
        instance.gluetun_apikey = 'testkey'
        instance.qbittorrent_host = 'localhost'
        instance.qbittorrent_port = 8080
        instance.qbittorrent_user = 'admin'
        instance.qbittorrent_pass = 'adminadmin'
        instance.qbittorrent_https = False
        instance.qbittorrent_verify_ssl = False
        instance.qbittorrent_api_key = ''
        yield instance


@pytest.fixture
def port_manager(mock_settings, temp_health_file):
    with patch.dict(os.environ, {'HEALTH_FILE': temp_health_file}):
        with patch('qsticky.manager.QBittorrentClient') as mock_qbit, \
             patch('qsticky.manager.GluetunClient') as mock_gluetun:

            manager = PortManager()
            manager.qbit = mock_qbit.return_value
            manager.gluetun = mock_gluetun.return_value

            manager.qbit._use_api_key = False

            yield manager


class TestHealthStatusModel:
    def test_health_status_is_healthy_all_ok(self, health_status):
        health_status.gluetun.connected = True
        health_status.qbittorrent.connected = True
        health_status.qbittorrent.port_synced = True
        assert health_status.is_healthy() is True

    def test_health_status_is_healthy_gluetun_down(self, health_status):
        health_status.gluetun.connected = False
        health_status.qbittorrent.connected = True
        health_status.qbittorrent.port_synced = True
        assert health_status.is_healthy() is False

    def test_health_status_is_healthy_qbit_down(self, health_status):
        health_status.gluetun.connected = True
        health_status.qbittorrent.connected = False
        health_status.qbittorrent.port_synced = False
        assert health_status.is_healthy() is False

    def test_health_status_is_healthy_ports_not_synced(self, health_status):
        health_status.gluetun.connected = True
        health_status.qbittorrent.connected = True
        health_status.qbittorrent.port_synced = False
        assert health_status.is_healthy() is False

    def test_update_last_check(self, health_status):
        assert health_status.last_check is None
        health_status.update_last_check()
        assert health_status.last_check is not None
        assert isinstance(health_status.last_check, datetime)


class TestHealthManager:
    @pytest.mark.asyncio
    async def test_get_health_port_consistent(self, health_manager, health_status):
        now = datetime.now()
        health_status.gluetun.connected = True
        health_status.gluetun.status = ServiceStatus.OK
        health_status.gluetun.port = 55000
        health_status.gluetun.last_check = now
        health_status.gluetun.last_success = now
        health_status.qbittorrent.connected = True
        health_status.qbittorrent.status = ServiceStatus.OK
        health_status.qbittorrent.port = 55000
        health_status.qbittorrent.port_synced = True
        health_status.qbittorrent.last_check = now
        health_status.qbittorrent.last_success = now
        health_status.last_check = now
        health_status.last_port_change = now
        health_status.last_successful_sync = now
        health_status.current_port = 55000

        result = health_manager.get_health()

        assert result['healthy'] is True
        assert result['current_port'] == 55000
        assert result['services']['gluetun']['connected'] is True
        assert result['services']['gluetun']['status'] == 'ok'
        assert result['services']['gluetun']['port'] == 55000
        assert result['services']['qbittorrent']['connected'] is True
        assert result['services']['qbittorrent']['status'] == 'ok'
        assert result['services']['qbittorrent']['port'] == 55000
        assert result['services']['qbittorrent']['port_synced'] is True
        assert result['last_check'] is not None
        assert result['last_successful_sync'] is not None
        assert result['last_port_change'] is not None
        assert result['last_error'] is None

    @pytest.mark.asyncio
    async def test_update_health_file_writes_json(self, health_manager, health_status):
        health_status.gluetun.connected = True
        health_status.gluetun.status = ServiceStatus.OK
        health_status.gluetun.port = 55000
        health_status.qbittorrent.connected = True
        health_status.qbittorrent.status = ServiceStatus.OK
        health_status.qbittorrent.port = 55000
        health_status.qbittorrent.port_synced = True
        health_status.current_port = 55000

        await health_manager.update_health_file()

        with open(health_manager.health_file, 'r') as f:
            data = json.load(f)

        assert data['healthy'] is True
        assert data['current_port'] == 55000
        assert data['services']['gluetun']['port'] == 55000
        assert data['services']['qbittorrent']['port_synced'] is True

    @pytest.mark.asyncio
    async def test_get_health_gluetun_error(self, health_manager, health_status):
        now = datetime.now()
        health_status.gluetun.connected = False
        health_status.gluetun.status = ServiceStatus.ERROR
        health_status.gluetun.port = None
        health_status.gluetun.last_check = now
        health_status.gluetun.last_error = "Failed to get forwarded port"
        health_status.qbittorrent.connected = False
        health_status.qbittorrent.status = ServiceStatus.UNKNOWN
        health_status.qbittorrent.port_synced = False
        health_status.last_check = now
        health_status.current_port = None
        health_status.last_error = "Gluetun port fetch failed"

        result = health_manager.get_health()

        assert result['healthy'] is False
        assert result['current_port'] is None
        assert result['services']['gluetun']['connected'] is False
        assert result['services']['gluetun']['status'] == 'error'
        assert result['services']['gluetun']['port'] is None
        assert result['services']['gluetun']['last_error'] == "Failed to get forwarded port"
        assert result['services']['qbittorrent']['connected'] is False
        assert result['services']['qbittorrent']['port_synced'] is False
        assert result['last_error'] == "Gluetun port fetch failed"

    @pytest.mark.asyncio
    async def test_get_health_qbit_auth_failed(self, health_manager, health_status):
        now = datetime.now()
        health_status.gluetun.connected = True
        health_status.gluetun.status = ServiceStatus.OK
        health_status.gluetun.port = 55000
        health_status.gluetun.last_check = now
        health_status.gluetun.last_success = now
        health_status.qbittorrent.connected = False
        health_status.qbittorrent.status = ServiceStatus.AUTH_FAILED
        health_status.qbittorrent.port = None
        health_status.qbittorrent.port_synced = False
        health_status.qbittorrent.last_check = now
        health_status.qbittorrent.last_error = "API key auth failed (HTTP 401)"
        health_status.last_check = now
        health_status.current_port = None
        health_status.last_error = "API key auth failed (HTTP 401)"

        result = health_manager.get_health()

        assert result['healthy'] is False
        assert result['services']['gluetun']['connected'] is True
        assert result['services']['gluetun']['status'] == 'ok'
        assert result['services']['qbittorrent']['connected'] is False
        assert result['services']['qbittorrent']['status'] == 'auth_failed'
        assert result['services']['qbittorrent']['port_synced'] is False
        assert result['services']['qbittorrent']['last_error'] == "API key auth failed (HTTP 401)"

    @pytest.mark.asyncio
    async def test_get_health_port_mismatch(self, health_manager, health_status):
        now = datetime.now()
        health_status.gluetun.connected = True
        health_status.gluetun.status = ServiceStatus.OK
        health_status.gluetun.port = 55000
        health_status.gluetun.last_check = now
        health_status.gluetun.last_success = now
        health_status.qbittorrent.connected = True
        health_status.qbittorrent.status = ServiceStatus.PORT_MISMATCH
        health_status.qbittorrent.port = 54000
        health_status.qbittorrent.port_synced = False
        health_status.qbittorrent.last_check = now
        health_status.qbittorrent.last_error = "Port verification failed: expected 55000, got 54000"
        health_status.last_check = now
        health_status.current_port = 55000
        health_status.last_error = "Port change verification failed"

        result = health_manager.get_health()

        assert result['healthy'] is False
        assert result['services']['gluetun']['port'] == 55000
        assert result['services']['qbittorrent']['status'] == 'port_mismatch'
        assert result['services']['qbittorrent']['port'] == 54000
        assert result['services']['qbittorrent']['port_synced'] is False
        assert "Port verification failed" in result['services']['qbittorrent']['last_error']


class TestPortManagerEndToEnd:
    @pytest.mark.asyncio
    async def test_port_already_consistent(self, port_manager, temp_health_file):
        port_manager.gluetun.get_forwarded_port = AsyncMock(return_value=55000)
        port_manager.qbit.get_current_port = AsyncMock(return_value=55000)
        port_manager._first_run = True

        await port_manager.handle_port_change()

        assert port_manager.health_status.gluetun.connected is True
        assert port_manager.health_status.gluetun.status == ServiceStatus.OK
        assert port_manager.health_status.gluetun.port == 55000
        assert port_manager.health_status.qbittorrent.connected is True
        assert port_manager.health_status.qbittorrent.status == ServiceStatus.OK
        assert port_manager.health_status.qbittorrent.port == 55000
        assert port_manager.health_status.qbittorrent.port_synced is True
        assert port_manager.health_status.is_healthy() is True
        assert port_manager.health_status.current_port == 55000
        assert port_manager.health_status.last_successful_sync is not None
        assert port_manager.health_status.last_check is not None
        assert port_manager.health_status.last_error is None

        port_manager.qbit.update_port.assert_not_called()

        with open(temp_health_file, 'r') as f:
            file_data = json.load(f)
        assert file_data['healthy'] is True
        assert file_data['current_port'] == 55000
        assert file_data['services']['gluetun']['connected'] is True
        assert file_data['services']['qbittorrent']['port_synced'] is True

    @pytest.mark.asyncio
    async def test_gluetun_port_fetch_failed(self, port_manager, temp_health_file):
        port_manager.gluetun.get_forwarded_port = AsyncMock(return_value=None)
        port_manager._first_run = True

        await port_manager.handle_port_change()

        assert port_manager.health_status.gluetun.connected is False
        assert port_manager.health_status.gluetun.status == ServiceStatus.ERROR
        assert port_manager.health_status.gluetun.port is None
        assert port_manager.health_status.gluetun.last_error is not None
        assert "Failed to get forwarded port" in port_manager.health_status.gluetun.last_error
        assert port_manager.health_status.qbittorrent.port_synced is False
        assert port_manager.health_status.is_healthy() is False
        assert port_manager.health_status.last_check is not None
        assert "Gluetun" in port_manager.health_status.last_error

        port_manager.qbit.get_current_port.assert_not_called()
        port_manager.qbit.update_port.assert_not_called()

        with open(temp_health_file, 'r') as f:
            file_data = json.load(f)
        assert file_data['healthy'] is False
        assert file_data['services']['gluetun']['status'] == 'error'
        assert file_data['services']['gluetun']['connected'] is False
        assert file_data['services']['gluetun']['last_error'] is not None
        assert file_data['services']['qbittorrent']['port_synced'] is False

    @pytest.mark.asyncio
    async def test_gluetun_port_fetch_failed_then_recovery(self, port_manager, temp_health_file):
        port_manager.gluetun.get_forwarded_port = AsyncMock(return_value=None)
        port_manager._first_run = True
        await port_manager.handle_port_change()
        assert port_manager.health_status.is_healthy() is False
        assert port_manager.health_status.gluetun.last_success is None

        port_manager.gluetun.get_forwarded_port = AsyncMock(return_value=55000)
        port_manager.qbit.get_current_port = AsyncMock(return_value=55000)
        port_manager._first_run = False
        await port_manager.handle_port_change()

        assert port_manager.health_status.is_healthy() is True
        assert port_manager.health_status.gluetun.connected is True
        assert port_manager.health_status.gluetun.status == ServiceStatus.OK
        assert port_manager.health_status.gluetun.last_success is not None
        assert port_manager.health_status.qbittorrent.last_success is not None
        assert port_manager.health_status.last_error is None

    @pytest.mark.asyncio
    async def test_qbittorrent_auth_failed(self, port_manager, temp_health_file):
        port_manager.gluetun.get_forwarded_port = AsyncMock(return_value=55000)
        port_manager.qbit.get_current_port = AsyncMock(return_value=None)
        port_manager.health_status.qbittorrent.status = ServiceStatus.AUTH_FAILED
        port_manager.health_status.qbittorrent.last_error = "Login failed: 401"
        port_manager._first_run = True

        await port_manager.handle_port_change()

        assert port_manager.health_status.gluetun.connected is True
        assert port_manager.health_status.gluetun.status == ServiceStatus.OK
        assert port_manager.health_status.gluetun.port == 55000
        assert port_manager.health_status.qbittorrent.connected is False
        assert port_manager.health_status.qbittorrent.status == ServiceStatus.AUTH_FAILED
        assert port_manager.health_status.qbittorrent.port_synced is False
        assert port_manager.health_status.qbittorrent.last_error == "Login failed: 401"
        assert port_manager.health_status.is_healthy() is False

        port_manager.qbit.update_port.assert_not_called()

        with open(temp_health_file, 'r') as f:
            file_data = json.load(f)
        assert file_data['healthy'] is False
        assert file_data['services']['gluetun']['status'] == 'ok'
        assert file_data['services']['qbittorrent']['status'] == 'auth_failed'
        assert file_data['services']['qbittorrent']['connected'] is False
        assert file_data['services']['qbittorrent']['last_error'] == "Login failed: 401"

    @pytest.mark.asyncio
    async def test_port_needs_update_and_verification_fails(self, port_manager, temp_health_file):
        port_manager.gluetun.get_forwarded_port = AsyncMock(return_value=55000)
        port_manager.qbit.get_current_port = AsyncMock(side_effect=[54000, 54000])
        port_manager.qbit.update_port = AsyncMock(return_value=True)
        port_manager._first_run = True

        await port_manager.handle_port_change()

        port_manager.qbit.update_port.assert_called_once_with(55000)
        assert port_manager.qbit.get_current_port.call_count == 2

        assert port_manager.health_status.gluetun.connected is True
        assert port_manager.health_status.gluetun.port == 55000
        assert port_manager.health_status.qbittorrent.connected is True
        assert port_manager.health_status.qbittorrent.status == ServiceStatus.PORT_MISMATCH
        assert port_manager.health_status.qbittorrent.port == 54000
        assert port_manager.health_status.qbittorrent.port_synced is False
        assert "Port verification failed" in port_manager.health_status.qbittorrent.last_error
        assert port_manager.health_status.is_healthy() is False
        assert port_manager.health_status.last_port_change is not None
        assert "verification" in port_manager.health_status.last_error

        with open(temp_health_file, 'r') as f:
            file_data = json.load(f)
        assert file_data['healthy'] is False
        assert file_data['services']['qbittorrent']['status'] == 'port_mismatch'
        assert file_data['services']['qbittorrent']['port_synced'] is False
        assert "expected 55000, got 54000" in file_data['services']['qbittorrent']['last_error']

    @pytest.mark.asyncio
    async def test_port_needs_update_succeeds(self, port_manager, temp_health_file):
        port_manager.gluetun.get_forwarded_port = AsyncMock(return_value=55000)
        port_manager.qbit.get_current_port = AsyncMock(side_effect=[54000, 55000])
        port_manager.qbit.update_port = AsyncMock(return_value=True)
        port_manager._first_run = True

        await port_manager.handle_port_change()

        port_manager.qbit.update_port.assert_called_once_with(55000)
        assert port_manager.qbit.get_current_port.call_count == 2

        assert port_manager.health_status.gluetun.connected is True
        assert port_manager.health_status.qbittorrent.connected is True
        assert port_manager.health_status.qbittorrent.status == ServiceStatus.OK
        assert port_manager.health_status.qbittorrent.port == 55000
        assert port_manager.health_status.qbittorrent.port_synced is True
        assert port_manager.health_status.is_healthy() is True
        assert port_manager.health_status.last_port_change is not None
        assert port_manager.health_status.last_successful_sync is not None
        assert port_manager.health_status.last_error is None

    @pytest.mark.asyncio
    async def test_last_check_refreshes_each_cycle(self, port_manager, temp_health_file):
        port_manager.gluetun.get_forwarded_port = AsyncMock(return_value=55000)
        port_manager.qbit.get_current_port = AsyncMock(return_value=55000)

        await port_manager.handle_port_change()
        first_check = port_manager.health_status.last_check
        first_gluetun_check = port_manager.health_status.gluetun.last_check
        first_qbit_check = port_manager.health_status.qbittorrent.last_check

        import asyncio
        await asyncio.sleep(0.01)

        port_manager._first_run = False
        await port_manager.handle_port_change()
        second_check = port_manager.health_status.last_check
        second_gluetun_check = port_manager.health_status.gluetun.last_check
        second_qbit_check = port_manager.health_status.qbittorrent.last_check

        assert second_check > first_check
        assert second_gluetun_check > first_gluetun_check
        assert second_qbit_check > first_qbit_check

    @pytest.mark.asyncio
    async def test_handle_port_change_preserves_last_error_on_failure(self, port_manager, temp_health_file):
        port_manager.gluetun.get_forwarded_port = AsyncMock(return_value=None)
        await port_manager.handle_port_change()

        first_error = port_manager.health_status.last_error
        assert first_error is not None

        port_manager._first_run = False
        await port_manager.handle_port_change()

        assert port_manager.health_status.last_error is not None
        assert port_manager.health_status.gluetun.last_error is not None


class TestServiceStatusEnum:
    def test_status_values(self):
        assert ServiceStatus.OK.value == "ok"
        assert ServiceStatus.ERROR.value == "error"
        assert ServiceStatus.AUTH_FAILED.value == "auth_failed"
        assert ServiceStatus.PORT_MISMATCH.value == "port_mismatch"
        assert ServiceStatus.UNKNOWN.value == "unknown"

    def test_status_is_string_subclass(self):
        assert isinstance(ServiceStatus.OK, str)
        assert ServiceStatus.OK == "ok"