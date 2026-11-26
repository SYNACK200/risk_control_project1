import { useCallback, useEffect, useState } from 'react';
import { getLabBridgeHealth } from '../api/lab';

export type LabHealthState = { status: 'checking' | 'up' | 'down'; version: string | null };

const POLL_MS = 30000;

/** 特征平台连接状态：侧栏状态点与特征平台页共用同一套判定。 */
export function useLabHealth() {
  const [state, setState] = useState<LabHealthState>({ status: 'checking', version: null });

  const refresh = useCallback(() => {
    getLabBridgeHealth()
      .then((health) =>
        setState(
          health.status === 'ok'
            ? { status: 'up', version: health.catalog_version ?? null }
            : { status: 'down', version: null },
        ),
      )
      .catch(() => setState({ status: 'down', version: null }));
  }, []);

  useEffect(() => {
    refresh();
    const id = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  return { ...state, refresh };
}
