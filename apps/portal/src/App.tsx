import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Boxes,
  Download,
  FileJson,
  FolderKanban,
  Layers,
  LogOut,
  MessagesSquare,
  PenTool,
  Plus,
  Search,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  ApiError,
  type Artifact,
  type BaFeature,
  type DesignerSession,
  type MockUser,
  type ProjectDetail,
  type ProjectSummary,
  type User,
  type WikiList,
  api,
  canWrite,
  moduleUrl,
} from "./api";

// ── Helpers ──────────────────────────────────────────────────────────────

function usePath(): [string, (to: string) => void] {
  const [path, setPath] = useState(window.location.pathname + window.location.search);
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname + window.location.search);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);
  const navigate = useCallback((to: string) => {
    window.history.pushState({}, "", to);
    setPath(to);
    window.scrollTo(0, 0);
  }, []);
  return [path, navigate];
}

function safeNext(raw: string | null): string {
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";
}

function initials(name: string): string {
  const parts = name.replace(/\(.*\)/, "").trim().split(/\s+/);
  return ((parts[0]?.[0] ?? "?") + (parts[1]?.[0] ?? "")).toUpperCase();
}

/** Stable hue per project id, for the card accent. */
function hue(seed: string): number {
  let h = 0;
  for (const c of seed) h = (h * 31 + c.charCodeAt(0)) % 360;
  return h;
}

