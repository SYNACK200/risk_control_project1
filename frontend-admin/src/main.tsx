import { Component, StrictMode, type ErrorInfo, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import { HashRouter } from 'react-router-dom';
import App from './App';
import { AuthGate } from './components/AuthGate';
import './styles/app.css';

class ErrorBoundary extends Component<{ children: ReactNode }, { message: string }> {
  state = { message: '' };

  static getDerivedStateFromError(error: unknown) {
    return { message: error instanceof Error ? error.message : String(error) };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error('[admin] render error', error, info.componentStack);
  }

  render() {
    if (this.state.message) {
      return (
        <div style={{ padding: 24, fontFamily: 'sans-serif' }}>
          <h2>页面渲染出错</h2>
          <pre style={{ whiteSpace: 'pre-wrap', color: '#b3261e' }}>{this.state.message}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <HashRouter><AuthGate><App /></AuthGate></HashRouter>
    </ErrorBoundary>
  </StrictMode>,
);

