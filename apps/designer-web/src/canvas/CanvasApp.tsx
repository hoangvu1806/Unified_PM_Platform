import {
    Code2,
    Download,
    FileArchive,
    History,
    Image,
    Monitor,
    MousePointerClick,
    RefreshCw,
    Save,
    Search,
    Smartphone,
    Tablet,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useTheme } from "../theme";
import type { Screen, ScreenVersion } from "../types";

const params = new URLSearchParams(window.location.search);
const SESSION = params.get("session") || "";
const DESIGN_SYSTEM = params.get("ds") || "";
const VIEWPORTS = [
    { id: "auto", label: "Gốc", icon: Monitor, width: 0 },
    { id: "desktop", label: "Desktop", icon: Monitor, width: 1440 },
    { id: "tablet", label: "Tablet", icon: Tablet, width: 834 },
    { id: "mobile", label: "Mobile", icon: Smartphone, width: 390 },
] as const;
const POLL_MS = 3000;

/** Messages posted by app/render/runtime.js inside the screen iframe. */
type ScreenMessage =
    | { source: "designer-screen"; type: "ready"; states: string[]; height: number }
    | { source: "designer-screen"; type: "goto"; screen: string }
    | { source: "designer-screen"; type: "select"; element: { id: string; tag: string; text: string; html: string } };

export function CanvasApp() {
    useTheme();
    return DESIGN_SYSTEM ? <Gallery id={DESIGN_SYSTEM} /> : SESSION ? <ScreensCanvas /> : <p className="canvas-empty">Thiếu session.</p>;
}

function Frame({
    doc,
    width,
    onMessage,
    frameRef,
}: {
    doc: string;
    width: number;
    onMessage: (message: ScreenMessage) => void;
    frameRef: React.RefObject<HTMLIFrameElement | null>;
}) {
    const stage = useRef<HTMLDivElement>(null);
    const [height, setHeight] = useState(900);
    const [scale, setScale] = useState(1);

    useEffect(() => {
        const listen = (event: MessageEvent) => {
            if (event.source !== frameRef.current?.contentWindow) return;
            const data = event.data as ScreenMessage;
            if (data?.source !== "designer-screen") return;
            if (data.type === "ready") setHeight(Math.max(600, data.height));
            onMessage(data);
        };
        window.addEventListener("message", listen);
        return () => window.removeEventListener("message", listen);
    }, [onMessage, frameRef]);

    useEffect(() => {
        const fit = () => {
            const available = (stage.current?.clientWidth ?? width) - 48;
            setScale(Math.min(1, available / width));
        };
        fit();
        window.addEventListener("resize", fit);
        return () => window.removeEventListener("resize", fit);
    }, [width]);

    return (
        <div className="canvas-stage" ref={stage}>
            <div className="canvas-frame-box" style={{ width: width * scale, height: height * scale }}>
                {/* Opaque origin (no allow-same-origin): the screen's scripts cannot reach the studio. */}
                <iframe
                    ref={frameRef}
                    title="screen"
                    sandbox="allow-scripts allow-forms allow-popups"
                    srcDoc={doc}
                    style={{ width, height, transform: `scale(${scale})` }}
                />
            </div>
        </div>
    );
}

