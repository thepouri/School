import { Routes, Route } from 'react-router-dom';
import Layout from './components/Layout.jsx';
import RequireAuth from './components/RequireAuth.jsx';
import Browse from './pages/Browse.jsx';
import GroupDetail from './pages/GroupDetail.jsx';
import UserDetail from './pages/UserDetail.jsx';
import AnalyticsPage from './pages/AnalyticsPage.jsx';
import ComparePage from './pages/ComparePage.jsx';
import LoginPage from './pages/LoginPage.jsx';
import UsagePage from './pages/UsagePage.jsx';
import AdminPage from './pages/AdminPage.jsx';

export default function App() {
  return (
    <Routes>
      {/* Login renders without the app chrome */}
      <Route path="/login" element={<LoginPage />} />

      <Route element={<Layout />}>
        <Route path="/" element={<RequireAuth><Browse /></RequireAuth>} />
        <Route path="/groups/:id" element={<RequireAuth><GroupDetail /></RequireAuth>} />
        <Route path="/users/:id" element={<RequireAuth><UserDetail /></RequireAuth>} />
        <Route path="/compare" element={<RequireAuth><ComparePage /></RequireAuth>} />
        <Route path="/analytics" element={<RequireAuth><AnalyticsPage /></RequireAuth>} />
        <Route path="/usage" element={<RequireAuth><UsagePage /></RequireAuth>} />
        <Route path="/admin" element={<RequireAuth><AdminPage /></RequireAuth>} />
        <Route path="*" element={<RequireAuth><Browse /></RequireAuth>} />
      </Route>
    </Routes>
  );
}