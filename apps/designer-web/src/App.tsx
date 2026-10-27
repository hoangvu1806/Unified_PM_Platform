import { useCallback, useEffect, useMemo, useState } from "react";
import { api, canvasUrl } from "./api";
import { BuildRail } from "./BuildRail";
import { ChatWorkspace } from "./ChatWorkspace";
import { openRunStream } from "./events";
import { ProjectFilesPanel } from "./ProjectFilesPanel";
import { ReviewPanel } from "./ReviewPanel";
import { SessionRail } from "./SessionRail";
import { SettingsDrawer } from "./SettingsDrawer";
import { useTheme } from "./theme";
import type { Run, RunArtifacts, Session, WorkflowEvent } from "./types";
import { WorkspaceHeader } from "./WorkspaceHeader";
import { sessionWorkflowState } from "./workflowState";

export default function App() {
    const [sessions, setSessions] = useState<Session[]>([]);
    const [activeSession, setActiveSession] = useState<Session>();
    const [runs, setRuns] = useState<Run[]>([]);
    const [activeRun, setActiveRun] = useState<Run>();
    const [events, setEvents] = useState<WorkflowEvent[]>([]);
    const [artifacts, setArtifacts] = useState<RunArtifacts>();
    const [collapsed, setCollapsed] = useState(false);
    const [settingsOpen, setSettingsOpen] = useState(false);
    const [reviewOpen, setReviewOpen] = useState(false);
    const [rightPanel, setRightPanel] = useState<"workbench" | "files">("workbench");
    const [screensVersion, setScreensVersion] = useState(0);
    const [notice, setNotice] = useState("");
    const { resolvedTheme, toggleTheme } = useTheme();

    const applyRun = useCallback((updated: Run) => {
        setActiveRun((current) => (current?.id === updated.id ? updated : current));
        setRuns((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    }, []);

    const applySession = useCallback((updated: Session) => {
        setActiveSession((current) => (current?.id === updated.id ? updated : current));
        setSessions((current) => current.map((item) => (item.id === updated.id ? updated : item)));
    }, []);

    useEffect(() => {
        api.listSessions()
            .then((items) => {
                setSessions(items);
                const requested = new URLSearchParams(window.location.search).get("session");
                const selected = (requested && items.find((item) => item.id === requested)) || items[0];
                if (selected) setActiveSession(selected);
            })
            .catch((error) => setNotice(error.message));
    }, []);

    useEffect(() => {
        if (!activeSession) return;
        api.listRuns(activeSession.id)
            .then((items) => {
                setRuns(items);
                setActiveRun(items[0]);
                setEvents([]);
                setArtifacts(undefined);
            })
            .catch((error) => setNotice(error.message));
    }, [activeSession?.id]);

    useEffect(() => {
        if (!activeRun) return;
        const source = openRunStream(activeRun.id, (event) => {
            setEvents((current) => (current.some((item) => item.id === event.id) ? current : [...current, event]));
            if (event.type === "screen.saved" || event.type === "screen.finished") {
                setScreensVersion((v) => v + 1);
            }
            api.getRun(activeRun.id).then(applyRun).catch(() => undefined);
            api.getArtifacts(activeRun.id).then(setArtifacts).catch(() => undefined);
        });
        return () => source.close();
    }, [activeRun?.id, applyRun]);

    useEffect(() => {
        if (!activeRun) {
            setArtifacts(undefined);
            return;
        }
        api.getArtifacts(activeRun.id).then(setArtifacts).catch(() => undefined);
    }, [activeRun?.id, activeRun?.revision, activeRun?.stage]);

    useEffect(() => {
        if (!activeRun || !["queued", "running"].includes(activeRun.status)) return;
        const timer = window.setInterval(() => {
            api.getRun(activeRun.id).then(applyRun).catch(() => undefined);
        }, 3000);
        return () => window.clearInterval(timer);
    }, [activeRun?.id, activeRun?.status, applyRun]);

    const busy = useMemo(() => activeRun?.status === "running" || activeRun?.status === "queued", [activeRun]);
    const workflow = useMemo(() => sessionWorkflowState(activeRun, runs, events), [activeRun, runs, events]);

    const createSession = async () => {
        try {
            const session = await api.createSession(`Design session ${sessions.length + 1}`);
            setSessions((current) => [session, ...current]);
            setActiveSession(session);
            setActiveRun(undefined);
        } catch (error) {
            setNotice((error as Error).message);
        }
    };

    const deleteSession = async (session: Session) => {
        if (!window.confirm(`Delete "${session.title}" and all of its messages, screens and workflow data?`)) return;
        try {
            await api.deleteSession(session.id);
            const remaining = sessions.filter((item) => item.id !== session.id);
            setSessions(remaining);
            if (activeSession?.id === session.id) {
                setActiveSession(remaining[0]);
                setRuns([]);
                setActiveRun(undefined);
                setEvents([]);
                setArtifacts(undefined);
            }
            setNotice("");
        } catch (error) {
            setNotice((error as Error).message);
        }
    };

    const submit = async (value: {
        prompt: string;
        screenName: string;
        platform: string;
        styleName?: string;
        libraryIds: string[];
        assets?: import("./types").ExactAsset[];
    }) => {
        try {
            let session = activeSession;
            if (!session) {
                session = await api.createSession(value.screenName || "Design session");
                setSessions((current) => [session!, ...current]);
                setActiveSession(session);
            }
            const run = await api.sendMessage(session.id, {
                content: value.prompt,
                screen_name_hint: value.screenName,
                platform_hint: value.platform,
                style_hint: value.styleName,
                library_ids: value.libraryIds,
                assets: value.assets,
            });
            setRuns((current) => [run, ...current]);
            setActiveRun(run);
            setEvents([]);
            setArtifacts(undefined);
            setNotice("");
        } catch (error) {
            setNotice((error as Error).message);
        }
    };

    const review = async (decision: "approved" | "changes_requested", feedback = "") => {
        if (!activeRun) return;
        try {
            const checkpoint = activeRun.stage === "review_final" ? "final" : "specification";
            await api.review(activeRun.id, activeRun.revision, checkpoint, decision, feedback);
            setActiveRun(await api.getRun(activeRun.id));
        } catch (error) {
            setNotice((error as Error).message);
        }
    };

    const openCanvas = activeSession
        ? () => window.open(canvasUrl(activeSession.id), `designer-canvas-${activeSession.id}`)
        : undefined;

    return (
        <div className={`app-shell ${collapsed ? "rail-collapsed" : ""} ${reviewOpen ? "" : "review-closed"}`}>
            <SessionRail
                sessions={sessions}
                activeId={activeSession?.id}
                activeSession={activeSession}
                collapsed={collapsed}
                onToggle={() => setCollapsed(!collapsed)}
                onSelect={setActiveSession}
                onDelete={deleteSession}
                onCreate={createSession}
                onSettings={() => setSettingsOpen(true)}
            />

            <WorkspaceHeader
                session={activeSession}
                run={activeRun}
                theme={resolvedTheme}
                reviewOpen={reviewOpen}
                onTheme={toggleTheme}
                onReview={() => setReviewOpen(!reviewOpen)}
                onSettings={() => setSettingsOpen(true)}
                onOpenCanvas={openCanvas}
            />

            <section className="timeline-slot">
                <BuildRail
                    stage={workflow?.stage}
                    status={workflow?.status}
                    mode={workflow?.run.intent === "design" ? "workspace" : "project"}
                />
            </section>

            <ChatWorkspace
                run={activeRun}
                runs={runs}
                events={events}
                busy={busy}
                onSubmit={submit}
                onReview={review}
                sessionId={activeSession?.id}
                onOpenCanvas={openCanvas}
                onToggleSidePanel={() => setReviewOpen((prev) => !prev)}
                onRetry={async () => {
                    if (!activeRun) return;
                    try {
                        await api.retry(activeRun.id);
                        applyRun(await api.getRun(activeRun.id));
                    } catch (error) {
                        setNotice((error as Error).message);
                    }
                }}
                onCancel={async () => {
                    if (!activeRun) return;
                    try {
                        await api.cancel(activeRun.id);
                        applyRun(await api.getRun(activeRun.id));
                    } catch (error) {
                        setNotice((error as Error).message);
                    }
                }}
            />

            {reviewOpen && rightPanel === "workbench" && (
                <ReviewPanel
                    run={activeRun}
                    sessionId={activeSession?.id}
                    artifacts={artifacts}
                    screensVersion={screensVersion}
                    onReview={review}
                    onShowFiles={() => setRightPanel("files")}
                />
            )}
            {reviewOpen && rightPanel === "files" && (
                <ProjectFilesPanel onShowWorkbench={() => setRightPanel("workbench")} />
            )}

            {notice && (
                <button className="notice" onClick={() => setNotice("")} type="button">
                    {notice} (Click to dismiss)
                </button>
            )}

            {settingsOpen && (
                <SettingsDrawer
                    session={activeSession}
                    onClose={() => setSettingsOpen(false)}
                    onSessionChange={applySession}
                />
            )}
        </div>
    );
}
