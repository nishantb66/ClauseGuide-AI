import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import type { PDFDocumentProxy } from "pdfjs-dist/legacy/build/pdf.mjs";
import pdfWorkerUrl from "pdfjs-dist/legacy/build/pdf.worker.min.mjs?url";

import {
  API_BASE,
  clearStoredSession,
  createMarkdownNote,
  createMarkdownWorkspace,
  deleteMarkdownNote,
  downloadReportFile,
  generateReport,
  getAnalysis,
  getClauseDetail,
  getClauses,
  getCurrentUser,
  getDashboardStats,
  getImportantPoints,
  getMarkdownWorkspace,
  getOrCreateDocumentMarkdownWorkspace,
  getReviewWorkspace,
  getStoredToken,
  getStoredUser,
  googleAuth,
  listDocuments,
  listEvaluations,
  listMarkdownWorkspaces,
  listReports,
  loginAccount,
  processDocument,
  registerAccount,
  resendOtp,
  runEvaluation,
  setStoredSession,
  uploadDocument,
  updateMarkdownNote,
  verifyOtp,
  chatWithDocument,
} from "./api";
import type {
  AnalysisResponse,
  AnalysisRiskItem,
  ChatResponse,
  ClauseDetailResponse,
  ClauseItem,
  DashboardStats,
  DocumentSummary,
  EvaluationRunListItem,
  EvaluationRunResponse,
  ImportantPointItem,
  ImportantPointsResponse,
  MarkdownNoteItem,
  MarkdownWorkspaceDetail,
  MarkdownWorkspaceItem,
  PdfLineItem,
  ReportListItem,
  ReviewPageItem,
  ReviewRiskItem,
  ReviewWorkspaceResponse,
  TextHighlight,
  UserProfile,
} from "./types";

const GOOGLE_CLIENT_ID =
  import.meta.env.VITE_GOOGLE_CLIENT_ID ??
  "527917090388-bsf245sm5aavvop89hkfh9ae2qpdddna.apps.googleusercontent.com";
const GOOGLE_REDIRECT_URI =
  import.meta.env.VITE_GOOGLE_REDIRECT_URI ?? "http://localhost:5173/google/callback/";

type AuthMode = "login" | "register" | "verify";
type PortalView = "dashboard" | "documents" | "markdown";
type WorkspaceView = "risks" | "review" | "markdown" | "clauses" | "chat" | "reports";

function prettyLabel(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (char) => char.toUpperCase());
}

function riskTone(level: string | null | undefined): string {
  if (level === "critical") return "risk-critical";
  if (level === "high") return "risk-high";
  if (level === "medium") return "risk-medium";
  if (level === "low") return "risk-low";
  return "risk-neutral";
}

function confidenceLabel(score: number): string {
  if (score >= 0.8) return "Strong evidence";
  if (score >= 0.6) return "Good evidence";
  if (score >= 0.4) return "Limited evidence";
  return "Not enough evidence";
}

