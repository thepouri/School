import { useState } from 'react';
import { Shield, Plus, KeyRound, Power, CalendarPlus, Copy, Check, Trash2, X } from 'lucide-react';
import {
  useAdminAccounts, useCreateAccount, useExtendAccount, useSetActive, useResetPassword,
} from '../api/authApi.js';
import { post, buildQuery } from '../api/client.js';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { isAdmin, getAccount } from '../lib/auth.js';

function statusOf(acct) {
  if (!acct.is_active) return { text: 'Disabled', cls: 'bg-stone-100 text-stone-500' };
  const exp = new Date(acct.expires_at).getTime();
  if (exp < Date.now()) return { text: 'Expired', cls: 'bg-red-50 text-red-600' };
  const days = Math.ceil((exp - Date.now()) / 86400000);
  if (days <= 5) return { text: `${days}d left`, cls: 'bg-amber-50 text-amber-700' };
  return { text: 'Active', cls: 'bg-emerald-50 text-emerald-700' };
}

const randomPassword = () =>
  Array.from({ length: 12 }, () =>
    'abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ23456789'[Math.floor(Math.random() * 56)],
  ).join('');

// DELETE has no body — dedicated helper (client.post is JSON-body only).
export function useDeleteAccount() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (id) => {
      const token = localStorage.getItem('skool_token');
      const res = await fetch(`/api/admin/accounts/${id}`, {
        method: 'DELETE',
        headers: token ? { Authorization: `Bearer ${token}` } : undefined,
      });
      if (!res.ok) {
        let msg = `Request failed (${res.status})`;
        try { const b = await res.json(); if (b?.error) msg = b.error; } catch { /* ignore */ }
        throw new Error(msg);
      }
      return res.json();
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['admin-accounts'] }),
  });
}

