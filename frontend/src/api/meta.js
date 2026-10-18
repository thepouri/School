import { useQuery } from '@tanstack/react-query';
import request from './client.js';

export function useMeta() {
  return useQuery({
    queryKey: ['meta'],
    queryFn: () => request('/api/meta'),
    staleTime: 5 * 60 * 1000,
  });
}