import {
    Braces,
    ChevronRight,
    Download,
    ExternalLink,
    Eye,
    FileArchive,
    Layers,
    MessageSquareText,
    Monitor,
    Smartphone,
    Tablet,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { api, canvasUrl } from "./api";
import type { Run, RunArtifacts, Screen, ScreenSpec } from "./types";

interface Props {
    run?: Run;
    sessionId?: string;
    artifacts?: RunArtifacts;
    screensVersion: number;
    onReview: (decision: "approved" | "changes_requested", feedback?: string) => void;
    onShowFiles?: () => void;
}

const PLATFORM_ICON = { mobile: Smartphone, tablet: Tablet, desktop: Monitor, responsive: Monitor };

/** Workbench: the UI specification under review, the built screens, exports and token use. */
export function ReviewPanel({ run, sessionId, artifacts, screensVersion, onReview, onShowFiles }: Props) {
    const [tab, setTab] = useState<"review" | "screens" | "json">("review");
    const [selected, setSelected] = useState(0);
    const [feedback, setFeedback] = useState("");
    const [submitting, setSubmitting] = useState(false);
    const [screens, setScreens] = useState<Screen[]>([]);

    const spec = run?.specification?.schema_version === "html-1" ? run.specification : undefined;
    const specScreens: ScreenSpec[] = spec?.screens ?? [];
    const active = specScreens[Math.min(selected, Math.max(0, specScreens.length - 1))];
    const canReview =
        (run?.stage === "review_spec" || run?.stage === "review_final") && run.status === "waiting_review";

    useEffect(() => {
        if (!sessionId) {
            setScreens([]);
            return;
        }
        api.listScreens(sessionId).then(setScreens).catch(() => setScreens([]));
    }, [sessionId, screensVersion, run?.stage]);

    const usage = artifacts?.token_usage;
    const usageText = useMemo(() => {
        if (!usage?.calls) return "";
        const k = (n?: number) => `${((n ?? 0) / 1000).toFixed(1)}k`;
        return `${usage.calls} lượt gọi · ${k(usage.prompt_tokens)} token vào · ${k(usage.output_tokens)} token ra`;
    }, [usage]);

    const submit = async (decision: "approved" | "changes_requested") => {
        setSubmitting(true);
        try {
            await onReview(decision, feedback);
            setFeedback("");
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <aside className="review-panel" aria-label="Design workbench">
            <header>
                <div>
                    <span className="eyebrow">Workbench</span>
                    <h2>{active?.name ?? run?.screen_name ?? "Review"}</h2>
                </div>
                <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
                    {specScreens.length > 1 && <span className="revision">{specScreens.length} Screens</span>}
                    <span className="revision" title={`Revision ${run?.revision ?? 1}`}>
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
                <button className={tab === "review" ? "active" : ""} onClick={() => setTab("review")} type="button">
                    <MessageSquareText size={15} /> Spec
                </button>
                <button className={tab === "screens" ? "active" : ""} onClick={() => setTab("screens")} type="button">
                    <Eye size={15} /> Màn hình ({screens.length})
                </button>
                <button className={tab === "json" ? "active" : ""} onClick={() => setTab("json")} type="button">
                    <Braces size={15} /> JSON
                </button>
            </div>

            {tab === "review" && (
                <div className="review-body">
                    {!spec && <p className="artifact-note">Chưa có UI specification. Mô tả màn hình cần thiết kế ở khung chat.</p>}
                    {spec && (
                        <>
                            {spec.style_direction && <p className="artifact-note">{spec.style_direction}</p>}
                            <div className="screen-overview-grid">
                                {specScreens.map((item, idx) => {
                                    const Icon = PLATFORM_ICON[item.platform] ?? Monitor;
                                    return (
                                        <button
                                            key={item.id}
                                            className={`screen-overview-pill-btn ${idx === selected ? "selected" : ""}`}
                                            onClick={() => setSelected(idx)}
                                            type="button"
                                        >
                                            <span className="screen-overview-num">#{idx + 1}</span>
                                            <div className="screen-overview-info">
                                                <strong>{item.name}</strong>
                                                <small>
                                                    <Icon size={11} /> {item.platform} · {item.sections?.length ?? 0} vùng ·{" "}
                                                    {item.states?.length ?? 0} trạng thái
                                                </small>
                                            </div>
                                            <ChevronRight size={14} className="screen-overview-arrow" />
                                        </button>
                                    );
                                })}
                            </div>
                            {active && (
                                <div className="skeleton-sections-list">
                                    {active.purpose && <p className="skeleton-intent-note">{active.purpose}</p>}
                                    {active.layout && (
                                        <div className="skeleton-section-card">
                                            <div className="skeleton-section-title">Bố cục</div>
                                            <p>{active.layout}</p>
                                        </div>
                                    )}
                                    {(active.sections ?? []).map((section, i) => (
                                        <div key={i} className="skeleton-section-card">
                                            <div className="skeleton-section-header">
                                                <span className="skeleton-index-badge">{i + 1}</span>
                                                <span className="skeleton-section-title">{section}</span>
                                            </div>
                                        </div>
                                    ))}
                                    {!!active.states?.length && (
                                        <div className="skeleton-slots-row">
                                            <span className="skeleton-slots-label">Trạng thái</span>
                                            {active.states.map((s) => (
                                                <span key={s} className="skeleton-slot-chip">{s}</span>
                                            ))}
                                        </div>
                                    )}
                                    {!!active.source_ui_ids?.length && (
                                        <div className="skeleton-slots-row">
                                            <span className="skeleton-slots-label">BA</span>
                                            {active.source_ui_ids.map((s) => (
                                                <span key={s} className="skeleton-slot-chip">{s}</span>
                                            ))}
                                        </div>
                                    )}
                                    {!!active.data?.length && (
                                        <div className="skeleton-section-card">
                                            <div className="skeleton-section-title">Dữ liệu mẫu</div>
                                            <ul>{active.data.map((d, i) => <li key={i}>{d}</li>)}</ul>
                                        </div>
                                    )}
                                </div>
                            )}
                        </>
                    )}
                    {canReview && (
                        <div className="review-actions">
                            <textarea
                                value={feedback}
                                onChange={(e) => setFeedback(e.target.value)}
                                placeholder="Góp ý (bắt buộc khi yêu cầu sửa)…"
                                rows={3}
                                disabled={submitting}
                            />
                            <div style={{ display: "flex", gap: 8 }}>
                                <button
                                    className="secondary-button"
                                    type="button"
                                    disabled={submitting || !feedback.trim()}
                                    onClick={() => void submit("changes_requested")}
                                >
                                    Yêu cầu sửa
                                </button>
                                <button
                                    className="primary-button"
                                    type="button"
                                    disabled={submitting}
                                    onClick={() => void submit("approved")}
                                >
                                    {run?.stage === "review_final" ? "Duyệt thiết kế" : "Duyệt spec & dựng màn hình"}
                                </button>
                            </div>
                        </div>
                    )}
                    {usageText && <p className="artifact-note" title="Tổng token của run này">Token: {usageText}</p>}
                </div>
            )}

            {tab === "screens" && sessionId && (
                <div className="review-body">
                    {!screens.length && <p className="artifact-note">Chưa có màn hình nào được dựng.</p>}
                    {screens.length > 0 && (
                        <>
                            <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
                                <button
                                    className="primary-button"
                                    type="button"
                                    onClick={() => window.open(canvasUrl(sessionId), `designer-canvas-${sessionId}`)}
                                >
                                    <ExternalLink size={15} /> Mở trang thiết kế
                                </button>
                                <a className="secondary-button" href={api.exportUrl(sessionId, "fig")}>
                                    <Download size={15} /> .fig
                                </a>
                                <a className="secondary-button" href={api.exportUrl(sessionId, "zip")}>
                                    <FileArchive size={15} /> HTML + PNG
                                </a>
                            </div>
                            <div className="screen-overview-grid">
                                {screens.map((screen) => (
                                    <a
                                        key={screen.id}
                                        className="artifact-card"
                                        href={canvasUrl(sessionId) + `&screen=${screen.id}`}
                                        target={`designer-canvas-${sessionId}`}
                                    >
                                        <img
                                            src={`${api.screenshotUrl(sessionId, screen.id)}&v=${screen.version}`}
                                            alt={screen.name}
                                            loading="lazy"
                                            style={{ width: "100%", maxHeight: 180, objectFit: "cover", objectPosition: "top", borderRadius: 8 }}
                                        />
                                        <span>
                                            <Layers size={12} /> {screen.platform} · v{screen.version}
                                        </span>
                                        <strong>{screen.name}</strong>
                                    </a>
                                ))}
                            </div>
                        </>
                    )}
                </div>
            )}

            {tab === "json" && (
                <div className="review-body">
                    <pre className="json-view">{JSON.stringify(spec ?? run?.specification ?? {}, null, 2)}</pre>
                </div>
            )}
        </aside>
    );
}
