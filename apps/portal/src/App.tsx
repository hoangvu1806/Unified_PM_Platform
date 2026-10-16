import {
  ArrowLeft,
  ArrowRight,
  BookOpen,
  Boxes,
  Check,
  CircleAlert,
  Download,
  FileJson,
  FolderKanban,
  LayoutGrid,
  Layers,
  Lock,
  LogOut,
  MessagesSquare,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  PenTool,
  Plus,
  Search,
  Sun,
  UserPlus,
  Users,
  Workflow,
  X,
} from "lucide-react";
import { FormEvent, Fragment, ReactNode, createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";
import {
  ApiError,
  type Artifact,
  type AuthProviders,
  type BaFeature,
  type DesignerSession,
  type Journey,
  type JourneyStep,
  type MockUser,
  type ProjectDetail,
  type ProjectSummary,
  type User,
  type WikiList,
  api,
} from "./api";
import { toggleTheme, useThemeMode } from "./theme";

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

function plainName(name: string): string {
  return name.replace(/\s*\(.*\)/, "");
}

function Avatar({ name, size = 32 }: { name: string; size?: number }) {
  return (
    <span className="avatar" style={{ width: size, height: size, fontSize: size * 0.38, ["--h" as string]: hue(name) }}>
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

// ── App shell: project rail + page (same layout as the Designer app) ────

type ShellCtx = {
  me: User;
  projects: ProjectSummary[] | null;
  navigate: (to: string) => void;
  createProject: () => void;
  onLogout: () => void;
};

const Shell = createContext<ShellCtx>(null as unknown as ShellCtx);
const RAIL_KEY = "portal.rail.collapsed";

function readRailPref(): boolean {
  try { return localStorage.getItem(RAIL_KEY) === "1"; } catch { return false; }
}

export function App() {
  const [path, navigate] = usePath();
  const [user, setUser] = useState<User | null | undefined>(undefined);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [creating, setCreating] = useState(false);
  const [railPref, setRailPref] = useState(readRailPref);
  const [journeyRailOpen, setJourneyRailOpen] = useState(false);

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null));
  }, []);

  const loadProjects = useCallback(() => {
    api.projects().then(setProjects).catch(() => setProjects([]));
  }, []);
  useEffect(() => {
    if (user) loadProjects();
  }, [user, loadProjects]);

  const pathname = path.split("?")[0];
  const params = new URLSearchParams(path.split("?")[1] ?? "");
  const match = pathname.match(/^\/projects\/([^/]+)(?:\/f\/([^/]+)|\/(designer))?$/);
  const projectId = match ? decodeURIComponent(match[1]) : null;
  const featureId = match?.[2] ? decodeURIComponent(match[2]) : null;
  const designerView = !!match?.[3];

  useEffect(() => setJourneyRailOpen(false), [featureId, designerView]);

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
    setProjects(null);
    navigate("/login");
  };

  // The journey page needs the width for the BA / Designer workspaces: the rail starts collapsed there.
  const wide = !!featureId || designerView;
  const collapsed = wide ? !journeyRailOpen : railPref;
  const toggleRail = () => {
    if (wide) {
      setJourneyRailOpen((open) => !open);
      return;
    }
    const next = !railPref;
    setRailPref(next);
    try { localStorage.setItem(RAIL_KEY, next ? "1" : "0"); } catch { /* private mode */ }
  };

  const ctx: ShellCtx = { me: user, projects, navigate, createProject: () => setCreating(true), onLogout: logout };
  const enc = (id: string) => encodeURIComponent(id);

  return (
    <Shell.Provider value={ctx}>
      <div className={`app-shell ${collapsed ? "rail-collapsed" : ""}`}>
        <Rail collapsed={collapsed} activeProject={projectId} onToggle={toggleRail} />
        <div className="page">
          {projectId && featureId ? (
            <JourneyPage
              key={featureId}
              projectId={projectId}
              featureId={featureId}
              onBack={() => navigate(`/projects/${enc(projectId)}`)}
            />
          ) : projectId && designerView ? (
            <DesignerPage key={projectId} projectId={projectId} />
          ) : projectId ? (
            <ProjectPage
              key={projectId}
              projectId={projectId}
              me={user}
              onBack={() => navigate("/")}
              onOpenFeature={(fid) => navigate(`/projects/${enc(projectId)}/f/${enc(fid)}`)}
            />
          ) : (
            <HomePage me={user} onOpenProject={(id) => navigate(`/projects/${enc(id)}`)} />
          )}
        </div>
      </div>
      {creating && (
        <CreateDialog
          title="Dự án mới"
          note="Bạn là PM của dự án (làm cả BA và Designer) và có quyền quản trị thành viên."
          submitLabel="Tạo dự án"
          onClose={() => setCreating(false)}
          onSubmit={async (name, description) => {
            const created = await api.createProject(name, description);
            setCreating(false);
            loadProjects();
            navigate(`/projects/${enc(created.id)}`);
          }}
        />
      )}
    </Shell.Provider>
  );
}

function BrandMark() {
  return <img className="brand-mark" src="/unified-logo.png" alt="" aria-hidden="true" />;
}

function Brand() {
  return (
    <span className="brand">
      <BrandMark />
      <span className="brand-text">
        <strong>Unified Work</strong>
        <small>AI Platform</small>
      </span>
    </span>
  );
}

function ThemeButton() {
  const mode = useThemeMode();
  return (
    <button className="icon-btn" onClick={toggleTheme} title={mode === "dark" ? "Giao diện sáng" : "Giao diện tối"} aria-label="Đổi giao diện">
      {mode === "dark" ? <Sun size={16} /> : <Moon size={16} />}
    </button>
  );
}

