/* Telegram Web Lite — client-side logic.
 * Vanilla JS, no build step. Each page self-initialises via [data-page].
 */
"use strict";

// ── Helpers ─────────────────────────────────────────────────────

async function api(path, { method = "GET", body = null } = {}) {
    const opts = { method, headers: {} };
    if (body !== null) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    if (res.status === 204) return null;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        const detail = data.detail;
        const msg = Array.isArray(detail)
            ? detail.map((e) => e.msg).join("; ")
            : detail || `Request failed (${res.status})`;
        const err = new Error(msg);
        err.status = res.status;
        throw err;
    }
    return data;
}

function showMessage(text, type = "error") {
    const el = document.getElementById("message");
    if (!el) return;
    el.className = `msg msg-${type} mx-4 mt-3`;
    el.textContent = text;
    el.classList.remove("hidden");
}

function clearMessage() {
    const el = document.getElementById("message");
    if (el) el.classList.add("hidden");
}

function setBusy(form, busy) {
    form.querySelectorAll("button[type=submit]").forEach((b) => (b.disabled = busy));
}

function esc(s) {
    const d = document.createElement("div");
    d.textContent = s ?? "";
    return d.innerHTML;
}

// Deterministic pastel avatar colour from a peer id
function avatarColor(seed) {
    let h = 0;
    for (const c of String(seed)) h = (h * 31 + c.charCodeAt(0)) % 360;
    return `hsl(${h}, 55%, 55%)`;
}

function initialOf(title) {
    return (title || "?").trim().charAt(0).toUpperCase() || "?";
}

function fmtDate(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return d.toLocaleString(undefined, {
        month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
}

// ── Login page ──────────────────────────────────────────────────

function initLoginPage() {
    const loginForm = document.getElementById("login-form");
    const registerForm = document.getElementById("register-form");
    const tabLogin = document.getElementById("tab-login");
    const tabRegister = document.getElementById("tab-register");

    const activate = (which) => {
        const loginActive = which === "login";
        loginForm.classList.toggle("hidden", !loginActive);
        registerForm.classList.toggle("hidden", loginActive);
        tabLogin.className = `flex-1 pb-2 font-semibold border-b-2 ${loginActive ? "border-blue-500 text-blue-600" : "border-transparent text-gray-500"}`;
        tabRegister.className = `flex-1 pb-2 font-semibold border-b-2 ${loginActive ? "border-transparent text-gray-500" : "border-blue-500 text-blue-600"}`;
        clearMessage();
    };
    tabLogin.addEventListener("click", () => activate("login"));
    tabRegister.addEventListener("click", () => activate("register"));

    loginForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        clearMessage();
        setBusy(loginForm, true);
        const data = Object.fromEntries(new FormData(loginForm));
        try {
            await api("/api/auth/login", { method: "POST", body: data });
            window.location.href = "/";
        } catch (err) {
            showMessage(err.message);
        } finally {
            setBusy(loginForm, false);
        }
    });

    registerForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        clearMessage();
        setBusy(registerForm, true);
        const data = Object.fromEntries(new FormData(registerForm));
        try {
            await api("/api/auth/register", { method: "POST", body: data });
            showMessage("Account created — you can sign in now.", "success");
            activate("login");
        } catch (err) {
            showMessage(err.message);
        } finally {
            setBusy(registerForm, false);
        }
    });
}

// ── Dashboard page ──────────────────────────────────────────────