function timeAgo(iso: string): string {
  const minutes = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  if (Number.isNaN(minutes)) return "";
  if (minutes < 1) return "vừa xong";
  if (minutes < 60) return `${minutes} phút trước`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours} giờ trước`;
  const days = Math.round(hours / 24);
  return days < 30 ? `${days} ngày trước` : new Date(iso).toLocaleDateString();
}

function greeting(): string {
  const h = new Date().getHours();
  return h < 11 ? "Chào buổi sáng" : h < 14 ? "Chào buổi trưa" : h < 18 ? "Chào buổi chiều" : "Chào buổi tối";
}

function Avatar({ name, size = 32 }: { name: string; size?: number }) {
  return (
    <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.36, ["--h" as string]: hue(name) }}>
      {initials(name)}
    </span>
  );
}

function RoleChips({ roles }: { roles: string[] }) {
  return (
    <span className="chips">
      {roles.map((r) => (
        <span key={r} className={`chip chip-${r.toLowerCase()}`}>
          {r}
        </span>
      ))}
    </span>
  );
}

// ── App ──────────────────────────────────────────────────────────────────

export function App() {
  const [path, navigate] = usePath();
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null));
  }, []);

  const pathname = path.split("?")[0];
  const params = new URLSearchParams(path.split("?")[1] ?? "");

  if (user === undefined) return <div className="boot"><span className="spinner" /></div>;

  if (!user || pathname === "/login") {
    return (
      <LoginPage
        onLoggedIn={(u) => {
          setUser(u);
          const next = safeNext(params.get("next"));
          if (next.startsWith("/ba/") || next.startsWith("/designer/")) window.location.assign(next);
          else navigate(next === "/login" ? "/" : next);
        }}
      />
    );
  }

  const logout = async () => {
    await api.logout().catch(() => undefined);
    setUser(null);
    navigate("/login");
  };

  const projectMatch = pathname.match(/^\/projects\/([^/]+)$/);
  return (
    <div className="shell">
      <TopBar user={user} onLogout={logout} onHome={() => navigate("/")} />
      <main className="main">
        {projectMatch ? (
          <ProjectPage projectId={decodeURIComponent(projectMatch[1])} me={user} onBack={() => navigate("/")} />
        ) : (
          <HomePage me={user} onOpenDetail={(id) => navigate(`/projects/${encodeURIComponent(id)}`)} />
        )}
      </main>
    </div>
  );
}

function Brand() {
  return (
    <span className="brand">
      <span className="brand-mark" aria-hidden="true">
        UW
      </span>
      <span className="brand-text">
        Unified Work <span className="brand-sub">AI Platform</span>
      </span>
    </span>
  );
}

function TopBar({ user, onLogout, onHome }: { user: User; onLogout: () => void; onHome: () => void }) {
  return (
    <header className="topbar">
      <button className="topbar-home" onClick={onHome} aria-label="Trang chủ">
        <Brand />
      </button>
      <div className="topbar-user">
        <RoleChips roles={user.roles} />
        <div className="user-pill">
          <Avatar name={user.name} size={28} />
          <span className="user-name">{user.name}</span>
        </div>
        <button className="icon-btn" onClick={onLogout} title="Đăng xuất" aria-label="Đăng xuất">
          <LogOut size={16} />
        </button>
      </div>
    </header>
  );
}

// ── Login ────────────────────────────────────────────────────────────────

function LoginPage({ onLoggedIn }: { onLoggedIn: (u: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [demo, setDemo] = useState<MockUser[]>([]);

  useEffect(() => {
    api.mockUsers().then(setDemo).catch(() => setDemo([]));
  }, []);

  const signIn = async (u: string, p: string) => {
    setBusy(u);
    setError("");
    try {
      const { user } = await api.login(u, p);
      onLoggedIn(user);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Không đăng nhập được");
    } finally {
      setBusy(null);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void signIn(username, password);
  };

  return (
    <div className="login">
      <div className="login-card">
        <Brand />
        <h2>Đăng nhập</h2>
        <p className="muted">Không gian làm việc chung cho phân tích nghiệp vụ và thiết kế.</p>
        <form onSubmit={submit} className="form">
          <label>
            Tài khoản
            <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" autoFocus />
          </label>
          <label>
            Mật khẩu
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
            />
          </label>
          {error && <div className="alert">{error}</div>}
          <button className="btn primary block" disabled={!!busy || !username || !password}>
            {busy === username ? <span className="spinner sm" /> : "Đăng nhập"}
          </button>
        </form>

        {demo.length > 0 && (
          <div className="demo">
            <div className="demo-title">Tài khoản demo · mật khẩu {demo[0].password}</div>
            <div className="demo-list">
              {demo.map((d) => (
                <button
                  key={d.username}
                  className="demo-user"
                  disabled={!!busy}
                  onClick={() => void signIn(d.username, d.password)}
                >
                  <Avatar name={d.name} size={28} />
                  <span className="demo-info">
                    <strong>{d.name.replace(/\s*\(.*\)/, "")}</strong>
                    <span className="mono">{d.username}</span>
                  </span>
                  {busy === d.username ? <span className="spinner sm" /> : <RoleChips roles={d.roles} />}
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
      <p className="login-foot muted small">Unified Work AI Platform · đăng nhập giả lập (Keycloak sẽ thay thế)</p>
    </div>
  );
}

// ── Home: my projects ────────────────────────────────────────────────────

function openProject(p: ProjectSummary, onOpenDetail: (id: string) => void) {
  const ba = canWrite(p.my_roles, "BA");
  const designer = canWrite(p.my_roles, "DESIGNER");
  if (ba && !designer) window.location.assign(moduleUrl("ba", p.id));
  else if (designer && !ba) window.location.assign(moduleUrl("designer", p.id));
  else onOpenDetail(p.id);
}

function HomePage({ me, onOpenDetail }: { me: User; onOpenDetail: (id: string) => void }) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [query, setQuery] = useState("");

  const load = useCallback(() => {
    api.projects().then(setProjects).catch((e) => setError(String(e.message ?? e)));
  }, []);
  useEffect(load, [load]);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (projects ?? []).filter(
      (p) => !q || p.name.toLowerCase().includes(q) || p.id.toLowerCase().includes(q) || p.description.toLowerCase().includes(q),
    );
  }, [projects, query]);

  const roleHint = me.roles.includes("BA") && me.roles.includes("DESIGNER")
    ? "Chọn dự án để mở BA hoặc Designer."
    : me.roles.includes("BA")
      ? "Bấm vào dự án để vào không gian BA."
      : "Bấm vào dự án để vào không gian Designer.";

  return (
    <section>
      <div className="hero">
        <div>
          <h1>Dự án của tôi</h1>
          <p className="muted">
            {greeting()}, {me.name.replace(/\s*\(.*\)/, "")}. {roleHint}
          </p>
        </div>
        <div className="hero-stats">
          <div className="stat">
            <strong>{projects?.length ?? "–"}</strong>
            <span>dự án</span>
          </div>
          <div className="stat">
            <strong>{me.roles.length}</strong>
            <span>vai trò</span>
          </div>
        </div>
      </div>

      <div className="toolbar">
        <label className="search">
          <Search size={16} />
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Tìm dự án…" />
        </label>
        <button className="btn primary" onClick={() => setCreating(true)}>
          <Plus size={16} /> Dự án mới
        </button>
      </div>

      {creating && (
        <CreateProjectDialog
          onClose={() => setCreating(false)}
          onCreated={() => {
            setCreating(false);
            load();
          }}
        />
      )}

      {error && <div className="alert">{error}</div>}
      {projects === null ? (
        <div className="grid">
          {[0, 1, 2].map((i) => (
            <div key={i} className="card project skeleton" />
          ))}
        </div>
      ) : visible.length === 0 ? (
        <div className="empty">
          <FolderKanban size={28} />
          <p>{projects.length === 0 ? "Bạn chưa thuộc dự án nào." : "Không có dự án khớp tìm kiếm."}</p>
        </div>
      ) : (
        <div className="grid">
          {visible.map((p) => (
            <ProjectCard key={p.id} project={p} onOpen={() => openProject(p, onOpenDetail)} onDetail={() => onOpenDetail(p.id)} />
          ))}
        </div>
      )}
    </section>
  );
}

function ProjectCard({ project: p, onOpen, onDetail }: { project: ProjectSummary; onOpen: () => void; onDetail: () => void }) {
  const ba = canWrite(p.my_roles, "BA");
  const designer = canWrite(p.my_roles, "DESIGNER");
  return (
    <article className="card project" style={{ ["--h" as string]: hue(p.id) }} onClick={onOpen}>
      <div className="project-head">
        <span className="project-mark">{p.name.slice(0, 1).toUpperCase()}</span>
        <RoleChips roles={p.my_roles} />
      </div>
      <h2>{p.name}</h2>
      <p className="muted desc">{p.description || "Chưa có mô tả."}</p>
      <div className="project-foot">
        <span className="meta">
          <Users size={13} /> {p.member_count}
        </span>
        <span className="meta mono">{p.id}</span>
        <span className="spacer" />
        {ba && designer ? (
          <span className="quick" onClick={(e) => e.stopPropagation()}>
            <a href={moduleUrl("ba", p.id)} className="quick-btn ba" title="Mở BA">
              <MessagesSquare size={14} /> BA
            </a>
            <a href={moduleUrl("designer", p.id)} className="quick-btn designer" title="Mở Designer">
              <PenTool size={14} /> Design
            </a>
          </span>
        ) : (
          <button
            className="link"
            onClick={(e) => {
              e.stopPropagation();
              onDetail();
            }}
          >
            Chi tiết <ArrowRight size={13} />
          </button>
        )}
      </div>
    </article>
  );
}

function CreateProjectDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    try {
      await api.createProject(name, description);
      onCreated();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Không tạo được dự án");
      setBusy(false);
    }
  };

  return (
    <Modal title="Dự án mới" onClose={onClose}>
      <form className="form" onSubmit={create}>
        <label>
          Tên dự án
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} autoFocus />
        </label>
        <label>
          Mô tả
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} rows={3} />
        </label>
        {error && <div className="alert">{error}</div>}
        <p className="muted small">Bạn sẽ là quản trị (ADMIN) của dự án và có thể mời thành viên sau.</p>
        <div className="dialog-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Huỷ
          </button>
          <button className="btn primary" disabled={!name.trim() || busy}>
            Tạo dự án
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Modal({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="dialog" role="dialog" aria-label={title}>
        <div className="dialog-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Đóng">
            <X size={16} />
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ── Project page ─────────────────────────────────────────────────────────

type Tab = "assets" | "workspace" | "members";

function ProjectPage({ projectId, me, onBack }: { projectId: string; me: User; onBack: () => void }) {
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("assets");

  const load = useCallback(() => {
    api.project(projectId).then(setProject).catch((e) => setError(String(e.message ?? e)));
  }, [projectId]);
  useEffect(load, [load]);

  if (error)
    return (
      <div className="empty">
        <p>{error}</p>
        <button className="btn" onClick={onBack}>
          Về danh sách dự án
        </button>
      </div>
    );
  if (!project) return <div className="boot inline"><span className="spinner" /></div>;

  const ba = canWrite(project.my_roles, "BA");
  const designer = canWrite(project.my_roles, "DESIGNER");

  return (
    <section>
      <button className="back" onClick={onBack}>
        <ArrowLeft size={15} /> Dự án của tôi
      </button>
      <div className="project-hero" style={{ ["--h" as string]: hue(project.id) }}>
        <span className="project-mark lg">{project.name.slice(0, 1).toUpperCase()}</span>
        <div className="project-hero-text">
          <h1>{project.name}</h1>
          <p className="muted">{project.description || "Chưa có mô tả."}</p>
          <div className="project-hero-meta">
            <span className="mono">{project.id}</span>
            <span>
              <Users size={13} /> {project.members.length} thành viên
            </span>
            <RoleChips roles={project.my_roles} />
          </div>
        </div>
      </div>

      <div className="modules">
        <ModuleCard
          kind="ba"
          href={moduleUrl("ba", project.id)}
          title="Business Analysis"
          text="Chat với BA Agent theo từng feature, wiki dự án, validation và BA package."
          icon={<MessagesSquare size={22} />}
          canWrite={ba}
        />
        <ModuleCard
          kind="designer"
          href={moduleUrl("designer", project.id)}
          title="Designer"
          text="Tạo và chỉnh màn hình với Designer Agent trên OpenPencil, trích dẫn file của dự án."
          icon={<PenTool size={22} />}
          canWrite={designer}
        />
      </div>

      <nav className="tabs">
        {([
          ["assets", "Assets"],
          ["workspace", "Data workspace"],
          ["members", "Thành viên"],
        ] as [Tab, string][]).map(([id, label]) => (
          <button key={id} className={tab === id ? "tab active" : "tab"} onClick={() => setTab(id)}>
            {label}
          </button>
        ))}
      </nav>

      {tab === "assets" && <AssetsTab projectId={project.id} />}
      {tab === "workspace" && <WorkspaceTab projectId={project.id} />}
      {tab === "members" && <MembersTab project={project} me={me} onChanged={load} />}
    </section>
  );
}

function ModuleCard(props: { kind: "ba" | "designer"; href: string; title: string; text: string; icon: ReactNode; canWrite: boolean }) {
  return (
    <a className={`card module module-${props.kind}`} href={props.href}>
      <span className="module-icon">{props.icon}</span>
      <div className="module-body">
        <h2>{props.title}</h2>
        <p className="muted">{props.text}</p>
      </div>
      <span className="module-cta">
        {props.canWrite ? "Mở để làm việc" : "Mở chỉ đọc"} <ArrowRight size={14} />
      </span>
    </a>
  );
}

// ── Tabs ─────────────────────────────────────────────────────────────────

const KIND: Record<Artifact["kind"], { label: string; icon: ReactNode; cls: string }> = {
  ba_package: { label: "BA package", icon: <FileJson size={16} />, cls: "ba" },
  designer_output: { label: "Thiết kế", icon: <Layers size={16} />, cls: "designer" },
};

function openArtifactUrl(a: Artifact, projectId: string): string {
  const p = encodeURIComponent(projectId);
  if (a.kind === "ba_package") return `/ba/chat.html?session=${encodeURIComponent(a.source_ref)}&project_id=${p}`;
  return `/designer/?project=${p}&session=${encodeURIComponent(a.meta?.session_id ?? "")}`;
}

function AssetsTab({ projectId }: { projectId: string }) {
  const [items, setItems] = useState<Artifact[] | null>(null);
  const [wiki, setWiki] = useState<WikiList | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    api.artifacts(projectId).then(setItems).catch((e) => setError(String(e.message ?? e)));
    api.wiki(projectId).then(setWiki).catch(() => setWiki(null));
  }, [projectId]);

  if (error) return <div className="alert">{error}</div>;
  return (
    <div className="stack">
      {wiki && (
        <a className="card wiki-card" href={`/ba/wiki.html?project_id=${encodeURIComponent(projectId)}`}>
          <span className="module-icon small wiki">
            <BookOpen size={18} />
          </span>
          <div>
            <strong>Wiki &amp; tri thức</strong>
            <p className="muted small">
              {wiki.project_approved.length} trang đã duyệt · {wiki.project_drafts.length} bản nháp ·{" "}
              {wiki.company_approved.length} trang chung công ty
            </p>
          </div>
          <ArrowRight size={16} className="dim" />
        </a>
      )}
      {items === null ? (
        <div className="card skeleton tall" />
      ) : items.length === 0 ? (
        <div className="empty">
          <Boxes size={28} />
          <p>Chưa có artifact nào. Export BA package hoặc hoàn tất một thiết kế để thấy ở đây.</p>
        </div>
      ) : (
        <div className="card list">
          {items.map((a) => (
            <div key={a.id} className="row">
              <span className={`module-icon small ${KIND[a.kind].cls}`}>{KIND[a.kind].icon}</span>
              <div className="row-main">
                <div className="row-title">
                  {a.title}
                  <span className="pill">v{a.version}</span>
                  {a.version < a.latest_version && <span className="pill dim">mới nhất v{a.latest_version}</span>}
                  {a.stale && <span className="pill warn">Cần xem lại · BA v{a.derived_latest_version}</span>}
                </div>
                <div className="row-meta">
                  {KIND[a.kind].label}
                  {a.derived_title && <> · từ {a.derived_title} v{a.derived_version}</>}
                  {a.created_by && <> · {a.created_by}</>} · {timeAgo(a.created_at)}
                </div>
              </div>
              <div className="row-actions">
                <a className="btn sm ghost" href={openArtifactUrl(a, projectId)}>
                  Mở
                </a>
                {a.storage_key && (
                  <a className="icon-btn" href={`/api/core/artifacts/${encodeURIComponent(a.id)}/download`} title="Tải xuống">
                    <Download size={15} />
                  </a>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function WorkspaceTab({ projectId }: { projectId: string }) {
  const [features, setFeatures] = useState<BaFeature[] | null>(null);
  const [sessions, setSessions] = useState<DesignerSession[] | null>(null);
  useEffect(() => {
    api.baFeatures(projectId).then(setFeatures).catch(() => setFeatures([]));
    api.designerSessions(projectId).then(setSessions).catch(() => setSessions([]));
  }, [projectId]);
  const p = encodeURIComponent(projectId);
  return (
    <div className="modules">
      <SessionList
        kind="ba"
        title="BA sessions"
        icon={<MessagesSquare size={16} />}
        items={features?.map((f) => ({
          id: f.session_id,
          title: f.title,
          meta: f.feature_status,
          href: `/ba/chat.html?session=${encodeURIComponent(f.session_id)}&project_id=${p}`,
        }))}
      />
      <SessionList
        kind="designer"
        title="Designer sessions"
        icon={<PenTool size={16} />}
        items={sessions?.map((s) => ({
          id: s.id,
          title: s.title,
          meta: s.source === "ba-handoff" ? "từ BA handoff" : timeAgo(s.updated_at),
          href: `/designer/?project=${p}&session=${encodeURIComponent(s.id)}`,
        }))}
      />
    </div>
  );
}

function SessionList(props: {
  kind: "ba" | "designer";
  title: string;
  icon: ReactNode;
  items?: { id: string; title: string; meta: string; href: string }[];
}) {
  return (
    <div className={`card sessions sessions-${props.kind}`}>
      <div className="sessions-head">
        <span className={`module-icon small ${props.kind}`}>{props.icon}</span>
        <h2>{props.title}</h2>
        <span className="pill">{props.items?.length ?? "…"}</span>
      </div>
      {props.items === undefined ? (
        <div className="skeleton line" />
      ) : props.items.length === 0 ? (
        <p className="muted small">Chưa có phiên nào.</p>
      ) : (
        <ul>
          {props.items.map((it) => (
            <li key={it.id}>
              <a href={it.href}>
                <span className="session-title">{it.title}</span>
                <span className="session-meta">{it.meta}</span>
              </a>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

const ROLES = ["BA", "DESIGNER", "REVIEWER", "ADMIN"];

function MembersTab({ project, me, onChanged }: { project: ProjectDetail; me: User; onChanged: () => void }) {
  const isAdmin = project.my_roles.includes("ADMIN");
  const [users, setUsers] = useState<User[]>([]);
  const [newUser, setNewUser] = useState("");
  const [newRole, setNewRole] = useState("BA");
  const [error, setError] = useState("");

  useEffect(() => {
    if (isAdmin) api.users().then(setUsers).catch(() => setUsers([]));
  }, [isAdmin]);

  const add = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.addMember(project.id, newUser, newRole);
      setNewUser("");
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Không thêm được thành viên");
    }
  };
  const remove = async (userId: string) => {
    try {
      await api.removeMember(project.id, userId);
      onChanged();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Không xoá được thành viên");
    }
  };

  return (
    <div className="stack">
      {error && <div className="alert">{error}</div>}
      <div className="card list">
        {project.members.map((m) => (
          <div key={m.id} className="row">
            <Avatar name={m.name} size={34} />
            <div className="row-main">
              <div className="row-title">
                {m.name}
                {m.id === me.id && <span className="pill dim">bạn</span>}
              </div>
              <div className="row-meta mono">{m.username}</div>
            </div>
            <RoleChips roles={m.roles} />
            {isAdmin && m.id !== me.id && (
              <button className="icon-btn danger" onClick={() => void remove(m.id)} title="Xoá khỏi dự án">
                <X size={15} />
              </button>
            )}
          </div>
        ))}
      </div>
      {isAdmin && (
        <form className="card invite" onSubmit={add}>
          <UserPlus size={18} className="dim" />
          <select value={newUser} onChange={(e) => setNewUser(e.target.value)} required>
            <option value="">Chọn người dùng…</option>
            {users.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name} ({u.username})
              </option>
            ))}
          </select>
          <select value={newRole} onChange={(e) => setNewRole(e.target.value)}>
            {ROLES.map((r) => (
              <option key={r}>{r}</option>
            ))}
          </select>
          <button className="btn primary" disabled={!newUser}>
            Thêm
          </button>
        </form>
      )}
    </div>
  );
}
