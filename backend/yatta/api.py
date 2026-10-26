"""Yatta HTTP API, version 1 (mounted at /api/v1). Thin layer: validation and shaping over ``yatta.services``."""

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request, Response

from yatta import auth, core, engines, schemas, services
from yatta.config import PACKAGE, settings

router = APIRouter(prefix="/api/v1")
LIMITS = {"video": 6 * 1024**3, "audio": 100 * 1024**2, "background": 30 * 1024**2}
CHUNK_LIMIT = 64 * 1024**2  # Cloudflare rejects request bodies over 100 MB, so uploads arrive in chunks
state = {}  # "renders": RenderQueue, "trainer": Trainer, "throttle": auth.Throttle (set by the app factory)


def renders() -> services.RenderQueue:
    return state["renders"]


def trainer() -> services.Trainer:
    return state["trainer"]


def bad(message, status=400):
    raise HTTPException(status, str(message))


def not_found():
    raise HTTPException(404, "not found")


# ---- session ---------------------------------------------------------------------------------------

@router.get("/session", response_model=schemas.Session, tags=["session"])
def get_session(request: Request):
    return {"signed_in": request.state.signed_in}


@router.post("/session", response_model=schemas.Session, tags=["session"])
def create_session(body: schemas.SessionCreate, request: Request, response: Response):
    config = auth.load()
    if not config:
        bad("No access key yet. On the server run: python -m yatta.auth", 503)
    client = auth.client_id(request)
    if state["throttle"].blocked(client):
        bad("Too many attempts; try again in 15 minutes", 429)
    if not auth.verify_password(body.key, config["password"]):
        state["throttle"].fail(client)
        bad("Wrong key", 401)
    auth.set_session(response, request, config)
    return {"signed_in": True}


@router.delete("/session", response_model=schemas.Session, tags=["session"])
def delete_session(response: Response):
    response.delete_cookie(auth.COOKIE, path="/")
    return {"signed_in": False}


# ---- system ----------------------------------------------------------------------------------------

