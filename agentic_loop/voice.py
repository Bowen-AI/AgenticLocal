from html import escape


def voice_page_html(version: str) -> str:
    safe_version = escape(version)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>agentic-loop voice</title>
  <style>
    :root {{
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #15171a;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #1264a3;
      --danger: #b42318;
      --ok: #027a48;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }}
    main {{
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
      gap: 16px;
      min-height: 100vh;
      padding: 16px;
    }}
    section {{
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-width: 0;
    }}
    header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
    }}
    h1, h2 {{
      margin: 0;
      font-size: 16px;
      line-height: 1.3;
      letter-spacing: 0;
    }}
    .version {{
      color: var(--muted);
      font-size: 12px;
    }}
    .toolbar {{
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
    }}
    button {{
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 6px;
      min-height: 36px;
      padding: 0 12px;
      font: inherit;
      cursor: pointer;
    }}
    button.primary {{
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }}
    button:disabled {{
      opacity: 0.55;
      cursor: not-allowed;
    }}
    label {{
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 14px;
    }}
    input[type="checkbox"] {{
      width: 16px;
      height: 16px;
    }}
    form {{
      display: flex;
      gap: 8px;
      padding: 12px 16px;
      border-top: 1px solid var(--line);
    }}
    input[type="text"] {{
      flex: 1;
      min-width: 0;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 10px;
      font: inherit;
    }}
    .status {{
      padding: 10px 16px;
      min-height: 40px;
      color: var(--muted);
      border-bottom: 1px solid var(--line);
      font-size: 14px;
    }}
    .log {{
      height: calc(100vh - 190px);
      overflow: auto;
      padding: 14px 16px;
    }}
    .message {{
      display: grid;
      gap: 4px;
      padding: 10px 0;
      border-bottom: 1px solid #eef1f5;
    }}
    .role {{
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }}
    .content {{
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      line-height: 1.45;
    }}
    .timeline {{
      height: calc(100vh - 58px);
      overflow: auto;
      padding: 12px 16px;
    }}
    .step {{
      border-left: 3px solid var(--line);
      padding: 8px 0 8px 10px;
      margin: 0 0 8px;
    }}
    .step.ok {{ border-left-color: var(--ok); }}
    .step.denied {{ border-left-color: var(--danger); }}
    .step-title {{
      font-weight: 600;
      line-height: 1.35;
    }}
    .step-detail {{
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
      margin-top: 4px;
    }}
    @media (max-width: 820px) {{
      main {{
        grid-template-columns: 1fr;
      }}
      .log, .timeline {{
        height: auto;
        max-height: 52vh;
      }}
    }}
  </style>
