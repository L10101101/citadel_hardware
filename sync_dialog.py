from PyQt6.QtWidgets import (
    QApplication,
    QDialog,
    QVBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QHBoxLayout,
)
from PyQt6.QtCore import QTimer, Qt, QEventLoop
from data_sync import DataSyncManager
from db_utils import has_internet

class SyncDialog(QDialog):
    _PROGRESS_STEPS = [
        "Connecting to cloud...",
        "Syncing schema from cloud...",
        "Syncing reference data...",
        "Syncing verification methods...",
        "Syncing students...",
        "Syncing fingerprints...",
        "Syncing facial data...",
        "Syncing slideshow...",
        "Sync complete",
    ]

    def __init__(
        self,
        parent=None,
        *,
        title: str = "Citadel",
        sync_manager: DataSyncManager | None = None,
        allow_offline: bool = False,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"{title} - Syncing Data")
        self.setModal(True)
        self.setFixedSize(480, 220)
        self.setWindowFlags(
            Qt.WindowType.Dialog
            | Qt.WindowType.FramelessWindowHint
        )
        self.setObjectName("syncDialog")
        self.setStyleSheet(
            """
            #syncDialog {
                background-color: #f7f9fb;
                border-radius: 14px;
            }
            QProgressBar {
                border: 1px solid #d0d4da;
                border-radius: 8px;
                background-color: #E0E0E0;
            }
            QProgressBar::chunk {
                border-radius: 8px;
                background-color: #4CAF50;
            }
            QPushButton { border-radius: 6px; padding: 6px 12px; }
            """
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title_label = QLabel("Syncing data from cloud...", self)
        title_label.setStyleSheet("font-size: 14px; font-weight: bold; color: #064F32;")
        layout.addWidget(title_label)

        self.status_label = QLabel("Preparing...", self)
        self.status_label.setStyleSheet("color: #555; font-size: 12px;")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        self.button_layout = QHBoxLayout()
        self.button_layout.addStretch()
        self.retry_btn = QPushButton("Retry", self)
        self.retry_btn.setVisible(False)
        self.retry_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #2E7D32;
                color: white;
                font-weight: bold;
            }
            """
        )
        self.exit_btn = QPushButton("Exit", self)
        self.exit_btn.setVisible(False)
        self.exit_btn.setStyleSheet(
            """
            QPushButton {
                background-color: #E0E0E0;
                color: #C62828;
                font-weight: bold;
            }
            """
        )
        self.button_layout.addWidget(self.retry_btn)
        self.button_layout.addWidget(self.exit_btn)
        layout.addLayout(self.button_layout)

        self.sync_manager = sync_manager or DataSyncManager()
        self._allow_offline = allow_offline
        self._sync_failed = False
        self._sync_started = False
        self._last_progress = ""
        self._poll_timer = QTimer(self)
        self._poll_timer.timeout.connect(self._poll_sync_status)

        self.retry_btn.clicked.connect(self._on_retry)
        self.exit_btn.clicked.connect(self.reject)

    def _poll_sync_status(self):
        if not self._sync_started:
            return
        msg = getattr(self.sync_manager, "sync_progress", "") or ""
        if self.sync_manager.is_syncing:
            if msg and msg != self._last_progress:
                self._last_progress = msg
                progress = self._progress_from_message(msg)
                self._update_ui(msg, progress)
        else:
            self._poll_timer.stop()
            self._sync_started = False
            if "Sync complete" in msg or msg.strip() == "Sync complete":
                self.handleSyncComplete()
            else:
                err = msg if msg else "Sync failed"
                self.handleSyncError(err)

    def _progress_from_message(self, message: str) -> int:
        msg = (message or "").strip()
        for idx, step in enumerate(self._PROGRESS_STEPS, start=1):
            if msg.startswith(step) or step in msg:
                return int(idx * 100 / len(self._PROGRESS_STEPS))
        return 0

    def _update_ui(self, message: str, progress: int):
        self.status_label.setText(message or "Preparing...")
        if not self._sync_failed:
            self.progress_bar.setRange(0, 0)
        if self._sync_failed:
            self.progress_bar.setStyleSheet(
                "QProgressBar { border: 1px solid #d0d4da; border-radius: 8px; background-color: #FDE0DC; }"
                "QProgressBar::chunk { border-radius: 8px; background-color: #F44336; }"
            )
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def handleSyncComplete(self):
        self._sync_failed = False
        self.status_label.setText("Sync completed successfully")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        QTimer.singleShot(800, self.accept)

    def handleSyncError(self, error: str):
        self._sync_failed = True
        # Detect no-internet both from the error text and the actual network state.
        no_internet = "no internet" in (error or "").lower() or not has_internet()
        msg = "No internet connection." if no_internet else (error or "Sync failed.")
        self.status_label.setText(f"Sync failed: {msg}")
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(100)
        self.progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #d0d4da; border-radius: 8px; background-color: #FDE0DC; }"
            "QProgressBar::chunk { border-radius: 8px; background-color: #F44336; }"
        )

        # For callers that explicitly allow offline mode (e.g. Citadel main),
        # automatically proceed instead of forcing Retry/Exit on no-internet errors.
        if no_internet and self._allow_offline:
            QTimer.singleShot(800, self.accept)
            return

        self.retry_btn.setVisible(True)
        self.exit_btn.setVisible(True)

    def _on_retry(self):
        self.retry_btn.setVisible(False)
        self.exit_btn.setVisible(False)
        self._sync_failed = False
        self.progress_bar.setRange(0, 0)
        self.progress_bar.setStyleSheet(
            "QProgressBar { border: 1px solid #d0d4da; border-radius: 8px; background-color: #E0E0E0; }"
            "QProgressBar::chunk { border-radius: 8px; background-color: #4CAF50; }"
        )
        self._sync_started = True
        self._last_progress = ""
        self._update_ui("Retrying...", 0)
        self._poll_timer.start(150)
        self.sync_manager.sync_now(force_full=True, background=True)

    def showEvent(self, event):
        super().showEvent(event)
        self._sync_started = True
        self._last_progress = ""
        self._update_ui("Connecting to cloud...", 0)
        self._poll_timer.start(150)
        self.sync_manager.sync_now(force_full=True, background=True)
