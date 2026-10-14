import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "./api";
import { BuildRail } from "./BuildRail";
import { ChatWorkspace } from "./ChatWorkspace";
import {
    mcpProfile,
    normalizeMcpEndpoint,
    readSettings,
    requireMcpProfile,
} from "./connection";
import { openRunStream } from "./events";
import { ProjectFilesPanel } from "./ProjectFilesPanel";
import { ReviewPanel } from "./ReviewPanel";
import { SessionRail } from "./SessionRail";
import { SettingsDrawer } from "./SettingsDrawer";
import { useTheme } from "./theme";
import type {
    ConnectionSettings,
    Run,
    RunArtifacts,
    Session,
    SessionWorkspace,
    WorkflowEvent,
} from "./types";
import { WorkspaceHeader } from "./WorkspaceHeader";
import { sessionWorkflowState } from "./workflowState";

const MCP_RETRY_STAGES = new Set([
    "components",
    "binding",
    "assembly",
    "layout_check",
]);

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
    const [connection, setConnection] = useState(readSettings);
    const [notice, setNotice] = useState("");
    const { resolvedTheme, toggleTheme } = useTheme();

    const applyRun = useCallback((updated: Run) => {
        setActiveRun((current) =>
            current?.id === updated.id ? updated : current,
        );
        setRuns((current) =>
            current.map((item) => (item.id === updated.id ? updated : item)),
        );
    }, []);

    const applySession = useCallback((updated: Session) => {
        setActiveSession((current) =>
            current?.id === updated.id ? updated : current,
        );
        setSessions((current) =>
            current.map((item) => (item.id === updated.id ? updated : item)),
        );
    }, []);

    const applyWorkspaceToConnection = useCallback(
        (workspace?: SessionWorkspace | null) => {
            setConnection((current) => ({
                ...current,
                documentId: workspace?.document_id ?? "",
                documentPath: workspace?.document_path ?? "",
                documentName: workspace?.document_name ?? "",
                pageId: workspace?.page_id ?? "",
                pageName: workspace?.page_name ?? "",
            }));
        },
        [],
    );

    const applySessionWorkspace = useCallback(
        (sessionId: string, workspace: SessionWorkspace) => {
            applyWorkspaceToConnection(workspace);
            setActiveSession((current) =>
                current?.id === sessionId ? { ...current, workspace } : current,
            );
            setSessions((current) =>
                current.map((item) =>
                    item.id === sessionId ? { ...item, workspace } : item,
                ),
            );
        },
        [applyWorkspaceToConnection],
    );

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
        applyWorkspaceToConnection(activeSession.workspace);
        api.listRuns(activeSession.id)
            .then((items) => {
                setRuns(items);
                setActiveRun(items[0]);
                setEvents([]);
                setArtifacts(undefined);
            })
            .catch((error) => setNotice(error.message));
    }, [activeSession?.id, applyWorkspaceToConnection]);

    useEffect(() => {
        if (!activeSession || !activeRun) return;
        const checkpoint = artifacts?.openpencil_checkpoint;
        const documentId = String(checkpoint?.document_id ?? "");
        const outputFile = activeRun.mcp_profile?.output_file ?? "";
        if (!documentId || !outputFile) return;
        const screens = Array.isArray(checkpoint?.screens)
            ? (checkpoint.screens as Record<string, unknown>[])
            : [];
        const latest = screens.at(-1);
        const pageId = String(
            checkpoint?.in_progress_page_id ?? latest?.page_id ?? "",
        );
        const pageName = String(
            checkpoint?.in_progress_page_name ?? latest?.page_name ?? "",
        );
        const documentName =
            outputFile.split(/[\\/]/).at(-1)?.replace(/\.fig$/i, "") ||
            "Design document";
        const workspace: SessionWorkspace = {
            document_id: documentId,
            document_path: outputFile,
            document_name: documentName,
            page_id: pageId,
            page_name: pageName,
        };
        if (
            activeSession.workspace?.document_id === documentId &&
            activeSession.workspace?.page_id === pageId
        ) {
            return;
        }
        const updated = { ...activeSession, workspace };
        applySession(updated);
        applyWorkspaceToConnection(workspace);
    }, [
        activeRun,
        activeSession,
        artifacts?.openpencil_checkpoint,
        applySession,
        applyWorkspaceToConnection,
    ]);

    useEffect(() => {
        if (!activeRun) return;
        const source = openRunStream(activeRun.id, (event) => {
            setEvents((current) =>
                current.some((item) => item.id === event.id)
                    ? current
                    : [...current, event],
            );
            api.getRun(activeRun.id)
                .then(applyRun)
                .catch(() => undefined);
            api.getArtifacts(activeRun.id)
                .then(setArtifacts)
                .catch(() => undefined);
            const workspace = event.payload.workspace;
            if (
                workspace &&
                typeof workspace === "object" &&
                "document_id" in workspace
            ) {
                applySessionWorkspace(
                    activeRun.session_id,
                    workspace as unknown as SessionWorkspace,
                );
            }
        });
        return () => source.close();
    }, [activeRun?.id, applyRun, applySessionWorkspace]);

    useEffect(() => {
        if (!activeRun) {
            setArtifacts(undefined);
            return;
        }
        api.getArtifacts(activeRun.id)
            .then(setArtifacts)
            .catch(() => undefined);
    }, [activeRun?.id, activeRun?.revision, activeRun?.stage]);

    useEffect(() => {
        if (!activeRun || !["queued", "running"].includes(activeRun.status))
            return;
        const timer = window.setInterval(() => {
            api.getRun(activeRun.id)
                .then(applyRun)
                .catch(() => undefined);
            api.getArtifacts(activeRun.id)
                .then(setArtifacts)
                .catch(() => undefined);
        }, 1500);
        return () => window.clearInterval(timer);
    }, [activeRun?.id, activeRun?.status, applyRun]);

    const busy = useMemo(
        () => activeRun?.status === "running" || activeRun?.status === "queued",
        [activeRun],
    );
    const workflow = useMemo(
        () => sessionWorkflowState(activeRun, runs, events),
        [activeRun, runs, events],
    );

    const createSession = async () => {
        try {
            const session = await api.createSession(
                `Design session ${sessions.length + 1}`,
            );
            setSessions((current) => [session, ...current]);
            setActiveSession(session);
            setActiveRun(undefined);
        } catch (error) {
            setNotice((error as Error).message);
        }
    };

    const deleteSession = async (session: Session) => {
        if (
            !window.confirm(
                `Delete "${session.title}" and all of its messages and workflow data?`,
            )
        ) {
            return;
        }
        try {
            await api.deleteSession(session.id);
            const remaining = sessions.filter((item) => item.id !== session.id);
            setSessions(remaining);
            if (activeSession?.id === session.id) {
                const next = remaining[0];
                setActiveSession(next);
                setRuns([]);
                setActiveRun(undefined);
                setEvents([]);
                setArtifacts(undefined);
                if (!next) applyWorkspaceToConnection(undefined);
            }
            setNotice("");
        } catch (error) {
            setNotice((error as Error).message);
        }
    };

    const updateWorkspace = useCallback(
        (value: ConnectionSettings) => {
            setConnection(value);
            localStorage.setItem("designer.connection", JSON.stringify(value));
            if (!activeSession) return;
            const workspace: SessionWorkspace = {
                document_id: value.documentId,
                document_path: value.documentPath,
                document_name: value.documentName,
                page_id: value.pageId,
                page_name: value.pageName,
            };
            void api
                .updateSessionWorkspace(activeSession.id, workspace)
                .then(applySession)
                .catch((error) => setNotice((error as Error).message));
        },
        [activeSession, applySession],
    );

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
                session = await api.createSession(
                    value.screenName || "Design session",
                );
                setSessions((current) => [session!, ...current]);
                setActiveSession(session);
            }
            const run = await api.sendMessage(session.id, {
                content: value.prompt,
                screen_name_hint: value.screenName,
                platform_hint: value.platform,
                style_hint: value.styleName,
                library_ids: value.libraryIds,
                mcp_profile: mcpProfile(connection),
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

    const review = async (
        decision: "approved" | "changes_requested",
        feedback = "",
    ) => {
        if (!activeRun) return;
        try {
            const checkpoint =
                activeRun.stage === "review_final" ? "final" : "specification";
            const currentProfile =
                decision === "approved" && checkpoint === "specification"
                    ? requireMcpProfile(connection)
                    : mcpProfile(connection);
            await api.review(
                activeRun.id,
                activeRun.revision,
                checkpoint,
                decision,
                feedback,
                currentProfile,
            );
            setActiveRun(await api.getRun(activeRun.id));
        } catch (error) {
            setNotice((error as Error).message);
        }
    };

    const recheckLayout = useCallback(
        async (showNotice = false) => {
            if (!activeRun || activeRun.stage !== "review_final") return;
            try {
                const result = await api.recheckLayout(activeRun.id);
                setArtifacts((current) =>
                    current
                        ? { ...current, layout_review: result.layout_review }
                        : current,
                );
            } catch (error) {
                if (showNotice) setNotice((error as Error).message);
            }
        },
        [activeRun?.id, activeRun?.stage],
    );

    useEffect(() => {
        if (
            !activeRun ||
            activeRun.stage !== "review_final" ||
            activeRun.status !== "waiting_review"
        ) {
            return;
        }
        const timer = window.setInterval(() => {
            void recheckLayout();
        }, 8000);
        return () => window.clearInterval(timer);
    }, [activeRun?.id, activeRun?.stage, activeRun?.status, recheckLayout]);

    return (
        <div
            className={`app-shell ${collapsed ? "rail-collapsed" : ""} ${reviewOpen ? "" : "review-closed"}`}
        >
            <SessionRail
                sessions={sessions}
                activeId={activeSession?.id}
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
                artifacts={artifacts}
                busy={busy}
                settings={connection}
                onSettingsChange={updateWorkspace}
                onSubmit={submit}
                onReview={review}
                onDownload={async () => {
                    if (!activeRun) return;
                    try {
                        await api.syncCanvas(activeRun.id);
                        window.location.assign(api.downloadRunFile(activeRun.id));
                    } catch (error) {
                        setNotice((error as Error).message);
                    }
                }}
                onToggleSidePanel={() => setReviewOpen((prev) => !prev)}
                onRetry={async () => {
                    if (!activeRun) return;
                    try {
                        const profile = MCP_RETRY_STAGES.has(
                            activeRun.error?.stage ?? "",
                        )
                            ? requireMcpProfile(connection)
                            : mcpProfile(connection);
                        await api.retry(activeRun.id, profile);
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
                    artifacts={artifacts}
                    onRecheckLayout={() => recheckLayout(true)}
                    onReview={review}
                    onShowFiles={() => setRightPanel("files")}
                />
            )}
            {reviewOpen && rightPanel === "files" && (
                <ProjectFilesPanel onShowWorkbench={() => setRightPanel("workbench")} />
            )}

            {notice && (
                <button
                    className="notice"
                    onClick={() => setNotice("")}
                    type="button"
                >
                    {notice} (Click to dismiss)
                </button>
            )}

            {settingsOpen && (
                <SettingsDrawer
                    value={connection}
                    onClose={() => setSettingsOpen(false)}
                    onSave={(value) => {
                        const normalized = {
                            ...value,
                            mcpEndpoint: normalizeMcpEndpoint(
                                value.mcpEndpoint,
                            ),
                            sourceFile: value.sourceFile.trim(),
                        };
                        setConnection(normalized);
                        localStorage.setItem(
                            "designer.connection",
                            JSON.stringify(normalized),
                        );
                        setSettingsOpen(false);
                    }}
                    onLoadComponents={(value) =>
                        api.listComponents(requireMcpProfile(value))
                    }
                />
            )}
        </div>
    );
}
