import type { PDFDocumentProxy } from 'pdfjs-dist';
import type { SamplePage } from './types';

type PdfjsModule = typeof import('pdfjs-dist');

let pdfjsPromise: Promise<PdfjsModule> | null = null;

/** 按需加载 pdfjs：首屏不背 1MB+ 的解析器，只有真的要打开 PDF 时才拉。 */
async function loadPdfjs(): Promise<PdfjsModule> {
  if (!pdfjsPromise) {
    pdfjsPromise = (async () => {
      const [pdfjs, worker] = await Promise.all([
        import('pdfjs-dist'),
        import('pdfjs-dist/build/pdf.worker.min.mjs?url'),
      ]);
      pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
      return pdfjs;
    })().catch(err => {
      pdfjsPromise = null;
      throw err;
    });
  }
  return pdfjsPromise;
}

export class PdfPasswordError extends Error {
  readonly kind: 'needed' | 'wrong';
  constructor(kind: 'needed' | 'wrong') {
    super(kind === 'needed' ? 'PDF 需要打开口令' : 'PDF 口令不正确');
    this.name = 'PdfPasswordError';
    this.kind = kind;
  }
}

export async function openSampleFile(file: File, password?: string): Promise<SamplePage> {
  const name = file.name.toLowerCase();
  if (file.type === 'application/pdf' || name.endsWith('.pdf')) return openPdf(file, password);
  if (/^image\/(jpeg|png)$/.test(file.type) || /\.(jpe?g|png)$/.test(name)) return openImage(file);
  throw new Error('仅支持 PDF、JPG、JPEG、PNG 文件');
}

async function openPdf(file: File, password?: string): Promise<SamplePage> {
  const pdfjs = await loadPdfjs().catch(() => {
    throw new Error('PDF 解析组件加载失败，请刷新页面重试');
  });
  const buffer = await file.arrayBuffer();
  let doc: PDFDocumentProxy;
  try {
    // 必须带 cMapUrl：中文字体要靠 CMap 才能渲染，缺了只会画出表格线、印不出汉字
    // （线上表现就是「样本一片空白只有几条竖线」）。cmaps 随构建产物放在 public/cmaps。
    const cMapUrl = (import.meta.env.BASE_URL || '/') + 'cmaps/';
    doc = await pdfjs.getDocument({
      data: new Uint8Array(buffer), password, cMapUrl, cMapPacked: true,
    }).promise;
  } catch (err) {
    const raw = err instanceof Error ? err.message : String(err);
    const errName = err instanceof Error ? err.name : '';
    if (errName === 'PasswordException' || /password/i.test(raw)) {
      throw new PdfPasswordError(password ? 'wrong' : 'needed');
    }
    throw new Error(`PDF 无法打开：${raw}`);
  }

  const first = await doc.getPage(1);
  const baseViewport = first.getViewport({ scale: 1 });

  return {
    pageCount: doc.numPages,
    width: baseViewport.width,
    height: baseViewport.height,
    async render(pageNo, target, maxWidth) {
      const page = await doc.getPage(pageNo);
      const base = page.getViewport({ scale: 1 });
      const scale = maxWidth / base.width;
      const viewport = page.getViewport({ scale });
      target.width = Math.round(viewport.width);
      target.height = Math.round(viewport.height);
      const ctx = target.getContext('2d');
      if (!ctx) throw new Error('浏览器不支持画布绘制');
      await page.render({ canvasContext: ctx, viewport }).promise;
    },
    dispose() { void doc.destroy(); },
  };
}

async function openImage(file: File): Promise<SamplePage> {
  const url = URL.createObjectURL(file);
  const img = new Image();
  img.src = url;
  try {
    await img.decode();
  } catch {
    URL.revokeObjectURL(url);
    throw new Error('图片无法读取，请换一张或导出为 PDF');
  }

  return {
    pageCount: 1,
    width: img.naturalWidth,
    height: img.naturalHeight,
    async render(_pageNo, target, maxWidth) {
      const scale = maxWidth / img.naturalWidth;
      target.width = Math.round(img.naturalWidth * scale);
      target.height = Math.round(img.naturalHeight * scale);
      const ctx = target.getContext('2d');
      if (!ctx) throw new Error('浏览器不支持画布绘制');
      ctx.drawImage(img, 0, 0, target.width, target.height);
    },
    dispose() { URL.revokeObjectURL(url); },
  };
}