function initIndexPage() {
    // Linking widgets
    const linkWrap = document.getElementById("link-wrap");
    const linkCard = document.getElementById("link-card");
    const sendCodeForm = document.getElementById("send-code-form");
    const verifyCodeForm = document.getElementById("verify-code-form");
    const twofaGroup = document.getElementById("twofa-group");
    // Chat widgets
    const emptyState = document.getElementById("empty-state");
    const chatView = document.getElementById("chat-view");
    const chatList = document.getElementById("chat-list");
    const chatsEmpty = document.getElementById("chats-empty");
    const addForm = document.getElementById("add-chat-form");
    const messagesEl = document.getElementById("messages");
    const composer = document.getElementById("composer");
    const composerInput = document.getElementById("composer-input");

    let me = null;
    let chats = [];            // curated list (from DB)
    let activeChatId = null;
    let pendingPhone = null;
    let pendingCodeHash = null;

    // ── Layout helpers ─────────────────────────────────────────
    function showPane(name) {
        // name: "link" | "empty" | "chat"
        linkWrap.classList.toggle("hidden", name !== "link");
        linkCard.classList.toggle("hidden", name !== "link");
        emptyState.classList.toggle("hidden", name !== "empty");
        emptyState.classList.toggle("flex", name === "empty");
        chatView.classList.toggle("hidden", name !== "chat");
        chatView.classList.toggle("flex", name === "chat");
    }

    // ── Identity & linking ─────────────────────────────────────
    async function loadIdentity() {
        try {
            me = await api("/api/auth/me");
            document.getElementById("current-user").textContent = `@${me.username}`;
            return true;
        } catch {
            window.location.href = "/login";
            return false;
        }
    }

    sendCodeForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        clearMessage();
        setBusy(sendCodeForm, true);
        const fd = new FormData(sendCodeForm);
        const body = { phone_number: fd.get("phone_number").trim() };
        if (fd.get("custom_api_id")) body.custom_api_id = Number(fd.get("custom_api_id"));
        if (fd.get("custom_api_hash")) body.custom_api_hash = fd.get("custom_api_hash").trim();
        try {
            const res = await api("/api/auth/telegram/send-code", { method: "POST", body });
            pendingPhone = body.phone_number;
            pendingCodeHash = res.phone_code_hash;
            sendCodeForm.classList.add("hidden");
            verifyCodeForm.classList.remove("hidden");
            showMessage("Code sent — check your Telegram app.", "info");
        } catch (err) {
            showMessage(err.message);
        } finally {
            setBusy(sendCodeForm, false);
        }
    });

    verifyCodeForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        clearMessage();
        setBusy(verifyCodeForm, true);
        const fd = new FormData(verifyCodeForm);
        const body = {
            phone_number: pendingPhone,
            code: fd.get("code").trim(),
            phone_code_hash: pendingCodeHash,
        };
        const pwd = fd.get("password");
        if (pwd) body.password = pwd;
        try {
            const res = await api("/api/auth/telegram/verify-code", { method: "POST", body });
            if (res.status === "password_required") {
                twofaGroup.classList.remove("hidden");
                showMessage("Two-factor auth is enabled — enter your Telegram password.", "info");
            } else {
                showMessage(`Telegram account ${res.telegram_phone} linked!`, "success");
                await loadChats();
            }
        } catch (err) {
            showMessage(err.message);
        } finally {
            setBusy(verifyCodeForm, false);
        }
    });

    // ── Curated chat list ──────────────────────────────────────
    function renderChatList() {
        chatList.innerHTML = "";
        chatsEmpty.classList.toggle("hidden", chats.length > 0);
        chatList.classList.toggle("hidden", chats.length === 0);
        for (const chat of chats) {
            const li = document.createElement("li");
            li.dataset.chatId = chat.id;
            li.className = "side-chat" + (chat.id === activeChatId ? " active" : "");
            li.innerHTML = `
                <div class="avatar" style="background:${avatarColor(chat.peer_id)}">${esc(initialOf(chat.title))}</div>
                <div class="flex-1 min-w-0">
                    <p class="side-title"></p>
                    <p class="side-sub"></p>
                </div>`;
            li.querySelector(".side-title").textContent = chat.title;
            li.querySelector(".side-sub").textContent =
                chat.username ? `@${chat.username}` : `ID: ${chat.peer_id}`;
            li.addEventListener("click", () => selectChat(chat.id));
            chatList.appendChild(li);
        }
    }

    async function loadChats() {
        clearMessage();
        try {
            const data = await api("/api/chats/");
            if (!data.telegram_linked) {
                chats = [];
                activeChatId = null;
                renderChatList();
                showPane("link");
                return;
            }
            chats = data.chats;
            renderChatList();
            if (activeChatId && !chats.some((c) => c.id === activeChatId)) {
                activeChatId = null;
            }
            showPane(activeChatId ? "chat" : "empty");
        } catch (err) {
            if (err.status === 401) { window.location.href = "/login"; return; }
            showMessage(err.message);
        }
    }

    // ── Add / remove chats ─────────────────────────────────────
    document.getElementById("toggle-add").addEventListener("click", () => {
        addForm.classList.toggle("hidden");
        addForm.querySelector("input").focus();
    });

    addForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        clearMessage();
        setBusy(addForm, true);
        const identifier = new FormData(addForm).get("identifier").trim();
        try {
            const chat = await api("/api/chats/", { method: "POST", body: { identifier } });
            addForm.reset();
            addForm.classList.add("hidden");
            showMessage(`Added “${chat.title}”.`, "success");
            await loadChats();
            selectChat(chat.id);
        } catch (err) {
            showMessage(err.message);
        } finally {
            setBusy(addForm, false);
        }
    });

    document.getElementById("delete-chat").addEventListener("click", async () => {
        if (!activeChatId) return;
        const chat = chats.find((c) => c.id === activeChatId);
        if (!confirm(`Remove “${chat?.title}” from your chats? (Telegram itself is untouched)`)) return;
        try {
            await api(`/api/chats/${activeChatId}`, { method: "DELETE" });
            activeChatId = null;
            await loadChats();
        } catch (err) {
            showMessage(err.message);
        }
    });

    // ── Messages ───────────────────────────────────────────────
    function appendMessage(m) {
        const wrap = document.createElement("div");
        wrap.className = `msg-row ${m.out ? "mine" : "theirs"}`;
        const when = fmtDate(m.date);
        wrap.innerHTML = `
            <div class="bubble">
                <span class="bubble-text"></span>
                <span class="bubble-time">${esc(when)}</span>
            </div>`;
        wrap.querySelector(".bubble-text").textContent = m.text || "";
        messagesEl.appendChild(wrap);
    }

    async function openMessages(scroll = true) {
        if (!activeChatId) return;
        try {
            const data = await api(`/api/chats/${activeChatId}/messages`);
            messagesEl.innerHTML = "";
            if (data.messages.length === 0) {
                messagesEl.innerHTML =
                    `<p class="text-center text-sm text-gray-400 mt-6">No messages yet — say hi! 👋</p>`;
            } else {
                data.messages.forEach(appendMessage);
            }
            if (scroll) messagesEl.scrollTop = messagesEl.scrollHeight;
        } catch (err) {
            showMessage(err.message);
        }
    }

    async function selectChat(id) {
        activeChatId = id;
        const chat = chats.find((c) => c.id === id);
        if (!chat) return;
        renderChatList();
        document.getElementById("chat-avatar").style.background = avatarColor(chat.peer_id);
        document.getElementById("chat-avatar").textContent = initialOf(chat.title);
        document.getElementById("chat-title").textContent = chat.title;
        document.getElementById("chat-subtitle").textContent =
            chat.username ? `@${chat.username}` : `ID: ${chat.peer_id}`;
        messagesEl.innerHTML =
            `<p class="text-center text-sm text-gray-400 mt-6">Loading…</p>`;
        showPane("chat");
        await openMessages();
    }

    document.getElementById("refresh-msgs").addEventListener("click", () => openMessages());

    composer.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = composerInput.value.trim();
        if (!text || !activeChatId) return;
        composerInput.value = "";
        try {
            const res = await api(`/api/chats/${activeChatId}/messages`, {
                method: "POST", body: { text },
            });
            appendMessage(res.message);           // instantly show own message
            messagesEl.scrollTop = messagesEl.scrollHeight;
        } catch (err) {
            composerInput.value = text;           // restore on failure
            showMessage(err.message);
        }
    });

    // ── Session ────────────────────────────────────────────────
    document.getElementById("logout-btn").addEventListener("click", async () => {
        try { await api("/api/auth/logout", { method: "POST" }); } catch { /* ignore */ }
        window.location.href = "/login";
    });

    loadIdentity().then((ok) => ok && loadChats());
}

// ── Bootstrap ───────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    const page = document.querySelector("[data-page]");
    if (!page) return;
    if (page.dataset.page === "login") initLoginPage();
    if (page.dataset.page === "index") initIndexPage();
});
