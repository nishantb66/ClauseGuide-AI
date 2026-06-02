import type {
  AnalysisResponse,
  AuthResponse,
  ChatResponse,
  ClauseDetailResponse,
  ClauseListResponse,
  DashboardStats,
  DocumentSummary,
  EvaluationRunListResponse,
  EvaluationRunResponse,
  ImportantPointsResponse,
  MarkdownNoteItem,
  MarkdownWorkspaceDetail,
  MarkdownWorkspaceItem,
  ProcessResponse,
  RegisterResponse,
  ReportGenerateResponse,
  ReportListResponse,
  ReviewWorkspaceResponse,
  UserProfile,
} from "./types";

export const API_BASE = import.meta.env.VITE_API_BASE ?? "http://localhost:8000/api";
export const TOKEN_STORAGE_KEY = "clauseguide_access_token";
export const USER_STORAGE_KEY = "clauseguide_user";

export function getStoredToken(): string | null {
  return localStorage.getItem(TOKEN_STORAGE_KEY);
}

export function setStoredSession(auth: AuthResponse): void {
  localStorage.setItem(TOKEN_STORAGE_KEY, auth.access_token);
  localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(auth.user));
}

export function clearStoredSession(): void {
  localStorage.removeItem(TOKEN_STORAGE_KEY);
  localStorage.removeItem(USER_STORAGE_KEY);
}

export function getStoredUser(): UserProfile | null {
  const raw = localStorage.getItem(USER_STORAGE_KEY);
  if (!raw) return null;
  try {
    return JSON.parse(raw) as UserProfile;
  } catch {
    clearStoredSession();
    return null;
  }
}

function authHeaders(extra?: HeadersInit): HeadersInit {
  const token = getStoredToken();
  return {
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...(extra ?? {}),
  };
}

async function parseResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = `Request failed: ${response.status}`;
    try {
      const payload = await response.json();
      detail = extractErrorMessage(payload, response.status);
    } catch {
      detail = await response.text();
    }
    throw new Error(detail || `Request failed: ${response.status}`);
  }
  return (await response.json()) as T;
}

function extractErrorMessage(payload: unknown, statusCode: number): string {
  if (!payload || typeof payload !== "object") {
    return `Request failed (${statusCode}).`;
  }
  const record = payload as Record<string, unknown>;
  const detail = record.detail;
  if (typeof detail === "string") {
    return detail;
  }
  if (Array.isArray(detail)) {
    const messages = detail
      .map((entry) => {
        if (!entry || typeof entry !== "object") return null;
        const item = entry as Record<string, unknown>;
        const location = Array.isArray(item.loc)
          ? item.loc.filter((part) => typeof part === "string").join(" ")
          : "";
        const msg = typeof item.msg === "string" ? item.msg : "";
        const normalizedLocation = location.replace(/^body\s*/i, "");
        const friendlyLocation = normalizedLocation
          .replace(/_/g, " ")
          .replace(/\b\w/g, (char) => char.toUpperCase())
          .trim();
        if (!msg) return null;
        return friendlyLocation ? `${friendlyLocation}: ${msg}` : msg;
      })
      .filter((line): line is string => Boolean(line));
    if (messages.length > 0) {
      return messages.join(". ");
    }
  }
  const message = record.message;
  if (typeof message === "string" && message.trim()) {
    return message;
  }
  return `Request failed (${statusCode}).`;
}

export async function registerAccount(payload: {
  email: string;
  password: string;
  full_name?: string | null;
}): Promise<RegisterResponse> {
  const response = await fetch(`${API_BASE}/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

export async function verifyOtp(payload: { email: string; otp: string }): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE}/auth/verify-otp`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

export async function resendOtp(email: string): Promise<{ message: string }> {
  const response = await fetch(`${API_BASE}/auth/resend-otp`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  return parseResponse(response);
}

export async function loginAccount(payload: { email: string; password: string }): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

export async function googleAuth(payload: {
  code?: string | null;
  id_token?: string | null;
  redirect_uri?: string | null;
}): Promise<AuthResponse> {
  const response = await fetch(`${API_BASE}/auth/google`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

export async function getCurrentUser(): Promise<UserProfile> {
  const response = await fetch(`${API_BASE}/auth/me`, { headers: authHeaders() });
  return parseResponse(response);
}

export async function getDashboardStats(): Promise<DashboardStats> {
  const response = await fetch(`${API_BASE}/dashboard/stats`, { headers: authHeaders() });
  return parseResponse(response);
}

export async function uploadDocument(file: File): Promise<{ document_id: string; status: string }> {
  const formData = new FormData();
  formData.append("file", file);

  const response = await fetch(`${API_BASE}/documents/upload`, {
    method: "POST",
    headers: authHeaders(),
    body: formData,
  });

  return parseResponse(response);
}

export async function processDocument(documentId: string): Promise<ProcessResponse> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/process`, {
    method: "POST",
    headers: authHeaders(),
  });
  return parseResponse(response);
}

export async function listDocuments(): Promise<DocumentSummary[]> {
  const response = await fetch(`${API_BASE}/documents`, { headers: authHeaders() });
  return parseResponse(response);
}

export async function getAnalysis(documentId: string): Promise<AnalysisResponse> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/analysis`, {
    headers: authHeaders(),
  });
  return parseResponse(response);
}

export async function getClauses(documentId: string): Promise<ClauseListResponse> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/clauses`, {
    headers: authHeaders(),
  });
  return parseResponse(response);
}

export async function getClauseDetail(
  documentId: string,
  clauseId: number
): Promise<ClauseDetailResponse> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/clauses/${clauseId}`, {
    headers: authHeaders(),
  });
  return parseResponse(response);
}

export async function chatWithDocument(
  documentId: string,
  question: string,
  sessionId?: string
): Promise<ChatResponse> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/chat`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ question, session_id: sessionId ?? null }),
  });
  return parseResponse(response);
}

export async function getReviewWorkspace(documentId: string): Promise<ReviewWorkspaceResponse> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/review-workspace`, {
    headers: authHeaders(),
  });
  return parseResponse(response);
}

