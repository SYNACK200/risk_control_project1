import { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import {
  listTasks,
  purgeTasks,
  reanalyzeTask,
  recycleTasks,
  restoreTasks,
  type TaskList,
  type TaskSummary,
} from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { getUser } from '../../auth/store';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';

const VERDICT_TONE: Record<string, string> = {
  未发现异常: 'ok',
  存在不一致: 'bad',
  来源可疑: 'bad',
  余额可疑: 'warn',
  无法判定: 'muted',
};

const RUNNING_STATUSES = new Set(['QUEUED', 'PENDING', 'CHECKING', 'PARSING', 'VERIFYING', 'REPORTING']);

const STATUS_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: '全部状态' },
  { value: 'DONE', label: '已完成' },
  { value: 'QUEUED', label: '排队中' },
  { value: 'PARSING', label: '解析中' },
  { value: 'NEED_SUPPLEMENT', label: '需补充材料' },
  { value: 'FAILED', label: '解析失败' },
];

function Badge({ text, tone }: { text: string; tone: string }) {
  return <span className={'badge badge-' + tone}>{text}</span>;
}

export default function TaskListPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const isAdmin = Boolean(getUser()?.is_admin);

  const [data, setData] = useState<TaskList | null>(null);
  const [query, setQuery] = useState(() => searchParams.get('q') || '');
  const [status, setStatus] = useState(() => searchParams.get('status') || '');
  const [authenticity, setAuthenticity] = useState(() => searchParams.get('authenticity') || '');
  const [source, setSource] = useState(() => searchParams.get('source') || '');
  const [bank, setBank] = useState(() => searchParams.get('bank') || '');
  const [risk, setRisk] = useState(() => searchParams.get('risk') || '');
  const [riskCode, setRiskCode] = useState(() => searchParams.get('risk_code') || '');
  const [parseLevel, setParseLevel] = useState(() => searchParams.get('parse') || '');
  const [dateFrom, setDateFrom] = useState(() => searchParams.get('date_from') || '');
  const [dateTo, setDateTo] = useState(() => searchParams.get('date_to') || '');
  const [minIncome, setMinIncome] = useState(() => searchParams.get('min_income') || '');
  const [maxIncome, setMaxIncome] = useState(() => searchParams.get('max_income') || '');
  const [trash, setTrash] = useState(false);

  const [selectedIds, setSelectedIds] = useState<number[]>([]);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(true);
  const [busyId, setBusyId] = useState<number | null>(null);
  const [batchBusy, setBatchBusy] = useState(false);
  const PAGE = 20;
  const [offset, setOffset] = useState(0);

  const load = useCallback(
    (silent = false) => {
      if (!silent) setLoading(true);
      listTasks({
        q: query || undefined,
        status: status || undefined,
        authenticity: authenticity || undefined,
        source: source || undefined,
        bank: bank || undefined,
        risk: risk || undefined,
        risk_code: riskCode || undefined,
        parse: parseLevel || undefined,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        min_income: minIncome || undefined,
        max_income: maxIncome || undefined,
        trash,
        limit: PAGE,
        offset,
      })
        .then((result) => {
          setData(result);
          setError('');
        })
        .catch((err) => setError(getErrorMessage(err, 'banker')))
        .finally(() => {
          if (!silent) setLoading(false);
        });
    },
    [query, status, authenticity, source, bank, risk, riskCode, parseLevel, dateFrom, dateTo, minIncome, maxIncome, trash, offset],
  );

  useEffect(() => {
    setSelectedIds([]);
    load();
  }, [load]);

  // 有正在处理中的任务时每 3 秒自动刷新一次状态
  useEffect(() => {
    const hasRunning = (data?.items ?? []).some((t) => RUNNING_STATUSES.has(t.status));
    if (!hasRunning || trash) return;
    const timer = window.setTimeout(() => load(true), 3000);
    return () => window.clearTimeout(timer);
  }, [data, trash, load]);

  const authFacets = data?.facets?.authenticity ?? {};
  const bankFacets = data?.facets?.bank ?? {};
  const riskFacets = data?.facets?.risk ?? {};

  const toggleSelect = (id: number) => {
    setSelectedIds((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  };

  const toggleAll = () => {
    const ids = (data?.items ?? []).map((t) => t.id);
    if (ids.length > 0 && ids.every((id) => selectedIds.includes(id))) {
      setSelectedIds([]);
    } else {
      setSelectedIds(ids);
    }
  };

  async function handleReanalyze(task: TaskSummary) {
    setBusyId(task.id);
    setError('');
    setNotice('');
    try {
      await reanalyzeTask(task.id);
      setNotice(`任务 #${task.id}（${task.biz_no}）已提交重新解析。`);
      load(true);
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusyId(null);
    }
  }

  const [pendingConfirm, setPendingConfirm] = useState<{ action: 'recycle' | 'purge'; ids: number[] } | null>(null);

  function requestConfirm(action: 'recycle' | 'purge', ids: number[]) {
    if (!ids.length) return;
    setPendingConfirm({ action, ids });
  }

  async function runBatch(action: 'recycle' | 'restore' | 'purge', ids: number[]) {
    if (!ids.length) return;
    setPendingConfirm(null);
    setBatchBusy(true);
    setError('');
    setNotice('');
    try {
      if (action === 'recycle') {
        await recycleTasks(ids);
        setNotice(`已将 ${ids.length} 条任务移入回收站。`);
      } else if (action === 'restore') {
        await restoreTasks(ids);
        setNotice(`已恢复 ${ids.length} 条任务。`);
      } else {
        await purgeTasks(ids);
        setNotice(`已彻底删除 ${ids.length} 条任务。`);
      }
      setSelectedIds([]);
      load();
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBatchBusy(false);
    }
  }

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <h1>{trash ? '流水回收站' : '受理与报告'}</h1>
          <p className="sub">
            {trash
              ? '回收站内的流水可随时恢复或由管理员彻底粉碎。'
              : `按真实性、银行与风险维度筛选查看；共 ${data?.total ?? 0} 份。`}
          </p>
        </div>
        <div className="filters">
          <Button size="sm" variant="ghost" onClick={() => load()}>
            刷新
          </Button>
          {isAdmin && (
            <Button
              size="sm"
              variant={trash ? 'primary' : 'ghost'}
              onClick={() => {
                setTrash((v) => !v);
                setOffset(0);
              }}
            >
              {trash ? '返回正式列表' : '查看回收站'}
            </Button>
          )}
        </div>
      </header>

      <div className="filters-bar">
        <div className="filters">
          <input
            className="search"
            placeholder="搜索业务号 / 流水编号"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setOffset(0);
            }}
          />
          <select
            aria-label="状态筛选"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setOffset(0);
            }}
          >
            {STATUS_OPTIONS.map((opt) => (
              <option key={opt.value} value={opt.value}>{opt.label}</option>
            ))}
          </select>
          <select
            aria-label="真实性筛选"
            value={authenticity}
            onChange={(e) => {
              setAuthenticity(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">全部真实性</option>
            {Object.entries(authFacets).map(([key, count]) => (
              <option key={key} value={key}>{key}（{count}）</option>
            ))}
          </select>
          <select
            aria-label="银行筛选"
            value={bank}
            onChange={(e) => {
              setBank(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">全部银行</option>
            {Object.entries(bankFacets).map(([key, count]) => (
              <option key={key} value={key}>{key}（{count}）</option>
            ))}
          </select>
          <select
            aria-label="风险筛选"
            value={risk}
            onChange={(e) => {
              setRisk(e.target.value);
              setOffset(0);
            }}
          >
            <option value="">全部风险</option>
            {Object.entries(riskFacets).map(([key, count]) => (
              <option key={key} value={key}>{key}（{count}）</option>
            ))}
          </select>
          <details style={{ display: 'inline-block' }}>
            <summary className="link-btn" style={{ padding: '4px 8px' }}>高级筛选（日期/收入/解析/来源）</summary>
            <div className="filters" style={{ marginTop: 8, padding: '8px 10px', background: '#f8fafc', borderRadius: 6 }}>
              <select aria-label="来源筛选" value={source} onChange={(e) => { setSource(e.target.value); setOffset(0); }}>
                <option value="">全部来源</option>
                <option value="clean">可信电子版</option>
                <option value="warn">存疑/影像</option>
              </select>
              <select aria-label="解析质量" value={parseLevel} onChange={(e) => { setParseLevel(e.target.value); setOffset(0); }}>
                <option value="">全部解析质量</option>
                <option value="ok">解析完整</option>
                <option value="warn">部分受限</option>
                <option value="fail">解析失败</option>
              </select>
              <input placeholder="风险规则码（如 R1）" value={riskCode} onChange={(e) => { setRiskCode(e.target.value); setOffset(0); }} style={{ width: 120 }} />
              <input type="date" aria-label="提交起日" value={dateFrom} onChange={(e) => { setDateFrom(e.target.value); setOffset(0); }} />
              <input type="date" aria-label="提交止日" value={dateTo} onChange={(e) => { setDateTo(e.target.value); setOffset(0); }} />
              <input type="number" placeholder="最低月均收入" value={minIncome} onChange={(e) => { setMinIncome(e.target.value); setOffset(0); }} style={{ width: 110 }} />
              <input type="number" placeholder="最高月均收入" value={maxIncome} onChange={(e) => { setMaxIncome(e.target.value); setOffset(0); }} style={{ width: 110 }} />
              <button
                type="button"
                className="link-btn"
                onClick={() => {
                  setQuery('');
                  setStatus('');
                  setAuthenticity('');
                  setSource('');
                  setBank('');
                  setRisk('');
                  setRiskCode('');
                  setParseLevel('');
                  setDateFrom('');
                  setDateTo('');
                  setMinIncome('');
                  setMaxIncome('');
                  setOffset(0);
                }}
              >
                重置全部
              </button>
            </div>
          </details>
        </div>

        {isAdmin && selectedIds.length > 0 && (
          <div className="filters">
            <span className="small muted">已选 {selectedIds.length} 条：</span>
            {trash ? (
              <>
                <Button size="sm" variant="ghost" disabled={batchBusy} onClick={() => void runBatch('restore', selectedIds)}>
                  批量恢复
                </Button>
                <Button size="sm" variant="ghost" disabled={batchBusy} onClick={() => requestConfirm('purge', selectedIds)}>
                  彻底删除
                </Button>
              </>
            ) : (
              <Button size="sm" variant="ghost" disabled={batchBusy} onClick={() => requestConfirm('recycle', selectedIds)}>
                移入回收站
              </Button>
            )}
          </div>
        )}
      </div>

      {pendingConfirm ? (
        <div className="alert warn" style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
          <span>
            {pendingConfirm.action === 'purge'
              ? `确定彻底删除选中的 ${pendingConfirm.ids.length} 条任务及其流水、报告与原件？此操作不可恢复。`
              : `确定将选中的 ${pendingConfirm.ids.length} 条任务移入回收站？`}
          </span>
          <div className="filters">
            <Button size="sm" disabled={batchBusy} onClick={() => void runBatch(pendingConfirm.action, pendingConfirm.ids)}>确认</Button>
            <Button size="sm" variant="ghost" onClick={() => setPendingConfirm(null)}>再想想</Button>
          </div>
        </div>
      ) : null}
      {error ? <Notice>{error}</Notice> : null}
      {notice ? <Notice tone="ok">{notice}</Notice> : null}
      {loading && !data ? <p className="muted">加载中…</p> : null}

      {data ? (
        <table className="grid">
          <thead>
            <tr>
              {isAdmin && (
                <th style={{ width: 28 }}>
                  <input
                    type="checkbox"
                    aria-label="全选本页"
                    checked={data.items.length > 0 && data.items.every((t) => selectedIds.includes(t.id))}
                    onChange={toggleAll}
                  />
                </th>
              )}
              <th>业务号 / 银行</th>
              <th>真实性</th>
              <th>解析与受限</th>
              <th>风险线索</th>
              <th>期间 / 月均收入 / DTI</th>
              <th>材料</th>
              <th>账期</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            {data.items.map((task: TaskSummary) => {
              const isDone = task.status === 'DONE';
              return (
                <tr
                  key={task.id}
                  className={isDone ? 'clickable' : ''}
                  onClick={() => isDone && navigate('/bank/report/' + task.id)}
                >
                  {isAdmin && (
                    <td onClick={(e) => e.stopPropagation()}>
                      <input
                        type="checkbox"
                        aria-label={`选择 ${task.biz_no}`}
                        checked={selectedIds.includes(task.id)}
                        onChange={() => toggleSelect(task.id)}
                      />
                    </td>
                  )}
                  <td>
                    <strong>{task.biz_no}</strong>
                    <div className="muted small">
                      #{task.id} · {task.bank_name || '未识别银行'} ·{' '}
                      {task.carrier === 'electronic' ? '电子件' : task.carrier === 'image' ? '影像件' : task.carrier || '截图'}
                    </div>
                  </td>
                  <td>
                    <Badge
                      text={isDone ? (task.verdict ?? '待复核') : (STATUS_OPTIONS.find((o) => o.value === task.status)?.label ?? task.status)}
                      tone={isDone ? (VERDICT_TONE[task.verdict ?? ''] ?? 'muted') : 'warn'}
                    />
                    <div className="muted small">{task.authenticity?.label}</div>
                  </td>
                  <td>
                    <div>{task.parse?.label}</div>
                    <div className="muted small">
                      {task.parse?.txn_count ?? 0} 笔 · 指标 {task.parse?.metrics_valued ?? 0}/{task.parse?.metrics_total ?? 40}
                      {task.limitations ? ` · 受限 ${task.limitations}` : ''}
                    </div>
                  </td>
                  <td>
                    <div>{task.risk?.label}</div>
                    <div className="muted small">{task.risk?.count ?? 0} 条 · {task.source?.label || '—'}</div>
                  </td>
                  <td className="mono small">
                    <div>{task.monthly_income ?? '—'}/月</div>
                    <div className="muted">总额 {task.income ?? '—'} · DTI {task.dti ?? '—'}</div>
                  </td>
                  <td className="small muted">{task.materials ?? 1} 份</td>
                  <td className="small">
                    {task.period_start ?? '—'} ~ {task.period_end ?? '—'}
                  </td>
                  <td className="actions-cell" onClick={(e) => e.stopPropagation()}>
                    {!trash ? (
                      <>
                        {isDone && (
                          <Link className="link-btn" to={'/bank/report/' + task.id}>
                            报告
                          </Link>
                        )}
                        <button
                          type="button"
                          className="link-btn"
                          onClick={() => navigate('/bank/annotate?taskId=' + task.id)}
                        >
                          调框
                        </button>
                        <button
                          type="button"
                          className="link-btn"
                          disabled={busyId === task.id}
                          onClick={() => void handleReanalyze(task)}
                        >
                          {busyId === task.id ? '重跑中…' : '重跑'}
                        </button>
                        {isAdmin && (
                          <button
                            type="button"
                            className="link-btn danger"
                            onClick={() => requestConfirm('recycle', [task.id])}
                          >
                            删除
                          </button>
                        )}
                      </>
                    ) : (
                      <>
                        {isDone && (
                          <Link className="link-btn" to={'/bank/report/' + task.id}>
                            复核报告
                          </Link>
                        )}
                        {isAdmin && (
                          <>
                            <button
                              type="button"
                              className="link-btn"
                              onClick={() => void runBatch('restore', [task.id])}
                            >
                              恢复
                            </button>
                            <button
                              type="button"
                              className="link-btn danger"
                              onClick={() => requestConfirm('purge', [task.id])}
                            >
                              粉碎
                            </button>
                          </>
                        )}
                      </>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      ) : null}

      {data && data.items.length === 0 ? <p className="muted">没有符合条件的流水。</p> : null}

      {data && data.total > PAGE ? (
        <div className="pager">
          <button className="btn btn-ghost" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>
            上一页
          </button>
          <span className="muted small">
            第 {offset + 1}–{Math.min(offset + PAGE, data.total)} 条 / 共 {data.total} 条
          </span>
          <button
            className="btn btn-ghost"
            disabled={offset + PAGE >= data.total}
            onClick={() => setOffset(offset + PAGE)}
          >
            下一页
          </button>
        </div>
      ) : null}
    </div>
  );
}
