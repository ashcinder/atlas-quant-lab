// Compact account icons travel with ledger backups; original uploads are not stored.
export const ACCOUNT_IMAGE_MAX_LENGTH = 12000;

export function validAccountImage(value: unknown): value is string {
  if (typeof value !== 'string' || value.length > ACCOUNT_IMAGE_MAX_LENGTH)
    return false;
  const match =
    /^data:image\/(png|jpeg|webp);base64,([A-Za-z0-9+/]+={0,2})$/.exec(value);
  if (!match || match[2].length % 4 !== 0) return false;
  try {
    const bytes = atob(match[2]);
    if (match[1] === 'png') return bytes.startsWith('\x89PNG\r\n\x1a\n');
    if (match[1] === 'jpeg') return bytes.startsWith('\xff\xd8\xff');
    return bytes.startsWith('RIFF') && bytes.slice(8, 12) === 'WEBP';
  } catch {
    return false;
  }
}
