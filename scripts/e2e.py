"""Browser smoke test of a running Yatta (Playwright + Chrome). Screenshots go to OUT.

    YATTA_KEY=<key> YATTA_URL=http://localhost:8790 uv run --no-project --with playwright python scripts/e2e.py [OUT]
"""
import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = os.environ.get("YATTA_URL", "http://localhost:8790")
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/yatta-e2e")
OUT.mkdir(parents=True, exist_ok=True)

with sync_playwright() as p:
    browser = p.chromium.launch(executable_path=os.environ.get("CHROME", "/usr/bin/google-chrome"), headless=True, args=["--no-sandbox"])
    for name, viewport in (("desktop", {"width": 1440, "height": 1000}), ("phone", {"width": 390, "height": 844})):
        page = browser.new_page(viewport=viewport)
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.on("console", lambda m: m.type == "error" and "401" not in m.text and errors.append(m.text))
        page.goto(URL, wait_until="networkidle")
        page.wait_for_selector(".hero")
        page.screenshot(path=str(OUT / f"{name}-landing.png"))
        page.fill("input[type=password]", "wrong key")
        page.click("button:has-text('Enter')")
        page.wait_for_selector("text=Wrong key")
        page.fill("input[type=password]", os.environ["YATTA_KEY"])
        page.click("button:has-text('Enter')")
        page.wait_for_selector(".settings img.thumb")
        assert page.locator(".settings img.thumb").count() >= 3
        page.locator("textarea").fill("Hello from the Yatta browser test.")
        page.click("button.option:has-text('Fast')")
        assert page.locator(".swatch").count() >= 6
        page.click("button.option:has-text('Realistic')")
        page.click(".seg button:has-text('My voices')")
        page.wait_for_timeout(300)
        page.screenshot(path=str(OUT / f"{name}-create.png"), full_page=True)
        for route in ("avatars", "voices", "train", "library"):
            page.goto(f"{URL}/{route}", wait_until="networkidle")
            page.wait_for_timeout(500)
            page.screenshot(path=str(OUT / f"{name}-{route}.png"), full_page=True)
        width = page.evaluate("document.documentElement.scrollWidth")
        assert width <= viewport["width"] + 1, f"horizontal overflow on {name}: {width}"
        assert not errors, errors
        page.close()
    browser.close()
print(f"ok; screenshots in {OUT}")