function ScreensCanvas() {
    const [screens, setScreens] = useState<Screen[]>([]);
    const [current, setCurrent] = useState(params.get("screen") || "");
    const [doc, setDoc] = useState("");
    const [viewport, setViewport] = useState<(typeof VIEWPORTS)[number]["id"]>("auto");
    const [states, setStates] = useState<string[]>([]);
    const [state, setState] = useState("");
    const [selecting, setSelecting] = useState(false);
    const [codeOpen, setCodeOpen] = useState(false);
    const [code, setCode] = useState("");
    const [versions, setVersions] = useState<ScreenVersion[]>([]);
    const [version, setVersion] = useState<number>();
    const [toast, setToast] = useState("");
    const frameRef = useRef<HTMLIFrameElement>(null);
    const channel = useMemo(
        () => (typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(`designer-canvas-${SESSION}`) : null),
        [],
    );

    const screen = screens.find((s) => s.id === current) ?? screens[0];
    const width = viewport === "auto" ? (screen?.width ?? 1440) : VIEWPORTS.find((v) => v.id === viewport)!.width;

    const loadScreens = useCallback(async () => {
        const items = await api.listScreens(SESSION);
        setScreens((old) =>
            old.length === items.length && old.every((s, i) => s.id === items[i].id && s.version === items[i].version)
                ? old
                : items,
        );
    }, []);

    useEffect(() => {
        void loadScreens().catch((e) => setToast((e as Error).message));
        const timer = window.setInterval(() => void loadScreens().catch(() => undefined), POLL_MS);
        return () => window.clearInterval(timer);
    }, [loadScreens]);

    // Reload the document when the screen, its latest version or the viewed version changes.
    useEffect(() => {
        if (!screen) return;
        let cancelled = false;
        api.screenDocument(SESSION, screen.id, version).then((d) => !cancelled && setDoc(d)).catch(() => undefined);
        api.screenVersions(SESSION, screen.id).then((v) => !cancelled && setVersions(v)).catch(() => undefined);
        if (codeOpen) api.getScreen(SESSION, screen.id, version).then((s) => !cancelled && setCode(s.html ?? ""));
        return () => {
            cancelled = true;
        };
    }, [screen?.id, screen?.version, version, codeOpen]);

    useEffect(() => {
        setState("");
        setVersion(undefined);
    }, [screen?.id]);

    const post = (message: Record<string, unknown>) => frameRef.current?.contentWindow?.postMessage(message, "*");
    useEffect(() => post({ type: "designer:state", state }), [state, doc]);
    useEffect(() => post({ type: "designer:select", on: selecting }), [selecting, doc]);

    const onMessage = useCallback(
        (message: ScreenMessage) => {
            if (message.type === "ready") {
                setStates(message.states);
                post({ type: "designer:state", state });
                post({ type: "designer:select", on: selecting });
            } else if (message.type === "goto") {
                if (screens.some((s) => s.id === message.screen)) setCurrent(message.screen);
                else setToast(`Chưa có màn hình "${message.screen}"`);
            } else if (message.type === "select" && screen) {
                channel?.postMessage({ type: "select", screenId: screen.id, screenName: screen.name, element: message.element });
                setToast(`Đã gửi phần tử "${message.element.text.slice(0, 40) || message.element.tag}" sang khung chat`);
                setSelecting(false);
            }
        },
        [screens, screen, channel, state, selecting],
    );

    useEffect(() => {
        if (!toast) return;
        const t = window.setTimeout(() => setToast(""), 3500);
        return () => window.clearTimeout(t);
    }, [toast]);

    const saveCode = async () => {
        if (!screen) return;
        try {
            await api.saveScreen(SESSION, screen.id, { name: screen.name, platform: screen.platform, html: code, note: "manual edit" });
            setVersion(undefined);
            await loadScreens();
            setToast("Đã lưu phiên bản mới");
        } catch (error) {
            setToast((error as Error).message);
        }
    };

    if (!screens.length) {
        return (
            <div className="canvas-shell">
                <p className="canvas-empty">
                    Chưa có màn hình nào. Agent sẽ dựng màn hình sau khi bạn duyệt spec; trang này tự cập nhật.
                </p>
            </div>
        );
    }

    return (
        <div className="canvas-shell">
            <aside className="canvas-rail">
                <h1>Màn hình</h1>
                {screens.map((s) => (
                    <button
                        key={s.id}
                        className={`canvas-screen ${s.id === screen?.id ? "active" : ""}`}
                        onClick={() => setCurrent(s.id)}
                        type="button"
                    >
                        <strong>{s.name}</strong>
                        <small>
                            {s.platform} · v{s.version}
                        </small>
                    </button>
                ))}
                <div className="canvas-rail-footer">
                    <a className="secondary-button compact" href={api.exportUrl(SESSION, "fig")}>
                        <Download size={14} /> .fig
                    </a>
                    <a className="secondary-button compact" href={api.exportUrl(SESSION, "zip")}>
                        <FileArchive size={14} /> HTML + PNG
                    </a>
                </div>
            </aside>

            <main className="canvas-main">
                <header className="canvas-toolbar">
                    <div className="canvas-group">
                        {VIEWPORTS.map((v) => (
                            <button key={v.id} className={viewport === v.id ? "active" : ""} onClick={() => setViewport(v.id)} type="button" title={v.label}>
                                <v.icon size={15} /> {v.label}
                            </button>
                        ))}
                    </div>
                    {states.length > 0 && (
                        <select value={state} onChange={(e) => setState(e.target.value)} title="Trạng thái">
                            <option value="">Mặc định</option>
                            {states.map((s) => (
                                <option key={s} value={s}>{s}</option>
                            ))}
                        </select>
                    )}
                    <button className={selecting ? "active" : ""} onClick={() => setSelecting(!selecting)} type="button"
                        title="Chọn một phần tử để góp ý ở khung chat">
                        <MousePointerClick size={15} /> Chọn phần tử
                    </button>
                    <button className={codeOpen ? "active" : ""} onClick={() => setCodeOpen(!codeOpen)} type="button">
                        <Code2 size={15} /> Code
                    </button>
                    <label className="canvas-versions" title="Lịch sử phiên bản">
                        <History size={15} />
                        <select value={version ?? ""} onChange={(e) => setVersion(e.target.value ? Number(e.target.value) : undefined)}>
                            <option value="">Mới nhất (v{screen?.version})</option>
                            {versions.slice(1).map((v) => (
                                <option key={v.version} value={v.version}>
                                    v{v.version} · {v.note || v.updated_by || ""}
                                </option>
                            ))}
                        </select>
                    </label>
                    {screen && (
                        <a className="canvas-link" href={api.screenshotUrl(SESSION, screen.id, state)} target="_blank" rel="noreferrer">
                            <Image size={15} /> PNG
                        </a>
                    )}
                    <button onClick={() => void loadScreens()} type="button" title="Làm mới">
                        <RefreshCw size={15} />
                    </button>
                </header>
                <div className={`canvas-body ${codeOpen ? "with-code" : ""}`}>
                    {doc && <Frame doc={doc} width={width} onMessage={onMessage} frameRef={frameRef} />}
                    {codeOpen && (
                        <section className="canvas-code">
                            <textarea value={code} onChange={(e) => setCode(e.target.value)} spellCheck={false} />
                            <button className="primary-button" onClick={() => void saveCode()} type="button">
                                <Save size={15} /> Lưu thành phiên bản mới
                            </button>
                        </section>
                    )}
                </div>
            </main>
            {toast && <div className="canvas-toast">{toast}</div>}
        </div>
    );
}

