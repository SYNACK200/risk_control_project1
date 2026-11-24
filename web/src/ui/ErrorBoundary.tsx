import { Component, type ReactNode } from 'react';

type Props = { children: ReactNode };
type State = { message: string | null };

/** 兜底渲染错误：白屏只会让人以为「页面没了」，这里把原因直接摆出来。 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { message: null };

  static getDerivedStateFromError(err: unknown): State {
    return { message: err instanceof Error ? err.message : String(err) };
  }

  render() {
    if (this.state.message) {
      return (
        <div className="panel wide">
          <div className="alert err">页面渲染出错了：{this.state.message}</div>
          <div className="empty-actions">
            <button className="btn" onClick={() => this.setState({ message: null })}>重试</button>
            <button className="btn btn-ghost" onClick={() => window.location.reload()}>重新加载页面</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
