import {
    CheckCircle2,
    Laptop,
    Moon,
    RefreshCw,
    Sun,
    X,
} from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "./api";
import { useTheme } from "./theme";
import type { ConnectionSettings, DesignSystemInfo } from "./types";

interface Props {
    value: ConnectionSettings;
    onClose: () => void;
    onSave: (value: ConnectionSettings) => void;
    onLoadComponents: (
        value: ConnectionSettings,
    ) => Promise<
        { component_id: string; name: string; canonical_path: string }[]
    >;
}

export function SettingsDrawer({
    value,
    onClose,
    onSave,
    onLoadComponents,
}: Props) {
    const [draft, setDraft] = useState(value);
    const [designSystems, setDesignSystems] = useState<DesignSystemInfo[]>([]);
    const [result, setResult] = useState<{ message: string; ok: boolean }>();
    const [busy, setBusy] = useState(false);
    const [customSourceMode, setCustomSourceMode] = useState(false);
    const { theme, setTheme } = useTheme();
    const selectedSourceId =
        customSourceMode
            ? "__custom__"
            : designSystems.find((system) => system.path === draft.sourceFile)?.id ??
              (draft.sourceFile ? "__custom__" : "");

    useEffect(() => {
        api.listDesignSystems()
            .then(setDesignSystems)
            .catch(() => undefined);
    }, []);

    useEffect(() => {
        const handleKeyDown = (e: KeyboardEvent) => {
            if (e.key === "Escape") onClose();
        };
        window.addEventListener("keydown", handleKeyDown);
        return () => window.removeEventListener("keydown", handleKeyDown);
    }, [onClose]);

    const sync = async () => {
        setBusy(true);
        try {
            const items = await onLoadComponents(draft);
            setResult({
                message: `Synced ${items.length} components.`,
                ok: true,
            });
        } catch (error) {
            setResult({ message: (error as Error).message, ok: false });
        } finally {
            setBusy(false);
        }
    };

    return (
        <div
            className="drawer-backdrop"
            role="presentation"
            onMouseDown={onClose}
        >
            <aside
                className="settings-drawer"
                role="dialog"
                aria-modal="true"
                aria-label="Agentic Designer Settings"
                onMouseDown={(event) => event.stopPropagation()}
            >
                <header>
                    <div>
                        <span className="eyebrow">Control Plane</span>
                        <h2>Workspace Settings</h2>
                    </div>
                    <button
                        className="icon-button"
                        onClick={onClose}
                        title="Close settings"
                        type="button"
                    >
                        <X size={18} />
                    </button>
                </header>

                <p className="drawer-intro">
                    Configure visual appearance and read-only component library
                    sources.
                </p>

                {/* Section: Appearance & Theme */}
                <section>
                    <h3>Appearance & Theme</h3>
                    <div className="theme-options-grid">
                        <button
                            type="button"
                            className={`theme-option-btn ${theme === "light" ? "active" : ""}`}
                            onClick={() => setTheme("light")}
                            title="Light theme"
                        >
                            <Sun size={20} />
                            <span>Light</span>
                        </button>
                        <button
                            type="button"
                            className={`theme-option-btn ${theme === "dark" ? "active" : ""}`}
                            onClick={() => setTheme("dark")}
                            title="Dark theme"
                        >
                            <Moon size={20} />
                            <span>Dark</span>
                        </button>
                        <button
                            type="button"
                            className={`theme-option-btn ${theme === "system" ? "active" : ""}`}
                            onClick={() => setTheme("system")}
                            title="Sync with system preference"
                        >
                            <Laptop size={20} />
                            <span>System</span>
                        </button>
                    </div>
                </section>

                {/* Section: Files */}
                <section>
                    <h3>Design System & Files</h3>
                    <label>
                        OpenPencil MCP endpoint
                        <input
                            value={draft.mcpEndpoint}
                            onChange={(event) =>
                                setDraft({
                                    ...draft,
                                    mcpEndpoint: event.target.value,
                                })
                            }
                            placeholder="http://host.docker.internal:7600/mcp"
                        />
                    </label>
                    <p className="field-note">
                        For the Docker setup, use 
                        <code>http://host.docker.internal:7600/mcp</code>.
                    </p>
                    <label>
                        Component Source (.fig)
                        {designSystems.length > 0 ? (
                            <select
                                value={selectedSourceId}
                                onChange={(event) => {
                                    const selected = designSystems.find(
                                        (system) => system.id === event.target.value,
                                    );
                                    if (selected) {
                                        setCustomSourceMode(false);
                                        setDraft({
                                            ...draft,
                                            sourceFile: selected.path,
                                            knowledgeId: selected.knowledge_id,
                                        });
                                    } else if (event.target.value === "__custom__") {
                                        setCustomSourceMode(true);
                                        setDraft({ ...draft, sourceFile: "" });
                                    } else {
                                        setCustomSourceMode(false);
                                        setDraft({ ...draft, sourceFile: "" });
                                    }
                                }}
                            >
                                <option value="">
                                    -- Select an installed design system --
                                </option>
                                {designSystems.map((system) => (
                                    <option key={system.id} value={system.id}>
                                        {system.name}
                                    </option>
                                ))}
                                <option value="__custom__">Custom path...</option>
                            </select>
                        ) : (
                            <input
                                value={draft.sourceFile}
                                onChange={(event) =>
                                    setDraft({
                                        ...draft,
                                        sourceFile: event.target.value,
                                    })
                                }
                                placeholder="Full path to a .fig file"
                            />
                        )}
                    </label>
                    {designSystems.length > 0 && selectedSourceId === "__custom__" && (
                        <label>
                            Custom component source path
                            <input
                                value={draft.sourceFile}
                                onChange={(event) =>
                                    setDraft({
                                        ...draft,
                                        sourceFile: event.target.value,
                                    })
                                }
                                placeholder="Full path to a .fig file"
                            />
                        </label>
                    )}
                    <label>
                        Component Knowledge
                        <select
                            value={draft.knowledgeId}
                            onChange={(event) =>
                                setDraft({
                                    ...draft,
                                    knowledgeId: event.target
                                        .value as ConnectionSettings["knowledgeId"],
                                })
                            }
                        >
                            <option value="auto">
                                Auto detect from source file
                            </option>
                            <option value="shadcn-ui">shadcn/ui catalog</option>
                            <option value="taptap">TapTap catalog</option>
                        </select>
                    </label>
                    <p className="field-note">
                        The source `.fig` is read directly from disk and is
                        separate from the working document selected below the
                        message input.
                    </p>
                </section>

                {/* Section: Component Catalog */}
                <section>
                    <div
                        className="section-heading"
                        style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            marginBottom: "12px",
                        }}
                    >
                        <h3 style={{ margin: 0 }}>Component Catalog</h3>
                        <button
                            className="secondary-button compact"
                            onClick={sync}
                            disabled={busy}
                            type="button"
                        >
                            <RefreshCw
                                size={13}
                                className={busy ? "spin" : ""}
                            />
                            <span>{busy ? "Syncing..." : "Sync Catalog"}</span>
                        </button>
                    </div>
                    {result && (
                        <div className={`catalog-result ${result.ok ? "success" : "error"}`}>
                            {result.ok ? <CheckCircle2 size={14} /> : <X size={14} />}
                            <span>{result.message}</span>
                        </div>
                    )}
                </section>

                <footer>
                    <button
                        className="secondary-button"
                        onClick={onClose}
                        type="button"
                    >
                        Cancel
                    </button>
                    <button
                        className="primary-button"
                        onClick={() => onSave(draft)}
                        type="button"
                    >
                        Save Settings
                    </button>
                </footer>
            </aside>
        </div>
    );
}
