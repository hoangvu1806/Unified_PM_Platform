import { Moon, PanelRight, Settings2, Sun } from "lucide-react";
import type { Run, Session } from "./types";

export function WorkspaceHeader({
    session,
    run,
    theme,
    reviewOpen,
    onTheme,
    onReview,
    onSettings,
}: {
    session?: Session;
    run?: Run;
    theme: "light" | "dark";
    reviewOpen: boolean;
    onTheme: () => void;
    onReview: () => void;
    onSettings: () => void;
}) {
    return (
        <header className="topbar">
            <div className="topbar-title">
                <img
                    src={`${import.meta.env.BASE_URL}logo.png`}
                    alt="Designer Studio"
                    className="topbar-logo-img"
                />
                <span
                    className="connection-pulse"
                    title="System connected & streaming active"
                />
                <h2>{session?.title ?? "Agentic Designer Workspace"}</h2>
            </div>
            <div className="topbar-actions">
                {run ? (
                    <span
                        className="run-id-badge"
                        title={`Active run revision R${run.revision}`}
                    >
                        Run {run.id.slice(0, 7).toUpperCase()}
                    </span>
                ) : (
                    <span className="run-id-badge" style={{ opacity: 0.7 }}>
                        Ready
                    </span>
                )}
                <div className="topbar-divider" />
                <button
                    className="icon-button"
                    onClick={onTheme}
                    title={`Switch to ${theme === "dark" ? "Light" : "Dark"} theme`}
                    type="button"
                >
                    {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
                </button>
                <button
                    className={`icon-button ${reviewOpen ? "active" : ""}`}
                    onClick={onReview}
                    title={
                        reviewOpen
                            ? "Hide Review Workbench"
                            : "Show Review Workbench"
                    }
                    type="button"
                >
                    <PanelRight size={17} />
                </button>
                <button
                    className="icon-button"
                    onClick={onSettings}
                    title="Open Settings"
                    type="button"
                >
                    <Settings2 size={17} />
                </button>
            </div>
        </header>
    );
}
