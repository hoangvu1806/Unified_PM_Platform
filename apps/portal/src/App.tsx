import { FormEvent, useCallback, useEffect, useState } from "react";
import {
  ApiError,
  MockUser,
  ProjectDetail,
  ProjectSummary,
  User,
  api,
  canWrite,
  moduleUrl,
} from "./api";

// ── Tiny router: /login, /, /projects/:id ───────────────────────────────

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
  }, []);
  return [path, navigate];
}

function safeNext(raw: string | null): string {
  // Only same-origin absolute paths; never "//host".
  return raw && raw.startsWith("/") && !raw.startsWith("//") ? raw : "/";
}

export function App() {
  const [path, navigate] = usePath();
  const [user, setUser] = useState<User | null | undefined>(undefined);

  useEffect(() => {
    api.me().then(setUser).catch(() => setUser(null));
  }, []);

  const pathname = path.split("?")[0];
  const params = new URLSearchParams(path.split("?")[1] ?? "");

  if (user === undefined) return <div className="center muted">Đang tải…</div>;

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
      <Header user={user} onLogout={logout} onHome={() => navigate("/")} />
      <main className="main">
        {projectMatch ? (
          <ProjectPage projectId={decodeURIComponent(projectMatch[1])} me={user} onBack={() => navigate("/")} />
        ) : (
          <ProjectsPage me={user} onOpenDetail={(id) => navigate(`/projects/${encodeURIComponent(id)}`)} />
        )}
      </main>
    </div>
  );
}

// ── Header ───────────────────────────────────────────────────────────────

function RoleBadges({ roles }: { roles: string[] }) {
  return (
    <span className="badges">
      {roles.map((r) => (
        <span key={r} className={`badge badge-${r.toLowerCase()}`}>
          {r}
        </span>
      ))}
    </span>
  );
}

