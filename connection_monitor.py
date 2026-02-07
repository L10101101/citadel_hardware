from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import QTimer, Qt, QPropertyAnimation, QEasingCurve, QPoint
from PyQt6.QtGui import QPixmap, QPainter, QBrush, QColor
from db_utils import has_internet

class ConnectionNotification(QWidget):
    def __init__(self, parent=None, restored=False):
        super().__init__(parent)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(350, 120)
        
        container = QWidget()
        container.setStyleSheet("""
            QWidget {
                background-color: #FFFFFF;
                border-radius: 15px;
                border: 2px solid #E0E0E0;
            }
        """)
        
        layout = QVBoxLayout(container)
        layout.setSpacing(8)
        layout.setContentsMargins(20, 15, 20, 15)
        
        title_label = QLabel()
        title_label.setStyleSheet("""
            font-size: 16px;
            font-weight: bold;
            color: #064F32;
            border: none;
            background-color: transparent;
        """)
        
        message_label = QLabel()
        message_label.setWordWrap(True)
        message_label.setStyleSheet("""
            font-size: 12px;
            color: #666;
            border: none;
            background-color: transparent;
        """)
        
        if restored:
            title_label.setText("Internet Connection Restored")
            message_label.setText("Cloud services are now available.")
        else:
            title_label.setText("No Internet Connection")
            message_label.setText("Some features may be limited.")
        
        layout.addWidget(title_label)
        layout.addWidget(message_label)
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.addWidget(container)
        self.position_notification()
        
        self.dismiss_timer = QTimer()
        self.dismiss_timer.setSingleShot(True)
        self.dismiss_timer.timeout.connect(self.hide_notification)
        self.dismiss_timer.start(4000)
        
        self.animation = QPropertyAnimation(self, b"pos")
        self.animation.setDuration(300)
        self.animation.setEasingCurve(QEasingCurve.Type.OutCubic)
    
    def position_notification(self):
        if self.parent():
            parent_rect = self.parent().geometry()
            x = parent_rect.width() - self.width() - 20
            y = 20
            self.move(x, y)
    
    def show_notification(self):
        self.position_notification()
        start_pos = QPoint(self.x() + self.width(), self.y())
        end_pos = QPoint(self.x(), self.y())
        self.move(start_pos)
        self.show()
        self.animation.setStartValue(start_pos)
        self.animation.setEndValue(end_pos)
        self.animation.start()
    
    def hide_notification(self):
        start_pos = QPoint(self.x(), self.y())
        end_pos = QPoint(self.x() + self.width(), self.y())
        self.animation.setStartValue(start_pos)
        self.animation.setEndValue(end_pos)
        self.animation.finished.connect(self.hide)
        self.animation.start()

class ConnectionMonitor:
    def __init__(self, main_window):
        self.main_window = main_window
        self.has_connection = True
        self.connection_warning_shown = False
        self._connection_notification = None
        self.connection_check_timer = QTimer()
        self.connection_check_timer.timeout.connect(self.check_internet_connection)
        self.connection_check_timer.start(5000)  # Check every 5 seconds
        
        QTimer.singleShot(1000, self.check_internet_connection_startup)
        QTimer.singleShot(500, self._setup_sync_callbacks)
    
    def _setup_sync_callbacks(self):
        if hasattr(self.main_window, 'sync_manager'):
            sm = self.main_window.sync_manager
            prev_start = getattr(sm, "on_sync_start", None)
            prev_progress = getattr(sm, "on_sync_progress", None)
            prev_complete = getattr(sm, "on_sync_complete", None)
            prev_error = getattr(sm, "on_sync_error", None)

            def chained_start():
                if callable(prev_start):
                    prev_start()
                self._on_sync_start()

            def chained_progress(message: str, percent=None):
                if callable(prev_progress):
                    prev_progress(message, percent)
                self._on_sync_progress(message, percent)

            def chained_complete():
                if callable(prev_complete):
                    prev_complete()
                self._on_sync_complete()

            def chained_error(error: str):
                if callable(prev_error):
                    prev_error(error)
                self._on_sync_error(error)

            sm.on_sync_start = chained_start
            sm.on_sync_progress = chained_progress
            sm.on_sync_complete = chained_complete
            sm.on_sync_error = chained_error
    
    def _on_sync_start(self):
        pass

    def _on_sync_progress(self, message: str, percent=None):
        pass

    def _on_sync_complete(self):
        pass

    def _on_sync_error(self, error: str):
        pass
    
    def update_online_status_icons(self, is_online):
        pixmap = QPixmap(80, 80)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        
        if is_online:
            painter.setBrush(QBrush(QColor(76, 175, 80)))
            painter.setPen(Qt.PenStyle.NoPen)
        else:
            painter.setBrush(QBrush(QColor(244, 67, 54)))
            painter.setPen(Qt.PenStyle.NoPen)
        
        painter.drawEllipse(20, 20, 40, 40)
        painter.end()
        
        if hasattr(self.main_window, 'onlineLabel'):
            self.main_window.onlineLabel.setPixmap(pixmap)
        if hasattr(self.main_window, 'onlineLabel_2'):
            self.main_window.onlineLabel_2.setPixmap(pixmap)
    
    def check_internet_connection_startup(self):
        current_connection = has_internet()
        self.has_connection = current_connection
        self.update_online_status_icons(current_connection)
        
        if not current_connection:
            self.connection_warning_shown = True
            self.show_connection_notification(False)
    
    def check_internet_connection(self):
        current_connection = has_internet()
        self.update_online_status_icons(current_connection)
        
        if self.has_connection and not current_connection:
            self.has_connection = False
            self.connection_warning_shown = True
            self.show_connection_notification(False)
        
        elif not self.has_connection and current_connection:
            self.has_connection = True
            self.connection_warning_shown = False
            self.show_connection_notification(True)
            if hasattr(self.main_window, 'sync_manager'):
                QTimer.singleShot(1000, lambda: self.main_window.sync_manager.sync_now(force_full=False, background=True))
    
    def show_connection_notification(self, restored=False):
        if self._connection_notification:
            self._connection_notification.hide()
            self._connection_notification.deleteLater()
        
        self._connection_notification = ConnectionNotification(self.main_window, restored=restored)
        self._connection_notification.show_notification()
    
    def stop(self):
        if self.connection_check_timer:
            self.connection_check_timer.stop()