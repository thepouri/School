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
