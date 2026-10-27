"""Lifelike: MiniMax H3 (reference-to-video) generates the video from one photo of the avatar, animated to the speech.

It runs locally through ComfyUI (``scripts/run_minimax_h3.py`` in the research repository, experiment 007); nothing is
sent to MiniMax. H3 makes at most about 15 s per generation, so the speech is cut at pauses into pieces of up to
14.5 s, each piece is generated from the same photo, and the pieces are joined. H3 regenerates the soundtrack it is
given; the final video keeps the original speech instead (H3 follows its timing to within about 20 ms).

ComfyUI is started for each render and stopped afterwards: even idle it keeps about 40 GB of GPU memory.
"""

import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

from yatta import core, steps
from yatta.config import settings
from yatta.engines.base import Engine, face_photo

ROOT = settings.gaussian_talker
COMFY = settings.comfyui
PY = settings.comfyui_python
PORT = settings.comfyui_port
RUNNER = ROOT / "scripts/run_minimax_h3.py"
MODELS = ("diffusion_models/minimax_h3_ref2va_int8_convrot.safetensors",
          "text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
          "vae/minimax_h3_video_vae_fp16.safetensors", "vae/minimax_h3_audio_vae_fp32.safetensors",
          "loras/minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors")
MAX_PIECE = 14.5  # seconds; H3's trained range is 124-362 frames at 24 fps (5.2-15 s)
MIN_PIECE = 5.2


class MiniMaxH3(Engine):
    id = "minimax_h3"
    name = "Lifelike"
    model = "MiniMax H3"
    summary = "Generated from one photo · keeps your look, natural motion"
    badge = "New"
    needs = "photo"
    background_note = "Keeps the room from the avatar's photo."
    min_free_mib = 40000
    load_seconds = 1500  # loading ~50 GB of weights from the Seagate drive dominates
    seconds_per_second = 4  # 4-step turbo: 18 s of sampling for 5.9 s of video
    licence = "MiniMax H3 Community License; US use authorized by MiniMax for Harvard (Henry's final project)"

    def speed(self):
        return "~25 min to load, then ~40 s per 10 s of speech"

    def available(self):
        return (PY.is_file() and RUNNER.is_file() and (COMFY / "main.py").is_file()
                and all((COMFY / "models" / m).exists() for m in MODELS))

    def render(self, job):
        photo = face_photo(job.variant, job.log)
        work = job.dir / "h3"
        work.mkdir(exist_ok=True)
        pieces = core.split_at_pauses(silences(job.speech), job.seconds, MAX_PIECE, MIN_PIECE)
        server = start_server(job.dir / "comfyui.log")
        try:
            parts = []
            for index, (start, end) in enumerate(pieces):
                job.status("rendering", f"MiniMax H3: piece {index + 1} of {len(pieces)}"
                           + (" (loading the model first, about 25 min)" if index == 0 else ""))
                audio = work / f"speech_{index:02d}.wav"
                steps.ffmpeg(["-ss", f"{start:.3f}", "-to", f"{end:.3f}", "-i", job.speech, "-c:a", "pcm_s16le", audio], job.log)
                raw = work / f"h3_{index:02d}.mp4"
                steps.run(["python3", RUNNER, "--image", photo, "--audio", audio, "--out", raw, "--turbo",
                           "--width", "640", "--height", "640", "--seconds", f"{max(end - start, MIN_PIECE):.3f}",
                           "--server", f"http://127.0.0.1:{PORT}"], job.log, env={"PYTHONUNBUFFERED": "1"})
                part = work / f"part_{index:02d}.mp4"
                # Keep H3's frames for the piece's length and put the original speech back.
                steps.ffmpeg(["-i", raw, "-i", audio, "-map", "0:v", "-map", "1:a", "-t", f"{end - start:.3f}",
                              "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", part], job.log)
                parts.append(part)
        finally:
            stop_server(server)
        out = job.dir / "minimax_h3.mp4"
        if len(parts) == 1:
            os.replace(parts[0], out)
        else:
            listing = work / "parts.txt"
            listing.write_text("".join(f"file '{p}'\n" for p in parts))
            steps.ffmpeg(["-f", "concat", "-safe", "0", "-i", listing, "-c:v", "libx264", "-crf", "16",
                          "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", out], job.log)
        return out

    def cleanup(self, job, output):
        output.unlink(missing_ok=True)
        for path in (job.dir / "h3").glob("*"):
            path.unlink(missing_ok=True)


def silences(wav):
    out = subprocess.run(["ffmpeg", "-nostdin", "-hide_banner", "-i", str(wav), "-af", "silencedetect=noise=-35dB:d=0.2",
                          "-f", "null", "-"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    return core.parse_silences(out.stderr)


def start_server(log, timeout=300):
    """Start ComfyUI on 127.0.0.1 only, offline (no partner/API nodes, frontend without internet)."""
    with open(log, "a") as out:
        process = subprocess.Popen([str(PY), "main.py", "--listen", "127.0.0.1", "--port", str(PORT), "--offline",
                                    "--disable-metadata"], cwd=COMFY, stdout=out, stderr=subprocess.STDOUT,
                                   stdin=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if process.poll() is not None:
            raise steps.StepError(f"ComfyUI exited (code {process.returncode}); see {log}")
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{PORT}/system_stats", timeout=5) as response:
                json.loads(response.read())
                return process
        except OSError:
            time.sleep(2)
    stop_server(process)
    raise steps.StepError(f"ComfyUI did not start within {timeout} s; see {log}")


def stop_server(process):
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait()
