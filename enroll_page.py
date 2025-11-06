from PyQt6.QtWidgets import QWidget, QMessageBox, QPushButton, QLineEdit, QLabel, QFrame
from PyQt6.QtCore import Qt
import psycopg2
from face_enroll_thread import FaceEnrollWorker
from finger_enroll_thread import FingerEnrollWorker


class EnrollPage:
    def __init__(self, page_enroll: QWidget):
        self.page = page_enroll
        self.selected_mode = None
        self.worker = None
        self._hidden_input = None
        self._hidden_input_prev_policy = None

        # --- Find widgets from .ui ---
        self.btnFace = self.page.findChild(QPushButton, "btnFace")
        self.btnFinger = self.page.findChild(QPushButton, "btnFinger")
        self.btnSubmit = self.page.findChild(QPushButton, "btnSubmit")
        self.txtStudentNo = self.page.findChild(QLineEdit, "txtStudentNo")
        self.lblStatus = self.page.findChild(QLabel, "lblStatus")

        # --- Initial State ---
        if self.txtStudentNo:
            self.txtStudentNo.setReadOnly(True)
            self.txtStudentNo.setPlaceholderText("Select enrollment type first...")

        if self.btnSubmit:
            self.btnSubmit.setEnabled(False)

        # --- Connect buttons ---
        if self.btnFace:
            self.btnFace.clicked.connect(lambda: self.select_mode("face"))
        if self.btnFinger:
            self.btnFinger.clicked.connect(lambda: self.select_mode("finger"))
        if self.btnSubmit:
            self.btnSubmit.clicked.connect(self.start_enrollment)

        print("[DEBUG] EnrollPage initialized. txtStudentNo is now read-only until mode selected.")

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
            print(f"[DEBUG] Enrollment mode selected: {mode}. txtStudentNo is now editable.")

        if self.btnSubmit:
            self.btnSubmit.setEnabled(True)

        if self.lblStatus:
            self.lblStatus.setText(
                "Facial enrollment selected." if mode == "face"
                else "Fingerprint enrollment selected."
            )

    # -----------------------------------------------------------------

    def start_enrollment(self):
        student_no = self.txtStudentNo.text().strip() if self.txtStudentNo else ""

        if not student_no:
            QMessageBox.warning(self.page, "Input Missing", "Please enter student number.")
            return

        if not self.student_exists(student_no):
            QMessageBox.warning(self.page, "Not Found", f"Student {student_no} not found in database.")
            return

        # --- Check if already enrolled for selected mode ---
        if self.selected_mode == "face" and self.is_already_enrolled(student_no, "face"):
            QMessageBox.warning(self.page, "Already Enrolled", f"Student {student_no} already has a face record.")
            return

        if self.selected_mode == "finger" and self.is_already_enrolled(student_no, "finger"):
            QMessageBox.warning(self.page, "Already Enrolled", f"Student {student_no} already has a fingerprint record.")
            return

        self.set_inputs_enabled(False)

        if self.selected_mode == "face":
            if self.lblStatus:
                self.lblStatus.setText("Starting facial enrollment...")
            self.worker = FaceEnrollWorker(student_no)
            self.worker.finished.connect(self.on_enroll_done)
            self.worker.start()

        elif self.selected_mode == "finger":
            if self.lblStatus:
                self.lblStatus.setText("Starting fingerprint enrollment...")
            self.worker = FingerEnrollWorker(student_no)
            self.worker.finished.connect(self.on_enroll_done)
            self.worker.start()

        else:
            QMessageBox.warning(self.page, "No Mode", "Please select an enrollment type.")

    # -----------------------------------------------------------------

    def set_inputs_enabled(self, enabled: bool):
        if self.btnFace:
            self.btnFace.setEnabled(enabled)
        if self.btnFinger:
            self.btnFinger.setEnabled(enabled)
        if self.txtStudentNo:
            self.txtStudentNo.setEnabled(enabled)
            # Keep read-only state when re-enabled after enrollment
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
        if self.lblStatus:
            self.lblStatus.setText(msg)

        if success:
            QMessageBox.information(self.page, "Success", msg)
        else:
            QMessageBox.critical(self.page, "Error", msg)

        # Reset to initial state
        self.selected_mode = None
        if self.txtStudentNo:
            self.txtStudentNo.clear()
            self.txtStudentNo.setReadOnly(True)
            self.txtStudentNo.setPlaceholderText("Select enrollment type first...")

        self.set_inputs_enabled(True)
        print("[DEBUG] Enrollment finished, txtStudentNo set back to read-only.")
