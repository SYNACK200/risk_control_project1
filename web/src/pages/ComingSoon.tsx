import { Link } from 'react-router-dom';

export default function ComingSoon({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="page-center">
      <div className="card">
        <h1>{title}</h1>
        <p className="sub">{detail}</p>
        <Link className="btn btn-ghost" to="/">
          返回首页
        </Link>
      </div>
    </div>
  );
}
