import { useEffect, useMemo, useRef, useState } from "react";
import { Activity, AlertCircle, Check, ChevronDown, Circle, Clock3, Copy, FileText, Layers, Pause, Play, Search, Trash2, Zap } from "lucide-react";
import { api } from "./api";
import { openRunStream } from "./events";
import type { Run, Session, WorkflowEvent } from "./types";

const DEBUG_TYPES = new Set([
    "debug.step.started", "debug.step.completed", "debug.step.failed",
    "debug.function.started", "debug.function.completed", "debug.function.failed", "debug.decision",
]);
const label = (event: WorkflowEvent) => String(event.payload.function ?? event.type);
const preview = (event: WorkflowEvent) => {
    const payload = event.payload;
    if (event.type === "debug.step.started") return `Started · ${String(payload.phase ?? "Designer")}`;
    if (event.type === "debug.step.completed") return `Completed · ${String(payload.phase ?? "Designer")}`;
    if (event.type === "debug.step.failed") return String((payload.error as { message?: string } | undefined)?.message ?? "Step failed");
    if (event.type === "debug.function.started") return `Called · ${String(payload.phase ?? "Designer")}`;
    if (event.type === "debug.function.completed") return `Returned · ${String(payload.duration_ms ?? "?")} ms`;
    if (event.type === "debug.function.failed") return String((payload.error as { message?: string } | undefined)?.message ?? "Function failed");
    if (event.type === "debug.decision") return `${String(payload.condition ?? "Condition")} → ${String(payload.chosen ?? "")}`;
    if (event.type === "stage.changed") return `${String(payload.stage ?? "")} · ${String(payload.status ?? "")}`;
    return JSON.stringify(payload).slice(0, 180);
};
const severity = (event: WorkflowEvent) => event.type.endsWith("failed") || event.type === "run.failed" || event.type === "action.required" ? "ERROR" : DEBUG_TYPES.has(event.type) ? "DEBUG" : "INFO";
const readable = (value: unknown) => JSON.stringify(value ?? {}, null, 2);

