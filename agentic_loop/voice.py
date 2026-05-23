from html import escape


def voice_page_html(version: str) -> str:
    safe_version = escape(version)
    template = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>agentic-loop voice</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --ink: #15171a;
      --muted: #667085;
      --line: #d9dee7;
      --accent: #1264a3;
      --accent-soft: #e7f0f8;
      --danger: #b42318;
      --ok: #027a48;
      --warn: #b54708;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    main {
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
      gap: 16px;
      min-height: 100vh;
      padding: 16px;
    }
    section {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
      min-width: 0;
    }
    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 14px 16px;
      border-bottom: 1px solid var(--line);
    }
    h1, h2 {
      margin: 0;
      font-size: 16px;
      line-height: 1.3;
      letter-spacing: 0;
    }
    .header-meta {
      display: flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 12px;
    }
    .mode-badge {
      border: 1px solid var(--line);
      border-radius: 999px;
      padding: 3px 8px;
      background: #fff;
      color: var(--muted);
      white-space: nowrap;
    }
    .mode-badge.live {
      border-color: var(--ok);
      color: var(--ok);
      background: #ecfdf3;
    }
    .mode-badge.fallback {
      border-color: var(--warn);
      color: var(--warn);
      background: #fffaeb;
    }
    .toolbar {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
    }
    button {
      border: 1px solid var(--line);
      background: #fff;
      color: var(--ink);
      border-radius: 6px;
      min-height: 36px;
      padding: 0 12px;
      font: inherit;
      cursor: pointer;
    }
    button.primary {
      background: var(--accent);
      color: white;
      border-color: var(--accent);
    }
    button.danger {
      color: var(--danger);
      border-color: #fecdca;
      background: #fffbfa;
    }
    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }
    label {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      color: var(--muted);
      font-size: 14px;
    }
    input[type="checkbox"] {
      width: 16px;
      height: 16px;
    }
    form {
      display: flex;
      gap: 8px;
      padding: 12px 16px;
      border-top: 1px solid var(--line);
    }
    input[type="text"] {
      flex: 1;
      min-width: 0;
      min-height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 0 10px;
      font: inherit;
    }
    .status {
      padding: 10px 16px;
      min-height: 40px;
      color: var(--muted);
      border-bottom: 1px solid var(--line);
      font-size: 14px;
    }
    .log {
      height: calc(100vh - 242px);
      overflow: auto;
      padding: 14px 16px;
    }
    .message {
      display: grid;
      gap: 4px;
      padding: 10px 0;
      border-bottom: 1px solid #eef1f5;
    }
    .role {
      color: var(--muted);
      font-size: 12px;
      text-transform: uppercase;
    }
    .content {
      white-space: pre-wrap;
      overflow-wrap: anywhere;
      line-height: 1.45;
    }
    .timeline {
      height: calc(100vh - 58px);
      overflow: auto;
      padding: 12px 16px;
    }
    .registry {
      display: grid;
      gap: 12px;
      padding: 12px 16px;
      border-bottom: 1px solid var(--line);
    }
    .registry-title {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0;
      text-transform: uppercase;
      margin-bottom: 8px;
    }
    .rule-list, .workflow-list {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .rule-item {
      border: 1px solid var(--line);
      border-radius: 6px;
      min-height: 34px;
      padding: 0 10px;
      color: var(--ink);
      background: #fff;
    }
    button.workflow {
      min-height: 34px;
      padding: 0 10px;
    }
    button.workflow.active {
      border-color: var(--accent);
      color: var(--accent);
      font-weight: 700;
      background: var(--accent-soft);
    }
    .step {
      border-left: 3px solid var(--line);
      padding: 8px 0 8px 10px;
      margin: 0 0 8px;
    }
    .step.ok { border-left-color: var(--ok); }
    .step.denied { border-left-color: var(--danger); }
    .step-title {
      font-weight: 600;
      line-height: 1.35;
    }
    .step-detail {
      color: var(--muted);
      font-size: 13px;
      overflow-wrap: anywhere;
      margin-top: 4px;
    }
    @media (max-width: 820px) {
      main {
        grid-template-columns: 1fr;
      }
      .log, .timeline {
        height: auto;
        max-height: 52vh;
      }
    }
  </style>
</head>
<body>
  <main>
    <section aria-label="Voice chat">
      <header>
        <h1>agentic-loop voice</h1>
        <div class="header-meta">
          <span id="modeBadge" class="mode-badge">checking voice</span>
          <span>v__VERSION__</span>
        </div>
      </header>
      <div class="toolbar" aria-label="Live voice controls">
        <button id="connectLive" class="primary" type="button">Connect live</button>
        <button id="muteLive" type="button" disabled>Mute</button>
        <button id="interruptLive" class="danger" type="button" disabled>Interrupt</button>
        <button id="listen" type="button">Start fallback</button>
        <button id="stop" type="button" disabled>Stop</button>
        <button id="clear" type="button">Clear</button>
        <label><input id="speak" type="checkbox" checked> Speak replies</label>
      </div>
      <div id="status" class="status">Voice mode is loading.</div>
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
      <div class="registry">
        <div>
          <div class="registry-title">Rules</div>
          <div id="rules" class="rule-list"></div>
        </div>
        <div>
          <div class="registry-title">Workflows</div>
          <div id="workflows" class="workflow-list"></div>
        </div>
      </div>
      <div id="timeline" class="timeline"></div>
    </section>
  </main>
  <script>
    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    const AudioContextClass = window.AudioContext || window.webkitAudioContext;
    const connectLiveButton = document.getElementById("connectLive");
    const muteLiveButton = document.getElementById("muteLive");
    const interruptLiveButton = document.getElementById("interruptLive");
    const listenButton = document.getElementById("listen");
    const stopButton = document.getElementById("stop");
    const clearButton = document.getElementById("clear");
    const speakCheckbox = document.getElementById("speak");
    const statusEl = document.getElementById("status");
    const modeBadge = document.getElementById("modeBadge");
    const logEl = document.getElementById("log");
    const timelineEl = document.getElementById("timeline");
    const rulesEl = document.getElementById("rules");
    const workflowsEl = document.getElementById("workflows");
    const form = document.getElementById("textForm");
    const textInput = document.getElementById("textInput");

    let voiceConfig = null;
    let sessionId = null;
    let recognition = null;
    let listening = false;
    let currentWorkflow = null;
    let eventAfterId = 0;

    const live = {
      connected: false,
      muted: false,
      turnId: 0,
      inputTranscript: "",
      inputSocket: null,
      outputSocket: null,
      mediaStream: null,
      audioContext: null,
      source: null,
      processor: null,
      eventSource: null,
      playbackSources: []
    };

    function setStatus(text) {
      statusEl.textContent = text;
    }

    function setMode(text, className) {
      modeBadge.textContent = text;
      modeBadge.className = "mode-badge" + (className ? " " + className : "");
    }

    function appendMessage(role, content) {
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
    }

    function renderSteps(steps) {
      timelineEl.textContent = "";
      if (!steps || steps.length === 0) {
        return;
      }
      for (const step of steps) {
        appendTimelineStep(step.tool_name || step.action, step.error || step.observation || step.action, step.allowed === false);
      }
    }

    function appendTimelineStep(titleText, detailValue, denied) {
      const item = document.createElement("div");
      item.className = "step " + (denied ? "denied" : "ok");
      const title = document.createElement("div");
      title.className = "step-title";
      title.textContent = titleText || "event";
      const detail = document.createElement("div");
      detail.className = "step-detail";
      detail.textContent = typeof detailValue === "string" ? detailValue : JSON.stringify(detailValue);
      item.append(title, detail);
      timelineEl.append(item);
      timelineEl.scrollTop = timelineEl.scrollHeight;
    }

    function renderRules(rules) {
      rulesEl.textContent = "";
      for (const rule of rules || []) {
        const label = document.createElement("label");
        label.className = "rule-item";
        label.title = rule.description || rule.key;
        const checkbox = document.createElement("input");
        checkbox.type = "checkbox";
        checkbox.checked = Boolean(rule.enabled);
        checkbox.addEventListener("change", async () => {
          await fetch("/rules/toggle", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
              rule: rule.key,
              enabled: checkbox.checked,
              scope_type: "global",
              session_id: sessionId
            })
          });
          loadRegistries().catch(error => setStatus("Registry error: " + error.message));
        });
        label.append(checkbox, document.createTextNode(rule.label || rule.key));
        rulesEl.append(label);
      }
    }

    function renderWorkflows(workflows) {
      workflowsEl.textContent = "";
      for (const workflow of workflows || []) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "workflow" + (currentWorkflow === workflow.key ? " active" : "");
        button.textContent = workflow.command || ("/" + workflow.key);
        button.title = workflow.description || workflow.key;
        button.addEventListener("click", async () => {
          const response = await fetch("/workflows/start", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({workflow: workflow.key, session_id: sessionId})
          });
          const data = await response.json();
          if (!response.ok) {
            setStatus(data.message || data.error || "Workflow unavailable");
            return;
          }
          currentWorkflow = workflow.key;
          sessionId = data.session_id || sessionId;
          renderWorkflows(workflows);
          setStatus("Workflow active: " + (workflow.command || workflow.key));
        });
        workflowsEl.append(button);
      }
    }

    async function loadVoiceConfig() {
      const response = await fetch("/voice/config");
      voiceConfig = await response.json();
      if (voiceConfig.live_available) {
        setMode("Gemini Live ready", "live");
        setStatus("Live voice is ready.");
      } else {
        connectLiveButton.disabled = true;
        setMode("browser fallback", "fallback");
        setStatus(voiceConfig.unavailable_reason || "Live voice unavailable. Browser fallback is ready.");
      }
    }

    async function loadRegistries() {
      const rulesResponse = await fetch("/registry/rules" + (sessionId ? "?session_id=" + encodeURIComponent(sessionId) : ""));
      const workflowResponse = await fetch("/registry/workflows");
      if (rulesResponse.ok) {
        const data = await rulesResponse.json();
        renderRules(data.rules);
      }
      if (workflowResponse.ok) {
        const data = await workflowResponse.json();
        renderWorkflows(data.workflows);
      }
    }

    async function ensureSession() {
      if (sessionId) {
        return sessionId;
      }
      const response = await fetch("/sessions", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({})
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.message || data.error || "Could not create session");
      }
      sessionId = data.session_id;
      await loadRegistries();
      return sessionId;
    }

    async function requestGeminiToken(purpose) {
      const response = await fetch("/voice/gemini/token", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({purpose, session_id: sessionId})
      });
      const data = await response.json();
      if (!response.ok) {
        throw new Error(data.message || data.error || "Could not create Gemini Live token");
      }
      sessionId = data.session_id || sessionId;
      return data;
    }

    function tokenWebSocketUrl(tokenPayload) {
      const separator = tokenPayload.websocket_url.includes("?") ? "&" : "?";
      return tokenPayload.websocket_url + separator + "access_token=" + encodeURIComponent(tokenPayload.token);
    }

    function openGeminiSocket(purpose, onMessage) {
      return requestGeminiToken(purpose).then(tokenPayload => new Promise((resolve, reject) => {
        const socket = new WebSocket(tokenWebSocketUrl(tokenPayload));
        const timer = window.setTimeout(() => reject(new Error("Gemini Live setup timed out")), 10000);
        socket.addEventListener("open", () => {
          socket.send(JSON.stringify({setup: tokenPayload.setup}));
        });
        socket.addEventListener("message", event => {
          let data = null;
          try {
            data = JSON.parse(event.data);
          } catch (error) {
            return;
          }
          if (data.setupComplete) {
            window.clearTimeout(timer);
            resolve(socket);
            return;
          }
          onMessage(data);
        });
        socket.addEventListener("error", () => {
          window.clearTimeout(timer);
          reject(new Error("Gemini Live WebSocket failed"));
        });
        socket.addEventListener("close", () => {
          if (live.connected) {
            setStatus("Gemini Live disconnected.");
            disconnectLive();
          }
        });
      }));
    }

    async function connectLive() {
      if (live.connected) {
        disconnectLive();
        return;
      }
      if (!voiceConfig || !voiceConfig.live_available) {
        setStatus((voiceConfig && voiceConfig.unavailable_reason) || "Gemini Live is not available.");
        return;
      }
      if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia || !window.WebSocket || !AudioContextClass) {
        setStatus("Live voice needs microphone, WebSocket, and AudioContext support.");
        return;
      }
      setStatus("Connecting Gemini Live...");
      await ensureSession();
      live.inputSocket = await openGeminiSocket("input", handleInputGeminiMessage);
      live.outputSocket = await openGeminiSocket("output", handleOutputGeminiMessage);
      live.mediaStream = await navigator.mediaDevices.getUserMedia({audio: true});
      live.audioContext = new AudioContextClass();
      live.source = live.audioContext.createMediaStreamSource(live.mediaStream);
      live.processor = live.audioContext.createScriptProcessor(4096, 1, 1);
      live.processor.onaudioprocess = event => {
        if (!live.connected || live.muted || !socketReady(live.inputSocket)) {
          return;
        }
        const input = event.inputBuffer.getChannelData(0);
        const pcm = downsampleToPcm16(input, live.audioContext.sampleRate, 16000);
        live.inputSocket.send(JSON.stringify({
          realtimeInput: {
            audio: {
              data: arrayBufferToBase64(pcm.buffer),
              mimeType: "audio/pcm;rate=16000"
            }
          }
        }));
      };
      live.source.connect(live.processor);
      live.processor.connect(live.audioContext.destination);
      live.connected = true;
      connectLiveButton.textContent = "Disconnect live";
      muteLiveButton.disabled = false;
      interruptLiveButton.disabled = false;
      listenButton.disabled = true;
      setMode("Gemini Live connected", "live");
      setStatus("Listening live...");
    }

    function disconnectLive() {
      stopEventStream();
      stopPlayback();
      if (live.processor) {
        live.processor.disconnect();
      }
      if (live.source) {
        live.source.disconnect();
      }
      if (live.mediaStream) {
        for (const track of live.mediaStream.getTracks()) {
          track.stop();
        }
      }
      closeSocket(live.inputSocket);
      closeSocket(live.outputSocket);
      live.connected = false;
      live.muted = false;
      live.inputTranscript = "";
      live.inputSocket = null;
      live.outputSocket = null;
      live.mediaStream = null;
      live.audioContext = null;
      live.source = null;
      live.processor = null;
      connectLiveButton.textContent = "Connect live";
      muteLiveButton.textContent = "Mute";
      muteLiveButton.disabled = true;
      interruptLiveButton.disabled = true;
      listenButton.disabled = Boolean(voiceConfig && voiceConfig.live_available && !SpeechRecognition);
      setMode(voiceConfig && voiceConfig.live_available ? "Gemini Live ready" : "browser fallback", voiceConfig && voiceConfig.live_available ? "live" : "fallback");
      setStatus("Voice mode is ready.");
    }

    function closeSocket(socket) {
      if (socket && socket.readyState <= WebSocket.OPEN) {
        socket.close();
      }
    }

    function socketReady(socket) {
      return socket && socket.readyState === WebSocket.OPEN;
    }

    function toggleMute() {
      live.muted = !live.muted;
      muteLiveButton.textContent = live.muted ? "Unmute" : "Mute";
      if (live.muted && socketReady(live.inputSocket)) {
        live.inputSocket.send(JSON.stringify({realtimeInput: {audioStreamEnd: true}}));
      }
      setStatus(live.muted ? "Live microphone muted." : "Listening live...");
    }

    function interruptLive() {
      live.turnId += 1;
      live.inputTranscript = "";
      stopPlayback();
      if (socketReady(live.inputSocket)) {
        live.inputSocket.send(JSON.stringify({realtimeInput: {audioStreamEnd: true}}));
      }
      setStatus("Interrupted. Listening live...");
    }

    function handleInputGeminiMessage(data) {
      const content = data.serverContent || {};
      if (content.inputTranscription && content.inputTranscription.text) {
        live.inputTranscript += content.inputTranscription.text;
      }
      if (content.interrupted) {
        stopPlayback();
      }
      if (content.turnComplete) {
        const transcript = live.inputTranscript.trim();
        live.inputTranscript = "";
        if (transcript) {
          sendLiveTranscript(transcript).catch(error => setStatus("Agent error: " + error.message));
        }
      }
    }

    function handleOutputGeminiMessage(data) {
      const content = data.serverContent || {};
      if (content.interrupted) {
        stopPlayback();
        return;
      }
      const parts = (content.modelTurn && content.modelTurn.parts) || [];
      for (const part of parts) {
        const inlineData = part.inlineData || part.inline_data;
        if (inlineData && inlineData.data && speakCheckbox.checked) {
          playPcm24(inlineData.data);
        }
      }
    }

    async function sendLiveTranscript(transcript) {
      const turnId = ++live.turnId;
      appendMessage("user", transcript);
      setStatus("Running agent loop...");
      startEventStream();
      const data = await postChatMessage(transcript);
      if (turnId !== live.turnId) {
        return;
      }
      appendMessage("assistant", data.final_answer);
      renderSteps(data.steps);
      await speakWithGemini(data.final_answer);
      stopEventStream();
      setStatus(live.connected ? "Listening live..." : "Voice mode is ready.");
    }

    async function postChatMessage(message) {
      const response = await fetch("/chat", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({message, session_id: sessionId, workflow: currentWorkflow})
      });
      if (!response.ok) {
        const errorText = await response.text();
        throw new Error(errorText);
      }
      const data = await response.json();
      sessionId = data.session_id;
      loadRegistries().catch(error => setStatus("Registry error: " + error.message));
      return data;
    }

    async function speakWithGemini(text) {
      if (!speakCheckbox.checked || !socketReady(live.outputSocket)) {
        return;
      }
      live.outputSocket.send(JSON.stringify({
        clientContent: {
          turns: [{
            role: "user",
            parts: [{text: "Speak exactly this text and nothing else: " + text}]
          }],
          turnComplete: true
        }
      }));
    }

    function startEventStream() {
      stopEventStream();
      if (!sessionId || !window.EventSource) {
        return;
      }
      const url = "/events?follow=1&timeout=30&session_id=" + encodeURIComponent(sessionId) + "&after=" + eventAfterId;
      live.eventSource = new EventSource(url);
      for (const name of ["run_started", "tool_requested", "tool_result", "approval_required", "final_answer"]) {
        live.eventSource.addEventListener(name, handleAgentEvent);
      }
    }

    function handleAgentEvent(event) {
      const data = JSON.parse(event.data);
      eventAfterId = Math.max(eventAfterId, Number(data.id || 0));
      if (data.event_type === "tool_requested") {
        appendTimelineStep(data.payload.tool, data.payload.arguments, data.payload.allowed === false);
      } else if (data.event_type === "tool_result") {
        appendTimelineStep(data.payload.tool, data.payload.result, false);
      } else if (data.event_type === "approval_required") {
        appendTimelineStep(data.payload.tool, data.payload.reason, true);
      }
    }

    function stopEventStream() {
      if (live.eventSource) {
        live.eventSource.close();
        live.eventSource = null;
      }
    }

    function speak(text) {
      if (!speakCheckbox.checked || !("speechSynthesis" in window)) {
        return;
      }
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.rate = 1;
      window.speechSynthesis.speak(utterance);
    }

    async function sendMessage(message) {
      appendMessage("user", message);
      setStatus("Running agent loop...");
      const data = await postChatMessage(message);
      appendMessage("assistant", data.final_answer);
      renderSteps(data.steps);
      speak(data.final_answer);
      setStatus("Voice mode is ready.");
    }

    function configureRecognition() {
      if (!SpeechRecognition) {
        listenButton.disabled = true;
        if (!voiceConfig || !voiceConfig.live_available) {
          setStatus("This browser does not expose SpeechRecognition. Use text input or Chrome/Edge.");
        }
        return;
      }
      recognition = new SpeechRecognition();
      recognition.continuous = false;
      recognition.interimResults = false;
      recognition.lang = "en-US";
      recognition.onstart = () => {
        listening = true;
        listenButton.disabled = true;
        stopButton.disabled = false;
        setStatus("Listening with browser fallback...");
      };
      recognition.onend = () => {
        listening = false;
        listenButton.disabled = live.connected;
        stopButton.disabled = true;
      };
      recognition.onerror = event => {
        setStatus("Voice error: " + event.error);
      };
      recognition.onresult = event => {
        const transcript = event.results[0][0].transcript;
        sendMessage(transcript).catch(error => setStatus("Agent error: " + error.message));
      };
    }

    function downsampleToPcm16(input, inputRate, outputRate) {
      if (inputRate === outputRate) {
        return floatToPcm16(input);
      }
      const ratio = inputRate / outputRate;
      const outputLength = Math.floor(input.length / ratio);
      const output = new Float32Array(outputLength);
      for (let i = 0; i < outputLength; i += 1) {
        output[i] = input[Math.floor(i * ratio)];
      }
      return floatToPcm16(output);
    }

    function floatToPcm16(input) {
      const output = new Int16Array(input.length);
      for (let i = 0; i < input.length; i += 1) {
        const sample = Math.max(-1, Math.min(1, input[i]));
        output[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
      }
      return output;
    }

    function arrayBufferToBase64(buffer) {
      const bytes = new Uint8Array(buffer);
      let binary = "";
      for (let i = 0; i < bytes.byteLength; i += 1) {
        binary += String.fromCharCode(bytes[i]);
      }
      return btoa(binary);
    }

    function playPcm24(base64Audio) {
      if (!live.audioContext) {
        return;
      }
      const binary = atob(base64Audio);
      const samples = new Int16Array(binary.length / 2);
      for (let i = 0; i < samples.length; i += 1) {
        const lo = binary.charCodeAt(i * 2);
        const hi = binary.charCodeAt(i * 2 + 1);
        const value = (hi << 8) | lo;
        samples[i] = value >= 0x8000 ? value - 0x10000 : value;
      }
      const audioBuffer = live.audioContext.createBuffer(1, samples.length, 24000);
      const channel = audioBuffer.getChannelData(0);
      for (let i = 0; i < samples.length; i += 1) {
        channel[i] = samples[i] / 0x8000;
      }
      const source = live.audioContext.createBufferSource();
      source.buffer = audioBuffer;
      source.connect(live.audioContext.destination);
      source.addEventListener("ended", () => {
        live.playbackSources = live.playbackSources.filter(item => item !== source);
      });
      live.playbackSources.push(source);
      source.start();
    }

    function stopPlayback() {
      for (const source of live.playbackSources) {
        try {
          source.stop();
        } catch (error) {
          // Already stopped.
        }
      }
      live.playbackSources = [];
      window.speechSynthesis && window.speechSynthesis.cancel();
    }

    connectLiveButton.addEventListener("click", () => {
      connectLive().catch(error => setStatus("Live voice error: " + error.message));
    });
    muteLiveButton.addEventListener("click", toggleMute);
    interruptLiveButton.addEventListener("click", interruptLive);
    listenButton.addEventListener("click", () => {
      if (recognition && !listening) {
        recognition.start();
      }
    });
    stopButton.addEventListener("click", () => {
      if (recognition && listening) {
        recognition.stop();
      }
    });
    clearButton.addEventListener("click", () => {
      sessionId = null;
      currentWorkflow = null;
      eventAfterId = 0;
      logEl.textContent = "";
      timelineEl.textContent = "";
      stopPlayback();
      if (live.connected) {
        disconnectLive();
      }
      setStatus("Voice mode is ready.");
      loadRegistries().catch(error => setStatus("Registry error: " + error.message));
    });
    form.addEventListener("submit", event => {
      event.preventDefault();
      const message = textInput.value.trim();
      if (!message) {
        return;
      }
      textInput.value = "";
      sendMessage(message).catch(error => setStatus("Agent error: " + error.message));
    });

    loadVoiceConfig()
      .catch(error => {
        connectLiveButton.disabled = true;
        setMode("browser fallback", "fallback");
        setStatus("Voice config error: " + error.message);
      })
      .finally(() => {
        configureRecognition();
        loadRegistries().catch(error => setStatus("Registry error: " + error.message));
      });
  </script>
</body>
</html>
"""
    return template.replace("__VERSION__", safe_version)
