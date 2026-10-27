import {
    ArrowUp,
    Bot,
    Check,
    Download,
    ExternalLink,
    Eye,
    MousePointerClick,
    List,
    FileCode,
    FileText,
    Image,
    LoaderCircle,
    Paperclip,
    Sparkles,
    Workflow,
    X,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { MentionMenu } from "./MentionMenu";
import {
    ATTACH_EVENT,
    type ProjectFile,
    filterFiles,
    listProjectFiles,
    readDraggedFile,
    toBrowserFile,
} from "./projectFiles";
import { api } from "./api";
import { STARTER_PROMPTS, StyleSelector } from "./ChatControls";
import { MarkdownRenderer } from "./MarkdownRenderer";
import type {
    ParsedAttachment,
    Run,
    WorkflowEvent,
    ExactAsset,
} from "./types";

/** Element picked on the design page (canvas tab), sent over BroadcastChannel. */
interface CanvasSelection {
    screenId: string;
    screenName: string;
    element: { id: string; tag: string; text: string; html: string };
}

interface Props {
    run?: Run;
    runs: Run[];
    events: WorkflowEvent[];
    busy: boolean;
    sessionId?: string;
    onOpenCanvas?: () => void;
    onSubmit: (value: {
        prompt: string;
        screenName: string;
        platform: string;
        styleName?: string;
        libraryIds: string[];
        assets?: ExactAsset[];
    }) => void;
    onReview?: (
        decision: "approved" | "changes_requested",
        feedback?: string,
    ) => Promise<void> | void;
    onToggleSidePanel?: () => void;
    onRetry: () => void;
    onCancel: () => void;
}

function eventText(event: WorkflowEvent) {
    const value = event.payload.message ?? event.payload.detail ?? event.type;
    return String(value).replaceAll("_", " ");
}

function formatMessageTime(dateStr?: string) {
    if (!dateStr) {
        return new Date().toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
        });
    }
    try {
        const d = new Date(dateStr);
        if (isNaN(d.getTime())) return "";
        return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
        return "";
    }
}

function getStageStatusText(stage?: string) {
    switch (stage) {
        case "requirement":
            return "Analyzing requirements & design intent...";
        case "specification":
            return "Writing the UI specification...";
        case "review_spec":
            return "Preparing specification for review...";
        case "assembly":
            return "Building screens in HTML + Tailwind (write, check, refine)...";
        case "review_final":
            return "Finalizing design for review...";
        default:
            return "Designer is thinking & preparing response...";
    }
}

function getStageBadge(stage?: string) {
    switch (stage) {
        case "requirement":
            return "Requirements";
        case "specification":
            return "Specification";
        case "assembly":
            return "Build";
        case "review_spec":
        case "review_final":
            return "Review";
        default:
            return "Working";
    }
}

const HIDDEN_CONVERSATION_EVENTS = new Set(["run.created", "stage.changed", "llm.usage"]);
const ATTACHMENT_CONTEXT_MARKER = "<!-- DESIGNER_ATTACHMENT_CONTEXT -->";
const DEFAULT_ATTACHMENT_REQUEST =
    "Analyze the attached requirements and determine the complete, consistent set of screens and states to design.";

interface ParsedUserPrompt {
    text: string;
    attachmentNames: string[];
}

function parseUserPrompt(raw: string): ParsedUserPrompt {
    const visible = raw.split(ATTACHMENT_CONTEXT_MARKER, 1)[0].trim();
    const match = visible.match(
        /^(.*?)(?:\r?\n\r?\n|\r?\n)?Attachments:\s*(.+)$/s,
    );
    if (!match) {
        return { text: visible, attachmentNames: [] };
    }

    const userText = match[1].trim();
    const filesStr = match[2].trim();
    const attachmentNames = filesStr
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);

    const isDefault = userText === DEFAULT_ATTACHMENT_REQUEST;

    return {
        text: isDefault ? "" : userText,
        attachmentNames,
    };
}

