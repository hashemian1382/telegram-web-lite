/* ═══════════════════════════════════════════════════════════════
   Telegram Web Lite — client-side logic.
   Vanilla JS, no build step. Each page self-initialises via [data-page].

   Dashboard features: curated chat list, search, text messaging,
   photo/file upload & download, image lightbox, light/dark theme, and
   incremental auto-refresh (polls `?after_id=` every 2 s so new incoming
   messages appear by themselves).

   Robustness notes
   - Sends are guarded by a single `sendInFlight` flag + disabled controls,
     so mashing Enter / the send button can never fire duplicate requests.
   - Messages are rendered optimistically (a "sending" bubble appears
     instantly) and reconciled against the server reply — no re-press, and
     duplicate incoming ids are de-duplicated against a `knownIds` set.
   - Polling is self-scheduling (never overlaps itself) and results are
     discarded if the user switched chats mid-request.
   ═══════════════════════════════════════════════════════════════ */
"use strict";

// ── Tiny DOM helpers ────────────────────────────────────────────

const $ = (id) => document.getElementById(id);

function icon(name, cls = "") {
    return `<svg${cls ? ` class="${cls}"` : ""}><use href="#i-${name}"></use></svg>`;
}

function esc(s) {
    const d = document.createElement("div");
    d.textContent = s ?? "";
    return d.innerHTML;
}

// ── Theme ───────────────────────────────────────────────────────

const Theme = {
    get() {
        return document.documentElement.getAttribute("data-theme") || "light";
    },
    set(theme) {
        document.documentElement.setAttribute("data-theme", theme);
        try { localStorage.setItem("twl-theme", theme); } catch { /* private mode */ }
    },
    toggle() {
        this.set(this.get() === "dark" ? "light" : "dark");
    },
    init() {
        const btn = $("theme-toggle");
        if (btn) btn.addEventListener("click", () => Theme.toggle());
        // Follow the OS only while the user has never chosen explicitly.
        let stored = null;
        try { stored = localStorage.getItem("twl-theme"); } catch { /* ignore */ }
        if (!stored && window.matchMedia) {
            const mq = window.matchMedia("(prefers-color-scheme: dark)");
            const onChange = (e) => {
                let saved = null;
                try { saved = localStorage.getItem("twl-theme"); } catch { /* ignore */ }
                if (!saved) document.documentElement.setAttribute("data-theme", e.matches ? "dark" : "light");
            };
            mq.addEventListener ? mq.addEventListener("change", onChange) : mq.addListener(onChange);
        }
    },
};

// ── HTTP layer ──────────────────────────────────────────────────

async function api(path, { method = "GET", body = null } = {}) {
    const opts = { method, headers: {} };
    if (body !== null) {
        opts.headers["Content-Type"] = "application/json";
        opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    if (res.status === 204) return null;
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw apiError(res, data);
    return data;
}

// Multipart upload (browser sets the boundary — never set Content-Type here)
async function apiUpload(path, formData) {
    const res = await fetch(path, { method: "POST", body: formData });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw apiError(res, data);
    return data;
}

function apiError(res, data) {
    const detail = data.detail;
    const msg = Array.isArray(detail)
        ? detail.map((e) => e.msg).join("; ")
        : detail || `Request failed (${res.status})`;
    const err = new Error(msg);
    err.status = res.status;
    return err;
}

// ── Feedback: toasts + inline alerts ────────────────────────────

const TOAST_ICONS = { error: "alert", success: "check", info: "info" };

function toast(text, type = "error", timeout = 4600) {
    const host = $("toasts");
    if (!host) return;
    const el = document.createElement("div");
    el.className = `toast toast-${type}`;
    el.innerHTML = `
        <span class="toast-icon">${icon(TOAST_ICONS[type] || "info")}</span>
        <span class="toast-body"></span>
        <button type="button" class="toast-close" aria-label="Dismiss">${icon("close")}</button>`;
    el.querySelector(".toast-body").textContent = text;

    const dismiss = () => {
        if (!el.isConnected) return;
        el.classList.add("leaving");
        setTimeout(() => el.remove(), 180);
    };
    el.querySelector(".toast-close").addEventListener("click", dismiss);
    host.appendChild(el);
    if (timeout) setTimeout(dismiss, timeout);
    return el;
}

/** Inline alert inside #message when present, otherwise a toast. */
function showMessage(text, type = "error") {
    const el = $("message");
    if (!el) { toast(text, type); return; }
    el.className = `alert alert-${type}`;
    el.innerHTML = `<span>${icon(TOAST_ICONS[type] || "info")}</span><span class="alert-body"></span>`;
    el.querySelector(".alert-body").textContent = text;
    el.classList.remove("hidden");
    if (type === "error") {
        el.classList.remove("shake");
        void el.offsetWidth;              // restart the animation
        el.classList.add("shake");
    }
}

function clearMessage() {
    const el = $("message");
    if (el) { el.classList.add("hidden"); el.classList.remove("shake"); }
}

// ── Busy state ──────────────────────────────────────────────────

function setBusy(form, busy) {
    form.querySelectorAll("button").forEach((b) => {
        b.disabled = busy;
        if (b.type === "submit") b.classList.toggle("is-loading", busy);
    });
}

// ── Formatting ──────────────────────────────────────────────────

// Deterministic avatar colour from a peer id / username.
// FNV-1a keeps neighbouring ids (1001, 1002, …) in visibly different hues.
function avatarColor(seed) {
    let h = 0x811c9dc5;
    const s = String(seed);
    for (let i = 0; i < s.length; i++) {
        h ^= s.charCodeAt(i);
        h = Math.imul(h, 0x01000193) >>> 0;
    }
    const hue = h % 360;
    return `linear-gradient(135deg, hsl(${hue}, 64%, 58%), hsl(${(hue + 26) % 360}, 60%, 46%))`;
}

function initialOf(title) {
    return (title || "?").trim().charAt(0).toUpperCase() || "?";
}

function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
}

