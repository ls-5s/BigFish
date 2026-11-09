import json
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

VIDEO_URL = "https://www.douyin.com/video/7625667148647765157"
PROFILE = r"C:\Users\86177\Desktop\dafyue\.dy-profile"
OUT = Path(r"C:\Users\86177\Desktop\dafyue\.tmp\dy_voice")
OUT.mkdir(parents=True, exist_ok=True)


def pick_mp4(entries):
    cands = [e for e in entries if ".mp4" in e or "video" in e or "aweme" in e]
    return cands


with sync_playwright() as p:
    ctx = p.chromium.launch_persistent_context(
        PROFILE,
        headless=True,
        channel="chrome",
        args=["--mute-audio", "--autoplay-policy=no-user-gesture-required"],
    )
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    page.goto(VIDEO_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(8000)
    print("TITLE:", page.title())
    print("URL:", page.url)

    html = page.content()
    print("HTML_LEN:", len(html))
    for pat in ("play_addr", "url_list", "video/tos", "aweme/v1/play"):
        print(pat, html.count(pat))

    # try video element src
    src = page.evaluate("() => { const v = document.querySelector('video'); return v ? (v.currentSrc || v.src) : '' }")
    print("VIDEO_SRC:", (src or "")[:200])

    # resource urls
    urls = page.evaluate("() => performance.getEntriesByType('resource').map(e => e.name)")
    mp4 = [u for u in urls if ".mp4" in u or "video/tos" in u or "aweme" in u]
    print("MP4_CANDIDATES:", len(mp4))
    for u in mp4[:5]:
        print("  ", u[:200])

    target = (src if src and src.startswith("http") else (mp4[0] if mp4 else ""))
    if target:
        try:
            resp = ctx.request.get(target, headers={"Referer": "https://www.douyin.com/"})
            print("DL_STATUS:", resp.status, "len=", len(resp.body()))
            (OUT / "source.mp4").write_bytes(resp.body())
            print("SAVED:", OUT / "source.mp4")
        except Exception as exc:
            print("DL_ERR:", repr(exc))
    else:
        # fallback: search html for mp4 urls
        found = re.findall(r'https?://[^"\\]+?\.mp4[^"\\]*', html)
        print("HTML_MP4:", len(found))
        if found:
            try:
                resp = ctx.request.get(found[0], headers={"Referer": "https://www.douyin.com/"})
                (OUT / "source.mp4").write_bytes(resp.body())
                print("SAVED_FROM_HTML:", len(resp.body()))
            except Exception as exc:
                print("DL_ERR2:", repr(exc))

    ctx.close()
print("DONE")
