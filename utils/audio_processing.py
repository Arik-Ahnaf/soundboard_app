"""Prepare attenuated audio before it is allowed to reach an output device.

These are digital level limits, not a guarantee about acoustic sound pressure:
headphone sensitivity, amplifiers, system gain and listening duration still matter.
Only the validated WAV returned by ``prepare_audio`` should be played. Callers
must keep its temporary directory alive until playback has finished.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import threading
from uuid import uuid4


MAX_INTEGRATED_LUFS = -23.0
MAX_TRUE_PEAK_DBTP = -6.0
# loudnorm reports measurements to two decimal places. Leave headroom for that
# rounding and for rendering; the rendered file is measured again regardless.
_MARGIN_DB = 0.2
_SAMPLE_RATE = 48_000
_FLOAT_SUBFORMAT = bytes.fromhex("0300000000001000800000aa00389b71")


class AudioProcessingError(RuntimeError):
    """The source could not be decoded or verified for playback."""


class AudioCancelled(AudioProcessingError):
    """Preparation was cancelled before any audio was played."""


def find_ffmpeg() -> str:
    executable = shutil.which("ffmpeg")
    if executable is not None:
        return executable
    if sys.platform == "win32":
        # Windows wheels include an executable, so playback does not require a
        # separate FFmpeg installation or a change to the user's PATH.
        try:
            from imageio_ffmpeg import get_ffmpeg_exe

            return get_ffmpeg_exe()
        except (ImportError, OSError, RuntimeError) as error:
            raise AudioProcessingError(
                "FFmpeg is required to check audio levels. Run 'uv sync' to "
                "install the bundled Windows FFmpeg, or install FFmpeg on PATH."
            ) from error
    raise AudioProcessingError(
        "FFmpeg is required to check audio levels. Install the Arch Linux "
        "'ffmpeg' package, then try again."
    )


def _check_cancelled(cancel_event: threading.Event) -> None:
    if cancel_event.is_set():
        raise AudioCancelled("Audio preparation cancelled.")


def _run_ffmpeg(
    executable: str, arguments: list[str], cancel_event: threading.Event
) -> str:
    """Keep PCM and potentially large diagnostics out of process memory."""
    _check_cancelled(cancel_event)
    with tempfile.TemporaryFile() as diagnostics:
        try:
            process = subprocess.Popen(
                [executable, "-hide_banner", "-nostdin", "-nostats", *arguments],
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=diagnostics,
                creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
            )
        except OSError as error:
            raise AudioProcessingError(f"Could not start FFmpeg: {error}") from error
        try:
            while process.poll() is None:
                if cancel_event.wait(0.05):
                    raise AudioCancelled("Audio preparation cancelled.")
            _check_cancelled(cancel_event)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=0.5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        size = diagnostics.seek(0, 2)
        diagnostics.seek(max(0, size - 32_768))
        output = diagnostics.read().decode("utf-8", errors="replace")
        if process.returncode:
            detail = output.strip()[-2_000:]
            raise AudioProcessingError(
                f"FFmpeg could not prepare this audio. {detail}"
            )
        return output


def _sample_peak(path: Path, cancel_event: threading.Event) -> float:
    """Check every sample in our float WAV, including RF64 files, in chunks.

    This catches NaN/Inf and gives an independent instantaneous sample bound;
    loudness meters may report -inf for clips below their gating threshold.
    """
    with path.open("rb") as audio:
        file_size = path.stat().st_size
        header = audio.read(12)
        if len(header) != 12 or header[:4] not in (b"RIFF", b"RF64") or header[8:] != b"WAVE":
            raise AudioProcessingError("FFmpeg produced an invalid WAV file.")
        valid_format = False
        large_data_size = None
        while audio.tell() + 8 <= file_size:
            _check_cancelled(cancel_event)
            chunk, size = struct.unpack("<4sI", audio.read(8))
            if chunk == b"data" and size == 0xFFFFFFFF:
                if large_data_size is None:
                    raise AudioProcessingError("Invalid RF64 audio size.")
                size = large_data_size
            end = audio.tell() + size
            if end > file_size:
                raise AudioProcessingError("The decoded WAV file is truncated.")
            if chunk == b"ds64":
                if size < 28:
                    raise AudioProcessingError("Invalid RF64 header.")
                large_data_size = struct.unpack("<QQ", audio.read(16))[1]
            elif chunk == b"fmt ":
                fmt = audio.read(min(size, 40))
                if len(fmt) < 16:
                    raise AudioProcessingError("Invalid WAV format.")
                codec, channels, rate, _, alignment, bits = struct.unpack("<HHIIHH", fmt[:16])
                is_float = codec == 3 or (
                    codec == 0xFFFE and len(fmt) >= 40 and fmt[24:40] == _FLOAT_SUBFORMAT
                )
                valid_format = is_float and (channels, rate, alignment, bits) == (2, _SAMPLE_RATE, 8, 32)
            elif chunk == b"data":
                if not valid_format or not size or size % 8:
                    raise AudioProcessingError("The decoded audio is empty or has an invalid format.")
                peak = 0.0
                remaining = size
                while remaining:
                    _check_cancelled(cancel_event)
                    block = audio.read(min(65_536, remaining))
                    if not block or len(block) % 8:
                        raise AudioProcessingError("The decoded audio is truncated.")
                    for (sample,) in struct.iter_unpack("<f", block):
                        if not math.isfinite(sample):
                            raise AudioProcessingError("Audio contains invalid (NaN or infinite) samples.")
                        peak = max(peak, abs(sample))
                    remaining -= len(block)
                return -math.inf if peak == 0 else 20 * math.log10(peak)
            audio.seek(end + size % 2)
    raise AudioProcessingError("The decoded WAV contains no audio samples.")


def _measure(
    executable: str, path: Path, cancel_event: threading.Event
) -> tuple[float, float, float]:
    sample_peak = _sample_peak(path, cancel_event)
    # Only read the *input* statistics: loudnorm's normalized output is discarded.
    # Its dynamic measurement pass oversamples to 192 kHz for true-peak analysis.
    # https://ffmpeg.org/ffmpeg-filters.html#loudnorm
    output = _run_ffmpeg(
        executable,
        [
            "-v", "info", "-protocol_whitelist", "file,pipe", "-i", str(path),
            "-map", "0:a:0", "-af",
            f"loudnorm=I={MAX_INTEGRATED_LUFS}:TP={MAX_TRUE_PEAK_DBTP}:linear=false:print_format=json",
            "-f", "null", "-",
        ],
        cancel_event,
    )
    try:
        blocks = re.findall(r'\{\s*"input_i"\s*:.*?\}', output, flags=re.DOTALL)
        report = json.loads(blocks[-1])
        integrated = float(report["input_i"])
        true_peak = float(report["input_tp"])
    except (IndexError, KeyError, TypeError, ValueError) as error:
        raise AudioProcessingError("FFmpeg did not return valid audio level measurements.") from error
    if any(math.isnan(level) or level == math.inf for level in (integrated, true_peak)):
        raise AudioProcessingError("Audio level measurements are not finite.")
    if true_peak == -math.inf and sample_peak != -math.inf:
        raise AudioProcessingError("FFmpeg could not verify the true peak of this audio.")
    # -inf integrated loudness is valid for silence and clips shorter than the
    # 400 ms loudness gate. Nonzero audio without a loudness measurement receives
    # the more conservative peak ceiling below.
    return integrated, true_peak, sample_peak


def _peak_limit(levels: tuple[float, float, float]) -> float:
    integrated, _, sample_peak = levels
    if integrated == -math.inf and sample_peak != -math.inf:
        # A short clip otherwise could be ~17 dB louder than a slightly longer
        # version of the same sound just because it misses the loudness gate.
        return min(MAX_INTEGRATED_LUFS, MAX_TRUE_PEAK_DBTP)
    return MAX_TRUE_PEAK_DBTP


def _required_gain(levels: tuple[float, float, float]) -> float:
    integrated, true_peak, sample_peak = levels
    peak_limit = _peak_limit(levels)
    return min(
        0.0,
        MAX_INTEGRATED_LUFS - _MARGIN_DB - integrated,
        peak_limit - _MARGIN_DB - true_peak,
        peak_limit - _MARGIN_DB - sample_peak,
    )


def prepare_audio(path: Path, work_dir: Path, cancel_event: threading.Event) -> Path:
    """Return a verified WAV with at most -23 LUFS and -6 dBTP, never boosted.

    When integrated loudness cannot be measured, nonzero audio instead receives
    a conservative -23 dBTP peak ceiling. Silence remains unchanged.

    The source is decoded once into an immutable working snapshot so edits to
    the original cannot bypass the checks. Processing and verification finish
    before this function returns; errors must never fall back to the original.
    ``work_dir`` must exist and remain private to the caller during playback.
    """
    _check_cancelled(cancel_event)
    executable = find_ffmpeg()
    source = Path(path).resolve()
    if not source.is_file():
        raise AudioProcessingError(f"Audio file does not exist: {source}")
    prefix = uuid4().hex
    snapshot = Path(work_dir).resolve() / f"{prefix}-decoded.wav"
    prepared = Path(work_dir).resolve() / f"{prefix}-prepared.wav"
    succeeded = False
    try:
        _run_ffmpeg(
            executable,
            [
                "-v", "error", "-xerror", "-protocol_whitelist", "file,pipe",
                "-i", str(source), "-map", "0:a:0", "-vn", "-sn", "-dn",
                "-map_metadata", "-1", "-ar", str(_SAMPLE_RATE), "-ac", "2",
                "-c:a", "pcm_f32le", "-rf64", "auto", "-y", str(snapshot),
            ],
            cancel_event,
        )
        gain_db = _required_gain(_measure(executable, snapshot, cancel_event))
        # Re-measure the final sample rate and encoding, correcting any gating
        # differences or rounding. The gain only decreases on each attempt.
        for _ in range(3):
            _run_ffmpeg(
                executable,
                [
                    "-v", "error", "-xerror", "-i", str(snapshot),
                    "-map", "0:a:0", "-map_metadata", "-1", "-af",
                    f"volume={gain_db:.10f}dB:precision=double",
                    "-ar", str(_SAMPLE_RATE), "-ac", "2", "-c:a", "pcm_f32le",
                    "-rf64", "auto", "-y", str(prepared),
                ],
                cancel_event,
            )
            levels = _measure(executable, prepared, cancel_event)
            if (
                levels[0] <= MAX_INTEGRATED_LUFS - _MARGIN_DB / 2
                and max(levels[1:]) <= _peak_limit(levels) - _MARGIN_DB / 2
            ):
                _check_cancelled(cancel_event)
                succeeded = True
                return prepared
            gain_db += _required_gain(levels)
        raise AudioProcessingError("Could not bring this audio within the fixed level limits.")
    except OSError as error:
        raise AudioProcessingError(f"Could not prepare the audio file: {error}") from error
    finally:
        snapshot.unlink(missing_ok=True)
        if not succeeded:
            prepared.unlink(missing_ok=True)
