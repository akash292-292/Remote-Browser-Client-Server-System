# Remote Playwright Viewer

This project streams a live browser session to a web client and allows users to interact with it remotely (clicks, typing, scrolling, navigation). It is built with **FastAPI**, **WebSockets**, and **Playwright**.

---

##  How to Run

### 1. Install dependencies

Make sure you have Python 3.9+ and pip installed.

```bash
pip install -r requirements.txt
```

Then install the Playwright browsers (Chromium):

```bash
python -m playwright install chromium
```

### 2. Run the server

Start the FastAPI app:

```bash
python main.py
```

This will:

* Launch a FastAPI server on [http://127.0.0.1:8000](http://127.0.0.1:8000).
* Start **two browsers** using Playwright:

  * A **visible browser** (`headless=False`) for debugging.
  * A **headless browser** (`headless=True`) for streaming frames to the client.

### 3. Open the client

In your browser, go to:

```
http://127.0.0.1:8000/
```

You will see the remote browser stream.

* Type a URL and click **Go** to navigate.
* Click inside the frame to send clicks.
* Use your keyboard to type remotely.
* Scroll with the mouse wheel.

---

##  Design Choices

1. **FastAPI + WebSockets**

   * The backend exposes a `/ws` endpoint.
   * Clients connect via WebSocket, receive periodic screenshots, and send events (clicks, keys, navigation).

2. **Two Playwright Browsers**

   * A **headless browser** captures screenshots and streams them to connected clients.
   * A **visible browser** runs in parallel for debugging and to visualize interactions locally.
   * Events from the client are applied to both browsers so they stay in sync.

3. **Screenshot Streaming**

   * A background task (`capture_loop`) captures screenshots of the headless page at \~5 FPS.
   * Images are base64-encoded JPEGs sent over the WebSocket.
   * The frontend (`client.js`) renders them inside an `<img>` element (or `<canvas>` if configured).

4. **Frontend (HTML/JS/CSS)**

   * `index.html` provides the UI: URL input, status indicator, and a frame area.
   * `client.js` manages the WebSocket connection, displays frames, and captures user input to send back.
   * `style.css` provides a clean, responsive layout.
