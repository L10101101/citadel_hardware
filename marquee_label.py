from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont

class FooterMarquee:
    def __init__(self, label, speed=40, padding=60, left_to_right=True):
        self.label = label
        self.text = label.text() or ""
        self.label.setWordWrap(False)

        self.padded_text = " " * padding + self.text + " " * padding
        self.offset = 0
        self.speed = max(5, int(speed))
        self.left_to_right = left_to_right

        self.timer = QTimer(self.label)
        self.timer.timeout.connect(self.scroll)
        self.timer.start(self.speed)


    def scroll(self):
        if self.left_to_right:
            self.offset = (self.offset - 1) % len(self.padded_text)
        else:
            self.offset = (self.offset + 1) % len(self.padded_text)

        visible = self.padded_text[self.offset:] + self.padded_text[:self.offset]
        self.label.setText(visible)


    def stop(self):
        self.timer.stop()


    def start(self):
        if not self.timer.isActive():
            self.timer.start(self.speed)
