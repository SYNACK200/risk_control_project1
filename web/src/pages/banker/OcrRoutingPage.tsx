import { useEffect, useState } from 'react';
import { getOcrRouting, saveOcrRouting, type OcrRouting as OcrRoutingType } from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { getUser } from '../../auth/store';
import { Button } from '../../ui/Button';
import { Field } from '../../ui/Field';
import { Notice } from '../../ui/Notice';

/** OCR 路由：图片件多到一定数量才走云端；Key 只显示「有没有配」，不回显。 */
export default function OcrRoutingPage() {
  const isAdmin = Boolean(getUser()?.is_admin);
  const [config, setConfig] = useState<OcrRoutingType | null>(null);
  const [apiKey, setApiKey] = useState('');
  const [message, setMessage] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    getOcrRouting()
      .then(setConfig)
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  }, []);

  async function save() {
    if (!config) return;
    setError('');
    setMessage('');
    try {
      const next = await saveOcrRouting({ ...config, api_key: apiKey || undefined });
      setConfig(next);
      setApiKey('');
      setMessage('已保存。');
    } catch (err) {
      setError(getErrorMessage(err, 'banker'));
    }
  }

  if (!config) return <p className="muted">加载中…</p>;

  return (
    <div className="panel">
      <header className="panel-head">
        <div>
          <h1>OCR 路由</h1>
          <p className="sub">图片件达到阈值才走云端识别；未配置 Key 时只用本地引擎。</p>
        </div>
        {isAdmin ? <Button onClick={() => void save()}>保存</Button> : <span className="muted small">只读（需管理员）</span>}
      </header>

      {error ? <Notice>{error}</Notice> : null}
      {message ? <Notice tone="ok">{message}</Notice> : null}

      <label className="inline-check">
        <input
          type="checkbox"
          checked={config.enabled}
          disabled={!isAdmin}
          onChange={(event) => setConfig({ ...config, enabled: event.target.checked })}
        />
        启用云端路由
      </label>

      <Field
        label="最少图片数"
        type="number"
        value={String(config.min_images)}
        disabled={!isAdmin}
        onChange={(event) => setConfig({ ...config, min_images: Number(event.target.value) })}
      />
      <Field
        label="并发数"
        type="number"
        value={String(config.workers)}
        disabled={!isAdmin}
        onChange={(event) => setConfig({ ...config, workers: Number(event.target.value) })}
      />
      {config.workers > 2 ? (
        <p className="pill warn" style={{ marginTop: 6 }}>
          并发数建议不超过 2，过高并发易触发本地 RapidOCR CPU 争用或云端限流。
        </p>
      ) : null}
      <p className="small muted" style={{ marginTop: 8 }}>
        凭据状态：{config.credential_ready ? '已就绪（可开启云端路由）' : '未就绪（请填写 API Key 后保存）'}
      </p>
      <section style={{ marginTop: 16 }}>
        <h3>本地 vs 云端路由分流策略</h3>
        <table className="grid compact">
          <thead><tr><th>条件</th><th>路由去向</th><th>说明</th></tr></thead>
          <tbody>
            <tr><td>电子 PDF（含文本层）</td><td>本地解析 + PyMuPDF 版式</td><td>零网络出域、毫秒级精度最高</td></tr>
            <tr><td>扫描件 / 图片 &lt; {config.min_images} 张</td><td>本地 RapidOCR 引擎</td><td>单机内网离线完成识字与坐标对齐</td></tr>
            <tr><td>图片 ≥ {config.min_images} 张且已启用云端</td><td>云端视觉 OCR（并发 {config.workers}）</td><td>大批次多页拍照件加速识别</td></tr>
          </tbody>
        </table>
      </section>
      {config.enabled ? (
        <>
          <Field
            label="模型"
            value={config.model ?? ''}
            disabled={!isAdmin}
            onChange={(event) => setConfig({ ...config, model: event.target.value })}
          />
          <Field
            label="接口地址"
            value={config.endpoint ?? ''}
            disabled={!isAdmin}
            onChange={(event) => setConfig({ ...config, endpoint: event.target.value })}
          />
          <Field
            label={config.has_api_key ? 'API Key（已配置，留空表示不改）' : 'API Key（未配置）'}
            type="password"
            value={apiKey}
            disabled={!isAdmin}
            onChange={(event) => setApiKey(event.target.value)}
            hint="Key 加密落库且不会回显；留空保存表示沿用原值。"
          />
        </>
      ) : null}
    </div>
  );
}
