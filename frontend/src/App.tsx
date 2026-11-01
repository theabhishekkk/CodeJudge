import { useEffect, useMemo, useState } from 'react';
import {
  Link,
  Navigate,
  Route,
  Routes,
  useNavigate,
  useParams,
} from 'react-router-dom';
import {
  ApiError,
  api,
  type Problem,
  type StatsSummary,
  type Submission,
  type SubmissionSummary,
} from './api';
import { useAuth } from './auth';
import { useNotice } from './notice';

const PYTHON_STARTER = `import sys\n\n\ndef solve():\n    data = sys.stdin.read().strip().split()\n    # TODO: implement your solution\n    print(data)\n\n\nif __name__ == "__main__":\n    solve()\n`;
const CPP_STARTER = `#include <iostream>\nusing namespace std;\n\nint main() {\n    // Read input, solve the problem, and print the answer\n    return 0;\n}\n`;

function PageTitle({ eyebrow, children }: { eyebrow?: string; children: string }) {
  return (
    <div className="page-title">
      {eyebrow && <p className="eyebrow">{eyebrow}</p>}
      <h1>{children}</h1>
    </div>
  );
}

function Loading({ label = 'Loading…' }: { label?: string }) {
  return <div className="loading" role="status">{label}</div>;
}

function EmptyState({ children }: { children: string }) {
  return <div className="empty-state">{children}</div>;
}

function VerdictBadge({ verdict, status }: { verdict?: string | null; status?: string }) {
  const label = verdict ?? status ?? 'PENDING';
  const tone =
    label === 'AC' ? 'success'
      : label === 'WA' || label === 'RE' ? 'danger'
        : label === 'TLE' || label === 'MLE' ? 'warning'
          : 'neutral';
  return <span className={`badge badge-${tone}`}>{label}</span>;
}

function AppLayout() {
  const { user, logout } = useAuth();
  const { notice, dismiss, showNotice } = useNotice();
  const navigate = useNavigate();

  useEffect(() => {
    const handleUnauthorized = () => {
      logout();
      navigate('/login', { replace: true });
    };
    const handleApiNotice = (event: Event) => {
      const noticeEvent = event as CustomEvent<{ message: string; tone?: 'success' | 'error' | 'info' }>;
      showNotice(noticeEvent.detail.message, noticeEvent.detail.tone ?? 'error');
    };
    window.addEventListener('codejudge:unauthorized', handleUnauthorized);
    window.addEventListener('codejudge:notice', handleApiNotice);
    return () => {
      window.removeEventListener('codejudge:unauthorized', handleUnauthorized);
      window.removeEventListener('codejudge:notice', handleApiNotice);
    };
  }, [logout, navigate, showNotice]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <Link className="brand" to="/problems" aria-label="CodeJudge home">
          <span className="brand-mark">&lt;/&gt;</span>
          <span>Code<span className="brand-accent">Judge</span></span>
        </Link>
        <nav className="nav-links" aria-label="Main navigation">
          {user ? (
            <>
              <Link to="/problems">Problems</Link>
              <Link to="/submissions">Submissions</Link>
              <Link to="/dashboard">Dashboard</Link>
              <span className="user-email">{user.email}</span>
              <button className="button button-quiet button-small" onClick={logout}>Logout</button>
            </>
          ) : (
            <>
              <Link to="/login">Sign in</Link>
              <Link className="button button-primary button-small" to="/register">Create account</Link>
            </>
          )}
        </nav>
      </header>
      {notice && (
        <div className={`notice notice-${notice.tone}`} role="alert">
          <span>{notice.message}</span>
          <button className="notice-close" aria-label="Dismiss notification" onClick={dismiss}>×</button>
        </div>
      )}
      <main className="main-content">
        <Routes>
          <Route path="/" element={<Navigate to={user ? '/problems' : '/login'} replace />} />
          <Route path="/login" element={user ? <Navigate to="/problems" replace /> : <AuthPage mode="login" />} />
          <Route path="/register" element={user ? <Navigate to="/problems" replace /> : <AuthPage mode="register" />} />
          <Route path="/problems" element={<RequireAuth><ProblemsPage /></RequireAuth>} />
          <Route path="/problem/:id" element={<RequireAuth><ProblemPage /></RequireAuth>} />
          <Route path="/submissions" element={<RequireAuth><SubmissionsPage /></RequireAuth>} />
          <Route path="/submissions/:id" element={<RequireAuth><SubmissionPage /></RequireAuth>} />
          <Route path="/dashboard" element={<RequireAuth><DashboardPage /></RequireAuth>} />
          <Route path="/stats" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </main>
      <footer className="footer">CodeJudge <span>·</span> Research-grade code evaluation</footer>
    </div>
  );
}

