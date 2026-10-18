// Tiny auth store: token + account in localStorage with a subscribe event so
// components (Header) re-render on login/logout without heavy context.

const TOKEN_KEY = 'skool_token';
const ACCOUNT_KEY = 'skool_account';

let listeners = new Set();

const emit = () => listeners.forEach((fn) => fn());

export function subscribe(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getToken() {
  return localStorage.getItem(TOKEN_KEY);
}

export function getAccount() {
  try {
    const raw = localStorage.getItem(ACCOUNT_KEY);
    return raw ? JSON.parse(raw) : null;
  } catch {
    return null;
  }
}

export function setSession(token, account) {
  localStorage.setItem(TOKEN_KEY, token);
  if (account) localStorage.setItem(ACCOUNT_KEY, JSON.stringify(account));
  emit();
}

export function clearSession() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ACCOUNT_KEY);
  emit();
}

export function isLoggedIn() {
  return !!getToken() && !isTokenExpired();
}

// Client-side nicety only — the server re-validates every request.
export function isTokenExpired() {
  const token = getToken();
  if (!token) return true;
  try {
    const payload = JSON.parse(atob(token.split('.')[1].replace(/-/g, '+').replace(/_/g, '/')));
    return payload.exp ? payload.exp * 1000 < Date.now() : false;
  } catch {
    return false; // opaque/unparseable token — let the server decide
  }
}

// Admin marker — from the account's real is_admin flag; falls back to the
// seeded demo email for older sessions cached before the flag existed.
export function isAdmin() {
  const acct = getAccount();
  if (!acct) return false;
  return !!acct.is_admin || acct.email === 'admin@skool.local';
}