function compactTitle(value: string | null | undefined): string {
  if (!value) return "Untitled document";
  const cleaned = value
    .replace(/^https?:/i, "")
    .replace(/[:/\\]+/g, " ")
    .replace(/[_-]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
  return cleaned.length > 92 ? `${cleaned.slice(0, 89)}...` : cleaned;
}

function formatDate(value: string | null | undefined): string {
  if (!value) return "Not processed";
  return new Date(value).toLocaleDateString(undefined, {
    day: "2-digit",
    month: "short",
    year: "numeric",
  });
}

function riskCopy(level: string): string {
  if (level === "critical") return "Do not sign before review.";
  if (level === "high") return "Review carefully before signing.";
  if (level === "medium") return "Some terms need attention.";
  return "No major risk surfaced yet.";
}

function sourcePages(analysis: AnalysisResponse | null): string {
  const pages = analysis?.extraction_health.source_pages ?? [];
  return pages.length > 0 ? pages.join(", ") : "No cited pages yet";
}

function verificationTone(status: string | null | undefined): string {
  return status === "verified" ? "verification-ok" : "verification-needs-review";
}

function verificationLabel(status: string | null | undefined): string {
  return status === "verified" ? "Verified" : "Needs review";
}

function truncateText(value: string | null | undefined, maxChars: number): string {
  if (!value) return "";
  const clean = value.trim();
  if (clean.length <= maxChars) return clean;
  return `${clean.slice(0, maxChars - 1).trimEnd()}...`;
}

function App() {
  const [user, setUser] = useState<UserProfile | null>(() => getStoredUser());
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [authEmail, setAuthEmail] = useState("");
  const [authName, setAuthName] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [otp, setOtp] = useState("");
  const [portalView, setPortalView] = useState<PortalView>("dashboard");
  const [dashboardStats, setDashboardStats] = useState<DashboardStats | null>(null);

  const [documents, setDocuments] = useState<DocumentSummary[]>([]);
  const [selectedDocumentId, setSelectedDocumentId] = useState("");
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [clauses, setClauses] = useState<ClauseItem[]>([]);
  const [selectedClauseDetail, setSelectedClauseDetail] = useState<ClauseDetailResponse | null>(null);
  const [question, setQuestion] = useState("");
  const [chatHistory, setChatHistory] = useState<ChatResponse[]>([]);
  const [chatSessionId, setChatSessionId] = useState<string | undefined>();
  const [reports, setReports] = useState<ReportListItem[]>([]);
  const [evaluationRuns, setEvaluationRuns] = useState<EvaluationRunListItem[]>([]);
  const [latestEvaluation, setLatestEvaluation] = useState<EvaluationRunResponse | null>(null);
  const [useRagasEval, setUseRagasEval] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [activeView, setActiveView] = useState<WorkspaceView>("risks");
  const [isRailCollapsed, setIsRailCollapsed] = useState(() => {
    return localStorage.getItem("clauseguide_rail_collapsed") === "true";
  });

  const selectedDocument = useMemo(
    () => documents.find((doc) => doc.id === selectedDocumentId) ?? null,
    [documents, selectedDocumentId]
  );

  const risksByLevel = useMemo(() => {
    const groups: Record<string, AnalysisRiskItem[]> = {
      critical: [],
      high: [],
      medium: [],
      low: [],
    };
    for (const risk of analysis?.top_risks ?? []) {
      const level = risk.risk_level in groups ? risk.risk_level : "low";
      groups[level].push(risk);
    }
    return groups;
  }, [analysis]);

  const viewItems = useMemo(
    () => [
      { id: "risks" as const, label: "Risks", count: analysis?.extraction_health.risks_found },
      { id: "review" as const, label: "Review", count: analysis?.extraction_health.risks_found },
      { id: "markdown" as const, label: "Markdown", count: undefined },
      { id: "clauses" as const, label: "Clauses", count: analysis?.extraction_health.clauses_found },
      { id: "chat" as const, label: "Chat", count: chatHistory.length || undefined },
      { id: "reports" as const, label: "Reports", count: reports.length || undefined },
    ],
    [analysis, chatHistory.length, reports.length]
  );

  function setRailCollapsed(collapsed: boolean) {
    setIsRailCollapsed(collapsed);
    localStorage.setItem("clauseguide_rail_collapsed", String(collapsed));
  }

  function handleAuthSuccess(authUser: UserProfile) {
    setUser(authUser);
    setAuthMode("login");
    setAuthPassword("");
    setOtp("");
    setError("");
    setPortalView("dashboard");
  }

  function logout() {
    clearStoredSession();
    setUser(null);
    setDocuments([]);
    setDashboardStats(null);
    setSelectedDocumentId("");
    resetDocumentState();
    setMessage("");
    setError("");
  }

  function handleError(err: unknown, fallback: string) {
    const detail = err instanceof Error ? err.message : fallback;
    setError(detail);
    if (/authentication|required|token|401|403/i.test(detail)) {
      logout();
    }
  }

  async function refreshDashboard() {
    if (!user) return;
    try {
      const stats = await getDashboardStats();
      setDashboardStats(stats);
    } catch (err) {
      handleError(err, "Failed to load dashboard");
    }
  }

  async function refreshDocuments() {
    try {
      const data = await listDocuments();
      setDocuments(data);
      if (!selectedDocumentId && data.length > 0) {
        setSelectedDocumentId(data[0].id);
      }
    } catch (err) {
      handleError(err, "Failed to load documents");
    }
  }

  async function refreshClauseExplorer(documentId: string, preferredClauseId?: number) {
    const clauseList = await getClauses(documentId);
    setClauses(clauseList.clauses);

    if (clauseList.clauses.length === 0) {
      setSelectedClauseDetail(null);
      return;
    }

    const targetClauseId = preferredClauseId ?? clauseList.clauses[0].id;
    const detail = await getClauseDetail(documentId, targetClauseId);
    setSelectedClauseDetail(detail);
  }

  async function refreshReports(documentId: string) {
    const reportList = await listReports(documentId);
    setReports(reportList.reports);
  }

  async function refreshEvaluations(documentId: string) {
    const evaluationList = await listEvaluations(documentId);
    setEvaluationRuns(evaluationList.runs);
  }

  async function loadAnalysisForDocument(documentId: string) {
    if (!documentId) return;

    setBusy(true);
    setError("");
    try {
      const [analysisResult] = await Promise.all([
        getAnalysis(documentId),
        refreshClauseExplorer(documentId),
        refreshReports(documentId),
        refreshEvaluations(documentId),
      ]);
      setAnalysis(analysisResult);
    } catch (err) {
      handleError(err, "Failed to load analysis");
    } finally {
      setBusy(false);
    }
  }

  function resetDocumentState() {
    setAnalysis(null);
    setClauses([]);
    setSelectedClauseDetail(null);
    setChatHistory([]);
    setChatSessionId(undefined);
    setReports([]);
    setEvaluationRuns([]);
    setLatestEvaluation(null);
  }

  async function onRegister() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await registerAccount({ email: authEmail, password: authPassword, full_name: authName || null });
      setAuthMode("verify");
      setMessage("OTP sent to your email. Verify it to activate your account.");
    } catch (err) {
      handleError(err, "Registration failed");
    } finally {
      setBusy(false);
    }
  }

  async function onVerifyOtp() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const auth = await verifyOtp({ email: authEmail, otp });
      setStoredSession(auth);
      handleAuthSuccess(auth.user);
      setMessage("Account verified. Welcome to ClauseGuide AI.");
    } catch (err) {
      handleError(err, "OTP verification failed");
    } finally {
      setBusy(false);
    }
  }

  async function onLogin() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const auth = await loginAccount({ email: authEmail, password: authPassword });
      setStoredSession(auth);
      handleAuthSuccess(auth.user);
    } catch (err) {
      handleError(err, "Login failed");
    } finally {
      setBusy(false);
    }
  }

  async function onResendOtp() {
    setBusy(true);
    setError("");
    try {
      const result = await resendOtp(authEmail);
      setMessage(result.message);
    } catch (err) {
      handleError(err, "Could not resend OTP");
    } finally {
      setBusy(false);
    }
  }

  function startGoogleSignIn() {
    const params = new URLSearchParams({
      client_id: GOOGLE_CLIENT_ID,
      redirect_uri: GOOGLE_REDIRECT_URI,
      response_type: "code",
      scope: "openid email profile",
      prompt: "select_account",
    });
    window.location.href = `https://accounts.google.com/o/oauth2/v2/auth?${params.toString()}`;
  }

  async function onUpload(file: File | null) {
    if (!file) return;

    setBusy(true);
    setError("");
    setMessage("");
    try {
      const upload = await uploadDocument(file);
      setSelectedDocumentId(upload.document_id);
      resetDocumentState();
      await Promise.all([refreshDocuments(), refreshDashboard()]);
      setPortalView("documents");
      setMessage("Document uploaded. Run analysis when ready.");
    } catch (err) {
      handleError(err, "Upload failed");
    } finally {
      setBusy(false);
    }
  }

  async function onProcessDocument() {
    if (!selectedDocumentId) {
      setError("Select a document first");
      return;
    }

    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await processDocument(selectedDocumentId);
      await refreshDocuments();
      await loadAnalysisForDocument(selectedDocumentId);
      await refreshDashboard();
      setActiveView("risks");
      setMessage(
        `Analysis complete: ${result.total_pages} pages, ${result.clauses_extracted} clauses, ${result.risk_findings} findings.`
      );
    } catch (err) {
      handleError(err, "Processing failed");
    } finally {
      setBusy(false);
    }
  }

  async function onSelectClause(clauseId: number) {
    if (!selectedDocumentId) return;
    setError("");
    try {
      const detail = await getClauseDetail(selectedDocumentId, clauseId);
      setSelectedClauseDetail(detail);
    } catch (err) {
      handleError(err, "Failed to load clause detail");
    }
  }

  async function onAsk() {
    if (!selectedDocumentId || !question.trim()) return;

    setBusy(true);
    setError("");
    try {
      const result = await chatWithDocument(selectedDocumentId, question, chatSessionId);
      setChatSessionId(result.session_id);
      setChatHistory((current) => [result, ...current]);
      setQuestion("");
    } catch (err) {
      handleError(err, "Chat failed");
    } finally {
      setBusy(false);
    }
  }

  async function onGenerateReport(outputFormat: "markdown" | "text") {
    if (!selectedDocumentId) {
      setError("Select a processed document first");
      return;
    }

    setBusy(true);
    setError("");
    setMessage("");
    try {
      const response = await generateReport(selectedDocumentId, outputFormat);
      await Promise.all([refreshReports(selectedDocumentId), refreshDashboard()]);
      setMessage(`Generated report: ${response.file_name}`);
    } catch (err) {
      handleError(err, "Report generation failed");
    } finally {
      setBusy(false);
    }
  }

  async function onDownloadReport(report: ReportListItem) {
    setBusy(true);
    setError("");
    try {
      const blob = await downloadReportFile(report.report_id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = report.file_name;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      handleError(err, "Report download failed");
    } finally {
      setBusy(false);
    }
  }

  async function onRunEvaluation() {
    if (!selectedDocumentId) return;

    setBusy(true);
    setError("");
    setMessage("");
    try {
      const result = await runEvaluation(selectedDocumentId, {
        run_label: "portal_default",
        use_ragas: useRagasEval,
      });
      setLatestEvaluation(result);
      await refreshEvaluations(selectedDocumentId);
      setMessage(`Quality check complete: ${result.metrics.total_cases} test questions.`);
    } catch (err) {
      handleError(err, "Evaluation run failed");
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const isGoogleCallback = window.location.pathname === "/google/callback/";
    const code = params.get("code");
    if (!isGoogleCallback || !code) return;

    setBusy(true);
    setError("");
    void googleAuth({ code, redirect_uri: GOOGLE_REDIRECT_URI })
      .then((auth) => {
        setStoredSession(auth);
        handleAuthSuccess(auth.user);
        window.history.replaceState({}, "", "/");
      })
      .catch((err) => handleError(err, "Google sign-in failed"))
      .finally(() => setBusy(false));
  }, []);

  useEffect(() => {
    if (!user) return;
    void getCurrentUser()
      .then((profile) => {
        setUser(profile);
        localStorage.setItem("clauseguide_user", JSON.stringify(profile));
      })
      .catch(() => logout());
  }, []);

  useEffect(() => {
    if (!user) return;
    void Promise.all([refreshDashboard(), refreshDocuments()]);
  }, [user?.id]);

  if (!user) {
    return (
      <main className="auth-shell">
        <section className="auth-hero">
          <p className="eyebrow">ClauseGuide AI</p>
          <h1>Legal risk analysis portal for agreements and documents.</h1>
          <p>
            Upload contracts, run AI risk review, ask document-grounded questions, and export
            professional reports from one secure workspace.
          </p>
          <div className="auth-proof-grid">
            <span>CUAD-backed clause intelligence</span>
            <span>Source-grounded AI chat</span>
            <span>Personal document workspace</span>
          </div>
        </section>

        <section className="auth-card">
          <p className="eyebrow">Secure access</p>
          <h2>
            {authMode === "login"
              ? "Sign in to your portal"
              : authMode === "register"
                ? "Create your account"
                : "Verify your email"}
          </h2>
          <p className="auth-copy">
            {authMode === "verify"
              ? `Enter the OTP sent to ${authEmail}.`
              : "Use email/password or continue with Google SSO."}
          </p>

          {error ? <div className="notice error">{error}</div> : null}
          {message ? <div className="notice success">{message}</div> : null}

          {authMode === "register" ? (
            <label className="form-field">
              Full name
              <input value={authName} onChange={(event) => setAuthName(event.target.value)} />
            </label>
          ) : null}

          <label className="form-field">
            Email address
            <input
              type="email"
              value={authEmail}
              disabled={authMode === "verify"}
              onChange={(event) => setAuthEmail(event.target.value)}
            />
          </label>

          {authMode !== "verify" ? (
            <label className="form-field">
              Password
              <input
                type="password"
                value={authPassword}
                onChange={(event) => setAuthPassword(event.target.value)}
              />
            </label>
          ) : (
            <label className="form-field">
              OTP code
              <input value={otp} onChange={(event) => setOtp(event.target.value)} inputMode="numeric" />
            </label>
          )}

          <button
            type="button"
            className="primary-wide"
            disabled={busy || !authEmail || (authMode !== "verify" && !authPassword)}
            onClick={() => {
              if (authMode === "login") void onLogin();
              if (authMode === "register") void onRegister();
              if (authMode === "verify") void onVerifyOtp();
            }}
          >
            {busy
              ? "Please wait..."
              : authMode === "login"
                ? "Sign in"
                : authMode === "register"
                  ? "Create account"
                  : "Verify and continue"}
          </button>

          {authMode !== "verify" ? (
            <button type="button" className="google-button" disabled={busy} onClick={startGoogleSignIn}>
              Continue with Google
            </button>
          ) : (
            <button type="button" className="ghost-wide" disabled={busy || !authEmail} onClick={() => void onResendOtp()}>
              Resend OTP
            </button>
          )}

          <div className="auth-switch">
            {authMode === "login" ? (
              <button type="button" onClick={() => setAuthMode("register")}>Create a new account</button>
            ) : (
              <button type="button" onClick={() => setAuthMode("login")}>Back to login</button>
            )}
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className={`app-shell portal-shell ${isRailCollapsed ? "rail-collapsed" : ""}`}>
      {isRailCollapsed ? (
        <button
          type="button"
          className="rail-open-button"
          onClick={() => setRailCollapsed(false)}
          aria-label="Open sidebar"
        >
          <span>Menu</span>
        </button>
      ) : null}

      <aside className="document-rail portal-rail" aria-hidden={isRailCollapsed}>
        <div className="brand-lockup">
          <div>
            <p className="eyebrow">ClauseGuide AI</p>
            <h1>Legal Risk Portal</h1>
            <small>{user.email}</small>
          </div>
          <div className="rail-top-actions">
            <span className="status-dot" />
            <button
              type="button"
              className="rail-collapse-button"
              onClick={() => setRailCollapsed(true)}
              aria-label="Collapse sidebar"
              title="Collapse sidebar"
            >
              Hide
            </button>
          </div>
        </div>

        <nav className="portal-nav">
          <button className={portalView === "dashboard" ? "active" : ""} onClick={() => setPortalView("dashboard")}>
            Dashboard
          </button>
          <button className={portalView === "documents" ? "active" : ""} onClick={() => setPortalView("documents")}>
            AI Document Review
          </button>
          <button className={portalView === "markdown" ? "active" : ""} onClick={() => setPortalView("markdown")}>
            Markdown
          </button>
        </nav>

        <label className="upload-zone">
          <span>Upload legal document</span>
          <small>PDF, DOCX, or TXT. Saved only to your account.</small>
          <input
            type="file"
            accept=".pdf,.docx,.txt"
            disabled={busy}
            onChange={(event) => void onUpload(event.currentTarget.files?.[0] ?? null)}
          />
        </label>

        <div className="rail-actions">
          <button type="button" disabled={busy || !selectedDocumentId} onClick={() => void onProcessDocument()}>
            Analyse
          </button>
          <button type="button" disabled={busy || !selectedDocumentId} onClick={() => void loadAnalysisForDocument(selectedDocumentId)}>
            Refresh
          </button>
        </div>

        <div className="document-list">
          {documents.map((doc) => (
            <button
              key={doc.id}
              type="button"
              onClick={() => {
                setSelectedDocumentId(doc.id);
                resetDocumentState();
                setPortalView("documents");
                if (doc.status === "analyzed") void loadAnalysisForDocument(doc.id);
              }}
              className={selectedDocumentId === doc.id ? "document-row active" : "document-row"}
              title={doc.title}
            >
              <span className="document-row-top">
                <strong>{compactTitle(doc.title)}</strong>
                <em>{doc.status}</em>
              </span>
              <small>{doc.contract_type ? prettyLabel(doc.contract_type) : "Unknown type"}</small>
              <small>
                {doc.total_pages ? `${doc.total_pages} pages` : "Awaiting analysis"} | {formatDate(doc.processed_at ?? doc.uploaded_at)}
              </small>
            </button>
          ))}
          {documents.length === 0 ? <p className="empty-copy">No documents yet.</p> : null}
        </div>

        <button type="button" className="logout-button" onClick={logout}>Sign out</button>
      </aside>

      <section className="workspace">
        {error ? <div className="notice error">{error}</div> : null}
        {message ? <div className="notice success">{message}</div> : null}

        {portalView === "dashboard" ? (
          <DashboardView
            stats={dashboardStats}
            user={user}
            onOpenDocuments={() => setPortalView("documents")}
          />
        ) : portalView === "markdown" ? (
          <MarkdownPortalView documents={documents} selectedDocumentId={selectedDocumentId} />
        ) : (
          <DocumentWorkspace
            activeView={activeView}
            analysis={analysis}
            busy={busy}
            clauses={clauses}
            documents={documents}
            evaluationRuns={evaluationRuns}
            latestEvaluation={latestEvaluation}
            onAsk={onAsk}
            onDownloadReport={onDownloadReport}
            onGenerateReport={onGenerateReport}
            onProcessDocument={onProcessDocument}
            onRunEvaluation={onRunEvaluation}
            onSelectClause={onSelectClause}
            question={question}
            reports={reports}
            risksByLevel={risksByLevel}
            selectedClauseDetail={selectedClauseDetail}
            selectedDocument={selectedDocument}
            selectedDocumentId={selectedDocumentId}
            setActiveView={setActiveView}
            setQuestion={setQuestion}
            setUseRagasEval={setUseRagasEval}
            useRagasEval={useRagasEval}
            viewItems={viewItems}
            chatHistory={chatHistory}
          />
        )}
      </section>
    </main>
  );
}

function DashboardView({
  stats,
  user,
  onOpenDocuments,
}: {
  stats: DashboardStats | null;
  user: UserProfile;
  onOpenDocuments: () => void;
}) {
  const statCards = [
    ["Documents analysed", stats?.documents_analyzed ?? 0],
    ["Documents uploaded", stats?.documents_uploaded ?? 0],
    ["Total risks found", stats?.total_risks_detected ?? 0],
    ["High/Critical risks", stats?.high_or_critical_risks ?? 0],
    ["Clauses read", stats?.clauses_read ?? 0],
    ["Reports generated", stats?.reports_generated ?? 0],
  ];

  return (
    <section className="portal-dashboard">
      <div className="workspace-top portal-hero-card">
        <div className="workspace-title">
          <p className="eyebrow">Portal dashboard</p>
          <h2>Welcome back{user.full_name ? `, ${user.full_name}` : ""}.</h2>
          <p>Track your AI legal reviews, risk exposure, reports, and recent uploads.</p>
          <div className="meta-chips">
            <span>Verified account</span>
            <span>{user.auth_provider === "google" ? "Google SSO" : "Email login"}</span>
            <span>Average risk score {stats?.average_risk_score ?? 0}</span>
          </div>
        </div>
        <button type="button" className="portal-cta" onClick={onOpenDocuments}>Review a document</button>
      </div>

      <div className="portal-stat-grid">
        {statCards.map(([label, value]) => (
          <article key={label} className="portal-stat-card">
            <span>{label}</span>
            <strong>{value}</strong>
          </article>
        ))}
      </div>

      <div className="portal-two-column">
        <section className="summary-panel">
          <p className="eyebrow">Risk distribution</p>
          <div className="risk-breakdown">
            {(["critical", "high", "medium", "low"] as const).map((level) => (
              <div key={level}>
                <span className={riskTone(level)}>{prettyLabel(level)}</span>
                <strong>{stats?.risk_level_breakdown[level] ?? 0}</strong>
              </div>
            ))}
          </div>
        </section>

        <section className="summary-panel">
          <p className="eyebrow">Recent documents</p>
          <div className="recent-list">
            {(stats?.latest_documents ?? []).map((doc) => (
              <article key={doc.id}>
                <strong>{compactTitle(doc.title)}</strong>
                <span>{prettyLabel(doc.contract_type ?? "unknown")} | {doc.status}</span>
              </article>
            ))}
            {!stats?.latest_documents.length ? <p className="empty-copy">Upload your first document to begin.</p> : null}
          </div>
        </section>
      </div>
    </section>
  );
}

function MarkdownPortalView({
  documents,
  selectedDocumentId,
}: {
  documents: DocumentSummary[];
  selectedDocumentId: string;
}) {
  const [workspaces, setWorkspaces] = useState<MarkdownWorkspaceItem[]>([]);
  const [activeWorkspaceId, setActiveWorkspaceId] = useState("");
  const [documentChoice, setDocumentChoice] = useState(selectedDocumentId);
  const [loading, setLoading] = useState(false);
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    setDocumentChoice((current) => current || selectedDocumentId);
  }, [selectedDocumentId]);

  async function refreshWorkspaces(preferredId?: string) {
    setLoading(true);
    setLocalError("");
    try {
      const rows = await listMarkdownWorkspaces();
      setWorkspaces(rows);
      setActiveWorkspaceId(preferredId ?? activeWorkspaceId ?? rows[0]?.id ?? "");
      if (!activeWorkspaceId && rows[0]) setActiveWorkspaceId(rows[0].id);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Could not load Markdown workspaces");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshWorkspaces();
  }, []);

  async function createFromDocument() {
    if (!documentChoice) {
      setLocalError("Select a PDF document first, or upload one from the left panel.");
      return;
    }
    setLoading(true);
    setLocalError("");
    try {
      const workspace = await createMarkdownWorkspace({ document_id: documentChoice });
      await refreshWorkspaces(workspace.id);
      setActiveWorkspaceId(workspace.id);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Could not create Markdown workspace");
    } finally {
      setLoading(false);
    }
  }

  return (
    <section className="markdown-portal">
      <div className="workspace-top portal-hero-card">
        <div className="workspace-title">
          <p className="eyebrow">Markdown notebook</p>
          <h2>Take source-linked notes directly on the PDF.</h2>
          <p>Double-click a PDF line to create a note. Click a note later to jump back to its exact source.</p>
        </div>
        <div className="markdown-create-panel">
          <select value={documentChoice} onChange={(event) => setDocumentChoice(event.target.value)}>
            <option value="">Choose a PDF document</option>
            {documents.filter((doc) => doc.file_type === ".pdf").map((doc) => (
              <option key={doc.id} value={doc.id}>
                {compactTitle(doc.title)}
              </option>
            ))}
          </select>
          <button type="button" className="portal-cta" disabled={loading || !documentChoice} onClick={() => void createFromDocument()}>
            Open notebook
          </button>
        </div>
      </div>

      {localError ? <div className="notice error">{localError}</div> : null}

      <div className="markdown-workspace-shell">
        <aside className="markdown-workspace-list">
          <div className="mini-panel-head">
            <span>Workspaces</span>
            <button type="button" disabled={loading} onClick={() => void refreshWorkspaces()}>Refresh</button>
          </div>
          {workspaces.map((workspace) => (
            <button
              key={workspace.id}
              type="button"
              className={workspace.id === activeWorkspaceId ? "active" : ""}
              onClick={() => setActiveWorkspaceId(workspace.id)}
            >
              <strong>{compactTitle(workspace.title)}</strong>
              <span>{workspace.notes_count} notes | {workspace.document_title ?? "No document"}</span>
            </button>
          ))}
          {!workspaces.length ? <p className="empty-copy">No Markdown workspaces yet.</p> : null}
        </aside>
        <MarkdownNotesView
          workspaceId={activeWorkspaceId}
          onWorkspaceSaved={(workspace) => {
            setWorkspaces((current) =>
              current.map((item) =>
                item.id === workspace.id ? { ...item, notes_count: workspace.notes.length, updated_at: workspace.updated_at } : item
              )
            );
          }}
        />
      </div>
    </section>
  );
}

