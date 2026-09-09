"""Windows speaker playback and a temporary microphone bridge into VB-CABLE.

Qt owns WASAPI streams on a dedicated event thread. Windows mixes the live
microphone and the clip at CABLE Input; voice apps listen to CABLE Output.
"""

from dataclasses import dataclass, field
from pathlib import Path
from threading import Event
from time import monotonic

from PySide6.QtCore import QObject, QThread, QTimer, QUrl, Signal, Slot
from PySide6.QtMultimedia import (
    QAudioFormat, QAudioOutput, QAudioSink, QAudioSource, QMediaDevices,
    QMediaPlayer, QtAudio,
)

from utils.audio_processing import AudioCancelled
from utils.audio_routing import AudioRoutingError
from utils.logger import get_logger

LOG = get_logger("WindowsAudio")


def _is_cable(device) -> bool:
    name = device.description().casefold()
    return "vb-audio" in name or name.startswith("cable ") or "voicemeeter" in name


def playback_devices(*, preview: bool):
    """Resolve fresh endpoint IDs; never send a preview back into the cable."""
    speaker = QMediaDevices.defaultAudioOutput()
    if speaker.isNull() or _is_cable(speaker):
        raise AudioRoutingError(
            "Select your speakers or headphones as the default Windows output. "
            "Select CABLE Output only as the microphone inside your voice app."
        )
    if preview:
        return speaker, None
    cable = next((device for device in QMediaDevices.audioOutputs()
                  if device.description().casefold().startswith("cable input (")
                  and "vb-audio" in device.description().casefold()), None)
    cable_output = any(
        device.description().casefold().startswith("cable output (")
        and "vb-audio" in device.description().casefold()
        for device in QMediaDevices.audioInputs()
    )
    if cable is None or not cable_output:
        raise AudioRoutingError(
            "VB-CABLE is unavailable. Install or enable VB-Audio Virtual Cable "
            "so Windows lists both CABLE Input and CABLE Output, then try again."
        )
    return speaker, cable


def microphone_format(microphone, cable):
    """Use the same PCM format at both ends, including mono microphones."""
    formats = [microphone.preferredFormat()]
    for rate in (48000, 44100):
        for channels in (1, 2):
            for sample_format in (QAudioFormat.Float, QAudioFormat.Int16):
                fmt = QAudioFormat()
                fmt.setSampleRate(rate)
                fmt.setChannelCount(channels)
                fmt.setSampleFormat(sample_format)
                formats.append(fmt)
    for fmt in formats:
        if microphone.isFormatSupported(fmt) and cable.isFormatSupported(fmt):
            return fmt
    raise AudioRoutingError(
        "The microphone and VB-CABLE have no compatible audio format. "
        "Set them to 48000 Hz in Windows sound settings."
    )


@dataclass
class _Playback:
    path: Path
    volume: int
    preview: bool
    cancel: Event
    done: Event = field(default_factory=Event)
    started: Event = field(default_factory=Event)
    error: Exception | None = None