function Gallery({ id }: { id: string }) {
    const [doc, setDoc] = useState("");
    const [page, setPage] = useState(0);
    const [q, setQ] = useState("");
    const [query, setQuery] = useState("");
    const frameRef = useRef<HTMLIFrameElement>(null);
    const noop = useCallback(() => undefined, []);

    useEffect(() => {
        api.galleryDocument(id, page, query).then(setDoc).catch((e) => setDoc(`<p>${(e as Error).message}</p>`));
    }, [id, page, query]);

    return (
        <div className="canvas-shell gallery">
            <main className="canvas-main">
                <header className="canvas-toolbar">
                    <form
                        className="canvas-group"
                        onSubmit={(e) => {
                            e.preventDefault();
                            setPage(0);
                            setQuery(q);
                        }}
                    >
                        <Search size={15} />
                        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Tìm component…" />
                    </form>
                    <button disabled={page === 0} onClick={() => setPage(page - 1)} type="button">‹ Trước</button>
                    <span>Trang {page + 1}</span>
                    <button onClick={() => setPage(page + 1)} type="button">Sau ›</button>
                </header>
                <div className="canvas-body">{doc && <Frame doc={doc} width={1280} onMessage={noop} frameRef={frameRef} />}</div>
            </main>
        </div>
    );
}
