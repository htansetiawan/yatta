"""Render brand assets (icons, share card) to web/public with headless Chrome. Run: uv run --with playwright python web/brand/render.py"""
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
PUBLIC = HERE.parent / "public"
ICONS = {"favicon-16": 16, "favicon-32": 32, "apple-touch-icon": 180, "icon-192": 192, "icon-512": 512, "icon-maskable-512": 512}

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True, args=["--no-sandbox"])
    for name, size in ICONS.items():
        page = browser.new_page(viewport={"width": size, "height": size})
        page.goto((HERE / f"{name}.html").as_uri())
        page.screenshot(path=str(PUBLIC / f"{name}.png"), omit_background=True, clip={"x": 0, "y": 0, "width": size, "height": size})
        page.close()
    page = browser.new_page(viewport={"width": 1200, "height": 630})
    page.goto((HERE / "og.html").as_uri(), wait_until="networkidle")
    page.wait_for_timeout(800)
    page.screenshot(path=str(PUBLIC / "og.png"))
    page.screenshot(path=str(PUBLIC / "og.jpg"), type="jpeg", quality=88)
    browser.close()
print("ok")
