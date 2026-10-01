"""Subtitle window for projecting lecture subtitles next to (or below) the slides.

The window never takes keyboard focus (so the slides keep it), so every control is
an on-screen button in the toolbar at the bottom:
  A- / A+     English font size        あ        show/hide the Japanese line
  ◐- / ◐+    background opacity       ▥ / ▤     snap to the right side / bottom of this screen
  💾          save transcript          ⏹         stop
Drag anywhere to move, drag the ◢ corner to resize. Display settings are stored in
display_prefs.json (not config.ini, which would trigger the hot reloader).
"""
import json
import os
import time
from ctypes import c_void_p

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QVBoxLayout, QWidget)

# macOS: Make window visible on all desktops (Spaces)
try:
    from AppKit import NSWindowCollectionBehaviorCanJoinAllSpaces, NSWindowCollectionBehaviorStationary
    import objc
    HAS_APPKIT = True
except ImportError:
    HAS_APPKIT = False

PREFS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "display_prefs.json")
DEFAULT_PREFS = {
    "en_font_size": 36,      # px; large enough to read from the back of a classroom
    "ja_font_size": 18,
    "show_ja": True,
    "bg_alpha": 200,         # 0 = fully transparent, 255 = opaque black
    "layout": "side",        # side | bottom | free
    "side_ratio": 0.3,       # side layout: fraction of the screen width
    "bottom_lines": 3,       # bottom layout: number of English lines kept visible
    "geometry": None,        # free layout: [x, y, w, h]
}


def load_prefs():
    prefs = dict(DEFAULT_PREFS)
    try:
        with open(PREFS_PATH, encoding="utf-8") as f:
            prefs.update(json.load(f))
    except (OSError, ValueError):
        pass
    return prefs


def save_prefs(prefs):
    try:
        with open(PREFS_PATH, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)
    except OSError as e:
        print(f"[Overlay] Could not save display prefs: {e}")


class LogItem(QFrame):
    """A widget representing a single chunk of transcription/translation"""
    def __init__(self, chunk_id, original_text, translated_text=""):
        super().__init__()
        self.chunk_id = chunk_id
        self.setStyleSheet("background-color: transparent;")
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(2)
        self.setLayout(layout)

        self.original_label = QLabel(original_text)
        self.original_label.setWordWrap(True)
        layout.addWidget(self.original_label)

        self.translated_label = QLabel(translated_text or "…")
        self.translated_label.setWordWrap(True)
        layout.addWidget(self.translated_label)

    def apply_style(self, prefs):
        self.original_label.setStyleSheet(
            f"color: #bbbbbb; font-size: {prefs['ja_font_size']}px;")
        self.original_label.setVisible(prefs["show_ja"])
        self.translated_label.setStyleSheet(
            f"color: #ffffff; font-size: {prefs['en_font_size']}px; font-weight: bold;")

    def update_translated(self, text):
        self.translated_label.setText(text)

    def update_original(self, text):
        self.original_label.setText(text)


class ResizeHandle(QLabel):
    def __init__(self, parent):
        super().__init__(parent)
        self.parent_window = parent
        self.setText("◢")
        self.setStyleSheet("color: rgba(255, 255, 255, 160); font-size: 28px;")
        self.setFixedSize(36, 36)
        self.setAlignment(Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignRight)
        self.setCursor(Qt.CursorShape.SizeFDiagCursor)
        self.startPos = None

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.startPos = event.globalPosition().toPoint()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.startPos:
            delta = event.globalPosition().toPoint() - self.startPos
            w = max(200, self.parent_window.width() + delta.x())
            h = max(120, self.parent_window.height() + delta.y())
            self.parent_window.resize(w, h)
            self.startPos = event.globalPosition().toPoint()
            event.accept()

    def mouseReleaseEvent(self, event):
        self.startPos = None
        self.parent_window.remember_free_geometry()


