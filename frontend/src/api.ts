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

export interface BatchDraftItem {
  problem_id: number;
  language_id: 'python3' | 'cpp17';
  source_code: string;
  sample_id?: string;
}

export interface BatchCreateResponse {
  id: string;
  total: number;
  status: string;
}

export interface BatchSummary {
  id: string;
  name: string | null;
  model_name: string | null;
  total: number;
  status: string;
  created_at: string;
  finished_at: string | null;
  counts: Record<string, number>;
  verdicts: Record<string, number>;
  completed: number;
  percent: number;
  started_at: string | null;
  throughput: number;
  eta_seconds: number | null;
  max_wall_ms: number | null;
  median_wall_ms: number | null;
  p95_wall_ms: number | null;
  max_memory_kb: number | null;
  median_memory_kb: number | null;
  p95_memory_kb: number | null;
}

export interface BatchListItem {
  id: string;
  name: string | null;
  model_name: string | null;
  total: number;
  status: string;
  created_at: string;
  finished_at: string | null;
  counts: Record<string, number>;
  verdicts: Record<string, number>;
}

export interface BatchItem {
  id: string;
  problem_id: number;
  problem_title: string;
  language_id: string;
  sample_id: string | null;
  repeat_index: number;
  status: string;
  verdict: string | null;
  wall_ms: number | null;
  cpu_ms: number | null;
  memory_kb: number | null;
  detail: string | null;
  created_at: string;
  queued_at: string;
  started_at: string | null;
  finished_at: string | null;
  source_code?: string;
}

export interface BatchItemsResponse {
  items: BatchItem[];
  total: number;
  limit: number;
  offset: number;
}

export interface BatchListResponse {
  items: BatchListItem[];
  total: number;
  limit: number;
  offset: number;
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
    const detail = formatApiDetail(body.detail, response.statusText);
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

function formatApiDetail(detail: unknown, fallback: string): string {
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map((issue: unknown) => {
      if (!issue || typeof issue !== 'object') return String(issue);
      const item = issue as { index?: number; field?: string; message?: string; msg?: string };
      const message = item.message ?? item.msg ?? '';
      return item.index == null
        ? message
        : `Item ${item.index + 1}${item.field ? ` (${item.field})` : ''}: ${message}`;
    }).filter(Boolean).join('; ') || fallback;
  }
  if (detail && typeof detail === 'object') {
    const errors = (detail as { errors?: unknown }).errors;
    if (Array.isArray(errors)) return formatApiDetail(errors, fallback);
  }
  return fallback;
}

async function exportBatchCsv(batchId: string): Promise<Blob> {
  const token = localStorage.getItem(TOKEN_KEY);
  const headers = new Headers({ Accept: 'text/csv' });
  if (token) headers.set('Authorization', `Bearer ${token}`);

  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/batches/${encodeURIComponent(batchId)}/export.csv`, { headers });
  } catch {
    throw new ApiError('Cannot connect to the CodeJudge API. Check that the backend is running.', 0);
  }
  if (response.status === 401) {
    localStorage.removeItem(TOKEN_KEY);
    localStorage.removeItem('codejudge.user_email');
    window.dispatchEvent(new Event('codejudge:unauthorized'));
  }
  if (!response.ok) {
    const body = await response.json().catch(() => ({})) as { detail?: unknown };
    const retrySeconds = Number(response.headers.get('Retry-After'));
    const retryAfter = Number.isFinite(retrySeconds) && retrySeconds > 0 ? retrySeconds : undefined;
    const detail = formatApiDetail(body.detail, response.statusText);
    const message = response.status === 429
      ? `Rate limit reached. Try again${retryAfter ? ` in ${retryAfter} seconds` : ' shortly'}.`
      : detail || (response.status === 401 ? 'Please sign in again.' : `Request failed (${response.status}).`);
    throw new ApiError(message, response.status, retryAfter);
  }
  return response.blob();
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
  createBatch: (payload: { name?: string; model_name?: string; repeats: number; items: BatchDraftItem[] }) =>
    request<BatchCreateResponse>('/batches', { method: 'POST', body: JSON.stringify(payload) }),
  getBatches: (limit = 50, offset = 0) =>
    request<BatchListResponse>(`/batches?limit=${limit}&offset=${offset}`),
  getBatch: (id: string) => request<BatchSummary>(`/batches/${encodeURIComponent(id)}`),
  getBatchItems: (
    id: string,
    params: {
      limit?: number;
      offset?: number;
      verdict?: string;
      status?: string;
      problem_id?: number;
      language_id?: string;
      sort?: string;
      include_code?: boolean;
    } = {},
  ) => {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== '') query.set(key, String(value));
    });
    const suffix = query.size ? `?${query.toString()}` : '';
    return request<BatchItemsResponse>(`/batches/${encodeURIComponent(id)}/items${suffix}`);
  },
  cancelBatch: (id: string) =>
    request<{ id: string; status: string; cancelled: number; running: number }>(
      `/batches/${encodeURIComponent(id)}/cancel`,
      { method: 'POST' },
    ),
  rerunFailedBatch: (id: string) =>
    request<BatchCreateResponse>(`/batches/${encodeURIComponent(id)}/rerun-failed`, { method: 'POST' }),
  exportBatchCsv,
};
