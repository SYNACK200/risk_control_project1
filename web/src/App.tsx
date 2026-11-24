import { lazy, Suspense, useEffect } from 'react';
import { Navigate, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { RequireRole } from './auth/guards';
import LandingPage from './pages/public/LandingPage';
import LoginPage from './pages/public/LoginPage';
import RegisterPage from './pages/public/RegisterPage';
import ComingSoon from './pages/ComingSoon';

// 按角色分包：借款侧不该下载银行侧的代码
const BorrowerApp = lazy(() => import('./pages/borrower/BorrowerApp'));
const BankerApp = lazy(() => import('./pages/banker/BankerApp'));

function LegacyHashRedirect() {
  const location = useLocation();
  const navigate = useNavigate();
  useEffect(() => {
    const rawHash = window.location.hash || '';
    if (!rawHash.startsWith('#/')) return;
    const sub = rawHash.slice(1);
    const prefix = location.pathname.startsWith('/bank')
      ? '/bank'
      : location.pathname.startsWith('/app')
        ? '/app'
        : '';
    const target = sub.startsWith('/bank') || sub.startsWith('/app') || sub.startsWith('/login')
      ? sub
      : `${prefix}${sub}`;
    if (target && target !== location.pathname + location.search) {
      navigate(target, { replace: true });
    }
  }, [location.pathname, location.search, navigate]);
  return null;
}

export default function App() {
  return (
    <Suspense fallback={<div className="boot">加载中…</div>}>
      <LegacyHashRedirect />
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/register" element={<RegisterPage />} />

        <Route
          path="/app/*"
          element={
            <RequireRole role="borrower">
              <BorrowerApp />
            </RequireRole>
          }
        />
        <Route
          path="/bank/*"
          element={
            <RequireRole role="banker">
              <BankerApp />
            </RequireRole>
          }
        />

        {/* 旧地址兼容：书签不能失效 */}
        <Route path="/portal" element={<Navigate to="/" replace />} />
        <Route path="*" element={<ComingSoon title="页面不存在" detail="请从首页重新进入。" />} />
      </Routes>
    </Suspense>
  );
}