function RequireAuth({ children }: { children: React.ReactNode }) {
  const { user } = useAuth();
  return user ? <>{children}</> : <Navigate to="/login" replace />;
}

function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const isRegister = mode === 'register';
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const { login } = useAuth();
  const { showNotice } = useNotice();
  const navigate = useNavigate();

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError('');
    setSubmitting(true);
    try {
      const response = isRegister
        ? await api.register(email, password)
        : await api.login(email, password);
      login(response.access_token, email);
      showNotice(isRegister ? 'Account created. You are signed in.' : 'Welcome back.', 'success');
      navigate('/problems', { replace: true });
    } catch (cause) {
      const message = cause instanceof ApiError
        ? cause.message
        : 'Unable to reach CodeJudge. Check your connection and try again.';
      setError(message);
      showNotice(message, 'error');
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <section className="auth-layout">
      <div className="auth-intro">
        <p className="eyebrow">A reliable benchmark for generated code</p>
        <h1>Write code.<br /><span>Prove it works.</span></h1>
        <p className="muted-copy">Submit solutions against isolated test cases and inspect reproducible verdicts, runtimes, and memory use.</p>
        <div className="auth-points">
          <span><i /> Fresh sandbox for each test</span>
          <span><i /> Hidden tests stay private</span>
          <span><i /> Python 3 and C++17</span>
        </div>
      </div>
      <div className="card auth-card">
        <div className="card-heading">
          <p className="eyebrow">{isRegister ? 'Get started' : 'Welcome back'}</p>
          <h2>{isRegister ? 'Create your account' : 'Sign in to CodeJudge'}</h2>
          <p className="muted-copy">{isRegister ? 'Your account is ready in a few seconds.' : 'Continue evaluating solutions and benchmarks.'}</p>
        </div>
        <form className="form-stack" onSubmit={handleSubmit}>
          <label className="field">
            <span>Email</span>
            <input
              autoComplete="email"
              type="email"
              value={email}
              onChange={(event) => setEmail(event.target.value)}
              placeholder="you@example.com"
              required
            />
          </label>
          <label className="field">
            <span>Password</span>
            <input
              autoComplete={isRegister ? 'new-password' : 'current-password'}
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder={isRegister ? 'At least 6 characters' : 'Your password'}
              minLength={6}
              required
            />
          </label>
          {error && <p className="inline-error" role="alert">{error}</p>}
          <button className="button button-primary button-full" type="submit" disabled={submitting}>
            {submitting ? 'Please wait…' : isRegister ? 'Create account' : 'Sign in'}
          </button>
        </form>
        <p className="auth-switch">
          {isRegister ? 'Already have an account?' : 'New to CodeJudge?'}{' '}
          <Link to={isRegister ? '/login' : '/register'}>{isRegister ? 'Sign in' : 'Create an account'}</Link>
        </p>
      </div>
    </section>
  );
}

