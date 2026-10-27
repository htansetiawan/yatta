"""Fast: a GaussianTalker 3D avatar trained on the person, re-animated from speech features.

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
from pathlib import Path

from yatta import core, steps
from yatta.config import settings
from yatta.engines.base import Engine

ROOT = settings.gaussian_talker
PY = settings.gt_python
DEEPSPEECH_PY = settings.deepspeech_python
SPEECHFEAT_PY = settings.speechfeat_python
OWN_FILES = {"bc.jpg", "transforms_val.json", "transforms_train.json", "track_params.pt", "speech.wav", "speech.npy"}
SLIM = core.DATA / "cache" / "slim"


class GaussianTalker(Engine):
    id = "gaussiantalker"
    name = "Fast"
    model = "GaussianTalker"
    summary = "3D avatar trained on you · custom backgrounds"
    needs = "trained"
    backgrounds = True
    speech_models = True
    background_note = ""
    load_seconds = 15
    seconds_per_second = 0.5
    licence = "Research only"

    def available(self):
        return PY.is_file()

    def speed(self):
        return "~20 s per video"

    def prepare(self, job):
        job.status("features", "Reading the speech")
        data = job.dir / "data"
        frames = extract_features(job.variant["feature"], job.speech, data / "speech.npy", job.log)
        make_dataset(job.variant["data"], data, frames, job.log)
        make_background(job.background, Path(job.variant["data"]) / "bc.jpg", data / "bc.jpg", job.log)
        job.frames = frames

    def render(self, job):
        job.status("rendering", f"Rendering {job.frames} frames", frames=job.frames)
        return render(job.dir, job.variant, job.log)

    def cleanup(self, job, output):
        shutil.rmtree(job.dir / "render" / "model" / "custom", ignore_errors=True)


def extract_features(feature, wav, out_npy, log):
    if feature == "deepspeech":
        steps.run([DEEPSPEECH_PY, ROOT / "scripts/extract_deepspeech.py", "--wav", wav, "--output", out_npy], log)
    elif feature in core.FEATURES and core.FEATURES[feature][1]:
        steps.run([SPEECHFEAT_PY, ROOT / "scripts/extract_speech_features.py", "--model", feature, "--wav", wav,
                   "--output", out_npy], log)
    else:
        raise steps.StepError(f"unknown speech features {feature}")
    shape = core.npy_shape(out_npy)
    expected = core.FEATURES[feature][1]
    if len(shape) != 3 or shape[2] != expected:
        raise steps.StepError(f"features {shape} do not match {feature} ({expected} channels)")
    return shape[0]


def make_background(spec, reference_bc, out_jpg, log):
    """spec = {"type": "original"} | {"type": "color", "value": "#rrggbb"} | {"type": "image", "path": ...}."""
    width, height = steps.image_size(reference_bc)
    kind = spec.get("type", "original")
    if kind == "original":
        shutil.copyfile(reference_bc, out_jpg)
    elif kind == "color":
        value = spec.get("value", "#ffffff").lstrip("#")
        if len(value) != 6 or any(c not in "0123456789abcdefABCDEF" for c in value):
            raise steps.StepError(f"bad colour {spec.get('value')}")
        steps.ffmpeg(["-f", "lavfi", "-i", f"color=c=0x{value}:s={width}x{height}", "-frames:v", "1", "-q:v", "2", out_jpg], log)
    elif kind == "image":
        steps.ffmpeg(["-i", spec["path"], "-vf", f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                      f"crop={width}:{height},setsar=1", "-frames:v", "1", "-q:v", "2", out_jpg], log)
    else:
        raise steps.StepError(f"unknown background type {kind}")


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
        steps.run([PY, "-c", "import sys, torch; d = torch.load(sys.argv[1], weights_only=False); "
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
    steps.run([PY, ROOT / "scripts/reproduce.py", "render", "--data", job_dir / "data", "--config", variant["config"],
               "--model", model, "--iteration", str(iteration), "--batch", "8", "--audio", "speech",
               "--report", job_dir / "render.json"], log,
              env={"OMP_NUM_THREADS": "1", "PYTHONUNBUFFERED": "1", "GT_RENDER_LEAN": "1"})
    mov = model / f"custom/ours_{iteration}/renders/render_custom_{iteration}iter_renders.mov"
    if not mov.is_file():
        raise steps.StepError(f"render produced no video; see {log}")
    return mov
