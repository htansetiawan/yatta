"""Services: render queue, avatar training, cloned voices, Quick avatars and uploads.

State lives in JSON files under ``settings.data``; the API layer (``yatta.api``) calls into this module.
"""

import datetime
import json
import os
import shutil
import subprocess
import threading
import time
import uuid
from pathlib import Path

import sys

from yatta import core, engines
from yatta.config import PACKAGE, settings

DATA = core.DATA
TERMINAL = {"done", "failed", "cancelled"}
GPU_POLL = settings.gpu_poll_seconds  # Henry: check waiting jobs every 30 minutes


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def new_id(prefix):
    return f"{prefix}-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"


def write_json(path, value):
    tmp = Path(str(path) + ".tmp")
    tmp.write_text(json.dumps(value, indent=2) + "\n")
    os.replace(tmp, path)


def read_json(path, default=None):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return default


# ---- avatars ---------------------------------------------------------------------------------------

def all_avatars():
    registry = DATA / "registry.json"  # research avatars (not in the repository); see docs/registry.example.json
    return ((core.load_registry(registry) if registry.is_file() else []) + core.load_studio_avatars(DATA)
            + core.load_quick_avatars(DATA))


# ---- renders ---------------------------------------------------------------------------------------

class RenderQueue:
    """Renders one job at a time in a background thread; GPU steps wait only for other projects' jobs."""

    def __init__(self, root=DATA / "renders", worker=True):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.wake = threading.Event()
        self.thread = None
        self.worker = worker
        if worker:  # a restart interrupts work in progress; steps are redone from the start
            for job in self.list():
                if job["state"] not in TERMINAL:
                    self.update(job["id"], state="queued", detail="requeued after restart")

    def path(self, job_id):
        if "/" in job_id or job_id.startswith("."):
            raise KeyError(job_id)
        return self.root / job_id

    def get(self, job_id):
        job = read_json(self.path(job_id) / "job.json")
        if job is None:
            raise KeyError(job_id)
        return job

    def list(self):
        jobs = [read_json(p) for p in self.root.glob("*/job.json")]
        return sorted([j for j in jobs if j], key=lambda j: j["created"], reverse=True)

    def update(self, job_id, **changes):
        with self.lock:
            job = self.get(job_id)
            job.update(changes, updated=now())
            write_json(self.path(job_id) / "job.json", job)
            return job

    def submit(self, request):
        avatar, variant = core.find_variant(all_avatars(), request["avatar"], request["feature"])
        if not variant:
            raise ValueError("unknown avatar or speech model")
        job_id = new_id("r")
        job_dir = self.path(job_id)
        job_dir.mkdir(parents=True)
        job = {"id": job_id, "created": now(), "updated": now(), "state": "queued", "detail": "",
               "title": request.get("title") or (request.get("text") or "Uploaded audio")[:60],
               "text": request.get("text", ""), "voice": request["voice"], "audio_upload": request.get("audio_upload"),
               "background": request.get("background", {"type": "original"}),
               "avatar": avatar["id"], "avatar_name": f"{avatar['name']} {avatar.get('edition', '')}".strip(),
               "feature": variant["feature"], "published": None, "public": None,
               "engine": "latentsync" if request.get("engine") == "latentsync" else "gaussiantalker"}
        if job["engine"] == "latentsync" and not engines.latentsync_available():
            raise ValueError("LatentSync is not installed on this server")
        if variant.get("base") and job["engine"] != "latentsync":
            raise ValueError("Quick avatars work on the Realistic engine only")
        write_json(job_dir / "job.json", job)
        self.wake.set()
        return job

    def delete(self, job_id):
        job = self.get(job_id)
        if job["state"] not in TERMINAL:
            raise ValueError("job is still running")
        if job.get("public"):
            raise ValueError("unpublish it from the public site first")
        shutil.rmtree(self.path(job_id))

    def start(self):
        if self.worker and not self.thread:
            threading.Thread(target=self.prewarm, daemon=True, name="prewarm").start()
            self.thread = threading.Thread(target=self.loop, daemon=True, name="render-queue")
            self.thread.start()

    def prewarm(self):
        """Build each avatar's slim track_params once at startup, so the first render is fast too."""
        log = DATA / "cache" / "prewarm.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        for avatar in all_avatars():
            for variant in avatar["variants"]:
                if not variant.get("data"):  # Quick avatars have no GaussianTalker dataset
                    continue
                try:
                    engines.slim_track_params(variant["data"], log)
                except (OSError, engines.StepError) as error:
                    with open(log, "a") as out:
                        out.write(f"{avatar['id']}/{variant['feature']}: {error}\n")

    def loop(self):
        while True:
            queued = sorted((j for j in self.list() if j["state"] == "queued"), key=lambda j: j["created"])
            if not queued:
                self.wake.wait(timeout=60)
                self.wake.clear()
                continue
            self.process(queued[0]["id"])

    def process(self, job_id):
        job_dir = self.path(job_id)
        log = job_dir / "job.log"
        job = self.get(job_id)
        try:
            avatar, variant = core.find_variant(all_avatars(), job["avatar"], job["feature"])
            if not variant:
                raise engines.StepError("the avatar or speech model is no longer available")
            data = job_dir / "data"
            if data.exists():  # leftovers of an interrupted attempt
                shutil.rmtree(data)
            shutil.rmtree(job_dir / "render", ignore_errors=True)
            data.mkdir()
            self.update(job_id, state="voicing", detail="Generating speech")
            if job["voice"].get("provider") == "clone":  # F5-TTS runs on the GPU
                self.wait_for_gpu(job_id, 6000)
            raw = job_dir / "speech_raw.wav"
            engines.synthesize(job["voice"], job["text"], job.get("audio_upload"), raw, log)
            # Quick avatars have no training audio to match (and LatentSync is not level-sensitive).
            reference = Path(variant["data"]) / "aud.wav" if variant.get("data") else None
            gain, seconds = engines.level_audio(raw, reference, data / "speech.wav", log)
            if job.get("engine") == "latentsync":
                self.process_latentsync(job_id, job_dir, variant, data / "speech.wav", seconds, log)
                return
            self.update(job_id, state="features", detail="Reading the speech", seconds=round(seconds, 2), gain_db=gain)
            frames = engines.extract_features(variant["feature"], data / "speech.wav", data / "speech.npy", log)
            engines.make_dataset(variant["data"], data, frames, log)
            engines.make_background(job["background"], Path(variant["data"]) / "bc.jpg", data / "bc.jpg", log)
            while True:
                busy = engines.gpu_foreign_busy()
                if not busy:
                    # If another project used the GPU in the last 10 minutes it may be running back-to-back short
                    # processes: confirm after 30 s so a render does not start in a gap. Otherwise start at once.
                    if time.time() - engines.LAST_FOREIGN > 600:
                        break
                    time.sleep(30)
                    busy = engines.gpu_foreign_busy()
                    if not busy:
                        break
                self.update(job_id, state="waiting_gpu", detail=f"GPU busy with {busy[0]['label']} (or under "
                            f"{engines.RENDER_MIN_FREE_MIB // 1000} GB free); checking every {GPU_POLL // 60} min",
                            waiting_since=self.get(job_id).get("waiting_since") or now())
                self.wake.wait(timeout=GPU_POLL)
                self.wake.clear()
            self.update(job_id, state="rendering", detail=f"Rendering {frames} frames", frames=frames)
            started = time.time()
            mov = engines.render(job_dir, variant, log)
            self.update(job_id, state="encoding", detail="Encoding video", render_seconds=round(time.time() - started, 1))
            engines.encode(mov, job_dir / "video.mp4", job_dir / "poster.jpg", log)
            shutil.rmtree(job_dir / "render" / "model" / "custom", ignore_errors=True)
            self.update(job_id, state="done", detail="", duration=engines.duration(job_dir / "video.mp4"))
        except Exception as error:  # noqa: BLE001 - any failure ends the job with a readable message
            self.update(job_id, state="failed", detail=str(error)[:500])

    def wait_for_gpu(self, job_id, min_free_mib):
        while True:
            busy = engines.gpu_foreign_busy(min_free_mib)
            if not busy:
                return
            self.update(job_id, state="waiting_gpu", detail=f"GPU busy with {busy[0]['label']} (or under "
                        f"{min_free_mib // 1000} GB free); checking every {GPU_POLL // 60} min",
                        waiting_since=self.get(job_id).get("waiting_since") or now())
            self.wake.wait(timeout=GPU_POLL)
            self.wake.clear()

    def process_latentsync(self, job_id, job_dir, variant, wav, seconds, log):
        """Realistic engine: LatentSync regenerates the mouth on a real clip of the avatar's own footage."""
        base = variant.get("base") or engines.latentsync_base(variant["data"], log)
        self.wait_for_gpu(job_id, engines.LATENTSYNC_MIN_FREE_MIB)
        self.update(job_id, state="rendering", detail=f"LatentSync: about {round(seconds * 13 / 60) or 1} min for "
                    f"{seconds:.0f} s of speech", seconds=round(seconds, 2))
        started = time.time()
        mp4 = engines.render_latentsync(job_dir, base, wav, log)
        self.update(job_id, state="encoding", detail="Encoding video", render_seconds=round(time.time() - started, 1))
        engines.encode(mp4, job_dir / "video.mp4", job_dir / "poster.jpg", log)
        mp4.unlink(missing_ok=True)
        self.update(job_id, state="done", detail="", duration=engines.duration(job_dir / "video.mp4"))

    def check_now(self):
        self.wake.set()