export default function AdminPage() {
  const { data, isLoading, error } = useAdminAccounts();
  const create = useCreateAccount();
  const extend = useExtendAccount();
  const setActive = useSetActive();
  const resetPw = useResetPassword();
  const del = useDeleteAccount();

  // create form state
  const [email, setEmail] = useState('');
  const [label, setLabel] = useState('');
  const [days, setDays] = useState(30);
  const [newPw, setNewPw] = useState(randomPassword());
  const [copied, setCopied] = useState(false);
  const [formError, setFormError] = useState(null);

  // inline row editors (replaces window.prompt which is blocked in some embeds)
  const [pwEditingId, setPwEditingId] = useState(null);
  const [pwDraft, setPwDraft] = useState('');
  const [confirmDeleteId, setConfirmDeleteId] = useState(null);

  if (!isAdmin()) {
    return (
      <div className="py-16 text-center">
        <Shield size={40} className="mx-auto text-stone-300" />
        <h1 className="mt-4 text-xl font-bold text-stone-800">Not authorized</h1>
        <p className="mt-1 text-sm text-stone-500">This area is for administrators only.</p>
      </div>
    );
  }

  const runAction = (mutation, path, body) => mutation.mutate({ path, body });

  const onCreate = (e) => {
    e.preventDefault();
    setFormError(null);
    create.mutate(
      { path: '/api/admin/accounts', body: { email: email.trim(), password: newPw, label: label.trim() || null, days: Number(days) || 30 } },
      {
        onError: (err) => setFormError(err.message),
        onSuccess: () => {
          setEmail('');
          setLabel('');
          setNewPw(randomPassword());
        },
      },
    );
  };

  const submitResetPw = (acct) => {
    if (!pwDraft.trim()) return;
    resetPw.mutate(
      { path: `/api/admin/accounts/${acct.id}/password`, body: { password: pwDraft } },
      { onSuccess: () => { setPwEditingId(null); setPwDraft(''); } },
    );
  };

  const accounts = data?.items ?? [];
  const busy = extend.isPending || setActive.isPending || resetPw.isPending || del.isPending;

  return (
    <div className="pb-16">
      <div className="py-8">
        <h1 className="flex items-center gap-2 text-3xl font-bold tracking-tight text-stone-900">
          <Shield size={26} className="text-brand-500" />
          Account management
        </h1>
        <p className="mt-1 text-[15px] text-stone-500">
          Create customer accounts, extend subscriptions, and control access. Signed in as{' '}
          <span className="font-semibold text-stone-700">{getAccount()?.email}</span>.
        </p>
      </div>

      {/* Create account */}
      <form
        onSubmit={onCreate}
        className="rounded-2xl border border-stone-200 bg-white p-5 shadow-sm"
      >
        <h2 className="flex items-center gap-2 text-base font-bold text-stone-900">
          <Plus size={16} className="text-brand-500" />
          New customer account
        </h2>
        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <input
            type="email" required placeholder="customer@email.com" value={email}
            onChange={(e) => setEmail(e.target.value)}
            className="h-10 rounded-lg border border-stone-200 px-3 text-sm outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
          />
          <input
            type="text" placeholder="Label / company (optional)" value={label}
            onChange={(e) => setLabel(e.target.value)}
            className="h-10 rounded-lg border border-stone-200 px-3 text-sm outline-none focus:border-brand-500"
          />
          <label className="flex h-10 items-center gap-2 rounded-lg border border-stone-200 px-3 text-sm">
            <span className="shrink-0 text-xs text-stone-400">Days</span>
            <input type="number" min={1} max={3650} value={days} onChange={(e) => setDays(e.target.value)} className="w-full outline-none" />
          </label>
          <div className="flex h-10 items-center gap-1 rounded-lg border border-stone-200 bg-stone-50 px-3 sm:col-span-2">
            <input
              type="text" required minLength={6} placeholder="Password (type your own or ↻)"
              value={newPw} onChange={(e) => setNewPw(e.target.value)}
              className="min-w-0 flex-1 bg-transparent text-sm tabular-nums outline-none"
            />
            <button type="button" title="Copy password" onClick={() => { navigator.clipboard?.writeText(newPw); setCopied(true); setTimeout(() => setCopied(false), 1200); }} className="text-stone-400 hover:text-stone-600">
              {copied ? <Check size={14} className="text-emerald-600" /> : <Copy size={14} />}
            </button>
            <button type="button" title="Generate a random password" onClick={() => setNewPw(randomPassword())} className="font-mono text-xs text-brand-600 hover:text-brand-700">↻</button>
          </div>
          <button
            type="submit" disabled={create.isPending}
            className="h-10 rounded-lg bg-brand-500 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-brand-600 disabled:opacity-60"
          >
            {create.isPending ? 'Creating…' : 'Create account'}
          </button>
        </div>
        {(formError || create.error) && (
          <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">{formError || create.error.message}</p>
        )}
      </form>

      {/* Accounts table */}
      <section className="mt-6 overflow-hidden rounded-2xl border border-stone-200 bg-white shadow-sm">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-stone-200 bg-stone-50 text-left text-xs uppercase tracking-wide text-stone-400">
              <th className="px-4 py-3 font-semibold">Email</th>
              <th className="px-4 py-3 font-semibold">Label</th>
              <th className="px-4 py-3 font-semibold">Status</th>
              <th className="px-4 py-3 font-semibold">Expires</th>
              <th className="px-4 py-3 text-right font-semibold">Requests (30d)</th>
              <th className="px-4 py-3 text-right font-semibold">Actions</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-stone-400">Loading…</td></tr>
            )}
            {!isLoading && error && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-red-500">{error.message}</td></tr>
            )}
            {accounts.map((acct) => {
              const st = statusOf(acct);
              const self = acct.email === getAccount()?.email;
              return (
                <>
                  <tr key={acct.id} className="border-b border-stone-100 hover:bg-stone-50/60">
                    <td className="max-w-[220px] truncate px-4 py-3 font-medium text-stone-800">{acct.email}</td>
                    <td className="px-4 py-3 text-stone-500">{acct.label || '—'}</td>
                    <td className="px-4 py-3">
                      <span className={`inline-flex rounded-full px-2.5 py-0.5 text-xs font-semibold ${st.cls}`}>{st.text}</span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 tabular-nums text-stone-600">
                      {new Date(acct.expires_at).toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' })}
                    </td>
                    <td className="px-4 py-3 text-right tabular-nums text-stone-700">{(acct.requests_30d ?? 0).toLocaleString('en-US')}</td>
                    <td className="px-4 py-3">
                      <div className="flex items-center justify-end gap-1.5">
                        <button
                          type="button" disabled={busy}
                          title={`Extend +${days} days`}
                          onClick={() => runAction(extend, `/api/admin/accounts/${acct.id}/extend`, { days: Number(days) || 30 })}
                          className="inline-flex items-center gap-1 rounded-lg border border-stone-200 px-2 py-1 text-xs font-semibold text-stone-600 transition-colors hover:border-brand-300 hover:text-brand-700 disabled:opacity-50"
                        >
                          <CalendarPlus size={13} />+{days}d
                        </button>
                        <button
                          type="button" disabled={busy}
                          onClick={() => runAction(setActive, `/api/admin/accounts/${acct.id}/active`, { is_active: !acct.is_active })}
                          className={`inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-xs font-semibold transition-colors disabled:opacity-50 ${
                            acct.is_active
                              ? 'border-stone-200 text-stone-600 hover:border-red-200 hover:text-red-600'
                              : 'border-emerald-200 text-emerald-700 hover:bg-emerald-50'
                          }`}
                          title={acct.is_active ? 'Deactivate' : 'Activate'}
                        >
                          <Power size={13} />{acct.is_active ? 'Disable' : 'Enable'}
                        </button>
                        <button
                          type="button" disabled={busy}
                          title="Set a new password"
                          onClick={() => { setPwEditingId(pwEditingId === acct.id ? null : acct.id); setPwDraft(''); }}
                          className={`inline-flex items-center rounded-lg border px-2 py-1 transition-colors disabled:opacity-50 ${
                            pwEditingId === acct.id
                              ? 'border-brand-300 bg-brand-50 text-brand-700'
                              : 'border-stone-200 text-stone-500 hover:border-stone-300 hover:text-stone-700'
                          }`}
                        >
                          <KeyRound size={13} />
                        </button>
                        <button
                          type="button" disabled={busy || self}
                          title={self ? 'You cannot delete your own account' : 'Delete account permanently'}
                          onClick={() => setConfirmDeleteId(confirmDeleteId === acct.id ? null : acct.id)}
                          className="inline-flex items-center rounded-lg border border-stone-200 px-2 py-1 text-stone-500 transition-colors hover:border-red-300 hover:text-red-600 disabled:opacity-40"
                        >
                          <Trash2 size={13} />
                        </button>
                      </div>
                    </td>
                  </tr>
                  {/* Inline password editor */}
                  {pwEditingId === acct.id && (
                    <tr key={`${acct.id}-pw`} className="border-b border-stone-100 bg-brand-50/40">
                      <td colSpan={6} className="px-4 py-3">
                        <div className="flex flex-wrap items-center gap-2">
                          <span className="text-xs font-semibold uppercase tracking-wide text-stone-500">
                            New password for {acct.email}
                          </span>
                          <input
                            type="text" autoFocus required minLength={6}
                            placeholder="Type the new password…"
                            value={pwDraft}
                            onChange={(e) => setPwDraft(e.target.value)}
                            onKeyDown={(e) => { if (e.key === 'Enter') submitResetPw(acct); }}
                            className="h-9 w-64 rounded-lg border border-stone-200 bg-white px-3 text-sm tabular-nums outline-none focus:border-brand-500 focus:ring-2 focus:ring-brand-500/20"
                          />
                          <button
                            type="button" disabled={!pwDraft.trim() || resetPw.isPending}
                            onClick={() => submitResetPw(acct)}
                            className="h-9 rounded-lg bg-brand-500 px-3 text-xs font-semibold text-white transition-colors hover:bg-brand-600 disabled:opacity-50"
                          >
                            {resetPw.isPending ? 'Saving…' : 'Save password'}
                          </button>
                          <button type="button" onClick={() => setNewPw(randomPassword()) && setPwDraft(randomPassword())} className="text-xs font-semibold text-brand-600 hover:text-brand-700">
                            Generate
                          </button>
                          <button type="button" onClick={() => { setPwEditingId(null); setPwDraft(''); }} className="ml-auto inline-flex items-center gap-1 text-xs font-medium text-stone-400 hover:text-stone-600">
                            <X size={13} />Cancel
                          </button>
                        </div>
                        {resetPw.error && (
                          <p className="mt-2 text-xs text-red-600">{resetPw.error.message}</p>
                        )}
                      </td>
                    </tr>
                  )}
                  {/* Delete confirmation row */}
                  {confirmDeleteId === acct.id && (
                    <tr key={`${acct.id}-del`} className="border-b border-stone-100 bg-red-50/60">
                      <td colSpan={6} className="px-4 py-3">
                        <div className="flex flex-wrap items-center gap-3">
                          <span className="text-sm text-red-700">
                            Permanently delete <b>{acct.email}</b>? Its usage history is removed too. This cannot be undone.
                          </span>
                          <button
                            type="button"
                            onClick={() => del.mutate(acct.id, { onSuccess: () => setConfirmDeleteId(null) })}
                            disabled={del.isPending}
                            className="h-8 rounded-lg bg-red-600 px-3 text-xs font-semibold text-white transition-colors hover:bg-red-700 disabled:opacity-50"
                          >
                            {del.isPending ? 'Deleting…' : 'Yes, delete'}
                          </button>
                          <button type="button" onClick={() => setConfirmDeleteId(null)} className="text-xs font-medium text-stone-500 hover:text-stone-700">
                            Cancel
                          </button>
                        </div>
                        {del.error && <p className="mt-2 text-xs text-red-600">{del.error.message}</p>}
                      </td>
                    </tr>
                  )}
                </>
              );
            })}
            {!isLoading && !error && accounts.length === 0 && (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-stone-400">No accounts yet — create one above.</td></tr>
            )}
          </tbody>
        </table>
      </section>
      {(extend.error || setActive.error) && (
        <p className="mt-3 rounded-lg bg-red-50 px-3 py-2 text-sm text-red-600">
          {extend.error?.message || setActive.error?.message}
        </p>
      )}
    </div>
  );
}