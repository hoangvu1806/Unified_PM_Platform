import { AlertTriangle, CheckCircle2, Circle, CircleDot, FileJson } from "lucide-react";
import { useEffect, useState } from "react";
import { isEmbedded, projectId } from "./platform";
import type { Session } from "./types";

type Feature = { session_id: string; title: string; updated_at: string };
type Step = { key: string; label: string; role: string; status: string; reason: string | null };
type Journey = {
    feature: { id: string; title: string; status: string };
    steps: Step[];
    ba_package: { latest_version: number | null; used_by_design: number | null; stale: boolean };
};

const STATUS_LABEL: Record<string, string> = {
    DRAFT: "Nháp",
    IN_PROGRESS: "Đang phân tích",
    PENDING_VALIDATION: "Chờ kiểm tra",
    VALIDATED: "Đã kiểm tra",
    VALIDATION_FAILED: "Kiểm tra chưa đạt",
    EXPORTED: "Đã bàn giao",
};

const pickKey = (sessionId: string) => `designer.ba-feature.${sessionId}`;

/** Left-rail panel: where the BA side of this design stands (read from the journey API).
 *  A handed-off session follows its feature; any other session in the project shows the
 *  project's BA features (latest first, choice remembered per session). */
export function BaStatusPanel({ session }: { session?: Session }) {
    const handoffFeature = session?.source === "ba-handoff" ? session.source_ref ?? null : null;
    const [features, setFeatures] = useState<Feature[] | null>(null);
    const [picked, setPicked] = useState<string | null>(null);
    const [journey, setJourney] = useState<Journey | null>(null);

    useEffect(() => {
        setFeatures(null);
        if (handoffFeature || !projectId || !session) return;
        try {
            setPicked(localStorage.getItem(pickKey(session.id)));
        } catch {
            setPicked(null);
        }
        fetch(`/ba/api/features?project_id=${encodeURIComponent(projectId)}`, { credentials: "same-origin" })
            .then((r) => (r.ok ? r.json() : []))
            .then((items: Feature[]) =>
                setFeatures([...items].sort((a, b) => b.updated_at.localeCompare(a.updated_at))),
            )
            .catch(() => setFeatures([]));
    }, [handoffFeature, session?.id]);

    const featureId =
        handoffFeature ??
        (features?.find((f) => f.session_id === picked)?.session_id || features?.[0]?.session_id || null);
    const choose = (id: string) => {
        setPicked(id);
        try {
            if (session) localStorage.setItem(pickKey(session.id), id);
        } catch {
            /* private mode */
        }
    };

    useEffect(() => {
        setJourney(null);
        if (!featureId || !projectId) return;
        let alive = true;
        const load = () =>
            fetch(
                `/api/core/projects/${encodeURIComponent(projectId)}/features/${encodeURIComponent(featureId)}/journey`,
                { credentials: "same-origin" },
            )
                .then((r) => (r.ok ? r.json() : null))
                .then((j) => alive && j && setJourney(j as Journey))
                .catch(() => undefined);
        void load();
        const timer = window.setInterval(load, 20000);
        return () => {
            alive = false;
            window.clearInterval(timer);
        };
    }, [featureId]);

    if (!session) return null;
    if (!featureId) {
        return (
            <section className="ba-status">
                <div className="rail-label">Trạng thái BA</div>
                <p className="ba-status-empty">
                    {features === null ? "Đang tải…" : "Dự án chưa có feature BA nào. Thiết kế tự do hoặc tạo feature ở portal."}
                </p>
            </section>
        );
    }
    if (!journey) {
        return (
            <section className="ba-status">
                <div className="rail-label">Trạng thái BA</div>
                <p className="ba-status-empty">Đang tải…</p>
            </section>
        );
    }

    const openStep = (key: string) => {
        if (isEmbedded) {
            window.parent.postMessage({ type: "platform:show-step", key }, window.location.origin);
        } else {
            window.location.assign(`/projects/${encodeURIComponent(projectId)}/f/${encodeURIComponent(featureId)}`);
        }
    };
    const baSteps = journey.steps.filter((s) => s.role === "BA");
    const { latest_version, used_by_design, stale } = journey.ba_package;

    return (
        <section className="ba-status">
            <div className="rail-label">Trạng thái BA</div>
            <div className="ba-status-card">
                {!handoffFeature && features && features.length > 1 ? (
                    <select
                        className="ba-status-select"
                        value={featureId}
                        onChange={(e) => choose(e.target.value)}
                        title="Feature BA của dự án"
                    >
                        {features.map((f) => (
                            <option key={f.session_id} value={f.session_id}>
                                {f.title}
                            </option>
                        ))}
                    </select>
                ) : (
                    <div className="ba-status-title" title={journey.feature.title}>
                        {journey.feature.title}
                    </div>
                )}
                {!handoffFeature && <span className="ba-status-note">Cùng dự án · chưa bàn giao cho phiên này</span>}
                <span className="ba-status-state">{STATUS_LABEL[journey.feature.status] ?? journey.feature.status}</span>
                <ul>
                    {baSteps.map((s) => (
                        <li key={s.key}>
                            <button type="button" onClick={() => openStep(s.key)} title="Xem bước này (BA)">
                                {s.status === "done" ? (
                                    <CheckCircle2 size={14} className="ok" />
                                ) : s.status === "attention" ? (
                                    <AlertTriangle size={14} className="warn" />
                                ) : s.status === "current" ? (
                                    <CircleDot size={14} className="now" />
                                ) : (
                                    <Circle size={14} />
                                )}
                                <span>{s.label}</span>
                            </button>
                        </li>
                    ))}
                </ul>
                <div className="ba-status-package">
                    <FileJson size={13} />
                    {latest_version ? (
                        <span>
                            BA package v{latest_version}
                            {used_by_design ? ` · thiết kế dùng v${used_by_design}` : ""}
                        </span>
                    ) : (
                        <span>Chưa có BA package</span>
                    )}
                </div>
                {stale && (
                    <div className="ba-status-stale">
                        <AlertTriangle size={13} /> BA đã có bản mới hơn — cần xem lại thiết kế.
                    </div>
                )}
            </div>
        </section>
    );
}
