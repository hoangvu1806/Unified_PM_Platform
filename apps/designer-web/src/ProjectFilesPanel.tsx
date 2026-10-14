import { AtSign, BookOpen, Download, FileJson, GripVertical, Layers, Plus, RefreshCw, Search } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import {
    KIND_LABEL,
    PROJECT_FILE_MIME,
    type ProjectFile,
    type ProjectFileKind,
    filterFiles,
    initials,
    listProjectFiles,
    requestAttach,
    timeAgo,
} from "./projectFiles";

const KIND_ICON: Record<ProjectFileKind, typeof FileJson> = {
    ba_package: FileJson,
    designer_output: Layers,
    wiki_source: BookOpen,
};

type Filter = "all" | ProjectFileKind;

const FILTERS: { id: Filter; label: string }[] = [
    { id: "all", label: "Tất cả" },
    { id: "ba_package", label: "BA" },
    { id: "wiki_source", label: "Wiki" },
    { id: "designer_output", label: "Thiết kế" },
];

export function ProjectFilesPanel({ onShowWorkbench }: { onShowWorkbench: () => void }) {
    const [files, setFiles] = useState<ProjectFile[] | null>(null);
    const [error, setError] = useState("");
    const [query, setQuery] = useState("");
    const [filter, setFilter] = useState<Filter>("all");

    const load = useCallback((force = false) => {
        setError("");
        listProjectFiles(force)
            .then(setFiles)
            .catch((e: Error) => setError(e.message));
    }, []);
    useEffect(() => load(), [load]);

    const visible = useMemo(
        () => filterFiles(files ?? [], query).filter((f) => filter === "all" || f.kind === filter),
        [files, query, filter],
    );

    return (
        <aside className="review-panel files-panel" aria-label="Project files">
            <header>
                <div>
                    <span className="eyebrow">Dự án</span>
                    <h2>Files dự án</h2>
                </div>
                <div className="files-header-actions">
                    <button className="icon-button" type="button" title="Tải lại" onClick={() => load(true)}>
                        <RefreshCw size={15} />
                    </button>
                    <button className="panel-switch" type="button" onClick={onShowWorkbench}>
                        Workbench
                    </button>
                </div>
            </header>

            <div className="files-toolbar">
                <label className="files-search">
                    <Search size={14} />
                    <input
                        value={query}
                        onChange={(e) => setQuery(e.target.value)}
                        placeholder="Tìm theo tên hoặc người tạo…"
                    />
                </label>
                <div className="files-filters">
                    {FILTERS.map((f) => (
                        <button
                            key={f.id}
                            type="button"
                            className={filter === f.id ? "active" : ""}
                            onClick={() => setFilter(f.id)}
                        >
                            {f.label}
                        </button>
                    ))}
                </div>
            </div>

            <div className="files-list">
                {error && <div className="files-empty files-error">{error}</div>}
                {!error && files === null && <div className="files-empty">Đang tải…</div>}
                {!error && files !== null && visible.length === 0 && (
                    <div className="files-empty">
                        {files.length === 0
                            ? "Dự án chưa có file chung. BA package, tài liệu wiki và thiết kế đã hoàn tất sẽ xuất hiện ở đây."
                            : "Không có file khớp bộ lọc."}
                    </div>
                )}
                {visible.map((file) => {
                    const Icon = KIND_ICON[file.kind];
                    return (
                        <article
                            key={`${file.kind}:${file.id}`}
                            className={`file-row kind-${file.kind} ${file.citable ? "" : "not-citable"}`}
                            draggable={file.citable}
                            onDragStart={(e) => {
                                e.dataTransfer.setData(PROJECT_FILE_MIME, JSON.stringify(file));
                                e.dataTransfer.setData("text/plain", `@${file.name}`);
                                e.dataTransfer.effectAllowed = "copy";
                            }}
                            title={file.citable ? "Kéo vào khung chat để đính kèm" : "File .fig không đính kèm vào chat được"}
                        >
                            {file.citable && <GripVertical size={14} className="file-grip" />}
                            <span className="file-icon">
                                <Icon size={16} />
                            </span>
                            <div className="file-main">
                                <div className="file-name">{file.title}</div>
                                <div className="file-meta">
                                    <span className="file-avatar" title={file.created_by ?? ""}>
                                        {initials(file.created_by_name)}
                                    </span>
                                    <span>{file.created_by_name ?? "—"}</span>
                                    <span className="file-dot">·</span>
                                    <span>{timeAgo(file.created_at)}</span>
                                </div>
                                <div className="file-tags">
                                    <span className="file-tag">{KIND_LABEL[file.kind]}</span>
                                    {file.version && <span className="file-tag">v{file.version}</span>}
                                    {file.scope === "company" && <span className="file-tag">Chung công ty</span>}
                                    {file.stale && <span className="file-tag warn">Cần xem lại</span>}
                                </div>
                            </div>
                            <div className="file-actions">
                                {file.citable && (
                                    <button
                                        type="button"
                                        className="icon-button"
                                        title="Đính kèm vào tin nhắn"
                                        onClick={() => requestAttach(file)}
                                    >
                                        <Plus size={15} />
                                    </button>
                                )}
                                <a className="icon-button" href={file.download_url} title="Tải xuống">
                                    <Download size={15} />
                                </a>
                            </div>
                        </article>
                    );
                })}
            </div>

            <footer className="files-hint">
                <AtSign size={13} /> Kéo file vào khung chat, bấm <Plus size={12} />, hoặc gõ <kbd>@</kbd> trong ô nhập để
                trích dẫn.
            </footer>
        </aside>
    );
}
