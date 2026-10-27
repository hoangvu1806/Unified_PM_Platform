import {
    Check,
    ChevronDown,
    Code2,
    Columns2,
    Download,
    FileArchive,
    Files,
    History,
    Image,
    Layers,
    Monitor,
    MousePointerClick,
    Rows3,
    Save,
    Search,
    Smartphone,
    Square,
    Tablet,
    X,
} from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { useTheme } from "../theme";
import type { Screen, ScreenVersion } from "../types";

const params = new URLSearchParams(window.location.search);
const SESSION = params.get("session") || "";
const DESIGN_SYSTEM = params.get("ds") || "";
const PLATFORMS: Record<string, { label: string; icon: typeof Monitor }> = {
    mobile: { label: "Mobile", icon: Smartphone },
    tablet: { label: "Tablet", icon: Tablet },
    desktop: { label: "Desktop", icon: Monitor },
};
const POLL_MS = 3000;

type FigLayout = "rows" | "pages";
const LAYOUT_KEY = "designer.figLayout";
const FIG_LAYOUTS: { id: FigLayout; label: string; hint: string; icon: typeof Rows3 }[] = [
    { id: "rows", label: "Một page", hint: "Mỗi màn một hàng", icon: Rows3 },
    { id: "pages", label: "Nhiều page", hint: "Mỗi màn một page", icon: Files },
];

function readLayout(): FigLayout {
    try {
        return localStorage.getItem(LAYOUT_KEY) === "pages" ? "pages" : "rows";
    } catch {
        return "rows";
    }
}

/** Custom dropdown that renders entirely in our design tokens — no OS chrome. */
function CanvasPicker<T extends string | number>({
    icon: Icon,
    value,
    options,
    onChange,
    title,
}: {
    icon: React.ComponentType<{ size: number }>;
    value: T;
    options: { value: T; label: string }[];
    onChange: (v: T) => void;
    title?: string;
}) {
    const [open, setOpen] = useState(false);
    const box = useRef<HTMLDivElement>(null);
    const current = options.find((o) => o.value === value);

    useEffect(() => {
        if (!open) return;
        const close = (e: MouseEvent | KeyboardEvent) => {
            if (e instanceof KeyboardEvent ? e.key === "Escape" : !box.current?.contains(e.target as Node)) setOpen(false);
        };
        document.addEventListener("mousedown", close);
        document.addEventListener("keydown", close);
        return () => { document.removeEventListener("mousedown", close); document.removeEventListener("keydown", close); };
    }, [open]);

    return (
        <div className="canvas-picker" ref={box} title={title}>
            <button className="canvas-picker-trigger" onClick={() => setOpen(!open)} type="button" aria-haspopup="listbox" aria-expanded={open}>
                <Icon size={14} />
                <span>{current?.label ?? String(value)}</span>
                <ChevronDown size={13} className={open ? "flip" : ""} />
            </button>
            {open && (
                <ul className="canvas-picker-pop" role="listbox">
                    {options.map((o) => (
                        <li key={String(o.value)} role="option" aria-selected={o.value === value}
                            onClick={() => { onChange(o.value); setOpen(false); }}>
                            {o.label}
                            {o.value === value && <Check size={13} />}
                        </li>
                    ))}
                </ul>
            )}
        </div>
    );
}

function Brand({ subtitle }: { subtitle: string }) {
    return (
        <div className="brand-lockup canvas-brand">
            <span className="brand-mark">
                <img src={`${import.meta.env.BASE_URL}logo.png`} alt="Designer Studio" className="brand-logo-img" />
            </span>
            <div>
                <strong>Designer Studio</strong>
                <small>{subtitle}</small>
            </div>
        </div>
    );
}

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