@router.get("/status", response_model=schemas.Status, tags=["system"])
def status():
    queue = renders().list()
    return {"gpu": engines.gpu_status(), "disk_free_gb": round(shutil.disk_usage(settings.data).free / 1e9, 1),
            "elevenlabs": engines.elevenlabs_available(), "latentsync": engines.latentsync_available(),
            "clone": engines.clone_available(),
            "queue": {"active": sum(j["state"] not in services.TERMINAL for j in queue),
                      "waiting_gpu": sum(j["state"] == "waiting_gpu" for j in queue)},
            "training": sum(a["state"] == "training" for a in trainer().list()),
            "poll_minutes": services.GPU_POLL // 60}


@router.post("/gpu/check", response_model=schemas.Ok, tags=["system"])
def gpu_check():
    renders().check_now()
    return {"ok": True}


# ---- avatars ---------------------------------------------------------------------------------------

def public_avatar(avatar):
    features = core.FEATURES
    return {key: avatar.get(key) for key in ("id", "name", "edition", "summary", "experiment", "default_feature", "source")} | {
        "engines": avatar.get("engines", ["latentsync", "gaussiantalker"]),
        "variants": [{"feature": v["feature"], "label": features[v["feature"]][0], "note": features[v["feature"]][2],
                      "metrics": v.get("metrics", {}),
                      "preview_url": f"/media/avatar/{avatar['id']}/{v['feature']}/preview.mp4" if v.get("preview") else None,
                      "poster_url": f"/media/avatar/{avatar['id']}/{v['feature']}/poster.jpg" if v.get("preview") else None}
                     for v in avatar["variants"]]}


@router.get("/avatars", response_model=list[schemas.Avatar], tags=["avatars"])
def list_avatars():
    return [public_avatar(a) for a in services.all_avatars()]


@router.get("/quick", response_model=list[schemas.Quick], tags=["avatars"])
def list_quick():
    return [{k: q.get(k) for k in ("id", "name", "state", "detail", "created", "seconds")} for q in services.list_quick()]


@router.post("/quick", response_model=schemas.Quick, tags=["avatars"])
def create_quick(body: schemas.QuickCreate):
    try:
        upload = services.get_upload(body.upload)
    except KeyError:
        bad("upload the video first")
    if upload["kind"] != "video":
        bad("upload a video")
    try:
        quick = services.create_quick(body.name.strip()[:60] or "Quick avatar", upload["path"], body.consent)
    except ValueError as error:
        bad(error)
    return {k: quick.get(k) for k in ("id", "name", "state", "detail", "created", "seconds")}


# ---- voices ----------------------------------------------------------------------------------------

def catalogue():
    return json.loads((PACKAGE / "catalog/voices.json").read_text())


@router.get("/voices", response_model=schemas.VoiceCatalogue, tags=["voices"])
def voices():
    data = catalogue()
    return {"elevenlabs": data["elevenlabs"], "mms": data["mms"], "clone_available": engines.clone_available(),
            "clone": [{"id": v["id"], "name": v["name"], "state": v["state"], "detail": v.get("detail"),
                       "accent": "cloned", "style": "your voice · F5-TTS",
                       "sample_url": f"/media/clone/{v['id']}/sample.wav" if v["state"] == "ready" else None}
                      for v in services.list_clones()]}


@router.post("/voices/sample", response_model=schemas.Url, tags=["voices"])
def voice_sample(body: schemas.VoiceSampleRequest):
    entry = next((v for v in catalogue().get(body.provider, []) if v["id"] == body.id), None)
    if not entry:
        bad("unknown voice")
    out = settings.data / "cache/voices" / f"{body.provider}-{core.slugify(body.id)}.wav"
    if not out.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
        text = ("Halo, saya suara bahasa Indonesia di Yatta." if body.id == "ind"
                else f"Hi, I'm {entry['name']}. This is how your avatar will sound with my voice.")
        try:
            engines.synthesize({"provider": body.provider, "id": body.id}, text, None, out, settings.data / "cache/voices.log")
        except engines.StepError as error:
            bad(error)
    return {"url": f"/media/voice/{out.name}"}


@router.post("/voices/clones", response_model=schemas.Voice, tags=["voices"])
def create_clone(body: schemas.CloneCreate):
    try:
        profile = services.create_clone(body.name.strip()[:60] or "My voice", body.upload, body.consent, body.clip, body.text)
    except (ValueError, KeyError) as error:
        bad(error)
    return {"id": profile["id"], "name": profile["name"], "state": profile["state"]}


@router.delete("/voices/clones/{voice_id}", response_model=schemas.Ok, tags=["voices"])
def delete_clone(voice_id: str):
    try:
        services.delete_clone(voice_id)
    except KeyError:
        not_found()
    return {"ok": True}


# ---- uploads ---------------------------------------------------------------------------------------

def upload_folder(upload_id):
    if "/" in upload_id or upload_id.startswith("."):
        not_found()
    folder = settings.data / "uploads" / upload_id
    record = services.read_json(folder / "upload.json")
    if not record:
        not_found()
    return folder, record


def public_upload(record):
    return {k: v for k, v in record.items() if k not in ("path", "partial", "received")}


@router.post("/uploads", response_model=schemas.UploadTicket, tags=["uploads"])
def start_upload(body: schemas.UploadStart):
    """Begin a chunked upload; send the bytes with PUT /uploads/{id}?offset=N, then POST /uploads/{id}/finish."""
    if body.size <= 0 or body.size > LIMITS[body.kind]:
        bad("file too large" if body.size > 0 else "empty file", 413)
    if body.kind == "video" and shutil.disk_usage(settings.data).free < body.size + settings.min_free_gb * 1e9:
        bad(f"not enough disk space: keep {settings.min_free_gb:.0f} GB free for training after the upload", 507)
    upload_id = services.new_id("u")
    folder = settings.data / "uploads" / upload_id
    folder.mkdir(parents=True)
    safe = core.slugify(Path(body.name).stem, "file") + Path(body.name).suffix.lower()[:8]
    (folder / safe).touch()
    services.write_json(folder / "upload.json", {
        "id": upload_id, "kind": body.kind, "name": body.name, "path": str(folder / safe), "size": body.size,
        "received": 0, "partial": True, "created": services.now()})
    return {"id": upload_id, "chunk_limit": CHUNK_LIMIT}


@router.put("/uploads/{upload_id}", response_model=schemas.UploadProgress, tags=["uploads"])
async def upload_chunk(upload_id: str, offset: int, request: Request):
    folder, record = upload_folder(upload_id)
    if not record.get("partial"):
        bad("upload already finished")
    if offset != record["received"]:
        bad(f"expected offset {record['received']}", 409)
    received = 0
    with open(record["path"], "ab") as out:
        async for chunk in request.stream():
            received += len(chunk)
            if received > CHUNK_LIMIT or offset + received > record["size"]:
                out.truncate(offset)
                bad("chunk too large", 413)
            out.write(chunk)
    record["received"] = offset + received
    services.write_json(folder / "upload.json", record)
    return {"received": record["received"]}


@router.post("/uploads/{upload_id}/finish", response_model=schemas.Upload, tags=["uploads"])
def finish_upload(upload_id: str):
    folder, record = upload_folder(upload_id)
    if not record.get("partial"):
        return public_upload(record)
    if record["received"] != record["size"]:
        bad(f"received {record['received']} of {record['size']} bytes")
    digest = hashlib.sha256()
    with open(record["path"], "rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    record["sha256"] = digest.hexdigest()
    if record["kind"] in ("video", "audio"):
        seconds = engines.duration(record["path"])
        if not seconds:
            shutil.rmtree(folder)
            bad("could not read this file as " + record["kind"])
        record["seconds"] = round(seconds, 2)
    record.pop("partial", None)
    record.pop("received", None)
    services.write_json(folder / "upload.json", record)
    return public_upload(record)


@router.get("/backgrounds", response_model=list[schemas.Background], tags=["uploads"])
def backgrounds():
    return [{"id": b["id"], "name": b["name"], "url": f"/media/upload/{b['id']}"} for b in services.list_backgrounds()]


# ---- renders ---------------------------------------------------------------------------------------

def public_job(job):
    out = {k: v for k, v in job.items() if k != "audio_upload"}
    if job["state"] == "done":
        out["video_url"] = f"/media/render/{job['id']}/video.mp4"
        out["poster_url"] = f"/media/render/{job['id']}/poster.jpg"
    if job.get("published"):
        out["watch_url"] = f"/watch/{job['published']}"
    return out


def job_or_404(job_id):
    try:
        return renders().get(job_id)
    except KeyError:
        not_found()


@router.post("/renders", response_model=schemas.Render, tags=["renders"])
def create_render(body: schemas.RenderCreate):
    request = body.model_dump()
    voice = body.voice
    if voice.provider == "upload":
        try:
            record = services.get_upload(body.audio_upload or "")
        except KeyError:
            bad("upload the audio first")
        if record["kind"] != "audio":
            bad("not an audio upload")
        request["audio_upload"] = record["path"]
    else:
        if not body.text.strip():
            bad("write something for the avatar to say")
        if len(body.text) > 2500:
            bad("keep the script under 2,500 characters")
        if voice.provider == "clone":
            try:
                if engines.clone_profile(voice.id or "").get("state") != "ready":
                    bad("this cloned voice is still being prepared")
            except engines.StepError as error:
                bad(error)
    background = request["background"]
    if background["type"] == "image":
        try:
            record = services.get_upload(background.get("upload") or "")
        except KeyError:
            bad("unknown background image")
        background = {"type": "image", "upload": record["id"], "path": record["path"]}
    request["background"] = {k: v for k, v in background.items() if v is not None}
    request["voice"] = {k: v for k, v in request["voice"].items() if v is not None}
    try:
        return public_job(renders().submit(request))
    except ValueError as error:
        bad(error)


@router.get("/renders", response_model=list[schemas.Render], tags=["renders"])
def list_renders():
    return [public_job(j) for j in renders().list()]


@router.get("/renders/{job_id}", response_model=schemas.Render, tags=["renders"])
def get_render(job_id: str):
    return public_job(job_or_404(job_id))


@router.delete("/renders/{job_id}", response_model=schemas.Ok, tags=["renders"])
def delete_render(job_id: str):
    job_or_404(job_id)
    try:
        renders().delete(job_id)
    except ValueError as error:
        bad(error)
    return {"ok": True}


@router.post("/renders/{job_id}/publish", response_model=schemas.Render, tags=["renders"])
def publish(job_id: str, body: schemas.PublishRequest):
    """Give the render a public share page at /watch/<slug> (no access key needed to watch)."""
    job = job_or_404(job_id)
    if job["state"] != "done":
        bad("render is not finished")
    title = (body.title or job["title"]).strip()[:120]
    slug = job.get("published") or f"{core.slugify(title, 'video')}-{job_id[-4:]}"
    return public_job(renders().update(job_id, published=slug, title=title))


@router.post("/renders/{job_id}/unpublish", response_model=schemas.Render, tags=["renders"])
def unpublish(job_id: str):
    job_or_404(job_id)
    return public_job(renders().update(job_id, published=None))


# ---- training --------------------------------------------------------------------------------------

def public_training(avatar):
    return {k: v for k, v in avatar.items() if k != "uploads"}


def training_or_404(avatar_id):
    try:
        return trainer().status(avatar_id)
    except KeyError:
        not_found()


@router.post("/trainings", response_model=schemas.Training, tags=["training"])
def create_training(body: schemas.TrainingCreate):
    try:
        return public_training(trainer().create(body.name.strip() or "My avatar", body.uploads, body.consent))
    except (ValueError, KeyError) as error:
        bad(error)


@router.get("/trainings", response_model=list[schemas.Training], tags=["training"])
def list_trainings():
    return [public_training(a) for a in trainer().list()]


@router.get("/trainings/{avatar_id}", response_model=schemas.Training, tags=["training"])
def get_training(avatar_id: str):
    return public_training(training_or_404(avatar_id))


@router.post("/trainings/{avatar_id}/approve", response_model=schemas.Training, tags=["training"])
def approve_training(avatar_id: str, body: schemas.TrainingApprove):
    training_or_404(avatar_id)
    try:
        trainer().approve(avatar_id, [c.model_dump() for c in body.crops], body.features)
    except (ValueError, KeyError, subprocess.CalledProcessError) as error:
        bad(error)
    return public_training(trainer().status(avatar_id))


@router.post("/trainings/{avatar_id}/retry", response_model=schemas.Training, tags=["training"])
def retry_training(avatar_id: str):
    training_or_404(avatar_id)
    try:
        trainer().retry(avatar_id)
    except ValueError as error:
        bad(error)
    return public_training(trainer().status(avatar_id))


@router.delete("/trainings/{avatar_id}", response_model=schemas.Ok, tags=["training"])
def discard_training(avatar_id: str):
    avatar = training_or_404(avatar_id)
    if avatar["state"] not in ("review", "failed") or avatar.get("active") or avatar.get("ready_features"):
        bad("only an avatar that is in review or failed without a trained model can be discarded")
    shutil.rmtree(trainer().path(avatar_id))
    return {"ok": True}
