declare module 'pdfjs-dist/build/pdf.mjs' {
  export const GlobalWorkerOptions: { workerSrc: string; workerPort: Worker | null };
  export function getDocument(
    src: string | {
      url: string;
      password?: string;
      cMapUrl?: string;
      cMapPacked?: boolean;
      standardFontDataUrl?: string;
    },
  ): {
    promise: Promise<{
      numPages: number;
      getPage(index: number): Promise<{
        getViewport(params: { scale: number }): { width: number; height: number };
        render(params: { canvasContext: CanvasRenderingContext2D; viewport: unknown }): { promise: Promise<void> };
      }>;
    }>;
  };
}

declare module '*?url' {
  const src: string;
  export default src;
}