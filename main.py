# main.py
import asyncio
import base64
import json
import logging
from typing import Set

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# Playwright imports
from playwright.async_api import async_playwright, Playwright, Page, Browser

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("remote-browser-proto")

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")

# Globals
PLAYWRIGHT: Playwright = None
VISIBLE_BROWSER: Browser = None
VISIBLE_CONTEXT = None
VISIBLE_PAGE: Page = None

HEADLESS_BROWSER: Browser = None
HEADLESS_CONTEXT = None
HEADLESS_PAGE: Page = None

PAGE_LOCK = asyncio.Lock()
CLIENTS: Set[WebSocket] = set()

CAPTURE_FPS = 5
_capture_task = None

@app.on_event("startup")
async def on_startup():
    global PLAYWRIGHT, VISIBLE_BROWSER, VISIBLE_CONTEXT, VISIBLE_PAGE
    global HEADLESS_BROWSER, HEADLESS_CONTEXT, HEADLESS_PAGE, _capture_task

    try:
        PLAYWRIGHT = await async_playwright().start()
        logger.info("Playwright started.")
    except Exception as e:
        logger.exception("Failed to start Playwright. Ensure playwright is installed and browsers are installed: %s", e)
        # If playwright fails, do not continue — leave server running but no streaming
        return

    try:
        # Visible browser for debugging
        VISIBLE_BROWSER = await PLAYWRIGHT.chromium.launch(headless=False, args=["--start-maximized"])
        VISIBLE_CONTEXT = await VISIBLE_BROWSER.new_context(viewport={"width": 1280, "height": 720})
        VISIBLE_PAGE = await VISIBLE_CONTEXT.new_page()
        await VISIBLE_PAGE.goto("https://example.com")
        logger.info("Visible browser launched.")
    except Exception:
        logger.exception("Failed to start visible browser (debug). Continuing without it.")

    try:
        # Headless browser for streaming
        HEADLESS_BROWSER = await PLAYWRIGHT.chromium.launch(headless=True)
        HEADLESS_CONTEXT = await HEADLESS_BROWSER.new_context(viewport={"width": 1280, "height": 720})
        HEADLESS_PAGE = await HEADLESS_CONTEXT.new_page()
        await HEADLESS_PAGE.goto("https://example.com")
        logger.info("Headless browser launched and navigated to example.com.")
    except Exception:
        logger.exception("Failed to start headless browser. Streaming disabled.")
        HEADLESS_PAGE = None

    # Start capture loop only if headless page is available
    if HEADLESS_PAGE:
        _capture_task = asyncio.create_task(capture_loop())
        logger.info("Capture loop started.")
    else:
        logger.warning("Headless page not available; capture loop not started.")

    logger.info("Server startup complete.")

@app.on_event("shutdown")
async def on_shutdown():
    global PLAYWRIGHT, VISIBLE_BROWSER, HEADLESS_BROWSER, _capture_task
    try:
        if _capture_task:
            _capture_task.cancel()
    except Exception:
        pass

    try:
        if VISIBLE_BROWSER:
            await VISIBLE_BROWSER.close()
        if HEADLESS_BROWSER:
            await HEADLESS_BROWSER.close()
        if PLAYWRIGHT:
            await PLAYWRIGHT.stop()
    except Exception as e:
        logger.exception("Error during shutdown: %s", e)