function dayKey(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return "";
    return `${d.getFullYear()}-${d.getMonth()}-${d.getDate()}`;
}

function fmtDay(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return "";
    const today = new Date();
    const yesterday = new Date();
    yesterday.setDate(today.getDate() - 1);
    if (dayKey(iso) === dayKey(today.toISOString())) return "Today";
    if (dayKey(iso) === dayKey(yesterday.toISOString())) return "Yesterday";
    const sameYear = d.getFullYear() === today.getFullYear();
    return d.toLocaleDateString(undefined, {
        weekday: "short", month: "short", day: "numeric",
        ...(sameYear ? {} : { year: "numeric" }),
    });
}

function fmtSize(bytes) {
    if (bytes === null || bytes === undefined) return "";
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/** A browser File is an image when its MIME type or extension says so. */
function isImageFile(f) {
    if (!f) return false;
    if (f.type && f.type.startsWith("image/")) return true;
    return /\.(jpe?g|png|gif|bmp|webp)$/i.test(f.name || "");
}

// ── Shared widgets ──────────────────────────────────────────────

/** Password reveal buttons ([data-reveal="<input id>"]). */
function initPasswordReveals(root = document) {
    root.querySelectorAll("[data-reveal]").forEach((btn) => {
        btn.addEventListener("click", () => {
            const input = $(btn.dataset.reveal);
            if (!input) return;
            const show = input.type === "password";
            input.type = show ? "text" : "password";
            btn.classList.toggle("revealed", show);
            btn.setAttribute("aria-label", show ? "Hide password" : "Show password");
            btn.title = show ? "Hide password" : "Show password";
            input.focus({ preventScroll: true });
        });
    });
}

/** Full-screen image viewer. */
function openLightbox(src) {
    const box = document.createElement("div");
    box.className = "lightbox";
    box.innerHTML = `
        <button type="button" class="lightbox-close" aria-label="Close">${icon("close")}</button>
        <img alt="Photo">`;
    box.querySelector("img").src = src;

    const close = () => {
        box.remove();
        document.removeEventListener("keydown", onKey);
    };
    const onKey = (e) => { if (e.key === "Escape") close(); };
    box.addEventListener("click", close);
    box.querySelector("img").addEventListener("click", (e) => e.stopPropagation());
    box.querySelector(".lightbox-close").addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    document.body.appendChild(box);
}

// ═══════════════════════════════════════════════════════════════
//  Login / register page
// ═══════════════════════════════════════════════════════════════

function initLoginPage() {
    const loginForm = $("login-form");
    const registerForm = $("register-form");
    const tabLogin = $("tab-login");
    const tabRegister = $("tab-register");
    const seg = document.querySelector(".seg");
    const subtitle = $("auth-subtitle");

    initPasswordReveals();

    const activate = (which) => {
        const isLogin = which === "login";
        seg.dataset.active = which;
        tabLogin.setAttribute("aria-selected", String(isLogin));
        tabRegister.setAttribute("aria-selected", String(!isLogin));

        const show = isLogin ? loginForm : registerForm;
        const hide = isLogin ? registerForm : loginForm;
        hide.classList.add("hidden");
        show.classList.remove("hidden");
        show.classList.remove("entering");
        void show.offsetWidth;
        show.classList.add("entering");

        subtitle.textContent = isLogin
            ? "Sign in to your account to continue"
            : "Create an account to get started";
        clearMessage();
        const first = show.querySelector("input");
        if (first && window.matchMedia("(min-width: 761px)").matches) {
            first.focus({ preventScroll: true });
        }
    };

    tabLogin.addEventListener("click", () => activate("login"));
    tabRegister.addEventListener("click", () => activate("register"));

    // ── Password strength meter ─────────────────────────────────
    const pwd = $("reg-password");
    const strength = $("pwd-strength");
    const strengthText = $("pwd-strength-text");
    const LABELS = ["Use at least 8 characters", "Weak password", "Fair password", "Good password", "Strong password"];

    if (pwd && strength) {
        pwd.addEventListener("input", () => {
            const v = pwd.value;
            let score = 0;
            if (v.length >= 8) score++;
            if (v.length >= 12) score++;
            if (/[A-Z]/.test(v) && /[a-z]/.test(v)) score++;
            if (/[0-9]/.test(v) && /[^A-Za-z0-9]/.test(v)) score++;
            if (v.length < 8) score = v.length ? 1 : 0;
            score = Math.min(score, 4);
            strength.dataset.level = String(score);
            strengthText.textContent = LABELS[score];
        });
    }

    // ── Sign in ─────────────────────────────────────────────────
    loginForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        clearMessage();
        if (!loginForm.reportValidity()) return;
        setBusy(loginForm, true);
        const data = Object.fromEntries(new FormData(loginForm));
        try {
            await api("/api/auth/login", { method: "POST", body: data });
            showMessage("Signed in — taking you to your chats…", "success");
            window.location.href = "/";
        } catch (err) {
            showMessage(err.message);
            setBusy(loginForm, false);
        }
    });

    // ── Create account ──────────────────────────────────────────
    registerForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        clearMessage();
        if (!registerForm.reportValidity()) return;
        setBusy(registerForm, true);
        const data = Object.fromEntries(new FormData(registerForm));
        try {
            await api("/api/auth/register", { method: "POST", body: data });
            const username = data.username;
            registerForm.reset();
            if (strength) { strength.dataset.level = "0"; strengthText.textContent = LABELS[0]; }
            activate("login");
            $("login-username").value = username;
            $("login-password").focus({ preventScroll: true });
            showMessage("Account created — you can sign in now.", "success");
        } catch (err) {
            showMessage(err.message);
        } finally {
            setBusy(registerForm, false);
        }
    });
}

