"""Expressive: LongCat-Video-Avatar 1.5 (Meituan, MIT) generates the whole video from one photo and the speech.

Head, face and shoulders move with the speech, so it is not limited to the motion in the avatar's
footage; the price is identity drift and slow renders. It runs through ``scripts/run_longcat.py`` in the
research repository (experiment 007), with the int8 DiT and the 8-step distilled LoRA.
"""

from yatta import steps
from yatta.config import settings
from yatta.engines.base import Engine, face_photo

ROOT = settings.gaussian_talker
SRC = settings.longcat
PY = settings.longcat_python
RUNNER = ROOT / "scripts/run_longcat.py"
WEIGHTS = SRC / "weights"


class LongCat(Engine):
    id = "longcat"
    name = "Expressive"
    model = "LongCat-Video-Avatar 1.5"
    summary = "Generated from one photo · head and face move freely"
    badge = "Experimental"
    needs = "photo"
    background_note = "Keeps the room from the avatar's photo."
    min_free_mib = 40000
    load_seconds = 240
    seconds_per_second = 45
    licence = "MIT"

    def available(self):
        return (PY.is_file() and RUNNER.is_file()
                and (WEIGHTS / "LongCat-Video-Avatar-1.5/base_model_int8/quantized_model.safetensors.index.json").is_file()
                and (WEIGHTS / "LongCat-Video/text_encoder/model.safetensors.index.json").is_file())

    def render(self, job):
        photo = face_photo(job.variant, job.log)
        out = job.dir / "longcat.mp4"
        steps.run([PY, RUNNER, "--image", photo, "--audio", job.speech, "--out", out], job.log,
                  env={"PYTHONUNBUFFERED": "1", "LONGCAT_ROOT": str(SRC)})
        if not out.is_file():
            raise steps.StepError(f"LongCat produced no video; see {job.log}")
        return out

    def cleanup(self, job, output):
        output.unlink(missing_ok=True)
        output.with_suffix(".json").unlink(missing_ok=True)
