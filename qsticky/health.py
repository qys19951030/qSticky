import json
import logging
import os
from datetime import datetime
from typing import Any, Dict, Optional

from .config import HealthStatus


def _isoformat(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


class HealthManager:
    def __init__(self, health_status: HealthStatus, health_file: str, logger: logging.Logger):
        self.health_status = health_status
        self.health_file = health_file
        self.logger = logger
        self.start_time = datetime.now()

    def get_health(self) -> Dict[str, Any]:
        now = datetime.now()
        hs = self.health_status
        return {
            "healthy": hs.is_healthy(),
            "services": {
                "gluetun": {
                    "connected": hs.gluetun.connected,
                    "status": hs.gluetun.status.value,
                    "port": hs.gluetun.port,
                    "last_check": _isoformat(hs.gluetun.last_check),
                    "last_error": hs.gluetun.last_error,
                    "last_success": _isoformat(hs.gluetun.last_success)
                },
                "qbittorrent": {
                    "connected": hs.qbittorrent.connected,
                    "status": hs.qbittorrent.status.value,
                    "port": hs.qbittorrent.port,
                    "port_synced": hs.qbittorrent.port_synced,
                    "last_check": _isoformat(hs.qbittorrent.last_check),
                    "last_error": hs.qbittorrent.last_error,
                    "last_success": _isoformat(hs.qbittorrent.last_success)
                }
            },
            "current_port": hs.current_port,
            "uptime": str(now - self.start_time),
            "last_check": _isoformat(hs.last_check),
            "last_port_change": _isoformat(hs.last_port_change),
            "last_successful_sync": _isoformat(hs.last_successful_sync),
            "last_error": hs.last_error,
            "timestamp": now.isoformat()
        }

    async def update_health_file(self) -> None:
        health_data = self.get_health()
        try:
            health_dir = os.path.dirname(self.health_file)
            os.makedirs(health_dir, exist_ok=True)
            self.logger.debug(f"Writing health status to {self.health_file}")
            with open(self.health_file, 'w') as f:
                json.dump(health_data, f, indent=2)
            self.logger.debug("Successfully wrote health status")
        except Exception as e:
            self.logger.error(f"Failed to write health status: {str(e)}")
