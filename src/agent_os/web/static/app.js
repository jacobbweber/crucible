/**
 * Agent OS — Local Companion Web UI Client
 * Handles real-time SSE streaming, sessions, reasoning accordions, and ambient nudges.
 */

(() => {
  let currentSessionId = null;
  let isStreaming = false;

  // DOM Elements
  const sessionList = document.getElementById("session-list");
  const btnNewChat = document.getElementById("btn-new-chat");
  const chatTitle = document.getElementById("chat-title");
  const chatStream = document.getElementById("chat-stream");
  const messagesContainer = document.getElementById("messages-container");
  const starterContainer = document.getElementById("starter-container");
  const chatInput = document.getElementById("chat-input");
  const btnSend = document.getElementById("btn-send");
  const healthDot = document.getElementById("health-dot");
  const healthText = document.getElementById("health-text");
  const btnAmbient = document.getElementById("btn-ambient");
  const ambientBadge = document.getElementById("ambient-badge");
  const ambientDrawer = document.getElementById("ambient-drawer");
  const btnCloseAmbient = document.getElementById("btn-close-ambient");
  const ambientList = document.getElementById("ambient-list");
  const sidebar = document.getElementById("sidebar");
  const btnMenuToggle = document.getElementById("btn-menu-toggle");

  // ---------------------------------------------------------------------------
  // Markdown & Text Formatter
  // ---------------------------------------------------------------------------
  function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text;
    return div.innerHTML;
  }

  function renderMarkdown(rawText) {
    if (!rawText) return "";
    let html = escapeHtml(rawText);

    // Code blocks: ```code```
    html = html.replace(/```([a-zA-Z0-9_\-\.]*)\n([\s\S]*?)```/g, (_m, lang, code) => {
      return `<pre><code class="language-${lang}">${code.trim()}</code></pre>`;
    });

    // Inline code: `code`
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

    // Bold: **text**
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

    // Headings: ###, ##, #
    html = html.replace(/^### (.*$)/gim, "<h3>$1</h3>");
    html = html.replace(/^## (.*$)/gim, "<h2>$1</h2>");
    html = html.replace(/^# (.*$)/gim, "<h1>$1</h1>");

    // Bullet lists: * or -
    html = html.replace(/^\s*[-*]\s+(.*)$/gim, "<li>$1</li>");
    html = html.replace(/(<li>[\s\S]*?<\/li>)/g, "<ul>$1</ul>");
    html = html.replace(/<\/ul>\s*<ul>/g, "");

    // Line breaks (convert remaining single newlines to <br> unless inside pre/ul)
    html = html.split("\n\n").map(para => {
      if (para.startsWith("<pre>") || para.startsWith("<ul>") || para.startsWith("<h")) {
        return para;
      }
      return `<p>${para.replace(/\n/g, "<br>")}</p>`;
    }).join("");

    return html;
  }

  // ---------------------------------------------------------------------------
  // Session Management
  // ---------------------------------------------------------------------------
  async function loadSessions() {
    try {
      const res = await fetch("/api/sessions");
      if (!res.ok) return;
      const sessions = await res.json();
      sessionList.innerHTML = "";

      if (sessions.length === 0) {
        await createNewSession("Initial Chat");
        return;
      }

      sessions.forEach((s) => {
        const li = document.createElement("li");
        li.className = `session-item ${s.session_id === currentSessionId ? "active" : ""}`;
        li.textContent = s.title || "Untitled Session";
        li.dataset.sessionId = s.session_id;
        li.addEventListener("click", () => switchSession(s.session_id, s.title));
        sessionList.appendChild(li);
      });

      if (!currentSessionId && sessions.length > 0) {
        switchSession(sessions[0].session_id, sessions[0].title);
      }
    } catch (err) {
      console.error("Failed to load sessions:", err);
    }
  }

  async function createNewSession(title = "New Conversation") {
    try {
      const res = await fetch("/api/sessions", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title }),
      });
      if (!res.ok) return;
      const data = await res.json();
      await switchSession(data.session_id, data.title);
      await loadSessions();
    } catch (err) {
      console.error("Failed to create session:", err);
    }
  }

  async function switchSession(sessionId, title) {
    currentSessionId = sessionId;
    chatTitle.textContent = title || "Conversation";
    chatStream.innerHTML = "";

    // Update active highlight
    document.querySelectorAll(".session-item").forEach((el) => {
      el.classList.toggle("active", el.dataset.sessionId === sessionId);
    });

    // Close mobile menu if open
    sidebar.classList.remove("open");

    // Load turns
    try {
      const res = await fetch(`/api/sessions/${sessionId}/turns`);
      if (res.ok) {
        const turns = await res.json();
        if (turns.length > 0) {
          starterContainer.classList.add("hidden");
          turns.forEach((turn) => {
            if (turn.role === "user") {
              appendMessageBubble("user", turn.content);
            } else if (turn.role === "assistant") {
              appendMessageBubble("assistant", turn.content);
            }
          });
          scrollToBottom();
        } else {
          starterContainer.classList.remove("hidden");
        }
      }
    } catch (err) {
      console.error("Failed to load session turns:", err);
    }
  }

  // ---------------------------------------------------------------------------
  // Message Bubbles & Rendering
  // ---------------------------------------------------------------------------
  function appendMessageBubble(role, content) {
    const row = document.createElement("div");
    row.className = `message-row ${role}`;

    const sender = document.createElement("div");
    sender.className = "message-sender";
    sender.textContent = role === "user" ? "You" : "Companion";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble";
    bubble.innerHTML = renderMarkdown(content);

    row.appendChild(sender);
    row.appendChild(bubble);
    chatStream.appendChild(row);
    scrollToBottom();
    return bubble;
  }

  function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }

  // ---------------------------------------------------------------------------
  // Streaming Turn Execution (SSE)
  // ---------------------------------------------------------------------------
  async function sendMessage(userText) {
    if (!userText || isStreaming) return;
    if (!currentSessionId) {
      await createNewSession("New Conversation");
    }

    isStreaming = true;
    btnSend.disabled = true;
    chatInput.value = "";
    chatInput.style.height = "auto";
    starterContainer.classList.add("hidden");

    // 1. Render User Bubble
    appendMessageBubble("user", userText);

    // 2. Prepare Assistant Bubble
    const row = document.createElement("div");
    row.className = "message-row assistant";

    const sender = document.createElement("div");
    sender.className = "message-sender";
    sender.textContent = "Companion";

    const bubble = document.createElement("div");
    bubble.className = "message-bubble stream-cursor";

    row.appendChild(sender);
    row.appendChild(bubble);
    chatStream.appendChild(row);
    scrollToBottom();

    let fullDelta = "";
    let fullReasoning = "";
    let reasoningBox = null;
    let reasoningBody = null;

    try {
      const response = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: currentSessionId, message: userText }),
      });

      if (!response.ok || !response.body) {
        bubble.innerHTML = "<em>Error initiating response stream.</em>";
        bubble.classList.remove("stream-cursor");
        isStreaming = false;
        btnSend.disabled = false;
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop(); // keep last incomplete line

        let currentEvent = null;

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.substring(7).trim();
          } else if (line.startsWith("data: ")) {
            const dataStr = line.substring(6).trim();
            if (!dataStr) continue;

            try {
              const data = JSON.parse(dataStr);

              if (currentEvent === "delta") {
                fullDelta += data.delta;
                bubble.innerHTML = renderMarkdown(fullDelta);
                scrollToBottom();
              } else if (currentEvent === "thinking") {
                fullReasoning += data.reasoning;
                if (!reasoningBox) {
                  reasoningBox = document.createElement("div");
                  reasoningBox.className = "reasoning-box";
                  const toggle = document.createElement("div");
                  toggle.className = "reasoning-toggle";
                  toggle.innerHTML = "<span>🧠</span> Thinking Process (Click to toggle)";
                  reasoningBody = document.createElement("div");
                  reasoningBody.className = "reasoning-body";
                  toggle.addEventListener("click", () => {
                    reasoningBody.classList.toggle("hidden");
                  });
                  reasoningBox.appendChild(toggle);
                  reasoningBox.appendChild(reasoningBody);
                  bubble.parentNode.insertBefore(reasoningBox, bubble);
                }
                if (reasoningBody) {
                  reasoningBody.textContent = fullReasoning;
                }
                scrollToBottom();
              } else if (currentEvent === "tool_executed") {
                const toolPill = document.createElement("div");
                toolPill.className = "tool-pill";
                toolPill.innerHTML = `<span>🔧</span> Executed tool: <strong>${escapeHtml(data.tool_name)}</strong>`;
                bubble.parentNode.insertBefore(toolPill, bubble);
                scrollToBottom();
              } else if (currentEvent === "job_dispatched") {
                const jobPill = document.createElement("div");
                jobPill.className = "tool-pill";
                jobPill.innerHTML = `<span>⚡</span> Dispatched background directive: <strong>${escapeHtml(data.task)}</strong>`;
                bubble.parentNode.insertBefore(jobPill, bubble);
                scrollToBottom();
              } else if (currentEvent === "ambient_nudge") {
                addAmbientNotice(data.notice);
              } else if (currentEvent === "error") {
                bubble.innerHTML += `<p class="error-text">⚠️ Error: ${escapeHtml(data.error)}</p>`;
              }
            } catch (parseErr) {
              console.warn("Failed to parse SSE JSON chunk:", dataStr);
            }
          }
        }
      }
    } catch (streamErr) {
      console.error("Stream connection failed:", streamErr);
      bubble.innerHTML += "<p><em>Connection interrupted.</em></p>";
    } finally {
      bubble.classList.remove("stream-cursor");
      isStreaming = false;
      btnSend.disabled = false;
      chatInput.focus();
      pollAmbient();
      loadSessions(); // Update session list timestamp
    }
  }

  // ---------------------------------------------------------------------------
  // Ambient Notifications & Health Polling
  // ---------------------------------------------------------------------------
  function addAmbientNotice(noticeText) {
    const emptyEl = ambientList.querySelector(".ambient-empty");
    if (emptyEl) emptyEl.remove();

    const item = document.createElement("div");
    item.className = "ambient-item";
    item.innerHTML = `<div class="notice">🔔 ${escapeHtml(noticeText)}</div>`;
    ambientList.prepend(item);

    const currentCount = parseInt(ambientBadge.textContent || "0", 10) + 1;
    ambientBadge.textContent = currentCount;
    ambientBadge.classList.remove("hidden");
  }

  async function pollAmbient() {
    try {
      const res = await fetch("/api/ambient");
      if (!res.ok) return;
      const nudges = await res.json();
      if (nudges.length > 0) {
        ambientBadge.textContent = nudges.length;
        ambientBadge.classList.remove("hidden");
        ambientList.innerHTML = "";
        nudges.forEach((n) => {
          const item = document.createElement("div");
          item.className = "ambient-item";
          item.innerHTML = `
            <div class="notice">🔔 ${escapeHtml(n.short_notice)}</div>
            ${n.details ? `<div class="details">${escapeHtml(n.details)}</div>` : ""}
          `;
          ambientList.appendChild(item);
        });
      }
    } catch (err) {
      console.warn("Failed to poll ambient nudges:", err);
    }
  }

  async function pollHealth() {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) return;
      const health = await res.json();
      healthText.textContent = `Health: ${health.health_score}%`;
      healthDot.className = `health-dot ${health.health_score < 80 ? "warning" : ""}`;
    } catch (err) {
      healthText.textContent = "Health: Offline";
      healthDot.className = "health-dot warning";
    }
  }

  // ---------------------------------------------------------------------------
  // Event Listeners & Initialization
  // ---------------------------------------------------------------------------
  btnNewChat.addEventListener("click", () => createNewSession("New Conversation"));

  btnSend.addEventListener("click", () => {
    sendMessage(chatInput.value.trim());
  });

  chatInput.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      sendMessage(chatInput.value.trim());
    }
  });

  // Auto-resize input
  chatInput.addEventListener("input", () => {
    chatInput.style.height = "auto";
    chatInput.style.height = Math.min(chatInput.scrollHeight, 180) + "px";
  });

  // Ambient drawer toggle
  btnAmbient.addEventListener("click", () => {
    ambientDrawer.classList.toggle("hidden");
    if (!ambientDrawer.classList.contains("hidden")) {
      ambientBadge.classList.add("hidden");
      ambientBadge.textContent = "0";
    }
  });

  btnCloseAmbient.addEventListener("click", () => {
    ambientDrawer.classList.add("hidden");
  });

  // Mobile menu toggle
  btnMenuToggle.addEventListener("click", () => {
    sidebar.classList.toggle("open");
  });

  // Starter card clicks
  document.querySelectorAll(".starter-card").forEach((card) => {
    card.addEventListener("click", () => {
      const prompt = card.dataset.prompt;
      if (prompt) {
        sendMessage(prompt);
      }
    });
  });

  // Initial Boot
  loadSessions();
  pollHealth();
  pollAmbient();
  setInterval(pollAmbient, 10000);
  setInterval(pollHealth, 30000);
})();
