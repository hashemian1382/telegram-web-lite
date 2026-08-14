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
        throw new Error(msg);
    }
    return data;
}

function showMessage(text, type = "error") {
    const el = document.getElementById("message");
    if (!el) return;
    el.className = `msg msg-${type}`;
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
    const linkCard = document.getElementById("link-card");
    const welcomePane = document.getElementById("welcome-pane");
    const chatList = document.getElementById("chat-list");
    const chatsEmpty = document.getElementById("chats-empty");
    const sendCodeForm = document.getElementById("send-code-form");
    const verifyCodeForm = document.getElementById("verify-code-form");
    const twofaGroup = document.getElementById("twofa-group");

    let pendingPhone = null;
    let pendingCodeHash = null;

    async function loadIdentity() {
        try {
            const me = await api("/api/auth/me");
            document.getElementById("current-user").textContent = `@${me.username}`;
            return true;
        } catch {
            window.location.href = "/login";
            return false;
        }
    }

    function renderChats(chats) {
        chatList.innerHTML = "";
        chatsEmpty.classList.toggle("hidden", chats.length > 0);
        for (const chat of chats) {
            const li = document.createElement("li");
            li.className = "chat-item";
            const badge = chat.unread_count > 0 ? `<span class="unread-badge">${chat.unread_count}</span>` : "";
            li.innerHTML = `
                <div class="flex items-center justify-between gap-2">
                    <span class="chat-title"></span>${badge}
                </div>
                <span class="chat-preview"></span>`;
            li.querySelector(".chat-title").textContent = chat.title;
            li.querySelector(".chat-preview").textContent = chat.last_message || "—";
            chatList.appendChild(li);
        }
    }

    async function loadChats() {
        clearMessage();
        try {
            const data = await api("/api/chats/");
            if (!data.telegram_linked) {
                linkCard.classList.remove("hidden");
                welcomePane.classList.add("hidden");
                renderChats([]);
                return;
            }
            linkCard.classList.add("hidden");
            welcomePane.classList.remove("hidden");
            renderChats(data.chats);
        } catch (err) {
            showMessage(err.message);
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

    document.getElementById("refresh-chats").addEventListener("click", loadChats);
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
