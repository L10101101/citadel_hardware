from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QProgressBar, QApplication
from PyQt6.QtCore import Qt, QEventLoop

from utils import resource_path
DEFAULT_LOGO_PATH = resource_path("gui/assets/logo.png")
DEFAULT_TITLE = "Syncing Data"
DEFAULT_SUBTITLE = "University of Caloocan City"
BACKGROUND_COLOR = "rgba(232, 234, 240, 255)"
TITLE_COLOR = "#064F32"
SUBTITLE_COLOR = "#555"
STATUS_COLOR = "#666"

_PROGRESS_STYLE_GREEN = (
    "QProgressBar {"
    "  border: 1px solid #CCCCCC;"
    "  border-radius: 8px;"
    "  background-color: #E0E0E0;"
    "}"
    "QProgressBar::chunk {"
    "  border-radius: 8px;"
    "  background-color: #4CAF50;"
    "}"
)
_PROGRESS_STYLE_RED = (
    "QProgressBar {"
    "  border: 1px solid #CCCCCC;"
    "  border-radius: 8px;"
    "  background-color: #FDE0DC;"
    "}"
    "QProgressBar::chunk {"
    "  border-radius: 8px;"
    "  background-color: #F44336;"
    "}"
)

class SyncSplashHandler:
    def __init__(self, main_window):
        self._main = main_window

    def update_sync_screen(
        self,
        message: str,
        progress: int | None = None,
        *,
        error: bool = False,
        no_internet: bool = False,
    ) -> None:
        if hasattr(self._main, "syncStatusLabel") and self._main.syncStatusLabel:
            self._main.syncStatusLabel.setText(message or "Preparing...")
            self._main.syncStatusLabel.show()
        if hasattr(self._main, "syncProgressBar") and self._main.syncProgressBar:
            if error or no_internet:
                self._main.syncProgressBar.setRange(0, 100)
                self._main.syncProgressBar.setValue(100)
                self._main.syncProgressBar.setStyleSheet(
                    "QProgressBar { border: 1px solid #CCCCCC; border-radius: 8px;"
                    " background-color: #FDE0DC; }"
                    "QProgressBar::chunk { border-radius: 8px; background-color: #F44336; }"
                )
            else:
                self._main.syncProgressBar.setStyleSheet(
                    "QProgressBar { border: 1px solid #CCCCCC; border-radius: 8px;"
                    " background-color: #E0E0E0; }"
                    "QProgressBar::chunk { border-radius: 8px; background-color: #4CAF50; }"
                )
                if progress is not None:
                    p = max(0, min(100, progress))
                    self._main.syncProgressBar.setRange(0, 100)
                    self._main.syncProgressBar.setValue(p)
        QApplication.processEvents(QEventLoop.ProcessEventsFlag.ExcludeUserInputEvents)

    def show_main_after_sync(self) -> None:
        self._main.stackedWidget.setCurrentWidget(self._main.page_main)
        self._main.toolBar.show()
        self._main.show_page("main")
        self._main.showFullScreen()


class SyncSplashScreen(QWidget):
    def __init__(
        self,
        parent: QWidget,
        *,
        logo_path: str | None = DEFAULT_LOGO_PATH,
        title: str = DEFAULT_TITLE,
        subtitle: str | None = DEFAULT_SUBTITLE,
    ):
        super().__init__(parent)
        self._title = title
        self._subtitle = subtitle
        self._logo_path = logo_path

        self.setStyleSheet(f"""
            QWidget {{
                background-color: {BACKGROUND_COLOR};
            }}
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        self._title_label = QLabel(title)
        self._title_label.setStyleSheet(f"""
            font-size: 42px;
            font-weight: bold;
            color: {TITLE_COLOR};
            background-color: transparent;
            border: none;
        """)
        self._title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self._title_label)

        if subtitle:
            self._subtitle_label = QLabel(subtitle)
            self._subtitle_label.setStyleSheet(f"""
                font-size: 20px;
                color: {SUBTITLE_COLOR};
                background-color: transparent;
                border: none;
            """)
            self._subtitle_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(self._subtitle_label)
        else:
            self._subtitle_label = None

        self.status_label.setStyleSheet(f"""
            font-size: 22px;
            color: {STATUS_COLOR};
            background-color: transparent;
            border: none;
        """)
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self._progress_bar = QProgressBar(self)
        self._progress_bar.setMinimumSize(280, 18)
        self._progress_bar.setMaximumHeight(22)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(_PROGRESS_STYLE_GREEN)
        layout.addWidget(self._progress_bar, alignment=Qt.AlignmentFlag.AlignCenter)

        self.setGeometry(0, 0, 1920, 1080)

    def update_message(self, text: str) -> None:
        self.status_label.setText(text)

    def set_progress(self, percent: int | None, *, error: bool = False, no_internet: bool = False) -> None:
        if error or no_internet:
            self._progress_bar.setRange(0, 100)
            self._progress_bar.setValue(100)
            self._progress_bar.setStyleSheet(_PROGRESS_STYLE_RED)
        else:
            self._progress_bar.setStyleSheet(_PROGRESS_STYLE_GREEN)
            if percent is not None:
                p = max(0, min(100, percent))
                self._progress_bar.setRange(0, 100)
                self._progress_bar.setValue(p)

    def set_title(self, text: str) -> None:
        self._title_label.setText(text)

    def set_subtitle(self, text: str | None) -> None:
        if self._subtitle_label is not None:
            if text:
                self._subtitle_label.setText(text)
                self._subtitle_label.show()
            else:
                self._subtitle_label.hide()