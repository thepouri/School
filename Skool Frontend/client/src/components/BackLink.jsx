import { useNavigate } from 'react-router-dom';
import { ArrowLeft } from 'lucide-react';

// Back link that returns to the previous page (filtered list, prior detail)
// instead of resetting to home. Falls back to "/" when there is no history.
export default function BackLink({ children }) {
  const navigate = useNavigate();
  const canGoBack =
    typeof window !== 'undefined' &&
    window.history.length > 1 &&
    (window.history.state?.idx ?? 0) > 0;

  return (
    <button
      type="button"
      onClick={() => (canGoBack ? navigate(-1) : navigate('/'))}
      className="mb-4 inline-flex items-center gap-1 text-sm font-medium text-stone-500 transition-colors hover:text-stone-800"
    >
      <ArrowLeft size={15} />
      {children}
    </button>
  );
}
