import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import request, { post, buildQuery } from './client.js';

// Login is a plain call (no token yet) — returns {token, account}.
export async function login(email, password) {
  return post('/api/auth/login', { email, password });
}

export function useMyUsage() {
  return useQuery({
    queryKey: ['me-usage'],
    queryFn: () => request('/api/me/usage'),
    staleTime: 60 * 1000,
  });
}

export function useAdminAccounts() {
  return useQuery({
    queryKey: ['admin-accounts'],
    queryFn: () => request('/api/admin'),
    staleTime: 30 * 1000,
  });
}

function useAdminMutation(invalidate) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ path, body }) => post(path, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: [invalidate] }),
  });
}

export function useCreateAccount() {
  return useAdminMutation('admin-accounts');
}
export function useExtendAccount() {
  return useAdminMutation('admin-accounts');
}
export function useSetActive() {
  return useAdminMutation('admin-accounts');
}
export function useResetPassword() {
  return useAdminMutation('admin-accounts');
}

export function useMetrics(kind, id, params) {
  return useQuery({
    queryKey: ['metrics', kind, id, params],
    queryFn: () => request(`/api/metrics/${kind}/${id}${buildQuery(params)}`),
    staleTime: 5 * 60 * 1000,
  });
}