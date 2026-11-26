"""Physical Android device discovery, exclusive file locking, and fleet healthchecks."""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional


class DeviceFleetManager:
    """Manages ADB serial resolution, per-device locks, and fleet health reporting."""

    def __init__(
        self,
        config_path: Optional[Path] = None,
        locks_dir: Optional[Path] = None,
        runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    ):
        self.config_path = config_path
        self.locks_dir = locks_dir or (Path.cwd() / "data" / ".device_locks")
        self.locks_dir.mkdir(parents=True, exist_ok=True)
        self._runner = runner or subprocess.run
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        if self.config_path and self.config_path.is_file():
            try:
                with self.config_path.open("r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    return data
            except Exception:
                pass
        return {"devices": []}

    def get_connected_adb_devices(self) -> Dict[str, str]:
        try:
            res = self._runner(["adb", "devices"], capture_output=True, text=True, timeout=5)
            lines = (res.stdout or "").strip().splitlines()[1:]
            devices: Dict[str, str] = {}
            for line in lines:
                parts = line.strip().split()
                if len(parts) >= 2:
                    devices[parts[0]] = parts[1]
            return devices
        except Exception:
            return {}

    def resolve_active_serial(self, device_id: str) -> Optional[str]:
        connected = self.get_connected_adb_devices()
        for dev in self.config.get("devices", []):
            if dev.get("device_id") != device_id:
                continue
            primary = dev.get("serial")
            if primary and connected.get(primary) == "device":
                return str(primary)
            for fb in dev.get("fallback_serials", []):
                if connected.get(fb) == "device":
                    return str(fb)
        return None

    def acquire_device_lock(
        self,
        device_id: str,
        timeout_sec: float = 5.0,
        stale_after_sec: float = 300.0,
    ) -> bool:
        lock_file = self.locks_dir / f"{device_id}.lock"
        deadline = time.time() + timeout_sec
        while time.time() < deadline:
            if not lock_file.exists():
                try:
                    fd = os.open(str(lock_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    with os.fdopen(fd, "w", encoding="utf-8") as fh:
                        fh.write(f"{os.getpid()}:{time.time()}\n")
                    return True
                except FileExistsError:
                    pass
            else:
                try:
                    if time.time() - lock_file.stat().st_mtime > stale_after_sec:
                        lock_file.unlink(missing_ok=True)
                        continue
                except OSError:
                    pass
            time.sleep(0.1)
        return False

    def release_device_lock(self, device_id: str) -> None:
        (self.locks_dir / f"{device_id}.lock").unlink(missing_ok=True)

    def run_fleet_healthcheck(self) -> List[Dict[str, Any]]:
        connected = self.get_connected_adb_devices()
        configured = self.config.get("devices", [])
        if not configured:
            return [{"serial": serial, "state": state} for serial, state in connected.items()]

        report: List[Dict[str, Any]] = []
        for dev in configured:
            dev_id = dev.get("device_id")
            active_serial = self.resolve_active_serial(str(dev_id)) if dev_id else None
            report.append(
                {
                    "device_id": dev_id,
                    "enabled": bool(dev.get("enabled", True)),
                    "active_serial": active_serial,
                    "online": active_serial is not None,
                }
            )
        return report