function getFileMeta(fileName: string) {
    const ext = fileName.split(".").pop()?.toLowerCase() || "";
    switch (ext) {
        case "json":
            return {
                label: "JSON",
                type: "Data Specification",
                color: "#F59E0B",
                icon: "code",
            };
        case "bpmn":
        case "bpmn2":
            return {
                label: "BPMN",
                type: "Business Process",
                color: "#8B5CF6",
                icon: "workflow",
            };
        case "png":
        case "jpg":
        case "jpeg":
        case "webp":
        case "svg":
            return {
                label: ext.toUpperCase(),
                type: "Image Reference",
                color: "#38BDF8",
                icon: "image",
            };
        case "pdf":
            return {
                label: "PDF",
                type: "Document",
                color: "#EF4444",
                icon: "doc",
            };
        case "md":
            return {
                label: "MD",
                type: "Markdown Docs",
                color: "#A78BFA",
                icon: "doc",
            };
        case "txt":
        case "csv":
        case "yaml":
        case "yml":
            return {
                label: ext.toUpperCase(),
                type: "Text Data",
                color: "#10B981",
                icon: "doc",
            };
        default:
            return {
                label: ext ? ext.toUpperCase() : "FILE",
                type: "Attachment",
                color: "#94A3B8",
                icon: "file",
            };
    }
}

