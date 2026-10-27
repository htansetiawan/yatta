# Yatta やった

**Your face. Your voice. Any words.**

Yatta (やった, Japanese for *"Yay!"* or *"I did it!"*) is a personal avatar studio. You write a script and pick a face and a voice; Yatta renders a talking video you can download or share with a link.

- **Realistic engine:** [LatentSync 1.6](https://github.com/bytedance/LatentSync) keeps real footage of you and regenerates only the mouth to match the speech. It needs no training: a 15–60 s clip is enough.
- **Fast engine:** a [GaussianTalker](https://github.com/cvlab-kaist/GaussianTalker) avatar trained on 3–6 minutes of video. It renders in about 20 s and supports custom backgrounds.
- **Voices:**
  - [ElevenLabs](https://elevenlabs.io) stock voices.
  - Meta MMS (free and local; English and Indonesian).
  - Your own voice, cloned from 10–15 s of speech with [F5-TTS](https://github.com/SWivid/F5-TTS) through [narrate](https://github.com/htansetiawan/narrate).
  - An uploaded or recorded audio file.
- **Sharing:** every video can get a public `/watch/<slug>` page with iMessage, WhatsApp and Open Graph previews.

Website: **[htansetiawan.github.io/yatta](https://htansetiawan.github.io/yatta/)** · Studio (private beta): [yatta.enrica.ai](https://yatta.enrica.ai/)

This repository is the product system: the API, the render and training services, and the web app. It contains **no data, no media, no model weights and no keys**; those live on the host, outside the repository.

## Architecture

```
web/ (React + TypeScript + Vite)          typed client generated from the OpenAPI schema
   │  /api/v1  (JSON, access-key session)
backend/yatta/
   app.py       FastAPI app: host and session guard, media, share pages, serves web/dist
   api.py       /api/v1 routers: session, status, avatars, voices, uploads, renders, trainings
   schemas.py   request/response models → OpenAPI (/api/v1/openapi.json, docs at /api/docs)
   services.py  render queue (one GPU worker), training manager, voice clones, Quick avatars
   engines.py   speech → features → GaussianTalker / LatentSync render → MP4; GPU gate
   core.py      pure helpers (pose looping, log parsing, registry)
   training/    train_avatar.sh + configs: GaussianTalker training as a systemd unit
site/           landing page, deployed to GitHub Pages by .github/workflows/pages.yml
```

Read [docs/architecture.md](docs/architecture.md) for the request lifecycle and the GPU policy.

## Run locally

Requirements:
- Linux with an NVIDIA GPU (developed on an RTX PRO 5000 Blackwell, 48 GB);
- `ffmpeg`, [uv](https://docs.astral.sh/uv/) and Node 22;
- the engine environments: a GaussianTalker checkout prepared like [gaussian-talker](https://github.com/henryatharvard/gaussian-talker) (`GAUSSIAN_TALKER_ROOT`), LatentSync with its checkpoints (`LATENTSYNC_ROOT`, `LATENTSYNC_PYTHON`), and optionally narrate (`NARRATE_BIN`).

```bash
cd backend && uv venv --python 3.11 && uv pip install -e ".[dev]" && cd ..
cd web && npm ci && npm run build && cd ..
cd backend && .venv/bin/python -m yatta.auth          # prints an access key and sign-in link
.venv/bin/python -m yatta.app --port 8790            # http://localhost:8790
```

For development with hot reload, `scripts/dev.sh` runs the API (without the render worker) and Vite on :5173.

## Configuration

Settings come from the environment or from `~/.config/yatta/env` (`KEY=VALUE`, outside the repository). See [`backend/yatta/config.py`](backend/yatta/config.py).

| Variable | Default | Meaning |
|---|---|---|
| `YATTA_DATA` | `~/.local/share/yatta` | Uploads, renders, voices, avatars, caches |
| `YATTA_AUTH_FILE` | `~/.config/yatta/auth.json` | Hash of the access key and the session secret |
| `YATTA_HOSTS` | `yatta.enrica.ai,avatar.enrica.ai` | Allowed hosts; the first is canonical, the others redirect to it |
| `GAUSSIAN_TALKER_ROOT` | `~/git/gaussian-talker` | GaussianTalker environments and scripts |
| `LATENTSYNC_ROOT`, `LATENTSYNC_PYTHON` | under `GAUSSIAN_TALKER_ROOT/.local` | LatentSync checkout and interpreter |
| `NARRATE_BIN` | `~/git/narrate/narrate` | Voice cloning |
| `YATTA_GPU_POLL` | `1800` | Seconds between GPU checks while another project is using it |
| `YATTA_WORKER` | `1` | `0` serves the API without processing renders |

Research avatars trained outside Yatta can be listed in `$YATTA_DATA/registry.json` ([example](docs/registry.example.json)).

## API

Everything the web app does goes through the versioned JSON API under `/api/v1`, documented at `/api/docs`. The OpenAPI document is at `/api/v1/openapi.json`, and `npm run gen:api` regenerates the TypeScript types from it.

Access is one shared key:
- `POST /api/v1/session {key}` sets an HttpOnly session cookie for 30 days.
- Opening `/?key=…` does the same.
- State-changing requests must send `X-Yatta: 1`.

## Tests

```bash
cd backend && .venv/bin/python -m pytest -q                       # unit and API tests
YATTA_KEY=… uv run --no-project --with playwright python scripts/e2e.py   # browser smoke test
```

## Deploy

`deploy/yatta.service` runs the server as a systemd user service on `127.0.0.1:8790`, and a Cloudflare Tunnel publishes it; see [deploy/README.md](deploy/README.md).

## Licences and consent

Yatta's own code is © Henry Tan. The engines it drives have their own licences:

| Engine | Licence |
|---|---|
| GaussianTalker | Research-only |
| Basel Face Model | Non-commercial |
| F5-TTS weights | CC-BY-NC 4.0 |
| MMS voices | CC-BY-NC 4.0 |
| LatentSync | Apache-2.0 |

So the current stack is for personal and research use. Only create avatars or voice clones of people who agreed; Yatta asks for confirmation every time.
