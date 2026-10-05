const $ = (selector) => document.querySelector(selector);
let conversationId = null;
let csrfToken = null;
// Chặn gửi trùng (Enter liên tục) và bỏ qua phản hồi đến muộn sau khi người
// dùng đã chuyển sang phiên khác.
let sending = false;
let viewVersion = 0;

async function api(url, options = {}) {
  const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
  if (csrfToken && !["GET", "HEAD"].includes((options.method || "GET").toUpperCase())) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  const response = await fetch(url, {
    ...options,
    headers,
  });
  const raw = await response.text();
  let data;
  try {
    data = raw ? JSON.parse(raw) : {};
  } catch {
    data = { detail: raw || "Lỗi phản hồi" };
  }
  if (!response.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map((item) => item.msg).join("; ")
      : data.detail;
    throw new Error(detail || "Yêu cầu thất bại");
  }
  return data;
}

function showApp(on) {
  $("#loginView").classList.toggle("hidden", on);
  $("#appView").classList.toggle("hidden", !on);
  if (on) {
    $("#sendBtn").disabled = true;
    initializeSession();
  }
}

async function initializeSession() {
  try {
    const data = await api("/api/auth/session");
    csrfToken = data.csrf_token;
    await Promise.all([refresh(), health()]);
    $("#sendBtn").disabled = false;
  } catch {
    csrfToken = null;
    showApp(false);
  }
}

async function login() {
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({
        username: $("#username").value,
        password: $("#password").value,
      }),
    });
    csrfToken = data.csrf_token;
    $("#loginError").textContent = "";
    showApp(true);
  } catch (error) {
    $("#loginError").textContent = error.message;
  }
}

// Markdown tối giản cho phản hồi AI. Chỉ tạo phần tử bằng DOM và textContent,
// không dùng innerHTML, nên nội dung từ AI không thể chèn HTML/script.
function appendInline(parent, text) {
  const pattern = /(\*\*[^*]+\*\*|`[^`]+`|\*[^*\s][^*]*\*)/g;
  let last = 0;
  for (const match of text.matchAll(pattern)) {
    if (match.index > last) parent.append(text.slice(last, match.index));
    const token = match[0];
    let node;
    if (token.startsWith("**")) {
      node = document.createElement("strong");
      appendInline(node, token.slice(2, -2));
    } else if (token.startsWith("`")) {
      node = document.createElement("code");
      node.textContent = token.slice(1, -1);
    } else {
      node = document.createElement("em");
      appendInline(node, token.slice(1, -1));
    }
    parent.append(node);
    last = match.index + token.length;
  }
  if (last < text.length) parent.append(text.slice(last));
}

