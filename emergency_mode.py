from PyQt6 import QtCore
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QMessageBox, QTextEdit, QPushButton, QFileDialog, QWidget, QHBoxLayout, QLabel, QFrame, QSizePolicy
from html import escape
from datetime import datetime

from utils import get_present_students_with_program, get_program_remaining_counts, format_program_label


class EmergencyModeController:
    def __init__(self, main_window):
        self.main = main_window
        self.active = False
        self._program_page_index = 0
        self._program_counts = []
        self._last_list_html = ""
        self._default_details_margins = self.main.detailsLayout.contentsMargins()

        self._normal_title_style = self.main.titleWidget.styleSheet()
        self._normal_footer_style = self.main.footerWidget.styleSheet()
        self._default_title_style = (
            "background-color: #064f32; border-bottom-left-radius: 20px; border-bottom-right-radius: 20px;"
        )
        self._default_footer_style = (
            "background-color: #064f32; border-top-left-radius: 20px; border-top-right-radius: 20px;"
        )

        self._tick_timer = QTimer(self.main)
        self._tick_timer.setInterval(5000)
        self._tick_timer.timeout.connect(self._tick)

        self._list_title = QLabel("LIST OF STUDENTS", self.main.detailsWidget)
        self._list_title.setAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
        self._list_title.setVisible(False)
        self._list_title.setStyleSheet("font-size: 28px; font-weight: bold; color: #1f1f1f;")
        self.main.detailsLayout.insertWidget(0, self._list_title)

        self._list_widget = QTextEdit(self.main.detailsWidget)
        self._list_widget.setReadOnly(True)
        self._list_widget.setObjectName("emergencyListWidget")
        self._list_widget.setVisible(False)
        self._list_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._list_widget.setFrameShape(QFrame.Shape.NoFrame)
        self._list_widget.setVerticalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        self._list_widget.setHorizontalScrollBarPolicy(QtCore.Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self._list_widget.setStyleSheet(
            """
            QTextEdit#emergencyListWidget {
                background-color: #FFFFFF;
                border: 1px solid #FFFFFF;
                border-radius: 10px;
                padding: 8px;
                font-size: 14px;
            }
            QTextEdit#emergencyListWidget:focus {
                border: 1px solid #FFFFFF;
            }
            QTextEdit#emergencyListWidget QScrollBar:vertical {
                width: 12px;
                background: #F0F0F0;
                border-radius: 6px;
            }
            QTextEdit#emergencyListWidget QScrollBar::handle:vertical {
                background: #9E9E9E;
                min-height: 24px;
                border-radius: 6px;
            }
            QTextEdit#emergencyListWidget QScrollBar::add-line:vertical,
            QTextEdit#emergencyListWidget QScrollBar::sub-line:vertical {
                height: 0px;
            }
            QTextEdit#emergencyListWidget QScrollBar:horizontal {
                height: 12px;
                background: #F0F0F0;
                border-radius: 6px;
            }
            QTextEdit#emergencyListWidget QScrollBar::handle:horizontal {
                background: #9E9E9E;
                min-width: 24px;
                border-radius: 6px;
            }
            QTextEdit#emergencyListWidget QScrollBar::add-line:horizontal,
            QTextEdit#emergencyListWidget QScrollBar::sub-line:horizontal {
                width: 0px;
            }
            """
        )
        self.main.detailsLayout.insertWidget(1, self._list_widget)
        self.main.detailsLayout.setStretchFactor(self._list_widget, 1)

        self._export_row = QWidget(self.main.detailsWidget)
        self._export_row_layout = QHBoxLayout(self._export_row)
        self._export_row_layout.setContentsMargins(0, 0, 0, 0)
        self._export_row_layout.setSpacing(8)
        self._export_row_layout.addStretch(1)
        self._export_btn = QPushButton("Export List", self._export_row)
        self._export_btn.setCursor(QtCore.Qt.CursorShape.PointingHandCursor)
        self._export_btn.setStyleSheet(
            "background-color: #2E7D32; color: white; font-weight: bold; border-radius: 8px; padding: 8px 14px;"
        )
        self._export_btn.clicked.connect(self._export_emergency_report)
        self._export_row_layout.addWidget(self._export_btn)
        self._export_row.setVisible(False)
        self.main.detailsLayout.insertWidget(2, self._export_row)

    def toggle(self):
        if self.active:
            self._prompt_and_exit()
            return
        self._prompt_and_enter()

    def _prompt_and_enter(self):
        dialog = QMessageBox(self.main)
        dialog.setWindowTitle("Emergency Mode")
        dialog.setText("Do you intend to open Emergency mode?")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setWindowFlags(
            QtCore.Qt.WindowType.Dialog | QtCore.Qt.WindowType.FramelessWindowHint
        )
        yes_btn = dialog.addButton("Yes", QMessageBox.ButtonRole.AcceptRole)
        no_btn = dialog.addButton("No", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(no_btn)
        yes_btn.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold;")
        no_btn.setStyleSheet("background-color: #E0E0E0; color: #C62828; font-weight: bold;")
        dialog.exec()
        if dialog.clickedButton() == yes_btn:
            self.enter_mode()

    def _prompt_and_exit(self):
        dialog = QMessageBox(self.main)
        dialog.setWindowTitle("Emergency Mode")
        dialog.setText("Exit Emergency mode and return to normal monitoring?")
        dialog.setIcon(QMessageBox.Icon.Question)
        dialog.setWindowFlags(
            QtCore.Qt.WindowType.Dialog | QtCore.Qt.WindowType.FramelessWindowHint
        )
        yes_btn = dialog.addButton("Yes", QMessageBox.ButtonRole.AcceptRole)
        no_btn = dialog.addButton("No", QMessageBox.ButtonRole.RejectRole)
        dialog.setDefaultButton(no_btn)
        yes_btn.setStyleSheet("background-color: #2E7D32; color: white; font-weight: bold;")
        no_btn.setStyleSheet("background-color: #E0E0E0; color: #C62828; font-weight: bold;")
        dialog.exec()
        if dialog.clickedButton() == yes_btn:
            self.exit_mode()

    def enter_mode(self):
        if self.active:
            return
        self.active = True

        self.main.cancel_reset_info()
        self.main.reset_verification_state()
        self.main.detailsLayout.setContentsMargins(
            self._default_details_margins.left(),
            self._default_details_margins.top(),
            self._default_details_margins.right(),
            self._default_details_margins.bottom(),
        )
        if hasattr(self.main, "fingerprint_thread"):
            self.main.fingerprint_thread.deactivate()
        self.main.hiddenInput.setEnabled(False)

        if hasattr(self.main, "summary_timer"):
            self.main.summary_timer.stop()
        if hasattr(self.main, "slideshow_idle_timer"):
            self.main.slideshow_idle_timer.stop()
        if hasattr(self.main, "slideshow_cycle_timer"):
            self.main.slideshow_cycle_timer.stop()
        if hasattr(self.main, "_stop_slideshow"):
            self.main._stop_slideshow()

        for widget_name in (
            "label",
            "spacerLabel_1",
            "spacerLabel_2",
            "nameLabel",
            "programLabel",
            "yearSecLabel",
            "idLabel",
            "entryLabel",
            "verificationIconsWidget",
            "statusWidget",
        ):
            widget = getattr(self.main, widget_name, None)
            if widget is not None:
                widget.setVisible(False)

        self._list_widget.setVisible(True)
        self._list_title.setVisible(True)
        self._export_row.setVisible(True)

        self.main.titleWidget.setStyleSheet("background-color: #B71C1C;")
        self.main.footerWidget.setStyleSheet("background-color: #B71C1C;")

        self._program_page_index = 0
        self._tick()
        self._tick_timer.start()

    def exit_mode(self):
        if not self.active:
            return
        self.active = False
        self._tick_timer.stop()

        for widget_name in (
            "label",
            "spacerLabel_1",
            "spacerLabel_2",
            "nameLabel",
            "programLabel",
            "yearSecLabel",
            "idLabel",
            "entryLabel",
            "verificationIconsWidget",
            "statusWidget",
        ):
            widget = getattr(self.main, widget_name, None)
            if widget is not None:
                widget.setVisible(True)

        self._list_widget.setVisible(False)
        self._list_title.setVisible(False)
        self._export_row.setVisible(False)

        self.main.titleWidget.setStyleSheet(
            self._normal_title_style or self._default_title_style
        )
        self.main.footerWidget.setStyleSheet(
            self._normal_footer_style or self._default_footer_style
        )

        self.main.hiddenInput.setEnabled(True)
        self.main.detailsLayout.setContentsMargins(
            self._default_details_margins.left(),
            self._default_details_margins.top(),
            self._default_details_margins.right(),
            self._default_details_margins.bottom(),
        )
        if hasattr(self.main, "fingerprint_thread"):
            self.main.fingerprint_thread.activate()
        self.main._focus_hidden_input()
        self.main.reset_info()

        if hasattr(self.main, "summary_timer"):
            self.main.summary_timer.start()
        if hasattr(self.main, "_reset_slideshow_timer"):
            self.main._reset_slideshow_timer()
        self.main.refresh_monitoring_summary()

    def _tick(self):
        self._refresh_present_students_list()
        self._refresh_program_summary_page()

    def _refresh_present_students_list(self):
        rows = get_present_students_with_program()
        if not rows:
            html = (
                "<div style='text-align:center;'>No students currently present inside campus.</div>"
            )
        else:
            grouped: dict[str, list[str]] = {}
            for name, program in rows:
                abbrev = self._abbreviate_program(program)
                grouped.setdefault(abbrev, []).append(name)

            sections = []
            overall_idx = 1
            for program_key in sorted(grouped.keys()):
                student_lines = []
                for name in grouped[program_key]:
                    student_lines.append(f"{overall_idx}. {escape(name)}")
                    overall_idx += 1
                section_html = (
                    f"<div style='font-weight:700; margin-top: 10px;'>{escape(program_key)}</div>"
                    f"<div>{'<br>'.join(student_lines)}</div>"
                )
                sections.append(section_html)
            html = "".join(sections)

        if html == self._last_list_html:
            return

        vbar = self._list_widget.verticalScrollBar()
        prev_pos = vbar.value()
        max_before = vbar.maximum()

        self._list_widget.setHtml(html)
        self._last_list_html = html

        max_after = vbar.maximum()
        if max_before > 0:
            ratio = prev_pos / max_before
            vbar.setValue(int(ratio * max_after))
        else:
            vbar.setValue(prev_pos)

    def _refresh_program_summary_page(self):
        self._program_counts = get_program_remaining_counts()
        self.main.summaryLabel.setText("STUDENTS IN CAMPUS")
        if not self._program_counts:
            self.main.firstDetailLabel.setText("-")
            self.main.secondDetailLabel.setText("-")
            self.main.thirdDetailLabel.setText("-")
            return

        page_size = 3
        page_count = max(1, (len(self._program_counts) + page_size - 1) // page_size)
        self._program_page_index = self._program_page_index % page_count
        start = self._program_page_index * page_size
        chunk = self._program_counts[start:start + page_size]

        lines = [f"{self._abbreviate_program(name)}\n{count}" for name, count in chunk]
        while len(lines) < 3:
            lines.append("-")
        self.main.firstDetailLabel.setText(lines[0])
        self.main.secondDetailLabel.setText(lines[1])
        self.main.thirdDetailLabel.setText(lines[2])

        self._program_page_index = (self._program_page_index + 1) % page_count

    @staticmethod
    def _abbreviate_program(program_name: str) -> str:
        return format_program_label(program_name)

    def _export_emergency_report(self):
        students = get_present_students_with_program()
        programs = get_program_remaining_counts()
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        default_name = f"emergency_list_{ts}.txt"
        file_path, _ = QFileDialog.getSaveFileName(
            self.main,
            "Save Emergency List",
            default_name,
            "Text Files (*.txt);;All Files (*)",
        )
        if not file_path:
            return

        lines = []
        lines.append("EMERGENCY MODE REPORT")
        lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        lines.append("")
        lines.append("STUDENT COUNT PER PROGRAM")
        if programs:
            for program, count in programs:
                lines.append(f"{self._abbreviate_program(program)}: {count}")
        else:
            lines.append("No program counts available.")
        lines.append("")
        lines.append(f"Total Students Present: {len(students)}")
        lines.append("")
        lines.append("LIST OF STUDENTS")
        if students:
            grouped: dict[str, list[str]] = {}
            for name, program in students:
                key = self._abbreviate_program(program)
                grouped.setdefault(key, []).append(name)

            idx = 1
            for program_key in sorted(grouped.keys()):
                lines.append(f"{program_key}")
                for name in grouped[program_key]:
                    lines.append(f"{idx}. {name}")
                    idx += 1
                lines.append("")
        else:
            lines.append("No students currently present inside campus.")        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
