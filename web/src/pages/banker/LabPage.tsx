import { useEffect, useMemo, useRef, useState } from 'react';
import {
  computeFileFeatures,
  deleteCustom,
  evaluate,
  evaluateCode,
  listCustom,
  listFeatures,
  listOperators,
  listSamples,
  saveCustom,
  type ComputeFileResult,
  type CustomFeature,
  type EvaluateResult,
  type LabFeature,
  type LabOperator,
  type LabSample,
} from '../../api/lab';
import { getErrorMessage } from '../../api/errors';
import { Button } from '../../ui/Button';
import { Notice } from '../../ui/Notice';

const FAMILY_LABEL: Record<string, string> = {
  numeric: '数值',
  logic: '逻辑与比较',
  group: '分组',
  window: '时间窗',
  filter: '过滤',
};

const COLUMNS = [
  { name: 'amount', note: '金额（Decimal，带正负）' },
  { name: 'direction', note: "'in' 入账 / 'out' 出账" },
  { name: 'balance', note: '余额' },
  { name: 'summary', note: '摘要（文本）' },
  { name: 'counterparty_name', note: '对方户名' },
  { name: 'txn_date', note: '交易日期 YYYY-MM-DD' },
  { name: 'trade_time', note: '交易时分 HH:MM:SS' },
  { name: 'reference_no', note: '流水号' },
  { name: 'hour', note: '小时（0–23，来自 trade_time）' },
  { name: 'month', note: '月份（1–12）' },
  { name: 'dow', note: '星期（0 = 周一）' },
];

const CURL_EXAMPLE = `curl -X POST http://127.0.0.1:8010/api/v1/features/compute \\
  -H "Authorization: Bearer <TOKEN>" \\
  -H "Content-Type: application/json" \\
  -d '{"codes":["f_txn_count","f_in_total","f_debt_service_ratio"],"rows":[{"txn_date":"2026-01-05","amount":"1000","direction":"in"}]}'`;

const NOTES = [
  "聚合要带 where：count(where=direction=='out')，不写 where 就是全部行。",
  "文本要用引号：in_lexicon(name='salary')、contains(word='工资')。",
  "产出是一列数的算子（zscore / pct_rank / in_hours / contains）要跟比较或聚合搭配：count(where=zscore() > 3)。",
  "时间衍生字段 hour / month / dow 可直接引用：count(where=hour>=22) / count()。",
  "缺列不报 0，返回空值 + 原因；报告里会写成「不可算」，不会悄悄算成 0。",
];

const EXAMPLES = [
  { label: '出账总额', expr: "sum(amount, where=direction=='out')" },
  { label: '月均出账', expr: 'sum(amount) / coverage_months()' },
  { label: '开方', expr: "sqrt(sum(amount, where=direction=='out'))" },
  { label: '平方', expr: "pow(sum(amount, where=direction=='in') / 1000, 2)" },
  { label: '对数', expr: "log10(sum(amount, where=direction=='out'))" },
  { label: '夜间占比', expr: 'count(where=hour>=22) / count()' },
  { label: '工资入账占比', expr: "sum(amount, where=(direction=='in') & in_lexicon(name='salary')) / sum(amount, where=direction=='in')" },
  { label: '网贷出账占比', expr: "sum(amount, where=(direction=='out') & in_lexicon(name='online_loan')) / sum(amount, where=direction=='out')" },
  { label: '大额异常笔数', expr: 'count(where=robust_zscore() > 3)' },
  { label: '对手集中度 HHI', expr: "share_square_sum(by='counterparty_name')" },
  { label: '月度序列积分', expr: "integrate(monthly_values(agg='count'))" },
  { label: '月度序列微分', expr: "derivative(monthly_values(agg='count'))" },
  { label: '条件判断', expr: "if_else(sum(amount, where=direction=='in') > 10000, '高收入', '普通')" },
];