function Rail({ collapsed, activeProject, onToggle }: { collapsed: boolean; activeProject: string | null; onToggle: () => void }) {
  const { projects, navigate, createProject } = useContext(Shell);
  return (
    <aside className={`rail ${collapsed ? "is-collapsed" : ""}`}>
      <button className="rail-brand" onClick={() => navigate("/")} title="Unified Work AI Platform">
        {collapsed ? <BrandMark /> : <Brand />}
      </button>
      <button className="rail-new" onClick={createProject} title="Dự án mới">
        <Plus size={17} />
        {!collapsed && <span>Dự án mới</span>}
      </button>
      {!collapsed && <div className="rail-label">Dự án của tôi {projects ? `(${projects.length})` : ""}</div>}
      <nav className="rail-list" aria-label="Dự án">
        <button className={`rail-row ${activeProject ? "" : "active"}`} onClick={() => navigate("/")} title="Tất cả dự án">
          <span className="rail-icon"><LayoutGrid size={15} /></span>
          {!collapsed && <span className="rail-title">Tất cả dự án</span>}
        </button>
        {projects?.map((p) => (
          <button
            key={p.id}
            className={`rail-row ${p.id === activeProject ? "active" : ""}`}
            onClick={() => navigate(`/projects/${encodeURIComponent(p.id)}`)}
            title={p.name}
          >
            <span className="rail-mark" style={{ ["--h" as string]: hue(p.id) }}>{p.name.slice(0, 1).toUpperCase()}</span>
            {!collapsed && <span className="rail-title">{p.name}</span>}
          </button>
        ))}
      </nav>
      <div className="rail-footer">
        <button onClick={onToggle} title={collapsed ? "Mở thanh bên" : "Thu gọn thanh bên"}>
          {collapsed ? <PanelLeftOpen size={17} /> : <PanelLeftClose size={17} />}
          {!collapsed && <span>Thu gọn</span>}
        </button>
      </div>
    </aside>
  );
}

type Crumb = { label: string; to?: string };

function PageHeader({ crumbs, center, children }: { crumbs: Crumb[]; center?: ReactNode; children?: ReactNode }) {
  const { me, navigate, onLogout } = useContext(Shell);
  return (
    <header className={`topbar ${center ? "has-center" : ""}`}>
      <nav className="crumbs" aria-label="Vị trí">
        {crumbs.map((c, i) => (
          <Fragment key={i}>
            {i > 0 && <span className="crumb-sep">/</span>}
            {c.to ? (
              <button className="crumb" onClick={() => navigate(c.to!)}>
                {i === 0 && crumbs.length > 1 && <ArrowLeft size={14} />}
                {c.label}
              </button>
            ) : (
              <span className="crumb current" title={c.label}>{c.label}</span>
            )}
          </Fragment>
        ))}
      </nav>
      {center}
      <div className="topbar-actions">
        {children}
        <ThemeButton />
        <span className="topbar-divider" />
        <span className="user-chip" title={me.username}>
          <Avatar name={me.name} size={26} />
          <span className="user-name">{me.name}</span>
        </span>
        <button className="icon-btn" onClick={onLogout} title="Đăng xuất" aria-label="Đăng xuất">
          <LogOut size={16} />
        </button>
      </div>
    </header>
  );
}

// ── Login ────────────────────────────────────────────────────────────────

