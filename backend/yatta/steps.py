"""Steps every render shares, whichever engine draws the video: running tools, speech, audio levels and encoding.

Speech comes from ElevenLabs, Meta MMS, a cloned voice (narrate / F5-TTS) or an upload, and is levelled
and padded into a 16 kHz mono WAV. Engines (``yatta.engines``) turn that WAV into a video, and
``encode`` makes the final H.264 MP4 and its poster.
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from yatta import core
from yatta.config import PACKAGE, settings

ROOT = settings.gaussian_talker  # research repository: tool environments and scripts
PY = settings.gt_python
TTS_PY = settings.mms_python
NARRATE = settings.narrate  # htansetiawan/narrate (F5-TTS)
MAX_SECONDS = 300  # 5 minutes (Henry, 2026-10-26)


class StepError(RuntimeError):
    pass


def run(command, log, cwd=ROOT, env=None):
    """Run a command, appending its output to ``log``; raise StepError on failure."""
    with open(log, "a") as out:
        out.write("$ " + " ".join(str(c) for c in command) + "\n")
        out.flush()
        result = subprocess.run([str(c) for c in command], cwd=cwd, stdout=out, stderr=subprocess.STDOUT,
                                stdin=subprocess.DEVNULL, env={**os.environ, **(env or {})})
    if result.returncode != 0:
        raise StepError(f"{Path(str(command[1] if len(command) > 1 else command[0])).name} failed (exit {result.returncode}); see {log}")


def ffmpeg(args, log):
    run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-y"] + list(args), log)


def mean_volume(path):
    out = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return core.parse_mean_volume(out.stderr)


def duration(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, stdin=subprocess.DEVNULL)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return None


def image_size(path):
    out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                          "-of", "csv=p=0", str(path)], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    width, height = out.stdout.strip().split(",")[:2]
    return int(width), int(height)


# ---- speech ------------------------------------------------------------------------------------------

def synthesize(voice, text, upload, out_wav, log):
    """Produce speech audio for a job. voice = {"provider": "elevenlabs"|"mms"|"clone"|"upload", "id": ...}."""
    provider = voice["provider"]
    if provider == "elevenlabs":
        voices = json.loads((PACKAGE / "catalog/voices.json").read_text())
        run([sys.executable, "-m", "yatta.elevenlabs", "--voice", voice["id"], "--text", text,
             "--output", out_wav, "--model", voices["elevenlabs_model"]], log)
    elif provider == "clone":
        profile = clone_profile(voice["id"])
        if profile.get("state") != "ready":
            raise StepError("this cloned voice is not ready yet")
        narrate(profile, text, out_wav, log)
    elif provider == "mms":
        run([TTS_PY, ROOT / "scripts/synthesize_speech.py", "--lang", voice["id"], "--text", text, "--output", out_wav], log)
    elif provider == "upload":
        if not upload or not Path(upload).is_file():
            raise StepError("uploaded audio is missing")
        ffmpeg(["-i", upload, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out_wav], log)
    else:
        raise StepError(f"unknown voice provider {provider}")


def clone_available():
    return NARRATE.is_file()


def clone_profile(voice_id):
    if "/" in voice_id or voice_id.startswith("."):
        raise StepError("bad voice id")
    path = core.DATA / "voices" / voice_id / "voice.json"
    if not path.is_file():
        raise StepError("unknown cloned voice")
    return json.loads(path.read_text())


def narrate(profile, text, out_wav, log, out_dir=None):
    """Speak ``text`` in a cloned voice with narrate (F5-TTS); writes 16 kHz mono WAV. Returns narration.json."""
    folder = Path(out_dir or Path(out_wav).parent / "narrate")
    shutil.rmtree(folder, ignore_errors=True)
    command = [NARRATE, "--voice", profile["reference"], "--text", text, "--out", folder]
    if profile.get("clip"):
        command += ["--clip", profile["clip"]]
    if profile.get("text"):
        command += ["--voice-text", profile["text"]]
    run(command, log)
    takes = sorted(folder.glob("*.mp3"))
    if not takes:
        raise StepError(f"narrate produced no audio; see {log}")
    ffmpeg(["-i", takes[0], "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out_wav], log)
    return json.loads((folder / "narration.json").read_text())


def level_audio(raw_wav, reference_wav, out_wav, log, lead=0.2, tail=0.4):
    """Match the speech level to the avatar's training audio (DeepSpeech is level-sensitive) and pad it."""
    gain = core.gain_db(mean_volume(reference_wav), mean_volume(raw_wav)) if reference_wav else 0.0
    delay = int(lead * 1000)
    ffmpeg(["-i", raw_wav, "-af", f"volume={gain}dB,adelay={delay}|{delay},apad=pad_dur={tail}",
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", out_wav], log)
    seconds = duration(out_wav) or 0
    if seconds > MAX_SECONDS:
        raise StepError(f"speech is {seconds:.0f} s; Yatta renders at most {MAX_SECONDS} s")
    return gain, seconds


def elevenlabs_available():
    """True if an ElevenLabs key is configured (env var, ~/.config/elevenlabs/api_key or ~/.elevenlabs/env)."""
    from yatta import elevenlabs
    return bool(elevenlabs.read_api_key())


# ---- video ---------------------------------------------------------------------------------------------

def encode(video, out_mp4, poster, log):
    """Final H.264 + AAC MP4 (web-friendly) and a poster frame, from any engine's output."""
    ffmpeg(["-i", video, "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_mp4], log)
    ffmpeg(["-ss", "0.6", "-i", out_mp4, "-frames:v", "1", "-q:v", "3", poster], log)


def poster_for(video, out_jpg, log, at=1.0):
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(["-ss", str(at), "-i", video, "-frames:v", "1", "-q:v", "3", out_jpg], log)