export default function LogsApp() {
    const [sessions, setSessions] = useState<Session[]>([]);
    const [sessionId, setSessionId] = useState("");
    const [runs, setRuns] = useState<Run[]>([]);
    const [runId, setRunId] = useState("");
    const [events, setEvents] = useState<WorkflowEvent[]>([]);
    const [selectedId, setSelectedId] = useState("");
    const [query, setQuery] = useState("");
    const [level, setLevel] = useState("ALL");
    const [paused, setPaused] = useState(false);
    const [autoscroll, setAutoscroll] = useState(true);
    const [notice, setNotice] = useState("");
    const listRef = useRef<HTMLDivElement>(null);

    useEffect(() => { api.listSessions().then((items) => { setSessions(items); const wanted = new URLSearchParams(location.search).get("session"); const first = items.find((item) => item.id === wanted) ?? items[0]; if (first) setSessionId(first.id); }).catch((error) => setNotice(error.message)); }, []);
    useEffect(() => { if (!sessionId) return; api.listRuns(sessionId).then((items) => { setRuns(items); const wanted = new URLSearchParams(location.search).get("run"); setRunId(items.find((item) => item.id === wanted)?.id ?? items[0]?.id ?? ""); }).catch((error) => setNotice(error.message)); }, [sessionId]);
    useEffect(() => { if (!runId) { setEvents([]); return; } let alive = true; api.eventHistory(runId).then((items) => { if (alive) { setEvents(items); setSelectedId(items.at(-1)?.id ?? ""); } }).catch((error) => setNotice(error.message)); return () => { alive = false; }; }, [runId]);
    useEffect(() => { if (!runId || paused) return; const stream = openRunStream(runId, (event) => setEvents((items) => items.some((item) => item.id === event.id) ? items : [...items, event])); return () => stream.close(); }, [runId, paused]);
    useEffect(() => { if (autoscroll && listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight; }, [events, autoscroll]);

    const filtered = useMemo(() => events.filter((event) => {
        const text = `${label(event)} ${event.type} ${preview(event)} ${JSON.stringify(event.payload)}`.toLowerCase();
        return text.includes(query.toLowerCase()) && (level === "ALL" || severity(event) === level);
    }), [events, query, level]);
    const selected = events.find((event) => event.id === selectedId) ?? filtered.at(-1);
    const errors = events.filter((event) => severity(event) === "ERROR").length;
    const steps = events.filter((event) => event.type === "debug.step.started" || event.type === "debug.function.started").length;
    const duration = runs.find((run) => run.id === runId);
    const firstEvent = events[0];
    const lastEvent = events.at(-1);
    const elapsed = firstEvent && lastEvent
        ? Math.max(0, (Date.parse(lastEvent.time) - Date.parse(firstEvent.time)) / 1000)
        : duration ? Math.max(0, (Date.parse(duration.updated_at) - Date.parse(duration.created_at)) / 1000) : 0;

    return <main className="logs-page">
        <aside className="logs-sidebar"><div className="logs-brand"><span className="brand-mark"><Layers size={19} /></span><b>Unified PM</b></div><nav><a href="./"><FileText size={17}/>Designer</a><a href="./"><Activity size={17}/>Runs</a><a className="active"><Zap size={17}/>Logs</a></nav><div className="sidebar-foot"><span className="live-dot"/>Local debug stream</div></aside>
        <section className="logs-main">
            <header className="logs-header"><div><div className="title-line"><h1>Designer Logs</h1><span className="live-badge"><i/>LIVE</span></div><p>Inspect each step of a local Designer run.</p></div><div className="header-actions"><button onClick={() => setPaused(!paused)}>{paused ? <Play size={15}/> : <Pause size={15}/>} {paused ? "Resume" : "Pause stream"}</button><button onClick={() => { setEvents([]); setSelectedId(""); }}><Trash2 size={15}/>Clear view</button></div></header>
            <div className="log-filters"><label className="select-wrap"><span>Run</span><select value={runId} onChange={(event) => setRunId(event.target.value)}>{runs.length === 0 && <option value="">No runs yet</option>}{runs.map((run) => <option key={run.id} value={run.id}>{run.id.slice(0, 8)} · {new Date(run.created_at).toLocaleString()} · {run.status}</option>)}</select><ChevronDown size={15}/></label><label className="search-wrap"><Search size={17}/><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search events, functions, output…"/></label><label className="level-wrap">Severity<select value={level} onChange={(event) => setLevel(event.target.value)}><option value="ALL">All levels</option><option value="INFO">Info</option><option value="DEBUG">Debug</option><option value="ERROR">Error</option></select></label><button className={`auto-toggle ${autoscroll ? "on" : ""}`} onClick={() => setAutoscroll(!autoscroll)}>Autoscroll <span/></button></div>
        <div className="summary-cards"><div className="summary teal"><Layers/><div><b>{events.length}</b><span>Events</span></div></div><div className="summary violet"><Activity/><div><b>{steps}</b><span>Function calls</span></div></div><div className="summary teal"><Clock3/><div><b>{elapsed.toFixed(1)}s</b><span>Duration</span></div></div><div className="summary violet"><AlertCircle/><div><b>{errors}</b><span>Errors</span></div></div></div>
            {notice && <div className="logs-notice">{notice}</div>}
            <div className="log-panels"><section className="event-panel"><div className="panel-heading"><b>Events ({filtered.length})</b><span>Chronological · newest first</span></div><div className="event-list" ref={listRef}>{filtered.slice().reverse().map((event) => <button key={event.id} className={`event-row ${selected?.id === event.id ? "selected" : ""}`} onClick={() => setSelectedId(event.id)}><span className={`event-icon ${severity(event).toLowerCase()}`}>{event.type.endsWith("started") ? <Play size={12}/> : event.type.endsWith("completed") ? <Check size={13}/> : event.type.endsWith("failed") ? <AlertCircle size={13}/> : <Circle size={9}/>}</span><time>{new Date(event.time).toLocaleTimeString([], { hour12: false })}.{String(new Date(event.time).getMilliseconds()).padStart(3,"0")}</time><span className={`level-pill ${severity(event).toLowerCase()}`}>{severity(event)}</span><span className="event-copy"><b>{label(event)}</b><small>{preview(event)}</small></span></button>)}{filtered.length === 0 && <div className="empty-logs">{events.length ? "No events match these filters." : "No events yet. Start a Designer run to see its steps here."}</div>}</div></section>
                <section className="detail-panel">{selected ? <><div className="detail-title"><span className="detail-icon"><Activity size={20}/></span><div><h2>{label(selected)}</h2><code>{selected.type}</code></div><span className="step-tag">{String(selected.payload.phase ?? "WORKFLOW")}</span></div><div className="detail-tabs"><span className="tab-active">Details</span><span>Event #{selected.sequence}</span><span>{new Date(selected.time).toLocaleString()}</span></div><div className="detail-meta"><div><small>Timestamp</small><b>{new Date(selected.time).toLocaleTimeString([], { hour12: false })}</b></div><div><small>Severity</small><b className={`level-pill ${severity(selected).toLowerCase()}`}>{severity(selected)}</b></div><div><small>Run ID</small><code>{selected.run_id}</code></div><div><small>Revision</small><code>{selected.revision}</code></div></div>
                    {("input" in selected.payload) && <JsonBlock title="Input" value={selected.payload.input}/>}{("output" in selected.payload) && <JsonBlock title="Output" value={selected.payload.output}/>}{("error" in selected.payload) && <JsonBlock title="Error" value={selected.payload.error}/>}{!(("input" in selected.payload) || ("output" in selected.payload) || ("error" in selected.payload)) && <JsonBlock title="Event payload" value={selected.payload}/>}</> : <div className="empty-logs">Select an event to inspect its input, output, or details.</div>}</section>
            </div>
            <footer className="logs-footer"><span><i className={paused ? "paused-dot" : ""}/>{paused ? "Stream paused" : "Listening for live events"}</span><span>Event data is stored with each run.</span></footer>
        </section>
    </main>;
}

function JsonBlock({ title, value }: { title: string; value: unknown }) {
    const [copied, setCopied] = useState(false);
    const json = readable(value);
    return <section className="json-block"><header><span><ChevronDown size={14}/><b>{title}</b><small>JSON</small></span><button title="Copy JSON" onClick={() => { void navigator.clipboard.writeText(json).then(() => { setCopied(true); window.setTimeout(() => setCopied(false), 1200); }); }}>{copied ? <Check size={15}/> : <Copy size={15}/>}</button></header><pre>{json}</pre></section>;
}
