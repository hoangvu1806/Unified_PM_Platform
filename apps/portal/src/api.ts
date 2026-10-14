// core-api client. Same origin as the gateway; the session lives in an
// HttpOnly cookie set by /api/core/auth/login.

export type User = { id: string; username: string; name: string; roles: string[] };
export type MockUser = { username: string; name: string; roles: string[]; password: string };
export type ProjectSummary = {
  id: string;
  name: string;
  description: string;
  my_roles: string[];
  member_count: number;
};
export type Member = { id: string; username: string; name: string; roles: string[] };
export type ProjectDetail = ProjectSummary & { members: Member[] };

export type Artifact = {
  id: string;
  kind: "ba_package" | "designer_output";
  source_module: string;
  source_ref: string;
  version: number;
  latest_version: number;
  title: string;
  storage_key: string | null;
  derived_from_id: string | null;
  derived_version: number | null;
  derived_title: string | null;
  derived_latest_version: number | null;
  stale: boolean;
  meta: Record<string, string>;
  created_by: string | null;
  created_at: string;
};
export type BaFeature = { session_id: string; title: string; feature_status: string; updated_at: string };
export type DesignerSession = { id: string; title: string; source?: string | null; updated_at: string };
export type WikiList = { project_approved: unknown[]; project_drafts: unknown[]; company_approved: unknown[] };

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api/core${path}`, {
    credentials: "same-origin",
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    const detail = body?.detail;
    const message = typeof detail === "string" ? detail : detail?.message ?? res.statusText;
    throw new ApiError(res.status, message);
  }
  return res.json() as Promise<T>;
}

async function moduleGet<T>(url: string): Promise<T> {
  const res = await fetch(url, { credentials: "same-origin" });
  if (!res.ok) throw new ApiError(res.status, res.statusText);
  return res.json() as Promise<T>;
}

export const api = {
  artifacts: (projectId: string) => call<Artifact[]>(`/projects/${encodeURIComponent(projectId)}/artifacts`),
  baFeatures: (projectId: string) =>
    moduleGet<BaFeature[]>(`/ba/api/features?project_id=${encodeURIComponent(projectId)}`),
  designerSessions: (projectId: string) =>
    moduleGet<DesignerSession[]>(`/designer/api/v1/sessions?project_id=${encodeURIComponent(projectId)}`),
  wiki: (projectId: string) => moduleGet<WikiList>(`/ba/api/wiki/pages?project_id=${encodeURIComponent(projectId)}`),
  me: () => call<User>("/me"),
  mockUsers: () => call<MockUser[]>("/auth/mock-users"),
  login: (username: string, password: string) =>
    call<{ user: User }>("/auth/login", { method: "POST", body: JSON.stringify({ username, password }) }),
  logout: () => call<{ ok: boolean }>("/auth/logout", { method: "POST" }),
  projects: () => call<ProjectSummary[]>("/projects"),
  project: (id: string) => call<ProjectDetail>(`/projects/${encodeURIComponent(id)}`),
  createProject: (name: string, description: string) =>
    call<ProjectSummary>("/projects", { method: "POST", body: JSON.stringify({ name, description }) }),
  users: () => call<User[]>("/users"),
  addMember: (projectId: string, userId: string, role: string) =>
    call(`/projects/${encodeURIComponent(projectId)}/members`, {
      method: "POST",
      body: JSON.stringify({ user_id: userId, project_role: role }),
    }),
  removeMember: (projectId: string, userId: string) =>
    call(`/projects/${encodeURIComponent(projectId)}/members/${encodeURIComponent(userId)}`, { method: "DELETE" }),
};

// Which module UI opens a project. BA → /ba/, Designer → /designer/.
export function moduleUrl(module: "ba" | "designer", projectId: string): string {
  return `/${module}/?project=${encodeURIComponent(projectId)}`;
}

export function canWrite(roles: string[], role: "BA" | "DESIGNER"): boolean {
  return roles.includes(role) || roles.includes("ADMIN");
}
