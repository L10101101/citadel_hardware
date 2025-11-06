from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QFont

class FooterMarquee:
    def __init__(self, label, speed=40, padding=60, left_to_right=True):
        """
        label         : the QLabel instance
        speed         : timer interval in ms (smaller -> more frames -> smoother)
        padding       : number of spaces added around text (larger -> smoother wrap)
        left_to_right : True for left-to-right motion (inverted from your original)
        """
        self.label = label
        self.text = label.text() or ""
        # keep text single-line and use a monospace font for consistent character width
        self.label.setWordWrap(False)
        self.label.setFont(QFont("Consolas"))  

        # pad both sides so the text can fully enter/exit smoothly
        self.padded_text = " " * padding + self.text + " " * padding
        self.offset = 0
        self.speed = max(5, int(speed))   # protect against too-small values
        self.left_to_right = left_to_right

        self.timer = QTimer(self.label)   # parent it to the label so it cleans up with the widget
        self.timer.timeout.connect(self.scroll)
        self.timer.start(self.speed)

    def scroll(self):
        # inverted direction: subtract 1 for left-to-right, add 1 for right-to-left
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
