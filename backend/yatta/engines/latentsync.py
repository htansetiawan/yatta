"""Realistic: LatentSync 1.6 keeps real footage of the avatar and regenerates only the mouth."""

import shutil

from yatta import steps
from yatta.config import settings
from yatta.engines.base import Engine, face_clip

ROOT = settings.latentsync  # bytedance/LatentSync a229c39 with checkpoints 1.6
PY = settings.latentsync_python


class LatentSync(Engine):
    id = "latentsync"
    name = "Realistic"
    model = "LatentSync 1.6"
    summary = "Your real footage, new mouth"
    badge = "Recommended"
    needs = "clip"
    min_free_mib = 20000  # inference peaks near 18 GB
    load_seconds = 60
    seconds_per_second = 13  # experiment 007 and Yatta renders on the RTX PRO 5000
    licence = "Apache-2.0"

    def available(self):
        return (ROOT / "checkpoints/latentsync_unet.pt").is_file() and PY.is_file()

    def render(self, job, steps_count=20):
        """Experiment 007's settings. If the speech outlasts the clip, LatentSync loops it back and forth."""
        base = face_clip(job.variant, job.log)
        out = job.dir / "latentsync.mp4"
        steps.run([PY, "-m", "scripts.inference", "--unet_config_path", "configs/unet/stage2_512.yaml",
                   "--inference_ckpt_path", "checkpoints/latentsync_unet.pt", "--inference_steps", str(steps_count),
                   "--guidance_scale", "1.5", "--enable_deepcache", "--seed", "1247", "--temp_dir", job.dir / "latentsync-tmp",
                   "--video_path", base, "--audio_path", job.speech, "--video_out_path", out], job.log, cwd=ROOT,
                  env={"PYTHONUNBUFFERED": "1"})
        shutil.rmtree(job.dir / "latentsync-tmp", ignore_errors=True)
        if not out.is_file():
            raise steps.StepError(f"LatentSync produced no video; see {job.log}")
        return out
