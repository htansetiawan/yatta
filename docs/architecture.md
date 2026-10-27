# Architecture

## Layers

| Layer | Module | Responsibility |
|---|---|---|
| Web | `web/` | React app; talks only to `/api/v1`, with types generated from the OpenAPI schema |
| HTTP | `yatta/app.py` | Host and session guard, `X-Yatta` header check, media files, public share pages, static web app |
| API | `yatta/api.py`, `yatta/schemas.py` | Versioned JSON endpoints; validation and response shaping only |
| Services | `yatta/services.py` | Render queue, training manager, cloned voices, Quick avatars, uploads; JSON state in `YATTA_DATA` |
| Steps | `yatta/steps.py`, `yatta/gpu.py` | Speech synthesis, audio levels, encoding; the GPU gate |
| Engines | `yatta/engines/` | One module per video model, behind one interface; the registry is all the rest of Yatta sees |
| Training | `yatta/training/` | GaussianTalker training as a systemd unit |

## A render

1. **Request.** `POST /api/v1/renders` (avatar, engine, script or audio, voice, background) writes `renders/<id>/job.json` in the `queued` state.
2. **Speech.** The single render worker generates speech: ElevenLabs, MMS, a cloned voice through narrate (F5-TTS), or the uploaded audio.
3. **Engine.** The job's engine prepares (CPU work), the worker waits for the GPU (`min_free_mib`), and the engine renders:
   - **Realistic** (`latentsync`): LatentSync 1.6 runs on a face clip of the avatar: the last 30 s of its training video, or a Quick avatar's clip.
   - **Expressive** (`longcat`): LongCat-Video-Avatar 1.5 generates the whole video from one frame of that clip, through `scripts/run_longcat.py` in the research repository.
   - **Lifelike** (`minimax_h3`): MiniMax H3 generates the video from one frame of the clip through a local ComfyUI server (started per render, `127.0.0.1` only, offline), in pieces of up to 14.5 s cut at pauses, with the original speech kept as the soundtrack.
   - **Fast** (`gaussiantalker`): Yatta builds a per-job dataset of symlinks to the trained avatar. It contains the background, the held-out head poses looped back and forth to the speech length, a slim `track_params.pt`, and a two-frame training list. GaussianTalker renders with only the attention-free output.
4. **Output.** The result is encoded to H.264/AAC MP4 with a poster frame. The job becomes `done`, and the web app shows it.

## Adding an engine

Every video model is a module in `yatta/engines/` with an `Engine` subclass (`yatta/engines/base.py`):

- **Description** for the picker: `id`, `name`, `model`, `summary`, `badge`, `licence`, and rough timing (`load_seconds`, `seconds_per_second`).
- **What it needs** from an avatar: `needs = "clip"` (a video of the face), `"photo"` (one frame of it) or `"trained"` (a GaussianTalker model). `face_clip()` and `face_photo()` provide the first two for any avatar.
- **Options:** `backgrounds` (can replace the background) and `speech_models` (offers the avatar's speech-feature variants).
- **`available()`**: true once its code, environment and weights are installed; until then the engine is listed with `available: false` and hidden from the picker.
- **`render(job)`**: returns a video whose audio track is the job's speech; `prepare(job)` and `cleanup(job, output)` are optional.

Then list it in `ENGINES` (`yatta/engines/__init__.py`). `GET /api/v1/engines`, each avatar's `engines`, the render queue and the web app's engine picker all follow from the registry.

## The GPU policy

The host's GPU is shared with other projects.
- Yatta waits while another project is actually working: utilization of 20 % or more over a few samples, or too little free memory.
- When another project was busy in the last 10 minutes, idle has to hold for 30 s, so long jobs do not start in the gap between someone's short runs.
- Waiting jobs re-check every `YATTA_GPU_POLL` seconds (30 min by default). "Check now" in the web app wakes the worker.

## Training

`POST /api/v1/trainings` crops proposals for each uploaded video. Approval launches `yatta/training/train_avatar.sh` as the systemd user unit `yatta-train-<id>` (`MemoryMax=28G`, `LimitNOFILE=1048576`):

1. Prepare and join the videos.
2. Audio features and blinks.
3. Face parsing, background, torso and tracking (GaussianTalker's preprocessing).
4. One resumable training run per chosen speech model.
5. Preview render and evaluation.

Progress is read from the unit's `pipeline.log` and the upstream training log.

## Security

| Area | Rule |
|---|---|
| Key | One access key, hashed with scrypt in `YATTA_AUTH_FILE` |
| Sessions | HMAC-signed cookies: HttpOnly, SameSite=Lax, Secure on public hosts |
| Sign-in throttle | 10 failures per 15 min per client |
| Requests | Configured hosts only; writes need `X-Yatta: 1` |
| Public without a session | The web app shell and its assets, `/api/v1/session`, the OpenAPI document, published `/watch/<slug>` pages and their media |
