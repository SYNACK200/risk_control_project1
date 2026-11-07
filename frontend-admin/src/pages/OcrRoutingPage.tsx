import { useEffect, useState } from 'react';
import { getOcrRouting, saveOcrRouting } from '../lib/api';
import { useIsAdmin } from '../lib/auth';

/**
 * OCR 路由：决定某次识别走本地引擎还是云端 API。
 *
 * 为什么做成可配置：云端 API 单张 4–10 秒，比本地慢；只有多张并发才划算。
 * 「多少张算多」「要不要开」「并发几路」会随网络、限流、文件类型变化，
 * 写死在代码里就得改代码重新发布。
 */
export function OcrRoutingPage() {
  const isAdmin = useIsAdmin();
  const [cfg, setCfg] = useState<{
    enabled: boolean; min_images: number; workers: number; model: string;
    endpoint?: string | null; has_api_key?: boolean; credential_ready?: boolean;
  } | null>(null);
  const [form, setForm] = useState({ enabled: false, min_images: 3, workers: 2, model: 'PP-OCRv6', endpoint: '', api_key: '', note: '' });
  const [msg, setMsg] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);

  function load() {
    getOcrRouting()
      .then(d => {
        setCfg(d);
        // api_key 永远从空开始：后端不回显 key，只回「有没有」
        setForm({ enabled: d.enabled, min_images: d.min_images, workers: d.workers, model: d.model, endpoint: d.endpoint ?? '', api_key: '', note: '' });
      })
      .catch(e => setError(e instanceof Error ? e.message : String(e)));
  }
  useEffect(load, []);

  async function submit() {
    setBusy(true); setMsg(''); setError('');
    try {
      await saveOcrRouting(form);
      setMsg('已保存。下一次识别就按新规则走。');
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="result">
      <div className="result-head">
        <h2>OCR 路由</h2>
        <span className="muted">本地引擎与云端 API 怎么选</span>
      </div>
      {error && <div className="notice error">{error}</div>}
      {msg && <div className="notice info">{msg}</div>}

      <section className="card">
        <div className="card-head-static">
          <strong>当前策略</strong>
          <span className="muted small">
            {cfg ? (cfg.enabled ? '已开启云端路由' : '全部走本地引擎') : '读取中…'}
            {cfg && !cfg.credential_ready && ' · 未找到云端凭据'}
          </span>
        </div>
        <div className="card-body">
          <table className="mini" style={{ marginBottom: 14 }}>
            <thead><tr><th>场景</th><th>走哪条</th><th>为什么</th></tr></thead>
            <tbody>
              <tr><td>电子 PDF</td><td>不走 OCR</td><td>有文字层，直接提取</td></tr>
              <tr><td>单张图片</td><td>本地引擎</td><td>本地无网络等待，通常更快</td></tr>
              <tr>
                <td>多张图片（≥ {form.min_images} 张）</td>
                <td>{form.enabled ? '云端 API 并发' : '本地引擎'}</td>
                <td>云端是 HTTP，并发时才划算；本地受 GIL 限制，并发无效</td>
              </tr>
            </tbody>
          </table>

          {!isAdmin && <p className="muted small">只有管理员能改这些设置。</p>}

          <div className="tpl-row" style={{ flexWrap: 'wrap', alignItems: 'flex-end', gap: 12 }}>
            <label className="muted small" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              云端路由
              <select value={form.enabled ? '1' : '0'} disabled={!isAdmin}
                onChange={e => setForm(p => ({ ...p, enabled: e.target.value === '1' }))}>
                <option value="0">关闭（全部走本地）</option>
                <option value="1">开启（多张走云端）</option>
              </select>
            </label>
            <label className="muted small" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              张数门槛
              <input type="number" min={1} max={200} value={form.min_images} disabled={!isAdmin}
                onChange={e => setForm(p => ({ ...p, min_images: Number(e.target.value) || 1 }))}
                style={{ width: 96 }} />
            </label>
            <label className="muted small" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              并发路数
              <input type="number" min={1} max={8} value={form.workers} disabled={!isAdmin}
                onChange={e => setForm(p => ({ ...p, workers: Number(e.target.value) || 1 }))}
                style={{ width: 96 }} />
            </label>
            {/* 只有开启云端路由时才需要这些；关闭状态下显示它们只会让人以为必填 */}
            {form.enabled && (
              <>
                <label className="muted small" style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
                  云端模型
                  <input value={form.model} disabled={!isAdmin}
                    onChange={e => setForm(p => ({ ...p, model: e.target.value }))}
                    placeholder="PP-OCRv6"
                    style={{ width: 150 }} />
                </label>
                <label className="muted small" style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 260 }}>
                  API 地址（留空用默认 aistudio）
                  <input value={form.endpoint} disabled={!isAdmin}
                    onChange={e => setForm(p => ({ ...p, endpoint: e.target.value }))}
                    placeholder="https://paddleocr.aistudio-app.com" />
                </label>
                <label className="muted small" style={{ display: 'flex', flexDirection: 'column', gap: 4, flex: 1, minWidth: 260 }}>
                  API Key{cfg?.has_api_key ? '（已配置，留空表示不改）' : ''}
                  <input type="password" value={form.api_key} disabled={!isAdmin}
                    onChange={e => setForm(p => ({ ...p, api_key: e.target.value }))}
                    placeholder={cfg?.has_api_key ? '已配置，需要更换时填新值' : '填 API Key'} />
                </label>
              </>
            )}
            {isAdmin && (
              <button className="btn" type="button" disabled={busy} onClick={() => { void submit(); }}>
                {busy ? '保存中…' : '保存'}
              </button>
            )}
          </div>

          <div className="notice" style={{ marginTop: 12 }}>
            <div><b>并发别超过 2。</b>实测：2 张串行 17.2 秒；并发 2 只要 8.8 秒（提速 95%）；并发 4 反而 188 秒，因为服务端排队到超时。</div>
            <div className="muted small" style={{ marginTop: 6 }}>
              凭据在 <code>~/.dsh/ocr/paddle.json</code>，不进仓库。改凭据要重启服务。
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}