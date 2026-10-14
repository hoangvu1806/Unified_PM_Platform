// Platform context for the Designer UI (Sprint 3): login, project, read-only.
// Imported first by main.tsx so the project is known before App renders.

const STORAGE_KEY = "platform.projectId";
const API_BASE = import.meta.env.VITE_API_BASE_URL as string;

function toLogin(): void {
    const next = window.location.pathname + window.location.search;
    window.location.assign(`/login?next=${encodeURIComponent(next)}`);
}

function readProjectId(): string {
    const params = new URLSearchParams(window.location.search);
    const fromUrl = (params.get("project") || params.get("project_id") || "").trim();
    if (fromUrl) {
        try {
            sessionStorage.setItem(STORAGE_KEY, fromUrl);
        } catch {
            /* private mode */
        }
        return fromUrl;
    }
    try {
        return sessionStorage.getItem(STORAGE_KEY) || "";
    } catch {
        return "";
    }
}

export const projectId = readProjectId();

const nativeFetch = window.fetch.bind(window);
window.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    const res = await nativeFetch(input, init);
    const url = typeof input === "string" ? input : input instanceof URL ? input.href : input.url;
    if (res.status === 401 && API_BASE && url.includes(API_BASE)) toLogin();
    return res;
};

const BAR_CSS = `
#platformBar{position:sticky;top:0;z-index:1000;display:flex;align-items:center;gap:14px;height:34px;padding:0 16px;
  background:#0d0d10;border-bottom:1px solid #27272a;font:12px Inter,system-ui,sans-serif;color:#a1a1aa}
#platformBar a{color:#a855f7;text-decoration:none}
#platformBar .pb-project{color:#f4f4f5;font-weight:600}
#platformBar .pb-spacer{flex:1}
#platformBar .pb-role{padding:1px 7px;border-radius:20px;border:1px solid #3f3f46;font-size:10px;letter-spacing:.06em}
#platformBar .pb-ro{color:#f59e0b;border-color:rgba(245,158,11,.5)}
#platformBar button{background:none;border:0;color:#a1a1aa;cursor:pointer;font:inherit}
body.platform-readonly .composer-wrapper, body.platform-readonly .chat-review-actions,
body.platform-readonly .new-session { display:none !important; }
`;

export type PlatformContext = {
    user: { id: string; username: string; name: string; roles: string[] };
    project: { id: string; name: string; my_roles: string[] };
    readOnly: boolean;
};

function esc(value: unknown): string {
    return String(value ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]!);
}

function renderBar(ctx: PlatformContext): void {
    const style = document.createElement("style");
    style.textContent = BAR_CSS;
    document.head.appendChild(style);
    const bar = document.createElement("div");
    bar.id = "platformBar";
    bar.innerHTML = `
      <a href="/">← Dự án</a>
      <span class="pb-project">${esc(ctx.project.name)}</span>
      <span>${esc(ctx.project.id)}</span>
      <span class="pb-spacer"></span>
      ${ctx.readOnly ? '<span class="pb-role pb-ro">CHỈ ĐỌC</span>' : ""}
      ${ctx.project.my_roles.map((r) => `<span class="pb-role">${esc(r)}</span>`).join("")}
      <span>${esc(ctx.user.name)}</span>
      <button type="button" id="pbLogout">Đăng xuất</button>`;
    document.body.prepend(bar);
    bar.querySelector("#pbLogout")?.addEventListener("click", async () => {
        await nativeFetch("/api/core/auth/logout", { method: "POST" }).catch(() => undefined);
        window.location.assign("/login");
    });
}

/** Resolves once user and project are known; otherwise redirects away. */
export const platformReady: Promise<PlatformContext> = (async () => {
    const never = new Promise<PlatformContext>(() => undefined);
    const meRes = await nativeFetch("/api/core/me", { credentials: "same-origin" });
    if (meRes.status === 401) {
        toLogin();
        return never;
    }
    if (!projectId) {
        window.location.assign("/");
        return never;
    }
    const pRes = await nativeFetch(`/api/core/projects/${encodeURIComponent(projectId)}`);
    if (!pRes.ok) {
        window.location.assign("/");
        return never;
    }
    const ctx: PlatformContext = {
        user: await meRes.json(),
        project: await pRes.json(),
        readOnly: false,
    };
    const roles = ctx.project.my_roles ?? [];
    ctx.readOnly = !roles.includes("DESIGNER") && !roles.includes("ADMIN");
    if (ctx.readOnly) document.body.classList.add("platform-readonly");
    renderBar(ctx);
    return ctx;
})();
