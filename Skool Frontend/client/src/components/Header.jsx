import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useSyncExternalStore } from 'react';
import { Compass, BarChart3, Activity, Shield, LogOut, LogIn } from 'lucide-react';
import BrowseToggle from './BrowseToggle.jsx';
import * as auth from '../lib/auth.js';

export default function Header({ onBrowse }) {
  const location = useLocation();
  const navigate = useNavigate();
  // Re-render on login/logout via the tiny auth store.
  useSyncExternalStore(auth.subscribe, () => auth.getToken());

  const loggedIn = auth.isLoggedIn();
  const account = auth.getAccount();

  // Derive current view from URL, defaulting to groups
  const params = new URLSearchParams(location.search);
  const view = params.get('view') === 'users' ? 'users' : 'groups';

  const handleChange = (v) => {
    navigate(`/?view=${v}`);
  };

  const logout = () => {
    auth.clearSession();
    navigate('/login');
  };

  return (
    <header className="sticky top-0 z-40 border-b border-stone-200/80 bg-white/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 w-full max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
        <Link to="/" className="flex items-center gap-2" aria-label="Skool Explorer home">
          <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-500 text-white shadow-sm">
            <Compass size={20} />
          </span>
          <span className="text-lg font-bold tracking-tight text-stone-900">Skool</span>
        </Link>

        {onBrowse && (
          <div className="absolute left-1/2 -translate-x-1/2 sm:static sm:translate-x-0">
            <BrowseToggle view={view} onChange={handleChange} />
          </div>
        )}

        <div className="flex items-center gap-3">
          <Link
            to="/analytics"
            className="inline-flex items-center gap-1.5 text-sm font-semibold text-stone-600 transition-colors hover:text-brand-600"
          >
            <BarChart3 size={15} />
            Analytics
          </Link>
          {loggedIn && (
            <>
              <Link
                to="/usage"
                className="hidden items-center gap-1.5 text-sm font-semibold text-stone-600 transition-colors hover:text-brand-600 sm:inline-flex"
              >
                <Activity size={15} />
                Usage
              </Link>
              {auth.isAdmin() && (
                <Link
                  to="/admin"
                  className="inline-flex items-center gap-1.5 text-sm font-semibold text-stone-600 transition-colors hover:text-brand-600"
                >
                  <Shield size={15} />
                  Admin
                </Link>
              )}
            </>
          )}

          {loggedIn ? (
            <div className="flex items-center gap-2 border-l border-stone-200 pl-3">
              <span className="hidden max-w-[160px] truncate text-sm font-medium text-stone-500" title={account?.email}>
                {account?.email}
              </span>
              <button
                type="button"
                onClick={logout}
                title="Sign out"
                className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-stone-500 transition-colors hover:bg-stone-100 hover:text-stone-700"
              >
                <LogOut size={16} />
              </button>
            </div>
          ) : (
            <Link
              to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`}
              className="inline-flex items-center gap-1.5 rounded-lg bg-brand-500 px-3 py-2 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-600"
            >
              <LogIn size={15} />
              Sign in
            </Link>
          )}
        </div>
      </div>
    </header>
  );
}