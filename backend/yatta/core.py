"""Pure helpers (standard library only): pose looping, audio levels, log parsing and the avatar registry."""

import json
import math
import os
import re
from pathlib import Path

from yatta.config import settings

DATA = settings.data
# Avatars from research runs are listed in DATA/registry.json with paths relative to the GaussianTalker repository.
ROOT = settings.gaussian_talker
FPS = 25
FEATURES = {
    # name: (label, channels, note). "clip" marks Quick avatars, which have a face clip but no GaussianTalker
    # model; "latentsync" is the same in renders made before engines were pluggable.
    "clip": ("Video clip", 0, "No trained model"),
    "latentsync": ("Video clip", 0, "No trained model"),
    "deepspeech": ("DeepSpeech", 29, "Upstream default; English-only, 2017"),
    "esperanto": ("wav2vec2 · Esperanto", 44, "Best lip sync in experiment 006"),
    "hubert": ("HuBERT large", 1024, "Close second in experiment 006"),
    "whisper": ("Whisper small", 768, "Weakest lip sync in experiment 006"),
}
PROGRESS = re.compile(r"Training progress:\s*(\d+)%\|[^|]*\|\s*(\d+)/(\d+)\s*\[([0-9:]+)<([0-9:?]+)")
LOG_LINE = re.compile(r"^(\d{4}-\d\d-\d\dT[0-9:.+-]+)\s+(.*)$")


def pingpong_indices(available, needed):
    """Indices 0..n-1, n-2..1, 0.. of length ``needed``: loop a pose track without jump cuts."""
    if available < 1:
        raise ValueError("no frames to loop")
    if available == 1:
        return [0] * needed
    period = 2 * (available - 1)
    out = []
    for i in range(needed):
        k = i % period
        out.append(k if k < available else period - k)
    return out


def extend_frames(frames, needed):
    return [frames[i] for i in pingpong_indices(len(frames), needed)]


def slim_train_frames(frames):
    """First and highest-id training frames: enough for upstream's camera extent and timeline at render time."""
    if not frames:
        raise ValueError("no training frames")
    last = max(frames, key=lambda f: f["img_id"])
    return [frames[0]] if last is frames[0] else [frames[0], last]


def parse_mean_volume(text):
    """Mean volume in dB from ffmpeg volumedetect output, or None."""
    match = re.search(r"mean_volume:\s*(-?[0-9.]+|-inf) dB", text)
    if not match or match.group(1) == "-inf":
        return None
    return float(match.group(1))


def gain_db(target_db, source_db, limit=30.0):
    """Gain that brings source to the target level, clamped to +-limit dB."""
    if target_db is None or source_db is None:
        return 0.0
    return round(max(-limit, min(limit, target_db - source_db)), 1)


def slugify(text, fallback="item"):
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].strip("-")
    return slug or fallback


def estimate_seconds(text, words_per_second=2.6):
    words = len(text.split())
    return round(words / words_per_second, 1) if words else 0.0


def foreign_processes(processes, roots=(str(ROOT),)):
    """Filter (pid, cmdline, cwd) GPU processes to those that belong to none of ``roots`` (this project's folders)."""
    roots = (roots,) if isinstance(roots, (str, Path)) else roots
    def own(p):
        return any(str(r) in (p[1] or "") or (p[2] or "").startswith(str(r)) for r in roots)
    return [p for p in processes if not own(p)]


def config_iterations(config_text):
    """(coarse_iterations, iterations) from a training config's source text."""
    coarse = re.search(r"coarse_iterations\s*=\s*(\d+)", config_text)
    fine = re.search(r"(?<!coarse_)\biterations\s*=\s*(\d+)", config_text)
    return int(coarse.group(1)) if coarse else 7999, int(fine.group(1)) if fine else 10000


def training_progress(log_text, coarse_total=7999, fine_total=10000):
    """Latest tqdm progress in an upstream train.log: stage, iteration, total, overall percent, elapsed, remaining."""
    last = None
    for match in PROGRESS.finditer(log_text.replace("\r", "\n")):
        last = match
    if not last:
        return None
    percent, it, total, elapsed, remaining = last.groups()
    fine = int(total) == fine_total and fine_total != coarse_total
    done = (coarse_total if fine else 0) + int(it)
    return {"stage": "fine" if fine else "coarse", "iteration": int(it), "total": int(total),
            "percent": int(percent), "overall": round(100 * done / (coarse_total + fine_total)),
            "elapsed": elapsed, "remaining": remaining}


def log_events(log_text):
    """(timestamp, message) pairs from a pipeline log written with ``date -Is``."""
    events = []
    for line in log_text.splitlines():
        match = LOG_LINE.match(line.strip())
        if match:
            events.append((match.group(1), match.group(2)))
    return events


def resolve(path, root=ROOT):
    path = Path(path)
    return path if path.is_absolute() else root / path


def final_iteration(model):
    """Highest saved iteration in <model>/point_cloud/iteration_N with a point cloud, or None."""
    found = [int(p.parent.name.split("_")[1]) for p in Path(model).glob("point_cloud/iteration_*/point_cloud.ply")
             if p.parent.name.split("_")[1].isdigit()]
    return max(found) if found else None


def load_registry(path, root=ROOT):
    """Built-in avatars (experiment runs) with resolved paths; variants whose model is missing are dropped."""
    avatars = []
    for avatar in json.loads(Path(path).read_text())["avatars"]:
        variants = []
        for variant in avatar["variants"]:
            model = resolve(variant["model"], root)
            iteration = final_iteration(model)
            if iteration is None:
                continue
            variants.append({**variant, "iteration": iteration, "model": str(model), "data": str(resolve(variant["data"], root)),
                             "config": str(resolve(variant["config"], root)),
                             "preview": str(resolve(variant["preview"], root)) if variant.get("preview") else None})
        if variants:
            avatars.append({**avatar, "variants": variants, "source": "experiment"})
    return avatars