function ProblemsPage() {
  const [problems, setProblems] = useState<Problem[] | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api.getProblems().then(setProblems).catch((cause: unknown) => setError(errorMessage(cause)));
  }, []);

  return (
    <>
      <PageTitle eyebrow="Problem set">Choose a challenge</PageTitle>
      <p className="section-lead">Practice with a curated set of algorithmic problems. Every submission is tested in an isolated container.</p>
      {error ? <EmptyState>{error}</EmptyState> : problems === null ? <Loading label="Loading problems…" /> : (
        <div className="problem-grid">
          {problems.map((problem, index) => (
            <Link className="card problem-card" to={`/problem/${problem.id}`} key={problem.id}>
              <div className="problem-card-top">
                <span className="problem-index">{String(index + 1).padStart(2, '0')}</span>
                <span className="difficulty">Practice</span>
              </div>
              <h2>{problem.title}</h2>
              <p>{problem.statement}</p>
              <div className="problem-meta">
                <span>{problem.time_limit_ms} ms</span>
                <span>{problem.memory_limit_mb} MB</span>
              </div>
            </Link>
          ))}
        </div>
      )}
    </>
  );
}

function ProblemPage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { showNotice } = useNotice();
  const [problem, setProblem] = useState<Problem | null>(null);
  const [language, setLanguage] = useState<'python3' | 'cpp17'>('python3');
  const [source, setSource] = useState(PYTHON_STARTER);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!id) return;
    setProblem(null);
    setError('');
    api.getProblem(id)
      .then(setProblem)
      .catch((cause: unknown) => setError(errorMessage(cause)));
  }, [id]);

  function changeLanguage(next: 'python3' | 'cpp17') {
    setLanguage(next);
    setSource(next === 'python3' ? PYTHON_STARTER : CPP_STARTER);
  }

  async function submitSolution() {
    if (!id || !source.trim()) {
      setError('Add your solution before submitting.');
      return;
    }
    setSubmitting(true);
    setError('');
    try {
      const submission = await api.createSubmission({
        problem_id: Number(id),
        language_id: language,
        source_code: source,
      });
      showNotice('Submission queued. Results will update automatically.', 'success');
      navigate(`/submissions/${submission.id}`);
    } catch (cause) {
      const message = errorMessage(cause);
      setError(message);
      showNotice(message, 'error');
    } finally {
      setSubmitting(false);
    }
  }

  if (error && !problem) return <EmptyState>{error}</EmptyState>;
  if (!problem) return <Loading label="Loading problem…" />;

  return (
    <>
      <Link className="back-link" to="/problems">← All problems</Link>
      <div className="problem-layout">
        <section className="problem-description">
          <PageTitle eyebrow={`Problem #${problem.id}`}>{problem.title}</PageTitle>
          <div className="problem-limits">
            <span><strong>{problem.time_limit_ms} ms</strong> time limit</span>
            <span><strong>{problem.memory_limit_mb} MB</strong> memory limit</span>
          </div>
          <article className="card statement-card">
            <h2>Problem statement</h2>
            <p className="statement-text">{problem.statement}</p>
            {problem.sample_tests.length > 0 && (
              <div className="sample-list">
                <h3>Sample tests</h3>
                {problem.sample_tests.map((sample) => (
                  <div className="sample-case" key={sample.ordinal}>
                    <span className="sample-label">Sample {sample.ordinal}</span>
                    <div className="sample-columns">
                      <div><span>Input</span><pre>{sample.input}</pre></div>
                      <div><span>Output</span><pre>{sample.expected_output}</pre></div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </article>
        </section>
        <section className="card editor-card" aria-label="Code editor">
          <div className="editor-toolbar">
            <label htmlFor="language" className="sr-only">Programming language</label>
            <select id="language" value={language} onChange={(event) => changeLanguage(event.target.value as 'python3' | 'cpp17')}>
              <option value="python3">Python 3</option>
              <option value="cpp17">C++17</option>
            </select>
            <span className="editor-hint">UTF-8 · {source.split('\n').length} lines</span>
          </div>
          <div className="editor-body">
            <div className="line-numbers" aria-hidden="true">
              {source.split('\n').map((_, index) => <span key={index}>{index + 1}</span>)}
            </div>
            <label htmlFor="source-code" className="sr-only">Solution source code</label>
            <textarea
              id="source-code"
              className="code-editor"
              spellCheck={false}
              autoCapitalize="off"
              autoCorrect="off"
              value={source}
              onChange={(event) => setSource(event.target.value)}
              aria-label="Solution source code"
            />
          </div>
          <div className="editor-footer">
            {error && <p className="inline-error" role="alert">{error}</p>}
            <button className="button button-primary" onClick={submitSolution} disabled={submitting}>
              {submitting ? 'Submitting…' : '▶ Submit solution'}
            </button>
          </div>
        </section>
      </div>
    </>
  );
}

function SubmissionPage() {
  const { id } = useParams();
  const [submission, setSubmission] = useState<Submission | null>(null);
  const [problemTitle, setProblemTitle] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (!id) return undefined;
    let active = true;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await api.getSubmission(id);
        if (!active) return;
        setSubmission(next);
        setError('');
        if (next.status !== 'COMPLETED' && next.status !== 'ERROR') {
          timeout = setTimeout(poll, 1000);
        }
      } catch (cause) {
        if (!active) return;
        setError(errorMessage(cause));
        timeout = setTimeout(poll, 1000);
      }
    };
    void poll();
    return () => {
      active = false;
      if (timeout) clearTimeout(timeout);
    };
  }, [id]);

  useEffect(() => {
    if (!submission?.problem_id) return;
    api.getProblem(String(submission.problem_id))
      .then((problem) => setProblemTitle(problem.title))
      .catch(() => undefined);
  }, [submission?.problem_id]);

  if (error && !submission) return <EmptyState>{error}</EmptyState>;
  if (!submission) return <Loading label="Loading submission…" />;
  const completed = submission.status === 'COMPLETED' || submission.status === 'ERROR';

  return (
    <>
      <Link className="back-link" to="/submissions">← My submissions</Link>
      <div className="detail-heading">
        <div>
          <p className="eyebrow">Submission result</p>
          <h1>{problemTitle || `Problem #${submission.problem_id}`}</h1>
          <p className="muted-copy mono-text">{submission.id}</p>
        </div>
        <VerdictBadge verdict={submission.verdict} status={submission.status} />
      </div>
      {error && <div className="notice notice-error" role="status">{error} Retrying…</div>}
      {!completed && <div className="progress-banner"><span className="spinner" /> Your solution is running in a sandbox. This page refreshes automatically.</div>}
      {submission.detail && <div className={submission.status === 'ERROR' ? 'notice notice-error' : 'notice notice-info'}>{submission.detail}</div>}
      <div className="metric-grid">
        <Metric label="Wall time" value={formatMetric(submission.max_time_ms, 'ms')} />
        <Metric label="CPU time" value={formatMetric(submission.max_cpu_ms, 'ms')} />
        <Metric label="Peak memory" value={formatMetric(submission.max_memory_kb, 'KB')} />
        <Metric label="Submitted" value={formatDate(submission.created_at)} />
      </div>
      <section className="card table-card">
        <div className="table-heading"><div><p className="eyebrow">Execution</p><h2>Test case results</h2></div><span className="muted-copy">{submission.test_results.length} completed</span></div>
        {submission.test_results.length === 0 ? <EmptyState>Test results will appear here when the worker finishes.</EmptyState> : (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Test</th><th>Status</th><th>Wall time</th><th>CPU time</th><th>Memory</th></tr></thead>
              <tbody>
                {submission.test_results.map((test) => (
                  <tr key={test.ordinal}>
                    <td>Case {test.ordinal}</td>
                    <td><VerdictBadge verdict={test.verdict} /></td>
                    <td>{test.wall_ms} ms</td>
                    <td>{test.cpu_ms} ms</td>
                    <td>{test.memory_kb} KB</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  );
}

function SubmissionsPage() {
  const [submissions, setSubmissions] = useState<SubmissionSummary[] | null>(null);
  const [problemNames, setProblemNames] = useState<Record<number, string>>({});
  const [error, setError] = useState('');

  useEffect(() => {
    api.getSubmissions().then(setSubmissions).catch((cause: unknown) => setError(errorMessage(cause)));
    api.getProblems().then((items) => {
      setProblemNames(Object.fromEntries(items.map((item) => [item.id, item.title])));
    }).catch(() => undefined);
  }, []);

  return (
    <>
      <PageTitle eyebrow="Your activity">My submissions</PageTitle>
      <p className="section-lead">Review verdicts and performance for your recent attempts.</p>
      {error ? <EmptyState>{error}</EmptyState> : submissions === null ? <Loading label="Loading submissions…" /> : submissions.length === 0 ? <EmptyState>No submissions yet. Pick a problem and submit your first solution.</EmptyState> : (
        <section className="card table-card">
          <div className="table-scroll">
            <table>
              <thead><tr><th>ID</th><th>Problem</th><th>Language</th><th>Verdict</th><th>Time</th><th>Memory</th><th>Submitted at</th></tr></thead>
              <tbody>
                {submissions.map((item) => (
                  <tr key={item.id}>
                    <td><Link className="mono-link" to={`/submissions/${item.id}`}>{item.id.slice(0, 8)}</Link></td>
                    <td><Link className="table-link" to={`/problem/${item.problem_id}`}>{problemNames[item.problem_id] ?? `Problem #${item.problem_id}`}</Link></td>
                    <td><span className="language-pill">{item.language_id}</span></td>
                    <td><VerdictBadge verdict={item.verdict} status={item.status} /></td>
                    <td>{formatMetric(item.max_time_ms, 'ms')}</td>
                    <td>{formatMetric(item.max_memory_kb, 'KB')}</td>
                    <td>{formatDate(item.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}

function DashboardPage() {
  const [stats, setStats] = useState<StatsSummary | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    api.getStats().then(setStats).catch((cause: unknown) => setError(errorMessage(cause)));
  }, []);
  const distribution = useMemo(() => {
    if (!stats) return [];
    const total = Object.values(stats.verdicts).reduce((sum, count) => sum + count, 0);
    return Object.entries(stats.verdicts).map(([verdict, count]) => ({
      verdict,
      count,
      percent: total > 0 ? (count / total) * 100 : 0,
    }));
  }, [stats]);

  if (error) return <EmptyState>{error}</EmptyState>;
  if (!stats) return <Loading label="Loading dashboard…" />;
  return (
    <>
      <PageTitle eyebrow="Performance overview">Dashboard</PageTitle>
      <p className="section-lead">A snapshot of your submissions and execution performance.</p>
      <div className="metric-grid dashboard-metrics">
        <Metric label="Total submissions" value={String(stats.total)} />
        <Metric label="Pass rate" value={`${stats.pass_rate.toFixed(1)}%`} />
        <Metric label="Median runtime" value={formatMetric(stats.median_time_ms, 'ms')} />
        <Metric label="P95 runtime" value={formatMetric(stats.p95_time_ms, 'ms')} />
        <Metric label="Median memory" value={formatMetric(stats.median_memory_kb, 'KB')} />
        <Metric label="P95 memory" value={formatMetric(stats.p95_memory_kb, 'KB')} />
      </div>
      <section className="card distribution-card">
        <div className="table-heading"><div><p className="eyebrow">Verdicts</p><h2>Verdict distribution</h2></div><span className="muted-copy">{stats.total} total</span></div>
        <div className="distribution-list">
          {distribution.map(({ verdict, count, percent }) => (
            <div className="distribution-row" key={verdict}>
              <div className="distribution-label"><VerdictBadge verdict={verdict} /><span>{count} {count === 1 ? 'submission' : 'submissions'}</span><strong>{percent.toFixed(1)}%</strong></div>
              <div className="bar-track"><span className={`bar-fill bar-${verdict.toLowerCase()}`} style={{ width: `${percent}%` }} /></div>
            </div>
          ))}
        </div>
      </section>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="card metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

function NotFound() {
  return <div className="card not-found"><p className="eyebrow">404</p><h1>Page not found</h1><Link className="button button-primary" to="/problems">Browse problems</Link></div>;
}

function formatMetric(value: number | null | undefined, unit: string) {
  return value == null ? '—' : `${value} ${unit}`;
}

function formatDate(value: string | null | undefined) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}

export default function App() {
  return <AppLayout />;
}
