"""Temporary, app-owned PipeWire routing through its PulseAudio interface.

The microphone enters a private mixing sink. Soundboard playback enters a
different sink that fans out to the physical speakers and the mixing sink.
Only the mixing sink's monitor is exposed as ``Soundboard Mic``; microphone
audio is never intentionally looped back to the speakers.
"""

from dataclasses import dataclass
import json
import logging
import shlex
import subprocess
import sys
from time import monotonic
from uuid import uuid4


class AudioRoutingError(RuntimeError):
    """An actionable error setting up or maintaining audio routing."""


@dataclass
class _Module:
    name: str
    arguments: tuple[str, ...]
    index: int | None = None


class AudioRouting:
    """Own one temporary route; call serially from the playback worker.

    Requires Arch's ``pipewire-pulse`` service and ``pactl`` (``libpulse``).
    No defaults, physical-device volumes, or persistent configuration change.
    ``ensure()`` returns the playback sink; ``speaker()`` is for local previews.
    Call ``close()`` when the application exits, after stopping playback.
    """

    COMMAND_TIMEOUT = 5
    CLEANUP_TIMEOUT = 3

    def __init__(self):
        self._token = uuid4().hex
        prefix = f"soundboard_{self._token}"
        self.mix_sink = f"{prefix}_mix"
        self.microphone = f"{prefix}_mic"
        self.playback_sink = f"{prefix}_playback"
        self._modules: list[_Module] = []
        self._targets: tuple[str, str] | None = None
        self._cleanup_deadline: float | None = None

    def _run(self, *arguments: str) -> str:
        timeout = self.COMMAND_TIMEOUT
        if self._cleanup_deadline is not None:
            timeout = min(timeout, self._cleanup_deadline - monotonic())
            if timeout <= 0:
                raise AudioRoutingError("Temporary audio routing cleanup timed out.")
        try:
            result = subprocess.run(
                ["pactl", *arguments], capture_output=True, text=True,
                check=True, timeout=timeout,
            )
        except FileNotFoundError as exc:
            raise AudioRoutingError(
                "pactl is missing. Install libpulse and pipewire-pulse on Arch "
                "Linux, then start your PipeWire user services."
            ) from exc
        except subprocess.TimeoutExpired as exc:
            if self._cleanup_deadline is not None:
                raise AudioRoutingError("Temporary audio routing cleanup timed out.") from exc
            raise AudioRoutingError("PipeWire did not respond within 5 seconds.") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or "connection failed").strip()
            raise AudioRoutingError(
                f"PipeWire audio routing failed: {detail}. "
                "Check that pipewire and pipewire-pulse are running."
            ) from exc
        except OSError as exc:
            raise AudioRoutingError(f"Could not run pactl: {exc}") from exc
        return result.stdout.strip()

    def _json(self, *arguments: str):
        try:
            return json.loads(self._run("--format=json", *arguments))
        except (ValueError, TypeError) as exc:
            raise AudioRoutingError("pactl returned invalid audio-device information.") from exc

    def _list(self, kind: str) -> list[dict]:
        if kind == "modules":
            # Some pactl versions omit module IDs from JSON entirely. The short
            # format provides IDs and preserves our single-line arguments.
            # Native PipeWire modules can have multiline arguments; their
            # continuation lines are irrelevant to our ownership records.
            modules = []
            for line in self._run("list", "short", "modules").splitlines():
                fields = line.split("\t", 3)
                if len(fields) >= 3 and fields[0].isdigit():
                    modules.append({
                        "index": int(fields[0]), "name": fields[1], "argument": fields[2],
                    })
            return modules
        value = self._json("list", kind)
        if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
            raise AudioRoutingError(f"pactl returned invalid {kind} information.")
        return value

    def _defaults(self, *, microphone: bool) -> tuple[str, str | None]:
        if sys.platform != "linux":
            raise AudioRoutingError("Soundboard playback currently requires Linux with PipeWire.")
        info = self._json("info")
        if not isinstance(info, dict) or "pipewire" not in str(info.get("server_name", "")).lower():
            raise AudioRoutingError(
                "Soundboard requires PipeWire's PulseAudio service (pipewire-pulse)."
            )
        sink = self._physical_device(
            info.get("default_sink_name"), self._list("sinks"), microphone=False
        )
        source = None
        if microphone:
            source = self._physical_device(
                info.get("default_source_name"), self._list("sources"), microphone=True
            )
        return sink, source

    @staticmethod
    def _truthy(value) -> bool:
        return str(value).lower() in {"true", "yes", "1"}

    def _physical_device(self, name, devices: list[dict], *, microphone: bool) -> str:
        label = "microphone" if microphone else "speaker or headphones"
        device = next((item for item in devices if item.get("name") == name), None)
        if not name or device is None:
            raise AudioRoutingError(f"No default {label} is available. Select a connected device in audio settings.")
        props = device.get("properties") or {}
        flags = device.get("flags") or []
        if isinstance(flags, str):
            flags = flags.split()
        monitor = device.get("monitor_of_sink")
        is_monitor = microphone and (
            str(name).endswith(".monitor")
            or monitor not in (None, "n/a", "N/A", -1, 4294967295, "4294967295")
            or props.get("device.class") == "monitor"
        )
        physical = (
            "HARDWARE" in flags
            or props.get("device.api") in {"alsa", "bluez5", "bluez"}
            or props.get("device.bus") in {"pci", "usb", "bluetooth", "isa", "platform"}
        )
        if (str(name).startswith("soundboard_") or is_monitor
                or self._truthy(props.get("node.virtual"))
                or props.get("device.class") in {"filter", "abstract"}
                or not physical):
            raise AudioRoutingError(
                f"The default {label} is virtual or a monitor. Select your real "
                f"{label} in system audio settings; select Soundboard Mic only "
                "inside your voice app."
            )
        return str(name)

    def speaker(self) -> str:
        """Resolve and validate the current physical speaker for a preview."""
        return self._defaults(microphone=False)[0]

    @staticmethod
    def _argument_key(arguments: str) -> tuple[str, ...]:
        # pactl exposes the module argument string, not the original argv.
        # Parse only for comparison; never execute this text.
        try:
            return tuple(shlex.split(arguments))
        except ValueError:
            return ()

    def _matches(self, module: _Module, candidate: dict) -> bool:
        return (
            (module.index is None or candidate.get("index") == module.index)
            and candidate.get("name") == module.name
            and self._argument_key(str(candidate.get("argument", "")))
            == self._argument_key(" ".join(module.arguments))
        )

    def _load(self, name: str, *arguments: str):
        # Record the request first. A timeout can occur after the server loaded
        # it; close() can find that exact request by its unique arguments.
        module = _Module(name, arguments)
        self._modules.append(module)
        result = self._run("load-module", name, *arguments)
        try:
            module.index = int(result)
        except ValueError as exc:
            raise AudioRoutingError("PipeWire did not return the new module's ID.") from exc

    def _properties(self, description: str) -> str:
        return (
            f"'device.description=\"{description}\" "
            f"soundboard.instance={self._token} node.virtual=true priority.session=0'"
        )

    @staticmethod
    def _owned_device(device: dict, module: _Module, token: str) -> bool:
        owner = device.get("owner_module")
        props = device.get("properties") or {}
        return str(owner) == str(module.index) or props.get("soundboard.instance") == token

    def _route_devices(self) -> list[tuple[str, dict]] | None:
        if len(self._modules) != 4:
            return None
        devices = {"sink": self._list("sinks"), "source": self._list("sources")}
        wanted = (
            ("sink", self.mix_sink, self._modules[0]),
            ("source", self.microphone, self._modules[1]),
            ("sink", self.playback_sink, self._modules[3]),
        )
        result = []
        for kind, name, module in wanted:
            device = next((item for item in devices[kind] if item.get("name") == name), None)
            if device is None or not self._owned_device(device, module, self._token):
                return None
            result.append((kind, device))
        return result

    def _healthy(self) -> bool:
        if len(self._modules) != 4 or any(module.index is None for module in self._modules):
            return False
        current = self._list("modules")
        return all(any(self._matches(module, item) for item in current) for module in self._modules)

    def _unity_gain(self, devices: list[tuple[str, dict]]):
        # Do not allow restored virtual-device/stream gains to boost clips.
        # Physical device and microphone controls belong to the user.
        for kind, device in devices:
            self._run(f"set-{kind}-volume", str(device["name"]), "100%")
            self._run(f"set-{kind}-mute", str(device["name"]), "0")
        # Stream owner_module is a string in some pactl versions, whereas device
        # owner_module is an integer in the very same response format.
        owned_ids = {str(module.index) for module in self._modules}
        for kind, plural in (("sink-input", "sink-inputs"), ("source-output", "source-outputs")):
            for stream in self._list(plural):
                if str(stream.get("owner_module")) in owned_ids:
                    self._run(f"set-{kind}-volume", str(stream["index"]), "100%")
                    self._run(f"set-{kind}-mute", str(stream["index"]), "0")

    def ensure(self) -> str:
        """Create/revalidate the route, following current physical defaults.

        Leaves the real microphone feeding Soundboard Mic between clips. If a
        default changed or the audio server restarted, rebuild only our route.
        Fails closed when a selected default could feed sound back into itself.
        """
        try:
            speaker, microphone = self._defaults(microphone=True)
            targets = (speaker, microphone)
            devices = None
            if self._targets == targets and self._healthy():
                devices = self._route_devices()
            if devices is None:
                self.close()
                self._load(
                    "module-null-sink", f"sink_name={self.mix_sink}",
                    f"sink_properties={self._properties('Soundboard Mix')}",
                    "rate=48000", "channels=2", "channel_map=front-left,front-right",
                )
                self._load(
                    "module-remap-source", f"master={self.mix_sink}.monitor",
                    f"source_name={self.microphone}",
                    f"source_properties={self._properties('Soundboard Mic')}",
                    "rate=48000", "channels=2", "channel_map=front-left,front-right", "remix=no",
                )
                fixed_target = "'node.dont-reconnect=true node.dont-fallback=true'"
                self._load(
                    "module-loopback", f"source={microphone}", f"sink={self.mix_sink}",
                    "latency_msec=30", "source_dont_move=true", "sink_dont_move=true",
                    f"source_output_properties={fixed_target}", f"sink_input_properties={fixed_target}",
                )
                self._load(
                    "module-combine-sink", f"sink_name={self.playback_sink}",
                    f"sinks={speaker},{self.mix_sink}",
                    f"sink_properties={self._properties('Soundboard Playback')}",
                    "rate=48000", "channels=2", "channel_map=front-left,front-right",
                    "latency_compensate=true",
                )
                self._targets = targets
                if not self._healthy():
                    raise AudioRoutingError("PipeWire did not retain the Soundboard audio route.")
                devices = self._route_devices()
                if devices is None:
                    raise AudioRoutingError("PipeWire did not create the Soundboard audio devices.")
            self._unity_gain(devices)
            return self.playback_sink
        except Exception:
            try:
                self.close()
            except AudioRoutingError:
                logging.getLogger(__name__).exception("Could not clean up the failed Soundboard route")
            raise

    def close(self):
        """Unload only owned modules, in reverse order; safe to call repeatedly.

        Identity checks avoid unloading unrelated modules after ID reuse. A
        failed cleanup retains its ownership records so a later call can retry.
        The whole cleanup pass shares one deadline so shutdown cannot incur
        a full command timeout for every module when the server is unavailable.
        """
        self._targets = None
        failures = []
        self._cleanup_deadline = monotonic() + self.CLEANUP_TIMEOUT
        try:
            for module in list(reversed(self._modules)):
                if monotonic() >= self._cleanup_deadline:
                    failures.append("Temporary audio routing cleanup timed out.")
                    break
                try:
                    current = self._list("modules")
                    matches = [item for item in current if self._matches(module, item)]
                    for match in matches:
                        self._run("unload-module", str(match["index"]))
                    self._modules.remove(module)
                except AudioRoutingError as exc:
                    failures.append(str(exc))
        finally:
            self._cleanup_deadline = None
        if failures:
            raise AudioRoutingError("Could not remove temporary Soundboard audio routing: " + failures[0])
