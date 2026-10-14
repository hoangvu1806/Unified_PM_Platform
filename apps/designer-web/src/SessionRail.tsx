import {
    ChevronLeft,
    ChevronRight,
    LayoutGrid,
    Plus,
    Settings2,
    Sparkles,
    Trash2,
} from "lucide-react";
import { BaStatusPanel } from "./BaStatusPanel";
import type { Session } from "./types";

interface Props {
    sessions: Session[];
    activeId?: string;
    collapsed: boolean;
    onToggle: () => void;
    onSelect: (session: Session) => void;
    onDelete: (session: Session) => void;
    onCreate: () => void;
    onSettings: () => void;
    activeSession?: Session;
}

export function SessionRail(props: Props) {
    return (
        <aside
            className={`session-rail ${props.collapsed ? "is-collapsed" : ""}`}
            aria-label="Workspace sidebar"
        >
            <div className="brand-lockup">
                <span className="brand-mark" title="Designer Studio">
                    <img
                        src={`${import.meta.env.BASE_URL}logo.png`}
                        alt="Designer Studio"
                        className="brand-logo-img"
                    />
                </span>
                {!props.collapsed && (
                    <div>
                        <strong>Designer Studio</strong>
                        <small>AI-Powered UI Agent</small>
                    </div>
                )}
            </div>

            <button
                className="new-session"
                onClick={props.onCreate}
                title="Create new design session"
            >
                <Plus size={18} strokeWidth={2.2} />
                {!props.collapsed && <span>New Session</span>}
            </button>

            {!props.collapsed && (
                <div className="rail-label">
                    <span>Recent Sessions ({props.sessions.length})</span>
                </div>
            )}

            <nav className="session-list" aria-label="Design sessions">
                {props.sessions.map((session) => (
                    <div
                        key={session.id}
                        className={`session-row ${session.id === props.activeId ? "active" : ""}`}
                    >
                        <button
                            className="session-select"
                            onClick={() => props.onSelect(session)}
                            title={session.title}
                        >
                            <span className="session-dot" />
                            {!props.collapsed ? (
                                <span className="session-title">
                                    {session.title}
                                </span>
                            ) : (
                                <LayoutGrid size={16} />
                            )}
                        </button>
                        {!props.collapsed && (
                            <button
                                className="session-delete"
                                onClick={() => props.onDelete(session)}
                                title={`Delete ${session.title}`}
                                aria-label={`Delete ${session.title}`}
                            >
                                <Trash2 size={15} />
                            </button>
                        )}
                    </div>
                ))}
                {props.sessions.length === 0 && !props.collapsed && (
                    <div
                        style={{
                            padding: "12px",
                            color: "var(--text-muted)",
                            fontSize: "12.5px",
                        }}
                    >
                        No sessions yet. Click New Session to start.
                    </div>
                )}
            </nav>

            {!props.collapsed && <BaStatusPanel session={props.activeSession} />}

            <div className="rail-footer">
                <button
                    onClick={props.onSettings}
                    title="Open MCP & Connection Settings"
                >
                    <Settings2 size={18} />
                    {!props.collapsed && <span>Settings & MCP</span>}
                </button>
                <button
                    onClick={props.onToggle}
                    title={
                        props.collapsed ? "Expand sidebar" : "Collapse sidebar"
                    }
                >
                    {props.collapsed ? (
                        <ChevronRight size={18} />
                    ) : (
                        <>
                            <ChevronLeft size={18} />
                            <span>Collapse Sidebar</span>
                        </>
                    )}
                </button>
            </div>
        </aside>
    );
}