function renderMarkdown(text) {
  const root = document.createElement("div");
  root.className = "md";
  const lines = text.split("\n");
  let list = null;
  let i = 0;
  while (i < lines.length) {
    const line = lines[i].trim();
    const bullet = line.match(/^[-*+]\s+(.*)$/);
    const numbered = line.match(/^\d+[.)]\s+(.*)$/);
    if (!bullet && !numbered) list = null;
    if (!line) {
      i += 1;
      continue;
    }
    if (/^(-{3,}|\*{3,}|_{3,})$/.test(line)) {
      root.append(document.createElement("hr"));
    } else if (line.startsWith("|")) {
      const table = document.createElement("table");
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        const cells = lines[i].trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
        if (!cells.every((c) => /^:?-{2,}:?$/.test(c))) {
          const row = document.createElement("tr");
          cells.forEach((cell) => {
            const td = document.createElement(table.rows.length ? "td" : "th");
            appendInline(td, cell);
            row.append(td);
          });
          table.append(row);
        }
        i += 1;
      }
      root.append(table);
      continue;
    } else if (/^#{1,6}\s/.test(line)) {
      const level = Math.min(line.match(/^#+/)[0].length + 2, 6);
      const heading = document.createElement(`h${level}`);
      appendInline(heading, line.replace(/^#+\s*/, ""));
      root.append(heading);
    } else if (bullet || numbered) {
      const tag = bullet ? "ul" : "ol";
      if (!list || list.tagName.toLowerCase() !== tag) {
        list = document.createElement(tag);
        root.append(list);
      }
      const item = document.createElement("li");
      appendInline(item, (bullet || numbered)[1]);
      list.append(item);
    } else {
      const paragraph = document.createElement("p");
      appendInline(paragraph, line);
      root.append(paragraph);
    }
    i += 1;
  }
  return root;
}

function addMessage(role, text, meta = "") {
  const box = document.createElement("div");
  box.className = `message ${role}`;
  let content;
  if (role === "assistant") {
    content = renderMarkdown(text);
  } else {
    content = document.createElement("div");
    content.textContent = text;
  }
  box.appendChild(content);
  if (meta) {
    const info = document.createElement("div");
    info.className = "meta";
    info.textContent = meta;
    box.appendChild(info);
  }
  $("#messages").appendChild(box);
  $("#messages").scrollTop = $("#messages").scrollHeight;
}

function showAnalysis(data) {
  const element = $("#analysis");
  element.className = `analysis${data.action === "block" ? " block" : ""}`;
  const types = (data.detections || []).map((item) => item.kind).join(", ") || "Không có";
  element.textContent = `Policy: ${data.action.toUpperCase()} · ${data.reason} · PII: ${types}`;
  element.classList.remove("hidden");
}

async function send() {
  if (sending) return;
  if (!csrfToken) {
    addMessage("assistant", "Phiên đăng nhập chưa sẵn sàng, vui lòng đăng nhập lại.");
    return;
  }
  const prompt = $("#prompt").value.trim();
  if (!prompt) return;

  const wasNewConversation = conversationId === null;
  const version = viewVersion;
  sending = true;
  const welcome = $("#messages .welcome");
  if (welcome) welcome.remove();

  $("#sendBtn").disabled = true;
  addMessage("user", prompt);
  $("#prompt").value = "";

  try {
    const data = await api("/api/chat", {
      method: "POST",
      body: JSON.stringify({
        prompt,
        conversation_id: conversationId,
        remember: $("#remember").checked,
        use_cross_session_memory: $("#crossMemory").checked,
      }),
    });
    if (version !== viewVersion) return;
    showAnalysis(data);

    if (data.status === "blocked") {
      addMessage("assistant", "Yêu cầu đã bị chặn trước khi gọi AI.");
    } else {
      conversationId = data.conversation_id;
      if (wasNewConversation) {
        $("#chatTitle").textContent = data.conversation_title || "Phiên không lưu";
      }
      const fallback = data.fallback_reason ? ` · fallback ${data.fallback_reason}` : "";
      const memory = data.cross_session_memory_used
        ? ` · nhớ ${data.cross_session_memory_used} mục từ phiên khác`
        : "";
      addMessage(
        "assistant",
        data.response,
        `${data.provider} · ${data.model} · ${data.latency_ms} ms${memory}${fallback}`,
      );
    }
    await refresh();
  } catch (error) {
    if (version === viewVersion) addMessage("assistant", `Lỗi: ${error.message}`);
  } finally {
    sending = false;
    $("#sendBtn").disabled = false;
    $("#prompt").focus();
  }
}

async function refresh() {
  try {
    const [list, stats] = await Promise.all([
      api("/api/conversations"),
      api("/api/statistics"),
    ]);
    const root = $("#conversationList");
    root.innerHTML = "";

    list.forEach((conversation) => {
      const row = document.createElement("div");
      row.className = `conversation${conversation.id === conversationId ? " active" : ""}`;

      const open = document.createElement("button");
      open.textContent = conversation.title;
      open.title = conversation.title;
      open.onclick = () => loadConversation(conversation.id, conversation.title);

      const remove = document.createElement("button");
      remove.className = "delete";
      remove.textContent = "×";
      remove.title = "Xóa phiên";
      remove.onclick = async () => {
        if (!window.confirm("Xóa phiên đã lưu này?")) return;
        try {
          await api(`/api/conversations/${conversation.id}`, { method: "DELETE" });
        } catch (error) {
          window.alert(`Không xóa được phiên: ${error.message}`);
        }
        if (conversationId === conversation.id) newChat();
        await refresh();
      };

      row.append(open, remove);
      root.appendChild(row);
    });

    $("#stats").textContent = `Requests: ${stats.requests || 0} · Mask: ${stats.masked || 0} · Block: ${stats.blocked || 0}`;
  } catch (error) {
    if (error.message.includes("đăng nhập")) showApp(false);
  }
}

async function loadConversation(id, title) {
  let data;
  try {
    data = await api(`/api/conversations/${id}`);
  } catch (error) {
    window.alert(`Không mở được phiên: ${error.message}`);
    await refresh();
    return;
  }
  viewVersion += 1;
  conversationId = id;
  $("#chatTitle").textContent = title;
  $("#messages").innerHTML = "";
  data.messages.forEach((message) => {
    const meta = message.provider ? `${message.provider} · ${message.model}` : "";
    addMessage(message.role, message.content_display || message.content_sanitized, meta);
  });
  $("#analysis").classList.add("hidden");
  await refresh();
}

function newChat() {
  viewVersion += 1;
  conversationId = null;
  $("#chatTitle").textContent = "Phiên mới";
  $("#messages").innerHTML = `
    <div class="welcome">
      <h3>Phiên mới đã sẵn sàng</h3>
      <p>Có thể dùng ký ức đã làm sạch từ các phiên cũ khi tùy chọn bộ nhớ chéo phiên được bật.</p>
    </div>`;
  $("#analysis").classList.add("hidden");
  refresh();
}

async function health() {
  try {
    const data = await api("/api/ai/health");
    const entries = Object.entries(data.providers);
    $("#providerHealth").textContent = `Mode ${data.mode} · ${entries
      .map(([name, status]) => `${name}:${status.available ? "on" : "off"}`)
      .join(" · ")}`;
    $("#providerHealth").title = entries
      .map(([name, status]) => `${name} (${status.model}): ${status.detail}`)
      .join("\n");
  } catch (error) {
    $("#providerHealth").textContent = "Không kiểm tra được AI";
    $("#providerHealth").title = error.message;
  }
}

$("#loginBtn").onclick = login;
$("#sendBtn").onclick = send;
$("#newChat").onclick = newChat;
$("#logoutBtn").onclick = async () => {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch {
    // Phiên phía server đã hết hạn thì coi như đã đăng xuất.
  }
  csrfToken = null;
  conversationId = null;
  viewVersion += 1;
  showApp(false);
};
$("#prompt").onkeydown = (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    send();
  }
};
$("#password").onkeydown = (event) => {
  if (event.key === "Enter") login();
};
document.querySelectorAll(".sample").forEach((button) => {
  button.onclick = () => {
    if (sending) return;
    $("#prompt").value = button.dataset.prompt;
    send();
  };
});

showApp(Boolean(document.body.dataset.user));
