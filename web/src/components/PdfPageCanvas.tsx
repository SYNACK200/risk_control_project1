import { useEffect, useRef, useState, type ReactNode } from 'react';

export type PageRenderSize = {
  width: number;
  height: number;
  baseWidth: number;
  baseHeight: number;
  fitScale: number;
  pageCount: number;
};

type Props = {
  /** 二进制原件（PDF 或 JPG/PNG），传 null 时仅占位 */
  fileBytes: ArrayBuffer | null;
  mimeHint?: string;
  pageIndex: number; // 0-based
  zoom: number;
  password?: string;
  /** wrong=true 表示「给了口令但打不开」，界面据此提示口令不正确 */
  onPasswordRequired?: (wrong?: boolean) => void;
  onPageInfo?: (info: PageRenderSize) => void;
  onError?: (message: string) => void;
  overlay?: ReactNode;
  children?: (size: PageRenderSize | null) => ReactNode;
  className?: string;
};

function isPdfBuffer(buf: ArrayBuffer, mimeHint?: string): boolean {
  if (mimeHint && mimeHint.startsWith('image/')) return false;
  const view = new Uint8Array(buf, 0, Math.min(buf.byteLength, 1024));
  // 查找 %PDF- 头部标识
  for (let i = 0; i <= view.length - 5; i += 1) {
    if (
      view[i] === 0x25 &&
      view[i + 1] === 0x50 &&
      view[i + 2] === 0x44 &&
      view[i + 3] === 0x46 &&
      view[i + 4] === 0x2d
    ) {
      return true;
    }
  }
  return false;
}

export function PdfPageCanvas({
  fileBytes,
  mimeHint,
  pageIndex,
  zoom,
  password,
  onPasswordRequired,
  onPageInfo,
  onError,
  overlay,
  children,
  className,
}: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const renderTaskRef = useRef<{ cancel(): void } | null>(null);
  const [size, setSize] = useState<PageRenderSize | null>(null);
  const [imageUrl, setImageUrl] = useState<string | null>(null);
  const isPdf = fileBytes ? isPdfBuffer(fileBytes, mimeHint) : true;

  // 图片原件路径
  useEffect(() => {
    if (!fileBytes || isPdf) {
      setImageUrl(null);
      return;
    }
    const blob = new Blob([fileBytes], { type: mimeHint || 'image/jpeg' });
    const url = URL.createObjectURL(blob);
    setImageUrl(url);
    return () => URL.revokeObjectURL(url);
  }, [fileBytes, isPdf, mimeHint]);

  // PDF 原件路径：每次切页 / 缩放 / 换文件按高分屏倍数清晰渲染
  useEffect(() => {
    if (!fileBytes || !isPdf) return;
    let cancelled = false;
    (async () => {
      const pdfjs = await import('pdfjs-dist/build/pdf.mjs');
      pdfjs.GlobalWorkerOptions.workerSrc = '/pdf.worker.min.mjs';
      // 传 slice copy，防止 pdf.js worker transfer/detach 掉外层持有的 ArrayBuffer
      const dataCopy = new Uint8Array(fileBytes.slice(0));
      const doc = await pdfjs.getDocument({
        data: dataCopy,
        password: password || undefined,
        cMapUrl: '/cmaps/',
        cMapPacked: true,
        standardFontDataUrl: '/standard_fonts/',
      } as unknown as Parameters<typeof pdfjs.getDocument>[0]).promise;
      if (cancelled) return;
      const safePage = Math.max(0, Math.min(doc.numPages - 1, pageIndex));
      const pdfPage = await doc.getPage(safePage + 1);
      const base = pdfPage.getViewport({ scale: 1 });
      const containerW = Math.max(360, (containerRef.current?.clientWidth ?? 820) - 24);
      const fitScale = Math.max(0.35, Math.min(2.6, containerW / base.width));
      const cssScale = fitScale * zoom;
      const cssViewport = pdfPage.getViewport({ scale: cssScale });
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const renderViewport = pdfPage.getViewport({ scale: cssScale * dpr });

      const canvas = canvasRef.current;
      if (!canvas || cancelled) return;
      canvas.width = Math.floor(renderViewport.width);
      canvas.height = Math.floor(renderViewport.height);
      canvas.style.width = `${Math.floor(cssViewport.width)}px`;
      canvas.style.height = `${Math.floor(cssViewport.height)}px`;

      const ctx = canvas.getContext('2d');
      if (!ctx) return;
      renderTaskRef.current?.cancel();
      const task = pdfPage.render({ canvasContext: ctx, viewport: renderViewport });
      renderTaskRef.current = task as unknown as { cancel(): void };
      await task.promise;
      if (cancelled) return;

      const info: PageRenderSize = {
        width: Math.floor(cssViewport.width),
        height: Math.floor(cssViewport.height),
        baseWidth: base.width,
        baseHeight: base.height,
        fitScale,
        pageCount: doc.numPages,
      };
      setSize(info);
      onPageInfo?.(info);
    })().catch((err: unknown) => {
      if (cancelled) return;
      const msg = err instanceof Error ? err.message : String(err);
      if (msg.includes('cancel')) return;
      if (/password/i.test(msg)) {
        onPasswordRequired?.();
        return;
      }
      onError?.('原件渲染失败：' + msg);
    });
    return () => {
      cancelled = true;
      renderTaskRef.current?.cancel();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fileBytes, isPdf, pageIndex, zoom, password]);

  const handleImageLoad = (img: HTMLImageElement) => {
    const natW = img.naturalWidth || 800;
    const natH = img.naturalHeight || 1100;
    const containerW = Math.max(360, (containerRef.current?.clientWidth ?? 820) - 24);
    const fitScale = Math.max(0.2, Math.min(2.0, containerW / natW));
    const width = Math.floor(natW * fitScale * zoom);
    const height = Math.floor(natH * fitScale * zoom);
    const info: PageRenderSize = {
      width,
      height,
      baseWidth: natW,
      baseHeight: natH,
      fitScale,
      pageCount: 1,
    };
    setSize(info);
    onPageInfo?.(info);
  };

  return (
    <div ref={containerRef} className={className ? `pdf-stage-wrap ${className}` : 'pdf-stage-wrap'}>
      {!fileBytes ? (
        <div className="pdf-stage-empty">请先在左侧选择或上传流水文件</div>
      ) : (
        <div
          className="pdf-stage-surface"
          style={size ? { width: `${size.width}px`, height: `${size.height}px` } : undefined}
        >
          {isPdf ? (
            <canvas ref={canvasRef} className="pdf-stage-canvas" />
          ) : (
            imageUrl && (
              <img
                src={imageUrl}
                alt="流水原件"
                className="pdf-stage-img"
                style={size ? { width: `${size.width}px`, height: `${size.height}px` } : { maxWidth: '100%' }}
                onLoad={(e) => handleImageLoad(e.currentTarget)}
              />
            )
          )}
          <div className="pdf-stage-overlay">{overlay ?? children?.(size)}</div>
        </div>
      )}
    </div>
  );
}
