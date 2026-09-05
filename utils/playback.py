"""One cancellable playback queue shared by every sound row and preview."""

from dataclasses import dataclass, field
import json
from pathlib import Path
from queue import Queue
import shutil
import subprocess
import sys
from tempfile import TemporaryDirectory
from threading import Event, Thread

from PySide6.QtCore import QCoreApplication, QObject, Signal, Slot

from utils.audio_processing import AudioCancelled, prepare_audio
from utils.audio_routing import AudioRouting
from utils.logger import get_logger

SETTINGS_PATH = Path(__file__).resolve().parent.parent / "settings.json"
LOG = get_logger("Playback")


def read_volume(settings_path: Path = SETTINGS_PATH) -> int:
    """Settings can attenuate the prepared clip, never amplify it."""
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        value = int(settings.get("max_volume", 80))
    except (OSError, ValueError, TypeError, AttributeError, OverflowError):
        value = 80
    return max(0, min(100, value))


@dataclass
class PlaybackRequest:
    number: int
    path: Path
    preview: bool
    volume: int
    cancel: Event = field(default_factory=Event)


class WorkerSignals(QObject):
    state = Signal(int, str)
    failed = Signal(int, str)


class PlaybackWorker(Thread):
    """Serial ownership prevents old processes overlapping their replacements."""

    def __init__(self, signals: WorkerSignals):
        super().__init__(name="soundboard-playback", daemon=True)
        self.signals = signals
        self.requests: Queue[PlaybackRequest | None] = Queue()

    def run(self):
        routing = AudioRouting()
        try:
            while (request := self.requests.get()) is not None:
                if request.cancel.is_set():
                    continue
                try:
                    self._play(request, routing)
                except AudioCancelled:
                    pass
                except Exception as error:
                    LOG.exception("Couldn't play %s", request.path)
                    if not request.cancel.is_set():
                        self.signals.failed.emit(request.number, str(error))
                finally:
                    self.signals.state.emit(request.number, "idle")
        finally:
            try:
                routing.close()
            except Exception:
                LOG.exception("Couldn't clean up the virtual audio devices")

    def _play(self, request: PlaybackRequest, routing: AudioRouting):
        if sys.platform != "linux":
            raise RuntimeError("Soundboard playback currently supports Linux with PipeWire.")
        paplay = shutil.which("paplay")
        if paplay is None:
            raise RuntimeError("Install libpulse (paplay) to enable playback on Arch Linux.")

        self.signals.state.emit(request.number, "preparing")
        with TemporaryDirectory(prefix="soundboard-audio-") as directory:
            prepared = prepare_audio(request.path, Path(directory), request.cancel)
            if request.cancel.is_set():
                raise AudioCancelled()
            sink = routing.speaker() if request.preview else routing.ensure()
            if request.cancel.is_set():
                raise AudioCancelled()
            # PulseAudio's volume scale is nonlinear, but 0..65536 never boosts.
            volume = round(65536 * max(0, min(100, request.volume)) / 100)
            with subprocess.Popen(
                [paplay, "--device", sink, "--volume", str(volume),
                 "--client-name", "Soundboard", "--stream-name", "Soundboard clip",
                 "--latency-msec", "50", "--property=node.dont-reconnect=true",
                 "--property=node.dont-fallback=true",
                 str(prepared)],
                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            ) as process:
                try:
                    self.signals.state.emit(request.number, "playing")
                    while True:
                        if request.cancel.is_set():
                            raise AudioCancelled()
                        try:
                            _, stderr = process.communicate(timeout=0.1)
                            break
                        except subprocess.TimeoutExpired:
                            continue
                    if process.returncode:
                        detail = stderr.decode(errors="replace").strip()[-2000:]
                        raise RuntimeError(f"Audio playback failed: {detail}")
                finally:
                    if process.poll() is None:
                        process.terminate()
                        try:
                            process.communicate(timeout=1)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.communicate()


class PlaybackController(QObject):
    state_changed = Signal(object, str)
    failed = Signal(object, str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._signals = WorkerSignals(self)
        self._signals.state.connect(self._on_state)
        self._signals.failed.connect(self._on_failure)
        self._worker = PlaybackWorker(self._signals)
        self._request: PlaybackRequest | None = None
        self._owner: int | None = None
        self._number = 0
        self._closed = False
        self._worker.start()

    def play(self, path: Path, owner: int, *, preview: bool = False):
        if self._closed:
            return
        self.stop()
        volume = read_volume()
        if volume == 0:
            self.failed.emit(owner, "Playback is muted. Increase Max Volume in Settings.")
            return
        self._number += 1
        self._owner = owner
        self._request = PlaybackRequest(self._number, path, preview, volume)
        self.state_changed.emit(owner, "preparing")
        self._worker.requests.put(self._request)

    def stop(self, owner: int | None = None):
        if owner is not None and owner != self._owner:
            return
        if self._request is not None:
            self._request.cancel.set()
            self.state_changed.emit(self._owner, "idle")
        self._request = None
        self._owner = None

    @Slot(int, str)
    def _on_state(self, number: int, state: str):
        if self._request is not None and self._request.number == number:
            self.state_changed.emit(self._owner, state)
            if state == "idle":
                self._request = None
                self._owner = None

    @Slot(int, str)
    def _on_failure(self, number: int, message: str):
        if self._request is not None and self._request.number == number:
            self.failed.emit(self._owner, message)

    def close(self):
        if self._closed:
            return
        self._closed = True
        self.stop()
        self._worker.requests.put(None)
        # Join before Qt destroys the signal objects or the process exits, so
        # paplay/ffmpeg are reaped and our temporary PipeWire modules are removed.
        self._worker.join()


def get_playback_controller() -> PlaybackController:
    app = QCoreApplication.instance()
    if app is None:
        raise RuntimeError("Create a QApplication before creating sound rows.")
    controller = getattr(app, "_soundboard_playback", None)
    if controller is None:
        controller = PlaybackController(app)
        app._soundboard_playback = controller
        app.aboutToQuit.connect(controller.close)
    return controller
