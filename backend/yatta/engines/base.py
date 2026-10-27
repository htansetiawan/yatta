"""What every video engine provides, and the avatar inputs (face clip, face photo) engines can ask for."""

import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from yatta import core, steps

BASE_SECONDS = 30  # face clip of a trained avatar: the last 30 s of its video (its held-out part)


@dataclass
class RenderJob:
    """One render as an engine sees it."""
    id: str
    dir: Path
    avatar: dict
    variant: dict
    speech: Path  # 16 kHz mono WAV, levelled and padded
    seconds: float
    background: dict
    log: Path
    status: Callable[..., None]  # status(state, detail, **fields) updates the job record
    text: str = ""  # the script, when the speech was synthesized from one (empty for uploaded or recorded audio)


class Engine:
    """A model that turns an avatar's look plus speech into a talking video.

    Subclasses set the class attributes (shown in the web app's engine picker through /api/v1/engines)
    and implement ``render``. List the subclass in ``yatta.engines.ENGINES`` to add it to the studio.
    """

    id = ""  # stable key stored in jobs
    name = ""  # picker title, e.g. "Realistic"
    model = ""  # the model behind it, e.g. "LatentSync 1.6"
    summary = ""  # one line under the title
    badge: Optional[str] = None  # e.g. "Recommended", "Experimental"
    needs = "clip"  # what the avatar provides: "clip" (video of the face), "photo" (a frame of it) or "trained"
    backgrounds = False  # can replace the background
    speech_models = False  # offers the avatar's speech-feature variants (GaussianTalker)
    background_note = "Keeps the room from the recording."
    min_free_mib = 12000  # free GPU memory to wait for
    load_seconds = 0.0  # rough fixed cost per render (loading models)
    seconds_per_second = 1.0  # rough render time per second of speech
    licence = ""

    def available(self):
        """Installed on this server (code, environment and weights present)."""
        return True

    def supports(self, avatar):
        if self.needs == "trained":
            return any(v.get("model") for v in avatar["variants"])
        return any(v.get("base") or v.get("data") for v in avatar["variants"])

    def estimate(self, seconds):
        return self.load_seconds + seconds * self.seconds_per_second

    def speed(self):
        """Human estimate for the picker, e.g. '~2 min per 10 s of speech'."""
        per_ten = self.estimate(10)
        return f"~{per_ten:.0f} s per 10 s of speech" if per_ten < 90 else f"~{per_ten / 60:.0f} min per 10 s of speech"

    def prepare(self, job: RenderJob):
        """CPU work before the render waits for the GPU (e.g. speech features)."""

    def render(self, job: RenderJob) -> Path:
        """Draw the video; return a file whose audio track is the job's speech. The queue encodes it."""
        raise NotImplementedError

    def cleanup(self, job: RenderJob, output: Path):
        """Remove intermediate files once the final MP4 exists."""
        if output.parent == job.dir:
            output.unlink(missing_ok=True)

    def info(self):
        return {"id": self.id, "name": self.name, "model": self.model, "summary": self.summary, "badge": self.badge,
                "needs": self.needs, "backgrounds": self.backgrounds, "speech_models": self.speech_models,
                "background_note": self.background_note, "speed": self.speed(), "licence": self.licence,
                "available": self.available()}


# ---- avatar inputs -----------------------------------------------------------------------------------

def identity_video(identity):
    """A trained avatar's normalized video (henry.mp4 in experiments, video.mp4 in Yatta)."""
    videos = sorted(p for p in Path(identity).glob("*.mp4") if p.is_file())
    if not videos:
        raise steps.StepError(f"no source video in {identity}")
    return videos[0]


def cache_key(source, extra):
    stat = Path(source).stat()
    return hashlib.sha1(f"{source}:{stat.st_size}:{stat.st_mtime_ns}:{extra}".encode()).hexdigest()[:16]


def face_clip(variant, log):
    """A silent video of the face: a Quick avatar's clip, or the last BASE_SECONDS of a trained avatar's video."""
    if variant.get("base"):
        return Path(variant["base"])
    source = identity_video(variant["data"]).resolve()
    out = core.DATA / "cache" / "latentsync" / f"{cache_key(source, BASE_SECONDS)}.mp4"  # shared with earlier renders
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.stem + ".tmp.mp4")
        steps.ffmpeg(["-sseof", f"-{BASE_SECONDS}", "-i", source, "-an", "-c:v", "libx264", "-crf", "12",
                      "-pix_fmt", "yuv420p", tmp], log)
        os.replace(tmp, out)
    return out


def face_photo(variant, log, at=0.5):
    """A still of the face (PNG) taken from ``face_clip``, for engines that start from one image."""
    clip = face_clip(variant, log).resolve()
    out = core.DATA / "cache" / "photos" / f"{cache_key(clip, at)}.png"
    if not out.is_file():
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name(out.stem + ".tmp.png")
        steps.ffmpeg(["-ss", str(at), "-i", clip, "-frames:v", "1", tmp], log)
        os.replace(tmp, out)
    return out
