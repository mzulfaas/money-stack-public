"""Fast Apple Silicon Vision OCR wrapper and modal dialog detector."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple


DEFAULT_DIALOG_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "Discard / Save Draft",
        "triggers": ["discard thread", "save draft", "don't save", "hapus utas", "simpan draf"],
        "dismiss_buttons": ["discard", "don't save", "jangan simpan", "hapus", "cancel", "batal"],
    },
    {
        "name": "Password Manager",
        "triggers": ["google password manager", "choose saved password", "pengelola sandi google"],
        "dismiss_buttons": ["cancel", "batal", "close", "tutup"],
    },
    {
        "name": "Save Login Info",
        "triggers": ["save your login info", "save login info", "simpan info login"],
        "dismiss_buttons": ["not now", "lain kali", "cancel", "batal"],
    },
]


def detect_dialog_in_boxes(
    boxes: Sequence[Dict[str, Any]],
    dialog_definitions: Sequence[Dict[str, Any]] = DEFAULT_DIALOG_DEFINITIONS,
) -> Optional[Tuple[str, Optional[Dict[str, Any]]]]:
    """Inspects OCR boxes for known modal prompts and returns (dialog_name, dismiss_box)."""
    all_text = " | ".join(str(b.get("text", "")).lower() for b in boxes)
    for dialog in dialog_definitions:
        triggers = [str(t).lower() for t in dialog.get("triggers", ())]
        if not any(t in all_text for t in triggers):
            continue
        # Prefer exact button label match before substring fallback so dialog titles aren't tapped
        for btn_kw in dialog.get("dismiss_buttons", ()):
            btn_low = str(btn_kw).lower()
            for box in boxes:
                if str(box.get("text", "")).strip().lower() == btn_low:
                    return str(dialog["name"]), box
        for btn_kw in dialog.get("dismiss_buttons", ()):
            btn_low = str(btn_kw).lower()
            for box in boxes:
                box_low = str(box.get("text", "")).strip().lower()
                if btn_low in box_low and not box_low.endswith("?"):
                    return str(dialog["name"]), box
        return str(dialog["name"]), None
    return None


class VisionOCRDriver:
    """Runs the compiled native macOS Vision OCR helper (`ocr_screen`)."""

    def __init__(self, ocr_bin_path: Path):
        self.ocr_bin_path = ocr_bin_path

    def recognize_image(self, image_path: Path) -> List[Dict[str, Any]]:
        if not self.ocr_bin_path.is_file():
            raise FileNotFoundError(
                f"Vision OCR binary not found at {self.ocr_bin_path}. "
                "Compile native/ocr_screen.swift with `swiftc -O native/ocr_screen.swift -o bin/ocr_screen` on macOS."
            )
        res = subprocess.run(
            [str(self.ocr_bin_path), str(image_path), "--json"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if res.returncode != 0:
            raise RuntimeError(f"ocr_screen failed: {res.stderr.strip()}")
        data = json.loads(res.stdout or "[]")
        return data if isinstance(data, list) else []