function UserMessageContent({ prompt }: { prompt: string }) {
    const { text, attachmentNames } = parseUserPrompt(prompt);

    return (
        <div className="user-message-content">
            {text && <p className="user-prompt-text">{text}</p>}
            {attachmentNames.length > 0 && (
                <div
                    className={`user-attachments-group ${text ? "has-text" : ""}`}
                >
                    {attachmentNames.map((fileName) => {
                        const meta = getFileMeta(fileName);
                        return (
                            <div
                                className="user-attachment-card"
                                key={fileName}
                            >
                                <span
                                    className="user-attachment-icon-box"
                                    style={{ color: meta.color }}
                                >
                                    {meta.icon === "image" ? (
                                        <Image size={16} />
                                    ) : meta.icon === "code" ? (
                                        <FileCode size={16} />
                                    ) : meta.icon === "workflow" ? (
                                        <Workflow size={16} />
                                    ) : (
                                        <FileText size={16} />
                                    )}
                                </span>
                                <div className="user-attachment-info">
                                    <span
                                        className="user-attachment-name"
                                        title={fileName}
                                    >
                                        {fileName}
                                    </span>
                                    <span className="user-attachment-type">
                                        {meta.type}
                                    </span>
                                </div>
                                <span className="user-attachment-badge">
                                    {meta.label}
                                </span>
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

function AssistantAvatar({ className = "" }: { className?: string }) {
    return (
        <span className={`assistant-avatar ${className}`}>
            <img
                src={`${import.meta.env.BASE_URL}logo.png`}
                alt="Designer"
                className="assistant-avatar-img"
            />
        </span>
    );
}

function UserAvatar({ className = "" }: { className?: string }) {
    return (
        <span className={`user-avatar ${className}`} title="You">
            <img src={`${import.meta.env.BASE_URL}user_icon.png`} alt="You" className="user-avatar-img" />
        </span>
    );
}

export function ChatWorkspace({
    run,
    runs,
    events,
    busy,
    sessionId,
    onOpenCanvas,
    onSubmit,
    onReview,
    onToggleSidePanel,
    onRetry,
    onCancel,
}: Props) {
    const [prompt, setPrompt] = useState("");
    const [screenName, setScreenName] = useState("");
    const [platform, setPlatform] = useState("responsive");
    const [styleName, setStyleName] = useState("minimal");
    const [attachments, setAttachments] = useState<ParsedAttachment[]>([]);
    const [attachmentError, setAttachmentError] = useState("");
    const [uploading, setUploading] = useState(false);
    const [dragging, setDragging] = useState(false);
    const [reviewFeedback, setReviewFeedback] = useState("");
    const [selection, setSelection] = useState<CanvasSelection>();
    const [submittingReview, setSubmittingReview] = useState(false);
    const [activityLogOpen, setActivityLogOpen] = useState(false);
    const conversationEndRef = useRef<HTMLDivElement>(null);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    // Platform: shared project files can be cited with "@" or dragged in.
    const [projectFiles, setProjectFiles] = useState<ProjectFile[]>([]);
    const [mention, setMention] = useState<{ start: number; query: string } | null>(null);
    const [mentionIndex, setMentionIndex] = useState(0);
    const mentionMatches = mention
        ? filterFiles(projectFiles, mention.query).filter((f) => f.citable).slice(0, 8)
        : [];
    const fileInputRef = useRef<HTMLInputElement>(null);

    const canReview =
        (run?.stage === "review_spec" || run?.stage === "review_final") &&
        run.status === "waiting_review";
    const specScreens = run?.specification?.schema_version === "html-1" ? run.specification.screens : [];
    const finalBlocked = false;

    // The design page posts the element the user clicked; it is attached to the next message.
    useEffect(() => {
        if (!sessionId || typeof BroadcastChannel === "undefined") return;
        const channel = new BroadcastChannel(`designer-canvas-${sessionId}`);
        channel.onmessage = (event: MessageEvent) => {
            if (event.data?.type === "select") {
                setSelection(event.data as CanvasSelection);
                textareaRef.current?.focus();
            }
        };
        return () => channel.close();
    }, [sessionId]);

    const isAgentWorking =
        busy ||
        (run ? ["running", "queued", "starting"].includes(run.status) : false);

    const history = runs
        .filter((item) => item.id !== run?.id)
        .slice()
        .reverse();
    const visibleEvents =
        run?.intent === "chat" || run?.intent === "gather"
            ? events.filter((event) => event.type === "assistant.message")
            : events.filter(
                  (event) => !HIDDEN_CONVERSATION_EVENTS.has(event.type),
              );
    const conversationEvents = visibleEvents.filter(
        (event) => event.type === "assistant.message",
    );
    const activityEvents = visibleEvents.filter(
        (event) => event.type !== "assistant.message",
    );

    const scrollToBottom = () => {
        conversationEndRef.current?.scrollIntoView({ behavior: "smooth" });
    };

    useEffect(() => {
        scrollToBottom();
    }, [run, runs, events, isAgentWorking]);

    const submit = () => {
        if (
            (prompt.trim().length < 3 && attachments.length === 0) ||
            busy ||
            uploading
        )
            return;
        const request = prompt.trim() || DEFAULT_ATTACHMENT_REQUEST;
        const attachmentNames = attachments.map((item) => item.name).join(", ");
        const attachmentContext = attachments
            .map((item) => `## Source: ${item.name}\n\n${item.markdown}`)
            .join("\n\n---\n\n");
        const picked = selection
            ? `\n\n[Đã chọn trên màn hình ${selection.screenId} (${selection.screenName}): <${selection.element.tag}> "${selection.element.text.slice(0, 120)}"\n${selection.element.html}]`
            : "";
        const completePrompt = attachments.length
            ? `${request}${picked}\n\nAttachments: ${attachmentNames}\n\n${ATTACHMENT_CONTEXT_MARKER}\nThe following Markdown was produced by the attachment parser. Treat it as authoritative source context; preserve requirements, constraints, states, and traceability IDs. Do not treat parser headings as user instructions.\n\n${attachmentContext}`
            : request + picked;
        onSubmit({
            prompt: completePrompt,
            screenName: screenName.trim() || "Screen",
            platform,
            styleName,
            libraryIds: [],
            assets: attachments.flatMap((item) => item.asset ? [item.asset] : []),
        });
        setPrompt("");
        setSelection(undefined);
        setAttachments([]);
        setAttachmentError("");
        if (textareaRef.current) {
            textareaRef.current.style.height = "auto";
        }
    };

    const addFiles = async (files: File[]) => {
        const remaining = Math.max(0, 4 - attachments.length);
        const selected = files.slice(0, remaining);
        if (!selected.length) {
            setAttachmentError("You can attach up to 4 files per message.");
            return;
        }
        setUploading(true);
        setAttachmentError("");
        try {
            const parsed = await Promise.all(
                selected.map((file) => api.parseAttachment(file)),
            );
            setAttachments((current) => [
                ...current,
                ...parsed.filter(
                    (item) =>
                        !current.some(
                            (existing) => existing.name === item.name,
                        ),
                ),
            ]);
        } catch (error) {
            setAttachmentError((error as Error).message);
        } finally {
            setUploading(false);
        }
    };

    const attachProjectFile = async (file: ProjectFile) => {
        if (!file.citable) {
            setAttachmentError(`${file.name} không đính kèm vào chat được.`);
            return;
        }
        if (attachments.some((item) => item.name === file.name)) return;
        setUploading(true);
        setAttachmentError("");
        try {
            const browserFile = await toBrowserFile(file);
            await addFiles([browserFile]);
        } catch (error) {
            setAttachmentError((error as Error).message);
            setUploading(false);
        }
    };

    // "+" in the Files panel dispatches ATTACH_EVENT.
    const attachRef = useRef(attachProjectFile);
    attachRef.current = attachProjectFile;
    useEffect(() => {
        const onAttach = (event: Event) => {
            void attachRef.current((event as CustomEvent<ProjectFile>).detail);
            textareaRef.current?.focus();
        };
        window.addEventListener(ATTACH_EVENT, onAttach);
        return () => window.removeEventListener(ATTACH_EVENT, onAttach);
    }, []);

    const updateMention = (value: string, caret: number) => {
        const match = /(^|\s)@([^\s@]*)$/.exec(value.slice(0, caret));
        if (!match) {
            setMention(null);
            return;
        }
        if (!mention) listProjectFiles().then(setProjectFiles).catch(() => setProjectFiles([]));
        setMention({ start: caret - match[2].length - 1, query: match[2] });
        setMentionIndex(0);
    };

    const pickMention = (file: ProjectFile) => {
        if (!mention) return;
        const caret = mention.start + 1 + mention.query.length;
        const token = `@${file.name} `;
        const next = prompt.slice(0, mention.start) + token + prompt.slice(caret);
        setPrompt(next);
        setMention(null);
        void attachProjectFile(file);
        requestAnimationFrame(() => {
            const el = textareaRef.current;
            if (el) {
                const pos = mention.start + token.length;
                el.focus();
                el.setSelectionRange(pos, pos);
            }
        });
    };

    const selectStarter = (starter: (typeof STARTER_PROMPTS)[number]) => {
        setPrompt(starter.prompt);
        setScreenName(starter.screenName);
        setPlatform(starter.platform);
        if (textareaRef.current) {
            textareaRef.current.focus();
        }
    };

    return (
        <main className="chat-workspace" role="main">
            <section className="conversation" aria-live="polite">
                {!run && history.length === 0 && (
                    <div className="empty-conversation">
                        <span className="empty-orbit">
                            <img
                                src={`${import.meta.env.BASE_URL}logo.png`}
                                alt="Designer Studio"
                                className="empty-orbit-logo"
                            />
                        </span>
                        <h2>What would you like to build?</h2>
                        <p>
                            Describe your target screen, audience, and key
                            actions. The AI designer will turn your requirements
                            into structured, reviewable UI components.
                        </p>
                        <div className="starter-grid">
                            {STARTER_PROMPTS.map((starter) => (
                                <button
                                    key={starter.title}
                                    type="button"
                                    className="starter-card"
                                    onClick={() => selectStarter(starter)}
                                >
                                    <strong>{starter.title}</strong>
                                    <span>{starter.prompt}</span>
                                </button>
                            ))}
                        </div>
                    </div>
                )}

                {history.map((item) => (
                    <div className="turn-history" key={item.id}>
                        <div className="user-message-row">
                            <div className="user-bubble-group">
                                <article className="message user-message">
                                    <UserMessageContent prompt={item.prompt} />
                                </article>
                                <span className="user-message-time">
                                    {formatMessageTime(item.created_at)}
                                </span>
                            </div>
                            <UserAvatar />
                        </div>
                        {item.assistant_message && (
                            <article className="message assistant-message">
                                <AssistantAvatar />
                                <div className="assistant-body">
                                    <div className="assistant-header">
                                        <small>Designer</small>
                                    </div>
                                    <MarkdownRenderer
                                        content={item.assistant_message}
                                    />
                                </div>
                            </article>
                        )}
                    </div>
                ))}

                {run && (
                    <div className="user-message-row">
                        <div className="user-bubble-group">
                            <article className="message user-message">
                                <UserMessageContent prompt={run.prompt} />
                            </article>
                            <span className="user-message-time">
                                {formatMessageTime(run.created_at)}
                            </span>
                        </div>
                        <UserAvatar />
                    </div>
                )}

                {conversationEvents.map((event) =>
                    event.type === "assistant.message" ? (
                        <article
                            className="message assistant-message"
                            key={event.id}
                        >
                            <AssistantAvatar />
                            <div className="assistant-body">
                                <div className="assistant-header">
                                    <small>Designer</small>
                                </div>
                                <MarkdownRenderer content={eventText(event)} />
                            </div>
                        </article>
                    ) : null,
                )}

                {activityEvents.length > 0 && (
                    <details
                        className="activity-log"
                        open={activityLogOpen}
                        onToggle={(event) =>
                            setActivityLogOpen(event.currentTarget.open)
                        }
                    >
                        <summary className="activity-log-summary">
                            <List size={14} />
                            <span>Activity log</span>
                            <span className="activity-log-count">
                                {activityEvents.length}
                            </span>
                        </summary>
                        <div className="activity-log-list">
                            {activityEvents.map((event) => (
                                <div
                                    className={`activity-log-row event-${event.type.replace(".", "-")}`}
                                    key={event.id}
                                >
                                    <span className="event-marker" />
                                    <div>
                                        <small>
                                            {event.type.replaceAll(".", " · ")}
                                        </small>
                                        <p>{eventText(event)}</p>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </details>
                )}

                {(run?.intent === "chat" || run?.intent === "gather") &&
                    run.assistant_message &&
                    !conversationEvents.some(
                        (event) => event.type === "assistant.message",
                    ) && (
                        <article className="message assistant-message">
                            <AssistantAvatar />
                            <div className="assistant-body">
                                <div className="assistant-header">
                                    <small>Designer</small>
                                </div>
                                <MarkdownRenderer
                                    content={run.assistant_message}
                                />
                            </div>
                        </article>
                    )}

                {run?.error && (
                    <article className="message error-message">
                        <small>{run.error.code}</small>
                        <p>{run.error.detail}</p>
                        {run.error.action && <em>{run.error.action}</em>}
                        {(run.status === "failed" ||
                            run.status === "blocked") && (
                            <button
                                className="secondary-button compact"
                                onClick={onRetry}
                                type="button"
                            >
                                Retry this stage
                            </button>
                        )}
                    </article>
                )}

                {run?.status === "cancelled" && !run.error && (
                    <article className="message error-message">
                        <small>RUN CANCELLED</small>
                        <p>The saved design checkpoint is ready to continue.</p>
                        <button
                            className="secondary-button compact"
                            onClick={onRetry}
                            type="button"
                        >
                            Resume saved stage
                        </button>
                    </article>
                )}

                {canReview && run && (
                    <article
                        className="message assistant-message chat-review-message"
                        aria-label="Review and approve design"
                    >
                        <AssistantAvatar />
                        <div className="assistant-body">
                            <div className="assistant-header">
                                <small>Designer</small>
                                <span className="chat-review-stage-badge">
                                    {run.stage === "review_final"
                                        ? "Final Design Review"
                                        : "Specification Review"}
                                </span>
                            </div>
                            <div className="chat-review-card">
                                <div className="chat-review-card-header">
                                    <div>
                                        <h4 className="chat-review-title">
                                            {run.stage === "review_final"
                                                ? "Review & export design"
                                                : "Approve UI Specification"}
                                        </h4>
                                        <p className="chat-review-subtitle">
                                            {run.stage === "review_final"
                                                ? "Open the design page to try the prototype, pick elements to comment on, then approve or request changes. Export .fig / PNG / HTML from there."
                                                : specScreens.length
                                                  ? `${specScreens.length} screens planned (${specScreens.map((s) => s.name).join(", ")}). Review the specification and approve to build them.`
                                                  : "The UI specification is ready. Approve to build the screens."}
                                        </p>
                                    </div>
                                    {onToggleSidePanel && (
                                        <button
                                            className="chat-review-side-btn"
                                            onClick={onToggleSidePanel}
                                            type="button"
                                            title="Inspect full details in side panel"
                                        >
                                            <Eye size={13} />
                                            <span>View Skeleton Screens</span>
                                        </button>
                                    )}
                                </div>

                                {specScreens.length > 1 && (
                                        <div
                                            style={{
                                                display: "flex",
                                                alignItems: "center",
                                                gap: "6px",
                                                flexWrap: "wrap",
                                                padding: "6px 10px",
                                                borderRadius: "8px",
                                                background: "var(--bg-app)",
                                                fontSize: "12px",
                                                fontWeight: 600,
                                                color: "var(--text-secondary)",
                                            }}
                                        >
                                            <span
                                                style={{
                                                    color: "var(--text-muted)",
                                                    fontSize: "11px",
                                                    fontWeight: 700,
                                                }}
                                            >
                                                Screens:
                                            </span>
                                            {specScreens.map(
                                                (s, idx) => (
                                                    <span
                                                        key={s.id}
                                                        style={{
                                                            padding: "2px 7px",
                                                            borderRadius: "6px",
                                                            background:
                                                                "var(--violet-soft)",
                                                            color: "var(--violet)",
                                                            fontSize: "11.5px",
                                                            fontFamily:
                                                                "var(--font-main)",
                                                        }}
                                                    >
                                                        #{idx + 1} {s.name}
                                                    </span>
                                                ),
                                            )}
                                        </div>
                                    )}

                                <div className="chat-review-feedback-container">
                                    <textarea
                                        className="chat-review-feedback-input"
                                        value={reviewFeedback}
                                        onChange={(e) =>
                                            setReviewFeedback(e.target.value)
                                        }
                                        placeholder="Describe adjustments needed... (optional for Approve, required for Request Changes)"
                                        rows={2}
                                        disabled={submittingReview}
                                    />
                                </div>

                                <div className="chat-review-actions">
                                    {run.stage === "review_final" && onOpenCanvas && (
                                        <button
                                            className="chat-review-btn"
                                            onClick={onOpenCanvas}
                                            disabled={submittingReview}
                                            type="button"
                                        >
                                            <ExternalLink size={15} />
                                            Mở trang thiết kế
                                        </button>
                                    )}
                                    {run.stage === "review_final" && sessionId && (
                                        <a className="chat-review-btn" href={api.exportUrl(sessionId, "fig")}>
                                            <Download size={15} /> .fig
                                        </a>
                                    )}
                                    <button
                                        className="chat-review-btn request-change"
                                        onClick={async () => {
                                            if (submittingReview || !onReview)
                                                return;
                                            setSubmittingReview(true);
                                            try {
                                                await onReview(
                                                    "changes_requested",
                                                    reviewFeedback,
                                                );
                                                setReviewFeedback("");
                                            } finally {
                                                setSubmittingReview(false);
                                            }
                                        }}
                                        disabled={submittingReview}
                                        type="button"
                                    >
                                        <X size={15} /> Request Changes
                                    </button>

                                    <button
                                        className="chat-review-btn approve"
                                        onClick={async () => {
                                            if (
                                                submittingReview ||
                                                !onReview ||
                                                finalBlocked
                                            )
                                                return;
                                            setSubmittingReview(true);
                                            try {
                                                await onReview(
                                                    "approved",
                                                    reviewFeedback,
                                                );
                                                setReviewFeedback("");
                                            } finally {
                                                setSubmittingReview(false);
                                            }
                                        }}
                                        disabled={
                                            finalBlocked || submittingReview
                                        }
                                        title={
                                            finalBlocked
                                                ? "Resolve blocking layout findings first"
                                                : undefined
                                        }
                                        type="button"
                                    >
                                        <Check size={15} />
                                        {submittingReview
                                            ? "Processing..."
                                            : run.stage === "review_final"
                                              ? "Approve Design"
                                              : "Approve Structure"}
                                    </button>
                                </div>
                            </div>
                        </div>
                    </article>
                )}

                {isAgentWorking && (
                    <article
                        className="message assistant-message typing-indicator-message"
                        aria-label="Designer is thinking"
                    >
                        <span className="assistant-avatar pulse-glow">
                            <Bot size={17} />
                        </span>
                        <div className="assistant-body">
                            <div className="assistant-header">
                                <small>Designer</small>
                                <span className="typing-header-stage">
                                    {getStageBadge(run?.stage)}
                                </span>
                            </div>
                            <div className="typing-bubble">
                                <div className="typing-dots" aria-hidden="true">
                                    <span className="typing-dot" />
                                    <span className="typing-dot" />
                                    <span className="typing-dot" />
                                </div>
                                <span className="typing-status-text">
                                    {getStageStatusText(run?.stage)}
                                </span>
                            </div>
                        </div>
                    </article>
                )}

                <div ref={conversationEndRef} />
            </section>

            <div className="composer-wrapper">
                <section
                    className={`composer ${dragging ? "is-dragging" : ""}`}
                    aria-label="Create design request"
                    onDragEnter={(event) => {
                        event.preventDefault();
                        if (!busy) setDragging(true);
                    }}
                    onDragOver={(event) => event.preventDefault()}
                    onDragLeave={(event) => {
                        if (
                            !event.currentTarget.contains(
                                event.relatedTarget as Node,
                            )
                        ) {
                            setDragging(false);
                        }
                    }}
                    onDrop={(event) => {
                        event.preventDefault();
                        setDragging(false);
                        if (busy) return;
                        const projectFile = readDraggedFile(event.dataTransfer);
                        if (projectFile) void attachProjectFile(projectFile);
                        else void addFiles(Array.from(event.dataTransfer.files));
                    }}
                >
                    {dragging && (
                        <div className="composer-drop-overlay">
                            <Paperclip size={18} /> Drop files to add context
                        </div>
                    )}
                    {(attachments.length > 0 ||
                        uploading ||
                        attachmentError) && (
                        <div className="attachment-strip">
                            {attachments.map((item) => (
                                <span
                                    className="attachment-chip"
                                    key={item.name}
                                >
                                    {item.kind === "image" ? (
                                        <Image size={14} />
                                    ) : (
                                        <FileText size={14} />
                                    )}
                                    <span
                                        title={
                                            item.asset
                                                ? `Asset token: asset::${item.asset.id}`
                                                : item.name
                                        }
                                    >
                                        {item.name}
                                    </span>
                                    {item.truncated && <small>compact</small>}
                                    <button
                                        type="button"
                                        aria-label={`Remove ${item.name}`}
                                        onClick={() =>
                                            setAttachments((current) =>
                                                current.filter(
                                                    (entry) =>
                                                        entry.name !==
                                                        item.name,
                                                ),
                                            )
                                        }
                                    >
                                        <X size={13} />
                                    </button>
                                </span>
                            ))}
                            {uploading && (
                                <span className="attachment-loading">
                                    <LoaderCircle size={14} /> Parsing file…
                                </span>
                            )}
                            {attachmentError && (
                                <span className="attachment-error">
                                    {attachmentError}
                                </span>
                            )}
                        </div>
                    )}
                    {selection && (
                        <div className="attachment-strip">
                            <span className="attachment-chip" title={selection.element.html}>
                                <MousePointerClick size={14} />
                                <span>
                                    {selection.screenName}: {selection.element.text.slice(0, 40) || `<${selection.element.tag}>`}
                                </span>
                                <button type="button" aria-label="Bỏ chọn" onClick={() => setSelection(undefined)}>
                                    <X size={13} />
                                </button>
                            </span>
                        </div>
                    )}
                    <div className="composer-input-area">
                        {mention && (
                            <MentionMenu
                                files={mentionMatches}
                                activeIndex={mentionIndex}
                                query={mention.query}
                                onPick={pickMention}
                                onHover={setMentionIndex}
                            />
                        )}
                        <textarea
                            ref={textareaRef}
                            value={prompt}
                            onBlur={() => setTimeout(() => setMention(null), 150)}
                            onChange={(event) => {
                                setPrompt(event.target.value);
                                updateMention(event.target.value, event.target.selectionStart ?? event.target.value.length);
                                if (textareaRef.current) {
                                    textareaRef.current.style.height = "auto";
                                    textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 140)}px`;
                                }
                            }}
                            onKeyDown={(event) => {
                                if (mention && mentionMatches.length > 0) {
                                    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
                                        event.preventDefault();
                                        const step = event.key === "ArrowDown" ? 1 : -1;
                                        setMentionIndex(
                                            (i) => (i + step + mentionMatches.length) % mentionMatches.length,
                                        );
                                        return;
                                    }
                                    if (event.key === "Enter" || event.key === "Tab") {
                                        event.preventDefault();
                                        pickMention(mentionMatches[Math.min(mentionIndex, mentionMatches.length - 1)]);
                                        return;
                                    }
                                }
                                if (mention && event.key === "Escape") {
                                    event.preventDefault();
                                    setMention(null);
                                    return;
                                }
                                if (event.key === "Enter" && !event.shiftKey) {
                                    event.preventDefault();
                                    submit();
                                }
                            }}
                            placeholder="Ask anything, or describe a screen to generate… (@ để trích dẫn file dự án)"
                            maxLength={8000}
                            rows={1}
                        />
                    </div>

                    <div className="composer-bottom-bar">
                        <div className="composer-pills-left">
                            {onOpenCanvas && (
                                <button className="composer-mini-pill" type="button" onClick={onOpenCanvas}
                                    title="Mở trang thiết kế ở tab mới">
                                    <ExternalLink size={14} /> Trang thiết kế
                                </button>
                            )}

                            <StyleSelector
                                value={styleName}
                                onChange={setStyleName}
                            />
                        </div>

                        <div className="composer-actions-right">
                            <input
                                ref={fileInputRef}
                                className="attachment-input"
                                type="file"
                                multiple
                                accept=".png,.jpg,.jpeg,.svg,.webp,.txt,.md,.json,.csv,.yaml,.yml,.bpmn,.bpmn2"
                                onChange={(event) => {
                                    void addFiles(
                                        Array.from(event.target.files ?? []),
                                    );
                                    event.target.value = "";
                                }}
                            />
                            <button
                                className={`composer-attach-btn ${uploading ? "is-uploading" : ""}`}
                                type="button"
                                onClick={() => fileInputRef.current?.click()}
                                disabled={
                                    busy || uploading || attachments.length >= 4
                                }
                                title="Attach requirements, BPMN, JSON, text, Markdown, or image"
                                aria-label="Attach file"
                            >
                                {uploading ? (
                                    <LoaderCircle size={16} />
                                ) : (
                                    <Paperclip size={16} />
                                )}
                            </button>
                            {busy && (
                                <button
                                    className="composer-cancel"
                                    onClick={onCancel}
                                    type="button"
                                >
                                    Cancel
                                </button>
                            )}
                            <span className="composer-shortcut">↵ Enter</span>
                            <button
                                className="composer-send-btn"
                                onClick={submit}
                                disabled={
                                    busy ||
                                    uploading ||
                                    (prompt.trim().length < 3 &&
                                        attachments.length === 0)
                                }
                                title={
                                    busy
                                        ? "Agent is working..."
                                        : "Send prompt (Enter)"
                                }
                                type="button"
                            >
                                <ArrowUp size={16} strokeWidth={2.5} />
                            </button>
                        </div>
                    </div>
                </section>
            </div>
        </main>
    );
}