async def capture_loop():
    global HEADLESS_PAGE
    logger.info("capture_loop running (fps=%s)", CAPTURE_FPS)
    sleep_time = 1.0 / max(1, CAPTURE_FPS)
    while True:
        if not CLIENTS:
            await asyncio.sleep(0.5)
            continue
        if not HEADLESS_PAGE:
            logger.warning("HEADLESS_PAGE not available in capture_loop; sleeping.")
            await asyncio.sleep(1.0)
            continue
        try:
            img_bytes = await HEADLESS_PAGE.screenshot(type="jpeg", quality=60)
            b64 = base64.b64encode(img_bytes).decode("ascii")
            vs = HEADLESS_PAGE.viewport_size or {"width": 1280, "height": 720}

            payload = json.dumps({
                "type": "frame",
                "image": b64,
                "width": vs["width"],
                "height": vs["height"],
            })

            stale = []
            for ws in list(CLIENTS):
                try:
                    await ws.send_text(payload)
                except Exception:
                    stale.append(ws)
            for ws in stale:
                CLIENTS.discard(ws)
        except Exception:
            logger.exception("Error during capture loop")

        await asyncio.sleep(sleep_time)

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    CLIENTS.add(ws)
    logger.info("Client connected. Total: %s", len(CLIENTS))

    # send meta if page available
    try:
        if HEADLESS_PAGE:
            vs = HEADLESS_PAGE.viewport_size or {"width": 1280, "height": 720}
            await ws.send_text(json.dumps({
                "type": "meta",
                "viewport": vs,
                "url": HEADLESS_PAGE.url
            }))
        else:
            await ws.send_text(json.dumps({"type": "meta", "viewport": {"width": 1280, "height": 720}, "url": ""}))
    except Exception:
        logger.exception("Error sending meta to client.")

    try:
        while True:
            msg = await ws.receive_text()
            try:
                data = json.loads(msg)
                if data.get("type") == "event":
                    # schedule event application
                    asyncio.create_task(handle_event(data))
            except Exception as e:
                logger.warning("Bad message from client: %s", e)
    except WebSocketDisconnect:
        CLIENTS.discard(ws)
        logger.info("Client disconnected.")
    except Exception:
        CLIENTS.discard(ws)
        logger.exception("Websocket handler exception; connection closed.")

async def handle_event(msg: dict):
    """Apply an event to both pages (headless + visible)."""
    global HEADLESS_PAGE, VISIBLE_PAGE
    async with PAGE_LOCK:
        try:
            name = msg.get("name")
            if not HEADLESS_PAGE:
                logger.warning("No headless page to handle event: %s", name)
                return

            vs = HEADLESS_PAGE.viewport_size or {"width": 1280, "height": 720}
            w, h = vs["width"], vs["height"]

            async def apply(page):
                if not page:
                    return
                if name == "click":
                    x = int(float(msg.get("x_ratio", 0)) * w)
                    y = int(float(msg.get("y_ratio", 0)) * h)
                    await page.mouse.click(x, y)
                elif name == "key":
                    key = msg.get("key")
                    if key:
                        if len(key) == 1:
                            await page.keyboard.type(key)
                        else:
                            await page.keyboard.press(key)
                elif name == "navigate":
                    url = msg.get("url", "")
                    if url:
                        if not (url.startswith("http://") or url.startswith("https://")):
                            url = "http://" + url
                        await page.goto(url)
                elif name == "wheel":
                    deltaY = float(msg.get("deltaY", 0))
                    client_h = float(msg.get("clientHeight") or h)
                    pixels = deltaY * (h / client_h) if client_h else deltaY
                    await page.evaluate("(dy) => window.scrollBy(0, dy)", pixels)

            # Apply to both pages (if present)
            await apply(HEADLESS_PAGE)
            await apply(VISIBLE_PAGE)

            # Send fresh frame back to clients (if possible)
            if HEADLESS_PAGE:
                try:
                    img_bytes = await HEADLESS_PAGE.screenshot(type="jpeg", quality=60)
                    b64 = base64.b64encode(img_bytes).decode("ascii")
                    payload = json.dumps({
                        "type": "frame",
                        "image": b64,
                        "width": w,
                        "height": h,
                    })
                    stale = []
                    for ws in list(CLIENTS):
                        try:
                            await ws.send_text(payload)
                        except Exception:
                            stale.append(ws)
                    for ws in stale:
                        CLIENTS.discard(ws)
                except Exception:
                    logger.exception("Failed to capture/send frame after event.")
        except Exception:
            logger.exception("Error handling event.")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
