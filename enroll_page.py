from PyQt6.QtWidgets import QWidget, QPushButton, QLineEdit, QLabel
from PyQt6.QtCore import Qt, QTimer
import psycopg2
from face_enroll_thread import FaceEnrollWorker
from finger_enroll_thread import FingerEnrollWorker
from marquee_label import FooterMarquee

class EnrollPage:
    def __init__(self, page_enroll: QWidget, main_window=None):
        self.page = page_enroll
        self.selected_mode = None
        self.worker = None
        self._hidden_input = None
        self._hidden_input_prev_policy = None
        self.main = main_window
        self.footer_marquee = None

        # --- Find widgets from .ui ---
        self.btnFace = self.page.findChild(QPushButton, "btnFace")
        self.btnFinger = self.page.findChild(QPushButton, "btnFinger")
        self.btnSubmit = self.page.findChild(QPushButton, "btnSubmit")
        self.txtStudentNo = self.page.findChild(QLineEdit, "txtStudentNo")
        self.lblStatus = self.page.findChild(QLabel, "lblStatus")
        self.footerLabel_2 = self.page.findChild(QLabel, "footerLabel_2")

        # --- Initial State ---
        if self.txtStudentNo:
            self.txtStudentNo.setReadOnly(True)
            self.txtStudentNo.setPlaceholderText("Select enrollment type first...")

        if self.btnSubmit:
            self.btnSubmit.setEnabled(False)

        self.init_footer_marquee()

        # --- Connect buttons ---
        if self.btnFace:
            self.btnFace.clicked.connect(lambda: self.select_mode("face"))
        if self.btnFinger:
            self.btnFinger.clicked.connect(lambda: self.select_mode("finger"))
        if self.btnSubmit:
            self.btnSubmit.clicked.connect(self.start_enrollment)

        self.set_status("Select enrollment type to start.", "orange")

    # -----------------------------------------------------------------
    def set_status(self, text: str, color: str):
        if self.lblStatus:
            self.lblStatus.setText(text)
            self.lblStatus.setStyleSheet(
                f"color: white; background-color: {color}; font-weight: bold; padding: 4px; border-radius: 4px;"
            )

    def init_footer_marquee(self):
        self.footer_marquee = FooterMarquee(
            self.footerLabel_2, speed=35, padding=40, left_to_right=True
        )

    # -----------------------------------------------------------------
    def _locate_hidden_input(self):
        if self._hidden_input:
            return self._hidden_input
        wnd = self.page.window()
        hidden = getattr(wnd, "hiddenInput", None)
        if not hidden and wnd:
            hidden = wnd.findChild(QLineEdit, "hiddenInput")
        if hidden:
            self._hidden_input = hidden
        return hidden

    def _disable_hidden_input_focus(self):
        hidden = self._locate_hidden_input()
        if not hidden:
            return
        self._hidden_input_prev_policy = hidden.focusPolicy()
        hidden.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        if hidden.hasFocus():
            hidden.clearFocus()

    def _restore_hidden_input_focus(self):
        hidden = self._locate_hidden_input()
        if not hidden or self._hidden_input_prev_policy is None:
            return
        hidden.setFocusPolicy(self._hidden_input_prev_policy)
        self._hidden_input_prev_policy = None

    # -----------------------------------------------------------------
    def select_mode(self, mode):
        self.selected_mode = mode
        self._disable_hidden_input_focus()

        if self.txtStudentNo:
            self.txtStudentNo.setReadOnly(False)
            self.txtStudentNo.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
            self.txtStudentNo.setFocus(Qt.FocusReason.MouseFocusReason)

        if self.btnSubmit:
            self.btnSubmit.setEnabled(True)

        self.set_status(
            "Facial enrollment selected." if mode == "face" else "Fingerprint enrollment selected.",
            "orange"
        )
    
    def update_camera_feed(self, frame):
        from PyQt6.QtGui import QImage, QPixmap
        h, w, ch = frame.shape
        bytes_per_line = ch * w
        qimg = QImage(frame.data, w, h, bytes_per_line, QImage.Format.Format_BGR888)
        camera_label = self.page.findChild(QLabel, "cameraFeed_2")
        if camera_label:
            camera_label.setPixmap(
                QPixmap.fromImage(qimg).scaled(
                    camera_label.width(),
                    camera_label.height(),
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
            )

    # -----------------------------------------------------------------
    def start_enrollment(self):
        student_no = self.txtStudentNo.text().strip() if self.txtStudentNo else ""

        if not student_no:
            self.set_status("Please enter student number.", "red")
            return

        if not self.student_exists(student_no):
            self.set_status(f"Student {student_no} not found in database.", "red")
            return

        if self.selected_mode == "face" and self.is_already_enrolled(student_no, "face"):
            self.set_status(f"Student {student_no} already has a face record.", "red")
            return

        if self.selected_mode == "finger" and self.is_already_enrolled(student_no, "finger"):
            self.set_status(f"Student {student_no} already has a fingerprint record.", "red")
            return

        self.set_inputs_enabled(False)

        wnd = self.page.window()

        # --- Stop any existing enrollment thread safely ---
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
            self.worker = None

        if self.selected_mode == "face":
            self.set_status("Starting facial enrollment...", "orange")
            camera_label = self.page.findChild(QLabel, "cameraFeed_2")
            self.worker = FaceEnrollWorker(student_no, label_widget=camera_label)
            self.worker.frameReady.connect(self.update_camera_feed)
            self.worker.finished.connect(self.on_enroll_done)
            self.worker.start()

        elif self.selected_mode == "finger":
            if hasattr(wnd, "fingerprint_thread"):
                wnd.fingerprint_thread.deactivate()
            self.set_status("Starting fingerprint enrollment...", "orange")
            self.worker = FingerEnrollWorker(student_no)
            self.worker.finished.connect(self.on_enroll_done)
            self.worker.start()

        else:
            self.set_status("Please select an enrollment type.", "red")

    # -----------------------------------------------------------------
    def set_inputs_enabled(self, enabled: bool):
        if self.btnFace:
            self.btnFace.setEnabled(enabled)
        if self.btnFinger:
            self.btnFinger.setEnabled(enabled)
        if self.txtStudentNo:
            self.txtStudentNo.setEnabled(enabled)
            if enabled and not self.selected_mode:
                self.txtStudentNo.setReadOnly(True)
        if self.btnSubmit:
            self.btnSubmit.setEnabled(enabled)
        if enabled:
            self._restore_hidden_input_focus()

    # -----------------------------------------------------------------
    def student_exists(self, student_no):
        conn = psycopg2.connect(
            dbname="citadel_db",
            user="postgres",
            password="postgres",
            host="127.0.0.1",
            port=5432
        )
        cur = conn.cursor()
        cur.execute("SELECT 1 FROM students WHERE student_no = %s", (student_no,))
        found = cur.fetchone() is not None
        cur.close()
        conn.close()
        return found

    def is_already_enrolled(self, student_no, mode):
        conn = psycopg2.connect(
            dbname="citadel_db",
            user="postgres",
            password="postgres",
            host="127.0.0.1",
            port=5432
        )
        cur = conn.cursor()
        if mode == "face":
            cur.execute("SELECT facial_recognition_data FROM students WHERE student_no = %s", (student_no,))
            result = cur.fetchone()
            exists = result is not None and result[0] is not None
        elif mode == "finger":
            cur.execute("SELECT 1 FROM fingerprints WHERE student_no = %s", (student_no,))
            exists = cur.fetchone() is not None
        else:
            exists = False
        cur.close()
        conn.close()
        return exists

    # -----------------------------------------------------------------
    def on_enroll_done(self, success, msg):
        color = "green" if success else "red"
        self.set_status(msg, color)

        # Reset UI
        self.selected_mode = None
        if self.txtStudentNo:
            self.txtStudentNo.clear()
            self.txtStudentNo.setReadOnly(True)
            self.txtStudentNo.setPlaceholderText("Select enrollment type first...")

        self.set_inputs_enabled(True)

        wnd = self.page.window()

        # --- Reload face gallery + reset models ---
        if success and hasattr(wnd, "verification_handler"):
            try:
                from face_recognition import load_gallery, reset_models
                reset_models()  # ensures models reinitialized
                new_gallery = load_gallery(force_reload=True)
                wnd.verification_handler.gallery = new_gallery
                print(f"[EnrollPage] Face models and gallery reloaded ({len(new_gallery)} records).")
            except Exception as e:
                print(f"[EnrollPage] Failed to reload face models/gallery: {e}")

        # --- Reactivate fingerprint reader ---
        def reset_reader():
            if not hasattr(wnd, "fingerprint_thread"):
                return
            with wnd.fingerprint_thread._lock:
                if wnd.fingerprint_thread.reader:
                    try:
                        wnd.fingerprint_thread.reader.close()
                    except Exception:
                        pass
                wnd.fingerprint_thread.reader = None
            wnd.fingerprint_thread.activate()

        QTimer.singleShot(100, reset_reader)

    # -----------------------------------------------------------------
    def stop_enrollment(self):
        """Stop any running enrollment thread safely."""
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait()
            self.worker = None
