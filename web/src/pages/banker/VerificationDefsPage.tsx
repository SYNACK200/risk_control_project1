import { useEffect, useMemo, useState } from 'react';
import { getVerificationDefinitions, type VerificationDef } from '../../api/banker';
import { getErrorMessage } from '../../api/errors';
import { Notice } from '../../ui/Notice';

/** 校验口径：每类识别方法是怎么验的，用于解释「为什么这项判了识别不准」。 */
export default function VerificationDefsPage() {
  const [items, setItems] = useState<VerificationDef[]>([]);
  const [error, setError] = useState('');
  const [layer, setLayer] = useState('');

  useEffect(() => {
    getVerificationDefinitions()
      .then((data) => setItems(data.items))
      .catch((err) => setError(getErrorMessage(err, 'banker')));
  }, []);

  const layers = useMemo(() => Array.from(new Set(items.map((item) => item.layer))), [items]);
  const shown = layer ? items.filter((item) => item.layer === layer) : items;

  return (
    <div className="panel wide">
      <header className="panel-head">
        <div>
          <h1>校验口径</h1>
          <p className="sub">共 {items.length} 项识别自检；按层分组。</p>
        </div>
        <div className="filters">
          <select value={layer} onChange={(event) => setLayer(event.target.value)}>
            <option value="">全部层</option>
            {layers.map((name) => (
              <option key={name} value={name}>{name}</option>
            ))}
          </select>
        </div>
      </header>

      {error ? <Notice>{error}</Notice> : null}

      <table className="grid compact">
        <thead>
          <tr><th>编号</th><th>层</th><th>方法</th></tr>
        </thead>
        <tbody>
          {shown.map((item) => (
            <tr key={item.code}>
              <td>{item.code}</td>
              <td>{item.layer}</td>
              <td className="small">{item.method}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
