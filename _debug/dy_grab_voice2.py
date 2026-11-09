import json
from pathlib import Path

from playwright.sync_api import sync_playwright

VIDEO_URL = "https://www.douyin.com/video/7625667148647765157"
PROFILE = r"C:\Users\86177\Desktop\dafyue\.dy-profile"
OUT = Path(r"C:\Users\86177\Desktop\dafyue\.tmp\dy_voice")
OUT.mkdir(parents=True, exist_ok=True)

media = []


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE,
        headless=True,
        channel="chrome",
        args=["--mute-audio", "--autoplay-policy=no-user-gesture-required"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()

    def on_response(resp):
        try:
            ct = (resp.headers or {}).get("content-type", "")
            if "video" in ct or "audio" in ct or ".mp4" in resp.url or "mime_type=video" in resp.url:
                media.append((resp.url, ct, resp))
        except Exception:
            pass

    page.on("response", on_response)
    page.goto(VIDEO_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(12000)

    print("MEDIA_RESPONSES:", len(media))
    for u, ct, _ in media[:6]:
        print("  ", ct, u[:160])

    saved = False
    for u, ct, resp in media:
        try:
            body = resp.body()
            if len(body) > 100000:
                (OUT / "source.mp4").write_bytes(body)
                print("SAVED", len(body), ct, u[:120])
                saved = True
                break
        except Exception as exc:
            print("BODY_ERR", repr(exc))

    if not saved:
        data = page.evaluate("() => window._ROUTER_DATA ? JSON.stringify(window._ROUTER_DATA).length : 0")
        print("ROUTER_DATA_LEN:", data)
        if data:
            blob = page.evaluate("() => JSON.stringify(window._ROUTER_DATA)")
            (OUT / "router.json").write_text(blob, encoding="utf-8")
            print("saved router.json")

    ctx.close()
print("DONE")
