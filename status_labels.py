from __future__ import annotations
from typing import Callable, Optional
from PyQt6.QtWidgets import QLabel


class StatusLabelController:
    def __init__(
        self,
        status_label: QLabel,
        camera_feed_label: Optional[QLabel] = None,
        reset_info_fn: Optional[Callable[[], None]] = None,
    ):
        self._status_label = status_label
        self._camera_feed_label = camera_feed_label
        self._reset_info_fn = reset_info_fn

    def set_status(self, text: str, color: str, reset_info: bool = False) -> None:
        if reset_info and self._reset_info_fn:
            try:
                self._reset_info_fn()
            except Exception:
                pass
        self._status_label.setText(text)
        self._status_label.setStyleSheet(
            f"""
            background-color: {color};
            color: white;
            font-weight: bold;
            border-radius: 10px;
            padding: 5px;
        """
        )
        self._apply_camera_background(color)

    def set_camera_background(self, color: str) -> None:
        """Update camera feed background color (letterbox only, does not cover video)."""
        self._apply_camera_background(color)

    def _apply_camera_background(self, color: str) -> None:
        if self._camera_feed_label:
            self._camera_feed_label.setStyleSheet(
                f"""
                background-color: {color};
                border-radius: 20px;
            """
            )


SetStatusFn = Callable[..., None]

COLOR_SUCCESS = "#77EE77"
COLOR_ERROR = "#FF6666"
COLOR_WARN = "#FFA500"


def status_cloud_unavailable(set_status: SetStatusFn) -> None:
    set_status("Cloud Unavailable", COLOR_ERROR, True)
    

def status_entry_already_logged(set_status: SetStatusFn) -> None:
    set_status("Entry Already Logged", COLOR_ERROR)


def status_entry_logged(set_status: SetStatusFn) -> None:
    set_status("Entry Logged", COLOR_SUCCESS)


def status_cannot_enter_yet(set_status: SetStatusFn) -> None:
    set_status("Cannot Enter Yet", COLOR_ERROR)


def status_cannot_exit_yet(set_status: SetStatusFn) -> None:
    set_status("Cannot Exit Yet", COLOR_ERROR)


def status_exit_already_logged(set_status: SetStatusFn) -> None:
    set_status("Exit Already Logged", COLOR_ERROR)


def status_exit_logged(set_status: SetStatusFn) -> None:
    set_status("Exit Logged", COLOR_SUCCESS)


def status_no_fingerprint_data(set_status: SetStatusFn) -> None:
    set_status("No Fingerprint Data", COLOR_ERROR)


def status_not_enrolled(set_status: SetStatusFn) -> None:
    set_status("Not Enrolled", COLOR_ERROR)


def status_qr_verified(set_status: SetStatusFn) -> None:
    set_status("QR Verified", COLOR_WARN)


def status_unrecognized(set_status: SetStatusFn) -> None:
    set_status("Unrecognized", COLOR_ERROR)
