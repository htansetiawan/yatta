"""Runtime settings. Everything machine- or person-specific comes from the environment (or an env file),
so the repository holds no paths to anyone's data, no keys and no model weights.

Settings are read from, in order: the process environment, then ``$YATTA_ENV_FILE`` (default
``~/.config/yatta/env``), a KEY=VALUE file kept outside the repository.
"""

import os
from dataclasses import dataclass, field
from pathlib import Path

HOME = Path.home()
PACKAGE = Path(__file__).resolve().parent


def _env_file():
    values = {}
    path = Path(os.environ.get("YATTA_ENV_FILE", HOME / ".config/yatta/env"))
    if path.is_file():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("'\"")
    return values


_FILE = _env_file()


def env(key, default=""):
    return os.environ.get(key, _FILE.get(key, default))


def env_path(key, default):
    return Path(os.path.expanduser(env(key, str(default))))


@dataclass(frozen=True)
class Settings:
    data: Path = field(default_factory=lambda: env_path("YATTA_DATA", HOME / ".local/share/yatta"))
    auth_file: Path = field(default_factory=lambda: env_path("YATTA_AUTH_FILE", HOME / ".config/yatta/auth.json"))
    # Hosts the server answers; the first is canonical (others redirect to it).
    hosts: tuple = field(default_factory=lambda: tuple(h.strip() for h in env(
        "YATTA_HOSTS", "yatta.enrica.ai,avatar.enrica.ai").split(",") if h.strip()))
    web_dist: Path = field(default_factory=lambda: env_path("YATTA_WEB_DIST", PACKAGE.parents[1] / "web/dist"))
    # Engines. GaussianTalker tooling (environments and scripts) lives in its research repository.
    gaussian_talker: Path = field(default_factory=lambda: env_path("GAUSSIAN_TALKER_ROOT", HOME / "git/gaussian-talker"))
    latentsync: Path = field(default_factory=lambda: env_path("LATENTSYNC_ROOT", HOME / "git/gaussian-talker/.local/src/LatentSync"))
    latentsync_python: Path = field(default_factory=lambda: env_path(
        "LATENTSYNC_PYTHON", HOME / "git/gaussian-talker/.local/envs/latentsync/bin/python"))
    longcat: Path = field(default_factory=lambda: env_path("LONGCAT_ROOT", HOME / "git/gaussian-talker/.local/src/LongCat-Video"))
    longcat_python: Path = field(default_factory=lambda: env_path(
        "LONGCAT_PYTHON", HOME / "git/gaussian-talker/.local/envs/longcat/bin/python"))
    comfyui: Path = field(default_factory=lambda: env_path("COMFYUI_ROOT", HOME / "git/gaussian-talker/.local/src/ComfyUI"))
    comfyui_python: Path = field(default_factory=lambda: env_path(
        "COMFYUI_PYTHON", HOME / "git/gaussian-talker/.local/envs/comfyui/bin/python"))
    comfyui_port: int = field(default_factory=lambda: int(env("YATTA_COMFYUI_PORT", "8188")))
    narrate: Path = field(default_factory=lambda: env_path("NARRATE_BIN", HOME / "git/narrate/narrate"))
    gpu_poll_seconds: int = field(default_factory=lambda: int(env("YATTA_GPU_POLL", "1800")))
    min_free_gb: float = field(default_factory=lambda: float(env("YATTA_MIN_FREE_GB", "15")))
    training_configs: Path = field(default_factory=lambda: env_path(
        "YATTA_TRAINING_CONFIGS", PACKAGE / "training/configs"))

    @property
    def canonical_host(self):
        return self.hosts[0] if self.hosts else "localhost"

    # GaussianTalker repository layout
    def gt(self, *parts):
        return self.gaussian_talker.joinpath(*parts)

    @property
    def gt_python(self):
        return self.gt(".venv/bin/python")

    @property
    def deepspeech_python(self):
        return self.gt(".local/envs/deepspeech/bin/python")

    @property
    def speechfeat_python(self):
        return self.gt(".local/envs/speechfeat/bin/python")

    @property
    def mms_python(self):
        return self.gt(".local/envs/tts/bin/python")

    @property
    def studio_python(self):
        """Interpreter running this server (used by training scripts to query the GPU gate)."""
        import sys
        return Path(sys.executable)


settings = Settings()