export async function getImportantPoints(documentId: string): Promise<ImportantPointsResponse> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/important-points`, {
    headers: authHeaders(),
  });
  return parseResponse(response);
}

export async function listMarkdownWorkspaces(): Promise<MarkdownWorkspaceItem[]> {
  const response = await fetch(`${API_BASE}/markdown/workspaces`, {
    headers: authHeaders(),
  });
  return parseResponse(response);
}

export async function createMarkdownWorkspace(payload: {
  title?: string | null;
  document_id?: string | null;
}): Promise<MarkdownWorkspaceDetail> {
  const response = await fetch(`${API_BASE}/markdown/workspaces`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

export async function getMarkdownWorkspace(workspaceId: string): Promise<MarkdownWorkspaceDetail> {
  const response = await fetch(`${API_BASE}/markdown/workspaces/${workspaceId}`, {
    headers: authHeaders(),
  });
  return parseResponse(response);
}

export async function getOrCreateDocumentMarkdownWorkspace(
  documentId: string
): Promise<MarkdownWorkspaceDetail> {
  const response = await fetch(`${API_BASE}/markdown/documents/${documentId}/workspace`, {
    method: "POST",
    headers: authHeaders(),
  });
  return parseResponse(response);
}

export async function createMarkdownNote(
  workspaceId: string,
  payload: {
    page_number: number;
    selected_text: string;
    rects: Array<{
      page: number;
      x0: number;
      y0: number;
      x1: number;
      y1: number;
      page_width: number;
      page_height: number;
    }>;
    note_html: string;
    note_markdown: string;
    color?: string;
  }
): Promise<MarkdownNoteItem> {
  const response = await fetch(`${API_BASE}/markdown/workspaces/${workspaceId}/notes`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

export async function updateMarkdownNote(
  workspaceId: string,
  noteId: string,
  payload: { note_html: string; note_markdown: string; color?: string }
): Promise<MarkdownNoteItem> {
  const response = await fetch(`${API_BASE}/markdown/workspaces/${workspaceId}/notes/${noteId}`, {
    method: "PATCH",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

export async function deleteMarkdownNote(workspaceId: string, noteId: string): Promise<{ status: string }> {
  const response = await fetch(`${API_BASE}/markdown/workspaces/${workspaceId}/notes/${noteId}`, {
    method: "DELETE",
    headers: authHeaders(),
  });
  return parseResponse(response);
}

export async function generateReport(
  documentId: string,
  outputFormat: "markdown" | "text" = "markdown"
): Promise<ReportGenerateResponse> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/report`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({ output_format: outputFormat }),
  });
  return parseResponse(response);
}

export async function listReports(documentId: string): Promise<ReportListResponse> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/reports`, {
    headers: authHeaders(),
  });
  return parseResponse(response);
}

export async function downloadReportFile(reportId: string): Promise<Blob> {
  const response = await fetch(`${API_BASE}/reports/${reportId}/download`, {
    headers: authHeaders(),
  });
  if (!response.ok) {
    await parseResponse(response);
  }
  return response.blob();
}

export async function runEvaluation(
  documentId: string,
  payload: { run_label?: string; use_ragas?: boolean } = {}
): Promise<EvaluationRunResponse> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/evaluations/run`, {
    method: "POST",
    headers: authHeaders({ "Content-Type": "application/json" }),
    body: JSON.stringify({
      run_label: payload.run_label ?? "default",
      use_ragas: payload.use_ragas ?? false,
    }),
  });
  return parseResponse(response);
}

export async function listEvaluations(documentId: string): Promise<EvaluationRunListResponse> {
  const response = await fetch(`${API_BASE}/documents/${documentId}/evaluations`, {
    headers: authHeaders(),
  });
  return parseResponse(response);
}
