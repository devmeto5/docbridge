// Server-side only. Requires a Node.js release with built-in fetch.
import { readFile, stat } from 'node:fs/promises';

export async function convertDocument(path, source, target, language = 'eng') {
  const key = process.env.DOCBRIDGE_API_KEY;
  if (!key) throw new Error('DOCBRIDGE_API_KEY is required');
  if ((await stat(path)).size > 20 * 1024 * 1024) throw new Error('File exceeds 20 MiB');
  const base = process.env.DOCBRIDGE_URL || 'http://127.0.0.1:8080';
  const query = new URLSearchParams({ source, target, language, ocr: 'auto' });
  const response = await fetch(`${base.replace(/\/$/, '')}/v1/convert?${query}`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${key}`, 'Content-Type': 'application/octet-stream' },
    body: await readFile(path),
    signal: AbortSignal.timeout(200_000),
    redirect: 'error',
  });
  if (!response.ok) throw new Error(`DocBridge returned HTTP ${response.status}`);
  return {
    bytes: Buffer.from(await response.arrayBuffer()),
    contentType: response.headers.get('content-type'),
    warnings: response.headers.get('x-conversion-warnings'),
  };
}
