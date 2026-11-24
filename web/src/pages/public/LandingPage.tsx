import { Link } from 'react-router-dom';
import { getUser, homeFor } from '../../auth/store';

export default function LandingPage() {
  const user = getUser();
  return (
    <div className="page-center">
      <main className="landing">
        <header className="brand">
          <i>风</i>
          <span>智能风控 · 银行流水分析</span>
        </header>

        <h1>把一份流水，读成一份可信的结论</h1>
        <p className="lede">
          借款人上传流水，系统做真实性核验、合格性判定与 40 项指标，出一份可追溯的报告；
          报告只有银行侧可见，借款侧只看得到处理进度。
        </p>

        <div className="choices">
          <Link className="choice" to={user?.role === 'banker' ? '/bank' : '/login?role=banker'}>
            <strong>银行员工</strong>
            <span>受理流水、看报告、标注模板、配阈值</span>
          </Link>
          <Link className="choice" to={user?.role === 'borrower' ? '/app' : '/login?role=borrower'}>
            <strong>借款人</strong>
            <span>上传本人流水，查看处理进度</span>
          </Link>
        </div>

        <footer className="landing-foot">
          {user ? (
            <span>
              已登录：{user.display_name || user.username} ·{' '}
              <Link to={homeFor(user)}>进入工作台</Link>
            </span>
          ) : (
            <span>
              还没有账号？<Link to="/register">注册借款人账号</Link>
            </span>
          )}
        </footer>
      </main>
    </div>
  );
}
