import type {
    OpenPencilDocument,
    OpenPencilProfile,
    ParsedAttachment,
    Run,
    RunArtifacts,
    Session,
    ExactAsset,
} from "./types";

import { projectId } from "./platform";

const API_BASE = import.meta.env.VITE_API_BASE_URL;

if (!API_BASE) throw new Error("VITE_API_BASE_URL is required");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
    const response = await fetch(`${API_BASE}${path}`, {
        ...init,
        headers: { "Content-Type": "application/json", ...init?.headers },
    });
    if (!response.ok) {
        const problem = (await response
            .json()
            .catch(() => ({ detail: response.statusText }))) as {
            detail?: string | { loc?: (string | number)[]; msg?: string }[];
        };
        const message = Array.isArray(problem.detail)
            ? problem.detail
                  .map(
                      (item) =>
                          `${item.loc?.slice(1).join(".") || "request"}: ${item.msg || "invalid value"}`,
                  )
                  .join("; ")
            : problem.detail || "Request failed";
        throw new Error(message);
    }
    return response.json() as Promise<T>;
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
    listSessions: () =>
        request<Session[]>(
            projectId ? `/sessions?project_id=${encodeURIComponent(projectId)}` : "/sessions",
        ),
    createSession: (title: string) =>
        request<Session>("/sessions", {
            method: "POST",
            body: JSON.stringify({ title, project_id: projectId || undefined }),
        }),
    deleteSession: (sessionId: string) =>
        request<{ status: string }>(`/sessions/${sessionId}`, {
            method: "DELETE",
        }),
    updateSessionWorkspace: (
        sessionId: string,
        workspace: import("./types").SessionWorkspace,
    ) =>
        request<Session>(`/sessions/${sessionId}/workspace`, {
            method: "PUT",
            body: JSON.stringify(workspace),
        }),
    listRuns: (sessionId: string) =>
        request<Run[]>(`/sessions/${sessionId}/runs`),
    getRun: (runId: string) => request<Run>(`/runs/${runId}`),
    getArtifacts: (runId: string) =>
        request<RunArtifacts>(`/runs/${runId}/artifacts`),
    createRun: (
        sessionId: string,
        body: {
            prompt: string;
            screen_name: string;
            platform: string;
            style_name?: string;
            library_ids: string[];
            mcp_profile?: OpenPencilProfile;
            assets?: ExactAsset[];
        },
    ) =>
        request<Run>(`/sessions/${sessionId}/runs`, {
            method: "POST",
            body: JSON.stringify(body),
        }),
    sendMessage: (
        sessionId: string,
        body: {
            content: string;
            screen_name_hint?: string;
            platform_hint?: string;
            style_hint?: string;
            library_ids: string[];
            mcp_profile?: OpenPencilProfile;
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
        mcpProfile?: OpenPencilProfile,
    ) =>
        request<{ status: string }>(`/runs/${runId}/reviews`, {
            method: "POST",
            body: JSON.stringify({
                checkpoint,
                decision,
                revision,
                feedback,
                mcp_profile: mcpProfile,
            }),
        }),
    retry: (runId: string, mcpProfile?: OpenPencilProfile) =>
        request<{ status: string }>(`/runs/${runId}/retry`, {
            method: "POST",
            body: JSON.stringify({ mcp_profile: mcpProfile }),
        }),
    recheckLayout: (runId: string) =>
        request<{
            status: string;
            layout_review: NonNullable<RunArtifacts["layout_review"]>;
        }>(`/runs/${runId}/layout/recheck`, { method: "POST" }),
    syncCanvas: (runId: string) =>
        request<{ status: string; canvas_sync: Record<string, unknown> }>(
            `/runs/${runId}/canvas/sync`,
            { method: "POST" },
        ),
    downloadRunFile: (runId: string) => `${API_BASE}/runs/${runId}/download`,
    cancel: (runId: string) =>
        request<{ status: string }>(`/runs/${runId}/cancel`, {
            method: "POST",
        }),
    probeMcp: (endpoint: string) =>
        request<{ reachable: boolean; message: string }>(
            "/integrations/openpencil/probe",
            {
                method: "POST",
                body: JSON.stringify({ endpoint }),
            },
        ),
    listOpenPencilDocuments: (endpoint: string) =>
        request<OpenPencilDocument[]>("/integrations/openpencil/documents", {
            method: "POST",
            body: JSON.stringify({ endpoint }),
        }),
    createOpenPencilDocument: (endpoint: string, name: string) =>
        request<OpenPencilDocument>(
            "/integrations/openpencil/documents/create",
            {
                method: "POST",
                body: JSON.stringify({ endpoint, name }),
            },
        ),
    createOpenPencilPage: (
        endpoint: string,
        documentId: string,
        name: string,
    ) =>
        request<OpenPencilDocument>(
            `/integrations/openpencil/documents/${encodeURIComponent(documentId)}/pages`,
            {
                method: "POST",
                body: JSON.stringify({ endpoint, name }),
            },
        ),
    listComponents: (profile: OpenPencilProfile) =>
        request<
            { component_id: string; name: string; canonical_path: string }[]
        >("/integrations/openpencil/components", {
            method: "POST",
            body: JSON.stringify(profile),
        }),
    listDesignSystems: () =>
        request<import("./types").DesignSystemInfo[]>("/design-systems"),
    eventUrl: (runId: string) => `${API_BASE}/runs/${runId}/events`,
};
