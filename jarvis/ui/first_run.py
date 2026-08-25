"""First-run setup.

A packaged application can't tell someone to edit a .env file, so this asks for
what it needs, verifies the key against the real API, downloads the models with
a progress readout, and writes everything to the per-user config directory.

Shown automatically when no working API key can be found.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Qt, QThread, Signal
from PySide6.QtGui import QPainter, QPainterPath, QBrush, QColor, QLinearGradient
from PySide6.QtWidgets import (
    QApplication, QComboBox, QDialog, QLabel, QLineEdit, QProgressBar,
    QPushButton, QStackedWidget, QVBoxLayout, QWidget,
)

from ..paths import CONFIG_PATH, ENV_PATH, ensure_dirs
from .theme import STYLESHEET, C, font, rgba
from .widgets import HoloGlobe

log = logging.getLogger(__name__)


class KeyValidator(QObject):
    """Verifies an API key by making the smallest real request there is."""

    done = Signal(bool, str)

    def __init__(self, key: str, model: str):
        super().__init__()
        self.key = key
        self.model = model

    def run(self):
        try:
            from anthropic import Anthropic

            client = Anthropic(api_key=self.key)
            client.messages.create(
                model=self.model,
                max_tokens=1,
                messages=[{"role": "user", "content": "hi"}],
            )
            self.done.emit(True, "Key accepted.")
        except Exception as exc:
            message = str(exc)
            if "authentication_error" in message or "invalid x-api-key" in message:
                self.done.emit(False, "That key was rejected. Check for a stray space.")
            elif "credit balance" in message.lower():
                self.done.emit(False, "The key is valid but the account has no credit.")
            elif "not_found_error" in message or "model" in message.lower():
                # Key works; this account just can't reach that specific model.
                self.done.emit(True, "Key accepted.")
            else:
                self.done.emit(False, f"Couldn't reach the API: {message[:90]}")


class ModelDownloader(QObject):
    """Fetches the wake word, voice and speech models up front."""

    progress = Signal(int, str)
    done = Signal(bool, str)

    def __init__(self, cfg: dict):
        super().__init__()
        self.cfg = cfg

    def run(self):
        try:
            self.progress.emit(10, "Downloading the wake word model...")
            import openwakeword.utils

            openwakeword.utils.download_models()

            self.progress.emit(40, "Downloading the voice...")
            from ..audio.tts import ensure_piper_voice

            ensure_piper_voice(self.cfg["tts"]["piper_voice"])

            self.progress.emit(65, "Downloading speech recognition (this is the big one)...")
            from ..audio.stt import Transcriber

            Transcriber(self.cfg)  # constructing it pulls the Whisper weights

            self.progress.emit(100, "Everything is in place.")
            self.done.emit(True, "")
        except Exception as exc:
            log.exception("model download failed")
            self.done.emit(False, str(exc)[:160])


class FirstRunWizard(QDialog):
    def __init__(self, cfg: dict, parent=None):
        super().__init__(parent)
        self.cfg = cfg
        self.api_key = ""
        self._thread = None
        self._worker = None
        self._build()

    # ── layout ──────────────────────────────────────────────────────────
    def _build(self):
        self.setWindowTitle("JARVIS Setup")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setStyleSheet(STYLESHEET)
        self.setFixedSize(600, 660)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self.globe = HoloGlobe()
        self.globe.setFixedHeight(210)
        self.globe.set_identity("JARVIS", "", "")
        outer.addWidget(self.globe)

        self.stack = QStackedWidget()
        self.stack.addWidget(self._page_key())
        self.stack.addWidget(self._page_prefs())
        self.stack.addWidget(self._page_download())
        outer.addWidget(self.stack, stretch=1)

    def _page(self, title: str, blurb: str) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        box = QVBoxLayout(page)
        box.setContentsMargins(46, 8, 46, 34)
        box.setSpacing(10)
        heading = QLabel(title)
        heading.setFont(font(19, 700, "display", spacing=1.4))
        heading.setStyleSheet(f"color: {C.TEXT};")
        subtitle = QLabel(blurb)
        subtitle.setWordWrap(True)
        subtitle.setFont(font(12))
        subtitle.setStyleSheet(f"color: {C.TEXT_MUTED};")
        box.addWidget(heading)
        box.addWidget(subtitle)
        box.addSpacing(6)
        return page, box

    def _page_key(self) -> QWidget:
        page, box = self._page(
            "Good evening.",
            "I need an Anthropic API key to think with. It is stored on this "
            "machine only, and never leaves it except to talk to the API.",
        )

        self.key_input = QLineEdit()
        self.key_input.setObjectName("Search")
        self.key_input.setEchoMode(QLineEdit.Password)
        self.key_input.setPlaceholderText("sk-ant-...")
        self.key_input.setFont(font(12, 400, "mono"))
        self.key_input.setFixedHeight(42)
        self.key_input.returnPressed.connect(self._verify_key)
        box.addWidget(self.key_input)

        link = QLabel(
            '<a href="https://console.anthropic.com/settings/keys" '
            f'style="color:{C.CYAN};text-decoration:none">'
            "Get a key at console.anthropic.com &rsaquo;</a>"
        )
        link.setOpenExternalLinks(True)
        link.setFont(font(11))
        box.addWidget(link)

        self.key_status = QLabel(" ")
        self.key_status.setWordWrap(True)
        self.key_status.setFont(font(11))
        self.key_status.setMinimumHeight(34)
        box.addWidget(self.key_status)
        box.addStretch()

        self.key_button = QPushButton("Verify and continue")
        self.key_button.setObjectName("Ghost")
        self.key_button.setFixedHeight(44)
        self.key_button.setFont(font(13, 600))
        self.key_button.setCursor(Qt.PointingHandCursor)
        self.key_button.clicked.connect(self._verify_key)
        box.addWidget(self.key_button)

        quit_button = QPushButton("Not now")
        quit_button.setObjectName("NavItem")
        quit_button.setFont(font(11))
        quit_button.setCursor(Qt.PointingHandCursor)
        quit_button.clicked.connect(self.reject)
        box.addWidget(quit_button)
        return page

    def _page_prefs(self) -> QWidget:
        page, box = self._page(
            "A few preferences.",
            "All of these can be changed later in settings.",
        )

        box.addWidget(self._field_label("What should I call you?"))
        self.address_input = QLineEdit()
        self.address_input.setObjectName("Search")
        self.address_input.setText("sir")
        self.address_input.setFont(font(12))
        self.address_input.setFixedHeight(40)
        box.addWidget(self.address_input)

        box.addSpacing(6)
        box.addWidget(self._field_label("Voice"))
        self.voice_select = QComboBox()
        self.voice_select.setFont(font(12))
        self.voice_select.setFixedHeight(40)
        self.voice_select.setStyleSheet(
            f"QComboBox {{ background: {rgba(C.INSET, 0.92)};"
            f"border: 1px solid {rgba(C.CYAN, 0.16)}; border-radius: 9px;"
            f"color: {C.TEXT}; padding: 6px 12px; }}"
            f"QComboBox QAbstractItemView {{ background: {C.PANEL_HI};"
            f"color: {C.TEXT}; selection-background-color: {rgba(C.CYAN, 0.3)}; }}"
        )
        from ..audio.tts import RECOMMENDED_PIPER_VOICES

        for voice_id, note in RECOMMENDED_PIPER_VOICES:
            self.voice_select.addItem(f"{note}", voice_id)
        box.addWidget(self.voice_select)

        box.addSpacing(6)
        box.addWidget(self._field_label("Speech recognition"))
        self.stt_select = QComboBox()
        self.stt_select.setFont(font(12))
        self.stt_select.setFixedHeight(40)
        self.stt_select.setStyleSheet(self.voice_select.styleSheet())
        for model, note in (
            ("base.en", "Balanced - recommended"),
            ("tiny.en", "Fastest, least accurate"),
            ("small.en", "Most accurate, slower"),
        ):
            self.stt_select.addItem(note, model)
        box.addWidget(self.stt_select)
        box.addStretch()

        button = QPushButton("Continue")
        button.setObjectName("Ghost")
        button.setFixedHeight(44)
        button.setFont(font(13, 600))
        button.setCursor(Qt.PointingHandCursor)
        button.clicked.connect(self._start_download)
        box.addWidget(button)
        return page

    def _page_download(self) -> QWidget:
        page, box = self._page(
            "Bringing systems online.",
            "Downloading the wake word, the voice and speech recognition. "
            "Around 200 MB, once. They run offline afterwards.",
        )
        self.progress = QProgressBar()
        self.progress.setFixedHeight(8)
        self.progress.setTextVisible(False)
        self.progress.setStyleSheet(
            f"QProgressBar {{ background: {rgba(C.INSET, 0.9)}; border: none;"
            f"border-radius: 4px; }}"
            f"QProgressBar::chunk {{ background: {C.CYAN}; border-radius: 4px; }}"
        )
        box.addWidget(self.progress)

        self.download_status = QLabel("Starting...")
        self.download_status.setWordWrap(True)
        self.download_status.setFont(font(11))
        self.download_status.setStyleSheet(f"color: {C.TEXT_MUTED};")
        box.addWidget(self.download_status)
        box.addStretch()

        self.finish_button = QPushButton("Start JARVIS")
        self.finish_button.setObjectName("Ghost")
        self.finish_button.setFixedHeight(44)
        self.finish_button.setFont(font(13, 600))
        self.finish_button.setCursor(Qt.PointingHandCursor)
        self.finish_button.setEnabled(False)
        self.finish_button.clicked.connect(self.accept)
        box.addWidget(self.finish_button)
        return page

    def _field_label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(font(11, 600))
        label.setStyleSheet(f"color: {C.CYAN_DIM};")
        return label

    # ── steps ───────────────────────────────────────────────────────────
    def _verify_key(self):
        key = self.key_input.text().strip()
        if not key:
            self._set_status(self.key_status, "Paste your key above first.", C.AMBER)
            return
        if not key.startswith("sk-ant-"):
            self._set_status(
                self.key_status,
                "Anthropic keys start with 'sk-ant-'. That looks like a different key.",
                C.AMBER,
            )
            return
        self.key_button.setEnabled(False)
        self.key_button.setText("Verifying...")
        self._set_status(self.key_status, "Checking with the API...", C.TEXT_MUTED)
        self._run_worker(
            KeyValidator(key, self.cfg["assistant"]["model"]), self._key_checked
        )

    def _key_checked(self, ok: bool, message: str):
        self.key_button.setEnabled(True)
        self.key_button.setText("Verify and continue")
        if not ok:
            self._set_status(self.key_status, message, C.RED)
            return
        self.api_key = self.key_input.text().strip()
        self._set_status(self.key_status, message, C.GREEN)
        self.stack.setCurrentIndex(1)
        self.globe.set_accent(C.GREEN, 0.02)

    def _start_download(self):
        self.cfg["assistant"]["address_user_as"] = self.address_input.text().strip() or "sir"
        self.cfg["tts"]["piper_voice"] = self.voice_select.currentData()
        self.cfg["stt"]["model"] = self.stt_select.currentData()
        self._save()
        self.stack.setCurrentIndex(2)
        self.globe.set_accent(C.AMBER, 0.04)
        self._run_worker(ModelDownloader(self.cfg), self._download_finished,
                         progress=self._download_progress)

    def _download_progress(self, value: int, message: str):
        self.progress.setValue(value)
        self.download_status.setText(message)

    def _download_finished(self, ok: bool, error: str):
        self.finish_button.setEnabled(True)
        if ok:
            self.globe.set_accent(C.CYAN, 0.006)
            self._set_status(self.download_status, "Ready.", C.GREEN)
        else:
            # Not fatal - the models download lazily on first use as well.
            self.globe.set_accent(C.AMBER, 0.01)
            self._set_status(
                self.download_status,
                f"Some downloads failed ({error}). JARVIS will retry them when "
                "first needed.",
                C.AMBER,
            )

    # ── plumbing ────────────────────────────────────────────────────────
    def _run_worker(self, worker: QObject, on_done, progress=None):
        """Move a worker onto its own thread so the UI keeps animating."""
        self._thread = QThread()
        self._worker = worker
        worker.moveToThread(self._thread)
        self._thread.started.connect(worker.run)
        worker.done.connect(on_done)
        worker.done.connect(self._thread.quit)
        if progress is not None:
            worker.progress.connect(progress)
        self._thread.start()

    @staticmethod
    def _set_status(label: QLabel, text: str, colour: str):
        label.setText(text)
        label.setStyleSheet(f"color: {colour};")

    def _save(self):
        """Write the key to .env and the preferences to config.yaml."""
        ensure_dirs()
        ENV_PATH.write_text(f"ANTHROPIC_API_KEY={self.api_key}\n", encoding="utf-8")
        try:
            ENV_PATH.chmod(0o600)  # no-op on Windows, meaningful elsewhere
        except OSError:
            pass

        import yaml

        existing = {}
        if CONFIG_PATH.exists():
            try:
                existing = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            except Exception:
                existing = {}
        existing.setdefault("assistant", {})["address_user_as"] = \
            self.cfg["assistant"]["address_user_as"]
        existing.setdefault("tts", {})["piper_voice"] = self.cfg["tts"]["piper_voice"]
        existing.setdefault("stt", {})["model"] = self.cfg["stt"]["model"]
        CONFIG_PATH.write_text(yaml.safe_dump(existing, sort_keys=False), encoding="utf-8")
        self.cfg["secrets"]["anthropic_api_key"] = self.api_key
        log.info("first-run settings written to %s", CONFIG_PATH)

    # ── chrome ──────────────────────────────────────────────────────────
    def paintEvent(self, event):  # noqa: N802
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        path = QPainterPath()
        path.addRoundedRect(0, 0, self.width(), self.height(), 16, 16)
        gradient = QLinearGradient(0, 0, 0, self.height())
        gradient.setColorAt(0.0, QColor("#0A1524"))
        gradient.setColorAt(1.0, QColor("#050B14"))
        p.fillPath(path, QBrush(gradient))
        p.end()

    def mousePressEvent(self, event):  # noqa: N802
        if event.button() == Qt.LeftButton:
            self._drag = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event):  # noqa: N802
        if getattr(self, "_drag", None) is not None and event.buttons() & Qt.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag)

    def mouseReleaseEvent(self, event):  # noqa: N802
        self._drag = None


def needs_first_run(cfg: dict) -> bool:
    return not cfg.get("secrets", {}).get("anthropic_api_key")


def run_first_run(cfg: dict) -> bool:
    """Show the wizard. True if setup completed and JARVIS should start."""
    # A QApplication must exist before any widget; the wizard may run before
    # the main window has created one.
    if QApplication.instance() is None:
        QApplication([])
    wizard = FirstRunWizard(cfg)
    accepted = wizard.exec() == QDialog.Accepted
    if accepted:
        # Re-read so the rest of the app sees the freshly written settings.
        from ..config import load_config

        cfg.update(load_config())
    return accepted
