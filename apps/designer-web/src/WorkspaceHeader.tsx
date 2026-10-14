import { ArrowLeft, LogOut, Moon, PanelRight, Settings2, Sun } from "lucide-react";
import { isEmbedded, logout, usePlatform } from "./platform";
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
    const platform = isEmbedded ? undefined : usePlatform();
    return (
        <header className="topbar">
            <div className="topbar-title">
                {platform && (
                    <nav className="platform-crumbs" aria-label="Dự án">
                        <a href="/" className="platform-back" title="Về danh sách dự án">
                            <ArrowLeft size={14} />
                            Dự án
                        </a>
                        <span className="platform-sep">/</span>
                        <span className="platform-project" title={platform.project.id}>
                            {platform.project.name}
                        </span>
                        <span className="platform-sep">/</span>
                    </nav>
                )}
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
                {platform && (
                    <>
                        {platform.readOnly ? (
                            <span className="run-id-badge platform-readonly-badge" title="Bạn chỉ xem được dự án này">
                                Chỉ đọc
                            </span>
                        ) : (
                            <span className="run-id-badge" title="Vai trò của bạn trong dự án">
                                {platform.project.my_roles.join(" · ")}
                            </span>
                        )}
                        <span className="platform-user" title={platform.user.username}>
                            {platform.user.name}
                        </span>
                        <button className="icon-button" onClick={() => void logout()} title="Đăng xuất" type="button">
                            <LogOut size={16} />
                        </button>
                        <div className="topbar-divider" />
                    </>
                )}
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
                {/* Embedded: the platform header owns the one light/dark switch. */}
                {!isEmbedded && (
                    <button
                        className="icon-button"
                        onClick={onTheme}
                        title={`Switch to ${theme === "dark" ? "Light" : "Dark"} theme`}
                        type="button"
                    >
                        {theme === "dark" ? <Sun size={17} /> : <Moon size={17} />}
                    </button>
                )}
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