// ═══════════════════════════════════════════════════════════════
//  Dashboard page
// ═══════════════════════════════════════════════════════════════

function initIndexPage() {
    // Linking widgets
    const linkWrap = $("link-wrap");
    const sendCodeForm = $("send-code-form");
    const verifyCodeForm = $("verify-code-form");
    const twofaGroup = $("twofa-group");
    const stepper = $("stepper");
    // Chat widgets
    const emptyState = $("empty-state");
    const chatView = $("chat-view");
    const chatList = $("chat-list");
    const chatsEmpty = $("chats-empty");
    const chatsNoMatch = $("chats-nomatch");
    const chatCount = $("chat-count");
    const searchInput = $("chat-search");
    const addForm = $("add-chat-form");
    const toggleAdd = $("toggle-add");
    const messagesEl = $("messages");
    const composer = $("composer");
    const composerInput = $("composer-input");
    const sendBtn = $("send-btn");
    const attachBtn = $("attach-btn");
    const fileInput = $("file-input");
    const pendingFile = $("pending-file");
    const pendingFileName = $("pending-file-name");
    const pendingFileRemove = $("pending-file-remove");
    const sendMode = $("send-mode");
    const modePhoto = $("mode-photo");
    const modeFile = $("mode-file");
    const sidebar = $("sidebar");
    const workspace = document.querySelector(".workspace");

    const POLL_MS = 2000;              // auto-refresh cadence: 2 s
    const MOBILE = () => window.matchMedia("(max-width: 760px)").matches;

    let me = null;
    let chats = [];
    let activeChatId = null;
    let lastMsgId = 0;                 // high-water mark for incremental polls
    let knownIds = new Set();          // message ids already rendered (de-dupe)
    let pendingAttachment = null;      // File selected via the clip button
    let pendingSendAsPhoto = true;     // how an image attachment is sent
    let sendInFlight = false;          // guards against duplicate submissions
    let pollTimer = null;              // self-scheduling poll handle
    let tmpIdCounter = 0;              // unique negative ids for pending bubbles
    let pendingPhone = null;
    let pendingCodeHash = null;
    let searchTerm = "";
    let lastDayKey = null;             // for date dividers
    let lastRowSide = null;            // for grouped bubbles

    initPasswordReveals();

    // ── Layout ──────────────────────────────────────────────────
    function showPane(name) {          // "link" | "empty" | "chat"
        linkWrap.classList.toggle("hidden", name !== "link");
        emptyState.classList.toggle("hidden", name !== "empty");
        chatView.classList.toggle("hidden", name !== "chat");
    }

    function openSidebar(open) {
        if (!MOBILE()) return;
        sidebar.classList.toggle("open", open);
        let backdrop = document.querySelector(".sidebar-backdrop");
        if (open && !backdrop) {
            backdrop = document.createElement("div");
            backdrop.className = "sidebar-backdrop";
            backdrop.addEventListener("click", () => openSidebar(false));
            workspace.appendChild(backdrop);
        } else if (!open && backdrop) {
            backdrop.remove();
        }
    }

    $("sidebar-toggle").addEventListener("click", () => openSidebar(!sidebar.classList.contains("open")));
    $("chat-back").addEventListener("click", () => openSidebar(true));

    window.addEventListener("resize", () => {
        if (!MOBILE()) {
            sidebar.classList.remove("open");
            const b = document.querySelector(".sidebar-backdrop");
            if (b) b.remove();
        }
    });

    // ── Identity ────────────────────────────────────────────────
    async function loadIdentity() {
        try {
            me = await api("/api/auth/me");
            $("current-user").textContent = `@${me.username}`;
            const av = $("me-avatar");
            av.textContent = initialOf(me.username);
            av.style.background = avatarColor(me.username);
            $("user-chip").title = `Signed in as @${me.username}`;
            return true;
        } catch {
            window.location.href = "/login";
            return false;
        }
    }

    // ── Telegram linking flow ───────────────────────────────────
    function setStep(step) {           // "phone" | "code" | "done"
        const order = ["phone", "code", "done"];
        const idx = order.indexOf(step);
        stepper.querySelectorAll(".step").forEach((el) => {
            const i = order.indexOf(el.dataset.step);
            el.classList.toggle("active", i === idx);
            el.classList.toggle("done", i < idx);
            const dot = el.querySelector(".step-dot");
            dot.innerHTML = i < idx ? icon("check") : String(i + 1);
        });
        stepper.querySelectorAll(".step-bar").forEach((bar, i) => {
            bar.classList.toggle("done", i < idx);
        });
    }

    function showLinkForm(which) {     // "phone" | "code"
        const show = which === "phone" ? sendCodeForm : verifyCodeForm;
        const hide = which === "phone" ? verifyCodeForm : sendCodeForm;
        hide.classList.add("hidden");
        show.classList.remove("hidden");
        show.classList.remove("entering");
        void show.offsetWidth;
        show.classList.add("entering");
        setStep(which);
        $("link-sub").innerHTML = which === "phone"
            ? "Enter your phone number in international format.<br>A confirmation code will be sent to your Telegram app."
            : "Open Telegram on your phone and enter the code we just sent you.";
        const first = show.querySelector("input:not([type=hidden])");
        if (first) first.focus({ preventScroll: true });
    }

    sendCodeForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!sendCodeForm.reportValidity()) return;
        setBusy(sendCodeForm, true);
        const fd = new FormData(sendCodeForm);
        const body = { phone_number: fd.get("phone_number").trim() };
        if (fd.get("custom_api_id")) body.custom_api_id = Number(fd.get("custom_api_id"));
        if (fd.get("custom_api_hash")) body.custom_api_hash = fd.get("custom_api_hash").trim();
        try {
            const res = await api("/api/auth/telegram/send-code", { method: "POST", body });
            pendingPhone = body.phone_number;
            pendingCodeHash = res.phone_code_hash;
            $("recap-phone").textContent = pendingPhone;
            showLinkForm("code");
            toast("Code sent — check your Telegram app.", "info");
        } catch (err) {
            toast(err.message, "error");
        } finally {
            setBusy(sendCodeForm, false);
        }
    });

    $("change-phone").addEventListener("click", () => {
        verifyCodeForm.reset();
        twofaGroup.classList.add("hidden");
        pendingCodeHash = null;
        showLinkForm("phone");
    });

    verifyCodeForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!verifyCodeForm.reportValidity()) return;
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
                $("tg-password").focus({ preventScroll: true });
                toast("Two-factor auth is enabled — enter your Telegram password.", "info", 6000);
            } else {
                setStep("done");
                toast(`Telegram account ${res.telegram_phone} linked!`, "success");
                await loadChats();
            }
        } catch (err) {
            toast(err.message, "error");
        } finally {
            setBusy(verifyCodeForm, false);
        }
    });

    // ── Curated chat list ───────────────────────────────────────
    function subtitleOf(chat) {
        return chat.username ? `@${chat.username}` : `ID: ${chat.peer_id}`;
    }

    function visibleChats() {
        if (!searchTerm) return chats;
        const q = searchTerm.toLowerCase();
        return chats.filter((c) =>
            (c.title || "").toLowerCase().includes(q) ||
            (c.username || "").toLowerCase().includes(q) ||
            String(c.peer_id).includes(q));
    }

    function renderChatList() {
        const list = visibleChats();
        chatList.innerHTML = "";
        chatCount.textContent = String(chats.length);

        chatsEmpty.classList.toggle("hidden", chats.length > 0);
        chatsNoMatch.classList.toggle("hidden", !(chats.length > 0 && list.length === 0));
        chatList.classList.toggle("hidden", list.length === 0);

        list.forEach((chat, i) => {
            const li = document.createElement("li");
            li.dataset.chatId = chat.id;
            li.className = "chat-item" + (chat.id === activeChatId ? " active" : "");
            li.style.animationDelay = `${Math.min(i, 12) * 22}ms`;
            li.tabIndex = 0;
            li.setAttribute("role", "button");
            li.innerHTML = `
                <div class="avatar" style="background:${avatarColor(chat.peer_id)}">${esc(initialOf(chat.title))}</div>
                <div class="chat-item-body">
                    <p class="chat-item-title"></p>
                    <p class="chat-item-sub"></p>
                </div>`;
            li.querySelector(".chat-item-title").textContent = chat.title;
            li.querySelector(".chat-item-sub").textContent = subtitleOf(chat);
            li.addEventListener("click", () => selectChat(chat.id));
            li.addEventListener("keydown", (e) => {
                if (e.key === "Enter" || e.key === " ") { e.preventDefault(); selectChat(chat.id); }
            });
            chatList.appendChild(li);
        });
    }

    function renderSkeletons(n = 4) {
        chatList.classList.remove("hidden");
        chatsEmpty.classList.add("hidden");
        chatsNoMatch.classList.add("hidden");
        chatList.innerHTML = Array.from({ length: n }, () => `
            <li class="skeleton-item">
                <span class="sk sk-avatar"></span>
                <span style="flex:1">
                    <span class="sk sk-line" style="display:block; width:58%; margin-bottom:7px"></span>
                    <span class="sk sk-line" style="display:block; width:38%; height:8px"></span>
                </span>
            </li>`).join("");
    }

    searchInput.addEventListener("input", () => {
        searchTerm = searchInput.value.trim();
        renderChatList();
    });
    searchInput.addEventListener("keydown", (e) => {
        if (e.key === "Escape") { searchInput.value = ""; searchTerm = ""; renderChatList(); }
    });

    async function loadChats() {
        try {
            const data = await api("/api/chats/");
            if (!data.telegram_linked) {
                chats = [];
                activeChatId = null;
                renderChatList();
                showLinkForm("phone");
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
            toast(err.message, "error");
        }
    }

    // ── Add / remove chats ──────────────────────────────────────
    toggleAdd.addEventListener("click", () => {
        const open = addForm.classList.toggle("hidden") === false;
        toggleAdd.classList.toggle("is-open", open);
        toggleAdd.setAttribute("aria-expanded", String(open));
        if (open) addForm.querySelector("input").focus({ preventScroll: true });
    });

    function closeAddPanel() {
        addForm.reset();
        addForm.classList.add("hidden");
        toggleAdd.classList.remove("is-open");
        toggleAdd.setAttribute("aria-expanded", "false");
    }

    addForm.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAddPanel(); });

    addForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        if (!addForm.reportValidity()) return;
        setBusy(addForm, true);
        const identifier = new FormData(addForm).get("identifier").trim();
        try {
            const chat = await api("/api/chats/", { method: "POST", body: { identifier } });
            closeAddPanel();
            searchInput.value = "";
            searchTerm = "";
            toast(`Added “${chat.title}”.`, "success");
            await loadChats();
            selectChat(chat.id);
        } catch (err) {
            toast(err.message, "error");
        } finally {
            setBusy(addForm, false);
        }
    });

    $("delete-chat").addEventListener("click", async () => {
        if (!activeChatId) return;
        const chat = chats.find((c) => c.id === activeChatId);
        if (!confirm(`Remove “${chat?.title}” from your chats?\n\nTelegram itself is untouched.`)) return;
        try {
            await api(`/api/chats/${activeChatId}`, { method: "DELETE" });
            activeChatId = null;
            toast("Chat removed from your list.", "success");
            await loadChats();
        } catch (err) {
            toast(err.message, "error");
        }
    });

    // ── Message rendering ───────────────────────────────────────
    function mediaUrl(messageId, thumb = false) {
        return `/api/chats/${activeChatId}/messages/${messageId}/download` + (thumb ? "?thumb=1" : "");
    }

    // Append a message bubble. `pending` marks an optimistic (not-yet-confirmed)
    // bubble: a spinner replaces the time/ticks and `localSrc` may point at a
    // blob: URL preview. Returns the row element, or null if de-duplicated.
    function appendMessage(m, { pending = false, localSrc = null } = {}) {
        if (!pending && m.id != null && knownIds.has(m.id)) return null;
        if (!pending && m.id != null) knownIds.add(m.id);

        const placeholder = messagesEl.querySelector(".msg-placeholder");
        if (placeholder) placeholder.remove();

        // Date divider when the day changes
        const key = dayKey(m.date);
        if (key && key !== lastDayKey) {
            const div = document.createElement("div");
            div.className = "day-divider";
            div.textContent = fmtDay(m.date);
            messagesEl.appendChild(div);
            lastDayKey = key;
            lastRowSide = null;
        }

        const side = m.out ? "mine" : "theirs";
        const wrap = document.createElement("div");
        wrap.className = `row ${side}` + (side === lastRowSide ? " same" : "");
        lastRowSide = side;

        let mediaHtml = "";
        if (m.media_type === "photo") {
            const src = pending && localSrc ? localSrc : mediaUrl(m.id, true);
            const full = pending && localSrc ? localSrc : mediaUrl(m.id);
            mediaHtml = `<img class="bubble-photo" loading="lazy" alt="Photo"
                              src="${esc(src)}" data-full="${esc(full)}">`;
        } else if (m.media_type === "document") {
            const href = pending && localSrc ? localSrc : mediaUrl(m.id);
            mediaHtml = `
                <a class="doc-card" href="${esc(href)}" title="Download ${esc(m.media_name || "file")}">
                    <span class="doc-icon">${icon("doc")}</span>
                    <span class="doc-info">
                        <span class="doc-name"></span>
                        <span class="doc-size">${esc(fmtSize(m.media_size))}</span>
                    </span>
                    <span class="doc-dl">${icon("download")}</span>
                </a>`;
        }

        const metaInner = pending
            ? `<span class="spinner" aria-hidden="true"></span><span class="sr-only">Sending…</span>`
            : `<span>${esc(fmtTime(m.date))}</span>${m.out ? icon("check-double") : ""}`;

        wrap.innerHTML = `
            <div class="bubble">
                ${mediaHtml}
                ${m.text ? `<span class="bubble-text"></span>` : ""}
                <span class="bubble-meta">${metaInner}</span>
            </div>`;

        const textEl = wrap.querySelector(".bubble-text");
        if (textEl) textEl.textContent = m.text;
        const nameEl = wrap.querySelector(".doc-name");
        if (nameEl) nameEl.textContent = m.media_name || "file";

        const img = wrap.querySelector(".bubble-photo");
        if (img) {
            img.addEventListener("click", () => openLightbox(img.dataset.full));
            img.addEventListener("error", () => { img.style.display = "none"; });
        }

        messagesEl.appendChild(wrap);
        if (!pending) lastMsgId = Math.max(lastMsgId, m.id);
        return wrap;
    }

    function scrollToBottom(smooth = false) {
        messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: smooth ? "smooth" : "auto" });
    }

    function resetMessageStream() {
        messagesEl.innerHTML = "";
        lastMsgId = 0;
        knownIds.clear();
        lastDayKey = null;
        lastRowSide = null;
    }

    function placeholder(text, loading = false) {
        messagesEl.innerHTML = `
            <p class="msg-placeholder">
                <span>${esc(text)}</span>
                ${loading ? `<span class="typing-dots"><i></i><i></i><i></i></span>` : ""}
            </p>`;
    }

    async function openMessages() {
        if (!activeChatId) return;
        const chatId = activeChatId;
        const btn = $("refresh-msgs");
        btn.disabled = true;
        try {
            const data = await api(`/api/chats/${chatId}/messages`);
            if (activeChatId !== chatId) return;   // switched away mid-request
            resetMessageStream();
            if (data.messages.length === 0) {
                placeholder("No messages yet — say hi! 👋");
            } else {
                data.messages.forEach(appendMessage);
            }
            scrollToBottom();
        } catch (err) {
            if (activeChatId === chatId) toast(err.message, "error");
        } finally {
            btn.disabled = false;
        }
    }

    // ── Incremental auto-refresh (self-scheduling — never overlaps) ──
    async function pollTick() {
        if (document.hidden) { schedulePoll(); return; }
        const chatId = activeChatId;
        if (!chatId) { schedulePoll(); return; }
        try {
            const data = await api(`/api/chats/${chatId}/messages?after_id=${lastMsgId}`);
            if (activeChatId !== chatId) return;   // switched away mid-request
            if (data.messages.length === 0) return;
            const nearBottom =
                messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight < 140;
            data.messages.forEach(appendMessage);
            // Don't yank the view down while the user reads history.
            if (nearBottom || data.messages.some((m) => m.out)) scrollToBottom(true);
        } catch (err) {
            if (err.status === 401) {           // session died or was revoked
                await loadChats();              // → link card (or /login) cleanly
                return;
            }
            console.warn("poll failed:", err.message);  // transient → next tick retries
        } finally {
            schedulePoll();
        }
    }

    function schedulePoll() {
        if (pollTimer) clearTimeout(pollTimer);
        pollTimer = setTimeout(pollTick, POLL_MS);
    }

    async function selectChat(id) {
        const chat = chats.find((c) => c.id === id);
        if (!chat) return;
        activeChatId = id;
        renderChatList();

        const av = $("chat-avatar");
        av.style.background = avatarColor(chat.peer_id);
        av.textContent = initialOf(chat.title);
        $("chat-title").textContent = chat.title;
        $("chat-subtitle").textContent = subtitleOf(chat);

        clearAttachment();
        resetMessageStream();
        placeholder("Loading messages", true);
        showPane("chat");
        openSidebar(false);
        await openMessages();
        if (!MOBILE() && activeChatId === id) composerInput.focus({ preventScroll: true });
    }

    $("refresh-msgs").addEventListener("click", openMessages);

    // ── Composer: auto-grow textarea ────────────────────────────
    function autoGrow() {
        composerInput.style.height = "auto";
        composerInput.style.height = `${Math.min(composerInput.scrollHeight, 148)}px`;
        syncSendState();
    }

    function syncSendState() {
        const empty = !composerInput.value.trim() && !pendingAttachment;
        sendBtn.disabled = empty || sendInFlight;
        attachBtn.disabled = sendInFlight;
        pendingFileRemove.disabled = sendInFlight;
        sendBtn.classList.toggle("is-loading", sendInFlight);
    }

    composerInput.addEventListener("input", autoGrow);
    composerInput.addEventListener("keydown", (e) => {
        // Enter sends, Shift+Enter makes a new line.
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            composer.requestSubmit();
        }
    });

    // ── Attachments ─────────────────────────────────────────────
    function setSendMode(photo) {
        pendingSendAsPhoto = photo;
        if (!sendMode) return;
        sendMode.classList.remove("hidden");
        modePhoto.classList.toggle("active", photo);
        modeFile.classList.toggle("active", !photo);
        modePhoto.setAttribute("aria-pressed", String(photo));
        modeFile.setAttribute("aria-pressed", String(!photo));
    }

    function clearAttachment() {
        pendingAttachment = null;
        pendingSendAsPhoto = true;
        fileInput.value = "";
        pendingFile.classList.add("hidden");
        if (sendMode) sendMode.classList.add("hidden");
        syncSendState();
    }

    $("attach-btn").addEventListener("click", () => fileInput.click());
    fileInput.addEventListener("change", () => {
        const f = fileInput.files[0];
        if (!f) return;
        if (f.size > 50 * 1024 * 1024) {
            toast("That file is larger than the 50 MB limit.", "error");
            fileInput.value = "";
            return;
        }
        pendingAttachment = f;
        pendingFileName.textContent = `${f.name} · ${fmtSize(f.size)}`;
        pendingFile.classList.remove("hidden");
        // Only images get the "photo vs file" choice.
        if (isImageFile(f)) setSendMode(true);
        else if (sendMode) sendMode.classList.add("hidden");
        composerInput.focus({ preventScroll: true });
        syncSendState();
    });
    pendingFileRemove.addEventListener("click", clearAttachment);

    if (modePhoto) modePhoto.addEventListener("click", () => setSendMode(true));
    if (modeFile) modeFile.addEventListener("click", () => setSendMode(false));

    // Drag & drop onto the chat pane
    const pane = document.querySelector(".pane");
    ["dragenter", "dragover"].forEach((ev) =>
        pane.addEventListener(ev, (e) => {
            if (!activeChatId) return;
            e.preventDefault();
        }));
    pane.addEventListener("drop", (e) => {
        if (!activeChatId || !e.dataTransfer?.files?.length) return;
        e.preventDefault();
        const dt = new DataTransfer();
        dt.items.add(e.dataTransfer.files[0]);
        fileInput.files = dt.files;
        fileInput.dispatchEvent(new Event("change"));
    });

    // Paste an image straight into the composer
    composerInput.addEventListener("paste", (e) => {
        const file = [...(e.clipboardData?.files || [])][0];
        if (!file) return;
        e.preventDefault();
        const dt = new DataTransfer();
        dt.items.add(file);
        fileInput.files = dt.files;
        fileInput.dispatchEvent(new Event("change"));
    });

    // ── Sending: text AND photos/files ──────────────────────────
    async function doSend() {
        if (sendInFlight || !activeChatId) return;
        const text = composerInput.value.trim();
        if (!text && !pendingAttachment) return;

        const chatIdAtStart = activeChatId;
        const attachment = pendingAttachment;
        const caption = text;
        const asPhoto = pendingSendAsPhoto;

        sendInFlight = true;
        syncSendState();

        // ── Optimistic bubble (instant feedback — no re-press) ──
        let tempEl = null;
        let localUrl = null;
        const tempId = --tmpIdCounter;
        const nowIso = new Date().toISOString();
        if (attachment && isImageFile(attachment)) {
            localUrl = URL.createObjectURL(attachment);
            tempEl = appendMessage(
                { id: tempId, text: caption, out: true, date: nowIso, media_type: "photo" },
                { pending: true, localSrc: localUrl });
        } else if (attachment) {
            tempEl = appendMessage(
                { id: tempId, text: caption, out: true, date: nowIso,
                  media_type: "document", media_name: attachment.name, media_size: attachment.size },
                { pending: true });
        } else {
            tempEl = appendMessage(
                { id: tempId, text: caption, out: true, date: nowIso },
                { pending: true });
        }
        scrollToBottom(true);

        // Clear the composer so it reads as "sent".
        composerInput.value = "";
        autoGrow();

        const removeTemp = () => {
            if (tempEl && tempEl.isConnected) tempEl.remove();
            if (localUrl) { URL.revokeObjectURL(localUrl); localUrl = null; }
        };

        try {
            const res = attachment
                ? await apiUpload(`/api/chats/${chatIdAtStart}/files`, buildUploadForm(attachment, caption, asPhoto))
                : await api(`/api/chats/${chatIdAtStart}/messages`, {
                    method: "POST", body: { text: caption },
                });

            removeTemp();
            // Confirm with the server's version of the message.
            if (activeChatId === chatIdAtStart) {
                appendMessage(res.message);
                scrollToBottom(true);
            }
            if (pendingAttachment === attachment) clearAttachment();
        } catch (err) {
            removeTemp();
            // Restore what the user typed/attached — but never clobber text the
            // user entered *while* the send was in flight.
            if (activeChatId === chatIdAtStart) {
                if (!composerInput.value.trim()) composerInput.value = caption;
                autoGrow();
            }
            toast(err.message, "error");
        } finally {
            sendInFlight = false;
            syncSendState();
            if (!MOBILE() && activeChatId === chatIdAtStart) composerInput.focus({ preventScroll: true });
        }
    }

    function buildUploadForm(file, caption, asPhoto) {
        const fd = new FormData();
        fd.append("file", file);
        if (caption) fd.append("caption", caption);
        // Only image attachments carry an explicit mode; other files use "auto".
        if (isImageFile(file)) fd.append("as_photo", asPhoto ? "true" : "false");
        return fd;
    }

    composer.addEventListener("submit", (e) => {
        e.preventDefault();
        doSend();
    });

    // ── Session ─────────────────────────────────────────────────
    $("logout-btn").addEventListener("click", async () => {
        try { await api("/api/auth/logout", { method: "POST" }); } catch { /* ignore */ }
        window.location.href = "/login";
    });

    // ── Boot ────────────────────────────────────────────────────
    syncSendState();
    renderSkeletons();
    loadIdentity().then((ok) => ok && loadChats());
    schedulePoll();   // start the self-scheduling auto-refresh loop
}

// ── Bootstrap ───────────────────────────────────────────────────

document.addEventListener("DOMContentLoaded", () => {
    const page = document.querySelector("[data-page]");
    if (!page) return;
    Theme.init();
    if (page.dataset.page === "login") initLoginPage();
    if (page.dataset.page === "index") initIndexPage();
});