</head>
<body>
  <main>
    <section aria-label="Voice chat">
      <header>
        <h1>agentic-loop voice</h1>
        <span class="version">v{safe_version}</span>
      </header>
      <div class="toolbar">
        <button id="listen" class="primary" type="button">Start voice</button>
        <button id="stop" type="button" disabled>Stop</button>
        <button id="clear" type="button">Clear</button>
        <label><input id="speak" type="checkbox" checked> Speak replies</label>
      </div>
      <div id="status" class="status">Voice mode is ready.</div>
      <div id="log" class="log" aria-live="polite"></div>
      <form id="textForm">
        <input id="textInput" type="text" autocomplete="off" placeholder="Type a fallback message">
        <button type="submit">Send</button>
      </form>
    </section>
    <section aria-label="Tool timeline">
      <header>
        <h2>Tool timeline</h2>
      </header>
      <div id="timeline" class="timeline"></div>
    </section>
  </main>
  <script>
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const listenButton = document.getElementById("listen");
    const stopButton = document.getElementById("stop");
    const clearButton = document.getElementById("clear");
    const speakCheckbox = document.getElementById("speak");
    const statusEl = document.getElementById("status");
    const logEl = document.getElementById("log");
    const timelineEl = document.getElementById("timeline");
    const form = document.getElementById("textForm");
    const textInput = document.getElementById("textInput");

    let sessionId = null;
    let recognition = null;
    let listening = false;

    function setStatus(text) {{
      statusEl.textContent = text;
    }}

    function appendMessage(role, content) {{
      const message = document.createElement("div");
      message.className = "message";
      const roleEl = document.createElement("div");
      roleEl.className = "role";
      roleEl.textContent = role;
      const contentEl = document.createElement("div");
      contentEl.className = "content";
      contentEl.textContent = content;
      message.append(roleEl, contentEl);
      logEl.append(message);
      logEl.scrollTop = logEl.scrollHeight;
    }}

    function renderSteps(steps) {{
      timelineEl.textContent = "";
      if (!steps || steps.length === 0) {{
        return;
      }}
      for (const step of steps) {{
        const item = document.createElement("div");
        item.className = "step " + (step.allowed === false ? "denied" : "ok");
        const title = document.createElement("div");
        title.className = "step-title";
        title.textContent = step.tool_name || step.action;
        const detail = document.createElement("div");
        detail.className = "step-detail";
        if (step.error) {{
          detail.textContent = step.error;
        }} else if (step.observation) {{
          detail.textContent = typeof step.observation === "string"
            ? step.observation
            : JSON.stringify(step.observation);
        }} else {{
          detail.textContent = step.action;
        }}
        item.append(title, detail);
        timelineEl.append(item);
      }}
    }}

    function speak(text) {{
      if (!speakCheckbox.checked || !("speechSynthesis" in window)) {{
        return;
      }}
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1;
      window.speechSynthesis.speak(utterance);
    }}

    async function sendMessage(message) {{
      appendMessage("user", message);
      setStatus("Running agent loop...");
      const response = await fetch("/chat", {{
        method: "POST",
        headers: {{"Content-Type": "application/json"}},
        body: JSON.stringify({{message, session_id: sessionId}})
      }});
      if (!response.ok) {{
        const errorText = await response.text();
        throw new Error(errorText);
      }}
      const data = await response.json();
      sessionId = data.session_id;
      appendMessage("assistant", data.final_answer);
      renderSteps(data.steps);
      speak(data.final_answer);
      setStatus("Voice mode is ready.");
    }}

    function configureRecognition() {{
      if (!SpeechRecognition) {{
        listenButton.disabled = true;
        setStatus("This browser does not expose SpeechRecognition. Use text input or Chrome/Edge.");
        return;
      }}
      recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = "en-US";
      recognition.onstart = () => {{
        listening = true;
        listenButton.disabled = true;
        stopButton.disabled = false;
        setStatus("Listening...");
      }};
      recognition.onend = () => {{
        listening = false;
        listenButton.disabled = false;
        stopButton.disabled = true;
      }};
      recognition.onerror = event => {{
        setStatus("Voice error: " + event.error);
      }};
      recognition.onresult = event => {{
        const transcript = event.results[0][0].transcript;
        sendMessage(transcript).catch(error => setStatus("Agent error: " + error.message));
      }};
    }}

    listenButton.addEventListener("click", () => {{
      if (recognition && !listening) {{
        recognition.start();
      }}
    }});
    stopButton.addEventListener("click", () => {{
      if (recognition && listening) {{
        recognition.stop();
      }}
    }});
    clearButton.addEventListener("click", () => {{
      sessionId = null;
      logEl.textContent = "";
      timelineEl.textContent = "";
      window.speechSynthesis && window.speechSynthesis.cancel();
      setStatus("Voice mode is ready.");
    }});
    form.addEventListener("submit", event => {{
      event.preventDefault();
      const message = textInput.value.trim();
      if (!message) {{
        return;
      }}
      textInput.value = "";
      sendMessage(message).catch(error => setStatus("Agent error: " + error.message));
    }});

    configureRecognition();
  </script>
</body>
</html>
"""

