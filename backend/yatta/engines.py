"""Engines: speech (ElevenLabs, MMS, cloned voices) -> features -> GaussianTalker or LatentSync render -> MP4.

Every render works in its own job directory. The avatar's dataset and model are linked, never
written: the job's ``data/`` mirrors the identity directory with symlinks, but has its own
``bc.jpg`` (background), its own ``transforms_val.json`` (validation head poses looped
back and forth to the speech length) and the speech files; the job's ``model/`` links the
trained point cloud, so upstream's render outputs land in the job directory.

Two slim stand-ins make loading fast without changing the frames. ``track_params.pt`` is a
cached copy whose per-frame mesh vertices are replaced by their average (all the reader uses them
for); cameras need only ``euler`` and ``trans``, but upstream loads the whole file (3.6–5.6 GB)
six times per render. ``transforms_train.json`` keeps two
training frames; training cameras only feed the camera extent and timeline, which are used when
initializing a new point cloud, never when rendering a trained one.
"""

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from yatta import core
from yatta.config import PACKAGE, settings

ROOT = settings.gaussian_talker  # GaussianTalker research repository: environments and scripts
PY = settings.gt_python
DEEPSPEECH_PY = settings.deepspeech_python
SPEECHFEAT_PY = settings.speechfeat_python
TTS_PY = settings.mms_python
NARRATE = settings.narrate  # htansetiawan/narrate (F5-TTS)
LATENTSYNC = settings.latentsync  # bytedance/LatentSync a229c39 with checkpoints 1.6
LATENTSYNC_PY = settings.latentsync_python
OWN_ROOTS = (str(ROOT), str(PACKAGE.parents[1]), str(NARRATE.parent))  # GPU processes from these are Yatta's own
LATENTSYNC_MIN_FREE_MIB = 20000  # inference peaks near 18 GB
BASE_SECONDS = 30
MAX_SECONDS = 300  # 5 minutes (Henry, 2026-10-26); a Realistic render then takes about an hour
OWN_FILES = {"bc.jpg", "transforms_val.json", "transforms_train.json", "track_params.pt", "speech.wav", "speech.npy"}
SLIM = core.DATA / "cache" / "slim"


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
    """Produce speech audio for a job. voice = {"provider": "elevenlabs"|"mms"|"upload", "id": ...}."""
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


def extract_features(feature, wav, out_npy, log):
    if feature == "deepspeech":
        run([DEEPSPEECH_PY, ROOT / "scripts/extract_deepspeech.py", "--wav", wav, "--output", out_npy], log)
    elif feature in core.FEATURES:
        run([SPEECHFEAT_PY, ROOT / "scripts/extract_speech_features.py", "--model", feature, "--wav", wav,
             "--output", out_npy], log)
    else:
        raise StepError(f"unknown speech features {feature}")
    shape = core.npy_shape(out_npy)
    expected = core.FEATURES[feature][1]
    if len(shape) != 3 or shape[2] != expected:
        raise StepError(f"features {shape} do not match {feature} ({expected} channels)")
    return shape[0]


# ---- per-job dataset and model ----------------------------------------------------------------------

def make_background(spec, reference_bc, out_jpg, log):
    """spec = {"type": "original"} | {"type": "color", "value": "#rrggbb"} | {"type": "image", "path": ...}."""
    width, height = image_size(reference_bc)
    kind = spec.get("type", "original")
    if kind == "original":
        shutil.copyfile(reference_bc, out_jpg)
    elif kind == "color":
        value = spec.get("value", "#ffffff").lstrip("#")
        if len(value) != 6 or any(c not in "0123456789abcdefABCDEF" for c in value):
            raise StepError(f"bad colour {spec.get('value')}")
        ffmpeg(["-f", "lavfi", "-i", f"color=c=0x{value}:s={width}x{height}", "-frames:v", "1", "-q:v", "2", out_jpg], log)
    elif kind == "image":
        ffmpeg(["-i", spec["path"], "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},setsar=1", "-frames:v", "1", "-q:v", "2", out_jpg], log)
    else:
        raise StepError(f"unknown background type {kind}")


def slim_track_params(identity, log):
    """Cached copy of the identity's track_params.pt without per-frame mesh vertices."""
    source = (Path(identity) / "track_params.pt").resolve()
    stat = source.stat()
    key = hashlib.sha1(f"{source}:{stat.st_size}:{stat.st_mtime_ns}".encode()).hexdigest()[:16]
    out = SLIM / key / "track_params.pt"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp")
        # The reader averages "vertices" over frames for an initial point cloud (unused when rendering a trained
        # model), so keep that average as a single frame: the reader gets the same mean from 1/8619 of the data.
        run([PY, "-c", "import sys, torch; d = torch.load(sys.argv[1], weights_only=False); "
             "d['vertices'] = d['vertices'].mean(dim=0, keepdim=True); torch.save(d, sys.argv[2])", source, tmp], log)
        os.replace(tmp, out)
        (out.parent / "source.txt").write_text(f"{source}\n")
    return out


