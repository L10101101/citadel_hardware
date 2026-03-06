import sys
import time
import os
import logging
from collections import deque, Counter
import cv2
import gui.resource_rc

from PyQt6.QtWidgets import (
    QApplication,
    QMainWindow,
    QLineEdit,
    QMessageBox,
    QDialog,
    QLabel,
    QGraphicsOpacityEffect,
    QWidget,
    QHBoxLayout,
    QSizePolicy,
)

from PyQt6 import QtCore
from PyQt6.QtCore import QTimer, QDateTime, QPropertyAnimation, QEasingCurve
from PyQt6.QtGui import QPixmap, QPainterPath, QRegion, QPainter
from main_ui import Ui_Citadel
from emergency_mode import EmergencyModeController
from finger_thread import FingerprintThread
from camera_handler import CameraHandler
from verification_handler import VerificationHandler
from marquee_label import FooterMarquee
from connection_monitor import ConnectionMonitor
from data_sync import DataSyncManager
from sync_dialog import SyncDialog
from face_lockout import FaceLockoutGuard
from utils import (
    lookup_student,
    log_entry,
    resource_path,
    get_daily_summary_counts,
    get_top_program_remaining,
    get_slideshow_images_local,
    format_program_label,
)

from config_store import get_slideshow_config
from async_email_notifier import notify_parent_task
from async_sms_notifier import notify_parent_sms_task
from utils import set_sync_manager
from status_labels import (
    StatusLabelController,
    status_entry_logged,
    status_unrecognized,
)
from app_logging import configure_logging

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow, Ui_Citadel):
    def __init__(self, sync_manager: DataSyncManager):
        super().__init__()
        self.setupUi(self)
        self._fix_resource_paths()
        self.camera_handler = CameraHandler(self)
        self.verification_handler = VerificationHandler(self)
        self.status_labels = StatusLabelController(self.statusLabel, getattr(self, "cameraFeed", None))
        self._default_prompt_text = "Scan QR then Verify Face or Scan Fingerprint for Identification"
        self._header_label_effect = None
        self._header_label_fade = None
        self._last_face_icon_opacity = None
        self._last_fingerprint_icon_opacity = None
        self._last_missing_text = None
        if hasattr(self, "label"):
            self._init_header_label_transition()
            self._set_header_label_text(self._default_prompt_text, animate=False)
        self._showing_student_details = False
        self._camera_available = True
        self._fingerprint_available = True
        self._had_missing_devices = False
        self._init_verification_icons()
        self.reset_info()
        self.active_action = None
        self.verification_active = False
        self.current_qr = None
        self._suppress_feed = False
        self.last_logged = {}
        self._face_vote_window = deque(maxlen=12)
        self._face_required_votes = 8
        self._face_min_verify_seconds = 1.2
        self._face_verify_started_at = 0.0
        self._face_accept_cooldown_until = 0.0
        self._face_lockout = FaceLockoutGuard(
            trigger_count=max(3, int(os.environ.get("FACE_LOCKOUT_TRIGGER_COUNT", "10"))),
            lockout_seconds=max(0.5, float(os.environ.get("FACE_LOCKOUT_SECONDS", "1.5"))),
            notice_interval_seconds=max(0.2, float(os.environ.get("FACE_LOCKOUT_NOTICE_INTERVAL", "0.6"))),
        )
        self._face_metrics_log_every = max(0, int(os.environ.get("FACE_RESULT_METRICS_LOG_EVERY", "0")))
        self._face_metrics_total = 0
        self._face_metrics_ok = 0
        self._face_metrics_fail = 0
        self._face_metrics_lockout_suppressed = 0
        self._face_metrics_fail_reasons = Counter()
        self._face_specific_errors = {
            "Too dark",
            "Too bright",
            "Too blurry",
            "Face too small",
            "No Face Detected",
            "Invalid Crop",
        }

        self._init_summary_display()
        self._init_slideshow()
        self.emergency_mode = EmergencyModeController(self)
        if hasattr(self, "projectLogoLabel"):
            self.projectLogoLabel.installEventFilter(self)
            self.projectLogoLabel.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)

        self.time_timer = QTimer()
        self.time_timer.timeout.connect(self.update_datetime)
        self.time_timer.start(1000)

        self.footer_marquee1 = FooterMarquee(self.footerLabel, speed=35, padding=40, left_to_right=True)

        self.fingerprint_thread = FingerprintThread()
        self.fingerprint_thread.fingerprintDetected.connect(
            self.verification_handler.fingerprint_verified
        )
        self.fingerprint_thread.deviceAvailabilityChanged.connect(
            self._on_fingerprint_device_availability_changed
        )
        self.fingerprint_thread.start()
        self.fingerprint_thread.activate()
        self.camera_thread = None

        self.hiddenInput = QLineEdit(self)
        self.hiddenInput.setGeometry(-100, -100, 10, 10)
        self.hiddenInput.setFocus()
        self.hiddenInput.returnPressed.connect(
            lambda: self.verification_handler.on_qr_input_received(self.hiddenInput.text())
        )

        self.reset_verification_state()
        self.inactivity_timer = QTimer()
        self.inactivity_timer.setInterval(2000)
        QTimer.singleShot(500, self.start_inactivity_timer)
        self.reset_info_timer = QTimer()
        self.reset_info_timer.setSingleShot(True)
        self.reset_info_timer.timeout.connect(self._run_scheduled_reset)
        self.idle_sync_timer = QTimer()
        self.idle_sync_timer.setSingleShot(True)
        self.idle_sync_timer.setInterval(10 * 60 * 1000)
        self.idle_sync_timer.timeout.connect(self._on_idle_sync_timeout)
        self.face_timeout_timer = QTimer()
        self.face_timeout_timer.setSingleShot(True)
        self.face_timeout_timer.timeout.connect(
            self.verification_handler.on_face_timeout
        )
        self._slideshow_vertical_padding_px = 20
        QTimer.singleShot(300, self._apply_missing_device_message)

        self.connection_monitor = ConnectionMonitor(self)
        self.sync_manager = sync_manager
        set_sync_manager(self.sync_manager)
        self.sync_manager.start()
        self._reset_idle_sync_timer()

        try:
            from face_recognition import load_gallery, get_model_health
            self.gallery = load_gallery()
            models_ok, model_msg = get_model_health()
            if not models_ok:
                self.set_status(model_msg, "#FF6666")
        except Exception:
            self.gallery = []

    def _init_header_label_transition(self):
        if not hasattr(self, "label"):
            return
        effect = QGraphicsOpacityEffect(self.label)
        effect.setOpacity(1.0)
        self.label.setGraphicsEffect(effect)
        self._header_label_effect = effect
        anim = QPropertyAnimation(effect, b"opacity")
        anim.setDuration(140)
        anim.setStartValue(0.82)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutQuad)
        self._header_label_fade = anim

    def _set_header_label_text(self, text: str, animate: bool = True):
        if not hasattr(self, "label"):
            return
        if self.label.text() == text:
            return
        if animate and self._header_label_effect is not None and self._header_label_fade is not None:
            self._header_label_fade.stop()
            self._header_label_effect.setOpacity(0.82)
            self.label.setText(text)
            self._header_label_fade.start()
            return
        self.label.setText(text)

    def _probe_camera_available(self) -> bool:
        previous_level = None
        try:
            if hasattr(cv2, "getLogLevel") and hasattr(cv2, "setLogLevel"):
                previous_level = cv2.getLogLevel()
                silent_level = getattr(cv2, "LOG_LEVEL_SILENT", 0)
                cv2.setLogLevel(silent_level)
        except Exception:
            previous_level = None

        backends = []
        if hasattr(cv2, "CAP_DSHOW"):
            backends.append(cv2.CAP_DSHOW)
        if hasattr(cv2, "CAP_MSMF"):
            backends.append(cv2.CAP_MSMF)
        if not backends:
            backends.append(cv2.CAP_ANY)

        try:
            for backend in backends:
                cap = cv2.VideoCapture(0, backend)
                try:
                    if cap.isOpened():
                        return True
                finally:
                    try:
                        cap.release()
                    except Exception:
                        pass
            return False
        finally:
            try:
                if previous_level is not None and hasattr(cv2, "setLogLevel"):
                    cv2.setLogLevel(previous_level)
            except Exception:
                pass

    def _missing_devices(self) -> list[str]:
        missing = []
        if not self._camera_available:
            missing.append("Camera")
        if not self._fingerprint_available:
            missing.append("Fingerprint Sensor")
        return missing

    def has_missing_devices(self) -> bool:
        return bool(self._missing_devices())

    def has_no_scan_devices_available(self) -> bool:
        return (not self._camera_available) and (not self._fingerprint_available)

    def ensure_fingerprint_ready(self, show_status: bool = False) -> bool:
        if self._fingerprint_available:
            return True
        if show_status:
            self.set_status("Missing device: Fingerprint Sensor", "#FF6666")
        return False

    def ensure_qr_ready(self, show_status: bool = False) -> bool:
        camera_running = bool(
            self.camera_handler
            and self.camera_handler.camera_thread
            and self.camera_handler.camera_thread.isRunning()
        )
        if camera_running:
            self._camera_available = True
        else:
            self._camera_available = self._probe_camera_available()
        self._apply_missing_device_message()
        if self._camera_available:
            return True
        if show_status:
            self.set_status("Missing device: Camera", "#FF6666")
        return False

    def _apply_missing_device_message(self):
        if not hasattr(self, "label"):
            return
        if getattr(self, "verification_active", False):
            return
        if getattr(self, "_showing_student_details", False):
            return
        self._apply_device_icon_opacity()
        missing = self._missing_devices()
        had_missing = self._had_missing_devices
        self._had_missing_devices = bool(missing)
        if missing:
            if self.has_no_scan_devices_available():
                if hasattr(self, "slideshow_idle_timer"):
                    self.slideshow_idle_timer.stop()
                self._stop_slideshow()
            text = f"Missing device(s): {', '.join(missing)}"
            self._last_missing_text = text
            self._set_header_label_text(text)
        else:
            self._last_missing_text = None
            self._set_header_label_text(self._default_prompt_text)
            if had_missing:
                self._resume_scanning_after_reconnect()

    def _resume_scanning_after_reconnect(self):
        self.cancel_reset_info()
        self.reset_verification_state()
        self.reset_info()
        self.fingerprint_thread.activate()
        self.hiddenInput.setEnabled(True)
        self._focus_hidden_input()

    def _on_fingerprint_device_availability_changed(self, available: bool):
        self._fingerprint_available = bool(available)
        self._apply_missing_device_message()

    def on_camera_device_availability_changed(self, available: bool):
        self._camera_available = bool(available)
        self._apply_missing_device_message()

    def _decode_slideshow_pixmaps(self, images):
        decoded = []
        for data in images:
            if not data:
                continue
            pixmap = QPixmap()
            if pixmap.loadFromData(data):
                decoded.append(pixmap)
        return decoded

    def _refresh_slideshow_mask(self, size):
        if not hasattr(self, "slideshowLabel"):
            return
        w = max(1, size.width())
        h = max(1, size.height())
        size_key = (w, h)
        if getattr(self, "_slideshow_mask_size_key", None) == size_key:
            return
        radius = 20
        rect = QtCore.QRectF(0, 0, w, h)
        path = QPainterPath()
        path.addRoundedRect(rect, radius, radius)
        self.slideshowLabel.setMask(QRegion(path.toFillPolygon().toPolygon()))
        self._slideshow_mask_size_key = size_key

    def _next_slideshow_source_pixmap(self):
        if not self._slideshow_images:
            return None
        self._slideshow_index = (self._slideshow_index + 1) % len(self._slideshow_images)
        return self._slideshow_images[self._slideshow_index]

    def _apply_scaled_slideshow_pixmap(self, source_pixmap: QPixmap):
        if source_pixmap is None or source_pixmap.isNull():
            return
        if not hasattr(self, "displayWidget"):
            return
        size = self.displayWidget.size()
        if size.width() <= 0 or size.height() <= 0:
            return
        self._refresh_slideshow_mask(size)
        target_w = size.width()
        target_h = size.height()
        padding = max(
            0,
            int(
                getattr(
                    self,
                    "_slideshow_vertical_padding_px",
                    getattr(self, "_slideshow_vertical_bleed_px", 20),
                )
            ),
        )
        drawable_h = max(1, target_h - (padding * 2))
        scaled = source_pixmap.scaled(
            target_w,
            drawable_h,
            QtCore.Qt.AspectRatioMode.IgnoreAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        frame = QPixmap(target_w, target_h)
        frame.fill(QtCore.Qt.GlobalColor.transparent)
        x = 0
        y = padding
        painter = QPainter(frame)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(x, y, scaled)
        painter.end()
        self.slideshowLabel.setPixmap(frame)

    def _refresh_current_slideshow_pixmap(self):
        source = getattr(self, "_slideshow_current_source_pixmap", None)
        if source is None or source.isNull():
            return
        self._apply_scaled_slideshow_pixmap(source)

    def _fix_resource_paths(self):
        for label, rel_path in (
            (getattr(self, "logoLabel", None), "gui/assets/UCC_Logo.ico"),
            (getattr(self, "projectLogoLabel", None), "gui/assets/logo.png"),
        ):
            if label is None:
                continue
            p = resource_path(rel_path)
            pix = QPixmap(p)
            if pix.isNull():
                continue
            pix = pix.scaled(
                label.size(),
                QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                QtCore.Qt.TransformationMode.SmoothTransformation,
            )
            label.setPixmap(pix)

    def _init_slideshow(self):
        cfg = get_slideshow_config()
        raw_images = get_slideshow_images_local()
        self._slideshow_images = self._decode_slideshow_pixmaps(raw_images)
        self._slideshow_interval_ms = max(2000, int(cfg.get("interval", 5)) * 1000)
        self._slideshow_index = -1
        self._slideshow_active = False
        self._slideshow_current_source_pixmap = None
        self._slideshow_mask_size_key = None

        self.slideshowLabel = QLabel(parent=self.displayWidget)
        self.slideshowLabel.setObjectName("slideshowLabel")
        self.slideshowLabel.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.slideshowLabel.setScaledContents(False)
        self.slideshowLabel.setVisible(False)
        self.displayLayout.addWidget(self.slideshowLabel, 0, 0, 1, 1)

        self._slideshow_effect = QGraphicsOpacityEffect(self.slideshowLabel)
        self._slideshow_effect.setOpacity(1.0)
        self.slideshowLabel.setGraphicsEffect(self._slideshow_effect)

        self._slideshow_fade_out = QPropertyAnimation(self._slideshow_effect, b"opacity")
        self._slideshow_fade_out.setDuration(120)
        self._slideshow_fade_out.setStartValue(1.0)
        self._slideshow_fade_out.setEndValue(0.0)
        self._slideshow_fade_out.setEasingCurve(QEasingCurve.Type.OutQuad)

        self._slideshow_fade_in = QPropertyAnimation(self._slideshow_effect, b"opacity")
        self._slideshow_fade_in.setDuration(180)
        self._slideshow_fade_in.setStartValue(0.0)
        self._slideshow_fade_in.setEndValue(1.0)
        self._slideshow_fade_in.setEasingCurve(QEasingCurve.Type.InQuad)

        self.slideshow_idle_timer = QTimer()
        self.slideshow_idle_timer.setSingleShot(True)
        self.slideshow_idle_timer.setInterval(15000)
        self.slideshow_idle_timer.timeout.connect(self._start_slideshow)

        self.slideshow_cycle_timer = QTimer()
        self.slideshow_cycle_timer.setInterval(self._slideshow_interval_ms)
        self.slideshow_cycle_timer.timeout.connect(self._next_slideshow_image)

        self._reset_slideshow_timer()

    def _focus_hidden_input(self):
        if not hasattr(self, "hiddenInput"):
            return
        if not self.hiddenInput.isEnabled():
            return
        self.hiddenInput.setFocus()

    def _reset_slideshow_timer(self):
        self._stop_slideshow()
        if getattr(self, "emergency_mode", None) and self.emergency_mode.active:
            return
        if self.has_no_scan_devices_available():
            if hasattr(self, "slideshow_idle_timer"):
                self.slideshow_idle_timer.stop()
            return
        if self._slideshow_images:
            self.slideshow_idle_timer.start()

    def _start_slideshow(self):
        if getattr(self, "emergency_mode", None) and self.emergency_mode.active:
            return
        if getattr(self, "verification_active", False) or getattr(self, "_showing_student_details", False):
            if hasattr(self, "slideshow_idle_timer"):
                self.slideshow_idle_timer.start()
            return
        if self.has_no_scan_devices_available():
            return
        if not self._slideshow_images:
            return
        self.reset_info()
        self._slideshow_active = True
        if hasattr(self, "detailsWidget"):
            self.detailsWidget.setVisible(False)
        self.slideshowLabel.setVisible(True)
        self.slideshowLabel.raise_()
        self._slideshow_index = -1
        self._next_slideshow_image()
        self.slideshow_cycle_timer.start()
        self._focus_hidden_input()

    def _stop_slideshow(self):
        if getattr(self, "_slideshow_active", False):
            self._slideshow_active = False
        if hasattr(self, "slideshow_cycle_timer"):
            self.slideshow_cycle_timer.stop()
        if hasattr(self, "slideshowLabel"):
            self.slideshowLabel.setVisible(False)
        if hasattr(self, "detailsWidget"):
            self.detailsWidget.setVisible(True)
        self._focus_hidden_input()

    def _next_slideshow_image(self):
        source_pixmap = self._next_slideshow_source_pixmap()
        if source_pixmap is None:
            return
        self._slideshow_current_source_pixmap = source_pixmap
        if self._slideshow_active:
            self._fade_to_slideshow_pixmap(source_pixmap)
        else:
            self._apply_scaled_slideshow_pixmap(source_pixmap)

    def _fade_to_slideshow_pixmap(self, source_pixmap: QPixmap):
        if source_pixmap is None or source_pixmap.isNull():
            return
        self._slideshow_fade_out.stop()
        self._slideshow_fade_in.stop()

        def _after_fade_out():
            self._apply_scaled_slideshow_pixmap(source_pixmap)
            self._slideshow_fade_in.start()

        try:
            self._slideshow_fade_out.finished.disconnect()
        except Exception:
            pass
        self._slideshow_fade_out.finished.connect(_after_fade_out)
        self._slideshow_fade_out.start()

    def _init_summary_display(self):
        for label in (self.firstDetailLabel, self.secondDetailLabel, self.thirdDetailLabel):
            label.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            label.setWordWrap(True)

        self._summary_mode = "counts"
        self._update_summary_counts()

        self.summary_timer = QTimer()
        self.summary_timer.setInterval(15000)
        self.summary_timer.timeout.connect(self._toggle_summary)
        self.summary_timer.start()

    def _init_verification_icons(self):
        if not hasattr(self, "detailsLayout"):
            return
        if not hasattr(self, "spacerLabel_1"):
            self.spacerLabel_1 = QLabel(parent=self.detailsWidget)
            self.spacerLabel_1.setObjectName("spacerLabel_1")
            self.spacerLabel_1.setMinimumSize(0, 50)
            self.spacerLabel_1.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            self.spacerLabel_1.setText("")
            insert_idx = self.detailsLayout.indexOf(self.nameLabel) if hasattr(self, "nameLabel") else -1
            if insert_idx >= 0:
                self.detailsLayout.insertWidget(insert_idx, self.spacerLabel_1)
            else:
                self.detailsLayout.addWidget(self.spacerLabel_1)
        self.verificationIconsWidget = QWidget(parent=self.detailsWidget)
        self.verificationIconsWidget.setObjectName("verificationIconsWidget")
        self.verificationIconsWidget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.verificationIconsWidget.setMinimumHeight(180)
        row = QHBoxLayout(self.verificationIconsWidget)
        row.setContentsMargins(0, 8, 0, 8)
        row.setSpacing(28)

        self.qrGuideIcon = QLabel(self.verificationIconsWidget)
        self.qrGuideIcon.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.qrGuideIcon.setMinimumSize(140, 140)
        self.qrGuideIcon.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.faceGuideIcon = QLabel(self.verificationIconsWidget)
        self.faceGuideIcon.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.faceGuideIcon.setMinimumSize(140, 140)
        self.faceGuideIcon.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        self.fingerprintGuideIcon = QLabel(self.verificationIconsWidget)
        self.fingerprintGuideIcon.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self.fingerprintGuideIcon.setMinimumSize(140, 140)
        self.fingerprintGuideIcon.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)

        row.addStretch(1)
        row.addWidget(self.qrGuideIcon)
        row.addWidget(self.faceGuideIcon)
        row.addWidget(self.fingerprintGuideIcon)
        row.addStretch(1)

        insert_index = self.detailsLayout.indexOf(self.nameLabel) if hasattr(self, "nameLabel") else -1
        if insert_index >= 0:
            self.detailsLayout.insertWidget(insert_index, self.verificationIconsWidget)
        else:
            self.detailsLayout.addWidget(self.verificationIconsWidget)
        self._verification_icon_mode = "idle"
        self._apply_verification_icon_pixmaps()

    def _apply_verification_icon_pixmaps(self):
        if not hasattr(self, "qrGuideIcon") or not hasattr(self, "faceGuideIcon") or not hasattr(self, "fingerprintGuideIcon"):
            return

        mode = getattr(self, "_verification_icon_mode", "idle")
        items = []
        if mode == "qr_face":
            items = [
                (self.faceGuideIcon, "gui/assets/face-unselected.png"),
            ]
        elif mode == "qr_fingerprint":
            items = [
                (self.fingerprintGuideIcon, "gui/assets/fingerprint-unselected.png"),
            ]
        elif mode == "qr_only":
            items = [
                (self.qrGuideIcon, "gui/assets/qr.png"),
            ]
        else:
            items = [
                (self.faceGuideIcon, "gui/assets/face-unselected.png"),
                (self.fingerprintGuideIcon, "gui/assets/fingerprint-unselected.png"),
            ]

        for icon in (self.qrGuideIcon, self.faceGuideIcon, self.fingerprintGuideIcon):
            icon.setVisible(False)

        target = 150
        if mode != "idle" and hasattr(self, "verificationIconsWidget"):
            container = self.verificationIconsWidget.size()
            visible_count = max(1, len(items))
            if visible_count == 1:
                target = max(120, min(220, min(container.height() - 16, container.width() // 2)))
            else:
                target = max(140, min(180, min(container.height() - 16, container.width() // (visible_count + 1))))

        for icon, rel_path in items:
            pixmap = QPixmap(resource_path(rel_path))
            if not pixmap.isNull():
                icon.setPixmap(
                    pixmap.scaled(
                        QtCore.QSize(target, target),
                        QtCore.Qt.AspectRatioMode.KeepAspectRatio,
                        QtCore.Qt.TransformationMode.SmoothTransformation,
                    )
                )
            icon.setVisible(True)
        self._apply_device_icon_opacity()

    def _set_icon_opacity(self, icon: QLabel, opacity: float):
        effect = icon.graphicsEffect()
        if not isinstance(effect, QGraphicsOpacityEffect):
            effect = QGraphicsOpacityEffect(icon)
            icon.setGraphicsEffect(effect)
        if abs(effect.opacity() - opacity) > 0.01:
            effect.setOpacity(opacity)

    def _apply_device_icon_opacity(self):
        face_opacity = 1.0 if self._camera_available else 0.3
        finger_opacity = 1.0 if self._fingerprint_available else 0.3
        if (
            self._last_face_icon_opacity == face_opacity
            and self._last_fingerprint_icon_opacity == finger_opacity
        ):
            return
        if hasattr(self, "faceGuideIcon"):
            self._set_icon_opacity(self.faceGuideIcon, face_opacity)
        if hasattr(self, "fingerprintGuideIcon"):
            self._set_icon_opacity(self.fingerprintGuideIcon, finger_opacity)
        self._last_face_icon_opacity = face_opacity
        self._last_fingerprint_icon_opacity = finger_opacity

    def set_verification_icons_mode(self, mode: str):
        self._verification_icon_mode = mode
        if hasattr(self, "verificationIconsWidget"):
            self.verificationIconsWidget.setVisible(True)
        self._apply_verification_icon_pixmaps()

    def _set_spacer_verification_icon(self, verification_mode: str | None):
        if not hasattr(self, "spacerLabel_1"):
            return
        mode_to_asset = {
            "qr_face": "gui/assets/face-unselected.png",
            "qr_fingerprint": "gui/assets/fingerprint-unselected.png",
            "qr_only": "gui/assets/qr.png",
        }
        asset = mode_to_asset.get(verification_mode or "")
        if not asset:
            self.spacerLabel_1.setPixmap(QPixmap())
            self.spacerLabel_1.setText("")
            self.spacerLabel_1.setMinimumHeight(50)
            return

        pixmap = QPixmap(resource_path(asset))
        if pixmap.isNull():
            self.spacerLabel_1.setPixmap(QPixmap())
            return
        target_h = max(130, min(240, self.spacerLabel_1.height() or 180))
        scaled = pixmap.scaled(
            QtCore.QSize(target_h, target_h),
            QtCore.Qt.AspectRatioMode.KeepAspectRatio,
            QtCore.Qt.TransformationMode.SmoothTransformation,
        )
        self.spacerLabel_1.setText("")
        self.spacerLabel_1.setMinimumHeight(target_h + 8)
        self.spacerLabel_1.setPixmap(scaled)

    def _toggle_summary(self):
        if self._summary_mode == "counts":
            self._summary_mode = "programs"
            self._update_program_summary()
        else:
            self._summary_mode = "counts"
            self._update_summary_counts()

    def _update_summary_counts(self):
        in_campus, out_campus, total = get_daily_summary_counts()
        self.summaryLabel.setText("SUMMARY")
        self.firstDetailLabel.setText(f"STUDENTS INSIDE\n{in_campus}")
        self.secondDetailLabel.setText(f"STUDENTS OUTSIDE\n{out_campus}")
        self.thirdDetailLabel.setText(f"DAILY ACTIVE STUDENTS\n{total}")

    def _update_program_summary(self):
        top_programs = get_top_program_remaining(limit=3)
        self.summaryLabel.setText("STUDENTS IN CAMPUS")
        lines = []
        for _, (program_name, count) in enumerate(top_programs, start=1):
            lines.append(f"{format_program_label(program_name)}\n{count}")
        while len(lines) < 3:
            lines.append("-")
        self.firstDetailLabel.setText(lines[0])
        self.secondDetailLabel.setText(lines[1])
        self.thirdDetailLabel.setText(lines[2])

    def refresh_monitoring_summary(self):
        if getattr(self, "_summary_mode", "counts") == "programs":
            self._update_program_summary()
        else:
            self._update_summary_counts()

    def show_page(self, page_name):
        self.fingerprint_thread.activate()
        self.hiddenInput.setEnabled(True)
        self.hiddenInput.setFocus()
        self.reset_verification_state()
        
    def update_datetime(self):
        self.dateTimeLabel.setText(QDateTime.currentDateTime().toString("MMM dd, yyyy - hh:mm AP").upper())

    def on_face_result(self, ok, info, box):
        if self._suppress_feed or not self.verification_active:
            return
        if info in ("Recognition model unavailable", "Liveness model unavailable"):
            self._record_face_result_metric(False, info)
            self.camera_handler.stop_camera()
            self.camera_handler.close_camera_window()
            self.face_timeout_timer.stop()
            self.reset_verification_state()
            self.set_status(info, "#FF6666")
            self.schedule_reset_info(7000)
            return
        now = time.monotonic()
        if self._face_lockout.in_lockout(now):
            self._face_metrics_lockout_suppressed += 1
            if self._face_lockout.should_emit_notice(now):
                self.set_status("Hold still and center your face", "#FFA500")
            if box:
                self.camera_handler.draw_face_box(box, False)
            return
        self._record_face_result_metric(ok, info)
        self._face_vote_window.append(bool(ok))
        if not ok:
            self._face_accept_cooldown_until = now + 0.8
            if self._face_lockout.register_result(False, now):
                self._face_vote_window.clear()
                self.set_status("Hold still and center your face", "#FFA500")
                if box:
                    self.camera_handler.draw_face_box(box, False)
                return
        if ok:
            self._face_lockout.register_result(True, now)
            enough_time = (now - self._face_verify_started_at) >= self._face_min_verify_seconds
            in_cooldown = now < self._face_accept_cooldown_until
            enough_votes = (
                len(self._face_vote_window) >= self._face_required_votes
                and sum(1 for v in self._face_vote_window if v) >= self._face_required_votes
            )
            if not enough_time or in_cooldown or not enough_votes:
                if box:
                    self.camera_handler.draw_face_box(box, False)
                return
            self.camera_handler.stop_camera()
            self.camera_handler.close_camera_window()
            self.face_timeout_timer.stop()
            self.qr_verified_success(self.current_qr, info)
            self.current_qr = None
        else:
            if isinstance(info, str) and info in self._face_specific_errors:
                self.set_status(info, "#FF6666")
            else:
                status_unrecognized(self.set_status)
        if box:
            self.camera_handler.draw_face_box(box, ok)

    def _record_face_result_metric(self, ok: bool, info) -> None:
        if self._face_metrics_log_every <= 0:
            return
        self._face_metrics_total += 1
        if ok:
            self._face_metrics_ok += 1
        else:
            self._face_metrics_fail += 1
            reason = info if isinstance(info, str) and info else "Unknown"
            self._face_metrics_fail_reasons[reason] += 1
        if self._face_metrics_total % self._face_metrics_log_every != 0:
            return
        success_rate = (self._face_metrics_ok / self._face_metrics_total) if self._face_metrics_total else 0.0
        top_failures = ", ".join(
            f"{name}:{count}"
            for name, count in self._face_metrics_fail_reasons.most_common(3)
        ) or "-"
        logger.info(
            "face_result_metrics total=%d ok=%d fail=%d success_rate=%.3f lockout_suppressed=%d top_failures=%s",
            self._face_metrics_total,
            self._face_metrics_ok,
            self._face_metrics_fail,
            success_rate,
            self._face_metrics_lockout_suppressed,
            top_failures,
        )

    def qr_verified_success(self, student_no, name=None):
        student = lookup_student(student_no)
        if student:
            name, program, year_section = student
        else:
            name, program, year_section = "Unknown", "-", "-"

        self.update_ui_verified(student_no, name, program, year_section, "Student Enrolled", verification_mode="qr_face")
        status_entry_logged(self.set_status)
        success = log_entry(
            student_no,
            method_id=1,
            set_status=self.set_status,
        )
        if success:
            self.refresh_monitoring_summary()
            self.schedule_reset_info(8000)
        else:
            self.schedule_reset_info(8000)

        notify_parent_task(student_no)
        notify_parent_sms_task(student_no)
        self.inactivity_timer.start()
        self.verification_active = False
        self.current_qr = None
        self.hiddenInput.setEnabled(True)
        self.fingerprint_thread.activate()
        self._focus_hidden_input()

    def update_ui_verified(self, student_no, name, program, year_section, status, verification_mode=None):
        if getattr(self, "emergency_mode", None) and self.emergency_mode.active:
            return
        self._showing_student_details = True
        self.setUpdatesEnabled(False)
        try:
            masked_student_no = student_no
            if student_no:
                visible_tail = student_no[6:] if len(student_no) > 6 else ""
                masked_student_no = f"******{visible_tail}"
            if hasattr(self, "label"):
                self._set_header_label_text("STUDENT DATA")
            if hasattr(self, "spacerLabel_1"):
                self.spacerLabel_1.setText("")
            if hasattr(self, "verificationIconsWidget"):
                self.verificationIconsWidget.setVisible(False)
            self._set_spacer_verification_icon(verification_mode)
            if verification_mode:
                self._verification_icon_mode = verification_mode
            self.nameLabel.setText(name)
            self.programLabel.setText(program)
            self.yearSecLabel.setText(year_section)
            self.idLabel.setText(masked_student_no)
            self.entryLabel.setText(
                QDateTime.currentDateTime().toString("dddd | MMM d, yyyy | hh:mm AP")
            )
            self.statusLabel.setText(status)
        finally:
            self.setUpdatesEnabled(True)
            self.update()

    def set_status(self, text, color, reset_info=False):
        self.status_labels.set_status(text, color, reset_info=reset_info)

    def schedule_reset_info(self, delay_ms=7000):
        if hasattr(self, "reset_info_timer"):
            self.reset_info_timer.stop()
            self.reset_info_timer.start(delay_ms)

    def cancel_reset_info(self):
        if hasattr(self, "reset_info_timer"):
            self.reset_info_timer.stop()

    def _run_scheduled_reset(self):
        self.reset_verification_state()
        self.reset_info()

    def start_inactivity_timer(self):
        self.inactivity_timer.start()
        self.camera_handler.clear_camera_feed()

    def reset_info(self):
        if getattr(self, "emergency_mode", None) and self.emergency_mode.active:
            return
        self._showing_student_details = False
        self.cancel_reset_info()
        self.setUpdatesEnabled(False)
        try:
            self.camera_handler.clear_camera_feed()
            if hasattr(self, "label"):
                self._set_header_label_text(self._default_prompt_text)
            if hasattr(self, "spacerLabel_1"):
                self.spacerLabel_1.setText("")
            self._set_spacer_verification_icon(None)
            if hasattr(self, "verificationIconsWidget"):
                self.set_verification_icons_mode("idle")
            self.nameLabel.setText("")
            self.idLabel.setText("")
            self.programLabel.setText("")
            self.yearSecLabel.setText("")
            self.entryLabel.setText("")
            self.statusLabel.setText("")
            self.statusLabel.setStyleSheet(
                """
                background-color: white;
                color: black;
                font-weight: bold;
                border-radius: 10px;
                padding: 5px;
                """
            )
        finally:
            self.setUpdatesEnabled(True)
            self.update()
        self._apply_missing_device_message()

    def reset_verification_state(self):
        self.verification_active = False
        self.current_qr = None
        self._face_vote_window.clear()
        self._face_verify_started_at = 0.0
        self._face_accept_cooldown_until = 0.0
        self._face_lockout.reset()
        self.hiddenInput.setEnabled(True)
        self.fingerprint_thread.activate()
        self.camera_handler.stop_camera()
        self.camera_handler.close_camera_window()
        self._focus_hidden_input()

    def start_face_verification_window(self):
        self._face_vote_window.clear()
        self._face_verify_started_at = time.monotonic()
        self._face_accept_cooldown_until = self._face_verify_started_at
        self._face_lockout.reset()

    def register_activity(self):
        self._reset_idle_sync_timer()
        self._reset_slideshow_timer()

    def _reset_idle_sync_timer(self):
        if hasattr(self, "idle_sync_timer"):
            self.idle_sync_timer.start()

    def _on_idle_sync_timeout(self):
        if self.verification_active:
            self._reset_idle_sync_timer()
            return
        if hasattr(self, "sync_manager") and self.sync_manager and self.sync_manager.is_syncing:
            self._reset_idle_sync_timer()
            return
        if hasattr(self, "sync_manager") and self.sync_manager:
            self.sync_manager.sync_now(force_full=False, background=True)

    def showEvent(self, event):
        super().showEvent(event)
        self._reset_slideshow_timer()

    def eventFilter(self, watched, event):
        if watched is getattr(self, "projectLogoLabel", None):
            if event.type() == QtCore.QEvent.Type.MouseButtonPress:
                if getattr(self, "emergency_mode", None):
                    self.emergency_mode.toggle()
                return True
        return super().eventFilter(watched, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._apply_verification_icon_pixmaps()
        if hasattr(self, "spacerLabel_1") and self.spacerLabel_1.pixmap() is not None and not self.spacerLabel_1.pixmap().isNull():
            mode = getattr(self, "_verification_icon_mode", None)
            if mode in ("qr_face", "qr_fingerprint", "qr_only"):
                self._set_spacer_verification_icon(mode)
        if getattr(self, "_slideshow_active", False) and getattr(self, "_slideshow_current_source_pixmap", None):
            self._refresh_current_slideshow_pixmap()
        elif hasattr(self, "displayWidget"):
            self._refresh_slideshow_mask(self.displayWidget.size())

    def closeEvent(self, event):
        confirm = QMessageBox(self)
        confirm.setWindowTitle("Exit Citadel")
        confirm.setText("Exit Application?")
        confirm.setIcon(QMessageBox.Icon.Question)
        confirm.setWindowFlags(
            QtCore.Qt.WindowType.Dialog | QtCore.Qt.WindowType.FramelessWindowHint
        )
        yes_btn = confirm.addButton("Yes", QMessageBox.ButtonRole.AcceptRole)
        no_btn = confirm.addButton("No", QMessageBox.ButtonRole.RejectRole)
        confirm.setDefaultButton(no_btn)
        confirm.setStyleSheet(
            """
            QMessageBox {
                background-color: #f7f9fb;
            }
            QLabel {
                color: #1f1f1f;
                font-weight: bold;
            }
            QPushButton {
                border-radius: 8px;
                padding: 8px 16px;
                font-weight: bold;
                min-width: 90px;
            }
            """
        )
        yes_btn.setStyleSheet("background-color: #2E7D32; color: white;")
        no_btn.setStyleSheet("background-color: #E0E0E0; color: #C62828;")
        confirm.exec()
        if confirm.clickedButton() != yes_btn:
            event.ignore()
            return

        if hasattr(self, "connection_monitor"):
            self.connection_monitor.stop()
        if hasattr(self, "sync_manager"):
            self.sync_manager.stop()
        if getattr(self, "face_thread", None) and self.face_thread.isRunning():
            self.face_thread.quit()
            self.face_thread.wait(2000)
        if getattr(self, "camera_thread", None) and self.camera_thread.isRunning():
            self.camera_thread.stop()
            self.camera_thread.wait(2000)
        if getattr(self, "fingerprint_thread", None):
            self.fingerprint_thread.stop()
            self.fingerprint_thread.wait(2000)
        super().closeEvent(event)


if __name__ == "__main__":
    configure_logging("citadel-main")
    app = QApplication(sys.argv)
    from system_checks import check_postgresql_installed
    ok, msg = check_postgresql_installed()
    if not ok:
        QMessageBox.critical(None, "PostgreSQL Required", msg)
        sys.exit(1)
    from config_store import is_configured, validate_runtime_config
    from setup_wizard import run_setup_wizard
    if not is_configured():
        if not run_setup_wizard():
            sys.exit(0)
    valid_cfg, cfg_msg = validate_runtime_config()
    if not valid_cfg:
        QMessageBox.critical(None, "Configuration Required", cfg_msg)
        sys.exit(1)

    sync_dlg = SyncDialog(title="Citadel", allow_offline=True)
    if sync_dlg.exec() != QDialog.DialogCode.Accepted:
        sys.exit(0)
    set_sync_manager(sync_dlg.sync_manager)
    window = MainWindow(sync_manager=sync_dlg.sync_manager)
    window.showFullScreen()
    sys.exit(app.exec())