# ---- cloned voices (narrate / F5-TTS) ----------------------------------------------------------

SAMPLE_LINE = "Hi! This is my cloned voice in Yatta. How does it sound?"


def voices_root():
    root = DATA / "voices"
    root.mkdir(parents=True, exist_ok=True)
    return root


def list_clones():
    profiles = [read_json(p) for p in sorted(voices_root().glob("*/voice.json"))]
    return sorted([p for p in profiles if p], key=lambda p: p["created"], reverse=True)


def create_clone(name, upload_id, consent, clip=None, text=None):
    """Store a reference recording and prepare the voice in the background (transcript + sample line)."""
    if not consent:
        raise ValueError("confirm that this is your voice or that the speaker agreed")
    upload = get_upload(upload_id)
    if upload["kind"] != "audio":
        raise ValueError("upload an audio recording")
    voice_id = core.slugify(name, "voice") + "-" + uuid.uuid4().hex[:4]
    folder = voices_root() / voice_id
    folder.mkdir(parents=True)
    reference = folder / ("reference" + Path(upload["path"]).suffix)
    shutil.copyfile(upload["path"], reference)
    profile = {"id": voice_id, "name": name, "reference": str(reference), "clip": clip or None,
               "text": (text or "").strip(), "consent": consent, "created": now(), "state": "preparing"}
    write_json(folder / "voice.json", profile)
    threading.Thread(target=prepare_clone, args=(voice_id,), daemon=True).start()
    return profile