function MarkdownNotesView({
  documentId,
  workspaceId,
  embedded = false,
  onWorkspaceSaved,
}: {
  documentId?: string;
  workspaceId?: string;
  embedded?: boolean;
  onWorkspaceSaved?: (workspace: MarkdownWorkspaceDetail) => void;
}) {
  const editorRef = useRef<HTMLDivElement | null>(null);
  const [workspace, setWorkspace] = useState<MarkdownWorkspaceDetail | null>(null);
  const [activeNoteId, setActiveNoteId] = useState<string | null>(null);
  const [draftHtml, setDraftHtml] = useState("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [localError, setLocalError] = useState("");

  const activeNote = workspace?.notes.find((note) => note.id === activeNoteId) ?? null;

  useEffect(() => {
    if (!documentId && !workspaceId) {
      setWorkspace(null);
      return;
    }

    setLoading(true);
    setLocalError("");
    const loader = documentId
      ? getOrCreateDocumentMarkdownWorkspace(documentId)
      : getMarkdownWorkspace(workspaceId as string);

    void loader
      .then((payload) => {
        setWorkspace(payload);
        setActiveNoteId(payload.notes[0]?.id ?? null);
        setDraftHtml(payload.notes[0]?.note_html ?? "");
      })
      .catch((err) => setLocalError(err instanceof Error ? err.message : "Could not open Markdown workspace"))
      .finally(() => setLoading(false));
  }, [documentId, workspaceId]);

  useEffect(() => {
    setDraftHtml(activeNote?.note_html ?? "");
    if (editorRef.current) editorRef.current.innerHTML = activeNote?.note_html ?? "";
  }, [activeNoteId]);

  function noteHighlights(): CanvasHighlight[] {
    return (
      workspace?.notes.map((note) => ({
        page: note.page_number,
        statement: note.selected_text,
        start_char: null,
        end_char: null,
        match_confidence: 1,
        rects: note.rects,
        id: `md-note-${note.id}`,
        title: note.selected_text,
        riskLevel: note.color,
      })) ?? []
    );
  }

  function focusNote(note: MarkdownNoteItem) {
    setActiveNoteId(note.id);
    jumpToReviewTarget(`md-note-${note.id}`, note.page_number);
  }

  async function createNoteFromLine(line: PdfLineItem) {
    if (!workspace) return;
    setSaving(true);
    setLocalError("");
    try {
      const note = await createMarkdownNote(workspace.id, {
        page_number: line.page,
        selected_text: line.text,
        rects: line.rects,
        note_html: `<p><strong>Note:</strong> ${escapeHtml(line.text)}</p>`,
        note_markdown: `**Note:** ${line.text}`,
        color: "yellow",
      });
      const updated = { ...workspace, notes: [...workspace.notes, note], notes_count: workspace.notes.length + 1 };
      setWorkspace(updated);
      onWorkspaceSaved?.(updated);
      setActiveNoteId(note.id);
      setDraftHtml(note.note_html);
      window.setTimeout(() => editorRef.current?.focus(), 80);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Could not create note");
    } finally {
      setSaving(false);
    }
  }

  async function saveActiveNote() {
    if (!workspace || !activeNote) return;
    const html = editorRef.current?.innerHTML ?? draftHtml;
    setSaving(true);
    setLocalError("");
    try {
      const note = await updateMarkdownNote(workspace.id, activeNote.id, {
        note_html: html,
        note_markdown: htmlToMarkdown(html),
        color: activeNote.color,
      });
      const updated = {
        ...workspace,
        notes: workspace.notes.map((item) => (item.id === note.id ? note : item)),
      };
      setWorkspace(updated);
      onWorkspaceSaved?.(updated);
      setDraftHtml(note.note_html);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Could not save note");
    } finally {
      setSaving(false);
    }
  }

  async function deleteActiveNote() {
    if (!workspace || !activeNote) return;
    setSaving(true);
    setLocalError("");
    try {
      await deleteMarkdownNote(workspace.id, activeNote.id);
      const remaining = workspace.notes.filter((note) => note.id !== activeNote.id);
      const updated = { ...workspace, notes: remaining, notes_count: remaining.length };
      setWorkspace(updated);
      onWorkspaceSaved?.(updated);
      setActiveNoteId(remaining[0]?.id ?? null);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Could not delete note");
    } finally {
      setSaving(false);
    }
  }

  if (loading) {
    return (
      <section className="summary-panel">
        <p className="eyebrow">Markdown</p>
        <h3>Opening PDF notebook...</h3>
      </section>
    );
  }

  if (!workspace) {
    return (
      <section className="summary-panel">
        <p className="eyebrow">Markdown</p>
        <h3>{embedded ? "Select a PDF document to start notes." : "Create or select a notebook."}</h3>
        <p>Markdown notes are mapped to exact PDF lines and saved to your account.</p>
      </section>
    );
  }

  if (workspace.file_type !== ".pdf" || !workspace.file_url) {
    return (
      <section className="summary-panel">
        <p className="eyebrow">Markdown</p>
        <h3>This workspace needs a PDF document.</h3>
        <p>Upload a PDF to use line-linked Markdown notes.</p>
      </section>
    );
  }

  return (
    <section className={`markdown-notes-view ${embedded ? "embedded" : ""}`}>
      <div className="markdown-header">
        <div>
          <p className="eyebrow">Markdown</p>
          <h3>{workspace.title}</h3>
          <p>Double-click any visible PDF line to create a mapped note.</p>
        </div>
        <span>{workspace.notes.length} notes</span>
      </div>
      {localError ? <div className="notice error">{localError}</div> : null}
      <div className="markdown-review-grid">
        <div className="markdown-pdf-panel">
          <PdfDocumentCanvas
            fileUrl={workspace.file_url}
            pages={[]}
            highlights={noteHighlights()}
            activeHighlightId={activeNote ? `md-note-${activeNote.id}` : null}
            selectableLines={workspace.lines}
            onLineDoubleClick={(line) => void createNoteFromLine(line)}
          />
        </div>
        <aside className="markdown-note-panel">
          <div className="markdown-note-list">
            {workspace.notes.map((note) => (
              <button
                key={note.id}
                type="button"
                className={activeNoteId === note.id ? "active" : ""}
                onClick={() => focusNote(note)}
              >
                <strong>Page {note.page_number}</strong>
                <span>{truncateText(note.selected_text, 130)}</span>
              </button>
            ))}
            {!workspace.notes.length ? (
              <div className="empty-note-state">
                <strong>No notes yet</strong>
                <span>Double-click a line on the PDF to pin your first Markdown note.</span>
              </div>
            ) : null}
          </div>

          <div className="markdown-editor-card">
            <div className="markdown-editor-toolbar">
              <button type="button" onClick={() => document.execCommand("bold")}>B</button>
              <button type="button" onClick={() => document.execCommand("italic")}>I</button>
              <button type="button" onClick={() => document.execCommand("underline")}>U</button>
              <button type="button" onClick={() => document.execCommand("insertUnorderedList")}>List</button>
            </div>
            <div className="selected-source">
              {activeNote ? activeNote.selected_text : "Select or create a note to start writing."}
            </div>
            <div
              ref={editorRef}
              className="markdown-editor"
              contentEditable={Boolean(activeNote)}
              suppressContentEditableWarning
              onInput={(event) => setDraftHtml(event.currentTarget.innerHTML)}
            />
            <div className="markdown-editor-actions">
              <button type="button" disabled={!activeNote || saving} onClick={() => void saveActiveNote()}>
                {saving ? "Saving..." : "Save note"}
              </button>
              <button type="button" className="danger-lite" disabled={!activeNote || saving} onClick={() => void deleteActiveNote()}>
                Delete
              </button>
            </div>
          </div>
        </aside>
      </div>
    </section>
  );
}

function escapeHtml(value: string): string {
  return value.replace(/[&<>"']/g, (char) => {
    const entities: Record<string, string> = {
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      "\"": "&quot;",
      "'": "&#039;",
    };
    return entities[char] ?? char;
  });
}

function htmlToMarkdown(html: string): string {
  const container = document.createElement("div");
  container.innerHTML = html;
  return (container.textContent ?? "").trim();
}

function DocumentWorkspace(props: {
  activeView: WorkspaceView;
  analysis: AnalysisResponse | null;
  busy: boolean;
  clauses: ClauseItem[];
  documents: DocumentSummary[];
  evaluationRuns: EvaluationRunListItem[];
  latestEvaluation: EvaluationRunResponse | null;
  onAsk: () => void;
  onDownloadReport: (report: ReportListItem) => void;
  onGenerateReport: (format: "markdown" | "text") => void;
  onProcessDocument: () => void;
  onRunEvaluation: () => void;
  onSelectClause: (clauseId: number) => void;
  question: string;
  reports: ReportListItem[];
  risksByLevel: Record<string, AnalysisRiskItem[]>;
  selectedClauseDetail: ClauseDetailResponse | null;
  selectedDocument: DocumentSummary | null;
  selectedDocumentId: string;
  setActiveView: (view: WorkspaceView) => void;
  setQuestion: (value: string) => void;
  setUseRagasEval: (value: boolean) => void;
  useRagasEval: boolean;
  viewItems: Array<{ id: WorkspaceView; label: string; count?: number }>;
  chatHistory: ChatResponse[];
}) {
  const {
    activeView,
    analysis,
    busy,
    clauses,
    evaluationRuns,
    latestEvaluation,
    onAsk,
    onDownloadReport,
    onGenerateReport,
    onProcessDocument,
    onRunEvaluation,
    onSelectClause,
    question,
    reports,
    risksByLevel,
    selectedClauseDetail,
    selectedDocument,
    selectedDocumentId,
    setActiveView,
    setQuestion,
    setUseRagasEval,
    useRagasEval,
    viewItems,
    chatHistory,
  } = props;

  return (
    <>
      <div className="workspace-top">
        <div className="workspace-title">
          <p className="eyebrow">Current document</p>
          <h2 title={selectedDocument?.title}>
            {selectedDocument ? compactTitle(selectedDocument.title) : "Select or upload a document"}
          </h2>
          <p>
            {analysis?.contract_type_label ??
              (selectedDocument?.contract_type
                ? prettyLabel(selectedDocument.contract_type)
                : "Document type will appear after analysis")}
          </p>
          {analysis ? (
            <div className="meta-chips">
              <span>{analysis.document_classification?.is_template ? "Template/sample" : "Agreement review"}</span>
              <span>{analysis.extraction_health.clauses_found} clauses read</span>
              <span>{analysis.extraction_health.risks_found} findings</span>
              <span>{sourcePages(analysis)}</span>
            </div>
          ) : null}
        </div>

        {analysis ? (
          <div className={`score-tile ${riskTone(analysis.overall_risk_level)}`}>
            <span>{analysis.overall_risk_score}</span>
            <strong>{prettyLabel(analysis.overall_risk_level)}</strong>
            <small>{riskCopy(analysis.overall_risk_level)}</small>
          </div>
        ) : (
          <button type="button" className="portal-cta" disabled={busy || !selectedDocumentId} onClick={() => void onProcessDocument()}>
            Run AI analysis
          </button>
        )}
      </div>

      {analysis ? (
        <div className="decision-strip">
          <div><span>Risk findings</span><strong>{analysis.extraction_health.risks_found}</strong></div>
          <div><span>Clauses read</span><strong>{analysis.extraction_health.clauses_found}</strong></div>
          <div><span>Evidence pages</span><strong>{sourcePages(analysis)}</strong></div>
          <div>
            <span>Verification coverage</span>
            <strong>
              {analysis.verification_summary
                ? `${analysis.verification_summary.verified_count}/${analysis.verification_summary.verified_count + analysis.verification_summary.needs_review_count} verified`
                : analysis.extraction_health.note}
            </strong>
          </div>
        </div>
      ) : null}

      <nav className="view-tabs">
        {viewItems.map((view) => (
          <button key={view.id} type="button" className={activeView === view.id ? "active" : ""} onClick={() => setActiveView(view.id)}>
            {view.label}{view.count ? <span>{view.count}</span> : null}
          </button>
        ))}
      </nav>

      {activeView === "risks" ? <RisksView analysis={analysis} risksByLevel={risksByLevel} /> : null}
      {activeView === "review" ? (
        <ReviewWorkspaceView selectedDocumentId={selectedDocumentId} analysis={analysis} />
      ) : null}
      {activeView === "markdown" ? (
        <MarkdownNotesView documentId={selectedDocumentId} embedded />
      ) : null}
      {activeView === "clauses" ? <ClausesView clauses={clauses} selectedClauseDetail={selectedClauseDetail} onSelectClause={onSelectClause} /> : null}
      {activeView === "chat" ? <ChatView busy={busy} selectedDocumentId={selectedDocumentId} question={question} setQuestion={setQuestion} onAsk={onAsk} chatHistory={chatHistory} /> : null}
      {activeView === "reports" ? <ReportsView busy={busy} selectedDocumentId={selectedDocumentId} reports={reports} latestEvaluation={latestEvaluation} evaluationRuns={evaluationRuns} useRagasEval={useRagasEval} setUseRagasEval={setUseRagasEval} onGenerateReport={onGenerateReport} onRunEvaluation={onRunEvaluation} onDownloadReport={onDownloadReport} /> : null}
    </>
  );
}

type ReviewMode = "risks" | "important";

type CanvasHighlight = TextHighlight & {
  id: string;
  title: string;
  riskLevel: string;
};

const MIN_PDF_SCALE = 0.55;
const MAX_PDF_SCALE = 1.9;

function reviewHighlightId(id: string): string {
  return `review-highlight-${id.replace(/[^a-zA-Z0-9_-]/g, "-")}`;
}

function resolveApiFileUrl(fileUrl: string): string {
  if (/^https?:\/\//i.test(fileUrl)) return fileUrl;
  return new URL(fileUrl, API_BASE).toString();
}

function jumpToReviewTarget(highlightId: string | null, page: number, attempt = 0) {
  window.setTimeout(() => {
    const highlightTarget = highlightId ? document.getElementById(reviewHighlightId(highlightId)) : null;
    const pageTarget = document.getElementById(`review-page-${page}`);

    if (highlightTarget) {
      highlightTarget.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
      return;
    }

    if (attempt < 8) {
      jumpToReviewTarget(highlightId, page, attempt + 1);
      return;
    }

    pageTarget?.scrollIntoView({ block: "center", inline: "center", behavior: "smooth" });
  }, attempt === 0 ? 40 : 140);
}

function ReviewWorkspaceView({
  selectedDocumentId,
  analysis,
}: {
  selectedDocumentId: string;
  analysis: AnalysisResponse | null;
}) {
  const [workspace, setWorkspace] = useState<ReviewWorkspaceResponse | null>(null);
  const [importantPoints, setImportantPoints] = useState<ImportantPointsResponse | null>(null);
  const [reviewMode, setReviewMode] = useState<ReviewMode>("risks");
  const [selectedRiskId, setSelectedRiskId] = useState<number | null>(null);
  const [activePointId, setActivePointId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [localError, setLocalError] = useState("");

  useEffect(() => {
    if (!selectedDocumentId || !analysis) {
      setWorkspace(null);
      setImportantPoints(null);
      setSelectedRiskId(null);
      setActivePointId(null);
      return;
    }

    setLoading(true);
    setLocalError("");
    void getReviewWorkspace(selectedDocumentId)
      .then((payload) => {
        setWorkspace(payload);
        setSelectedRiskId(payload.risks[0]?.finding_id ?? null);
      })
      .catch((err) => {
        setLocalError(err instanceof Error ? err.message : "Could not load review workspace");
      })
      .finally(() => setLoading(false));
  }, [selectedDocumentId, analysis?.contract_type]);

  async function openImportantPoints() {
    if (!selectedDocumentId) return;
    setReviewMode("important");
    if (importantPoints) {
      setActivePointId((current) => current ?? importantPoints.points[0]?.id ?? null);
      return;
    }

    setLoading(true);
    setLocalError("");
    try {
      const payload = await getImportantPoints(selectedDocumentId);
      setImportantPoints(payload);
      setActivePointId(payload.points[0]?.id ?? null);
    } catch (err) {
      setLocalError(err instanceof Error ? err.message : "Could not load important points");
    } finally {
      setLoading(false);
    }
  }

  function focusRisk(risk: ReviewRiskItem) {
    setReviewMode("risks");
    setSelectedRiskId(risk.finding_id);
    jumpToReviewTarget(`risk-${risk.finding_id}`, risk.highlight?.page ?? risk.page);
  }

  function focusPoint(point: ImportantPointItem) {
    setActivePointId(point.id);
    jumpToReviewTarget(point.id, point.highlight?.page ?? point.page);
  }

  if (!analysis) {
    return (
      <section className="summary-panel">
        <p className="eyebrow">Review workspace</p>
        <h3>Run analysis first to open source-linked risk review.</h3>
        <p>The interactive canvas appears once the document has extracted risks and cited pages.</p>
      </section>
    );
  }

  if (loading && !workspace) {
    return (
      <section className="summary-panel">
        <p className="eyebrow">Review workspace</p>
        <h3>Preparing linked evidence view...</h3>
      </section>
    );
  }

  if (localError) {
    return <div className="notice error">{localError}</div>;
  }

  if (!workspace) {
    return null;
  }

  const selectedRisk =
    workspace.risks.find((risk) => risk.finding_id === selectedRiskId) ?? workspace.risks[0] ?? null;
  const riskHighlights = selectedRisk?.highlight
    ? [
        {
          ...selectedRisk.highlight,
          id: `risk-${selectedRisk.finding_id}`,
          title: selectedRisk.title,
          riskLevel: selectedRisk.risk_level,
        },
      ]
    : [];
  const importantHighlights =
    importantPoints?.points
      .filter((point) => point.highlight)
      .map((point) => ({
        ...(point.highlight as TextHighlight),
        id: point.id,
        title: point.title,
        riskLevel: point.risk_level,
      })) ?? [];

  if (reviewMode === "important") {
    return (
      <section className="review-workspace">
        <ReviewToolbar
          mode={reviewMode}
          loading={loading}
          onShowRisks={() => setReviewMode("risks")}
          onShowImportant={() => void openImportantPoints()}
        />
        <div className="important-points-bar">
          {(importantPoints?.points ?? []).map((point) => (
            <button
              key={point.id}
              type="button"
              className={activePointId === point.id ? "active" : ""}
              onClick={() => focusPoint(point)}
            >
              <strong>{point.title}</strong>
              <span>Page {point.page} | Score {point.risk_score}</span>
              <small>{truncateText(point.reason, 92)}</small>
            </button>
          ))}
          {!importantPoints?.points.length && !loading ? (
            <p className="empty-copy">No important points were available for this document.</p>
          ) : null}
        </div>
        <DocumentCanvas
          pages={importantPoints?.pages ?? workspace.pages}
          fileUrl={importantPoints?.file_url ?? workspace.file_url}
          fileType={importantPoints?.file_type ?? workspace.file_type}
          highlights={importantHighlights}
          activeHighlightId={activePointId}
          mode="important"
        />
      </section>
    );
  }

  return (
    <section className="review-workspace">
      <ReviewToolbar
        mode={reviewMode}
        loading={loading}
        onShowRisks={() => setReviewMode("risks")}
        onShowImportant={() => void openImportantPoints()}
      />
      <div className="review-split">
        <aside className="review-risk-list">
          {workspace.risks.map((risk) => (
            <button
              key={risk.finding_id}
              type="button"
              className={selectedRisk?.finding_id === risk.finding_id ? "active" : ""}
              onClick={() => focusRisk(risk)}
            >
              <span className={`review-risk-level ${riskTone(risk.risk_level)}`}>
                {prettyLabel(risk.risk_level)}
              </span>
              <strong>{risk.title}</strong>
              <small>Page {risk.page} | Score {risk.risk_score}</small>
              <p>{truncateText(risk.summary, 150)}</p>
            </button>
          ))}
        </aside>
        <DocumentCanvas
          pages={workspace.pages}
          fileUrl={workspace.file_url}
          fileType={workspace.file_type}
          highlights={riskHighlights}
          activeHighlightId={selectedRisk ? `risk-${selectedRisk.finding_id}` : null}
          mode="risks"
        />
      </div>
    </section>
  );
}

function ReviewToolbar({
  mode,
  loading,
  onShowRisks,
  onShowImportant,
}: {
  mode: ReviewMode;
  loading: boolean;
  onShowRisks: () => void;
  onShowImportant: () => void;
}) {
  return (
    <div className="review-toolbar">
      <div>
        <p className="eyebrow">Source-linked review</p>
        <h3>Risks mapped to the document text</h3>
        <p>Click any item to jump to the highlighted source in the original PDF.</p>
      </div>
      <div className="review-mode-switch">
        <button type="button" className={mode === "risks" ? "active" : ""} onClick={onShowRisks}>
          Risks
        </button>
        <button type="button" className={mode === "important" ? "active" : ""} disabled={loading} onClick={onShowImportant}>
          Very important points
        </button>
      </div>
    </div>
  );
}

function DocumentCanvas({
  pages,
  fileUrl,
  fileType,
  highlights,
  activeHighlightId,
  mode,
}: {
  pages: ReviewPageItem[];
  fileUrl: string;
  fileType: string;
  highlights: CanvasHighlight[];
  activeHighlightId: string | null;
  mode: ReviewMode;
}) {
  const shouldRenderPdf = fileType.toLowerCase() === ".pdf" && Boolean(fileUrl);

  return (
    <div className={`document-canvas ${mode === "important" ? "full-canvas" : ""} ${shouldRenderPdf ? "pdf-canvas" : "text-canvas"}`}>
      {shouldRenderPdf ? (
        <PdfDocumentCanvas
          fileUrl={fileUrl}
          pages={pages}
          highlights={highlights}
          activeHighlightId={activeHighlightId}
        />
      ) : pages.map((page) => (
        <article key={page.page} id={`review-page-${page.page}`} className="document-page">
          <div className="document-page-head">
            <span>Page {page.page}</span>
            <small>
              {highlights.filter((highlight) => highlight.page === page.page).length || "No"} highlights
            </small>
          </div>
          <pre>{renderHighlightedText(page, highlights, activeHighlightId)}</pre>
        </article>
      ))}
    </div>
  );
}

function PdfDocumentCanvas({
  fileUrl,
  pages,
  highlights,
  activeHighlightId,
  selectableLines = [],
  onLineDoubleClick,
}: {
  fileUrl: string;
  pages: ReviewPageItem[];
  highlights: CanvasHighlight[];
  activeHighlightId: string | null;
  selectableLines?: PdfLineItem[];
  onLineDoubleClick?: (line: PdfLineItem) => void;
}) {
  const pagesFrameRef = useRef<HTMLDivElement | null>(null);
  const [pdf, setPdf] = useState<PDFDocumentProxy | null>(null);
  const [availableWidth, setAvailableWidth] = useState(900);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const frame = pagesFrameRef.current;
    if (!frame) return;

    const resizeObserver = new ResizeObserver(([entry]) => {
      setAvailableWidth(Math.max(320, entry.contentRect.width));
    });
    resizeObserver.observe(frame);
    return () => resizeObserver.disconnect();
  }, [pdf]);

  useEffect(() => {
    let cancelled = false;
    let loadingTask: { promise: Promise<PDFDocumentProxy>; destroy: () => Promise<void> } | null = null;
    const token = getStoredToken();

    setLoading(true);
    setError("");
    setPdf(null);

    void import("pdfjs-dist/legacy/build/pdf.mjs")
      .then(({ getDocument, GlobalWorkerOptions }) => {
        if (cancelled) return null;
        GlobalWorkerOptions.workerSrc = pdfWorkerUrl;
        loadingTask = getDocument({
          url: resolveApiFileUrl(fileUrl),
          httpHeaders: token ? { Authorization: `Bearer ${token}` } : undefined,
        });
        return loadingTask.promise;
      })
      .then((loadedPdf) => {
        if (!cancelled && loadedPdf) setPdf(loadedPdf);
      })
      .catch((err) => {
        if (!cancelled) {
          console.error("ClauseGuide PDF load failed", err);
          setError("The original PDF could not be opened in the review canvas. Please retry or reprocess the document.");
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
      void loadingTask?.destroy();
    };
  }, [fileUrl]);

  if (loading && !pdf) {
    return (
      <div className="pdf-loading-card">
        <span>Loading original PDF...</span>
      </div>
    );
  }

  if (error || !pdf) {
    return (
      <div className="pdf-loading-card">
        <strong>PDF preview unavailable</strong>
        <span>{error || "The source PDF could not be opened. Text fallback is available after reload."}</span>
      </div>
    );
  }

  const pageCount = Math.max(pdf.numPages, pages.length);

  return (
    <div ref={pagesFrameRef} className="pdf-pages-frame">
      {Array.from({ length: pageCount }, (_, index) => index + 1).map((pageNumber) => (
        <PdfPageCanvas
          key={`${fileUrl}-${pageNumber}`}
          pdf={pdf}
          pageNumber={pageNumber}
          availableWidth={availableWidth}
          highlights={highlights.filter((highlight) => highlight.page === pageNumber)}
          activeHighlightId={activeHighlightId}
          selectableLines={selectableLines.filter((line) => line.page === pageNumber)}
          onLineDoubleClick={onLineDoubleClick}
        />
      ))}
    </div>
  );
}

function PdfPageCanvas({
  pdf,
  pageNumber,
  availableWidth,
  highlights,
  activeHighlightId,
  selectableLines = [],
  onLineDoubleClick,
}: {
  pdf: PDFDocumentProxy;
  pageNumber: number;
  availableWidth: number;
  highlights: CanvasHighlight[];
  activeHighlightId: string | null;
  selectableLines?: PdfLineItem[];
  onLineDoubleClick?: (line: PdfLineItem) => void;
}) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [pageSize, setPageSize] = useState({ width: 0, height: 0 });
  const [pageError, setPageError] = useState("");
  const hasActiveHighlight = Boolean(activeHighlightId && highlights.some((highlight) => highlight.id === activeHighlightId));

  useEffect(() => {
    let cancelled = false;
    let renderTask: { promise: Promise<unknown>; cancel: () => void } | null = null;

    void pdf
      .getPage(pageNumber)
      .then((page) => {
        if (cancelled) return null;
        const canvas = canvasRef.current;
        const canvasContext = canvas?.getContext("2d");
        if (!canvas || !canvasContext) return null;

        const baseViewport = page.getViewport({ scale: 1 });
        const targetWidth = Math.max(320, availableWidth - 12);
        const displayScale = Math.min(MAX_PDF_SCALE, Math.max(MIN_PDF_SCALE, targetWidth / baseViewport.width));
        const outputScale = Math.min(2, window.devicePixelRatio || 1);
        const displayViewport = page.getViewport({ scale: displayScale });
        const renderViewport = page.getViewport({ scale: displayScale * outputScale });

        canvas.width = Math.floor(renderViewport.width);
        canvas.height = Math.floor(renderViewport.height);
        canvas.style.width = `${displayViewport.width}px`;
        canvas.style.height = `${displayViewport.height}px`;
        setPageSize({ width: displayViewport.width, height: displayViewport.height });
        setPageError("");

        renderTask = page.render({ canvasContext, viewport: renderViewport });
        return renderTask.promise;
      })
      .catch((err) => {
        if (!cancelled && !(err instanceof Error && err.name === "RenderingCancelledException")) {
          console.error(`ClauseGuide PDF page ${pageNumber} render failed`, err);
          setPageError("This PDF page could not be rendered. Please retry or reprocess the document.");
        }
      });

    return () => {
      cancelled = true;
      renderTask?.cancel();
    };
  }, [availableWidth, pdf, pageNumber]);

  useEffect(() => {
    if (!hasActiveHighlight || !activeHighlightId || !pageSize.width) return;
    window.setTimeout(() => {
      document.getElementById(reviewHighlightId(activeHighlightId))?.scrollIntoView({
        block: "center",
        inline: "center",
        behavior: "smooth",
      });
    }, 80);
  }, [activeHighlightId, hasActiveHighlight, pageSize.width]);

  return (
    <article id={`review-page-${pageNumber}`} className="document-page pdf-document-page">
      <div className="document-page-head">
        <span>Page {pageNumber}</span>
        <small>{highlights.length || "No"} highlights</small>
      </div>
      <div
        className="pdf-page-shell"
        style={pageSize.width && pageSize.height ? { width: pageSize.width, height: pageSize.height } : undefined}
      >
        <canvas ref={canvasRef} aria-label={`Original PDF page ${pageNumber}`} />
        {pageSize.width && pageSize.height ? (
          <div className="pdf-highlight-layer" aria-hidden="true">
            {highlights.flatMap((highlight) =>
              highlight.rects
                .filter((rect) => rect.page === pageNumber)
                .map((rect, rectIndex) => {
                  const scaleX = pageSize.width / rect.page_width;
                  const scaleY = pageSize.height / rect.page_height;
                  const x = Math.min(rect.x0, rect.x1) * scaleX;
                  const y = Math.min(rect.y0, rect.y1) * scaleY;
                  const width = Math.abs(rect.x1 - rect.x0) * scaleX;
                  const height = Math.abs(rect.y1 - rect.y0) * scaleY;

                  return (
                    <span
                      key={`${highlight.id}-${rectIndex}-${rect.x0}-${rect.y0}`}
                      id={rectIndex === 0 ? reviewHighlightId(highlight.id) : undefined}
                      className={`pdf-highlight ${activeHighlightId === highlight.id ? "active" : ""}`}
                      title={highlight.title}
                      style={{
                        left: x,
                        top: y,
                        width: Math.max(width, 8),
                        height: Math.max(height, 8),
                      }}
                    />
                  );
                })
            )}
          </div>
        ) : null}
        {pageSize.width && pageSize.height && selectableLines.length ? (
          <div className="pdf-line-layer">
            {selectableLines.map((line) => {
              const rect = line.rects[0];
              if (!rect) return null;
              const scaleX = pageSize.width / rect.page_width;
              const scaleY = pageSize.height / rect.page_height;
              const x = Math.min(rect.x0, rect.x1) * scaleX;
              const y = Math.min(rect.y0, rect.y1) * scaleY;
              const width = Math.abs(rect.x1 - rect.x0) * scaleX;
              const height = Math.abs(rect.y1 - rect.y0) * scaleY;
              return (
                <button
                  key={line.id}
                  type="button"
                  className="pdf-line-hitbox"
                  title={`Double-click to note: ${line.text}`}
                  style={{ left: x, top: y, width: Math.max(width, 18), height: Math.max(height, 10) }}
                  onDoubleClick={(event) => {
                    event.preventDefault();
                    onLineDoubleClick?.(line);
                  }}
                />
              );
            })}
          </div>
        ) : null}
      </div>
      {pageError ? <p className="pdf-page-error">{pageError}</p> : null}
      {highlights.length > 0 && highlights.every((highlight) => highlight.rects.length === 0) ? (
        <p className="pdf-page-error">Exact PDF coordinates were not available for this evidence. Page-level source is shown.</p>
      ) : null}
    </article>
  );
}

function renderHighlightedText(
  page: ReviewPageItem,
  highlights: CanvasHighlight[],
  activeHighlightId: string | null
) {
  const pageHighlights = highlights
    .filter(
      (highlight) =>
        highlight.page === page.page &&
        typeof highlight.start_char === "number" &&
        typeof highlight.end_char === "number" &&
        highlight.end_char > highlight.start_char
    )
    .sort((left, right) => (left.start_char ?? 0) - (right.start_char ?? 0));

  if (pageHighlights.length === 0) {
    return page.text;
  }

  const output: ReactNode[] = [];
  let cursor = 0;
  for (const highlight of pageHighlights) {
    const start = Math.max(cursor, Math.min(page.text.length, highlight.start_char ?? 0));
    const end = Math.max(start, Math.min(page.text.length, highlight.end_char ?? start));
    if (start > cursor) {
      output.push(page.text.slice(cursor, start));
    }
    output.push(
      <mark
        key={`${highlight.id}-${start}-${end}`}
        id={reviewHighlightId(highlight.id)}
        className={activeHighlightId === highlight.id ? "active" : ""}
        title={highlight.title}
      >
        {page.text.slice(start, end)}
      </mark>
    );
    cursor = end;
  }
  if (cursor < page.text.length) {
    output.push(page.text.slice(cursor));
  }
  return output;
}

function RisksView({ analysis, risksByLevel }: { analysis: AnalysisResponse | null; risksByLevel: Record<string, AnalysisRiskItem[]> }) {
  const [expandedRisk, setExpandedRisk] = useState<AnalysisRiskItem | null>(null);

  useEffect(() => {
    if (!expandedRisk) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setExpandedRisk(null);
      }
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      document.body.style.overflow = previousOverflow;
    };
  }, [expandedRisk]);

  if (!analysis) {
    return (
      <div className="summary-panel">
        <p className="eyebrow">Ready when you are</p>
        <h3>Upload and analyse a document to see legal risks in plain English.</h3>
        <p>The analyser will classify the document, extract clauses, identify risks, and attach sources.</p>
      </div>
    );
  }

  return (
    <section className="analysis-view">
      <div className="summary-panel">
        <p className="eyebrow">Plain-English summary</p>
        <h3>{analysis.risk_summary}</h3>
        {analysis.document_profile ? (
          <div className="profile-grid">
            <div><span>Document purpose</span><strong>{analysis.document_profile.purpose}</strong></div>
            <div><span>Likely reviewing role</span><strong>{analysis.document_profile.likely_user_role}</strong></div>
            <div><span>Likely stronger party</span><strong>{analysis.document_profile.stronger_party}</strong></div>
            <div><span>Detected parties</span><strong>{analysis.document_profile.detected_parties.length > 0 ? analysis.document_profile.detected_parties.join(" / ") : "Not found"}</strong></div>
            <div><span>Governing law</span><strong>{analysis.document_profile.governing_law ?? "Not found"}</strong></div>
          </div>
        ) : null}
        {analysis.document_classification ? (
          <div className="insight-box">
            <strong>Document classification</strong>
            <p>Primary: {prettyLabel(analysis.document_classification.primary_document_type)} | Confidence: {Math.round(analysis.document_classification.confidence_score * 100)}%</p>
            <p>{analysis.document_classification.is_template ? "Template/sample detected. " : ""}{analysis.document_classification.contains_multiple_document_types ? "Multiple document sections detected." : "Single-document analysis."}</p>
          </div>
        ) : null}
        {analysis.final_verdict ? <p><strong>Verdict:</strong> {analysis.final_verdict}</p> : null}
        {analysis.cuad_coverage?.enabled ? (
          <div className="insight-box">
            <strong>CUAD-backed clause knowledge</strong>
            <p>Using {analysis.cuad_coverage.contract_count} CUAD contracts, {analysis.cuad_coverage.cuad_label_count} expert clause labels, and {analysis.cuad_coverage.positive_answer_count} annotated answers.</p>
          </div>
        ) : null}
      </div>

      <div className="risk-columns">
        {(["critical", "high", "medium", "low"] as const).map((level) => (
          <div key={level} className="risk-lane">
            <div className="lane-heading"><span className={riskTone(level)}>{prettyLabel(level)}</span><strong>{analysis.risk_counts[level] ?? risksByLevel[level].length}</strong></div>
            {risksByLevel[level].length === 0 ? <p className="empty-copy">No {level} findings.</p> : risksByLevel[level].map((risk) => (
              <article key={`${risk.finding_id}-${risk.summary}`} className="risk-card">
                <div className="risk-card-top"><strong>{prettyLabel(risk.clause_type)}</strong><span>Page {risk.page} | Score {risk.risk_score}</span></div>
                <div className="verification-inline">
                  <span className={`verification-pill ${verificationTone(risk.verification?.status)}`}>
                    {verificationLabel(risk.verification?.status)}
                  </span>
                  {risk.verification ? (
                    <small>
                      {risk.verification.checks_passed}/{risk.verification.checks_total} checks
                    </small>
                  ) : null}
                </div>
                <p>{truncateText(risk.plain_language ?? risk.summary, 210)}</p>
                {risk.evidence ? <blockquote>{truncateText(risk.evidence, 180)}</blockquote> : null}
                <small>{truncateText(risk.suggested_question, 120)}</small>
                <button type="button" className="risk-expand-btn" onClick={() => setExpandedRisk(risk)}>
                  View details
                </button>
              </article>
            ))}
          </div>
        ))}
      </div>

      {expandedRisk
        ? createPortal(
        <div
          className="risk-modal-overlay"
          role="dialog"
          aria-modal="true"
          onClick={(event) => {
            if (event.target === event.currentTarget) {
              setExpandedRisk(null);
            }
          }}
        >
          <article className="risk-modal">
            <div className="risk-modal-head">
              <div>
                <p className="eyebrow">Risk detail</p>
                <h3>{prettyLabel(expandedRisk.clause_type)}</h3>
              </div>
              <button
                type="button"
                className="risk-modal-close"
                onClick={() => setExpandedRisk(null)}
                aria-label="Close details"
              >
                Close
              </button>
            </div>
            <div className="risk-modal-meta">
              <span className={riskTone(expandedRisk.risk_level)}>
                {prettyLabel(expandedRisk.risk_level)}
              </span>
              <span>Page {expandedRisk.page}</span>
              <span>Score {expandedRisk.risk_score}</span>
              <span>{prettyLabel(expandedRisk.risk_category)}</span>
              {expandedRisk.verification ? (
                <span className={`verification-pill ${verificationTone(expandedRisk.verification.status)}`}>
                  {verificationLabel(expandedRisk.verification.status)} ({expandedRisk.verification.checks_passed}/{expandedRisk.verification.checks_total})
                </span>
              ) : null}
            </div>
            <section className="risk-modal-section">
              <h4>Summary</h4>
              <p>{expandedRisk.plain_language ?? expandedRisk.summary}</p>
            </section>
            {expandedRisk.evidence ? (
              <section className="risk-modal-section">
                <h4>Evidence</h4>
                <blockquote>{expandedRisk.evidence}</blockquote>
              </section>
            ) : null}
            <section className="risk-modal-section">
              <h4>Suggested follow-up</h4>
              <p>{expandedRisk.suggested_question}</p>
            </section>
            {expandedRisk.verification?.status !== "verified" && expandedRisk.verification?.reasons?.length ? (
              <section className="risk-modal-section">
                <h4>Why review is needed</h4>
                <ul>
                  {expandedRisk.verification.reasons.map((reason, index) => (
                    <li key={`${reason}-${index}`}>{reason}</li>
                  ))}
                </ul>
              </section>
            ) : null}
          </article>
        </div>,
        document.body
      )
        : null}
    </section>
  );
}

