import json
import os
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from yatta import api, app as yatta_app, auth, services
from yatta.config import settings

KEY = "test-key-123"
HOST = "yatta.example.com"
WRITE = {"X-Yatta": "1"}


def client():
    return TestClient(yatta_app.create_app(), base_url=f"https://{HOST}")


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        settings.data.mkdir(parents=True, exist_ok=True)
        settings.web_dist.mkdir(parents=True, exist_ok=True)
        (settings.web_dist / "index.html").write_text("<title>Yatta</title>")
        auth.save_password(KEY)
        api.state.update(renders=services.RenderQueue(worker=False), trainer=services.Trainer(), throttle=auth.Throttle())

    def signed_in(self):
        c = client()
        self.assertEqual(c.post("/api/v1/session", json={"key": KEY}, headers=WRITE).status_code, 200)
        return c

    def test_unknown_host_is_refused_and_alias_redirects(self):
        c = client()
        self.assertEqual(c.get("/", headers={"host": "evil.example"}).status_code, 403)
        r = c.get("/create?x=1", headers={"host": "old.example.com"}, follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (301, f"https://{HOST}/create?x=1"))

    def test_web_shell_is_public_api_is_not(self):
        c = client()
        self.assertEqual(c.get("/create").status_code, 200)
        self.assertEqual(c.get("/api/v1/avatars").status_code, 401)
        self.assertEqual(c.get("/media/voice/x.wav").status_code, 401)
        self.assertEqual(c.get("/api/v1/session").json(), {"signed_in": False})

    def test_writes_need_the_header(self):
        r = client().post("/api/v1/session", json={"key": KEY})
        self.assertEqual(r.status_code, 403)

    def test_wrong_key_and_key_link(self):
        c = client()
        self.assertEqual(c.post("/api/v1/session", json={"key": "nope"}, headers=WRITE).status_code, 401)
        r = c.get(f"/library?key={KEY}", follow_redirects=False)
        self.assertEqual((r.status_code, r.headers["location"]), (303, "/library"))
        self.assertIn(auth.COOKIE, r.cookies)
        self.assertEqual(c.get("/api/v1/session").json(), {"signed_in": True})

    def test_signed_in_lists_and_status(self):
        c = self.signed_in()
        self.assertEqual(c.get("/api/v1/avatars").json(), [])
        voices = c.get("/api/v1/voices").json()
        self.assertGreaterEqual(len(voices["elevenlabs"]), 10)
        self.assertIn("clone_available", voices)
        self.assertIsInstance(c.get("/api/v1/renders").json(), list)
        self.assertEqual(c.delete("/api/v1/session", headers=WRITE).json(), {"signed_in": False})

    def test_chunked_upload(self):
        c = self.signed_in()
        data = os.urandom(300_000)
        ticket = c.post("/api/v1/uploads", json={"kind": "background", "name": "sky.png", "size": len(data)}, headers=WRITE).json()
        r1 = c.put(f"/api/v1/uploads/{ticket['id']}?offset=0", content=data[:200_000], headers=WRITE)
        self.assertEqual(r1.json(), {"received": 200_000})
        self.assertEqual(c.put(f"/api/v1/uploads/{ticket['id']}?offset=5", content=b"x", headers=WRITE).status_code, 409)
        c.put(f"/api/v1/uploads/{ticket['id']}?offset=200000", content=data[200_000:], headers=WRITE)
        done = c.post(f"/api/v1/uploads/{ticket['id']}/finish", headers=WRITE).json()
        self.assertEqual((done["size"], "path" in done), (len(data), False))
        self.assertEqual([b["id"] for b in c.get("/api/v1/backgrounds").json()], [ticket["id"]])

    def test_publish_makes_a_public_share_page(self):
        job_dir = settings.data / "renders" / "r-test-0001"
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "video.mp4").write_bytes(b"mp4")
        (job_dir / "poster.jpg").write_bytes(b"jpg")
        services.write_json(job_dir / "job.json", {
            "id": "r-test-0001", "created": "2026-10-26T00:00:00+00:00", "updated": "2026-10-26T00:00:00+00:00",
            "state": "done", "detail": "", "title": "Hello <world>", "text": "hi", "avatar": "a", "avatar_name": "Henry",
            "feature": "latentsync", "engine": "latentsync", "voice": {"provider": "clone", "id": "v"}, "published": None})
        anonymous = client()
        self.assertEqual(anonymous.get("/media/render/r-test-0001/video.mp4").status_code, 401)
        c = self.signed_in()
        job = c.post("/api/v1/renders/r-test-0001/publish", json={}, headers=WRITE).json()
        page = anonymous.get(job["watch_url"])
        self.assertEqual(page.status_code, 200)
        self.assertIn(f'property="og:image" content="https://{HOST}/media/render/r-test-0001/poster.jpg"', page.text)
        self.assertIn("Hello &lt;world&gt;", page.text)
        self.assertEqual(anonymous.get("/media/render/r-test-0001/video.mp4").status_code, 200)
        c.post("/api/v1/renders/r-test-0001/unpublish", headers=WRITE)
        self.assertEqual(anonymous.get("/media/render/r-test-0001/video.mp4").status_code, 401)

    def test_openapi_is_public_and_versioned(self):
        spec = client().get("/api/v1/openapi.json").json()
        self.assertEqual(spec["info"]["title"], "Yatta API")
        self.assertIn("/api/v1/renders", spec["paths"])


if __name__ == "__main__":
    unittest.main()
