import type {
    DesignSystemInfo,
    ExactAsset,
    ParsedAttachment,
    Run,
    RunArtifacts,
    Screen,
    ScreenVersion,
    Session,
} from "./types";

import { projectId } from "./platform";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

if (!API_BASE) throw new Error("VITE_API_BASE_URL is required");

async function failure(response: Response): Promise<Error> {
    const problem = (await response
        .json()
        .catch(() => ({ detail: response.statusText }))) as {
        detail?: string | { loc?: (string | number)[]; msg?: string }[] | { message?: string };
        title?: string;
    };
    const detail = problem.detail;
    const message = Array.isArray(detail)
        ? detail
              .map(
                  (item) =>
                      `${item.loc?.slice(1).join(".") || "request"}: ${item.msg || "invalid value"}`,
              )
              .join("; ")
        : typeof detail === "object" && detail
          ? detail.message || problem.title || "Request failed"
          : detail || problem.title || "Request failed";
    return new Error(message);
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
        ...init,
        headers: { "Content-Type": "application/json", ...init?.headers },
    });
    if (!response.ok) throw await failure(response);
    if (response.status === 204) return undefined as T;
    return response.json() as Promise<T>;
}

async function text(path: string): Promise<string> {
    const response = await fetch(`${API_BASE}${path}`);
    if (!response.ok) throw await failure(response);
    return response.text();
}

function fileAsBase64(file: File): Promise<string> {
    return new Promise((resolve, reject) => {
        const reader = new FileReader();
        reader.onerror = () => reject(new Error(`Could not read ${file.name}`));
        reader.onload = () => {
            const value = String(reader.result ?? "");
            resolve(value.slice(value.indexOf(",") + 1));
        };
        reader.readAsDataURL(file);
    });
}

const projectQuery = () => (projectId ? `?project_id=${encodeURIComponent(projectId)}` : "");

export const api = {
    parseAttachment: async (file: File) =>
        request<ParsedAttachment>("/attachments/parse", {
            method: "POST",
            body: JSON.stringify({
                name: file.name,
                mime_type: file.type,
                data_base64: await fileAsBase64(file),
            }),
        }),
    listSessions: () => request<Session[]>(`/sessions${projectQuery()}`),
    getSessions: () => request<Session[]>(`/sessions${projectQuery()}`),
    createSession: (title: string) =>
        request<Session>("/sessions", {
            method: "POST",
            body: JSON.stringify({ title, project_id: projectId || undefined }),
        }),
    deleteSession: (sessionId: string) =>
        request<{ status: string }>(`/sessions/${sessionId}`, {
            method: "DELETE",
        }),
    listRuns: (sessionId: string) =>
        request<Run[]>(`/sessions/${sessionId}/runs`),
    getRun: (runId: string) => request<Run>(`/runs/${runId}`),
    getArtifacts: (runId: string) =>
        request<RunArtifacts>(`/runs/${runId}/artifacts`),
    sendMessage: (
        sessionId: string,
        body: {
            content: string;
            screen_name_hint?: string;
            platform_hint?: string;
            style_hint?: string;
            library_ids: string[];
            assets?: ExactAsset[];
        },
    ) =>
        request<Run>(`/sessions/${sessionId}/messages`, {
            method: "POST",
            body: JSON.stringify(body),
        }),
    review: (
        runId: string,
        revision: number,
        checkpoint: "specification" | "final",
        decision: string,
        feedback = "",
    ) =>
        request<{ status: string }>(`/runs/${runId}/reviews`, {
            method: "POST",
            body: JSON.stringify({ checkpoint, decision, revision, feedback }),
        }),
    retry: (runId: string) =>
        request<{ status: string }>(`/runs/${runId}/retry`, { method: "POST" }),
    cancel: (runId: string) =>
        request<{ status: string }>(`/runs/${runId}/cancel`, {
            method: "POST",
        }),

    // Screens (HTML designer)
    listScreens: (sessionId: string) =>
        request<Screen[]>(`/sessions/${sessionId}/screens`),
    getScreen: (sessionId: string, screenId: string, version?: number) =>
        request<Screen>(
            `/sessions/${sessionId}/screens/${screenId}${version ? `?version=${version}` : ""}`,
        ),
    saveScreen: (
        sessionId: string,
        screenId: string,
        body: { name: string; platform: string; html: string; note?: string },
    ) =>
        request<Screen>(`/sessions/${sessionId}/screens/${screenId}`, {
            method: "PUT",
            body: JSON.stringify(body),
        }),
    screenVersions: (sessionId: string, screenId: string) =>
        request<ScreenVersion[]>(`/sessions/${sessionId}/screens/${screenId}/versions`),
    screenDocument: (sessionId: string, screenId: string, version?: number) =>
        text(
            `/sessions/${sessionId}/screens/${screenId}/document${version ? `?version=${version}` : ""}`,
        ),
    screenshotUrl: (sessionId: string, screenId: string, state?: string) =>
        `${API_BASE}/sessions/${sessionId}/screens/${screenId}/screenshot?format=png${state ? `&state=${encodeURIComponent(state)}` : ""}`,
    exportUrl: (sessionId: string, format: "fig" | "zip") =>
        `${API_BASE}/sessions/${sessionId}/export?format=${format}`,

    // Design systems
    listDesignSystems: () =>
        request<DesignSystemInfo[]>(`/design-systems${projectQuery()}`),
    importDesignSystem: async (file: File, name: string) => {
        const params = new URLSearchParams({ name, filename: file.name });
        if (projectId) params.set("project_id", projectId);
        const response = await fetch(`${API_BASE}/design-systems?${params}`, {
            method: "POST",
            headers: { "Content-Type": "application/octet-stream" },
            body: file,
        });
        if (!response.ok) throw await failure(response);
        return (await response.json()) as DesignSystemInfo;
    },
    deleteDesignSystem: (id: string) =>
        request<void>(`/design-systems/${id}`, { method: "DELETE" }),
    galleryDocument: (id: string, page = 0, q = "") =>
        text(`/design-systems/${id}/gallery?page=${page}&q=${encodeURIComponent(q)}`),
    setSessionDesignSystem: (sessionId: string, designSystemId: string) =>
        request<Session>(`/sessions/${sessionId}/design-system`, {
            method: "PUT",
            body: JSON.stringify({ design_system_id: designSystemId }),
        }),

    eventUrl: (runId: string) => `${API_BASE}/runs/${runId}/events`,
};

/** URL of the design page (canvas) for a session; one browser tab per session. */
export function canvasUrl(sessionId: string): string {
    const params = new URLSearchParams({ session: sessionId });
    if (projectId) params.set("project", projectId);
    return `${import.meta.env.BASE_URL}canvas.html?${params}`;
}
