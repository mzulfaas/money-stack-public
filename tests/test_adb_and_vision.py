"""Tests for ADB UI driver guards, device fleet locks, and Vision OCR dialog detection."""

import json
import subprocess
from pathlib import Path

import pytest

from money_stack.adb import ADBUIDriver, DeviceFleetManager, detect_dialog_in_boxes


def _completed(stdout: str = "", returncode: int = 0) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(args=["adb"], returncode=returncode, stdout=stdout, stderr="")


def test_adb_driver_scales_coords_and_blocks_launcher_taps():
    calls = []

    def fake_runner(cmd, capture_output=True, text=True):
        calls.append(cmd)
        if "wm" in cmd:
            return _completed("Physical size: 1080x2400\nOverride size: 1080x2400\n")
        if "dumpsys" in cmd:
            return _completed("mCurrentFocus=Window{abc u0 com.sec.android.app.launcher/com.sec.android.app.launcher.Launcher}")
        return _completed()

    driver = ADBUIDriver("127.0.0.1:15555", base_width=720, base_height=1600, runner=fake_runner)
    assert driver.scale_coords(360, 800) == (540, 1200)

    with pytest.raises(RuntimeError, match="ZERO_MISCLICK_ABORT"):
        driver.tap(100, 200, delay_after=0)


def test_adb_driver_taps_scaled_coordinates_inside_target_app():
    calls = []

    def fake_runner(cmd, capture_output=True, text=True):
        calls.append(cmd)
        if "wm" in cmd:
            return _completed("Physical size: 1080x2400\n")
        if "dumpsys" in cmd:
            return _completed("mCurrentFocus=Window{abc u0 com.instagram.barcelona/com.instagram.main.MainActivity}")
        return _completed()

    driver = ADBUIDriver("DEVICE-1", base_width=720, base_height=1600, runner=fake_runner)
    driver.tap(100, 200, delay_after=0)
    assert ["adb", "-s", "DEVICE-1", "shell", "input", "tap", "150", "300"] in calls


def test_device_fleet_manager_resolution_and_locks(tmp_path: Path):
    cfg_path = tmp_path / "devices.json"
    cfg_path.write_text(
        json.dumps(
            {
                "devices": [
                    {"device_id": "phone-a", "serial": "offline-usb", "fallback_serials": ["127.0.0.1:15555"]},
                ]
            }
        ),
        encoding="utf-8",
    )

    def fake_runner(cmd, capture_output=True, text=True, timeout=5):
        return _completed("List of devices attached\n127.0.0.1:15555\tdevice\n")

    mgr = DeviceFleetManager(config_path=cfg_path, locks_dir=tmp_path / "locks", runner=fake_runner)
    assert mgr.resolve_active_serial("phone-a") == "127.0.0.1:15555"
    assert mgr.acquire_device_lock("phone-a", timeout_sec=0.5) is True
    assert mgr.acquire_device_lock("phone-a", timeout_sec=0.2) is False
    mgr.release_device_lock("phone-a")
    assert mgr.acquire_device_lock("phone-a", timeout_sec=0.5) is True


def test_detect_dialog_in_boxes_finds_dismiss_button():
    boxes = [
        {"text": "Discard thread?", "center_x": 360, "center_y": 700},
        {"text": "Save draft", "center_x": 360, "center_y": 820},
        {"text": "Discard", "center_x": 360, "center_y": 900},
    ]
    detected = detect_dialog_in_boxes(boxes)
    assert detected is not None
    name, btn = detected
    assert name == "Discard / Save Draft"
    assert btn is not None
    assert btn["center_y"] == 900
