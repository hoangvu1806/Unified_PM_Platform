import {
    Check,
    ChevronDown,
    FilePenLine,
    Plus,
    Radio,
    RefreshCw,
    X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { normalizeMcpEndpoint } from "./connection";
import type { ConnectionSettings, OpenPencilDocument } from "./types";

interface Props {
    settings: ConnectionSettings;
    onChange: (value: ConnectionSettings) => void;
}

interface DocumentAlias {
    name: string;
    path: string;
}

const DOCUMENT_ALIASES_KEY = "designer.openpencil.document-aliases";

function readDocumentAliases(): Record<string, DocumentAlias> {
    try {
        return JSON.parse(
            localStorage.getItem(DOCUMENT_ALIASES_KEY) ?? "{}",
        ) as Record<string, DocumentAlias>;
    } catch {
        return {};
    }
}

export function WorkspacePicker({ settings, onChange }: Props) {
    const [open, setOpen] = useState(false);
    const [documents, setDocuments] = useState<OpenPencilDocument[]>([]);
    const [loading, setLoading] = useState(false);
    const [error, setError] = useState("");
    const [createMode, setCreateMode] = useState<"document" | "page" | null>(null);
    const [newName, setNewName] = useState("");
    const [creating, setCreating] = useState(false);
    const [aliases, setAliases] = useState<Record<string, DocumentAlias>>(
        readDocumentAliases,
    );
    const pickerRef = useRef<HTMLDivElement>(null);

    const selected = documents.find(
        (document) => document.id === settings.documentId,
    );
    const selectedPage = selected?.pages.find(
        (page) => page.id === settings.pageId,
    );

    useEffect(() => {
        if (!open) return;
        const closeOutside = (event: MouseEvent) => {
            if (
                pickerRef.current &&
                !pickerRef.current.contains(event.target as Node)
            ) {
                setOpen(false);
            }
        };
        const closeWithEscape = (event: KeyboardEvent) => {
            if (event.key === "Escape") setOpen(false);
        };
        document.addEventListener("mousedown", closeOutside);
        document.addEventListener("keydown", closeWithEscape);
        return () => {
            document.removeEventListener("mousedown", closeOutside);
            document.removeEventListener("keydown", closeWithEscape);
        };
    }, [open]);

    const loadDocuments = async () => {
        const endpoint = normalizeMcpEndpoint(settings.mcpEndpoint);
        if (!endpoint) {
            setError("OpenPencil MCP endpoint is not configured.");
            return;
        }
        setLoading(true);
        setError("");
        try {
            const items = await api.listOpenPencilDocuments(endpoint);
            const hydrated = items.map((document) => {
                const alias = aliases[document.id];
                return alias && !document.path
                    ? { ...document, path: alias.path }
                    : document;
            });
            setDocuments(hydrated);
            const saved = hydrated.find(
                (document) => document.id === settings.documentId,
            );
            const target = saved;
            if (target) {
                const pageId = target.pages.some(
                    (page) => page.id === settings.pageId,
                )
                    ? settings.pageId
                    : target.current_page_id ?? target.pages[0]?.id ?? "";
                onChange({
                    ...settings,
                    documentId: target.id,
                    documentPath: target.path ?? "",
                    documentName: target.name || "Untitled",
                    pageId,
                    pageName:
                        target.pages.find((page) => page.id === pageId)?.name ??
                        target.current_page_name ??
                        "",
                });
            }
        } catch (reason) {
            setDocuments([]);
            setError((reason as Error).message);
        } finally {
            setLoading(false);
        }
    };

    const toggle = () => {
        const next = !open;
        setOpen(next);
        if (next && documents.length === 0 && !loading) {
            void loadDocuments();
        }
    };

    const chooseDocument = (target: OpenPencilDocument) => {
        onChange({
            ...settings,
            documentId: target.id,
            documentPath: target.path ?? "",
            documentName: target.name || "Untitled",
            pageId: target.current_page_id ?? target.pages[0]?.id ?? "",
            pageName:
                target.current_page_name ?? target.pages[0]?.name ?? "",
        });
    };

    const beginCreate = (mode: "document" | "page") => {
        setCreateMode(mode);
        setNewName("");
        setError("");
    };

    const rememberDocument = (document: OpenPencilDocument) => {
        if (!document.name || document.name === "Untitled" || !document.path) {
            return;
        }
        setAliases((current) => {
            const next = {
                ...current,
                [document.id]: {
                    name: document.name,
                    path: document.path ?? "",
                },
            };
            localStorage.setItem(DOCUMENT_ALIASES_KEY, JSON.stringify(next));
            return next;
        });
    };

    const createTarget = async () => {
        const name = newName.trim();
        const endpoint = normalizeMcpEndpoint(settings.mcpEndpoint);
        if (!name || !endpoint || creating) return;
        if (createMode === "page" && !settings.documentId) {
            setError("Choose a document before creating a page.");
            return;
        }
        setCreating(true);
        setError("");
        try {
            const rawTarget =
                createMode === "document"
                    ? await api.createOpenPencilDocument(endpoint, name)
                    : await api.createOpenPencilPage(
                          endpoint,
                          settings.documentId,
                          name,
                      );
            const target = rawTarget;
            if (createMode === "document") rememberDocument(target);
            setDocuments((current) => [
                target,
                ...current
                    .filter((document) => document.id !== target.id)
                    .map((document) => ({
                        ...document,
                        active:
                            createMode === "document"
                                ? false
                                : document.active,
                    })),
            ]);
            chooseDocument(target);
            setCreateMode(null);
            setNewName("");
        } catch (reason) {
            setError((reason as Error).message);
        } finally {
            setCreating(false);
        }
    };

    const triggerLabel = selected?.name || settings.documentName ||
        (settings.documentId ? settings.documentPath || "Saved document" : "Choose workspace");
    const triggerPage = selectedPage?.name || selected?.current_page_name || settings.pageName;

    return (
        <div className="workspace-picker" ref={pickerRef}>
            <button
                type="button"
                className={`workspace-trigger ${open ? "active" : ""}`}
                onClick={toggle}
                aria-expanded={open}
                title="Choose the OpenPencil document and page"
            >
                <span className="workspace-trigger-icon">
                    <FilePenLine size={14} />
                    <i className={selected?.active ? "live" : ""} />
                </span>
                <span className="workspace-trigger-copy">
                    <strong>{triggerLabel}</strong>
                    <small>{triggerPage || "OpenPencil document"}</small>
                </span>
                <ChevronDown
                    size={13}
                    className={`dropdown-chevron ${open ? "rotate" : ""}`}
                />
            </button>

            {open && (
                <div className="workspace-menu">
                    <header>
                        <div>
                            <strong>OpenPencil workspace</strong>
                            <span>Select the file this conversation refers to.</span>
                        </div>
                        <div className="workspace-header-actions">
                            <button
                                type="button"
                                className="workspace-refresh"
                                onClick={() => beginCreate("document")}
                                disabled={creating}
                                title="Create document"
                            >
                                <Plus size={15} />
                            </button>
                            <button
                                type="button"
                                className="workspace-refresh"
                                onClick={() => void loadDocuments()}
                                disabled={loading || creating}
                                title="Refresh open documents"
                            >
                                <RefreshCw size={14} className={loading ? "spin" : ""} />
                            </button>
                        </div>
                    </header>

                    {createMode && (
                        <div className="workspace-create-row">
                            <input
                                autoFocus
                                value={newName}
                                onChange={(event) => setNewName(event.target.value)}
                                onKeyDown={(event) => {
                                    if (event.key === "Enter") {
                                        event.preventDefault();
                                        void createTarget();
                                    }
                                    if (event.key === "Escape") setCreateMode(null);
                                }}
                                maxLength={120}
                                placeholder={
                                    createMode === "document"
                                        ? "Document name"
                                        : "Page name"
                                }
                                aria-label={
                                    createMode === "document"
                                        ? "New document name"
                                        : "New page name"
                                }
                            />
                            <button
                                type="button"
                                onClick={() => void createTarget()}
                                disabled={!newName.trim() || creating}
                                title={`Create ${createMode}`}
                            >
                                {creating ? <RefreshCw size={14} className="spin" /> : <Check size={14} />}
                            </button>
                            <button
                                type="button"
                                onClick={() => setCreateMode(null)}
                                disabled={creating}
                                title="Cancel"
                            >
                                <X size={14} />
                            </button>
                        </div>
                    )}

                    {error && <p className="workspace-error">{error}</p>}
                    {!error && loading && documents.length === 0 && (
                        <p className="workspace-empty">Reading open tabs…</p>
                    )}
                    {!error && !loading && documents.length === 0 && (
                        <p className="workspace-empty">No OpenPencil documents are open.</p>
                    )}

                    <div className="workspace-documents" role="listbox">
                        {documents.map((document) => (
                            <button
                                key={document.id}
                                type="button"
                                role="option"
                                aria-selected={settings.documentId === document.id}
                                className={`workspace-document ${settings.documentId === document.id ? "selected" : ""}`}
                                onClick={() => chooseDocument(document)}
                            >
                                <FilePenLine size={15} />
                                <span>
                                    <strong>{document.name || "Untitled"}</strong>
                                    <small>{document.current_page_name || `${document.pages.length} pages`}</small>
                                </span>
                                {document.active && <Radio size={12} className="workspace-live" />}
                                {settings.documentId === document.id && <Check size={14} />}
                            </button>
                        ))}
                    </div>

                    {selected && (
                        <div className="workspace-page-row">
                            {selected.pages.length > 0 && (
                                <label className="workspace-page-picker">
                                    <span>Page</span>
                                    <select
                                        value={settings.pageId}
                                        onChange={(event) => {
                                            const pageId = event.target.value;
                                            onChange({
                                                ...settings,
                                                pageId,
                                                pageName:
                                                    selected.pages.find(
                                                        (page) => page.id === pageId,
                                                    )?.name ?? "",
                                            });
                                        }}
                                    >
                                        {selected.pages.map((page) => (
                                            <option key={page.id} value={page.id}>{page.name}</option>
                                        ))}
                                    </select>
                                </label>
                            )}
                            <button
                                type="button"
                                className="workspace-add-page"
                                onClick={() => beginCreate("page")}
                                disabled={creating}
                            >
                                <Plus size={13} />
                                New page
                            </button>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}
