import { Route, Routes, Link } from 'react-router-dom';

function AuthPage() {
  return (
    <div className="panel">
      <h2>Login / Register</h2>
      <p>API base URL: <code>{import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'}</code></p>
      <button>Register</button>
      <button>Login</button>
    </div>
  );
}

function ProblemsPage() {
  return (
    <div className="panel">
      <h2>Problems</h2>
      <ul>
        <li><Link to="/problem/1">A+B</Link></li>
      </ul>
    </div>
  );
}

function ProblemDetailPage() {
  return (
    <div className="panel">
      <h2>Problem detail</h2>
      <textarea defaultValue="print(sum(map(int, input().split())))" rows={12} />
      <select defaultValue="python3">
        <option value="python3">Python 3</option>
        <option value="cpp17">C++17</option>
      </select>
      <button>Submit</button>
    </div>
  );
}

function SubmissionsPage() {
  return (
    <div className="panel">
      <h2>My submissions</h2>
      <table>
        <thead><tr><th>ID</th><th>Status</th><th>Verdict</th></tr></thead>
        <tbody><tr><td>demo</td><td>COMPLETED</td><td>AC</td></tr></tbody>
      </table>
    </div>
  );
}

function DashboardPage() {
  return (
    <div className="panel">
      <h2>Dashboard</h2>
      <div className="bars">
        <span style={{ height: '70%' }} title="AC" />
        <span style={{ height: '20%' }} title="WA" />
        <span style={{ height: '10%' }} title="RE" />
      </div>
    </div>
  );
}

export default function App() {
  return (
    <div className="app-shell">
      <nav className="nav">
        <Link to="/">Login</Link>
        <Link to="/problems">Problems</Link>
        <Link to="/submissions">Submissions</Link>
        <Link to="/stats">Dashboard</Link>
      </nav>
      <Routes>
        <Route path="/" element={<AuthPage />} />
        <Route path="/problems" element={<ProblemsPage />} />
        <Route path="/problem/:id" element={<ProblemDetailPage />} />
        <Route path="/submissions" element={<SubmissionsPage />} />
        <Route path="/stats" element={<DashboardPage />} />
      </Routes>
    </div>
  );
}
