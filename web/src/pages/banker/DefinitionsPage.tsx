import { useSearchParams } from 'react-router-dom';
import GlossaryPage from './GlossaryPage';
import MetricDefsPage from './MetricDefsPage';
import VerificationDefsPage from './VerificationDefsPage';
import { PageHeader } from '../../ui/PageHeader';
import { Tabs } from '../../ui/Tabs';

type DefTab = 'metric' | 'verification' | 'glossary';

const TAB_ITEMS: { key: DefTab; label: string }[] = [
  { key: 'metric', label: '指标口径' },
  { key: 'verification', label: '核验口径' },
  { key: 'glossary', label: '术语' },
];

function toDefTab(raw: string | null): DefTab {
  return TAB_ITEMS.some((item) => item.key === raw) ? (raw as DefTab) : 'metric';
}

/**
 * 口径中心：指标口径 / 核验口径 / 术语三合一。
 *
 * 三个页签的内容直接复用原有三页；全部保持挂载、只隐藏不销毁，
 * 这样来回切换时搜索词和筛选不会丢。
 */
export default function DefinitionsPage() {
  const [params, setParams] = useSearchParams();
  const tab = toDefTab(params.get('tab'));

  function select(next: DefTab) {
    setParams(
      (prev) => {
        const merged = new URLSearchParams(prev);
        merged.set('tab', next);
        return merged;
      },
      { replace: true },
    );
  }

  return (
    <div className="panel wide">
      <PageHeader
        title="口径中心"
        description="指标怎么算、核验怎么验、术语怎么解释，都在这里查；口径只增不改，历史报告按当时版本解释。"
      />
      <Tabs className="page-tabs" label="口径中心" items={TAB_ITEMS} value={tab} onChange={select} />
      <div hidden={tab !== 'metric'}>
        <MetricDefsPage embedded />
      </div>
      <div hidden={tab !== 'verification'}>
        <VerificationDefsPage embedded />
      </div>
      <div hidden={tab !== 'glossary'}>
        <GlossaryPage embedded />
      </div>
    </div>
  );
}
