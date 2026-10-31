import { Link } from 'react-router-dom';

export function NotFoundPage() {
  return (
    <main className="shell">
      <h1 className="page-title">页面不存在</h1>
      <p className="desc">地址可能已失效，或该页面尚未开放。</p>
      <Link className="btn" to="/">返回上传页</Link>
    </main>
  );
}
