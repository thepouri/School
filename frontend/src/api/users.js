import { useQuery } from '@tanstack/react-query';
import request, { buildQuery } from './client.js';

export function useUsers(params) {
  const key = ['users', params];
  const url = `/api/users${buildQuery(params)}`;
  return useQuery({
    queryKey: key,
    queryFn: () => request(url),
    placeholderData: (prev) => prev,
  });
}

export function useUser(id) {
  return useQuery({
    queryKey: ['user', id],
    queryFn: () => request(`/api/users/${encodeURIComponent(id)}`),
  });
}