/**
 * 特征 Lab。
 *
 * 这一页的存在理由：特征衍生（通用能力）与个人流水风控特征（域内口径）是两件事——
 * 前者是我们提供的算子与表达式引擎，后者是建立在它上面的具体口径。
 * Lab 把两者摆在一起：左边是算子与内置特征库，右边是随手试算。
 */
export default function LabPage() {
  const [operators, setOperators] = useState<LabOperator[]>([]);
  const [features, setFeatures] = useState<LabFeature[]>([]);
  const [samples, setSamples] = useState<LabSample[]>([]);
  const [sample, setSample] = useState('clean/icbc.pdf');
  const [expr, setExpr] = useState("sum(amount, where=direction=='out')");
  const [result, setResult] = useState<EvaluateResult | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [filter, setFilter] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('all');
  const [tab, setTab] = useState<'features' | 'operators' | 'custom'>('features');
  const [custom, setCustom] = useState<CustomFeature[]>([]);
  const [saveCode, setSaveCode] = useState('');
  const [saveName, setSaveName] = useState('');
  const [saveUnit, setSaveUnit] = useState('');
  const [saveNote, setSaveNote] = useState('');
  const [activeOp, setActiveOp] = useState<LabOperator | null>(null);
  const [activeFeat, setActiveFeat] = useState<LabFeature | null>(null);
  const [fileBusy, setFileBusy] = useState(false);
  const [fileResult, setFileResult] = useState<ComputeFileResult | null>(null);
  const pdfInputRef = useRef<HTMLInputElement | null>(null);

  const reloadCustom = () => {
    listCustom()
      .then((data) => setCustom(data.items))
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  };

  useEffect(() => {
    Promise.all([listOperators(), listFeatures(), listSamples()])
      .then(([ops, defs, list]) => {
        setOperators(ops.items);
        setFeatures(defs.items);
        setSamples(list.items);
        reloadCustom();
        if (list.items.length && !list.items.some((item) => item.name === sample)) {
          setSample(list.items[0].name);
        }
      })
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  }, []);

  const grouped = useMemo(() => {
    const keyword = filter.trim();
    const out: Record<string, LabOperator[]> = {};
    for (const item of operators) {
      if (keyword && !item.key.includes(keyword) && !item.detail.includes(keyword)) continue;
      (out[item.family] ??= []).push(item);
    }
    return out;
  }, [operators, filter]);

  const categories = useMemo(() => {
    const set = new Set<string>();
    for (const item of features) {
      set.add(item.category || '基础统计');
    }
    return ['all', ...Array.from(set)];
  }, [features]);

  const shownFeatures = useMemo(() => {
    const keyword = filter.trim().toLowerCase();
    return features.filter((item) => {
      if (categoryFilter !== 'all' && (item.category || '基础统计') !== categoryFilter) return false;
      if (!keyword) return true;
      return (
        item.code.toLowerCase().includes(keyword) ||
        item.name.toLowerCase().includes(keyword) ||
        (item.description || '').toLowerCase().includes(keyword)
      );
    });
  }, [features, filter, categoryFilter]);

  async function run() {
    setBusy(true);
    setError('');
    try {
      setResult(await evaluate(sample, expr));
    } catch (err) {
      setResult(null);
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setBusy(false);
    }
  }

  async function runAllOnPdf(file: File) {
    setFileBusy(true);
    setError('');
    try {
      const res = await computeFileFeatures(file, file.name);
      setFileResult(res);
    } catch (err) {
      setFileResult(null);
      setError(getErrorMessage(err, 'banker'));
    } finally {
      setFileBusy(false);
    }
  }

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <h1>特征 Lab</h1>
          <p className="sub">
            特征衍生是通用能力，风控特征是它的具体口径。这里左边是算子与内置特征，右边随手试算——
            试算只跑合成样本，不接触真实客户流水。
          </p>
        </div>
      </header>

      {error ? <Notice>{error}</Notice> : null}

      <details className="lab-api">
        <summary>特征 API（目录 / 详情 / 计算，含自定义特征）</summary>
        <table className="grid compact">
          <thead><tr><th>方法</th><th>路径</th><th>用途</th></tr></thead>
          <tbody>
            <tr><td>GET</td><td><code>/api/v1/features</code></td><td>全部特征目录（内置 + 自定义）</td></tr>
            <tr><td>GET</td><td><code>/api/v1/features/&#123;code&#125;</code></td><td>单个特征的定义与表达式</td></tr>
            <tr><td>POST</td><td><code>/api/v1/features/compute</code></td><td>给交易行或样本，算全部/指定特征</td></tr>
            <tr><td>POST</td><td><code>/api/v1/features/compute-file</code></td><td>直接传 PDF，解析 + 计算一次完成</td></tr>
            <tr><td>POST</td><td><code>/api/v1/lab/evaluate</code></td><td>试算一条表达式（返回单值）</td></tr>
          </tbody>
        </table>
        <pre className="json-box">{CURL_EXAMPLE}</pre>
      </details>

      <div className="lab">
        <aside className="lab-side">
          <div className="tabs small-tabs">
            <button className={tab === 'features' ? 'active' : ''} onClick={() => setTab('features')}>
              内置特征（{features.length}）
            </button>
            <button className={tab === 'operators' ? 'active' : ''} onClick={() => setTab('operators')}>
              算子（{operators.length}）
            </button>
            <button className={tab === 'custom' ? 'active' : ''} onClick={() => setTab('custom')}>
              自定义（{custom.length}）
            </button>
          </div>
          <input
            className="search lab-search"
            placeholder={tab === 'features' ? '搜索特征（代码/名称/说明）' : tab === 'operators' ? '搜索算子' : '搜索自定义特征'}
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
          />
          {tab === 'features' ? (
            <select
              className="search lab-search"
              value={categoryFilter}
              onChange={(event) => setCategoryFilter(event.target.value)}
              aria-label="特征分类筛选"
            >
              <option value="all">全部分类（{features.length}）</option>
              {categories.filter((c) => c !== 'all').map((cat) => (
                <option key={cat} value={cat}>{cat}</option>
              ))}
            </select>
          ) : null}

          <div className="lab-list">
            {tab === 'custom' ? (
              custom.length ? (
                custom.map((item) => (
                  <div key={item.code} className="lab-item lab-custom">
                    <span className="lab-code">{item.code}</span>
                    <span className="lab-name">{item.name} · v{item.version}</span>
                    <span className="lab-actions">
                      <button className="link-btn" onClick={() => { setExpr(item.expr); setSample(sample); }}>
                        填入
                      </button>
                      <button
                        className="link-btn"
                        onClick={() => {
                          evaluateCode(sample, item.code)
                            .then(setResult)
                            .catch((err) => setError(getErrorMessage(err, 'banker')));
                        }}
                      >
                        运行
                      </button>
                      <button
                        className="link-btn danger"
                        onClick={() => {
                          deleteCustom(item.code)
                            .then(reloadCustom)
                            .catch((err) => setError(getErrorMessage(err, 'banker')));
                        }}
                      >
                        删除
                      </button>
                    </span>
                  </div>
                ))
              ) : (
                <p className="muted small">还没有自定义特征。在右边写好表达式后点「保存为特征」。</p>
              )
            ) : tab === 'features'
              ? shownFeatures.map((item) => (
                  <button
                    key={item.code}
                    className={'lab-item' + (activeFeat?.code === item.code ? ' active' : '')}
                    onClick={() => {
                      setActiveFeat(item);
                      setActiveOp(null);
                      setExpr(String(item.body));
                    }}
                    title={item.description || '点击填入表达式'}
                  >
                    <span className="lab-code">{item.code}</span>
                    <span className="lab-name">
                      {item.name}
                      {item.category ? <span className="muted small"> · {item.category}</span> : null}
                    </span>
                    <span className="muted small">{item.unit || '—'}</span>
                  </button>
                ))
              : Object.entries(grouped).map(([family, items]) => (
                  <div key={family} className="lab-group">
                    <span className="sider-title">{FAMILY_LABEL[family] ?? family}</span>
                    {items.map((item) => (
                      <button
                        key={item.key}
                        className={'lab-item' + (activeOp?.key === item.key ? ' active' : '')}
                        onClick={() => {
                          setActiveOp(item);
                          setExpr((prev) => insertOperator(prev, item.key));
                        }}
                        title={item.detail}
                      >
                        <span className="lab-code">{signature(item)}</span>
                        <span className="lab-name">{item.detail}</span>
                      </button>
                    ))}
                  </div>
                ))}
          </div>
        </aside>

        <section className="lab-main">
          <div className="lab-toolbar">
            <select value={sample} onChange={(event) => setSample(event.target.value)}>
              {samples.map((item) => (
                <option key={item.name} value={item.name}>{item.name}</option>
              ))}
            </select>
            <Button onClick={() => void run()} disabled={busy}>
              {busy ? '计算中…' : '运行单条表达式'}
            </Button>
            <input
              ref={pdfInputRef}
              type="file"
              accept=".pdf"
              style={{ display: 'none' }}
              onChange={(event) => {
                const f = event.target.files?.[0];
                event.target.value = '';
                if (f) void runAllOnPdf(f);
              }}
            />
            <Button
              variant="ghost"
              onClick={() => pdfInputRef.current?.click()}
              disabled={fileBusy}
            >
              {fileBusy ? '正在解析并批量试算…' : '上传 PDF 批量试算全部特征'}
            </Button>
          </div>

          <textarea
            className="lab-editor"
            value={expr}
            spellCheck={false}
            onChange={(event) => setExpr(event.target.value)}
            rows={4}
          />

          <div className="lab-guide">
            <div className="lab-guide-block">
              <span className="lab-guide-title">可用字段（点一下插入）</span>
              <div className="chips">
                {COLUMNS.map((column) => (
                  <button
                    key={column.name}
                    className="chip"
                    title={column.note}
                    onClick={() => setExpr((prev) => (prev.trim() ? prev + ' ' + column.name : column.name))}
                  >
                    {column.name}
                  </button>
                ))}
              </div>
            </div>

            {activeOp ? (
              <div className="lab-guide-block">
                <span className="lab-guide-title">
                  {activeOp.key} · {FAMILY_LABEL[activeOp.family] ?? activeOp.family} · {activeOp.kind}
                </span>
                <p className="small muted">{activeOp.detail}</p>
                {activeOp.params.length ? (
                  <table className="grid compact">
                    <thead><tr><th>参数</th><th>类型</th><th>默认</th><th>说明</th></tr></thead>
                    <tbody>
                      {activeOp.params.map((param) => (
                        <tr key={param.name}>
                          <td><code>{param.name}</code></td>
                          <td className="small muted">{param.type}</td>
                          <td className="small muted">{param.default === null || param.default === undefined ? '—' : String(param.default)}</td>
                          <td className="small muted">{param.detail || '—'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                ) : (
                  <p className="muted small">这个算子没有参数，直接调用即可。</p>
                )}
                <p className="muted small">函数签名：<code>{signature(activeOp)}</code></p>
              </div>
            ) : activeFeat ? (
              <div className="lab-guide-block">
                <span className="lab-guide-title">
                  {activeFeat.code} · {activeFeat.name}
                  {activeFeat.category ? `（${activeFeat.category}）` : ''}
                </span>
                <p className="small muted">{activeFeat.description || '内置衍生特征，已在左侧点击填入表达式编辑器，可直接点「运行单条表达式」试算。'}</p>
                <p className="small muted">单位：{activeFeat.unit || '—'} · 形式：{activeFeat.form} · 版本：{activeFeat.version || 'v1'}</p>
              </div>
            ) : (
              <div className="lab-guide-block">
                <span className="lab-guide-title">用法</span>
                <p className="muted small">点左边任意内置特征或算子，这里会列出业务含义、参数与签名。</p>
              </div>
            )}

            <div className="lab-guide-block">
              <span className="lab-guide-title">写法提示</span>
              <ul className="plain">
                {NOTES.map((note, index) => <li key={index}>{note}</li>)}
              </ul>
            </div>
          </div>

          <div className="lab-examples">
            {EXAMPLES.map((item) => (
              <button key={item.label} className="link-btn" onClick={() => setExpr(item.expr)}>
                {item.label}
              </button>
            ))}
          </div>

          <div className="lab-save">
            <input placeholder="编号（如 out_night_share）" value={saveCode} onChange={(e) => setSaveCode(e.target.value)} />
            <input placeholder="名称（如 夜间出账占比）" value={saveName} onChange={(e) => setSaveName(e.target.value)} />
            <input placeholder="单位（可空）" value={saveUnit} onChange={(e) => setSaveUnit(e.target.value)} />
            <Button
              onClick={() => {
                saveCustom({ code: saveCode, name: saveName, expr, unit: saveUnit })
                  .then(() => {
                    setSaveNote('已保存：' + saveCode + '（新版本会顶替旧版本，旧版本保留在历史里）');
                    setSaveCode('');
                    setSaveName('');
                    setSaveUnit('');
                    reloadCustom();
                  })
                  .catch((err) => setSaveNote(getErrorMessage(err, 'banker')));
              }}
            >
              保存为特征
            </Button>
          </div>
          {saveNote ? <p className="muted small">{saveNote}</p> : null}

          {result ? (
            <div className="lab-result">
              <div className="score">
                <span className="score-value">{formatValue(result.value)}</span>
                <span className="muted small">
                  {result.type} · 样本 {result.rows} 笔
                </span>
              </div>
              {result.preview ? (
                <div className="scroll small">
                  <code>{JSON.stringify(result.preview)}</code>
                </div>
              ) : null}
              {result.notes.length ? (
                <ul className="plain">
                  {result.notes.map((note, index) => (
                    <li key={index}>{note}</li>
                  ))}
                </ul>
              ) : null}
            </div>
          ) : (
            <p className="muted small">输入表达式后点运行。缺列的算子会返回空值并给出原因，不会填 0。</p>
          )}

          {fileResult ? (
            <div className="card" style={{ marginTop: 12 }}>
              <div className="row-between">
                <h3>
                  真实文件批量试算结果：{fileResult.file}（共 {fileResult.rows} 笔流水 · {fileResult.feature_count} 个特征）
                </h3>
                <button className="link-btn" onClick={() => setFileResult(null)}>收起</button>
              </div>
              <div className="scroll" style={{ maxHeight: 340 }}>
                <table className="grid compact">
                  <thead>
                    <tr>
                      <th>特征编码</th>
                      <th>名称</th>
                      <th>计算值</th>
                      <th>单位</th>
                      <th>说明 / 不可算原因</th>
                    </tr>
                  </thead>
                  <tbody>
                    {fileResult.features.map((f) => (
                      <tr key={f.code}>
                        <td><code>{f.code}</code></td>
                        <td>{f.name}</td>
                        <td><b>{f.value === null ? '不可算' : String(f.value)}</b></td>
                        <td className="muted small">{f.unit || '—'}</td>
                        <td className="muted small">{f.reason || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          ) : null}
        </section>
      </div>
    </div>
  );
}

function signature(op: LabOperator): string {
  if (!op.params.length) return op.key + '()';
  const inner = op.params
    .map((param) => {
      if (param.type === 'str') return param.name + "='…'";
      if (param.default === null || param.default === undefined) return param.name;
      return param.name + '=' + String(param.default);
    })
    .join(', ');
  return op.key + '(' + inner + ')';
}

function insertOperator(prev: string, key: string) {
  return prev.trim() ? prev + ' ' + key + '()' : key + '()';
}

function formatValue(value: EvaluateResult['value']) {
  if (value === null) return '空值';
  if (Array.isArray(value)) return '[' + value.map((item) => item ?? '空').join(', ') + ']';
  return String(value);
}