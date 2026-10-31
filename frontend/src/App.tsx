import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { NotFoundPage } from './pages/NotFoundPage';
import { ProgressPage } from './pages/ProgressPage';
import { UploadPage } from './pages/UploadPage';

export default function App() {
  return (
    <BrowserRouter basename={import.meta.env.BASE_URL.replace(/\/$/, "")}>
      <Routes>
        <Route path="/" element={<UploadPage />} />
        <Route path="/tasks/:taskId" element={<ProgressPage />} />
        <Route path="*" element={<NotFoundPage />} />
      </Routes>
    </BrowserRouter>
  );
}
