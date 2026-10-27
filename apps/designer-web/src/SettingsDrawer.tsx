import {
    CheckCircle2,
    Eye,
    Laptop,
    Moon,
    RefreshCw,
    Sun,
    Trash2,
    Upload,
    X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { projectId } from "./platform";
import { useTheme } from "./theme";
import type { DesignSystemInfo, Session } from "./types";

interface Props {
    session?: Session;
    onClose: () => void;
    onSessionChange: (session: Session) => void;
}

/** Appearance + design systems: choose the one a session renders with, import from a Figma .fig. */
export function SettingsDrawer({ session, onClose, onSessionChange }: Props) {
    const { theme, setTheme } = useTheme();
    const [systems, setSystems] = useState<DesignSystemInfo[]>([]);
    const [file, setFile] = useState<File>();
    const [name, setName] = useState("");
    const [busy, setBusy] = useState(false);
    const [result, setResult] = useState<{ message: string; ok: boolean }>();

    const load = useCallback(() => {
        api.listDesignSystems()
            .then(setSystems)
            .catch((error) => setResult({ message: (error as Error).message, ok: false }));
    }, []);

    useEffect(load, [load]);
    useEffect(() => {
        // Imports run in the background: refresh while one is in progress.
        if (!systems.some((s) => s.status === "importing")) return;
        const timer = window.setInterval(load, 2500);
        return () => window.clearInterval(timer);
    }, [systems, load]);

    const active = session?.design_system_id || "default";

    const choose = async (id: string) => {
        if (!session) return;
        try {
            onSessionChange(await api.setSessionDesignSystem(session.id, id));
            setResult({ message: "Đã đổi design system cho session này.", ok: true });
        } catch (error) {
            setResult({ message: (error as Error).message, ok: false });
        }
    };

    const importFig = async () => {
        if (!file) return;
        setBusy(true);
        setResult(undefined);
        try {
            await api.importDesignSystem(file, name.trim() || file.name.replace(/\.fig$/i, ""));
            setFile(undefined);
            setName("");
            setResult({ message: "Đang import… component sẽ xuất hiện khi xong.", ok: true });
            load();
        } catch (error) {
            setResult({ message: (error as Error).message, ok: false });
        } finally {
            setBusy(false);
        }
    };

    const remove = async (system: DesignSystemInfo) => {
        if (!window.confirm(`Xoá design system "${system.name}"?`)) return;
        try {
            await api.deleteDesignSystem(system.id);
            load();
        } catch (error) {
            setResult({ message: (error as Error).message, ok: false });
        }
    };

    const gallery = (id: string) => {
        const params = new URLSearchParams({ ds: id });
        if (projectId) params.set("project", projectId);
        window.open(`${import.meta.env.BASE_URL}canvas.html?${params}`, `designer-ds-${id}`);
    };

    return (
        <div className="drawer-backdrop" role="presentation" onMouseDown={onClose}>
            <aside
                className="settings-drawer"
                role="dialog"
                aria-modal="true"
                aria-label="Designer settings"
                onMouseDown={(event) => event.stopPropagation()}
            >
                <header>
                    <div>
                        <span className="eyebrow">Control Plane</span>
                        <h2>Workspace Settings</h2>
                    </div>
                    <button className="icon-button" onClick={onClose} title="Close settings" type="button">
                        <X size={18} />
                    </button>
                </header>

                <p className="drawer-intro">
                    Giao diện của studio và design system mà agent dùng để thiết kế.
                </p>

                <section>
                    <h3>Appearance & Theme</h3>
                    <div className="theme-options-grid">
                        <button type="button" className={`theme-option-btn ${theme === "light" ? "active" : ""}`}
                            onClick={() => setTheme("light")} title="Light theme">
                            <Sun size={20} />
                            <span>Light</span>
                        </button>
                        <button type="button" className={`theme-option-btn ${theme === "dark" ? "active" : ""}`}
                            onClick={() => setTheme("dark")} title="Dark theme">
                            <Moon size={20} />
                            <span>Dark</span>
                        </button>
                        <button type="button" className={`theme-option-btn ${theme === "system" ? "active" : ""}`}
                            onClick={() => setTheme("system")} title="Sync with system preference">
                            <Laptop size={20} />
                            <span>System</span>
                        </button>
                    </div>
                </section>

                <section>
                    <div className="section-heading">
                        <h3>Design system</h3>
                        <button className="secondary-button compact" type="button" onClick={load} title="Làm mới">
                            <RefreshCw size={14} />
                        </button>
                    </div>
                    <p className="field-note">
                        {session
                            ? `Session "${session.title}" dùng design system được chọn bên dưới.`
                            : "Mở một session để chọn design system cho nó."}
                    </p>
                    <div className="ds-list">
                        {systems.map((system) => (
                            <div key={system.id} className={`ds-item ${active === system.id ? "active" : ""}`}>
                                <label>
                                    <input
                                        type="radio"
                                        name="design-system"
                                        checked={active === system.id}
                                        disabled={!session || system.status !== "ready"}
                                        onChange={() => void choose(system.id)}
                                    />
                                    <span>
                                        <strong>{system.name}</strong>
                                        <small>
                                            {system.status === "importing"
                                                ? "Đang import…"
                                                : system.status === "failed"
                                                  ? `Lỗi: ${system.error ?? ""}`
                                                  : system.id === "default"
                                                    ? "Tailwind + token trung tính"
                                                    : `${system.summary.components ?? 0} component · ${system.source_name ?? ".fig"}`}
                                        </small>
                                    </span>
                                </label>
                                {system.id !== "default" && system.status === "ready" && (
                                    <button className="icon-button" type="button" title="Xem component" onClick={() => gallery(system.id)}>
                                        <Eye size={15} />
                                    </button>
                                )}
                                {system.id !== "default" && (
                                    <button className="icon-button" type="button" title="Xoá" onClick={() => void remove(system)}>
                                        <Trash2 size={15} />
                                    </button>
                                )}
                            </div>
                        ))}
                    </div>

                    <h3>Import từ Figma (.fig)</h3>
                    <p className="field-note">
                        Trong Figma: File → Save local copy. Token màu, chữ, đổ bóng và component sẽ được chuyển sang HTML + Tailwind.
                    </p>
                    <label>
                        File .fig
                        <input type="file" accept=".fig" onChange={(event) => setFile(event.target.files?.[0])} />
                    </label>
                    <label>
                        Tên
                        <input value={name} onChange={(event) => setName(event.target.value)}
                            placeholder={file?.name.replace(/\.fig$/i, "") || "Design system của dự án"} />
                    </label>
                    <button className="primary-button" type="button" disabled={!file || busy} onClick={() => void importFig()}>
                        <Upload size={15} /> {busy ? "Đang tải lên…" : "Import"}
                    </button>
                    {result && (
                        <p className={`field-note ${result.ok ? "" : "error"}`}>
                            {result.ok && <CheckCircle2 size={14} />} {result.message}
                        </p>
                    )}
                </section>
            </aside>
        </div>
    );
}
