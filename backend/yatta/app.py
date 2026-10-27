"""Yatta web server: the /api/v1 API, media files, public share pages and the React web app.

    python -m yatta.app --port 8790

It binds 127.0.0.1; a Cloudflare tunnel publishes it. Access is one shared key (``yatta.auth``): the web app
shell, its assets and share pages (/watch/<slug>) are public; the API and media need a session cookie.
Requests must name a configured host (DNS rebinding), other configured hosts redirect to the canonical one,
and state-changing requests must carry ``X-Yatta: 1``, which a cross-site form cannot send.
"""

import argparse
import html
import mimetypes
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

from yatta import api, auth, core, services, steps
from yatta.config import PACKAGE, env, settings

LOCAL_HOSTS = {"localhost", "127.0.0.1"}
VERSION = "0.1.0"


def is_public(path):
    """Reachable without a session. /media/render/ is checked per job (published videos only)."""
    if path.startswith("/api/"):
        return path in ("/api/v1/session", "/api/v1/openapi.json")
    if path.startswith("/media/"):
        return path.startswith("/media/render/")
    return True  # web app shell, assets, share pages


def create_app():
    app = FastAPI(title="Yatta API", version=VERSION, docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/v1/openapi.json",
                  description="Personal avatar studio: render talking videos of your avatars in any voice.")
    app.include_router(api.router)

    @app.middleware("http")
    async def guard(request: Request, call_next):
        host = (request.headers.get("host") or "").rsplit(":", 1)[0]
        if host not in LOCAL_HOSTS and host not in settings.hosts:
            return JSONResponse({"detail": "unknown host"}, status_code=403)
        if host in settings.hosts and host != settings.canonical_host:
            target = f"https://{settings.canonical_host}{request.url.path}"
            return RedirectResponse(target + (f"?{request.url.query}" if request.url.query else ""), status_code=301)
        if request.method not in ("GET", "HEAD") and request.headers.get("x-yatta") != "1":
            return JSONResponse({"detail": "missing X-Yatta header"}, status_code=403)
        request.state.signed_in = auth.signed_in(request)
        key = request.query_params.get("key")
        if key is not None and request.method == "GET" and not request.url.path.startswith(("/api/", "/media/")):
            # /?key=... signs this browser in, then drops the key from the address bar.
            config = auth.load()
            client = auth.client_id(request)
            if config and not api.state["throttle"].blocked(client) and auth.verify_password(key, config["password"]):
                response = RedirectResponse(request.url.path, status_code=303)
                auth.set_session(response, request, config)
                return response
            api.state["throttle"].fail(client)
            return RedirectResponse("/?signin=failed", status_code=303)
        if not request.state.signed_in and not is_public(request.url.path):
            return JSONResponse({"detail": "sign in required"}, status_code=401)
        return await call_next(request)

    # ---- media ------------------------------------------------------------------------------------

    def variant_or_404(avatar_id, feature):
        avatar, variant = core.find_variant(services.all_avatars(), avatar_id, feature)
        if not variant or not variant.get("preview"):
            raise HTTPException(404)
        return variant

    @app.get("/media/avatar/{avatar_id}/{feature}/preview.mp4", include_in_schema=False)
    def avatar_preview(avatar_id: str, feature: str):
        return FileResponse(variant_or_404(avatar_id, feature)["preview"], media_type="video/mp4")

    @app.get("/media/avatar/{avatar_id}/{feature}/poster.jpg", include_in_schema=False)
    def avatar_poster(avatar_id: str, feature: str):
        variant = variant_or_404(avatar_id, feature)
        poster = settings.data / "cache/posters" / f"{core.slugify(avatar_id)}-{feature}.jpg"
        if not poster.exists():
            steps.poster_for(variant["preview"], poster, settings.data / "cache/posters.log", at=2.0)
        return FileResponse(poster, media_type="image/jpeg")

    def data_file(*parts):
        path = settings.data.joinpath(*[Path(p).name for p in parts])
        if not path.is_file():
            raise HTTPException(404)
        return path

    @app.get("/media/voice/{name}", include_in_schema=False)
    def voice_file(name: str):
        return FileResponse(data_file("cache", "voices", name), media_type="audio/wav")

    @app.get("/media/clone/{voice_id}/sample.wav", include_in_schema=False)
    def clone_sample(voice_id: str):
        return FileResponse(data_file("voices", voice_id, "sample.wav"), media_type="audio/wav")

    @app.get("/media/upload/{upload_id}", include_in_schema=False)
    def upload_file(upload_id: str):
        try:
            record = services.get_upload(upload_id)
        except KeyError:
            raise HTTPException(404)
        if record["kind"] not in ("background", "audio"):
            raise HTTPException(404)
        return FileResponse(record["path"])

    @app.get("/media/training/{avatar_id}/{name}", include_in_schema=False)
    def training_frame(avatar_id: str, name: str):
        if not (name.startswith("frame_") and name.endswith(".jpg")):
            raise HTTPException(404)
        return FileResponse(data_file("avatars", avatar_id, name), media_type="image/jpeg")

    @app.get("/media/render/{job_id}/{name}", include_in_schema=False)
    def render_file(job_id: str, name: str, request: Request):
        if name not in ("video.mp4", "poster.jpg"):
            raise HTTPException(404)
        try:
            job = api.renders().get(job_id)
        except KeyError:
            raise HTTPException(404)
        if not request.state.signed_in and not job.get("published"):
            raise HTTPException(401, "sign in required")
        path = api.renders().path(job_id) / name
        if not path.is_file():
            raise HTTPException(404)
        return FileResponse(path, media_type="video/mp4" if name.endswith(".mp4") else "image/jpeg",
                            filename=f"yatta-{job_id}.mp4" if name.endswith(".mp4") else None,
                            content_disposition_type="inline")

    # ---- public share pages ---------------------------------------------------------------------------

    @app.get("/watch/{slug}", response_class=HTMLResponse, include_in_schema=False)
    def watch(slug: str):
        job = next((j for j in api.renders().list() if j.get("published") == slug), None)
        if not job:
            raise HTTPException(404)
        base = f"https://{settings.canonical_host}"
        page = (PACKAGE / "templates/watch.html").read_text()
        values = {"TITLE": html.escape(job["title"]), "URL": f"{base}/watch/{slug}",
                  "VIDEO": f"{base}/media/render/{job['id']}/video.mp4",
                  "POSTER": f"{base}/media/render/{job['id']}/poster.jpg",
                  "DESCRIPTION": html.escape(f"{job['avatar_name']} · made with Yatta")}
        for key, value in values.items():
            page = page.replace("{{" + key + "}}", value)
        return page

    # ---- web app ------------------------------------------------------------------------------------

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str):
        dist = settings.web_dist
        if path.startswith(("api/", "media/")):
            raise HTTPException(404)
        target = (dist / path).resolve()
        if path and target.is_file() and target.is_relative_to(dist.resolve()):
            immutable = path.startswith("assets/")
            return FileResponse(target, media_type=mimetypes.guess_type(target.name)[0],
                                headers={"Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"})
        index = dist / "index.html"
        if not index.is_file():
            return HTMLResponse("<p>Web app not built. Run <code>npm run build</code> in web/.</p>", status_code=503)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8790)
    args = parser.parse_args()
    settings.data.mkdir(parents=True, exist_ok=True)
    # YATTA_WORKER=0 serves the API without processing renders (a second instance next to the worker).
    worker = env("YATTA_WORKER", "1") != "0"
    api.state.update(renders=services.RenderQueue(worker=worker), trainer=services.Trainer(), throttle=auth.Throttle())
    api.state["renders"].start()
    import uvicorn
    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
