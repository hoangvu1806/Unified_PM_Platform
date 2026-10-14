// Platform context for the Designer UI: login, project, read-only.
// Imported first by main.tsx so the project is known before App renders.
// The project/user/role are shown inside WorkspaceHeader (usePlatform).
import { useEffect, useState } from "react";

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

// Read-only members: hide the composer, review actions and "New Session".
const READONLY_CSS = `
body.platform-readonly .composer-wrapper, body.platform-readonly .chat-review-actions,
body.platform-readonly .new-session { display:none !important; }
`;

export type PlatformContext = {
    user: { id: string; username: string; name: string; roles: string[] };
    project: { id: string; name: string; my_roles: string[] };
    readOnly: boolean;
};

export async function logout(): Promise<void> {
    await nativeFetch("/api/core/auth/logout", { method: "POST" }).catch(() => undefined);
    window.location.assign("/login");
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
    if (ctx.readOnly) {
        const style = document.createElement("style");
        style.textContent = READONLY_CSS;
        document.head.appendChild(style);
        document.body.classList.add("platform-readonly");
    }
    return ctx;
})();

/** Platform context for React components (undefined while loading). */
export function usePlatform(): PlatformContext | undefined {
    const [ctx, setCtx] = useState<PlatformContext>();
    useEffect(() => {
        let alive = true;
        platformReady.then((value) => alive && setCtx(value));
        return () => {
            alive = false;
        };
    }, []);
    return ctx;
}