def prepare_clone(voice_id):
    folder = voices_root() / voice_id
    profile = read_json(folder / "voice.json")
    try:
        manifest = engines.narrate(profile, SAMPLE_LINE, folder / "sample.wav", folder / "prepare.log", folder / "narrate")
        profile.update(text=profile.get("text") or manifest.get("reference_text", ""), state="ready",
                       sample_seconds=engines.duration(folder / "sample.wav"))
    except Exception as error:  # noqa: BLE001
        profile.update(state="failed", detail=str(error)[:300])
    write_json(folder / "voice.json", profile)


def delete_clone(voice_id):
    folder = voices_root() / voice_id
    if "/" in voice_id or not (folder / "voice.json").is_file():
        raise KeyError(voice_id)
    shutil.rmtree(folder)


# ---- quick avatars (Realistic engine only) -----------------------------------------------------

def create_quick(name, source, consent, start=None, end=None, summary=""):
    """Register a face clip as a Quick avatar and crop it to a 512x512, 25 fps square in the background."""
    if not consent:
        raise ValueError("confirm that this is you or that the person agreed")
    quick_id = core.slugify(name, "quick") + "-" + uuid.uuid4().hex[:4]
    folder = DATA / "quick" / quick_id
    folder.mkdir(parents=True)
    quick = {"id": quick_id, "name": name, "source": str(source), "start": start, "end": end, "consent": consent,
             "summary": summary or "Quick avatar · Realistic engine only", "created": now(), "state": "preparing"}
    write_json(folder / "quick.json", quick)
    threading.Thread(target=prepare_quick, args=(quick_id,), daemon=True).start()
    return quick


def prepare_quick(quick_id):
    folder = DATA / "quick" / quick_id
    quick = read_json(folder / "quick.json")
    log = folder / "prepare.log"
    try:
        trimmed = folder / "source.mp4"
        cut = (["-ss", str(quick["start"])] if quick.get("start") else []) + \
              (["-to", str(quick["end"])] if quick.get("end") else [])
        engines.ffmpeg(cut + ["-i", quick["source"], "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p",
                               "-an", trimmed], log)
        engines.run([engines.PY, core.ROOT / "scripts/select_crop.py", "--source", trimmed, "--output",
                      folder / "crop.json", "--detect-scale", "2.0"], log)
        crop = json.loads((folder / "crop.json").read_text())
        engines.ffmpeg(["-i", trimmed, "-vf", crop["filter"], "-c:v", "libx264", "-crf", "14", "-pix_fmt", "yuv420p",
                         "-an", folder / "clip.mp4"], log)
        engines.ffmpeg(["-ss", "1", "-i", folder / "clip.mp4", "-frames:v", "1", "-q:v", "3", folder / "poster.jpg"], log)
        trimmed.unlink()
        quick.update(state="ready", crop=crop["filter"], seconds=engines.duration(folder / "clip.mp4"))
    except Exception as error:  # noqa: BLE001
        quick.update(state="failed", detail=str(error)[:300])
    write_json(folder / "quick.json", quick)


