import { useState } from 'react';
import { Navigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext.jsx';

export default function Login() {
  const { isAuthenticated, login, authError, clearError } = useAuth();
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);

  if (isAuthenticated) {
    return <Navigate to="/" replace />;
  }

  const handleSubmit = async (event) => {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    clearError?.();
    try {
      await login(password);
    } catch (err) {
      setError(err.message || 'Login failed');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-950">
      <div className="w-full max-w-md rounded-2xl border border-slate-800/80 bg-slate-900/70 p-8 shadow-2xl">
        <h2 className="text-center text-2xl font-semibold text-emerald-300">
          Eris Device Login
        </h2>
        <p className="mt-2 text-center text-sm text-slate-400">
          Enter the administrator password configured during setup.
        </p>
        <form className="mt-6 space-y-4" onSubmit={handleSubmit}>
          <div>
            <label
              htmlFor="eris-password"
              className="text-xs uppercase tracking-[0.3em] text-slate-400"
            >
              Password
            </label>
            <input
              id="eris-password"
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              className="mt-2 w-full rounded-lg border border-slate-700 bg-slate-950 px-4 py-3 text-slate-100 shadow-inner outline-none focus:border-emerald-400 focus:ring-2 focus:ring-emerald-500/40"
              required
            />
          </div>
          {(error || authError) && (
            <div className="rounded-lg border border-red-500/50 bg-red-900/30 px-3 py-2 text-sm text-red-100">
              {error || authError}
            </div>
          )}
          <button
            type="submit"
            disabled={submitting}
            className="w-full rounded-lg bg-emerald-500 py-3 text-sm font-semibold text-slate-950 shadow-lg transition hover:bg-emerald-400 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>
      </div>
    </div>
  );
}
