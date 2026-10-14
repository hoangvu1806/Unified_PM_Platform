// Shared project files (core-api) for the Files panel, drag & drop and @-mentions.
// Cited files go through the normal attachment flow: they are fetched in the
// browser, turned into File objects and parsed like a file dropped from disk.
import { projectId } from "./platform";

export type ProjectFileKind = "ba_package" | "designer_output" | "wiki_source";

export type ProjectFile = {
    id: string;
    kind: ProjectFileKind;
    name: string;
    title: string;
    version: number | null;
    stale: boolean;
    created_by: string | null;
    created_by_name: string | null;
    created_at: string;
    scope: "project" | "company";
    citable: boolean;
    download_url: string;
};

/** dataTransfer type used when dragging a project file inside the app. */
export const PROJECT_FILE_MIME = "application/x-platform-file";
/** window event: "attach this project file to the current message". */
export const ATTACH_EVENT = "platform:attach-file";

export const KIND_LABEL: Record<ProjectFileKind, string> = {
    ba_package: "BA package",
    designer_output: "Thiết kế",
    wiki_source: "Wiki",
};

let cache: Promise<ProjectFile[]> | null = null;

export function listProjectFiles(force = false): Promise<ProjectFile[]> {
    if (!projectId) return Promise.resolve([]);
    if (!cache || force) {
        cache = fetch(`/api/core/projects/${encodeURIComponent(projectId)}/files`, {
            credentials: "same-origin",
        }).then(async (res) => {
            if (!res.ok) throw new Error(`Không tải được files dự án (${res.status})`);
            return (await res.json()) as ProjectFile[];
        });
        cache.catch(() => {
            cache = null;
        });
    }
    return cache;
}

export async function toBrowserFile(file: ProjectFile): Promise<File> {
    const res = await fetch(file.download_url, { credentials: "same-origin" });
    if (!res.ok) throw new Error(`Không tải được ${file.name} (${res.status})`);
    const blob = await res.blob();
    const type =
        blob.type ||
        (file.name.endsWith(".json") ? "application/json" : file.name.endsWith(".md") ? "text/markdown" : "");
    return new File([blob], file.name, { type });
}

export function requestAttach(file: ProjectFile): void {
    window.dispatchEvent(new CustomEvent<ProjectFile>(ATTACH_EVENT, { detail: file }));
}

export function readDraggedFile(data: DataTransfer): ProjectFile | null {
    const raw = data.getData(PROJECT_FILE_MIME);
    if (!raw) return null;
    try {
        return JSON.parse(raw) as ProjectFile;
    } catch {
        return null;
    }
}

export function filterFiles(files: ProjectFile[], query: string): ProjectFile[] {
    const q = query.trim().toLowerCase();
    if (!q) return files;
    return files.filter(
        (f) =>
            f.name.toLowerCase().includes(q) ||
            f.title.toLowerCase().includes(q) ||
            (f.created_by_name ?? "").toLowerCase().includes(q),
    );
}

export function timeAgo(iso: string): string {
    const then = new Date(iso).getTime();
    if (Number.isNaN(then)) return "";
    const minutes = Math.round((Date.now() - then) / 60000);
    if (minutes < 1) return "vừa xong";
    if (minutes < 60) return `${minutes} phút trước`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `${hours} giờ trước`;
    const days = Math.round(hours / 24);
    if (days < 30) return `${days} ngày trước`;
    return new Date(iso).toLocaleDateString();
}

export function initials(name: string | null): string {
    const parts = (name ?? "?").replace(/\(.*\)/, "").trim().split(/\s+/);
    return (parts[0]?.[0] ?? "?").toUpperCase() + (parts[1]?.[0] ?? "").toUpperCase();
}
