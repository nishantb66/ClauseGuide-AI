export interface VerificationCheck {
  check: string;
  passed: boolean;
  detail: string;
}

export interface VerificationResult {
  status: "verified" | "needs_review" | string;
  score: number;
  checks_total: number;
  checks_passed: number;
  failed_checks: string[];
  reasons: string[];
  checks: VerificationCheck[];
}

export interface DocumentSummary {
  id: string;
  title: string;
  file_name: string;
  file_type: string;
  contract_type: string | null;
  status: string;
  total_pages: number;
  uploaded_at: string;
  processed_at: string | null;
}

export interface ProcessResponse {
  document_id: string;
  status: string;
  contract_type: string;
  total_pages: number;
  total_chunks: number;
  clauses_extracted: number;
  risk_findings: number;
}

export interface AnalysisRiskItem {
  finding_id: number | null;
  clause_type: string;
  clause_id: number | null;
  risk_level: string;
  risk_score: number;
  risk_category: string;
  summary: string;
  why_risky: string;
  suggested_question: string;
  page: number;
  evidence?: string | null;
  plain_language?: string | null;
  verification?: VerificationResult | null;
}

export interface ExtractionHealth {
  clauses_found: number;
  risks_found: number;
  source_pages: number[];
  note: string;
}

export interface AnalysisResponse {
  contract_type: string;
  contract_type_label: string;
  document_profile?: {
    purpose: string;
    likely_user_role: string;
    stronger_party: string;
    detected_parties: string[];
    party_roles: Array<{
      name: string;
      role: string;
      side: string;
      is_placeholder: boolean;
    }>;
    governing_law: string | null;
  } | null;
  document_classification?: {
    primary_document_type: string;
    secondary_document_types: string[];
    is_template: boolean;
    is_executed_agreement: boolean;
    is_collection_or_handbook: boolean;
    contains_multiple_document_types: boolean;
    confidence_score: number;
    sections: Array<{
      document_type: string;
      title: string;
      page_start: number;
      page_end: number;
      confidence_score: number;
    }>;
  } | null;
  overall_risk_level: string;
  overall_risk_score: number;
  risk_summary: string;
  risk_counts: Record<string, number>;
  missing_clauses: string[];
  review_clauses: string[];
  false_positive_checks: string[];
  review_focus: string[];
  cuad_coverage?: {
    enabled: boolean;
    source: string;
    license: string;
    contract_count: number;
    cuad_label_count: number;
    positive_answer_count: number;
    mapped_clause_types_detected: string[];
  } | null;
  jurisdiction_warnings: Array<{
    id: string;
    warning: string;
    recommended_check: string;
  }>;
  benchmark_notes: Array<{
    id: string;
    document_types: string[];
    normal_structure: string[];
    red_flags: string[];
  }>;
  final_verdict?: string | null;
  verification_summary?: {
    verified_count: number;
    needs_review_count: number;
    verification_rate: number;
  } | null;
  top_risks: AnalysisRiskItem[];
  extraction_health: ExtractionHealth;
}

export interface ClauseItem {
  id: number;
  clause_type: string;
  clause_title: string;
  page_start: number;
  page_end: number;
  confidence_score: number;
  risk_level: string | null;
  risk_score: number | null;
  risk_summary: string | null;
}

export interface ClauseListResponse {
  document_id: string;
  clauses: ClauseItem[];
}

export interface ClauseRiskItem {
  finding_id: number;
  risk_category: string;
  risk_level: string;
  risk_score: number;
  summary: string;
  why_risky: string;
  suggested_question: string;
  page_number: number | null;
}

export interface ClauseDetailResponse {
  id: number;
  document_id: string;
  clause_type: string;
  clause_title: string;
  clause_text: string;
  normalized_text: string;
  page_start: number;
  page_end: number;
  confidence_score: number;
  risks: ClauseRiskItem[];
}

export interface ChatResponse {
  answer: string;
  confidence_score: number;
  confidence_label: string;
  sources: Array<{
    page: number;
    clause_type: string;
    evidence: string;
  }>;
  disclaimer: string;
  intent: string;
  required_clause_types: string[];
  session_id: string;
  verification?: VerificationResult | null;
}

export interface HighlightRect {
  page: number;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  page_width: number;
  page_height: number;
}

export interface PdfLineItem {
  id: string;
  page: number;
  text: string;
  rects: HighlightRect[];
}

export interface TextHighlight {
  page: number;
  statement: string;
  start_char: number | null;
  end_char: number | null;
  match_confidence: number;
  rects: HighlightRect[];
}