def list_quick():
    return sorted([read_json(p) for p in (DATA / "quick").glob("*/quick.json") if read_json(p)],
                  key=lambda q: q["created"], reverse=True)


# ---- uploads -------------------------------------------------------------------------------------

def get_upload(upload_id):
    if "/" in upload_id or upload_id.startswith("."):
        raise KeyError(upload_id)
    record = read_json(DATA / "uploads" / upload_id / "upload.json")
    if not record or record.get("partial"):
        raise KeyError(upload_id)
    return record


def list_backgrounds():
    records = [read_json(p) or {} for p in sorted((DATA / "uploads").glob("*/upload.json"))]
    return [r for r in records if r.get("kind") == "background" and not r.get("partial")]


# ---- training ------------------------------------------------------------------------------------

class Trainer:
    """Trained avatars: upload -> crop review -> systemd unit running yatta/training/train_avatar.sh."""

    def __init__(self, root=DATA / "avatars"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, avatar_id):
        if "/" in avatar_id or avatar_id.startswith("."):
            raise KeyError(avatar_id)
        return self.root / avatar_id

    def create(self, name, upload_ids, consent):
        if not consent:
            raise ValueError("consent is required")
        uploads = [get_upload(u) for u in upload_ids]
        if not uploads or any(u["kind"] != "video" for u in uploads):
            raise ValueError("upload at least one video")
        avatar_id = core.slugify(name, "avatar") + "-" + uuid.uuid4().hex[:4]
        folder = self.path(avatar_id)
        folder.mkdir(parents=True)
        avatar = {"id": avatar_id, "name": name, "edition": "", "created": now(), "consent": consent,
                  "summary": f"Studio upload, {len(uploads)} recording{'s' if len(uploads) > 1 else ''}",
                  "uploads": [u["id"] for u in uploads], "features": [], "state": "framing",
                  "default_feature": "esperanto"}
        write_json(folder / "avatar.json", avatar)
        threading.Thread(target=self.propose_crops, args=(avatar_id,), daemon=True).start()
        return avatar

    def get(self, avatar_id):
        avatar = read_json(self.path(avatar_id) / "avatar.json")
        if not avatar:
            raise KeyError(avatar_id)
        return avatar

    def save(self, avatar):
        write_json(self.path(avatar["id"]) / "avatar.json", avatar)

    def propose_crops(self, avatar_id):
        """Run select_crop.py on each upload and grab three upright sample frames for the crop editor."""
        folder = self.path(avatar_id)
        avatar = self.get(avatar_id)
        log = folder / "framing.log"
        crops = []
        try:
            for index, upload_id in enumerate(avatar["uploads"]):
                source = get_upload(upload_id)["path"]
                proposal = folder / f"crop_{index}.json"
                engines.run([engines.PY, core.ROOT / "scripts/select_crop.py", "--source", source,
                              "--output", proposal], log)
                crop = json.loads(proposal.read_text())
                seconds = engines.duration(source) or 0
                # Crop coordinates refer to the upright full-resolution frame; the editor gets 960 px tall copies.
                full = folder / f"frame_{index}_full.jpg"
                engines.ffmpeg(["-ss", f"{seconds * 0.5:.2f}", "-i", source, "-frames:v", "1", "-q:v", "3", full], log)
                width, height = engines.image_size(full)
                full.unlink()
                frames = []
                for k, at in enumerate((0.15, 0.5, 0.85)):
                    image = folder / f"frame_{index}_{k}.jpg"
                    engines.ffmpeg(["-ss", f"{seconds * at:.2f}", "-i", source, "-frames:v", "1", "-vf", "scale=-2:960",
                                     "-q:v", "3", image], log)
                    frames.append(image.name)
                crops.append({"upload": upload_id, "x": crop["x"], "y": crop["y"], "size": crop["size"],
                              "width": width, "height": height, "seconds": round(seconds, 1), "frames": frames})
            avatar = self.get(avatar_id)
            avatar.update(crops=crops, state="review")
        except Exception as error:  # noqa: BLE001
            avatar = self.get(avatar_id)
            avatar.update(state="failed", detail=f"framing failed: {error}"[:500])
        self.save(avatar)

    def approve(self, avatar_id, crops, features):
        avatar = self.get(avatar_id)
        if avatar["state"] != "review":
            raise ValueError("this avatar is not waiting for crop review")
        features = [f for f in features if f in core.FEATURES and f != "latentsync"]
        if not features:
            raise ValueError("choose at least one speech model")
        sources = []
        for proposal, crop in zip(avatar["crops"], crops):
            size = int(crop["size"])
            x = max(0, min(int(crop["x"]), proposal["width"] - size))
            y = max(0, min(int(crop["y"]), proposal["height"] - size))
            if size < 256 or size > min(proposal["width"], proposal["height"]):
                raise ValueError("crop size out of range")
            upload = get_upload(proposal["upload"])
            sources.append({"path": upload["path"], "sha256": upload["sha256"],
                            "video_filter": f"crop={size}:{size}:{x}:{y},scale=512:512:flags=lanczos,fps=25,setsar=1"})
        folder = self.path(avatar_id)
        write_json(folder / "sources.json", {"sources": sources})
        avatar.update(features=features, state="training", approved=now(), crops=[
            {**p, "x": c["x"], "y": c["y"], "size": c["size"]} for p, c in zip(avatar["crops"], crops)])
        self.save(avatar)
        self.launch(avatar_id)
        return avatar

    def unit(self, avatar_id):
        return "yatta-train-" + avatar_id

    def launch(self, avatar_id):
        folder = self.path(avatar_id)
        log = folder / "pipeline.log"
        if log.exists():
            log.rename(folder / f"pipeline.{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}.log")
        subprocess.run(["systemctl", "--user", "reset-failed", self.unit(avatar_id)], capture_output=True)
        passed = {k: v for k, v in os.environ.items()
                  if k.startswith(("YATTA_", "LATENTSYNC_")) or k in ("GAUSSIAN_TALKER_ROOT", "NARRATE_BIN")}
        passed.update(GAUSSIAN_TALKER_ROOT=str(settings.gaussian_talker), YATTA_PYTHON=sys.executable,
                      PYTHONPATH=str(PACKAGE.parent), YATTA_TRAINING_CONFIGS=str(settings.training_configs))
        extra = [f"--setenv={k}={v}" for k, v in sorted(passed.items())]
        subprocess.run(["systemd-run", "--user", f"--unit={self.unit(avatar_id)}", *extra, "-p", "MemoryMax=28G",
                        "-p", "MemorySwapMax=0", "-p", "LimitNOFILE=1048576", f"--working-directory={settings.gaussian_talker}",
                        "/bin/bash", "-c", f"exec {PACKAGE}/training/train_avatar.sh {folder} > {log} 2>&1"],
                       check=True, capture_output=True)

    def status(self, avatar_id):
        """Avatar record plus live progress from the pipeline log and the current training log."""
        avatar = self.get(avatar_id)
        folder = self.path(avatar_id)
        active = subprocess.run(["systemctl", "--user", "is-active", "--quiet", self.unit(avatar_id)]).returncode == 0
        events = core.log_events((folder / "pipeline.log").read_text(errors="replace")) if (folder / "pipeline.log").exists() else []
        progress = {}
        for feature in avatar.get("features", []):
            train_log = folder / "runs" / feature / "train.log"
            config = folder / "runs" / feature / "config.py"
            if train_log.exists():
                totals = core.config_iterations(config.read_text()) if config.exists() else (7999, 10000)
                with open(train_log, "rb") as handle:
                    handle.seek(max(0, train_log.stat().st_size - 20000))
                    progress[feature] = core.training_progress(handle.read().decode(errors="replace"), *totals)
        state = avatar["state"]
        if state == "training":
            if (folder / "done").exists():
                state = "ready"
            elif (folder / "failed").exists() or (not active and events):
                state = "failed"
        variants = core.studio_variants(folder, avatar.get("features", []))
        return {**avatar, "state": state, "active": active, "events": events[-40:], "progress": progress,
                "failure": (folder / "failed").read_text().strip() if (folder / "failed").exists() else None,
                "ready_features": [v["feature"] for v in variants]}

    def list(self):
        out = []
        for manifest in sorted(self.root.glob("*/avatar.json")):
            try:
                out.append(self.status(manifest.parent.name))
            except KeyError:
                pass
        return sorted(out, key=lambda a: a["created"], reverse=True)

    def retry(self, avatar_id):
        avatar = self.get(avatar_id)
        if avatar["state"] != "training":
            raise ValueError("only a training avatar can be retried")
        if subprocess.run(["systemctl", "--user", "is-active", "--quiet", self.unit(avatar_id)]).returncode == 0:
            raise ValueError("training is still running")
        self.launch(avatar_id)