/** Export popover: the .fig layout choice applies to the .fig and to the design.fig inside the zip. */
function ExportMenu({ screen, state }: { screen?: Screen; state: string }) {
    const [open, setOpen] = useState(false);
    const [layout, setLayout] = useState<FigLayout>(readLayout);
    const box = useRef<HTMLDivElement>(null);

    useEffect(() => {
        if (!open) return;
        const close = (event: MouseEvent | KeyboardEvent) => {
            if (event instanceof KeyboardEvent ? event.key === "Escape" : !box.current?.contains(event.target as Node)) {
                setOpen(false);
            }
        };
        document.addEventListener("mousedown", close);
        document.addEventListener("keydown", close);
        return () => {
            document.removeEventListener("mousedown", close);
            document.removeEventListener("keydown", close);
        };
    }, [open]);

    const choose = (value: FigLayout) => {
        setLayout(value);
        try {
            localStorage.setItem(LAYOUT_KEY, value);
        } catch {
            /* preference only */
        }
    };

    return (
        <div className="export-menu" ref={box}>
            <button className="canvas-export" onClick={() => setOpen(!open)} type="button" aria-expanded={open} aria-haspopup="menu">
                <Download size={15} /> Xuất <ChevronDown size={14} className={open ? "flip" : ""} />
            </button>
            {open && (
                <div className="export-pop" role="menu">
                    <p className="export-label">Bố cục file Figma</p>
                    <div className="export-layouts" role="radiogroup" aria-label="Bố cục file Figma">
                        {FIG_LAYOUTS.map((l) => (
                            <button
                                key={l.id}
                                className={layout === l.id ? "active" : ""}
                                onClick={() => choose(l.id)}
                                role="radio"
                                aria-checked={layout === l.id}
                                type="button"
                            >
                                <l.icon size={18} />
                                <span>
                                    <strong>{l.label}</strong>
                                    <small>{l.hint}</small>
                                </span>
                                {layout === l.id && <Check size={14} className="export-check" />}
                            </button>
                        ))}
                    </div>
                    <div className="export-items">
                        <a className="export-item primary" href={api.exportUrl(SESSION, "fig", layout)} onClick={() => setOpen(false)}>
                            <Download size={16} />
                            <span>
                                <strong>File Figma (.fig)</strong>
                                <small>Kéo thả vào Figma để chỉnh sửa</small>
                            </span>
                        </a>
                        <a className="export-item" href={api.exportUrl(SESSION, "zip", layout)} onClick={() => setOpen(false)}>
                            <FileArchive size={16} />
                            <span>
                                <strong>HTML + PNG (.zip)</strong>
                                <small>Prototype offline, ảnh từng màn và trạng thái</small>
                            </span>
                        </a>
                        {screen && (
                            <a
                                className="export-item"
                                href={api.screenshotUrl(SESSION, screen.id, state)}
                                target="_blank"
                                rel="noreferrer"
                                onClick={() => setOpen(false)}
                            >
                                <Image size={16} />
                                <span>
                                    <strong>PNG màn này</strong>
                                    <small>
                                        {screen.name}
                                        {state ? ` · ${state}` : ""}
                                    </small>
                                </span>
                            </a>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}

/** Horizontal all-frames overview — one iframe per screen, scrollable. */
function MultiView({ screens, onSelect }: { screens: Screen[]; onSelect: (id: string) => void }) {
    const [docs, setDocs] = useState<Record<string, string>>({});

    useEffect(() => {
        screens.forEach((s) => {
            if (docs[s.id]) return;
            api.screenDocument(SESSION, s.id).then((d) => setDocs((prev) => ({ ...prev, [s.id]: d }))).catch(() => undefined);
        });
    }, [screens]);

    return (
        <div className="canvas-multi">
            {screens.map((s) => {
                const p = PLATFORMS[s.platform] ?? PLATFORMS.desktop;
                const scale = Math.min(1, 320 / (s.width ?? 1440));
                const h = 600;
                return (
                    <div key={s.id} className="canvas-multi-frame" onClick={() => onSelect(s.id)}>
                        <div className="canvas-multi-viewport" style={{ width: (s.width ?? 1440) * scale, height: h * scale }}>
                            {docs[s.id]
                                ? <iframe title={s.name} sandbox="allow-scripts allow-forms" srcDoc={docs[s.id]}
                                    style={{ width: s.width ?? 1440, height: h, transform: `scale(${scale})`, pointerEvents: "none" }} />
                                : <div className="canvas-multi-loading" />}
                        </div>
                        <div className="canvas-multi-label">
                            <p.icon size={13} />
                            <strong>{s.name}</strong>
                            <small>v{s.version}</small>
                        </div>
                    </div>
                );
            })}
        </div>
    );
}

function ScreensCanvas() {
    const [screens, setScreens] = useState<Screen[]>([]);
    const [current, setCurrent] = useState(params.get("screen") || "");
    const [doc, setDoc] = useState("");
    const [states, setStates] = useState<string[]>([]);
    const [state, setState] = useState("");
    const [selecting, setSelecting] = useState(false);
    const [codeOpen, setCodeOpen] = useState(false);
    const [code, setCode] = useState("");
    const [versions, setVersions] = useState<ScreenVersion[]>([]);
    const [version, setVersion] = useState<number>();
    const [toast, setToast] = useState("");
    const [viewMode, setViewMode] = useState<"single" | "multi">("single");
    const frameRef = useRef<HTMLIFrameElement>(null);
    const channel = useMemo(
        () => (typeof BroadcastChannel !== "undefined" ? new BroadcastChannel(`designer-canvas-${SESSION}`) : null),
        [],
    );

    const screen = screens.find((s) => s.id === current) ?? screens[0];
    const width = screen?.width ?? 1440;

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
                <div className="canvas-empty">
                    <Brand subtitle="Trang thiết kế" />
                    <p>Chưa có màn hình nào. Agent sẽ dựng màn hình sau khi bạn duyệt spec; trang này tự cập nhật.</p>
                </div>
            </div>
        );
    }

    const platform = PLATFORMS[screen?.platform ?? ""] ?? PLATFORMS.desktop;

    return (
        <div className="canvas-shell">
            <aside className="canvas-rail">
                <Brand subtitle="Trang thiết kế" />
                <div className="canvas-rail-label">
                    <span>Màn hình</span>
                    <span className="canvas-count">{screens.length}</span>
                    <button
                        className={`canvas-icon canvas-view-toggle ${viewMode === "multi" ? "active" : ""}`}
                        onClick={() => setViewMode((m) => m === "single" ? "multi" : "single")}
                        title={viewMode === "single" ? "Xem tất cả frames ngang" : "Xem từng màn"}
                        type="button"
                    >
                        {viewMode === "single" ? <Columns2 size={15} /> : <Square size={15} />}
                    </button>
                </div>
                <nav className="canvas-screens" aria-label="Màn hình">
                    {screens.map((s) => {
                        const p = PLATFORMS[s.platform] ?? PLATFORMS.desktop;
                        return (
                            <button
                                key={s.id}
                                className={`canvas-screen ${s.id === screen?.id ? "active" : ""}`}
                                onClick={() => setCurrent(s.id)}
                                aria-current={s.id === screen?.id ? "page" : undefined}
                                type="button"
                            >
                                <span className="canvas-screen-icon">
                                    <p.icon size={16} />
                                </span>
                                <span className="canvas-screen-text">
                                    <strong>{s.name}</strong>
                                    <small>
                                        {p.label} · v{s.version}
                                    </small>
                                </span>
                            </button>
                        );
                    })}
                </nav>
            </aside>

            <main className="canvas-main">
                <header className="canvas-toolbar">
                    <div className="canvas-title">
                        {viewMode === "multi"
                            ? <><h2>Tất cả màn hình</h2><span className="canvas-chip"><Columns2 size={13} /> {screens.length} frames</span></>
                            : <><h2>{screen?.name}</h2><span className="canvas-chip"><platform.icon size={13} /> {platform.label} · {width}px</span></>
                        }
                    </div>
                    <div className="canvas-tools">
                        {viewMode === "single" && <>
                            {states.length > 0 && (
                                <CanvasPicker
                                    icon={Layers}
                                    title="Trạng thái của màn hình"
                                    value={state}
                                    options={[{ value: "", label: "Mặc định" }, ...states.map((s) => ({ value: s, label: s }))]}
                                    onChange={setState}
                                />
                            )}
                            <CanvasPicker
                                icon={History}
                                title="Lịch sử phiên bản"
                                value={version ?? ""}
                                options={[
                                    { value: "", label: `v${screen?.version} · mới nhất` },
                                    ...versions.slice(1).map((v) => ({ value: v.version, label: `v${v.version} · ${v.note || v.updated_by || ""}` })),
                                ]}
                                onChange={(v) => setVersion(v ? Number(v) : undefined)}
                            />
                            <span className="canvas-divider" aria-hidden />
                            <button
                                className={`canvas-tool ${selecting ? "active" : ""}`}
                                onClick={() => setSelecting(!selecting)}
                                type="button"
                                title="Chọn một phần tử để góp ý ở khung chat"
                            >
                                <MousePointerClick size={15} /> Chọn phần tử
                            </button>
                            <button
                                className={`canvas-tool ${codeOpen ? "active" : ""}`}
                                onClick={() => setCodeOpen(!codeOpen)}
                                type="button"
                                title="Sửa HTML của màn hình"
                            >
                                <Code2 size={15} /> Code
                            </button>
                        </>}
                        <ExportMenu screen={screen} state={state} />
                    </div>
                </header>
                <div className={`canvas-body ${codeOpen && viewMode === "single" ? "with-code" : ""}`}>
                    {viewMode === "multi"
                        ? <MultiView screens={screens} onSelect={(id) => { setCurrent(id); setViewMode("single"); }} />
                        : doc && <Frame doc={doc} width={width} onMessage={onMessage} frameRef={frameRef} />
                    }
                    {codeOpen && (
                        <section className="canvas-code" aria-label="HTML của màn hình">
                            <header>
                                <span>
                                    <Code2 size={15} /> HTML · v{version ?? screen?.version}
                                </span>
                                <button className="canvas-icon" onClick={() => setCodeOpen(false)} type="button" title="Đóng">
                                    <X size={16} />
                                </button>
                            </header>
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