function KeyIcon() {
  return (
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="8" cy="15" r="4" stroke="currentColor" strokeWidth="1.8" />
      <path d="M10.8 12.2 20 3m-3 3 2.5 2.5M14.5 8.5 17 11" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

const LOGIN_POINTS: { icon: ReactNode; title: string; text: string }[] = [
  { icon: <MessagesSquare size={17} />, title: "Phân tích với BA agent", text: "Mục tiêu, quy tắc, quy trình, use case — kiểm tra và bàn giao BA package." },
  { icon: <PenTool size={17} />, title: "Thiết kế với Designer agent", text: "Từ BA package ra màn hình trên OpenPencil, duyệt spec và bản cuối." },
  { icon: <Boxes size={17} />, title: "Một nơi cho mọi tài sản", text: "Wiki, BA package, BPMN, UI spec và file thiết kế có phiên bản." },
];

function LoginPage({ onLoggedIn }: { onLoggedIn: (u: User) => void }) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [demo, setDemo] = useState<MockUser[]>([]);
  const [providers, setProviders] = useState<AuthProviders | null>(null);
  const mode = useThemeMode();

  useEffect(() => {
    api.authProviders().then(setProviders).catch(() => setProviders(null));
    // Quick sign-in shows PM accounts only (BA + Designer in one person).
    api
      .mockUsers()
      .then((users) => setDemo(users.filter((u) => u.roles.includes("PM") || (u.roles.includes("BA") && u.roles.includes("DESIGNER")))))
      .catch(() => setDemo([]));
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

  const keycloak = providers?.keycloak;

  return (
    <div className="login">
      <section className="login-hero" aria-hidden="true">
        <div className="login-glow" />
        <Brand />
        <div className="login-hero-copy">
          <span className="login-kicker">BA × Designer · một hành trình</span>
          <h1>Từ yêu cầu nghiệp vụ đến màn hình, trong cùng một workspace.</h1>
          <ul className="login-points">
            {LOGIN_POINTS.map((p) => (
              <li key={p.title}>
                <span className="login-point-icon">{p.icon}</span>
                <span>
                  <strong>{p.title}</strong>
                  <small>{p.text}</small>
                </span>
              </li>
            ))}
          </ul>
        </div>
        <div className="login-flow">
          {["Định nghĩa", "Quy tắc", "Quy trình", "Use case", "Bàn giao", "Thiết kế", "Duyệt"].map((s, i, all) => (
            <Fragment key={s}>
              <span className={`login-flow-step ${i >= 5 ? "design" : ""}`}>{s}</span>
              {i < all.length - 1 && <span className="login-flow-line" />}
            </Fragment>
          ))}
        </div>
      </section>

      <section className="login-panel">
        <button className="icon-btn login-theme" onClick={toggleTheme} title={mode === "dark" ? "Giao diện sáng" : "Giao diện tối"} aria-label="Đổi giao diện">
          {mode === "dark" ? <Sun size={16} /> : <Moon size={16} />}
        </button>
        <div className="login-card">
          <div className="login-card-brand"><Brand /></div>
          <h2>Đăng nhập</h2>
          <p className="muted">Chào mừng trở lại. Đăng nhập để tiếp tục dự án của bạn.</p>

          <button
            type="button"
            className="btn sso"
            disabled={!keycloak?.enabled}
            onClick={() => keycloak?.login_url && window.location.assign(keycloak.login_url)}
            title={keycloak?.enabled ? "Đăng nhập một lần (SSO) qua Keycloak" : "Keycloak chưa được cấu hình (KEYCLOAK_URL, KEYCLOAK_REALM, KEYCLOAK_CLIENT_ID)"}
          >
            <KeyIcon />
            Đăng nhập với Keycloak
            {!keycloak?.enabled && <span className="sso-soon">Sắp có</span>}
          </button>

          <div className="login-divider"><span>hoặc dùng tài khoản</span></div>

          <form onSubmit={submit} className="form login-form">
            <label>
              Tài khoản
              <input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" placeholder="vd. pm.hoa" autoFocus />
            </label>
            <label>
              Mật khẩu
              <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" placeholder="••••••••" />
            </label>
            {error && <div className="alert">{error}</div>}
            <button className="btn primary block lg" disabled={!!busy || !username || !password}>
              {busy === username ? <span className="spinner sm" /> : <>Đăng nhập <ArrowRight size={16} /></>}
            </button>
          </form>

          {providers?.mock !== false && demo.length > 0 && (
            <div className="login-demo">
              <div className="login-demo-title">Đăng nhập nhanh · mật khẩu {demo[0].password}</div>
              <div className="login-demo-list">
                {demo.map((d) => (
                  <button key={d.username} className="login-demo-user" disabled={!!busy} onClick={() => void signIn(d.username, d.password)}>
                    <Avatar name={d.name} size={30} />
                    <span className="demo-info">
                      <strong>{plainName(d.name)}</strong>
                      <span className="mono">{d.username}</span>
                    </span>
                    {busy === d.username ? <span className="spinner sm" /> : <span className="chip chip-pm">PM</span>}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
        <p className="login-foot">Unified Work AI Platform · PM làm trọn hành trình BA và Thiết kế</p>
      </section>
    </div>
  );
}

// ── Home: projects ───────────────────────────────────────────────────────

function HomePage({ me, onOpenProject }: { me: User; onOpenProject: (id: string) => void }) {
  const { projects, createProject } = useContext(Shell);
  const [query, setQuery] = useState("");

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (projects ?? []).filter(
      (p) => !q || p.name.toLowerCase().includes(q) || p.id.toLowerCase().includes(q) || p.description.toLowerCase().includes(q),
    );
  }, [projects, query]);

  return (
    <>
      <PageHeader crumbs={[{ label: "Dự án của tôi" }]} />
      <main className="page-body">
        <div className="page-inner">
          <div className="hero">
            <h1>Chào {plainName(me.name)}</h1>
            <p className="muted">
              Chọn một dự án để tiếp tục. Trong dự án, mỗi feature đi từ phân tích BA tới thiết kế màn hình theo từng bước.
            </p>
          </div>

          <div className="toolbar">
            <label className="search">
              <Search size={16} />
              <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Tìm dự án…" />
            </label>
            <button className="btn primary" onClick={createProject}>
              <Plus size={16} /> Dự án mới
            </button>
          </div>

          {projects === null ? (
            <div className="grid">{[0, 1, 2].map((i) => <div key={i} className="card project skeleton" />)}</div>
          ) : visible.length === 0 ? (
            <div className="empty">
              <FolderKanban size={28} />
              <p>{projects.length === 0 ? "Bạn chưa thuộc dự án nào. Tạo dự án đầu tiên để bắt đầu." : "Không có dự án khớp tìm kiếm."}</p>
            </div>
          ) : (
            <div className="grid">
              {visible.map((p) => (
                <article key={p.id} className="card project" style={{ ["--h" as string]: hue(p.id) }} onClick={() => onOpenProject(p.id)}>
                  <div className="project-head">
                    <span className="project-mark">{p.name.slice(0, 1).toUpperCase()}</span>
                    <RoleChips roles={p.my_roles} />
                  </div>
                  <h2>{p.name}</h2>
                  <p className="muted desc">{p.description || "Chưa có mô tả."}</p>
                  <div className="project-foot">
                    <span className="meta"><Users size={13} /> {p.member_count} thành viên</span>
                    <span className="spacer" />
                    <span className="link">Mở dự án <ArrowRight size={13} /></span>
                  </div>
                </article>
              ))}
            </div>
          )}
        </div>
      </main>
    </>
  );
}

function CreateDialog(props: {
  title: string;
  note: string;
  submitLabel: string;
  nameLabel?: string;
  onClose: () => void;
  onSubmit: (name: string, description: string) => Promise<void>;
}) {
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError("");
    try {
      await props.onSubmit(name.trim(), description.trim());
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Không tạo được");
      setBusy(false);
    }
  };

  return (
    <Modal title={props.title} onClose={props.onClose}>
      <form className="form" onSubmit={submit}>
        <label>
          {props.nameLabel ?? "Tên"}
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={200} autoFocus />
        </label>
        <label>
          Mô tả
          <textarea value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} rows={3} />
        </label>
        {error && <div className="alert">{error}</div>}
        <p className="muted small">{props.note}</p>
        <div className="dialog-actions">
          <button type="button" className="btn ghost" onClick={props.onClose}>Huỷ</button>
          <button className="btn primary" disabled={!name.trim() || busy}>
            {busy ? <span className="spinner sm" /> : props.submitLabel}
          </button>
        </div>
      </form>
    </Modal>
  );
}

function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className={`dialog ${wide ? "wide" : ""}`} role="dialog" aria-label={title}>
        <div className="dialog-head">
          <h2>{title}</h2>
          <button className="icon-btn" onClick={onClose} aria-label="Đóng"><X size={16} /></button>
        </div>
        {children}
      </div>
    </div>
  );
}

// ── Project page ─────────────────────────────────────────────────────────

type Tab = "features" | "assets" | "workspace" | "members";

function ProjectPage({
  projectId,
  me,
  onBack,
  onOpenFeature,
}: {
  projectId: string;
  me: User;
  onBack: () => void;
  onOpenFeature: (fid: string) => void;
}) {
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState("");
  const [tab, setTab] = useState<Tab>("features");

  const load = useCallback(() => {
    api.project(projectId).then(setProject).catch((e) => setError(String(e.message ?? e)));
  }, [projectId]);
  useEffect(load, [load]);

  const crumbs: Crumb[] = [{ label: "Dự án", to: "/" }, { label: project?.name ?? "…" }];

  return (
    <>
      <PageHeader crumbs={crumbs} />
      <main className="page-body">
        <div className="page-inner">
          {error ? (
            <div className="empty">
              <p>{error}</p>
              <button className="btn" onClick={onBack}>Về danh sách dự án</button>
            </div>
          ) : !project ? (
            <div className="boot inline"><span className="spinner" /></div>
          ) : (
            <>
              <div className="project-hero" style={{ ["--h" as string]: hue(project.id) }}>
                <span className="project-mark lg">{project.name.slice(0, 1).toUpperCase()}</span>
                <div className="project-hero-text">
                  <h1>{project.name}</h1>
                  <p className="muted">{project.description || "Chưa có mô tả."}</p>
                  <div className="project-hero-meta">
                    <RoleChips roles={project.my_roles} />
                    <span><Users size={13} /> {project.members.length} thành viên</span>
                    <span className="mono" title="Mã dự án">{project.id}</span>
                  </div>
                </div>
              </div>

              <nav className="tabs">
                {([
                  ["features", "Features"],
                  ["assets", "Assets"],
                  ["workspace", "Data workspace"],
                  ["members", "Thành viên"],
                ] as [Tab, string][]).map(([id, label]) => (
                  <button key={id} className={tab === id ? "tab active" : "tab"} onClick={() => setTab(id)}>{label}</button>
                ))}
              </nav>

              {tab === "features" && <FeaturesTab project={project} onOpenFeature={onOpenFeature} />}
              {tab === "assets" && <AssetsTab projectId={project.id} />}
              {tab === "workspace" && <WorkspaceTab projectId={project.id} />}
              {tab === "members" && <MembersTab project={project} me={me} onChanged={load} />}
            </>
          )}
        </div>
      </main>
    </>
  );
}

function canWriteAny(roles: string[]): boolean {
  return roles.some((r) => ["PM", "ADMIN", "BA"].includes(r));
}

function canDesign(roles: string[]): boolean {
  return roles.some((r) => ["PM", "ADMIN", "DESIGNER"].includes(r));
}

function FeaturesTab({ project, onOpenFeature }: { project: ProjectDetail; onOpenFeature: (fid: string) => void }) {
  const { navigate } = useContext(Shell);
  const [features, setFeatures] = useState<BaFeature[] | null>(null);
  const [sessions, setSessions] = useState<DesignerSession[] | null>(null);
  const [journeys, setJourneys] = useState<Record<string, Journey>>({});
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .baFeatures(project.id)
      .then((items) => {
        setFeatures(items);
        items.forEach((f) =>
          api.journey(project.id, f.session_id).then((j) => setJourneys((cur) => ({ ...cur, [f.session_id]: j }))).catch(() => undefined),
        );
      })
      .catch((e) => setError(String(e.message ?? e)));
    api.designerSessions(project.id).then(setSessions).catch(() => setSessions([]));
  }, [project.id]);

  const handedOff = (features ?? []).filter((f) => f.feature_status === "EXPORTED").length;
  const inDesign = (sessions ?? []).filter((s) => s.source === "ba-handoff").length;
  const writeBa = canWriteAny(project.my_roles);
  const writeDesign = canDesign(project.my_roles);
  const openDesigner = () => navigate(`/projects/${encodeURIComponent(project.id)}/designer`);

  return (
    <div className="stack">
      <div className="agent-cards">
        <div className="card agent-card">
          <div className="agent-card-head">
            <span className="module-icon ba"><MessagesSquare size={18} /></span>
            <div>
              <strong>BA agent</strong>
              <span className="muted small">Phân tích nghiệp vụ · 4 section, kiểm tra, bàn giao</span>
            </div>
            <span className={`state-pill ${features?.length ? "ok" : ""}`}>
              {features === null ? "…" : features.length ? `${features.length} feature` : "Chưa bắt đầu"}
            </span>
          </div>
          <p className="muted small">
            {features === null
              ? "Đang tải…"
              : features.length === 0
                ? "Bắt đầu bằng một feature mới: BA agent hỏi mục tiêu, tác nhân và phạm vi."
                : `${handedOff} / ${features.length} feature đã bàn giao BA package cho thiết kế.`}
          </p>
          <div className="agent-card-actions">
            {writeBa ? (
              <button className="btn primary sm" onClick={() => setCreating(true)}><Plus size={15} /> Feature mới</button>
            ) : (
              <span className="state-pill">Chỉ xem</span>
            )}
          </div>
        </div>

        <div className={`card agent-card ${handedOff ? "" : "waiting"}`}>
          <div className="agent-card-head">
            <span className="module-icon designer"><PenTool size={18} /></span>
            <div>
              <strong>Designer agent</strong>
              <span className="muted small">Thiết kế màn hình trên OpenPencil từ BA package</span>
            </div>
            <span className={`state-pill ${handedOff ? "ok" : "wait"}`}>
              {features === null ? "…" : handedOff ? `${handedOff} package sẵn sàng` : <><Lock size={11} /> Chờ BA</>}
            </span>
          </div>
          <p className="muted small">
            {features === null
              ? "Đang tải…"
              : handedOff
                ? `${inDesign} phiên thiết kế từ BA${sessions && sessions.length > inDesign ? ` · ${sessions.length - inDesign} phiên khác` : ""}. Mở feature để đi tiếp bước Thiết kế.`
                : "Chưa có BA package nào được bàn giao. Bạn vẫn có thể mở Designer để xem hoặc trao đổi trước; thiết kế từ BA sẽ mở khi BA bàn giao."}
          </p>
          <div className="agent-card-actions">
            <button className={`btn sm ${handedOff ? "" : "ghost"}`} onClick={openDesigner}>
              {writeDesign ? "Mở Designer" : "Xem Designer"} <ArrowRight size={14} />
            </button>
          </div>
        </div>
      </div>

      <div className="section-row">
        <h2 className="section-title">Features</h2>
        <p className="muted small">Mỗi feature là một hành trình 9 bước: BA (1–6) rồi Thiết kế (7–9).</p>
      </div>
      {creating && (
        <CreateDialog
          title="Feature mới"
          nameLabel="Tên feature"
          note="Sau khi tạo, bạn bắt đầu ở bước 1 – Định nghĩa feature, cùng BA agent."
          submitLabel="Bắt đầu"
          onClose={() => setCreating(false)}
          onSubmit={async (name, description) => {
            const created = await api.createFeature(project.id, name, description);
            onOpenFeature(created.session_id);
          }}
        />
      )}
      {error && <div className="alert">{error}</div>}
      {features === null ? (
        <div className="card skeleton tall" />
      ) : features.length === 0 ? (
        <div className="empty">
          <MessagesSquare size={28} />
          <p>Dự án chưa có feature nào. Tạo feature đầu tiên để bắt đầu hành trình.</p>
          {writeBa && <button className="btn primary" onClick={() => setCreating(true)}><Plus size={16} /> Feature mới</button>}
        </div>
      ) : (
        <div className="card list">
          {features.map((f) => {
            const j = journeys[f.session_id];
            const done = j ? j.steps.filter((s) => s.status === "done").length : 0;
            const current = j?.steps.find((s) => s.key === j.current);
            return (
              <button key={f.session_id} className="row row-button" onClick={() => onOpenFeature(f.session_id)}>
                <span className={`module-icon small ${j?.role === "DESIGNER" ? "designer" : "ba"}`}>
                  {j?.role === "DESIGNER" ? <PenTool size={16} /> : <MessagesSquare size={16} />}
                </span>
                <div className="row-main">
                  <div className="row-title">{f.title}</div>
                  <div className="row-meta">
                    {j ? (j.current === "done" ? "Hoàn tất hành trình" : `Đang ở: ${current?.label ?? ""}`) : "…"} · {timeAgo(f.updated_at)}
                  </div>
                </div>
                <div className="progress" title={`${done}/9 bước`}>
                  <div className="progress-bar" style={{ width: `${(done / 9) * 100}%` }} />
                </div>
                <span className="mono">{done}/9</span>
                <ArrowRight size={16} className="dim" />
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ── Designer inside the portal (project level, no feature) ───────────────

function DesignerPage({ projectId }: { projectId: string }) {
  const { projects } = useContext(Shell);
  const name = projects?.find((p) => p.id === projectId)?.name ?? projectId;
  const session = new URLSearchParams(window.location.search).get("session");
  const src = `/designer/?project=${encodeURIComponent(projectId)}${session ? `&session=${encodeURIComponent(session)}` : ""}&embed=1`;
  return (
    <div className="journey-shell">
      <PageHeader crumbs={[{ label: "Dự án", to: "/" }, { label: name, to: `/projects/${encodeURIComponent(projectId)}` }, { label: "Designer agent" }]}>
        <span className="role-badge designer"><PenTool size={13} /> Vai: Designer</span>
      </PageHeader>
      <div className="frames">
        <iframe src={src} title="Designer agent" />
      </div>
    </div>
  );
}

// ── Journey page: guided BA -> Design in one screen ──────────────────────

const STEP_NUMBER: Record<string, number> = {
  feature_definition: 1, business_rules: 2, workflow: 3, use_cases: 4, validate: 5,
  export: 6, design_scope: 7, design_build: 8, design_review: 9,
};

type Guide =
  | { kind: "welcome"; journey: Journey }
  | { kind: "step"; from: JourneyStep; to: JourneyStep }
  | { kind: "role"; journey: Journey }
  | { kind: "finished"; journey: Journey }
  | { kind: "locked"; step: JourneyStep };

function JourneyPage({
  projectId,
  featureId,
  onBack,
}: {
  projectId: string;
  featureId: string;
  onBack: () => void;
}) {
  const { projects } = useContext(Shell);
  const [journey, setJourney] = useState<Journey | null>(null);
  const [error, setError] = useState("");
  const [selected, setSelected] = useState<string | null>(null);
  const [guide, setGuide] = useState<Guide | null>(null);
  const [handingOff, setHandingOff] = useState(false);
  const previous = useRef<Journey | null>(null);
  const baFrame = useRef<HTMLIFrameElement | null>(null);
  const seenKey = `journey.welcome.${featureId}`;
  const projectName = projects?.find((p) => p.id === projectId)?.name ?? projectId;

  const load = useCallback(async () => {
    try {
      const next = await api.journey(projectId, featureId);
      const prev = previous.current;
      previous.current = next;
      setJourney(next);
      if (!prev) {
        setSelected(next.current === "done" ? "design_review" : next.current);
        let seen = false;
        try { seen = localStorage.getItem(seenKey) === "1"; } catch { /* private mode */ }
        if (!seen) setGuide({ kind: "welcome", journey: next });
        else if (next.current === "design_scope" && !next.designer.session_id) setGuide({ kind: "role", journey: next });
        return;
      }
      if (prev.current !== next.current) {
        const from = prev.steps.find((s) => s.key === prev.current);
        const to = next.steps.find((s) => s.key === next.current);
        if (next.current === "done") setGuide({ kind: "finished", journey: next });
        else if (next.current === "design_scope" && !next.designer.session_id) setGuide({ kind: "role", journey: next });
        else if (from && to) setGuide({ kind: "step", from, to });
      }
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    }
  }, [projectId, featureId, seenKey]);

  useEffect(() => {
    void load();
    const timer = window.setInterval(() => void load(), 6000);
    return () => window.clearInterval(timer);
  }, [load]);

  // BA's "Export → Designer" inside the embedded page asks the shell to switch roles.
  useEffect(() => {
    const onMessage = (event: MessageEvent) => {
      if (event.origin !== window.location.origin) return;
      // Designer's "Trạng thái BA" panel asks to show a BA step in the same page.
      if (event.data?.type === "platform:show-step" && typeof event.data.key === "string") {
        setSelected(event.data.key);
        return;
      }
      if (event.data?.type === "platform:open-designer") {
        void load().then(() => {
          const j = previous.current;
          if (j) setGuide({ kind: "role", journey: j });
        });
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [load]);

  // Keep the embedded BA page on the section of the chosen step.
  const syncBaSection = useCallback(() => {
    if (selected) baFrame.current?.contentWindow?.postMessage({ type: "platform:select-section", key: selected }, window.location.origin);
  }, [selected]);
  useEffect(syncBaSection, [syncBaSection]);

  const startDesign = async () => {
    setHandingOff(true);
    try {
      if (!previous.current?.designer.session_id) await api.handoff(featureId);
      await load();
      setSelected("design_scope");
      setGuide(null);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : String(e));
    } finally {
      setHandingOff(false);
    }
  };

  const crumbs: Crumb[] = [
    { label: projectName, to: `/projects/${encodeURIComponent(projectId)}` },
    { label: journey?.feature.title ?? "…" },
  ];

  if (error && !journey)
    return (
      <>
        <PageHeader crumbs={crumbs} />
        <div className="empty page-empty">
          <p>{error}</p>
          <button className="btn" onClick={onBack}>Về dự án</button>
        </div>
      </>
    );
  if (!journey)
    return (
      <>
        <PageHeader crumbs={crumbs} />
        <div className="boot inline"><span className="spinner" /></div>
      </>
    );

  const step = journey.steps.find((s) => s.key === selected) ?? journey.steps[0];
  const module: "ba" | "designer" = step.role === "DESIGNER" ? "designer" : "ba";
  const baUrl =
    `/ba/chat.html?session=${encodeURIComponent(featureId)}&project_id=${encodeURIComponent(projectId)}` +
    `&title=${encodeURIComponent(journey.feature.title)}&embed=1`;
  const designerUrl = journey.designer.session_id
    ? `/designer/?project=${encodeURIComponent(projectId)}&session=${encodeURIComponent(journey.designer.session_id)}&embed=1`
    : null;
  const done = journey.steps.filter((s) => s.status === "done").length;
  const pkg = journey.ba_package;

  const choose = (s: JourneyStep) => {
    if (s.status === "locked") setGuide({ kind: "locked", step: s });
    else if (s.role === "DESIGNER" && !journey.designer.session_id) setGuide({ kind: "role", journey });
    else setSelected(s.key);
  };

  const groups: [string, JourneyStep[]][] = [
    ["Phân tích BA", journey.steps.slice(0, 6)],
    ["Thiết kế", journey.steps.slice(6)],
  ];

  return (
    <div className="journey-shell">
      <PageHeader
        crumbs={crumbs}
        center={
          <nav className="journey-strip" aria-label="Hành trình">
            {groups.map(([label, steps], g) => (
              <Fragment key={label}>
                {g > 0 && <span className="jdivider" title="BA → Thiết kế" />}
                <div className={`jgroup ${g ? "design" : "ba"}`} title={label}>
                  {steps.map((s, i) => (
                    <Fragment key={s.key}>
                      {i > 0 && <span className={`jconn ${steps[i - 1].status === "done" ? "done" : ""}`} />}
                      <button
                        className={`jstep ${s.status} ${s.key === step.key ? "selected" : ""}`}
                        onClick={() => choose(s)}
                        title={`Bước ${STEP_NUMBER[s.key]} · ${s.label}${s.status === "locked" && s.reason ? ` — ${s.reason}` : ` — ${s.hint}`}`}
                      >
                        <span className="jstep-icon">
                          {s.status === "done" ? <Check size={12} /> : s.status === "locked" ? <Lock size={10} /> : s.status === "attention" ? <CircleAlert size={12} /> : STEP_NUMBER[s.key]}
                        </span>
                        <span className="jstep-label">{s.label}</span>
                      </button>
                    </Fragment>
                  ))}
                </div>
              </Fragment>
            ))}
            <span className="jsummary" title={pkg.latest_version ? `${done}/9 bước · BA package v${pkg.latest_version}` : `${done}/9 bước · chưa có BA package`}>
              {done}<small>/9</small>
            </span>
          </nav>
        }
      >
        {pkg.stale && <span className="state-pill wait" title={`Thiết kế dùng BA v${pkg.used_by_design}`}>BA v{pkg.latest_version} mới — cần xem lại</span>}
        {step.key !== journey.current && journey.current !== "done" && (
          <button className="btn sm ghost" onClick={() => choose(journey.steps.find((s) => s.key === journey.current)!)} title="Về bước đang làm">
            Bước đang làm <ArrowRight size={14} />
          </button>
        )}
        <span className={`role-badge ${module}`}>
          {module === "ba" ? <MessagesSquare size={13} /> : <PenTool size={13} />}
          {module === "ba" ? "BA" : "Designer"}
        </span>
      </PageHeader>

      <div className="frames">
        <iframe ref={baFrame} className={module === "ba" ? "" : "hidden"} src={baUrl} title="BA agent" onLoad={() => window.setTimeout(syncBaSection, 1500)} />
        {designerUrl ? (
          <iframe className={module === "designer" ? "" : "hidden"} src={designerUrl} title="Designer agent" />
        ) : (
          module === "designer" && (
            <div className="frame-placeholder">
              <PenTool size={28} />
              <p>Chưa có phiên thiết kế. Phiên được tạo từ BA package khi bạn bắt đầu bước Thiết kế.</p>
              {journey.steps[5].status === "done" && (
                <button className="btn primary" onClick={() => setGuide({ kind: "role", journey })}>Bắt đầu thiết kế</button>
              )}
            </div>
          )
        )}
      </div>

      {guide && (
        <GuideDialog
          guide={guide}
          busy={handingOff}
          onClose={() => {
            if (guide.kind === "welcome") {
              try { localStorage.setItem(seenKey, "1"); } catch { /* ignore */ }
            }
            setGuide(null);
          }}
          onGo={(key) => {
            if (guide.kind === "welcome") {
              try { localStorage.setItem(seenKey, "1"); } catch { /* ignore */ }
            }
            const target = journey.steps.find((s) => s.key === key);
            setGuide(null);
            if (target) choose(target);
          }}
          onStartDesign={startDesign}
        />
      )}
    </div>
  );
}

function GuideDialog({
  guide,
  busy,
  onClose,
  onGo,
  onStartDesign,
}: {
  guide: Guide;
  busy: boolean;
  onClose: () => void;
  onGo: (key: string) => void;
  onStartDesign: () => void;
}) {
  if (guide.kind === "welcome") {
    const j = guide.journey;
    const current = j.steps.find((s) => s.key === j.current);
    return (
      <Modal title="Hành trình của feature" onClose={onClose} wide>
        <p className="muted">
          Feature <strong>{j.feature.title}</strong> đi qua 9 bước. Bạn làm phân tích với <strong>BA agent</strong> (bước 1–6),
          sau đó chuyển sang vai <strong>Designer</strong> để thiết kế màn hình (bước 7–9). Mỗi khi xong một bước,
          hệ thống sẽ báo và hướng dẫn bước tiếp theo.
        </p>
        <ol className="guide-steps">
          {j.steps.map((s) => (
            <li key={s.key} className={s.status}>
              <strong>{s.label}</strong> <span className="muted">— {s.hint}</span>
            </li>
          ))}
        </ol>
        <div className="dialog-actions">
          <button className="btn primary" onClick={() => onGo(j.current === "done" ? "design_review" : j.current)}>
            {j.current === "done" ? "Xem kết quả" : `Bắt đầu: ${current?.label ?? ""}`} <ArrowRight size={14} />
          </button>
        </div>
      </Modal>
    );
  }
  if (guide.kind === "step") {
    return (
      <Modal title={`Đã xong: ${guide.from.label}`} onClose={onClose}>
        <div className="guide-callout done"><Check size={16} /> Bước {STEP_NUMBER[guide.from.key]} – {guide.from.label} đã hoàn tất.</div>
        <p>Bước tiếp theo là <strong>{guide.to.label}</strong>: {guide.to.hint}</p>
        <p className="muted small">Bạn vẫn có thể bấm vào bước đã xong trên thanh hành trình để xem lại.</p>
        <div className="dialog-actions">
          <button className="btn ghost" onClick={onClose}>Ở lại bước này</button>
          <button className="btn primary" onClick={() => onGo(guide.to.key)}>Tiếp tục: {guide.to.label} <ArrowRight size={14} /></button>
        </div>
      </Modal>
    );
  }
  if (guide.kind === "role") {
    const v = guide.journey.ba_package.latest_version;
    return (
      <Modal title="Phân tích BA đã xong — sang Thiết kế" onClose={onClose} wide>
        <div className="guide-callout done"><Check size={16} /> BA package {v ? `v${v}` : ""} đã được bàn giao và lưu trong Assets.</div>
        <div className="role-switch">
          <span className="role-badge ba"><MessagesSquare size={13} /> Vai: BA</span>
          <ArrowRight size={16} className="dim" />
          <span className="role-badge designer"><PenTool size={13} /> Vai: Designer</span>
        </div>
        <p>
          Bạn sẽ chuyển sang vai <strong>Designer</strong>. Designer agent đọc BA package, đề xuất danh sách màn hình;
          bạn chốt phạm vi, duyệt spec, rồi agent dựng màn hình trên OpenPencil.
        </p>
        <p className="muted small">Các bước BA vẫn xem được trên thanh hành trình. Nếu BA thay đổi, thiết kế sẽ được đánh dấu "cần xem lại".</p>
        <div className="dialog-actions">
          <button className="btn ghost" onClick={onClose}>Để sau</button>
          <button className="btn primary" disabled={busy} onClick={onStartDesign}>
            {busy ? <span className="spinner sm" /> : <>Bắt đầu thiết kế <ArrowRight size={14} /></>}
          </button>
        </div>
      </Modal>
    );
  }
  if (guide.kind === "finished") {
    return (
      <Modal title="Hành trình hoàn tất" onClose={onClose}>
        <div className="guide-callout done"><Check size={16} /> Thiết kế đã được duyệt và lưu vào Assets của dự án.</div>
        <p className="muted">Bạn có thể tải file thiết kế ở tab Assets của dự án, hoặc tiếp tục chỉnh trong bước Thiết kế.</p>
        <div className="dialog-actions">
          <button className="btn primary" onClick={() => onGo("design_review")}>Xem thiết kế</button>
        </div>
      </Modal>
    );
  }
  return (
    <Modal title={`Chưa mở: ${guide.step.label}`} onClose={onClose}>
      <div className="guide-callout locked"><Lock size={15} /> {guide.step.reason}</div>
      <p className="muted small">{guide.step.hint}</p>
      <div className="dialog-actions">
        <button className="btn primary" onClick={onClose}>Đã hiểu</button>
      </div>
    </Modal>
  );
}

// ── Tabs: Assets, Data workspace, Members ────────────────────────────────

const KIND: Record<Artifact["kind"], { label: string; icon: ReactNode; cls: string }> = {
  ba_package: { label: "BA package", icon: <FileJson size={16} />, cls: "ba" },
  bpmn: { label: "BPMN", icon: <Workflow size={16} />, cls: "ba" },
  ui_spec: { label: "UI specification", icon: <FileJson size={16} />, cls: "designer" },
  designer_output: { label: "Thiết kế", icon: <Layers size={16} />, cls: "designer" },
};

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
          <span className="module-icon small wiki"><BookOpen size={18} /></span>
          <div>
            <strong>Wiki &amp; tri thức</strong>
            <p className="muted small">
              {wiki.project_approved.length} trang đã duyệt · {wiki.project_drafts.length} bản nháp · {wiki.company_approved.length} trang chung công ty
            </p>
          </div>
          <ArrowRight size={16} className="dim" />
        </a>
      )}
      {items === null ? (
        <div className="card skeleton tall" />
      ) : items.length === 0 ? (
        <div className="empty"><Boxes size={28} /><p>Chưa có artifact nào. BA package và thiết kế đã duyệt sẽ xuất hiện ở đây.</p></div>
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
                  {a.meta?.state === "review" && <span className="pill warn">Chờ duyệt</span>}
                  {a.meta?.state === "approved" && <span className="pill ok">Đã duyệt</span>}
                  {a.stale && <span className="pill warn">Cần xem lại · BA v{a.derived_latest_version}</span>}
                </div>
                <div className="row-meta">
                  {KIND[a.kind].label}
                  {a.derived_title && <> · từ {a.derived_title} v{a.derived_version}</>}
                  {a.created_by && <> · {a.created_by}</>} · {timeAgo(a.created_at)}
                </div>
              </div>
              {a.storage_key && (
                <a className="icon-btn" href={`/api/core/artifacts/${encodeURIComponent(a.id)}/download`} title="Tải xuống"><Download size={15} /></a>
              )}
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
      <SessionList kind="ba" title="BA sessions" icon={<MessagesSquare size={16} />}
        items={features?.map((f) => ({ id: f.session_id, title: f.title, meta: f.feature_status, href: `/projects/${p}/f/${encodeURIComponent(f.session_id)}` }))} />
      <SessionList kind="designer" title="Designer sessions" icon={<PenTool size={16} />}
        items={sessions?.map((s) => ({ id: s.id, title: s.title, meta: s.source === "ba-handoff" ? "từ BA" : timeAgo(s.updated_at), href: `/projects/${p}/designer?session=${encodeURIComponent(s.id)}` }))} />
    </div>
  );
}

function SessionList(props: { kind: "ba" | "designer"; title: string; icon: ReactNode; items?: { id: string; title: string; meta: string; href: string }[] }) {
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

const ROLES = ["PM", "BA", "DESIGNER", "REVIEWER", "ADMIN"];

function MembersTab({ project, me, onChanged }: { project: ProjectDetail; me: User; onChanged: () => void }) {
  const isAdmin = project.my_roles.includes("ADMIN");
  const [users, setUsers] = useState<User[]>([]);
  const [newUser, setNewUser] = useState("");
  const [newRole, setNewRole] = useState("PM");
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
              <div className="row-title">{m.name}{m.id === me.id && <span className="pill dim">bạn</span>}</div>
              <div className="row-meta mono">{m.username}</div>
            </div>
            <RoleChips roles={m.roles} />
            {isAdmin && m.id !== me.id && (
              <button className="icon-btn danger" onClick={() => void remove(m.id)} title="Xoá khỏi dự án"><X size={15} /></button>
            )}
          </div>
        ))}
      </div>
      {isAdmin && (
        <form className="card invite" onSubmit={add}>
          <UserPlus size={18} className="dim" />
          <select value={newUser} onChange={(e) => setNewUser(e.target.value)} required>
            <option value="">Chọn người dùng…</option>
            {users.map((u) => <option key={u.id} value={u.id}>{u.name} ({u.username})</option>)}
          </select>
          <select value={newRole} onChange={(e) => setNewRole(e.target.value)}>
            {ROLES.map((r) => <option key={r} value={r}>{r === "PM" ? "PM (BA + Designer)" : r}</option>)}
          </select>
          <button className="btn primary" disabled={!newUser}>Thêm</button>
        </form>
      )}
      <p className="muted small">PM làm trọn hành trình (BA + Designer). BA hoặc Designer riêng lẻ chỉ xem phần còn lại.</p>
    </div>
  );
}
