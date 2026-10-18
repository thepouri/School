import { Navigate, useLocation } from 'react-router-dom';
import { isLoggedIn } from '../lib/auth.js';

// Gate for protected routes — bounces to /login preserving the destination.
export default function RequireAuth({ children }) {
  const location = useLocation();
  if (!isLoggedIn()) {
    const next = encodeURIComponent(location.pathname + location.search);
    return <Navigate to={`/login?next=${next}`} replace />;
  }
  return children;
}