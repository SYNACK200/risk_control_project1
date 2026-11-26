import { useParams, useSearchParams } from 'react-router-dom';
import { PageHeader } from '../../ui/PageHeader';
import { Tabs } from '../../ui/Tabs';
import HistoryPage from './HistoryPage';
import ProgressPage from './ProgressPage';

type ProgressTab = 'current' | 'history';

const TABS: { key: ProgressTab; label: string }[] = [
  { key: 'current', label: '当前' },
  { key: 'history', label: '历史' },
];

/**
 * 借款侧进度页：当前任务的进度与历史提交合成一页。
 * 路由 /app/progress/:id?，页签走 ?tab=current|history。
 */
export default function ProgressHubPage() {
  const { id } = useParams();
  const [params, setParams] = useSearchParams();
  const tab: ProgressTab = params.get('tab') === 'history' ? 'history' : 'current';

  function select(next: ProgressTab) {
    setParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        if (next === 'history') merged.set('tab', 'history');
        else merged.delete('tab');
        return merged;
      },
      { replace: true },
    );
  }

  const currentId = id ? Number(id) : undefined;

  return (
    <div className="panel wide">
      <PageHeader title="处理进度" description="当前材料走到哪一步、失败了该怎么补；审核结论与风险指标仅银行侧可见。" />
      <Tabs className="page-tabs" label="处理进度" items={TABS} value={tab} onChange={select} />
      <div hidden={tab !== 'current'}>
        <ProgressPage active={tab === 'current'} />
      </div>
      <div hidden={tab !== 'history'}>
        <HistoryPage embedded currentId={currentId} />
      </div>
    </div>
  );
}