def make_dataset(identity, job_data, frames, log):
    """Mirror ``identity`` into ``job_data`` with symlinks; write the looped validation poses and slim stand-ins."""
    identity = Path(identity)
    job_data.mkdir(parents=True, exist_ok=True)
    for entry in identity.iterdir():
        if entry.name in OWN_FILES:
            continue
        link = job_data / entry.name
        if not link.exists() and not link.is_symlink():
            link.symlink_to(entry.resolve())
    transforms = json.loads((identity / "transforms_val.json").read_text())
    transforms["frames"] = core.extend_frames(transforms["frames"], frames)
    (job_data / "transforms_val.json").write_text(json.dumps(transforms))
    train = json.loads((identity / "transforms_train.json").read_text())
    train["frames"] = core.slim_train_frames(train["frames"])
    (job_data / "transforms_train.json").write_text(json.dumps(train))
    (job_data / "track_params.pt").symlink_to(slim_track_params(identity, log))


def make_model(trained_model, job_model):
    """Link the trained model's config and final point cloud; outputs then go under ``job_model``."""
    trained_model = Path(trained_model)
    job_model.mkdir(parents=True, exist_ok=True)
    for name in ("cfg_args", "point_cloud"):
        link = job_model / name
        if not link.exists() and not link.is_symlink():
            link.symlink_to((trained_model / name).resolve())


def render(job_dir, variant, log):
    """Render ``job_dir/data`` (speech basename ``speech``) with the variant's model; returns the MOV path."""
    model = job_dir / "render" / "model"
    make_model(variant["model"], model)
    iteration = variant.get("iteration", 10000)
    run([PY, ROOT / "scripts/reproduce.py", "render", "--data", job_dir / "data", "--config", variant["config"],
         "--model", model, "--iteration", str(iteration), "--batch", "8", "--audio", "speech",
         "--report", job_dir / "render.json"], log,
        env={"OMP_NUM_THREADS": "1", "PYTHONUNBUFFERED": "1", "GT_RENDER_LEAN": "1"})
    mov = model / f"custom/ours_{iteration}/renders/render_custom_{iteration}iter_renders.mov"
    if not mov.is_file():
        raise StepError(f"render produced no video; see {log}")
    return mov


# ---- LatentSync (real footage, regenerated mouth) -----------------------------------------------------

def latentsync_available():
    return (LATENTSYNC / "checkpoints/latentsync_unet.pt").is_file() and LATENTSYNC_PY.is_file()


def identity_video(identity):
    """The avatar's normalized training video (henry.mp4 in experiments, video.mp4 in Yatta)."""
    videos = sorted(p for p in Path(identity).glob("*.mp4") if p.is_file())
    if not videos:
        raise StepError(f"no source video in {identity}")
    return videos[0]


def latentsync_base(identity, log):
    """Cached base clip for LatentSync: the last BASE_SECONDS of the avatar's video (its held-out part), silent."""
    source = identity_video(identity).resolve()
    stat = source.stat()
    key = hashlib.sha1(f"{source}:{stat.st_size}:{stat.st_mtime_ns}:{BASE_SECONDS}".encode()).hexdigest()[:16]
    out = core.DATA / "cache" / "latentsync" / f"{key}.mp4"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.stem + ".tmp.mp4")
        ffmpeg(["-sseof", f"-{BASE_SECONDS}", "-i", source, "-an", "-c:v", "libx264", "-crf", "12",
                "-pix_fmt", "yuv420p", tmp], log)
        os.replace(tmp, out)
    return out


def render_latentsync(job_dir, base, wav, log, steps=20):
    """LatentSync 1.6 with experiment 007's settings; returns the output MP4 (with the speech as audio)."""
    out = job_dir / "latentsync.mp4"
    run([LATENTSYNC_PY, "-m", "scripts.inference", "--unet_config_path", "configs/unet/stage2_512.yaml",
         "--inference_ckpt_path", "checkpoints/latentsync_unet.pt", "--inference_steps", str(steps),
         "--guidance_scale", "1.5", "--enable_deepcache", "--seed", "1247", "--temp_dir", job_dir / "latentsync-tmp",
         "--video_path", base, "--audio_path", wav, "--video_out_path", out], log, cwd=LATENTSYNC,
        env={"PYTHONUNBUFFERED": "1"})
    shutil.rmtree(job_dir / "latentsync-tmp", ignore_errors=True)
    if not out.is_file():
        raise StepError(f"LatentSync produced no video; see {log}")
    return out


