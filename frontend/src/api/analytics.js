import { useQuery } from '@tanstack/react-query';
import request, { buildQuery } from './client.js';

export function useAnalytics(params) {
  const key = ['analytics', params];
  const url = `/api/analytics${buildQuery(params)}`;
  return useQuery({
    queryKey: key,
    queryFn: () => request(url),
    staleTime: 5 * 60 * 1000,
  });
}