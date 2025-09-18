// client.js - robust client for image or canvas frame rendering
(() => {
  // WebSocket URL (supports wss if page served over https)
  const wsProto = (location.protocol === 'https:') ? 'wss://' : 'ws://';
  const wsUrl = wsProto + location.host + '/ws';
  const ws = new WebSocket(wsUrl);

  // DOM elements (defensive)
  const statusEl = document.getElementById('status');
  const frameEl = document.getElementById('frame'); // might be img or canvas
  const urlInput = document.getElementById('url');
  const goBtn = document.getElementById('goBtn');

  if (!statusEl) console.warn('No #status element found.');
  if (!frameEl) console.error('No #frame element found. The viewer needs an <img id="frame"> or <canvas id="frame">.');

  // Detect if element is canvas or image
  const isCanvas = frameEl && frameEl.tagName && frameEl.tagName.toLowerCase() === 'canvas';
  let ctx = null;
  if (isCanvas) {
    // try to get context, but guard if canvas was not yet attached or sized
    try {
      ctx = frameEl.getContext && frameEl.getContext('2d');
      if (!ctx) {
        console.warn('Canvas exists but getContext returned null. Canvas may not be ready.');
      }
    } catch (err) {
      console.error('Error getting canvas context', err);
      ctx = null;
    }
  }

  let remoteViewport = { width: 1280, height: 720 };

  function setStatus(text) {
    if (statusEl) statusEl.textContent = text;
  }

  ws.onopen = () => {
    setStatus('Connected');
    console.info('WebSocket open:', wsUrl);
  };

  ws.onclose = (ev) => {
    setStatus('Disconnected');
    console.info('WebSocket closed', ev);
  };

  ws.onerror = (e) => {
    setStatus('Error');
    console.error('WebSocket error', e);
  };

  ws.onmessage = (event) => {
    // Event data expected to be JSON with type "meta" or "frame"
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === 'meta') {
        if (msg.viewport) remoteViewport = msg.viewport;
        console.info('meta', msg);
        // optionally update canvas size if using canvas:
        if (isCanvas && msg.viewport) {
          frameEl.width = msg.viewport.width || frameEl.width;
          frameEl.height = msg.viewport.height || frameEl.height;
          ctx = frameEl.getContext && frameEl.getContext('2d');
        }
      } else if (msg.type === 'frame') {
        if (!msg.image) return;
        // If we have a canvas and a context, draw onto canvas.
        if (isCanvas && ctx) {
          const img = new Image();
          img.onload = () => {
            // clear and draw the frame scaled to canvas size
            try {
              ctx.clearRect(0, 0, frameEl.width, frameEl.height);
              ctx.drawImage(img, 0, 0, frameEl.width, frameEl.height);
            } catch (err) {
              console.error('Error drawing image to canvas', err);
            }
          };
          img.src = "data:image/jpeg;base64," + msg.image;
        } else if (frameEl && frameEl.tagName && frameEl.tagName.toLowerCase() === 'img') {
          // set <img> src directly
          frameEl.src = "data:image/jpeg;base64," + msg.image;
        } else {
          console.warn('No valid element to render frame into.');
        }

        if (msg.width && msg.height) remoteViewport = { width: msg.width, height: msg.height };
      }
    } catch (err) {
      console.error('Failed to handle ws message', err, event.data);
    }
  };

  function sendIfOpen(obj) {
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify(obj));
      } catch (err) {
        console.error('Failed to send ws message', err, obj);
      }
    } else {
      console.warn('WebSocket not open, cannot send:', obj);
    }
  }

  function getRatiosFromEvent(evt) {
    if (!frameEl) return { x_ratio: 0, y_ratio: 0 };
    const rect = frameEl.getBoundingClientRect();
    const x = evt.clientX - rect.left;
    const y = evt.clientY - rect.top;
    return {
      x_ratio: Math.min(Math.max(x / rect.width, 0), 1),
      y_ratio: Math.min(Math.max(y / rect.height, 0), 1)
    };
  }

  // pointer/click events on frame
  if (frameEl) {
    frameEl.addEventListener('click', (e) => {
      const { x_ratio, y_ratio } = getRatiosFromEvent(e);
      sendIfOpen({ type: 'event', name: 'click', x_ratio, y_ratio });
    });

    frameEl.addEventListener('wheel', (e) => {
      e.preventDefault();
      const rect = frameEl.getBoundingClientRect();
      sendIfOpen({ type: 'event', name: 'wheel', deltaY: e.deltaY, clientHeight: rect.height });
    }, { passive: false });
  }

  // keyboard events (global)
  window.addEventListener('keydown', (e) => {
    // If focus is in the URL input, don't intercept local typing
    if (document.activeElement === urlInput) return;
    sendIfOpen({ type: 'event', name: 'key', key: e.key });
    e.preventDefault();
  });

  // navigate button
  if (goBtn) {
    goBtn.addEventListener('click', () => {
      const url = (urlInput && urlInput.value.trim()) || '';
      if (!url) return;
      sendIfOpen({ type: 'event', name: 'navigate', url });
    });
  }

  if (urlInput) {
    urlInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && goBtn) goBtn.click();
    });
  }

  // global safety: log ws current state when user presses F12 (debug)
  window.addEventListener('keydown', (e) => {
    if (e.key === 'F12') {
      console.info('WebSocket state', ws ? ws.readyState : 'no-ws');
    }
  });

  // expose for debugging from console
  window.__remoteViewer = { ws, frameEl, isCanvas, ctx, remoteViewport };
})();
