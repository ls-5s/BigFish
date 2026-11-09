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
            if "video/mp4" in ct or "audio" in ct:
                u = resp.url
                if u not in [m[0] for m in media]:
                    media.append((u, ct))
        except Exception:
            pass

    page.on("response", on_response)
    page.goto(VIDEO_URL, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(10000)

    audio_url = next((u for u, _ in media if "media-audio" in u), "")
    video_url = next((u for u, _ in media if "media-video" in u), "")
    print("AUDIO_URL:", audio_url[:140])
    print("VIDEO_URL:", video_url[:140])

    headers = {"Referer": "https://www.douyin.com/", "User-Agent": "Mozilla/5.0"}
    if audio_url:
        r = ctx.request.get(audio_url, headers=headers, timeout=120000)
        print("AUDIO_STATUS:", r.status, "len=", len(r.body()))
        (OUT / "audio.mp4").write_bytes(r.body())
    if video_url:
        r2 = ctx.request.get(video_url, headers=headers, timeout=120000)
        print("VIDEO_STATUS:", r2.status, "len=", len(r2.body()))
        (OUT / "video.mp4").write_bytes(r2.body())

    ctx.close()
print("DONE")
