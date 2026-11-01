export interface AuthResponse {
  access_token: string;
  token_type: string;
}

export interface SampleTest {
  ordinal: number;
  input: string;
  expected_output: string;
}

export interface Problem {
  id: number;
  title: string;
  statement: string;
  time_limit_ms: number;
  memory_limit_mb: number;
  sample_tests: SampleTest[];
}

export interface TestResult {
  ordinal: number;
  verdict: string;
  wall_ms: number;
  cpu_ms: number;
  memory_kb: number;
  exit_code: number;
}

export interface SubmissionSummary {
  id: string;
  problem_id: number;
  language_id: string;
  status: string;
  verdict: string | null;
  max_time_ms: number | null;
  max_memory_kb: number | null;
  created_at: string;
}

export interface Submission extends SubmissionSummary {
  user_id: number;
  detail: string | null;
  max_cpu_ms: number | null;
  finished_at: string | null;
  test_results: TestResult[];
}

export interface StatsSummary {
  total: number;
  completed: number;
  pass_rate: number;
  verdicts: Record<string, number>;
  median_time_ms: number | null;
  p95_time_ms: number | null;
  median_cpu_ms: number | null;
  p95_cpu_ms: number | null;
  median_memory_kb: number | null;
  p95_memory_kb: number | null;
}

export class ApiError extends Error {
  status: number;
  retryAfter?: number;

  constructor(message: string, status: number, retryAfter?: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.retryAfter = retryAfter;
  }
}

const API_BASE_URL = (import.meta.env.VITE_API_URL || 'http://localhost:8000/api').replace(/\/$/, '');
const TOKEN_KEY = 'codejudge.access_token';

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = localStorage.getItem(TOKEN_KEY);
  const headers = new Headers(init.headers);
  headers.set('Accept', 'application/json');
  if (init.body) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers });
  } catch {
    const message = 'Cannot connect to the CodeJudge API. Check that the backend is running.';
    window.dispatchEvent(new CustomEvent('codejudge:notice', { detail: { message, tone: 'error' } }));
    throw new ApiError(message, 0);
  }

  if (response.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem('codejudge.user_email');
    window.dispatchEvent(new Event('codejudge:unauthorized'));
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown };
    const detail = typeof body.detail === 'string'
      ? body.detail
      : Array.isArray(body.detail)
        ? body.detail.map((issue: { msg?: string }) => issue.msg).filter(Boolean).join(', ')
        : response.statusText;
    const retrySeconds = Number(response.headers.get('Retry-After'));
    const retryAfter = Number.isFinite(retrySeconds) && retrySeconds > 0 ? retrySeconds : undefined;
    const message = response.status === 429
      ? `Rate limit reached. Try again${retryAfter ? ` in ${retryAfter} seconds` : ' shortly'}.`
      : detail || (response.status === 401 ? 'Please sign in again.' : `Request failed (${response.status}).`);
    if (response.status === 429) {
      window.dispatchEvent(new CustomEvent('codejudge:notice', { detail: { message, tone: 'error' } }));
    }
    throw new ApiError(message, response.status, retryAfter);
  }
  return response.json() as Promise<T>;
}

export const api = {
  register: (email: string, password: string) =>
    request<AuthResponse>('/auth/register', { method: 'POST', body: JSON.stringify({ email, password }) }),
  login: (email: string, password: string) =>
    request<AuthResponse>('/auth/login', { method: 'POST', body: JSON.stringify({ email, password }) }),
  getProblems: () => request<Problem[]>('/problems'),
  getProblem: (id: string) => request<Problem>(`/problems/${encodeURIComponent(id)}`),
  createSubmission: (payload: { problem_id: number; language_id: string; source_code: string }) =>
    request<{ id: string; status: string }>('/submissions', { method: 'POST', body: JSON.stringify(payload) }),
  getSubmission: (id: string) => request<Submission>(`/submissions/${encodeURIComponent(id)}`),
  getSubmissions: () => request<SubmissionSummary[]>('/submissions?limit=100'),
  getStats: () => request<StatsSummary>('/stats/summary'),
};
