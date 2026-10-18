import { useQuery } from '@tanstack/react-query';
import request, { buildQuery } from './client.js';

export function useGroups(params) {
  const key = ['groups', params];
  const url = `/api/groups${buildQuery(params)}`;
  return useQuery({
    queryKey: key,
    queryFn: () => request(url),
    placeholderData: (prev) => prev, // smooth pagination / filter changes
  });
}

export function useGroup(id) {
  return useQuery({
    queryKey: ['group', id],
    queryFn: () => request(`/api/groups/${encodeURIComponent(id)}`),
  });
}

export function useCompareGroups(ids) {
  const key = ['compare-groups', ids];
  const url = `/api/groups/compare?ids=${encodeURIComponent(ids.join(','))}`;
  return useQuery({
    queryKey: key,
    queryFn: () => request(url),
    enabled: ids.length > 0,
    placeholderData: (prev) => prev,
  });
}