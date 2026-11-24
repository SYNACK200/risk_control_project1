import { BlobReader, BlobWriter, ZipReader } from '@zip.js/zip.js';

export type ArchiveOutcome =
  | { status: 'ok'; name: string; blob: Blob; others: number }
  | { status: 'need-password'; name: string }
  | { status: 'wrong-password'; name: string };

const ACCEPTED = /\.(pdf|jpe?g|png|webp)$/i;
const MAX_UNCOMPRESSED = 200 * 1024 * 1024;

/** 解包客户提交的加密/普通银行流水压缩包（如招行/工行带口令 ZIP）。 */
export async function extractStatement(file: File, password?: string): Promise<ArchiveOutcome> {
  const reader = new ZipReader(new BlobReader(file), password ? { password } : undefined);
  try {
    let entries;
    try {
      entries = await reader.getEntries();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (/not recognized|corrupt|invalid/i.test(msg)) {
        throw new Error('压缩包格式无效或已损坏，请检查后重试');
      }
      throw new Error(`压缩包读取失败：${msg}`);
    }
    const files = entries.filter((e) => !e.directory);
    if (files.length === 0) throw new Error('压缩包为空');

    const total = files.reduce((n, e) => n + (e.uncompressedSize ?? 0), 0);
    if (total > MAX_UNCOMPRESSED) throw new Error('解压体积超过 200MB 上限');

    const target = files.find((e) => ACCEPTED.test(e.filename));
    if (!target) throw new Error('压缩包里没有 PDF 或 JPG/PNG 流水文件');

    if (target.encrypted && !password) {
      return { status: 'need-password', name: target.filename };
    }
    try {
      const blob = await target.getData(new BlobWriter());
      return { status: 'ok', name: target.filename, blob, others: files.length - 1 };
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      if (/password|decrypt|wrong/i.test(msg)) {
        return { status: 'wrong-password', name: target.filename };
      }
      throw new Error(`压缩包解压失败：${msg}`);
    }
  } finally {
    await reader.close().catch(() => undefined);
  }
}

export function isArchive(file: File): boolean {
  return /\.zip$/i.test(file.name) || file.type === 'application/zip' || file.type === 'application/x-zip-compressed';
}