def studio_variants(avatar_dir, features):
    """Ready variants of a studio-trained avatar, judged from disk: runs/<feature>/done and a final model."""
    avatar_dir = Path(avatar_dir)
    variants = []
    for feature in features:
        run = avatar_dir / "runs" / feature
        iteration = final_iteration(run / "model")
        if not (run / "done").is_file() or iteration is None:
            continue
        metrics = {}
        if (run / "eval.json").is_file():
            report = json.loads((run / "eval.json").read_text())
            face = report.get("face_region", {})
            metrics = {"face_psnr": round(face.get("psnr", {}).get("mean", 0), 2),
                       "face_lpips": round(face.get("lpips", {}).get("mean", 0), 3)}
        data = avatar_dir / "data" / ("identity" if feature == "deepspeech" else feature)
        variants.append({"feature": feature, "run": feature, "iteration": iteration, "model": str(run / "model"), "data": str(data),
                         "config": str(run / "config.py"),
                         "preview": str(run / "preview.mp4") if (run / "preview.mp4").is_file() else None,
                         "metrics": metrics})
    return variants


def load_studio_avatars(data=DATA):
    """Avatars trained through the studio (<data>/avatars/<id>/avatar.json) that have a ready variant."""
    avatars = []
    for manifest in sorted((Path(data) / "avatars").glob("*/avatar.json")):
        avatar = json.loads(manifest.read_text())
        variants = studio_variants(manifest.parent, avatar.get("features", []))
        if variants:
            avatars.append({**avatar, "variants": variants, "source": "studio"})
    return avatars


def load_quick_avatars(data=DATA):
    """Quick avatars (<data>/quick/<id>/quick.json): a face clip only, for engines that need a clip or a photo."""
    avatars = []
    for manifest in sorted((Path(data) / "quick").glob("*/quick.json")):
        quick = json.loads(manifest.read_text())
        clip = manifest.parent / "clip.mp4"
        if quick.get("state") != "ready" or not clip.is_file():
            continue
        avatars.append({"id": quick["id"], "name": quick["name"], "edition": "", "summary": quick.get("summary", ""),
                        "default_feature": "clip", "source": "quick",
                        "variants": [{"feature": "clip", "base": str(clip), "preview": str(clip), "metrics": {}}]})
    return avatars


def split_at_pauses(silences, total, max_len=14.5, min_len=5.2):
    """Cut ``total`` seconds of speech into the fewest pieces of at most ``max_len`` s, of about equal length.

    Each cut goes to the middle of the pause closest to the balanced cut point, among pauses that keep this piece
    and the rest at least ``min_len`` long and this piece at most ``max_len``; with no such pause it is a hard cut at
    the balanced point. ``silences`` is a list of (start, end) pauses. Returns [(start, end), ...] covering 0..total.
    """
    pieces, start = [], 0.0
    while total - start > max_len:
        remaining = total - start
        target = start + remaining / math.ceil(remaining / max_len)
        cuts = [(a + b) / 2 for a, b in silences]
        cuts = [c for c in cuts if start + min_len <= c <= start + max_len and total - c >= min_len]
        cut = round(min(cuts, key=lambda c: abs(c - target)) if cuts else target, 3)
        pieces.append((start, cut))
        start = cut
    pieces.append((start, round(total, 3)))
    return pieces


def split_words(words, total, max_len=13.0, min_len=5.2):
    """Pieces of speech cut between words: [(start, end, text), ...] from Whisper words [[start, end, word], ...].

    Cuts go in the gaps between consecutive words (``split_at_pauses`` with each gap as a pause); each word belongs
    to the piece holding its midpoint. Pieces without words are dropped.
    """
    gaps = [(words[i][1], words[i + 1][0]) for i in range(len(words) - 1)]
    pieces = []
    for start, end in split_at_pauses(gaps, total, max_len, min_len):
        text = " ".join(w[2] for w in words if start <= (w[0] + w[1]) / 2 < end or (end == total and (w[0] + w[1]) / 2 >= end))
        if text.strip():
            pieces.append((start, end, text.strip()))
    return pieces


def parse_silences(text):
    """(start, end) pairs from ffmpeg ``silencedetect`` output."""
    starts = [float(x) for x in re.findall(r"silence_start: (-?[0-9.]+)", text)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", text)]
    return list(zip(starts, ends))


def npy_shape(path):
    """Shape of a .npy array from its header, without numpy."""
    with open(path, "rb") as handle:
        if handle.read(6) != b"\x93NUMPY":
            raise ValueError(f"{path} is not a .npy file")
        major = handle.read(2)[0]
        size = int.from_bytes(handle.read(2 if major == 1 else 4), "little")
        header = handle.read(size).decode("latin1")
    match = re.search(r"'shape':\s*\(([^)]*)\)", header)
    return tuple(int(x) for x in match.group(1).split(",") if x.strip())


def find_variant(avatars, avatar_id, feature=None):
    """The avatar and its variant for ``feature``; without a feature, the default variant (or the first)."""
    for avatar in avatars:
        if avatar["id"] == avatar_id:
            variants = avatar["variants"]
            wanted = feature or avatar.get("default_feature")
            match = next((v for v in variants if v["feature"] == wanted), None)
            if match is None and not feature and variants:
                match = variants[0]
            return (avatar, match) if match else (None, None)
    return None, None