def encode(mov, out_mp4, poster, log):
    ffmpeg(["-i", mov, "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", out_mp4], log)
    ffmpeg(["-ss", "0.6", "-i", out_mp4, "-frames:v", "1", "-q:v", "3", poster], log)


def poster_for(video, out_jpg, log, at=1.0):
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(["-ss", str(at), "-i", video, "-frames:v", "1", "-q:v", "3", out_jpg], log)


def elevenlabs_available():
    """True if an ElevenLabs key is configured (env var, ~/.config/elevenlabs/api_key or ~/.elevenlabs/env)."""
    import importlib.util
    from yatta import elevenlabs
    return bool(elevenlabs.read_api_key())


# ---- GPU --------------------------------------------------------------------------------------------

LAST_FOREIGN = 0.0  # time.time() when another project was last seen actually working on the GPU
BUSY_UTILIZATION = 20  # percent; below this, other projects' processes are idle residents (e.g. a model server)
RENDER_MIN_FREE_MIB = 12000
TRAIN_MIN_FREE_MIB = 24000


def gpu_status():
    """Utilization, memory and compute processes, each marked as this project's or another one's."""
    status = {"available": False, "utilization": None, "memory_used": None, "memory_total": None, "processes": []}
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=20)
        name, util, used, total = [x.strip() for x in out.stdout.strip().splitlines()[0].split(",")]
        status.update(available=True, name=name, utilization=int(util), memory_used=int(used), memory_total=int(total))
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return status
    rows = []
    for line in out.stdout.strip().splitlines():
        pid, memory = [x.strip() for x in line.split(",")]
        try:
            cmdline = Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(errors="replace").strip()
            cwd = os.readlink(f"/proc/{pid}/cwd")
        except OSError:
            cmdline, cwd = "", ""
        rows.append((int(pid), cmdline, cwd, int(memory)))
    foreign = {p[0] for p in core.foreign_processes([(p[0], p[1], p[2]) for p in rows], OWN_ROOTS)}
    status["processes"] = [{"pid": pid, "memory": memory, "own": pid not in foreign, "label": describe(cmdline)}
                           for pid, cmdline, cwd, memory in rows]
    status["foreign_busy"] = bool(foreign) and status["utilization"] >= BUSY_UTILIZATION
    if status["foreign_busy"]:
        global LAST_FOREIGN
        LAST_FOREIGN = time.time()
    return status


def describe(cmdline):
    """Short human label for a GPU process, e.g. 'maestro · train.py'."""
    parts = cmdline.split()
    script = next((p for p in parts if p.endswith(".py")), parts[0] if parts else "process")
    project = next((seg for seg in Path(script).parts if seg not in ("/", "home", "git") and not seg.startswith(".")
                    and seg != Path(script).name and seg != os.environ.get("USER", "")), "")
    return f"{project} · {Path(script).name}" if project else Path(script).name


def gpu_foreign_busy(min_free_mib=RENDER_MIN_FREE_MIB, samples=3):
    """Other projects' GPU processes that should make Yatta wait, or [] if it may start.

    Henry does not want Yatta competing with his other GPU jobs, but a resident process that holds a
    little memory at 0 % utilization (an idle model server) is not a job: Yatta starts when
    utilization stays under BUSY_UTILIZATION over a few samples and enough memory is free.
    """
    status = gpu_status()
    foreign = [p for p in status["processes"] if not p["own"]]
    if not foreign or not status["available"]:
        return foreign
    utilization = [status["utilization"]]
    for _ in range(samples - 1):
        time.sleep(1)
        utilization.append(gpu_status()["utilization"])
    free = status["memory_total"] - status["memory_used"]
    if max(utilization) < BUSY_UTILIZATION and free >= min_free_mib:
        return []
    global LAST_FOREIGN
    LAST_FOREIGN = time.time()
    return foreign


if __name__ == "__main__":
    # `python -m yatta.engines gpu-foreign` prints other projects' GPU processes that are busy enough to wait for
    # (used by train_avatar.sh; training needs TRAIN_MIN_FREE_MIB free).
    if sys.argv[1:] == ["gpu-foreign"]:
        for process in gpu_foreign_busy(TRAIN_MIN_FREE_MIB, samples=5):
            print(process["pid"], process["label"])
    else:
        sys.exit("usage: python -m yatta.engines gpu-foreign")
