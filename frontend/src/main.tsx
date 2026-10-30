import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import { AuthGate } from './components/AuthGate';
import './index.css';
import './styles/upload.css';
import './styles/progress.css';

createRoot(document.getElementById('root')!).render(
  <StrictMode><AuthGate><App /></AuthGate></StrictMode>,
);
