import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import App from './App.jsx';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 60_000,
      gcTime: 10 * 60_000,
      // Don't hammer the server retrying server-side failures; only retry
      // transient network/5xx once.
      retry: (failureCount, error) => {
        if (failureCount >= 1) return false;
        return !(error?.message || '').includes('(404)');
      },
      refetchOnWindowFocus: false,
      // Keep the previous page's data while the next loads — no flash of empty.
      placeholderData: (prev) => prev,
    },
  },
});

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>
);