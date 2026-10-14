import type { ConnectionSettings, OpenPencilProfile } from "./types";

const EMPTY_SETTINGS: ConnectionSettings = {
    mcpEndpoint: "http://127.0.0.1:7600/mcp",
    sourceFile: "",
    knowledgeId: "auto",
    documentId: "",
    documentPath: "",
    documentName: "",
    pageId: "",
    pageName: "",
};

export function readSettings(): ConnectionSettings {
    try {
        const saved = JSON.parse(
            localStorage.getItem("designer.connection") ?? "{}",
        ) as Partial<ConnectionSettings>;
        return {
            mcpEndpoint:
                normalizeMcpEndpoint(saved.mcpEndpoint) ||
                "http://127.0.0.1:7600/mcp",
            sourceFile: saved.sourceFile?.trim() ?? "",
            knowledgeId:
                saved.knowledgeId === "shadcn-ui" ||
                saved.knowledgeId === "taptap"
                    ? saved.knowledgeId
                    : "auto",
            documentId: saved.documentId?.trim() ?? "",
            documentPath: saved.documentPath?.trim() ?? "",
            documentName: saved.documentName?.trim() ?? "",
            pageId: saved.pageId?.trim() ?? "",
            pageName: saved.pageName?.trim() ?? "",
        };
    } catch {
        return { ...EMPTY_SETTINGS };
    }
}

export function normalizeMcpEndpoint(value?: string): string {
    const trimmed = value?.trim() ?? "";
    if (!trimmed) return "";
    try {
        const url = new URL(trimmed);
        if (!url.pathname || url.pathname === "/") url.pathname = "/mcp";
        return url.toString().replace(/\/$/, "");
    } catch {
        return trimmed;
    }
}

export function mcpProfile(
    settings: ConnectionSettings,
): OpenPencilProfile | undefined {
    const endpoint = normalizeMcpEndpoint(settings.mcpEndpoint);
    const sourceFile = settings.sourceFile.trim();
    if (!endpoint || !sourceFile) return undefined;
    return {
        endpoint,
        source_file: sourceFile,
        output_file: settings.documentPath || undefined,
        target_mode: settings.documentPath ? "existing_file" : "new_file",
        knowledge_id: settings.knowledgeId,
    };
}

export function requireMcpProfile(
    settings: ConnectionSettings,
): OpenPencilProfile {
    const profile = mcpProfile(settings);
    if (!profile) {
        throw new Error(
            "Complete the MCP endpoint and component source in Settings.",
        );
    }
    return profile;
}