function Header({ user, onLogout, onHome }: { user: User; onLogout: () => void; onHome: () => void }) {
  return (
    <header className="header">
      <button className="brand" onClick={onHome}>
        BA <span>×</span> DESIGNER
      </button>
      <div className="header-user">
        <span className="user-name">{user.name}</span>
        <RoleBadges roles={user.roles} />
        <button className="btn ghost" onClick={onLogout}>
          Đăng xuất
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
  const [busy, setBusy] = useState(false);
  const [demo, setDemo] = useState<MockUser[]>([]);

  useEffect(() => {
    api.mockUsers().then(setDemo).catch(() => setDemo([]));
  }, []);

  const signIn = async (u: string, p: string) => {
    setBusy(true);
    setError("");
    try {
      const { user } = await api.login(u, p);
      onLoggedIn(user);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Không đăng nhập được");
    } finally {
      setBusy(false);
    }
  };

  const submit = (e: FormEvent) => {
    e.preventDefault();
    void signIn(username, password);
  };

  return (
    <div className="login">
      <div className="login-card">
        <div className="brand big">
          BA <span>×</span> DESIGNER
        </div>
        <p className="muted">Đăng nhập để vào các dự án của bạn.</p>
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
          {error && <div className="error">{error}</div>}
          <button className="btn primary" disabled={busy || !username || !password}>
            Đăng nhập
          </button>
        </form>
        {demo.length > 0 && (
          <div className="demo">
            <div className="demo-title">Đăng nhập nhanh (tài khoản giả lập)</div>
            {demo.map((d) => (
              <button key={d.username} className="demo-user" disabled={busy} onClick={() => void signIn(d.username, d.password)}>
                <span>
                  <strong>{d.name}</strong>
                  <span className="mono muted"> {d.username}</span>
                </span>
                <RoleBadges roles={d.roles} />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ── Projects ─────────────────────────────────────────────────────────────

function openProject(p: ProjectSummary, onOpenDetail: (id: string) => void) {
  const ba = canWrite(p.my_roles, "BA");
  const designer = canWrite(p.my_roles, "DESIGNER");
  if (ba && !designer) window.location.assign(moduleUrl("ba", p.id));
  else if (designer && !ba) window.location.assign(moduleUrl("designer", p.id));
  else onOpenDetail(p.id); // several roles (or reviewer): let the user choose
}

function ProjectsPage({ me, onOpenDetail }: { me: User; onOpenDetail: (id: string) => void }) {
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [error, setError] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");

  const load = useCallback(() => {
    api.projects().then(setProjects).catch((e) => setError(String(e.message ?? e)));
  }, []);
  useEffect(load, [load]);

  const create = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.createProject(name, description);
      setName("");
      setDescription("");
      setCreating(false);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Không tạo được dự án");
    }
  };

  return (
    <section>
      <div className="section-head">
        <div>
          <h1>Dự án của tôi</h1>
          <p className="muted">
            Xin chào {me.name}. Bấm vào dự án để mở trong giao diện {me.roles.join(" / ")}.
          </p>
        </div>
        <button className="btn primary" onClick={() => setCreating((v) => !v)}>
          {creating ? "Đóng" : "+ Tạo dự án"}
        </button>
      </div>

      {creating && (
        <form className="card form inline-form" onSubmit={create}>
          <label>
            Tên dự án
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120} />
          </label>
          <label>
            Mô tả
            <input value={description} onChange={(e) => setDescription(e.target.value)} maxLength={2000} />
          </label>
          <button className="btn primary" disabled={!name.trim()}>
            Tạo
          </button>
        </form>
      )}

      {error && <div className="error">{error}</div>}
      {projects === null ? (
        <div className="muted">Đang tải dự án…</div>
      ) : projects.length === 0 ? (
        <div className="empty">Bạn chưa thuộc dự án nào.</div>
      ) : (
        <div className="grid">
          {projects.map((p) => (
            <article key={p.id} className="card project" onClick={() => openProject(p, onOpenDetail)}>
              <div className="project-top">
                <h2>{p.name}</h2>
                <RoleBadges roles={p.my_roles} />
              </div>
              <p className="muted desc">{p.description || "—"}</p>
              <div className="project-foot">
                <span className="mono dim">{p.id}</span>
                <span className="dim">{p.member_count} thành viên</span>
                <button
                  className="link"
                  onClick={(e) => {
                    e.stopPropagation();
                    onOpenDetail(p.id);
                  }}
                >
                  Chi tiết
                </button>
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

// ── Project detail ───────────────────────────────────────────────────────

const ROLES = ["BA", "DESIGNER", "REVIEWER", "ADMIN"];

function ProjectPage({ projectId, me, onBack }: { projectId: string; me: User; onBack: () => void }) {
  const [project, setProject] = useState<ProjectDetail | null>(null);
  const [error, setError] = useState("");
  const [users, setUsers] = useState<User[]>([]);
  const [newUser, setNewUser] = useState("");
  const [newRole, setNewRole] = useState("BA");

  const load = useCallback(() => {
    api.project(projectId).then(setProject).catch((e) => setError(String(e.message ?? e)));
  }, [projectId]);
  useEffect(load, [load]);

  const isAdmin = project?.my_roles.includes("ADMIN") ?? false;
  useEffect(() => {
    if (isAdmin) api.users().then(setUsers).catch(() => setUsers([]));
  }, [isAdmin]);

  if (error) return <div className="error">{error}</div>;
  if (!project) return <div className="muted">Đang tải…</div>;

  const ba = canWrite(project.my_roles, "BA");
  const designer = canWrite(project.my_roles, "DESIGNER");

  const add = async (e: FormEvent) => {
    e.preventDefault();
    try {
      await api.addMember(project.id, newUser, newRole);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Không thêm được thành viên");
    }
  };
  const remove = async (userId: string) => {
    try {
      await api.removeMember(project.id, userId);
      load();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Không xoá được thành viên");
    }
  };

  return (
    <section>
      <button className="link back" onClick={onBack}>
        ← Dự án của tôi
      </button>
      <div className="section-head">
        <div>
          <h1>{project.name}</h1>
          <p className="muted">{project.description}</p>
          <span className="mono dim">{project.id}</span>
        </div>
        <RoleBadges roles={project.my_roles} />
      </div>

      <div className="modules">
        <a className="card module module-ba" href={moduleUrl("ba", project.id)}>
          <h2>BA</h2>
          <p className="muted">Phân tích yêu cầu, chat với BA agent, wiki, validation.</p>
          <span className="module-mode">{ba ? "Mở để làm việc" : "Mở chỉ đọc"}</span>
        </a>
        <a className="card module module-designer" href={moduleUrl("designer", project.id)}>
          <h2>Designer</h2>
          <p className="muted">Tạo và chỉnh sửa màn hình với Designer agent và OpenPencil.</p>
          <span className="module-mode">{designer ? "Mở để làm việc" : "Mở chỉ đọc"}</span>
        </a>
      </div>

      <h2 className="sub">Thành viên</h2>
      <div className="card">
        <table className="members">
          <tbody>
            {project.members.map((m) => (
              <tr key={m.id}>
                <td>
                  <strong>{m.name}</strong> <span className="mono dim">{m.username}</span>
                </td>
                <td>
                  <RoleBadges roles={m.roles} />
                </td>
                <td className="right">
                  {isAdmin && m.id !== me.id && (
                    <button className="link danger" onClick={() => void remove(m.id)}>
                      Xoá
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {isAdmin && (
          <form className="form inline-form" onSubmit={add}>
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
            <button className="btn" disabled={!newUser}>
              Thêm thành viên
            </button>
          </form>
        )}
      </div>
    </section>
  );
}