function ClausesView({ clauses, selectedClauseDetail, onSelectClause }: { clauses: ClauseItem[]; selectedClauseDetail: ClauseDetailResponse | null; onSelectClause: (clauseId: number) => void }) {
  return (
    <section className="clause-view">
      <div className="clause-list">
        {clauses.map((clause) => (
          <button key={clause.id} type="button" onClick={() => onSelectClause(clause.id)} className={selectedClauseDetail?.id === clause.id ? "clause-row active" : "clause-row"}>
            <span>{prettyLabel(clause.clause_type)}</span>
            <small>{clause.clause_title}</small>
            <em className={riskTone(clause.risk_level)}>{clause.risk_level ?? "No major risk"}</em>
          </button>
        ))}
        {clauses.length === 0 ? <p className="empty-copy">No clauses loaded yet.</p> : null}
      </div>
      <div className="evidence-panel">
        {selectedClauseDetail ? (
          <>
            <p className="eyebrow">Source evidence</p>
            <h3>{selectedClauseDetail.clause_title}</h3>
            <p>Page {selectedClauseDetail.page_start} | {prettyLabel(selectedClauseDetail.clause_type)}</p>
            <blockquote>{selectedClauseDetail.clause_text}</blockquote>
            {selectedClauseDetail.risks.length > 0 ? selectedClauseDetail.risks.map((risk) => (
              <article key={risk.finding_id} className="finding-note">
                <strong>{risk.summary}</strong><span>{risk.why_risky}</span><small>{risk.suggested_question}</small>
              </article>
            )) : <p>No major deterministic risk was flagged for this clause.</p>}
          </>
        ) : <p className="empty-copy">Select a clause to inspect its source text.</p>}
      </div>
    </section>
  );
}

