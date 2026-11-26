import { Link } from 'react-router-dom';
import { PageHeader } from '../../ui/PageHeader';

type Group = { title: string; items: { label: string; to: string }[] };

/** 银行侧 404：把入口按导航分组列出来，比一句「页面不存在」有用。 */
export default function NotFoundPage({ groups }: { groups: Group[] }) {
  return (
    <div className="panel wide">
      <PageHeader
        title="页面不存在"
        description="这个地址没有对应的工作台页面，可能是旧书签或链接写错了。下面是全部入口。"
        actions={
          <Link className="btn" to="/bank">
            返回看板
          </Link>
        }
      />
      <div className="notfound-groups">
        {groups.map((group) => (
          <section key={group.title} className="notfound-group">
            <h2>{group.title}</h2>
            <ul>
              {group.items.map((item) => (
                <li key={item.to}>
                  <Link to={item.to}>{item.label}</Link>
                </li>
              ))}
            </ul>
          </section>
        ))}
      </div>
    </div>
  );
}
