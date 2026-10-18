import { Outlet, useLocation } from 'react-router-dom';
import Header from './Header.jsx';

export default function Layout() {
  const { pathname } = useLocation();
  const isDetail = pathname.startsWith('/groups/') || pathname.startsWith('/users/');
  return (
    <div className="min-h-screen bg-[#fafaf9]">
      <Header onBrowse={!isDetail} />
      <main className="mx-auto w-full max-w-7xl px-4 sm:px-6 lg:px-8">
        <Outlet />
      </main>
    </div>
  );
}