function ChatView(props: { busy: boolean; selectedDocumentId: string; question: string; setQuestion: (value: string) => void; onAsk: () => void; chatHistory: ChatResponse[] }) {
  return (
    <section className="chat-view">
      <div className="assistant-intro">
        <div><p className="eyebrow">Ask ClauseGuide</p><h3>Ask practical questions about this document.</h3><p>Answers use retrieved clauses and source evidence from the uploaded file.</p></div>
        <div className="prompt-row">
          {["Summarise this document for me.", "What are the top risks before signing?", "Which clauses need negotiation?"].map((prompt) => (
            <button key={prompt} type="button" onClick={() => props.setQuestion(prompt)}>{prompt}</button>
          ))}
        </div>
      </div>
      <div className="question-box">
        <textarea value={props.question} onChange={(event) => props.setQuestion(event.target.value)} placeholder="Ask about risk, payment, termination, penalties, missing clauses, or any term in this document." />
        <button type="button" disabled={props.busy || !props.selectedDocumentId || !props.question.trim()} onClick={() => props.onAsk()}>Ask ClauseGuide</button>
      </div>
      <div className="chat-list">
        {props.chatHistory.map((entry, index) => (
          <article key={`${entry.session_id}-${index}`} className="chat-answer">
            <p>{entry.answer}</p>
            <div className="chat-meta">
              <span>{confidenceLabel(entry.confidence_score)}</span>
              <span>{prettyLabel(entry.intent)}</span>
              <span>{entry.disclaimer}</span>
              {entry.verification ? (
                <span className={`verification-pill ${verificationTone(entry.verification.status)}`}>
                  {verificationLabel(entry.verification.status)}
                </span>
              ) : null}
            </div>
            {entry.verification && entry.verification.status !== "verified" && entry.verification.reasons.length > 0 ? (
              <ul>
                {entry.verification.reasons.map((reason, reasonIndex) => (
                  <li key={`${reason}-${reasonIndex}`}>{reason}</li>
                ))}
              </ul>
            ) : null}
            {entry.sources.length > 0 ? <ul>{entry.sources.map((source, sourceIndex) => <li key={`${source.page}-${sourceIndex}`}>Page {source.page}: {source.evidence}</li>)}</ul> : null}
          </article>
        ))}
        {props.chatHistory.length === 0 ? <p className="empty-copy">Your answers will appear here with source evidence.</p> : null}
      </div>
    </section>
  );
}

