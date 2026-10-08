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
  const btnMcp = document.getElementById("btn-mcp");
  const mcpDrawer = document.getElementById("mcp-drawer");
  const btnCloseMcp = document.getElementById("btn-close-mcp");
  const mcpProposalsList = document.getElementById("mcp-proposals-list");
  const mcpServersList = document.getElementById("mcp-servers-list");
  const formConnectMcp = document.getElementById("form-connect-mcp");
  const mcpTransport = document.getElementById("mcp-transport");
  const rowMcpCommand = document.getElementById("row-mcp-command");
  const rowMcpUrl = document.getElementById("row-mcp-url");
  const mcpToolsList = document.getElementById("mcp-tools-list");
  const mcpToolCount = document.getElementById("mcp-tool-count");
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

  function formatMarkdown(rawText) {
    if (!rawText) return "";
    let s = rawText.trim();

    // 1. Extract code blocks first
    const codeBlocks = [];
    s = s.replace(/```([a-zA-Z0-9_\-\.]*)\n?([\s\S]*?)```/g, (_m, lang, code) => {
      const idx = codeBlocks.length;
      codeBlocks.push(`<pre><code class="language-${escapeHtml(lang)}">${escapeHtml(code.trim())}</code></pre>`);
      return `%%CODEBLOCK_${idx}%%`;
    });

    // 2. Extract inline code
    const inlineCodes = [];
    s = s.replace(/`([^`]+)`/g, (_m, code) => {
      const idx = inlineCodes.length;
      inlineCodes.push(`<code>${escapeHtml(code)}</code>`);
      return `%%INLINECODE_${idx}%%`;
    });

    // 3. Escape HTML on prose
    s = escapeHtml(s);

    // 4. Tables: parse markdown tables (| col | col |)
    s = s.replace(/((?:^|\n)[ \t]*\|[^\r\n]+\|[ \t]*(?:\r?\n[ \t]*\|[^\r\n]+\|[ \t]*)+)/g, (match) => {
      const lines = match.trim().split(/\r?\n/).map(l => l.trim()).filter(Boolean);
      if (lines.length < 2) return match;

      const sep = lines[1].replace(/\|/g, "").replace(/[ \t]/g, "");
      if (!/^[-:]+$/.test(sep)) return match;

      const parseRow = (line) => {
        let cells = line.split("|");
        if (cells.length > 0 && cells[0].trim() === "") cells.shift();
        if (cells.length > 0 && cells[cells.length - 1].trim() === "") cells.pop();
        return cells;
      };

      const headerCells = parseRow(lines[0]).map(c => `<th>${c.trim()}</th>`).join("");
      const bodyRows = lines.slice(2).map(row => {
        const cells = parseRow(row).map(c => `<td>${c.trim()}</td>`).join("");
        return `<tr>${cells}</tr>`;
      }).join("");

      return `\n<div class="table-wrapper"><table class="markdown-table"><thead><tr>${headerCells}</tr></thead><tbody>${bodyRows}</tbody></table></div>\n`;
    });

    // 5. Headings
    s = s.replace(/(?:^|\n)#### (.*$)/gim, "\n<h4>$1</h4>");
    s = s.replace(/(?:^|\n)### (.*$)/gim, "\n<h3>$1</h3>");
    s = s.replace(/(?:^|\n)## (.*$)/gim, "\n<h2>$1</h2>");
    s = s.replace(/(?:^|\n)# (.*$)/gim, "\n<h1>$1</h1>");

    // 6. Bold & Italic
    s = s.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    s = s.replace(/(^|[^*])\*([^*]+)\*/g, "$1<em>$2</em>");

    // 7. Bullet lists
    s = s.replace(/(?:^|\n)[ \t]*[-*][ \t]+(.*)/g, "\n<li>$1</li>");
    s = s.replace(/((?:<li>.*<\/li>\s*)+)/g, "<ul>$1</ul>");

    // 8. Restore inline code and code blocks
    inlineCodes.forEach((code, idx) => {
      s = s.replace(new RegExp(`%%INLINECODE_${idx}%%`, "g"), code);
    });
    codeBlocks.forEach((block, idx) => {
      s = s.replace(new RegExp(`%%CODEBLOCK_${idx}%%`, "g"), block);
    });

    // 9. Paragraphs and line breaks
    const rawParts = s.split(/\n\s*\n/);
    const formatted = rawParts.map(p => {
      const trimmed = p.trim();
      if (!trimmed) return "";
      if (
        trimmed.startsWith("<pre>") ||
        trimmed.startsWith("<ul>") ||
        trimmed.startsWith("<div") ||
        trimmed.startsWith("<h") ||
        trimmed.startsWith("<table")
      ) {
        return trimmed;
      }
      return `<p>${trimmed.replace(/\n/g, "<br>")}</p>`;
    }).filter(Boolean);

    return formatted.join("\n");
  }

  function renderMarkdown(rawText) {
    if (!rawText) return "";
    let text = rawText;

    // 1. Extract <think> reasoning block
    let thinkingBlock = "";
    text = text.replace(/<think>([\s\S]*?)<\/think>/gi, (_m, reasoning) => {
      thinkingBlock = `<div class="reasoning-box">
        <div class="reasoning-toggle" onclick="this.nextElementSibling.classList.toggle('hidden')">
          <span>🧠</span> Thinking Process (Click to toggle)
        </div>
        <div class="reasoning-body hidden">${formatMarkdown(reasoning)}</div>
      </div>`;
      return "";
    });

    // 2. Extract [DISPATCH: task] directives with placeholders
    const directives = [];
    text = text.replace(/\[DISPATCH:\s*([^\]]+)\]/gi, (_m, task) => {
      const idx = directives.length;
      directives.push(`<div class="directive-card">
        <div class="directive-header"><span class="directive-icon">⚡</span> <strong>Background Directive Dispatched</strong></div>
        <div class="directive-body">${formatMarkdown(task)}</div>
      </div>`);
      return `\n\n%%DIRECTIVE_${idx}%%\n\n`;
    });

    // 3. Extract [COMPLETED: summary] directives with placeholders
    const completions = [];
    text = text.replace(/\[COMPLETED:\s*([\s\S]*?)\](?:\n|$)/gi, (_m, summary) => {
      const idx = completions.length;
      completions.push(`<div class="completion-card">
        <div class="completion-header"><span>✅</span> <strong>Directive Completed</strong></div>
        <div class="completion-summary">${formatMarkdown(summary)}</div>
      </div>`);
      return `\n\n%%COMPLETION_${idx}%%\n\n`;
    });

    // 4. Format markdown on prose
    let rendered = formatMarkdown(text);

    // 5. Reinsert actual HTML cards
    directives.forEach((card, idx) => {
      rendered = rendered.replace(new RegExp(`(<p>\\s*)?%%DIRECTIVE_${idx}%%(\\s*<\\/p>)?`, "g"), card);
    });
    completions.forEach((card, idx) => {
      rendered = rendered.replace(new RegExp(`(<p>\\s*)?%%COMPLETION_${idx}%%(\\s*<\\/p>)?`, "g"), card);
    });

    return thinkingBlock + rendered;
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
              } else if (currentEvent === "status") {
                const statusPill = document.createElement("div");
                statusPill.className = "status-pill";
                statusPill.innerHTML = `<span>⏳</span> ${escapeHtml(data.message)}`;
                bubble.parentNode.insertBefore(statusPill, bubble);
                scrollToBottom();
              } else if (currentEvent === "job_dispatched") {
                if (data.summary) {
                  addAmbientNotice("Directive Completed", data.summary);
                }
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
  function addAmbientNotice(noticeText, detailsText = "") {
    const emptyEl = ambientList.querySelector(".ambient-empty");
    if (emptyEl) emptyEl.remove();

    const item = document.createElement("div");
    item.className = "ambient-item";
    item.innerHTML = `
      <div class="notice">🔔 ${escapeHtml(noticeText)}</div>
      ${detailsText ? `<div class="details">${formatMarkdown(detailsText)}</div>` : ""}
    `;
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
            ${n.details ? `<div class="details">${formatMarkdown(n.details)}</div>` : ""}
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

  // ---------------------------------------------------------------------------
  // Tools & MCP Management
  // ---------------------------------------------------------------------------
  async function loadMcpStatus() {
    try {
      const res = await fetch("/api/mcp/status");
      if (!res.ok) return;
      const data = await res.json();

      // 1. Proposals
      mcpProposalsList.innerHTML = "";
      if (data.proposals && data.proposals.length > 0) {
        data.proposals.forEach((p) => {
          const item = document.createElement("div");
          item.className = "mcp-item";
          item.innerHTML = `
            <div class="mcp-item-header">
              <span class="mcp-item-title">📦 ${escapeHtml(p.tool_name)}</span>
              <span class="badge-count">${escapeHtml(p.domain)}</span>
            </div>
            <div class="mcp-item-desc">${escapeHtml(p.description)}</div>
            ${p.dry_run_output ? `<div class="details">Dry Run: <code>${escapeHtml(p.dry_run_output.substring(0, 100))}</code></div>` : ""}
            <div class="mcp-actions">
              <button class="btn-approve" data-tool="${escapeHtml(p.tool_name)}">Approve & Mount</button>
              <button class="btn-reject" data-tool="${escapeHtml(p.tool_name)}">Reject</button>
            </div>
          `;
          mcpProposalsList.appendChild(item);
        });

        mcpProposalsList.querySelectorAll(".btn-approve").forEach((btn) => {
          btn.addEventListener("click", () => approveToolProposal(btn.dataset.tool));
        });
        mcpProposalsList.querySelectorAll(".btn-reject").forEach((btn) => {
          btn.addEventListener("click", () => rejectToolProposal(btn.dataset.tool));
        });
      } else {
        mcpProposalsList.innerHTML = '<div class="mcp-empty">No pending tool proposals.</div>';
      }

      // 2. Servers
      mcpServersList.innerHTML = "";
      if (data.servers && data.servers.length > 0) {
        data.servers.forEach((s) => {
          const item = document.createElement("div");
          item.className = "mcp-item";
          item.innerHTML = `
            <div class="mcp-item-header">
              <span class="mcp-item-title">⚡ ${escapeHtml(s.server_id)}</span>
              <span class="details">${s.tools.length} tools</span>
            </div>
            <div class="mcp-item-desc">${escapeHtml(s.tools.join(", ") || "No tools exported")}</div>
          `;
          mcpServersList.appendChild(item);
        });
      } else {
        mcpServersList.innerHTML = '<div class="mcp-empty">No external MCP servers connected.</div>';
      }

      // 3. Active Tools
      mcpToolsList.innerHTML = "";
      if (data.tools && data.tools.length > 0) {
        mcpToolCount.textContent = data.tools.length;
        data.tools.forEach((t) => {
          const badge = document.createElement("span");
          const tierClass = (t.tier || "").toLowerCase().replace("-", "_");
          badge.className = `mcp-badge ${tierClass}`;
          badge.textContent = t.name;
          badge.title = `Tier: ${t.tier}`;
          mcpToolsList.appendChild(badge);
        });
      } else {
        mcpToolCount.textContent = "0";
      }
    } catch (err) {
      console.warn("Failed to load MCP status:", err);
    }
  }

  async function approveToolProposal(toolName) {
    try {
      const res = await fetch(`/api/mcp/proposals/${encodeURIComponent(toolName)}/activate`, {
        method: "POST",
      });
      if (res.ok) {
        await loadMcpStatus();
      } else {
        const err = await res.json();
        alert(`Failed to activate tool: ${err.error || "Unknown error"}`);
      }
    } catch (err) {
      alert(`Activation error: ${err.message}`);
    }
  }

  async function rejectToolProposal(toolName) {
    try {
      const res = await fetch(`/api/mcp/proposals/${encodeURIComponent(toolName)}/reject`, {
        method: "POST",
      });
      if (res.ok) {
        await loadMcpStatus();
      }
    } catch (err) {
      console.warn("Rejection error:", err);
    }
  }

  // Toggle transport fields
  if (mcpTransport) {
    mcpTransport.addEventListener("change", () => {
      if (mcpTransport.value === "sse") {
        rowMcpCommand.classList.add("hidden");
        rowMcpUrl.classList.remove("hidden");
      } else {
        rowMcpCommand.classList.remove("hidden");
        rowMcpUrl.classList.add("hidden");
      }
    });
  }

  // Form submit to mount MCP server
  if (formConnectMcp) {
    formConnectMcp.addEventListener("submit", async (e) => {
      e.preventDefault();
      const serverId = document.getElementById("mcp-server-id").value.trim();
      const transport = mcpTransport.value;
      const cmd = document.getElementById("mcp-command").value.trim();
      const rawArgs = document.getElementById("mcp-args").value.trim();
      const url = document.getElementById("mcp-url").value.trim();

      const payload = {
        server_id: serverId,
        transport: transport,
        command: cmd || undefined,
        args: rawArgs ? rawArgs.split(/\s+/) : [],
        url: url || undefined,
      };

      try {
        const res = await fetch("/api/mcp/servers", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (res.ok) {
          formConnectMcp.reset();
          await loadMcpStatus();
        } else {
          const err = await res.json();
          alert(`Failed to connect MCP server: ${err.error || "Unknown error"}`);
        }
      } catch (err) {
        alert(`Connection error: ${err.message}`);
      }
    });
  }

  // MCP Drawer toggle
  if (btnMcp) {
    btnMcp.addEventListener("click", () => {
      mcpDrawer.classList.toggle("hidden");
      if (!mcpDrawer.classList.contains("hidden")) {
        loadMcpStatus();
      }
    });
  }

  if (btnCloseMcp) {
    btnCloseMcp.addEventListener("click", () => {
      mcpDrawer.classList.add("hidden");
    });
  }

  // Initial Boot
  loadSessions();
  pollHealth();
  pollAmbient();
  loadMcpStatus();
  setInterval(pollAmbient, 10000);
  setInterval(pollHealth, 30000);
})();