class _AudioSession(QObject):
    """All multimedia objects are created and destroyed on this Qt thread."""

    def __init__(self):
        super().__init__()
        self._request = None
        self._players = []
        self._outputs = []
        self._playback_ids = set()
        self._microphone = None
        self._mic_sink = None
        self._mic_reader = None
        self._mic_targets = None
        self._timer = None
        self._devices = None

    def _initialize(self):
        if self._timer is None:
            self._timer = QTimer(self)
            self._timer.setInterval(50)
            self._timer.timeout.connect(self._tick)
            self._timer.start()
            self._devices = QMediaDevices(self)
            self._devices.audioOutputsChanged.connect(self._devices_changed)
            self._devices.audioInputsChanged.connect(self._devices_changed)

    def _ensure_microphone(self, cable):
        microphone = QMediaDevices.defaultAudioInput()
        if microphone.isNull() or _is_cable(microphone):
            raise AudioRoutingError(
                "Select your real microphone as the default Windows input. "
                "Use CABLE Output inside your voice app to hear your voice and clips."
            )
        targets = (bytes(microphone.id()), bytes(cable.id()))
        if targets == self._mic_targets:
            return
        self._close_microphone()
        fmt = microphone_format(microphone, cable)
        try:
            self._microphone = QAudioSource(microphone, fmt, self)
            self._microphone.setBufferSize(fmt.bytesForDuration(40000))
            self._mic_reader = self._microphone.start()
            if self._mic_reader is None or self._microphone.error() != QtAudio.NoError:
                raise AudioRoutingError(
                    "Could not open the microphone. Check Windows microphone "
                    "access for desktop apps and close apps using exclusive audio."
                )
            self._mic_sink = QAudioSink(cable, fmt, self)
            self._mic_sink.setBufferSize(fmt.bytesForDuration(80000))
            # Pull from the source's bounded buffer. Pushing directly into a
            # sink QIODevice can stall permanently after a short write.
            self._mic_sink.start(self._mic_reader)
            if (self._mic_reader is None
                    or self._microphone.error() != QtAudio.NoError
                    or self._mic_sink.error() not in (QtAudio.NoError, QtAudio.UnderrunError)):
                raise AudioRoutingError(
                    "Could not open the microphone or VB-CABLE. Check Windows "
                    "microphone access for desktop apps and close apps using exclusive audio."
                )
            self._mic_targets = targets
            LOG.info("Microphone %s -> %s", microphone.description(), cable.description())
        except Exception:
            self._close_microphone()
            raise

    def _check_microphone(self):
        if self._microphone is None:
            return
        if (self._microphone.error() != QtAudio.NoError
                or self._mic_sink.error() not in (QtAudio.NoError, QtAudio.UnderrunError)):
            raise AudioRoutingError("The microphone or VB-CABLE disconnected. Check Windows sound settings.")

    @Slot(object)
    def begin(self, request):
        self._request = request
        try:
            if request.cancel.is_set():
                raise AudioCancelled()
            self._initialize()
            speaker, cable = playback_devices(preview=request.preview)
            if cable is not None:
                self._ensure_microphone(cable)
            if request.cancel.is_set():
                raise AudioCancelled()
            devices = [speaker] if cable is None else [speaker, cable]
            self._playback_ids = {bytes(device.id()) for device in devices}
            for device in devices:
                output = QAudioOutput(device, self)
                output.setVolume(max(0, min(100, request.volume)) / 100)
                player = QMediaPlayer(self)
                self._outputs.append(output)
                self._players.append(player)
                player.setAudioOutput(output)
                player.setSource(QUrl.fromLocalFile(str(request.path)))
            self._last_positions = [None] * len(self._players)
            self._progress_deadlines = [monotonic() + 15] * len(self._players)
            for player in self._players:
                if request.cancel.is_set():
                    raise AudioCancelled()
                player.play()
            LOG.info("Clip -> %s", ", ".join(device.description() for device in devices))
        except Exception as error:
            self._finish(error)

    @Slot()
    def _tick(self):
        try:
            self._check_microphone()
        except Exception as error:
            LOG.error("Microphone routing failed: %s", error)
            self._close_microphone()
            if self._request is not None:
                self._finish(error)
        request = self._request
        if request is None:
            return
        try:
            if request.cancel.is_set():
                raise AudioCancelled()
            for player in self._players:
                if player.error() != QMediaPlayer.NoError:
                    raise AudioRoutingError(f"Windows audio playback failed: {player.errorString()}")
            if all(player.mediaStatus() == QMediaPlayer.EndOfMedia for player in self._players):
                self._finish()
                return
            if all(player.playbackState() == QMediaPlayer.PlayingState
                   or player.mediaStatus() == QMediaPlayer.EndOfMedia for player in self._players):
                request.started.set()
            for index, player in enumerate(self._players):
                if player.mediaStatus() == QMediaPlayer.EndOfMedia:
                    continue
                position = player.position()
                if position != self._last_positions[index]:
                    self._last_positions[index] = position
                    self._progress_deadlines[index] = monotonic() + 15
                elif monotonic() > self._progress_deadlines[index]:
                    raise AudioRoutingError("Windows audio playback stalled. Check the selected audio devices.")
        except Exception as error:
            self._finish(error)

    @Slot()
    def _devices_changed(self):
        outputs = {bytes(device.id()) for device in QMediaDevices.audioOutputs()}
        inputs = {bytes(device.id()) for device in QMediaDevices.audioInputs()}
        if self._mic_targets is not None:
            microphone, cable = self._mic_targets
            if microphone not in inputs or cable not in outputs:
                self._close_microphone()
                if self._request is not None:
                    self._finish(AudioRoutingError("The microphone or VB-CABLE disconnected."))
        if self._request is not None and not self._playback_ids <= outputs:
            self._finish(AudioRoutingError("A playback device disconnected. Check Windows sound settings."))

    def _finish(self, error=None):
        request, self._request = self._request, None
        for player in self._players:
            player.stop()
            # Release the decoder/file before the worker deletes its WAV.
            player.setSource(QUrl())
            player.setAudioOutput(None)
            player.deleteLater()
        for output in self._outputs:
            output.deleteLater()
        self._players.clear()
        self._outputs.clear()
        if request is not None:
            request.error = error
            request.done.set()

    def _close_microphone(self):
        # The sink reads a QIODevice owned by the source; detach it first.
        if self._mic_sink is not None:
            self._mic_sink.reset()
            self._mic_sink.deleteLater()
        if self._microphone is not None:
            self._microphone.stop()
            self._microphone.deleteLater()
        self._microphone = self._mic_sink = None
        self._mic_reader = None
        self._mic_targets = None

    @Slot(object)
    def shutdown(self, done):
        try:
            self._finish(AudioCancelled())
            self._close_microphone()
            if self._timer is not None:
                self._timer.stop()
        finally:
            done.set()


class WindowsAudio(QObject):
    """Synchronous worker-facing API, with an event loop for live mic audio."""

    _begin = Signal(object)
    _shutdown = Signal(object)

    def __init__(self):
        super().__init__()
        self._thread = QThread()
        self._session = _AudioSession()
        self._session.moveToThread(self._thread)
        self._begin.connect(self._session.begin)
        self._shutdown.connect(self._session.shutdown)
        self._thread.finished.connect(self._session.deleteLater)
        self._thread.start()

    def play(self, path, *, volume, preview, cancel, on_started):
        request = _Playback(Path(path), volume, preview, cancel)
        self._begin.emit(request)
        reported = False
        while not request.done.wait(0.05):
            if request.started.is_set() and not reported:
                on_started()
                reported = True
        if request.error is not None:
            raise request.error

    def close(self):
        if not self._thread.isRunning():
            return
        done = Event()
        self._shutdown.emit(done)
        done.wait()
        self._thread.quit()
        self._thread.wait()
