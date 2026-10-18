import { useState } from 'react';
import { useNavigate, useSearchParams, Link } from 'react-router-dom';
import { Compass, LogIn } from 'lucide-react';
import { login } from '../api/authApi.js';
import { setSession } from '../lib/auth.js';

export default function LoginPage() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const next = params.get('next') || '/';

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const { token, account } = await login(email.trim(), password);
      setSession(token, account);
      navigate(next, { replace: true });
    } catch (err) {
      setError(err.message === 'Request failed (401)' ? 'Wrong email or password.' : err.message);
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[#fafaf9] px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex items-center justify-center gap-2">
          <span className="flex h-10 w-10 items-center justify-center rounded-xl bg-brand-500 text-white shadow-sm">
            <Compass size={22} />
          </span>
          <span className="text-xl font-bold tracking-tight text-stone-900">Skool Explorer</span>
        </div>

        <form
          onSubmit={submit}
          className="rounded-2xl border border-stone-200 bg-white p-6 shadow-sm"
        >
          <h1 className="text-lg font-bold text-stone-900">Sign in</h1>
          <p className="mt-1 text-sm text-stone-500">Access your Skool market analytics.</p>

          <label className="mt-5 block text-xs font-semibold uppercase tracking-wide text-stone-400">
            Email
            <input
              type="email"
              required
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="mt-1 h-10 w-full rounded-lg border border-stone-200 bg-white px-3 text-sm font-medium normal-case tracking-normal text-stone-800 outline-none transition-colors hover:border-stone-300 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
              placeholder="you@company.com"
            />
          </label>

          <label className="mt-4 block text-xs font-semibold uppercase tracking-wide text-stone-400">
            Password
            <input
              type="password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="mt-1 h-10 w-full rounded-lg border border-stone-200 bg-white px-3 text-sm font-medium text-stone-800 outline-none transition-colors hover:border-stone-300 focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
              placeholder="••••••••"
            />
          </label>

          {error && (
            <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{error}</p>
          )}

          <button
            type="submit"
            disabled={busy}
            className="mt-5 inline-flex h-10 w-full items-center justify-center gap-2 rounded-lg bg-brand-500 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-600 disabled:cursor-not-allowed disabled:opacity-60"
          >
            <LogIn size={16} />
            {busy ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <p className="mt-4 text-center text-xs text-stone-400">
          No account? Contact your provider.{' '}
          <Link to="/" className="font-semibold text-brand-600 hover:text-brand-700">
            Back to home
          </Link>
        </p>
      </div>
    </div>
  );
}