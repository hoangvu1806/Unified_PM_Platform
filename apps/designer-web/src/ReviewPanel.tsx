import {
    Box,
    Braces,
    Check,
    ChevronRight,
    Component,
    Copy,
    Eye,
    Layers,
    LayoutGrid,
    MessageSquareText,
    Monitor,
    Smartphone,
    Sparkles,
    Tablet,
    X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import {
    PreviewCanvas,
    PreviewToolbar,
    type PreviewSize,
} from "./SemanticPreview";
import type { Run, RunArtifacts, UiNode, UiSpecification } from "./types";

interface Props {
    run?: Run;
    artifacts?: RunArtifacts;
    onRecheckLayout: () => Promise<void>;
    onReview: (
        decision: "approved" | "changes_requested",
        feedback?: string,
    ) => void;
    onShowFiles?: () => void;
}

interface ScreenItem {
    screen_id: string;
    screen_name: string;
    platforms: string[];
    specification: UiSpecification;
}

function PlatformIcon({ platform }: { platform?: string }) {
    const p = platform?.toLowerCase();
    if (p === "desktop") return <Monitor size={12} />;
    if (p === "tablet") return <Tablet size={12} />;
    return <Smartphone size={12} />;
}

function SkeletonSectionCard({ node, index }: { node: UiNode; index: number }) {
    const role = node.requirement?.role ?? node.kind;
    const variantIntent = node.requirement?.variant_intent;
    const requiredSlots = node.requirement?.required_slots ?? [];
    const layout = node.layout;
    const children = node.children ?? [];

    // Extract text preview if present
    const textPreview =
        typeof node.content?.title === "string"
            ? node.content.title
            : typeof node.content?.text === "string"
              ? node.content.text
              : typeof node.content?.label === "string"
                ? node.content.label
                : "";

    return (
        <div className="skeleton-section-card">
            <div className="skeleton-section-header">
                <div className="skeleton-section-title">
                    <span className="skeleton-index-badge">
                        #{String(index + 1).padStart(2, "0")}
                    </span>
                    <strong>{node.name}</strong>
                </div>
                <div className="skeleton-section-badges">
                    <span className="skeleton-role-badge">{role}</span>
                    {layout && (
                        <span className="skeleton-layout-badge">
                            {layout.mode}{" "}
                            {layout.direction === "row" ? "→" : "↓"}
                            {layout.columns ? ` (${layout.columns}c)` : ""}
                        </span>
                    )}
                </div>
            </div>

            {textPreview && (
                <p className="skeleton-text-preview">"{textPreview}"</p>
            )}

            {variantIntent && (
                <div className="skeleton-intent-note">
                    <Sparkles size={11} />
                    <span>Intent: {variantIntent}</span>
                </div>
            )}

            {requiredSlots.length > 0 && (
                <div className="skeleton-slots-row">
                    <span className="skeleton-slots-label">Slots:</span>
                    {requiredSlots.map((slot) => (
                        <span className="skeleton-slot-chip" key={slot}>
                            {slot}
                        </span>
                    ))}
                </div>
            )}

            {children.length > 0 && (
                <div className="skeleton-children-section">
                    <span className="skeleton-children-label">
                        Components ({children.length}):
                    </span>
                    <div className="skeleton-children-grid">
                        {children.map((child, cIdx) => (
                            <div
                                className="skeleton-child-chip"
                                key={child.id || `child-${cIdx}`}
                            >
                                <Component size={11} />
                                <span>{child.name}</span>
                                <small>
                                    {child.requirement?.role || child.kind}
                                </small>
                            </div>
                        ))}
                    </div>
                </div>
            )}
        </div>
    );
}

export function ReviewPanel({ run, artifacts, onRecheckLayout, onReview, onShowFiles }: Props) {
    const [tab, setTab] = useState<"review" | "preview" | "json">("review");
    const [jsonSubTab, setJsonSubTab] = useState<"project" | "screen">(
        "project",
    );
    const [selectedScreenIndex, setSelectedScreenIndex] = useState(0);
    const [feedback, setFeedback] = useState("");
    const [previewSize, setPreviewSize] = useState<PreviewSize>("fit");
    const [previewExpanded, setPreviewExpanded] = useState(false);
    const [copiedJson, setCopiedJson] = useState(false);
    const [submitting, setSubmitting] = useState(false);
    const [rechecking, setRechecking] = useState(false);

    // Extract complete screens list
    const screens: ScreenItem[] = useMemo(() => {
        if (artifacts?.project_specification?.screens?.length) {
            return artifacts.project_specification.screens.map((item, idx) => ({
                screen_id: item.screen_id || `screen_${idx + 1}`,
                screen_name:
                    item.specification?.screen_name ||
                    item.screen_id ||
                    `Screen ${idx + 1}`,
                platforms:
                    item.platforms ||
                    (item.specification?.platform
                        ? [item.specification.platform]
                        : ["mobile"]),
                specification: item.specification,
            }));
        }
        if (run?.specification) {
            return [
                {
                    screen_id: run.screen_name || "screen_1",
                    screen_name:
                        run.specification.screen_name ||
                        run.screen_name ||
                        "Screen 1",
                    platforms: [
                        run.specification.platform || run.platform || "mobile",
                    ],
                    specification: run.specification,
                },
            ];
        }
        return [];
    }, [
        artifacts?.project_specification,
        run?.specification,
        run?.screen_name,
        run?.platform,
    ]);

    // Ensure selected screen index is always valid
    const safeScreenIndex =
        selectedScreenIndex >= 0 && selectedScreenIndex < screens.length
            ? selectedScreenIndex
            : 0;
    const activeScreen = screens[safeScreenIndex];
    const activeSpec: UiSpecification | undefined =
        activeScreen?.specification ?? run?.specification;

    const handleAction = async (
        decision: "approved" | "changes_requested",
        fb?: string,
    ) => {
        if (submitting) return;
        setSubmitting(true);
        try {
            await onReview(decision, fb);
        } finally {
            setSubmitting(false);
        }
    };

    const handleRecheckLayout = async () => {
        if (rechecking) return;
        setRechecking(true);
        try {
            await onRecheckLayout();
        } finally {
            setRechecking(false);
        }
    };

    const canReview =
        (run?.stage === "review_spec" || run?.stage === "review_final") &&
        run.status === "waiting_review";
    const layout = artifacts?.layout_review;
    const finalBlocked =
        run?.stage === "review_final" && layout?.status !== "valid";

    const copyJson = async () => {
        const value =
            jsonSubTab === "screen" && activeSpec
                ? activeSpec
                : (artifacts?.project_specification ?? run?.specification);
        if (!value) return;
        try {
            await navigator.clipboard.writeText(JSON.stringify(value, null, 2));
            setCopiedJson(true);
            setTimeout(() => setCopiedJson(false), 2000);
        } catch {
            // ignore
        }
    };

    useEffect(() => {
        if (!previewExpanded) return;
        const close = (event: KeyboardEvent) => {
            if (event.key === "Escape") setPreviewExpanded(false);
        };
        window.addEventListener("keydown", close);
        return () => window.removeEventListener("keydown", close);
    }, [previewExpanded]);

    // Section skeletons of active specification
    const skeletonSections = activeSpec?.root?.children ?? [];

    return (
        <>
            <aside
                className="review-panel"
                aria-label="UI Specification Review Panel"
            >
                <header>
                    <div>
                        <span className="eyebrow">Workbench</span>
                        <h2>
                            {activeScreen?.screen_name ??
                                run?.screen_name ??
                                "Review"}
                        </h2>
                    </div>
                    <div
                        style={{
                            display: "flex",
                            alignItems: "center",
                            gap: 6,
                        }}
                    >
                        {screens.length > 1 && (
                            <span
                                className="revision"
                                title={`${screens.length} total screens`}
                            >
                                {screens.length} Screens
                            </span>
                        )}
                        <span
                            className="revision"
                            title={`Revision ${run?.revision ?? 1}`}
                        >
                            R{String(run?.revision ?? 1).padStart(2, "0")}
                        </span>
                        {onShowFiles && (
                            <button className="panel-switch" type="button" onClick={onShowFiles}>
                                Files dự án
                            </button>
                        )}
                    </div>
                </header>

                <div className="review-tabs">
                    <button
                        className={tab === "review" ? "active" : ""}
                        onClick={() => setTab("review")}
                        type="button"
                    >
                        <MessageSquareText size={15} /> Review
                    </button>
                    <button
                        className={tab === "preview" ? "active" : ""}
                        onClick={() => setTab("preview")}
                        type="button"
                    >
                        <Eye size={15} /> Preview
                    </button>
                    <button
                        className={tab === "json" ? "active" : ""}
                        onClick={() => setTab("json")}
                        type="button"
                    >
                        <Braces size={15} /> JSON
                    </button>
                </div>

                {/* Multi-screen Selector Bar when screens exist */}
                {screens.length > 1 && (
                    <div className="screen-selector-bar-wrapper">
                        <div className="screen-selector-bar">
                            <span className="screen-selector-label">
                                <Layers size={13} /> Screens ({screens.length}):
                            </span>
                            <div className="screen-selector-pills">
                                {screens.map((item, idx) => {
                                    const isSelected = idx === safeScreenIndex;
                                    const secCount =
                                        item.specification?.root?.children
                                            ?.length ?? 0;
                                    return (
                                        <button
                                            key={item.screen_id}
                                            className={`screen-tab-btn ${isSelected ? "active" : ""}`}
                                            onClick={() =>
                                                setSelectedScreenIndex(idx)
                                            }
                                            type="button"
                                            title={`Switch to Screen #${idx + 1}: ${item.screen_name}`}
                                        >
                                            <span className="screen-tab-num">
                                                {String(idx + 1).padStart(
                                                    2,
                                                    "0",
                                                )}
                                            </span>
                                            <span className="screen-tab-name">
                                                {item.screen_name}
                                            </span>
                                            <span className="screen-tab-badge">
                                                {secCount} sections
                                            </span>
                                        </button>
                                    );
                                })}
                            </div>
                        </div>
                    </div>
                )}

                <div className="review-content">
                    {tab === "review" && (
                        <div className="review-copy">
                            <div className="review-header-badge-row">
                                <span className="review-kicker">
                                    {canReview
                                        ? "Decision Required"
                                        : "Live Run Context"}
                                </span>
                                {screens.length > 1 && (
                                    <span className="screen-counter-pill">
                                        Screen {safeScreenIndex + 1} of{" "}
                                        {screens.length}
                                    </span>
                                )}
                            </div>

                            <h3>
                                {run?.intent === "chat"
                                    ? run.assistant_message
                                    : (activeSpec?.summary ??
                                      run?.specification?.summary ??
                                      "The structured UI specification will appear here once ready.")}
                            </h3>

                            {/* Active Screen Specs Meta */}
                            {activeSpec && (
                                <dl className="review-spec-meta">
                                    <div>
                                        <dt>Active Screen</dt>
                                        <dd>{activeSpec.screen_name}</dd>
                                    </div>
                                    <div>
                                        <dt>Platform</dt>
                                        <dd
                                            style={{
                                                display: "inline-flex",
                                                alignItems: "center",
                                                gap: 5,
                                            }}
                                        >
                                            <PlatformIcon
                                                platform={activeSpec.platform}
                                            />
                                            {activeSpec.platform}
                                        </dd>
                                    </div>
                                    <div>
                                        <dt>Target Viewport</dt>
                                        <dd>
                                            {activeSpec.viewport_width} ×{" "}
                                            {activeSpec.viewport_height} px
                                        </dd>
                                    </div>
                                    <div>
                                        <dt>Skeleton Sections</dt>
                                        <dd>
                                            {skeletonSections.length} sections
                                            planned
                                        </dd>
                                    </div>
                                    <div>
                                        <dt>Current Stage</dt>
                                        <dd>
                                            {run?.stage.replaceAll("_", " ")}
                                        </dd>
                                    </div>
                                    {run?.mcp_profile?.output_file && (
                                        <div>
                                            <dt>Output File</dt>
                                            <dd
                                                title={
                                                    run.mcp_profile.output_file
                                                }
                                            >
                                                {run.mcp_profile.output_file}
                                            </dd>
                                        </div>
                                    )}
                                </dl>
                            )}

                            {/* Skeleton Section Hierarchy List for Active Screen */}
                            {skeletonSections.length > 0 && (
                                <div className="skeleton-list-container">
                                    <div className="skeleton-list-header">
                                        <div className="skeleton-list-title">
                                            <LayoutGrid size={15} />
                                            <strong>
                                                Skeleton Structure (
                                                {skeletonSections.length}{" "}
                                                Sections)
                                            </strong>
                                        </div>
                                        <small>{activeSpec?.screen_name}</small>
                                    </div>

                                    <div className="skeleton-sections-list">
                                        {skeletonSections.map(
                                            (secNode, index) => (
                                                <SkeletonSectionCard
                                                    key={
                                                        secNode.id ||
                                                        `sec-${index}`
                                                    }
                                                    node={secNode}
                                                    index={index}
                                                />
                                            ),
                                        )}
                                    </div>
                                </div>
                            )}

                            {/* Project Specification Summary & Multi-Screen Overview */}
                            {artifacts?.project_specification && (
                                <div className="artifact-card project-overview-card">
                                    <div className="artifact-card-header">
                                        <span>Project specification</span>
                                        <span className="screens-total-badge">
                                            {
                                                artifacts.project_specification
                                                    .screens.length
                                            }{" "}
                                            Screens
                                        </span>
                                    </div>
                                    <strong>
                                        {
                                            artifacts.project_specification
                                                .brief.product_name
                                        }
                                    </strong>
                                    <p className="project-description-text">
                                        {
                                            artifacts.project_specification
                                                .brief.product_description
                                        }
                                    </p>

                                    <div className="screen-overview-grid">
                                        {screens.map((item, idx) => {
                                            const isSelected =
                                                idx === safeScreenIndex;
                                            const secCount =
                                                item.specification?.root
                                                    ?.children?.length ?? 0;
                                            return (
                                                <button
                                                    key={item.screen_id}
                                                    className={`screen-overview-pill-btn ${isSelected ? "selected" : ""}`}
                                                    onClick={() =>
                                                        setSelectedScreenIndex(
                                                            idx,
                                                        )
                                                    }
                                                    type="button"
                                                >
                                                    <span className="screen-overview-num">
                                                        #{idx + 1}
                                                    </span>
                                                    <div className="screen-overview-info">
                                                        <strong>
                                                            {item.screen_name}
                                                        </strong>
                                                        <small>
                                                            {secCount} sections
                                                            ·{" "}
                                                            {item.platforms.join(
                                                                ", ",
                                                            )}
                                                        </small>
                                                    </div>
                                                    <ChevronRight
                                                        size={14}
                                                        className="screen-overview-arrow"
                                                    />
                                                </button>
                                            );
                                        })}
                                    </div>

                                    <small className="project-meta-footer">
                                        Platforms:{" "}
                                        {artifacts.project_specification.brief.platforms.join(
                                            ", ",
                                        )}
                                        {artifacts.project_specification.brief
                                            .style_name &&
                                            ` · Style: ${artifacts.project_specification.brief.style_name}`}
                                    </small>
                                </div>
                            )}

                            {artifacts?.knowledge_snapshot?.libraries
                                ?.length ? (
                                <p className="artifact-note">
                                    Knowledge:{" "}
                                    {artifacts.knowledge_snapshot.libraries.join(
                                        ", ",
                                    )}
                                </p>
                            ) : null}

                            {artifacts?.openpencil_artifact && (
                                <div className="artifact-card">
                                    <span>OpenPencil output</span>
                                    <strong>
                                        {
                                            artifacts.openpencil_artifact
                                                .page_name
                                        }
                                    </strong>
                                    <code>
                                        {
                                            artifacts.openpencil_artifact
                                                .output_file
                                        }
                                    </code>
                                    <button
                                        className="secondary-button compact"
                                        type="button"
                                        onClick={() =>
                                            navigator.clipboard.writeText(
                                                artifacts.openpencil_artifact
                                                    ?.output_file ?? "",
                                            )
                                        }
                                    >
                                        <Copy size={13} /> Copy path
                                    </button>
                                </div>
                            )}

                            {layout && (
                                <div
                                    className={`layout-result ${layout.status}`}
                                >
                                    <div className="layout-result-header">
                                        <strong>Layout {layout.status}</strong>
                                        {run?.stage === "review_final" &&
                                            run.status === "waiting_review" && (
                                                <button
                                                    className="secondary-button compact"
                                                    type="button"
                                                    onClick={() => void handleRecheckLayout()}
                                                    disabled={rechecking}
                                                >
                                                    {rechecking
                                                        ? "Rechecking…"
                                                        : "Recheck OpenPencil"}
                                                </button>
                                            )}
                                    </div>
                                    <p>{layout.summary}</p>
                                    {layout.findings.map((finding, index) => (
                                        <div
                                            className={`layout-finding ${finding.severity}`}
                                            key={`${finding.category}-${index}`}
                                        >
                                            <span>{finding.category}</span>
                                            <p>{finding.evidence}</p>
                                            <small>{finding.correction}</small>
                                        </div>
                                    ))}
                                </div>
                            )}

                            {canReview && (
                                <div>
                                    <label
                                        htmlFor="review-feedback-input"
                                        style={{
                                            fontSize: "12px",
                                            fontWeight: 600,
                                            color: "var(--text-muted)",
                                            display: "block",
                                            marginBottom: "6px",
                                        }}
                                    >
                                        Revision Notes (Optional):
                                    </label>
                                    <textarea
                                        id="review-feedback-input"
                                        value={feedback}
                                        onChange={(event) =>
                                            setFeedback(event.target.value)
                                        }
                                        placeholder="Enter any feedback, design changes or adjustments needed..."
                                        rows={4}
                                    />
                                </div>
                            )}
                        </div>
                    )}

                    {tab === "preview" && (
                        <div className="preview-workbench">
                            <div className="preview-screen-header">
                                <div className="preview-screen-title">
                                    <strong>
                                        {activeScreen?.screen_name ??
                                            "Screen Preview"}
                                    </strong>
                                    {activeSpec && (
                                        <span>
                                            {activeSpec.viewport_width} ×{" "}
                                            {activeSpec.viewport_height} px
                                        </span>
                                    )}
                                </div>
                                <PreviewToolbar
                                    size={previewSize}
                                    expanded={false}
                                    onSize={setPreviewSize}
                                    onExpand={() => setPreviewExpanded(true)}
                                />
                            </div>
                            <PreviewCanvas
                                run={run}
                                specification={activeSpec}
                                size={previewSize}
                            />
                        </div>
                    )}

                    {tab === "json" && (
                        <div className="json-view-container">
                            <div className="json-view-header">
                                {screens.length > 1 && (
                                    <div className="json-subtabs">
                                        <button
                                            type="button"
                                            className={`json-subtab-btn ${jsonSubTab === "project" ? "active" : ""}`}
                                            onClick={() =>
                                                setJsonSubTab("project")
                                            }
                                        >
                                            Project Spec ({screens.length}{" "}
                                            Screens)
                                        </button>
                                        <button
                                            type="button"
                                            className={`json-subtab-btn ${jsonSubTab === "screen" ? "active" : ""}`}
                                            onClick={() =>
                                                setJsonSubTab("screen")
                                            }
                                        >
                                            {activeScreen?.screen_name ??
                                                "Active Screen"}
                                        </button>
                                    </div>
                                )}
                                {(artifacts?.project_specification ||
                                    run?.specification) && (
                                    <button
                                        className="md-copy-btn"
                                        onClick={copyJson}
                                        type="button"
                                        title="Copy specification JSON"
                                    >
                                        {copiedJson ? (
                                            <Check size={13} />
                                        ) : (
                                            <Copy size={13} />
                                        )}
                                        <span>
                                            {copiedJson
                                                ? "Copied"
                                                : "Copy JSON"}
                                        </span>
                                    </button>
                                )}
                            </div>
                            <pre>
                                {artifacts?.project_specification ||
                                run?.specification
                                    ? JSON.stringify(
                                          jsonSubTab === "screen" && activeSpec
                                              ? activeSpec
                                              : {
                                                    specification:
                                                        artifacts?.project_specification ??
                                                        run?.specification,
                                                    artifacts,
                                                },
                                          null,
                                          2,
                                      )
                                    : "No specification generated yet."}
                            </pre>
                        </div>
                    )}
                </div>

                {canReview && (
                    <footer>
                        <button
                            className="request-change"
                            onClick={() =>
                                handleAction("changes_requested", feedback)
                            }
                            disabled={submitting}
                            type="button"
                        >
                            <X size={16} /> Request Changes
                        </button>
                        <button
                            className="approve"
                            onClick={() => handleAction("approved")}
                            disabled={finalBlocked || submitting}
                            title={
                                finalBlocked
                                    ? "Resolve blocking layout findings first"
                                    : undefined
                            }
                            type="button"
                        >
                            <Check size={16} />{" "}
                            {submitting
                                ? "Processing..."
                                : run?.stage === "review_final"
                                  ? "Approve Design"
                                  : "Approve Structure"}
                        </button>
                    </footer>
                )}
            </aside>

            {previewExpanded && (
                <div
                    className="preview-modal"
                    role="dialog"
                    aria-modal="true"
                    aria-label={`${activeScreen?.screen_name ?? run?.screen_name ?? "UI"} Expanded Preview`}
                >
                    <header>
                        <div
                            style={{
                                display: "flex",
                                alignItems: "center",
                                gap: 12,
                            }}
                        >
                            <div>
                                <span className="eyebrow">
                                    Responsive Preview
                                </span>
                                <h2>
                                    {activeScreen?.screen_name ??
                                        run?.screen_name ??
                                        "Preview"}
                                </h2>
                            </div>
                            {screens.length > 1 && (
                                <div className="screen-selector-pills modal-pills">
                                    {screens.map((item, idx) => (
                                        <button
                                            key={item.screen_id}
                                            className={`screen-tab-btn ${idx === safeScreenIndex ? "active" : ""}`}
                                            onClick={() =>
                                                setSelectedScreenIndex(idx)
                                            }
                                            type="button"
                                        >
                                            <span className="screen-tab-num">
                                                {idx + 1}
                                            </span>
                                            <span className="screen-tab-name">
                                                {item.screen_name}
                                            </span>
                                        </button>
                                    ))}
                                </div>
                            )}
                        </div>
                        <PreviewToolbar
                            size={previewSize}
                            expanded
                            onSize={setPreviewSize}
                            onExpand={() => setPreviewExpanded(false)}
                        />
                    </header>
                    <PreviewCanvas
                        run={run}
                        specification={activeSpec}
                        size={previewSize}
                    />
                </div>
            )}
        </>
    );
}