function ReportsView(props: { busy: boolean; selectedDocumentId: string; reports: ReportListItem[]; latestEvaluation: EvaluationRunResponse | null; evaluationRuns: EvaluationRunListItem[]; useRagasEval: boolean; setUseRagasEval: (value: boolean) => void; onGenerateReport: (format: "markdown" | "text") => void; onRunEvaluation: () => void; onDownloadReport: (report: ReportListItem) => void }) {
  return (
    <section className="reports-view">
      <div className="report-actions">
        <button type="button" disabled={props.busy || !props.selectedDocumentId} onClick={() => props.onGenerateReport("markdown")}>Generate Markdown</button>
        <button type="button" disabled={props.busy || !props.selectedDocumentId} onClick={() => props.onGenerateReport("text")}>Generate Text</button>
        <button type="button" disabled={props.busy || !props.selectedDocumentId} onClick={props.onRunEvaluation}>Run Quality Check</button>
        <label><input type="checkbox" checked={props.useRagasEval} disabled={props.busy} onChange={(event) => props.setUseRagasEval(event.target.checked)} /> RAGAS</label>
      </div>
      <div className="report-grid">
        {props.reports.map((report) => (
          <button key={report.report_id} type="button" className="report-download-card" onClick={() => props.onDownloadReport(report)}>
            <strong>{report.file_name}</strong><span>{report.report_format} | {new Date(report.created_at).toLocaleString()}</span>
          </button>
        ))}
        {props.reports.length === 0 ? <p className="empty-copy">No generated reports yet.</p> : null}
      </div>
      {props.latestEvaluation ? (
        <div className="quality-panel"><strong>Latest quality check</strong><span>{props.latestEvaluation.metrics.total_cases} cases | citation match {props.latestEvaluation.metrics.citation_exact_match_score.toFixed(2)} | answer relevance {props.latestEvaluation.metrics.answer_relevancy_score?.toFixed(2) ?? "n/a"}</span></div>
      ) : props.evaluationRuns.length > 0 ? (
        <div className="quality-panel"><strong>Previous quality checks</strong><span>{props.evaluationRuns.length} runs available for this document.</span></div>
      ) : null}
    </section>
  );
}

export default App;
