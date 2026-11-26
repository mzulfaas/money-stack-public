"""Resilient Android ADB UI driver with Zero-Misclick launcher guard and screen scaling."""

from __future__ import annotations

import re
import subprocess
import time
from typing import Callable, List, Optional, Tuple

FORBIDDEN_LAUNCHER_PACKAGES = {
    "com.sec.android.app.kidshome",
    "com.sec.android.app.launcher",
    "com.google.android.apps.nexuslauncher",
    "com.miui.home",
    "com.sonyericsson.home",
    "com.android.launcher",
    "com.android.launcher3",
}


class ADBUIDriver:
    """Controls a single Android device via ADB with launcher/misclick protection."""

    def __init__(
        self,
        device: str,
        base_width: int = 720,
        base_height: int = 1600,
        runner: Optional[Callable[..., subprocess.CompletedProcess]] = None,
    ):
        self.device = device
        self.base_width = base_width
        self.base_height = base_height
        self._runner = runner or subprocess.run
        self._target_w, self._target_h = self._detect_screen_size()
        self.scale_x = self._target_w / float(self.base_width)
        self.scale_y = self._target_h / float(self.base_height)

    def run_adb(self, cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
        full_cmd = ["adb", "-s", self.device, *cmd]
        res = self._runner(full_cmd, capture_output=True, text=True)
        if check and res.returncode != 0:
            raise RuntimeError(f"ADB error ({' '.join(full_cmd)}): {res.stderr.strip()}")
        return res

    def _detect_screen_size(self) -> Tuple[int, int]:
        res = self.run_adb(["shell", "wm", "size"], check=False)
        for pattern in (r"Override size:\s*(\d+)x(\d+)", r"Physical size:\s*(\d+)x(\d+)"):
            match = re.search(pattern, res.stdout or "")
            if match:
                return int(match.group(1)), int(match.group(2))
        return self.base_width, self.base_height

    def get_foreground_app(self) -> Tuple[Optional[str], Optional[str]]:
        res = self.run_adb(["shell", "dumpsys", "window"], check=False)
        match = re.search(
            r"mCurrentFocus=Window\{[^\}]+\s+([a-zA-Z0-9_\.]+)/([a-zA-Z0-9_\.]+)",
            res.stdout or "",
        )
        if match:
            return match.group(1), match.group(2)
        return None, None

    def assert_safe_device(self) -> None:
        pkg, _ = self.get_foreground_app()
        if pkg in FORBIDDEN_LAUNCHER_PACKAGES:
            raise RuntimeError(
                f"[ZERO_MISCLICK_ABORT] Device {self.device} is on Launcher ({pkg}). Aborting touch action."
            )

    def ensure_foreground(self, package_name: str, wait_timeout: float = 5.0) -> bool:
        deadline = time.time() + wait_timeout
        while time.time() < deadline:
            pkg, _ = self.get_foreground_app()
            if pkg == package_name:
                return True
            self.run_adb(
                ["shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"],
                check=False,
            )
            time.sleep(1.0)
        return False

    def scale_coords(self, x: int, y: int) -> Tuple[int, int]:
        if self._target_w == self.base_width and self._target_h == self.base_height:
            return x, y
        return int(round(x * self.scale_x)), int(round(y * self.scale_y))

    def tap(self, x: int, y: int, delay_after: float = 0.2, is_scaled: bool = False) -> None:
        self.assert_safe_device()
        sx, sy = (x, y) if is_scaled else self.scale_coords(x, y)
        self.run_adb(["shell", "input", "tap", str(sx), str(sy)])
        if delay_after > 0:
            time.sleep(delay_after)

    def swipe(
        self,
        x1: int,
        y1: int,
        x2: int,
        y2: int,
        duration_ms: int = 300,
        is_scaled: bool = False,
    ) -> None:
        self.assert_safe_device()
        sx1, sy1 = (x1, y1) if is_scaled else self.scale_coords(x1, y1)
        sx2, sy2 = (x2, y2) if is_scaled else self.scale_coords(x2, y2)
        self.run_adb(["shell", "input", "swipe", str(sx1), str(sy1), str(sx2), str(sy2), str(duration_ms)])

    def press_back(self) -> None:
        self.assert_safe_device()
        self.run_adb(["shell", "input", "keyevent", "4"])