export interface ReviewRiskItem {
  finding_id: number;
  clause_id: number | null;
  clause_type: string;
  risk_category: string;
  risk_level: string;
  risk_score: number;
  title: string;
  summary: string;
  why_risky: string;
  suggested_question: string;
  page: number;
  evidence: string;
  highlight: TextHighlight | null;
  verification?: VerificationResult | null;
}

export interface ReviewPageItem {
  page: number;
  text: string;
}

export interface ReviewWorkspaceResponse {
  document_id: string;
  title: string;
  file_name: string;
  file_type: string;
  total_pages: number;
  file_url: string;
  canvas_mode: string;
  risks: ReviewRiskItem[];
  pages: ReviewPageItem[];
}

export interface ImportantPointItem {
  id: string;
  title: string;
  reason: string;
  action: string;
  risk_level: string;
  risk_score: number;
  page: number;
  source_finding_id: number | null;
  highlight: TextHighlight | null;
  verification?: VerificationResult | null;
}

export interface ImportantPointsResponse {
  document_id: string;
  title: string;
  file_name: string;
  file_type: string;
  total_pages: number;
  file_url: string;
  canvas_mode: string;
  points: ImportantPointItem[];
  pages: ReviewPageItem[];
}

export interface MarkdownNoteItem {
  id: string;
  workspace_id: string;
  page_number: number;
  selected_text: string;
  rects: HighlightRect[];
  note_html: string;
  note_markdown: string;
  color: string;
  created_at: string;
  updated_at: string;
}

export interface MarkdownWorkspaceItem {
  id: string;
  title: string;
  document_id: string | null;
  document_title: string | null;
  file_name: string | null;
  file_type: string | null;
  file_url: string | null;
  total_pages: number;
  notes_count: number;
  created_at: string;
  updated_at: string;
}

export interface MarkdownWorkspaceDetail extends MarkdownWorkspaceItem {
  notes: MarkdownNoteItem[];
  lines: PdfLineItem[];
}

export interface ReportGenerateResponse {
  report_id: string;
  document_id: string;
  report_format: string;
  file_name: string;
  download_url: string;
  created_at: string;
}

export interface ReportListItem {
  report_id: string;
  report_format: string;
  file_name: string;
  download_url: string;
  created_at: string;
}

export interface ReportListResponse {
  document_id: string;
  reports: ReportListItem[];
}

export interface EvaluationTestCase {
  question: string;
  expected_answer?: string | null;
  expected_source_page?: number | null;
  expected_clause_type?: string | null;
  expected_risk_level?: string | null;
}

export interface EvaluationMetricsSummary {
  total_cases: number;
  ragas_enabled: boolean;
  ragas_applied: boolean;

  faithfulness_score: number | null;
  answer_relevancy_score: number | null;
  context_precision_score: number | null;
  context_recall_score: number | null;

  amount_accuracy_score: number;
  date_accuracy_score: number;
  clause_classification_score: number;
  risk_level_accuracy_score: number;
  citation_exact_match_score: number;
  unsupported_refusal_score: number;
}

export interface EvaluationResultItem {
  question: string;
  expected_answer: string | null;
  actual_answer: string;

  faithfulness_score: number | null;
  answer_relevancy_score: number | null;
  context_precision_score: number | null;
  context_recall_score: number | null;

  amount_accuracy_score: number;
  date_accuracy_score: number;
  clause_classification_score: number;
  risk_level_accuracy_score: number;
  citation_exact_match_score: number;
  unsupported_refusal_score: number;
}

export interface EvaluationRunResponse {
  run_id: string;
  document_id: string;
  run_label: string;
  created_at: string;
  metrics: EvaluationMetricsSummary;
  results: EvaluationResultItem[];
}

export interface EvaluationRunListItem {
  run_id: string;
  run_label: string;
  created_at: string;
  metrics: EvaluationMetricsSummary;
}

export interface EvaluationRunListResponse {
  document_id: string;
  runs: EvaluationRunListItem[];
}

export interface UserProfile {
  id: string;
  email: string;
  full_name: string | null;
  auth_provider: string;
  is_email_verified: boolean;
  created_at: string;
  last_login_at: string | null;
}

export interface AuthResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: UserProfile;
}

export interface RegisterResponse {
  user_id: string;
  email: string;
  otp_required: boolean;
  message: string;
}

export interface DashboardStats {
  documents_uploaded: number;
  documents_analyzed: number;
  total_risks_detected: number;
  high_or_critical_risks: number;
  clauses_read: number;
  reports_generated: number;
  average_risk_score: number;
  latest_documents: Array<{
    id: string;
    title: string;
    contract_type: string | null;
    status: string;
    total_pages: number;
    uploaded_at: string;
    processed_at: string | null;
  }>;
  risk_level_breakdown: Record<string, number>;
}