class OverlayWindow(QWidget):
    stop_requested = pyqtSignal()

    def __init__(self, display_duration=None, window_width=400, window_height=None):
        super().__init__()
        # display_duration / window_width / window_height are kept for compatibility;
        # size and position now come from display_prefs.json
        self.prefs = load_prefs()
        self.items = []             # [(chunk_id, LogItem)] sorted by chunk_id
        self.transcript_data = {}   # chunk_id -> {timestamp, original, translated}
        self.is_moving = False
        self.initUI()
        self.apply_layout()

    def showEvent(self, event):
        """Called when window is shown - set all-spaces behavior here"""
        super().showEvent(event)
        if HAS_APPKIT and QApplication.platformName() == "cocoa":
            self._set_all_spaces()

    def _set_all_spaces(self):
        """Make window appear on all macOS Spaces/Desktops"""
        try:
            win_id = int(self.winId())
            ns_view = objc.objc_object(c_void_p=c_void_p(win_id))
            ns_window = ns_view.window()
            ns_window.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorStationary
            )
        except Exception as e:
            print(f"Could not set all-spaces behavior: {e}")

    def initUI(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint |
            Qt.WindowType.WindowStaysOnTopHint |
            Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.setLayout(layout)

        # Background frame (its alpha is the adjustable opacity)
        self.frame = QFrame()
        self.frame.setObjectName("bg")
        frame_layout = QVBoxLayout()
        frame_layout.setContentsMargins(16, 12, 8, 4)
        self.frame.setLayout(frame_layout)
        layout.addWidget(self.frame)

        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll_area.setStyleSheet("QScrollArea { background: transparent; } QScrollBar:vertical { width: 0px; }")
        self.scroll_area.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.scroll_area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self.container = QFrame()
        self.container.setStyleSheet("background-color: transparent;")
        self.container_layout = QVBoxLayout()
        self.container_layout.setContentsMargins(0, 0, 0, 0)
        # A leading stretch keeps the newest line at the bottom. (AlignBottom would break
        # height-for-width of word-wrapped labels and clip long translations.)
        self.container_layout.addStretch(1)
        self.container.setLayout(self.container_layout)
        self.scroll_area.setWidget(self.container)
        frame_layout.addWidget(self.scroll_area)

        # Toolbar
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.toolbar_buttons = []

        def button(text, tip, slot, width=44):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setFixedSize(width, 32)
            b.setStyleSheet("""
                QPushButton { background-color: rgba(255,255,255,40); color: rgba(255,255,255,200);
                              border: none; border-radius: 6px; font-size: 15px; }
                QPushButton:hover { background-color: rgba(255,255,255,110); color: white; }
            """)
            b.clicked.connect(slot)
            bar.addWidget(b)
            self.toolbar_buttons.append(b)
            return b

        button("A−", "Smaller English text", lambda: self._change_font(-4))
        button("A+", "Larger English text", lambda: self._change_font(+4))
        self.ja_btn = button("あ", "Show/hide Japanese", self._toggle_ja)
        button("◐−", "More transparent", lambda: self._change_alpha(-30))
        button("◐+", "Less transparent", lambda: self._change_alpha(+30))
        button("▥", "Snap to the right side of this screen", lambda: self._set_layout("side"))
        button("▤", "Snap to the bottom of this screen", lambda: self._set_layout("bottom"))
        self.save_btn = button("💾", "Save transcript", self._save_transcript)
        stop = button("⏹", "Stop translator", self.stop_requested.emit)
        stop.setStyleSheet(stop.styleSheet().replace("rgba(255,255,255,40)", "rgba(243,139,168,150)"))
        bar.addStretch()
        bar.addWidget(ResizeHandle(self))
        frame_layout.addLayout(bar)

        self.setMouseTracking(True)

    # ---------- display settings ----------

    def apply_style(self):
        self.frame.setStyleSheet(
            f"QFrame#bg {{ background-color: rgba(0, 0, 0, {self.prefs['bg_alpha']}); border-radius: 10px; }}")
        for _, w in self.items:
            w.apply_style(self.prefs)
        self.ja_btn.setText("あ" if self.prefs["show_ja"] else "EN")
        QTimer.singleShot(10, self._scroll_to_bottom)

    def apply_layout(self):
        """Place the window according to the current layout on the screen it is on"""
        screen = (self.screen() or QApplication.primaryScreen()).availableGeometry()
        layout = self.prefs["layout"]
        if layout == "side":
            w = int(screen.width() * self.prefs["side_ratio"])
            self.setGeometry(screen.x() + screen.width() - w, screen.y(), w, screen.height())
        elif layout == "bottom":
            line = self.prefs["en_font_size"] * 1.35
            ja = (self.prefs["ja_font_size"] * 1.4) if self.prefs["show_ja"] else 0
            h = int(self.prefs["bottom_lines"] * line + ja + 12 + 16 + 40)
            self.setGeometry(screen.x(), screen.y() + screen.height() - h, screen.width(), h)
        elif self.prefs.get("geometry"):
            self.setGeometry(*self.prefs["geometry"])
        else:
            self.setGeometry(screen.x() + screen.width() - 600, screen.y(), 600, screen.height())
        self.apply_style()

    def remember_free_geometry(self):
        """Called after a manual move/resize: switch to free layout and remember it"""
        self.prefs["layout"] = "free"
        self.prefs["geometry"] = [self.x(), self.y(), self.width(), self.height()]
        save_prefs(self.prefs)

    def _set_layout(self, layout):
        self.prefs["layout"] = layout
        save_prefs(self.prefs)
        self.apply_layout()

    def _change_font(self, delta):
        self.prefs["en_font_size"] = max(14, min(96, self.prefs["en_font_size"] + delta))
        self.prefs["ja_font_size"] = max(10, round(self.prefs["en_font_size"] / 2))
        save_prefs(self.prefs)
        if self.prefs["layout"] == "bottom":
            self.apply_layout()
        else:
            self.apply_style()

    def _change_alpha(self, delta):
        self.prefs["bg_alpha"] = max(0, min(255, self.prefs["bg_alpha"] + delta))
        save_prefs(self.prefs)
        self.apply_style()

    def _toggle_ja(self):
        self.prefs["show_ja"] = not self.prefs["show_ja"]
        save_prefs(self.prefs)
        if self.prefs["layout"] == "bottom":
            self.apply_layout()
        else:
            self.apply_style()

    # ---------- content ----------

    def update_text(self, chunk_id, original_text, translated_text):
        """Append new text or update existing text"""
        if chunk_id not in self.transcript_data:
            self.transcript_data[chunk_id] = {
                'timestamp': time.strftime("%H:%M:%S"),
                'original': original_text,
                'translated': translated_text
            }
        else:
            if original_text:
                self.transcript_data[chunk_id]['original'] = original_text
            if translated_text:
                self.transcript_data[chunk_id]['translated'] = translated_text

        existing = next((w for cid, w in self.items if cid == chunk_id), None)
        if existing:
            if original_text:
                existing.update_original(original_text)
            if translated_text and translated_text != "(translating...)":
                existing.update_translated(translated_text)
        else:
            shown = "" if translated_text == "(translating...)" else translated_text
            new_widget = LogItem(chunk_id, original_text, shown)
            new_widget.apply_style(self.prefs)
            insert_idx = len(self.items)
            for i, (cid, _) in enumerate(self.items):
                if cid > chunk_id:
                    insert_idx = i
                    break
            self.items.insert(insert_idx, (chunk_id, new_widget))
            self.container_layout.insertWidget(insert_idx + 1, new_widget)  # +1: leading stretch
            # Keep the widget count bounded during a 90-minute lecture
            while len(self.items) > 200:
                _, old = self.items.pop(0)
                old.setParent(None)
                old.deleteLater()
        QTimer.singleShot(10, self._scroll_to_bottom)

    def _scroll_to_bottom(self):
        sb = self.scroll_area.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _save_transcript(self):
        """Save history to file (the session log in transcripts/<timestamp>/ is written automatically)"""
        if not self.transcript_data:
            print("[Overlay] Nothing to save.")
            return
        os.makedirs("transcripts", exist_ok=True)
        filename = f"transcripts/transcript_{time.strftime('%Y%m%d_%H%M%S')}.txt"
        try:
            with open(filename, "w", encoding="utf-8") as f:
                f.write(f"Transcript saved at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
                f.write("=" * 50 + "\n\n")
                for cid in sorted(self.transcript_data):
                    d = self.transcript_data[cid]
                    f.write(f"[{d['timestamp']}] (ID: {cid})\nOriginal: {d['original']}\nTranslation: {d['translated']}\n{'-'*30}\n")
            print(f"[Overlay] Saved to {filename}")
            self.save_btn.setText("✓")
            QTimer.singleShot(2000, lambda: self.save_btn.setText("💾"))
        except Exception as e:
            print(f"[Overlay] Error saving transcript: {e}")

    # ---------- moving ----------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.is_moving = True
            self.moved = False
            self.oldPos = event.globalPosition().toPoint()

    def mouseMoveEvent(self, event):
        if self.is_moving:
            delta = event.globalPosition().toPoint() - self.oldPos
            self.move(self.x() + delta.x(), self.y() + delta.y())
            self.oldPos = event.globalPosition().toPoint()
            self.moved = True

    def mouseReleaseEvent(self, event):
        if self.is_moving:
            self.is_moving = False
            if self.moved:
                self.remember_free_geometry()


if __name__ == "__main__":
    import sys
    app = QApplication(sys.argv)
    window = OverlayWindow()
    window.show()
    window.update_text(1, "確率変数Xは1、2、3のいずれかの値を取ります", "(translating...)")
    QTimer.singleShot(800, lambda: window.update_text(1, "確率変数Xは1、2、3のいずれかの値を取ります",
                                                      "The random variable X takes one of the values 1, 2, or 3."))
    window.update_text(2, "そもそもこの6分の11ってのは", "First of all, this 11/6 is")
    sys.exit(app.exec())
