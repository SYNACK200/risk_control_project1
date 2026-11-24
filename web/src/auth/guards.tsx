import type { ReactNode } from 'react';
import { Navigate, useLocation } from 'react-router-dom';
import { getUser } from './store';

/** 角色守卫：没登录送回登录页，登录了但角色不对送回自己的首页。 */
export function RequireRole({ role, children }: { role: 'borrower' | 'banker'; children: ReactNode }) {
  const location = useLocation();
  const user = getUser();
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  if (user.role !== role) {
    return <Navigate to={user.role === 'banker' ? '/bank' : '/app'} replace />;
  }
  return <>{children}</>;
}
