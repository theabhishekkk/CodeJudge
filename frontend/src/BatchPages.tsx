import { useEffect, useMemo, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import {
  ApiError,
  api,
  type BatchItem,
  type BatchListItem,
  type BatchSummary,
  type Problem,
} from './api';
import { useNotice } from './notice';
import {
  createDemoBatch,
  expectedDemoVerdict,
  inferLanguageFromFilename,
  parseBatchInput,
  parseJsonl,
  validateBatchItems,
  type BatchDraftItem,
  type BatchRowError,
} from './batchUtils';

const configuredMaxItems = Number(import.meta.env.VITE_BATCH_MAX_ITEMS || 500);
const BATCH_MAX_ITEMS = Number.isFinite(configuredMaxItems) && configuredMaxItems > 0
  ? configuredMaxItems
  : 500;
const VERDICTS = ['AC', 'WA', 'RE', 'TLE', 'MLE'];
const STATUSES = ['PENDING', 'RUNNING', 'COMPLETED', 'ERROR', 'CANCELLED'];

function BatchTitle({ eyebrow, title }: { eyebrow: string; title: string }) {
  return <div className="page-title"><p className="eyebrow">{eyebrow}</p><h1>{title}</h1></div>;
}

function BatchBadge({ value }: { value: string | null | undefined }) {
  const label = value || 'PENDING';
  const tone = label === 'AC' ? 'success'
    : label === 'WA' || label === 'RE' || label === 'ERROR' ? 'danger'
      : label === 'TLE' || label === 'MLE' ? 'warning' : 'neutral';
  return <span className={`badge badge-${tone}`}>{label}</span>;
}

function InlineErrors({ errors }: { errors: BatchRowError[] }) {
  if (!errors.length) return null;
  return (
    <div className="batch-errors" role="alert">
      {errors.map((error, index) => (
        <p key={`${error.index}-${error.line}-${error.field}-${index}`}>
          {error.index < 0 ? 'Input' : `Row ${error.index + 1}`} · line {error.line} · {error.field}: {error.message}
        </p>
      ))}
    </div>
  );
}

function downloadTextFile(filename: string, contents: string) {
  const blob = new Blob([contents], { type: 'text/csv;charset=utf-8' });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export function BatchCreatePage() {
  const navigate = useNavigate();
  const { showNotice } = useNotice();
  const [problems, setProblems] = useState<Problem[]>([]);
  const [problemError, setProblemError] = useState('');
  const [mode, setMode] = useState<'files' | 'upload' | 'paste'>('files');
  const [fileProblemId, setFileProblemId] = useState('');
  const [items, setItems] = useState<BatchDraftItem[]>([]);
  const [errors, setErrors] = useState<BatchRowError[]>([]);
  const [paste, setPaste] = useState('');
  const [uploadedFilename, setUploadedFilename] = useState('');
  const [batchName, setBatchName] = useState('');
  const [modelName, setModelName] = useState('');
  const [repeats, setRepeats] = useState(1);
  const [submitting, setSubmitting] = useState(false);
  const [requestError, setRequestError] = useState('');

  useEffect(() => {
    api.getProblems()
      .then((loaded) => {
        setProblems(loaded);
        if (loaded.length) setFileProblemId(String(loaded[0].id));
      })
      .catch((cause: unknown) => setProblemError(getErrorMessage(cause)));
  }, []);

  const expandedCount = items.length * repeats;
  const overLimit = expandedCount > BATCH_MAX_ITEMS;
  const canSubmit = items.length > 0
    && errors.length === 0
    && !overLimit
    && (mode !== 'files' || Boolean(fileProblemId))
    && !submitting;

  function changeMode(nextMode: 'files' | 'upload' | 'paste') {
    setMode(nextMode);
    setItems([]);
    setErrors([]);
    setPaste('');
    setUploadedFilename('');
    setRequestError('');
  }

  async function loadSourceFiles(files: FileList | File[]) {
    const selected = Array.from(files);
    if (!selected.length) return;
    const candidates: unknown[] = [];
    const fileErrors: BatchRowError[] = [];
    for (const [index, file] of selected.entries()) {
      const language = inferLanguageFromFilename(file.name);
      if (!language) {
        fileErrors.push({
          index,
          line: index + 1,
          field: 'filename',
          message: 'Use a .py, .cpp, or .cc source file',
        });
        continue;
      }
      try {
        candidates.push({
          problem_id: Number(fileProblemId),
          language_id: language,
          source_code: await file.text(),
          sample_id: file.name,
        });
      } catch {
        fileErrors.push({ index, line: index + 1, field: 'file', message: `Could not read ${file.name}` });
      }
    }
    const validated = validateBatchItems(candidates);
    setItems(validated.items);
    setErrors([...fileErrors, ...validated.errors]);
    setRequestError('');
  }

  async function loadStructuredFile(file: File | undefined) {
    if (!file) return;
    setUploadedFilename(file.name);
    setRequestError('');
    try {
      const parsed = parseBatchInput(await file.text(), file.name);
      setItems(parsed.items);
      setErrors(parsed.errors);
    } catch (cause) {
      setItems([]);
      setErrors([{ index: -1, line: 1, field: 'file', message: getErrorMessage(cause) }]);
    }
  }

  function updatePaste(value: string) {
    setPaste(value);
    const parsed = parseJsonl(value);
    setItems(parsed.items);
    setErrors(parsed.errors);
    setRequestError('');
  }

  function loadDemo() {
    if (!problems.length) return;
    const problemId = problems[0].id;
    setMode('files');
    setFileProblemId(String(problemId));
    setItems(createDemoBatch(problemId));
    setErrors([]);
    setPaste('');
    setUploadedFilename('');
    setBatchName('Demo A+B (120 samples)');
    setRequestError('');
  }

  async function submitBatch() {
    if (!canSubmit) return;
    setSubmitting(true);
    setRequestError('');
    try {
      const payload = {
        name: batchName.trim() || undefined,
        model_name: modelName.trim() || undefined,
        repeats,
        items,
      };
      const created = await api.createBatch(payload);
      showNotice(`Queued ${created.total} submissions.`, 'success');
      navigate(`/batch/${created.id}`);
    } catch (cause) {
      setRequestError(getErrorMessage(cause));
      if (cause instanceof ApiError && cause.retryAfter) {
        setRequestError(`${getErrorMessage(cause)} Retry in ${cause.retryAfter} seconds.`);
      }
    } finally {
      setSubmitting(false);
    }
  }

  function handleDrop(event: React.DragEvent<HTMLDivElement>) {
    event.preventDefault();
    void loadSourceFiles(event.dataTransfer.files);
  }

  return (
    <>
      <BatchTitle eyebrow="Batch execution" title="Run a batch" />
      <p className="section-lead">Submit up to {BATCH_MAX_ITEMS} solutions together and inspect every result.</p>
      <div className="batch-methods" role="tablist" aria-label="Batch input method">
        {(['files', 'upload', 'paste'] as const).map((method) => (
          <button
            className={`button ${mode === method ? 'button-primary' : 'button-quiet'}`}
            key={method}
            role="tab"
            aria-selected={mode === method}
            onClick={() => changeMode(method)}
          >
            {method === 'files' ? 'Source files' : method === 'upload' ? 'Upload data' : 'Paste JSONL'}
          </button>
        ))}
      </div>

      <section className="card batch-input-card">
        {mode === 'files' && (
          <div className="form-stack">
            <label className="field">
              <span>Problem for every source file</span>
              <select
                value={fileProblemId}
                onChange={(event) => {
                  const selectedId = event.target.value;
                  setFileProblemId(selectedId);
                  if (selectedId) {
                    setItems((current) => current.map((item) => ({ ...item, problem_id: Number(selectedId) })));
                  }
                }}
                required
              >
                <option value="">Choose a problem</option>
                {problems.map((problem) => <option key={problem.id} value={problem.id}>{problem.title} · #{problem.id}</option>)}
              </select>
            </label>
            {problemError && <p className="inline-error" role="alert">{problemError}</p>}
            <div
              className="batch-dropzone"
              onDragOver={(event) => event.preventDefault()}
              onDrop={handleDrop}
            >
              <strong>Drop many .py, .cpp, or .cc files here</strong>
              <span>Language is inferred from each extension; the filename becomes sample_id.</span>
              <label className="button button-quiet" htmlFor="batch-source-files">Choose files</label>
              <input
                id="batch-source-files"
                type="file"
                accept=".py,.cpp,.cc"
                multiple
                onChange={(event) => {
                  if (event.currentTarget.files) void loadSourceFiles(event.currentTarget.files);
                  event.currentTarget.value = '';
                }}
              />
            </div>
            <button className="button button-quiet demo-button" onClick={loadDemo} disabled={!problems.length}>
              Load demo batch (120 samples)
            </button>
          </div>
        )}

        {mode === 'upload' && (
          <div className="form-stack">
            <div className="batch-schema">
              <strong>Expected columns</strong>
              <code>problem_id, language_id, source_code, sample_id</code>
              <span>CSV, JSONL (one object per line), and JSON arrays or an object with an items array are supported.</span>
              <button
                className="text-button"
                onClick={() => downloadTextFile(
                  'codejudge-batch-template.csv',
                  'problem_id,language_id,source_code,sample_id\n1,python3,"print(sum(map(int, input().split())))",example-1\n',
                )}
              >
                Download template
              </button>
            </div>
            <label className="field">
              <span>Upload .jsonl, .json, or .csv</span>
              <input
                type="file"
                accept=".jsonl,.json,.csv"
                onChange={(event) => void loadStructuredFile(event.currentTarget.files?.[0])}
              />
            </label>
            {uploadedFilename && <p className="muted-copy">Loaded {uploadedFilename}</p>}
          </div>
        )}

        {mode === 'paste' && (
          <label className="field">
            <span>Paste JSONL · one submission object per line</span>
            <textarea
              className="batch-jsonl"
              value={paste}
              onChange={(event) => updatePaste(event.target.value)}
              placeholder={'{"problem_id":1,"language_id":"python3","source_code":"print(1)","sample_id":"sample-1"}'}
              spellCheck={false}
            />
          </label>
        )}
      </section>

      <section className="card batch-settings">
        <div className="batch-setting-fields">
          <label className="field"><span>Batch name (optional)</span><input value={batchName} onChange={(event) => setBatchName(event.target.value)} maxLength={255} /></label>
          <label className="field"><span>Model name (optional)</span><input value={modelName} onChange={(event) => setModelName(event.target.value)} maxLength={255} /></label>
          <label className="field"><span>Repeats</span><input type="number" min={1} max={10} value={repeats} onChange={(event) => setRepeats(Math.min(10, Math.max(1, Math.trunc(Number(event.target.value) || 1))))} /></label>
        </div>
        <div className="batch-submit-row">
          <div>
            <strong>{expandedCount} submissions will be created</strong>
            <span>Maximum {BATCH_MAX_ITEMS} submissions per batch</span>
          </div>
          <button className="button button-primary" onClick={() => void submitBatch()} disabled={!canSubmit}>
            {submitting ? 'Queueing…' : '▶ Run batch'}
          </button>
        </div>
        {overLimit && <p className="inline-error" role="alert">This batch exceeds the {BATCH_MAX_ITEMS}-submission limit after repeats.</p>}
        {requestError && <p className="inline-error" role="alert">{requestError}</p>}
      </section>

      <section className="card batch-preview">
        <div className="table-heading">
          <div><p className="eyebrow">Preview</p><h2>{items.length} valid input rows</h2></div>
          <span className="muted-copy">Showing the first 10</span>
        </div>
        <InlineErrors errors={errors} />
        {items.length > 0 && (
          <div className="table-scroll">
            <table>
              <thead><tr><th>Row</th><th>Problem</th><th>Language</th><th>Sample ID</th><th>Source preview</th></tr></thead>
              <tbody>
                {items.slice(0, 10).map((item, index) => (
                  <tr key={`${item.sample_id ?? 'row'}-${index}`}>
                    <td>{index + 1}</td>
                    <td>#{item.problem_id}</td>
                    <td>{item.language_id}</td>
                    <td>{item.sample_id ?? '—'}</td>
                    <td className="batch-code-preview">{item.source_code.slice(0, 100)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {items.length === 0 && !errors.length && <p className="batch-preview-empty">Choose an input method to preview submissions.</p>}
      </section>
    </>
  );
}

export function BatchHistoryPage() {
  const [items, setItems] = useState<BatchListItem[] | null>(null);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [error, setError] = useState('');
  const limit = 20;

  useEffect(() => {
    let active = true;
    api.getBatches(limit, offset)
      .then((response) => {
        if (!active) return;
        setItems(response.items);
        setTotal(response.total);
        setError('');
      })
      .catch((cause: unknown) => {
        if (active) setError(getErrorMessage(cause));
      });
    return () => { active = false; };
  }, [offset]);

  return (
    <>
      <div className="batch-history-heading">
        <div><BatchTitle eyebrow="Your activity" title="Batch history" /><p className="section-lead">Review progress and verdict summaries from previous runs.</p></div>
        <Link className="button button-primary" to="/batch">＋ New batch</Link>
      </div>
      {error ? <div className="batch-errors" role="alert">{error}</div> : items === null ? <div className="loading">Loading batches…</div> : items.length === 0 ? (
        <div className="card batch-empty"><p>No batches yet.</p><Link className="button button-primary" to="/batch">Create your first batch</Link></div>
      ) : (
        <div className="batch-history-list">
          {items.map((batch) => {
            const counts = batch.counts;
            const complete = terminalCount(counts);
            const percent = batch.total ? Math.min(100, complete / batch.total * 100) : 0;
            return (
              <Link className="card batch-history-card" to={`/batch/${batch.id}`} key={batch.id}>
                <div className="batch-history-top">
                  <div><h2>{batch.name || 'Unnamed batch'}</h2><p>{batch.model_name || 'No model'} · {formatDate(batch.created_at)}</p></div>
                  <BatchBadge value={batch.status} />
                </div>
                <div className="batch-progress-label"><span>{complete}/{batch.total} terminal</span><span>{percent.toFixed(0)}%</span></div>
                <div className="batch-progress-track"><span style={{ width: `${percent}%` }} /></div>
                <div className="batch-mini-verdicts">
                  {Object.entries(batch.verdicts).map(([verdict, count]) => (
                    <span key={verdict}><BatchBadge value={verdict} /> {count}</span>
                  ))}
                  {Object.keys(batch.verdicts).length === 0 && <span className="muted-copy">Results will appear here as submissions finish.</span>}
                </div>
              </Link>
            );
          })}
        </div>
      )}
      {total > limit && (
        <div className="batch-pagination">
          <button className="button button-quiet" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - limit))}>Previous</button>
          <span>{offset + 1}–{Math.min(total, offset + limit)} of {total}</span>
          <button className="button button-quiet" disabled={offset + limit >= total} onClick={() => setOffset(offset + limit)}>Next</button>
        </div>
      )}
    </>
  );
}

export function BatchLivePage() {
  const { id = '' } = useParams();
  const navigate = useNavigate();
  const { showNotice } = useNotice();
  const [summary, setSummary] = useState<BatchSummary | null>(null);
  const [rows, setRows] = useState<BatchItem[]>([]);
  const [totalItems, setTotalItems] = useState(0);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [error, setError] = useState('');
  const [problemError, setProblemError] = useState('');
  const [page, setPage] = useState(0);
  const [verdictFilter, setVerdictFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [languageFilter, setLanguageFilter] = useState('');
  const [problemFilter, setProblemFilter] = useState('');
  const [sortKey, setSortKey] = useState('created_at');
  const [sortDescending, setSortDescending] = useState(true);
  const [actionInFlight, setActionInFlight] = useState(false);
  const [demoRows, setDemoRows] = useState<BatchItem[]>([]);
  const active = Boolean(
    summary
    && summary.status === 'RUNNING'
    && ((summary.counts.PENDING ?? 0) + (summary.counts.RUNNING ?? 0) > 0),
  );
  const isDemo = Boolean(summary?.name?.startsWith('Demo'));

  useEffect(() => {
    api.getProblems()
      .then(setProblems)
      .catch((cause: unknown) => setProblemError(getErrorMessage(cause)));
  }, []);

  useEffect(() => {
    if (!id) return undefined;
    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const next = await api.getBatch(id);
        if (cancelled) return;
        setSummary(next);
        setError('');
        const hasActiveItems = (next.counts.PENDING ?? 0) + (next.counts.RUNNING ?? 0) > 0;
        if (next.status === 'RUNNING' && hasActiveItems) timeout = setTimeout(poll, 1000);
      } catch (cause) {
        if (!cancelled) {
          setError(getErrorMessage(cause));
          timeout = setTimeout(poll, 2000);
        }
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timeout) clearTimeout(timeout);
    };
  }, [id]);

  useEffect(() => {
    if (!id) return undefined;
    let cancelled = false;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        const params = {
          limit: 50,
          offset: page * 50,
          verdict: verdictFilter || undefined,
          status: statusFilter || undefined,
          language_id: languageFilter || undefined,
          problem_id: problemFilter ? Number(problemFilter) : undefined,
          sort: `${sortDescending ? '-' : ''}${sortKey}`,
        };
        const response = await api.getBatchItems(id, params);
        if (cancelled) return;
        setRows(response.items);
        setTotalItems(response.total);
        setError('');
        if (isDemo) {
          const nextRows: BatchItem[] = [];
          for (let offset = 0; offset < (summary?.total ?? 0); offset += 100) {
            const pageResult = await api.getBatchItems(id, { limit: 100, offset });
            nextRows.push(...pageResult.items);
          }
          if (!cancelled) setDemoRows(nextRows);
        }
      } catch (cause) {
        if (!cancelled) setError(getErrorMessage(cause));
      } finally {
        if (!cancelled && active) timeout = setTimeout(poll, 2000);
      }
    };
    void poll();
    return () => {
      cancelled = true;
      if (timeout) clearTimeout(timeout);
    };
  }, [
    active,
    id,
    isDemo,
    languageFilter,
    page,
    problemFilter,
    sortDescending,
    sortKey,
    statusFilter,
    summary?.total,
    verdictFilter,
  ]);

  const demoExpected = useMemo(() => {
    const counts: Record<string, { expected: number; actual: number }> = {};
    let matched = 0;
    let terminal = 0;
    const mismatches: BatchItem[] = [];
    for (const row of demoRows) {
      const expected = expectedDemoVerdict(row.sample_id);
      if (!expected) continue;
      const actual = row.verdict;
      const item = counts[expected] ?? { expected: 0, actual: 0 };
      item.expected += 1;
      if (actual) item.actual += 1;
      if (isTerminal(row.status)) {
        terminal += 1;
        if (actual === expected) matched += 1;
        else mismatches.push(row);
      }
      counts[expected] = item;
    }
    return { counts, matched, terminal, mismatches };
  }, [demoRows]);

  async function cancelBatch() {
    setActionInFlight(true);
    try {
      const response = await api.cancelBatch(id);
      showNotice(`Cancelled ${response.cancelled} pending submissions.`, 'info');
      setSummary((current) => current ? { ...current, status: response.status } : current);
    } catch (cause) {
      setError(getErrorMessage(cause));
    } finally {
      setActionInFlight(false);
    }
  }

  async function rerunFailed() {
    setActionInFlight(true);
    try {
      const created = await api.rerunFailedBatch(id);
      showNotice(`Created a new batch with ${created.total} failed submissions.`, 'success');
      navigate(`/batch/${created.id}`);
    } catch (cause) {
      setError(getErrorMessage(cause));
    } finally {
      setActionInFlight(false);
    }
  }

  async function exportCsv() {
    setActionInFlight(true);
    try {
      const blob = await api.exportBatchCsv(id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `batch-${id}.csv`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (cause) {
      setError(getErrorMessage(cause));
    } finally {
      setActionInFlight(false);
    }
  }

  async function copyLink() {
    try {
      await navigator.clipboard.writeText(window.location.href);
      showNotice('Batch link copied.', 'success');
    } catch (cause) {
      setError(`Could not copy the batch link: ${getErrorMessage(cause)}`);
    }
  }

  function changeSort(nextKey: string) {
    if (sortKey === nextKey) setSortDescending((value) => !value);
    else {
      setSortKey(nextKey);
      setSortDescending(false);
    }
    setPage(0);
  }

  if (error && !summary) return <div className="batch-errors" role="alert">{error}</div>;
  if (!summary) return <div className="loading">Loading batch…</div>;
  const completedForProgress = terminalCount(summary.counts);
  const progress = summary.total ? Math.min(100, completedForProgress / summary.total * 100) : 0;
  const verdictEntries = Object.entries(summary.verdicts);
  const pageCount = Math.max(1, Math.ceil(totalItems / 50));
  const processedDemoCount = demoExpected.terminal;
  return (
    <>
      <Link className="back-link" to="/batches">← Batch history</Link>
      <div className="batch-live-heading">
        <div>
          <BatchTitle eyebrow="Batch run" title={summary.name || 'Unnamed batch'} />
          <p className="muted-copy">{summary.model_name || 'No model'} · {summary.id}</p>
        </div>
        <BatchBadge value={summary.status} />
      </div>
      <div className="batch-actions">
        <button className="button button-quiet" onClick={() => void cancelBatch()} disabled={!active || actionInFlight}>Cancel batch</button>
        <button className="button button-quiet" onClick={() => void exportCsv()} disabled={actionInFlight}>Export CSV</button>
        <button className="button button-quiet" onClick={() => void rerunFailed()} disabled={actionInFlight}>Re-run failed</button>
        <button className="button button-quiet" onClick={() => void copyLink()}>Copy link</button>
      </div>
      {error && <div className="batch-errors" role="alert">{error}</div>}
      <section className="card batch-live-progress">
        <div className="batch-progress-label">
          <strong>{completedForProgress}/{summary.total} terminal submissions</strong>
          <span>{progress.toFixed(1)}%</span>
        </div>
        <div className="batch-progress-track batch-progress-large"><span style={{ width: `${progress}%` }} /></div>
        <div className="batch-count-grid">
          {STATUSES.map((status) => <div key={status}><span>{status.toLowerCase()}</span><strong>{summary.counts[status] ?? 0}</strong></div>)}
        </div>
      </section>

      <div className="batch-metric-grid">
        <Metric label="Throughput" value={`${summary.throughput.toFixed(1)} / min`} />
        <Metric label="ETA" value={summary.eta_seconds == null ? '—' : `${Math.ceil(summary.eta_seconds)} s`} />
        <Metric label="Median / P95 wall" value={`${formatMetric(summary.median_wall_ms, 'ms')} / ${formatMetric(summary.p95_wall_ms, 'ms')}`} />
        <Metric label="Median / P95 memory" value={`${formatMetric(summary.median_memory_kb, 'KB')} / ${formatMetric(summary.p95_memory_kb, 'KB')}`} />
      </div>

      <section className="card distribution-card batch-verdict-card">
        <div className="table-heading"><div><p className="eyebrow">Verdicts</p><h2>Live distribution</h2></div><span className="muted-copy">{Object.values(summary.verdicts).reduce((sum, count) => sum + count, 0)} results</span></div>
        <div className="batch-verdict-bar" aria-label="Verdict distribution">
          {verdictEntries.map(([verdict, count]) => (
            <span
              className={`bar-${verdict.toLowerCase()}`}
              key={verdict}
              title={`${verdict}: ${count}`}
              style={{ width: `${summary.total ? count / summary.total * 100 : 0}%` }}
            />
          ))}
        </div>
        <div className="batch-mini-verdicts">
          {verdictEntries.map(([verdict, count]) => <span key={verdict}><BatchBadge value={verdict} /> {count}</span>)}
        </div>
      </section>

      {isDemo && (
        <section className="card batch-expected-card">
          <div className="table-heading"><div><p className="eyebrow">Demo verification</p><h2>Expected vs actual</h2></div><strong>{demoExpected.matched}/{processedDemoCount} matches</strong></div>
          <div className="batch-mini-verdicts">
            {Object.entries(demoExpected.counts).map(([verdict, counts]) => (
              <span key={verdict}><BatchBadge value={verdict} /> expected {counts.expected} · actual {counts.actual}</span>
            ))}
          </div>
          {demoExpected.mismatches.length > 0 && (
            <div className="batch-mismatch-list">
              {demoExpected.mismatches.slice(0, 10).map((row) => (
                <p key={row.id}>{row.sample_id}: expected {expectedDemoVerdict(row.sample_id)}, got {row.verdict || row.status}</p>
              ))}
            </div>
          )}
        </section>
      )}

      <section className="card batch-items-card">
        <div className="table-heading"><div><p className="eyebrow">Submissions</p><h2>Batch items</h2></div><span className="muted-copy">{totalItems} matching rows</span></div>
        <div className="batch-filter-row">
          <label>Verdict<select value={verdictFilter} onChange={(event) => { setVerdictFilter(event.target.value); setPage(0); }}><option value="">All</option>{VERDICTS.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label>Status<select value={statusFilter} onChange={(event) => { setStatusFilter(event.target.value); setPage(0); }}><option value="">All</option>{STATUSES.map((value) => <option key={value}>{value}</option>)}</select></label>
          <label>Language<select value={languageFilter} onChange={(event) => { setLanguageFilter(event.target.value); setPage(0); }}><option value="">All</option><option value="python3">Python 3</option><option value="cpp17">C++17</option></select></label>
          <label>Problem<select value={problemFilter} onChange={(event) => { setProblemFilter(event.target.value); setPage(0); }}><option value="">All</option>{problems.map((problem) => <option key={problem.id} value={problem.id}>{problem.title}</option>)}</select></label>
        </div>
        {problemError && <p className="inline-error batch-filter-error" role="alert">{problemError}</p>}
        {rows.length === 0 ? <p className="batch-preview-empty">No submissions match these filters.</p> : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th><button onClick={() => changeSort('created_at')}>Submission</button></th>
                  <th><button onClick={() => changeSort('problem_id')}>Problem</button></th>
                  <th>Language</th><th>Sample</th><th>Repeat</th>
                  <th><button onClick={() => changeSort('status')}>Status</button></th>
                  <th><button onClick={() => changeSort('verdict')}>Verdict</button></th>
                  <th><button onClick={() => changeSort('wall_ms')}>Wall</button></th>
                  <th><button onClick={() => changeSort('memory_kb')}>Memory</button></th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    className="batch-clickable-row"
                    key={row.id}
                    onClick={() => navigate(`/submissions/${row.id}`)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') navigate(`/submissions/${row.id}`);
                    }}
                    tabIndex={0}
                  >
                    <td className="mono-link">{row.id.slice(0, 8)}</td>
                    <td>{row.problem_title} · #{row.problem_id}</td>
                    <td>{row.language_id}</td>
                    <td>{row.sample_id || '—'}</td>
                    <td>{row.repeat_index}</td>
                    <td><BatchBadge value={row.status} /></td>
                    <td><BatchBadge value={row.verdict} /></td>
                    <td>{formatMetric(row.wall_ms, 'ms')}</td>
                    <td>{formatMetric(row.memory_kb, 'KB')}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="batch-pagination">
          <button className="button button-quiet" disabled={page === 0} onClick={() => setPage((value) => Math.max(0, value - 1))}>Previous</button>
          <span>Page {page + 1} of {pageCount}</span>
          <button className="button button-quiet" disabled={(page + 1) * 50 >= totalItems} onClick={() => setPage((value) => value + 1)}>Next</button>
        </div>
      </section>
    </>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="card metric-card"><span>{label}</span><strong>{value}</strong></div>;
}

function terminalCount(counts: Record<string, number>) {
  return (counts.COMPLETED ?? 0) + (counts.ERROR ?? 0) + (counts.CANCELLED ?? 0);
}

function isTerminal(status: string) {
  return ['COMPLETED', 'ERROR', 'CANCELLED'].includes(status);
}

function formatMetric(value: number | null | undefined, unit: string) {
  return value == null ? '—' : `${value} ${unit}`;
}

function formatDate(value: string | null | undefined) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}

function getErrorMessage(error: unknown) {
  return error instanceof Error ? error.message : 'Something went wrong. Please try again.';
}
