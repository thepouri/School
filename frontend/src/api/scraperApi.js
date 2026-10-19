import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import request, { post, buildQuery } from './client.js';

/**
 * Fetch real-time scraper daemon and job status.
 * Automatically polls every 5 seconds.
 */
export function useScraperStatus(options = {}) {
  return useQuery({
    queryKey: ['admin-scraper-status'],
    queryFn: () => request('/api/admin/scraper/status'),
    refetchInterval: 5000,
    staleTime: 3000,
    ...options,
  });
}

/**
 * Mutation to manually trigger a scraper job.
 * Accepts a mode string ("refresh", "discovery", "all", "missing_owners")
 * or an object `{ mode: string }`.
 */
export function useTriggerJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (variables) => {
      const body = typeof variables === 'string' ? { mode: variables } : variables;
      return post('/api/admin/scraper/trigger', body);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-scraper-status'] });
      qc.invalidateQueries({ queryKey: ['admin-scraper-logs'] });
    },
  });
}

export const useTriggerScraper = useTriggerJob;

/**
 * Fetch scraper execution logs and job history.
 * Supports limit and optional jobId filtering.
 */
export function useScraperLogs(limit = 50, jobId = null, options = {}) {
  const query = buildQuery({ limit, job_id: jobId });
  return useQuery({
    queryKey: ['admin-scraper-logs', limit, jobId],
    queryFn: () => request(`/api/admin/scraper/logs${query}`),
    refetchInterval: 10000,
    staleTime: 5000,
    ...options,
  });
}

/**
 * Fetch current scraper schedule and interval settings.
 */
export function useScraperSettings(options = {}) {
  return useQuery({
    queryKey: ['admin-scraper-settings'],
    queryFn: () => request('/api/admin/scraper/settings'),
    staleTime: 30000,
    ...options,
  });
}

/**
 * Mutation to update scraper schedule parameters.
 */
export function useUpdateScraperSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (settings) => post('/api/admin/scraper/settings', settings),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-scraper-settings'] });
      qc.invalidateQueries({ queryKey: ['admin-scraper-status'] });
    },
  });
}

/**
 * Mutation to cancel/abort an active or queued scraper job.
 */
export function useCancelJob() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobId) => post(`/api/admin/scraper/jobs/${jobId}/cancel`, {}),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-scraper-status'] });
      qc.invalidateQueries({ queryKey: ['admin-scraper-logs'] });
    },
  });
}

/**
 * Mutation to import scraped JSON dataset.
 */
export function useImportScraperData() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload) => post('/api/admin/scraper/import', payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['admin-scraper-status'] });
      qc.invalidateQueries({ queryKey: ['admin-scraper-logs'] });
    },
  });
}

/**
 * Trigger download of full scraped dataset export as a JSON file.
 */
export async function downloadScraperExport(includeMetrics = true) {
  const token = localStorage.getItem('token');
  const res = await fetch(`/api/admin/scraper/export?include_metrics=${includeMetrics}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    throw new Error(err.error || `Export failed with status ${res.status}`);
  }
  const blob = await res.blob();
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  const cd = res.headers.get('content-disposition');
  let filename = 'skool_export.json';
  if (cd && cd.includes('filename=')) {
    filename = cd.split('filename=')[1].replace(/["']/g, '');
  }
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  window.URL.revokeObjectURL(url);
}

