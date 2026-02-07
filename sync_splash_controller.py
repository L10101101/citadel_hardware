from PyQt6.QtCore import QTimer, QMetaObject, Q_ARG, Qt

from face_recognition import load_gallery

class SyncSplashController:
    def __init__(self, main_window, splash_handler):
        self._main = main_window
        self._splash = splash_handler
        self._startup_sync_completed = False
        self._startup_finalized = False
        self._progress_steps = [
            "Connecting to cloud...",
            "Syncing schema from cloud...",
            "Syncing reference data...",
            "Syncing verification methods...",
            "Syncing students...",
            "Syncing fingerprints...",
            "Syncing facial data...",
            "Sync complete",
        ]

    def setup(self):
        if not hasattr(self._main, "sync_manager"):
            return

        def post_progress(msg: str, pct=None):
            p = pct if pct is not None else 0
            QMetaObject.invokeMethod(
                self._main,
                "updateSyncSplash",
                Qt.ConnectionType.QueuedConnection,
                Q_ARG(str, msg),
                Q_ARG(int, p),
            )
        self._main.sync_manager.on_sync_start = lambda: self._on_sync_start()
        self._main.sync_manager.on_sync_progress = post_progress

        def post_complete():
            QMetaObject.invokeMethod(
                self._main,
                "handleSyncComplete",
                Qt.ConnectionType.QueuedConnection,
            )
        self._main.sync_manager.on_sync_complete = post_complete
        self._main.sync_manager.on_sync_error = self._on_sync_error

    def _progress_from_message(self, message: str) -> int | None:
        for idx, step in enumerate(self._progress_steps, start=1):
            if message.strip().startswith(step):
                total = len(self._progress_steps)
                return int(idx * 100 / total)
        return None

    def _on_sync_start(self):
        self._splash.update_sync_screen("Starting sync...", progress=5)

    def _on_sync_progress(self, message: str, percent: int | None = None):
        progress = percent if percent is not None else self._progress_from_message(message)
        self._splash.update_sync_screen(message, progress=progress)

    def _on_sync_complete(self):
        if self._startup_finalized:
            return
        self._startup_sync_completed = True
        self._startup_finalized = True
        self._splash.update_sync_screen("Sync completed successfully", progress=100)
        self._splash.update_sync_screen("Launching Citadel...", progress=100)
        QTimer.singleShot(2000, self._finish_sync_and_show_main)

    def _finish_sync_and_show_main(self):
        self._splash.show_main_after_sync()
        try:
            self._main.gallery = load_gallery()
        except Exception:
            self._main.gallery = getattr(self._main, "gallery", None) or []

    def _on_sync_error(self, error: str):
        if self._startup_finalized:
            return
        self._startup_sync_completed = True
        self._startup_finalized = True
        no_internet = "no internet" in (error or "").lower()
        if no_internet:
            message = "Sync Failed: No Internet Connection"
        else:
            message = f"Sync Failed: {error}" if error else "Syncing Data Failed."
        self._splash.update_sync_screen(message, progress=100, error=True, no_internet=no_internet)
        try:
            self._main.gallery = load_gallery()
        except Exception:
            self._main.gallery = getattr(self._main, "gallery", None) or []
        QTimer.singleShot(2000, self._splash.show_main_after_sync)