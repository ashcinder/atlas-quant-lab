import {
  ACCOUNT_IMAGE_MAX_LENGTH,
  validAccountImage,
} from '../domain/account-image';

export async function prepareAccountImage(file: File): Promise<string> {
  const isSvg = file.type === 'image/svg+xml' || /\.svg$/i.test(file.name);
  if (
    !isSvg &&
    !['image/png', 'image/jpeg', 'image/webp'].includes(file.type)
  ) {
    throw new Error('请选择 PNG、JPG、WebP 或 SVG 图片。');
  }
  if (!file.size || file.size > 5 * 1024 * 1024) {
    throw new Error('图片大小需在 5 MB 以内，请选择一张较小的图片。');
  }
  let source: Blob = file;
  if (isSvg) {
    const xml = new DOMParser().parseFromString(
      await file.text(),
      'image/svg+xml',
    );
    const svg = xml.documentElement;
    if (
      xml.querySelector('parsererror') ||
      svg.localName !== 'svg' ||
      svg.namespaceURI !== 'http://www.w3.org/2000/svg'
    ) {
      throw new Error('SVG 文件无法读取，请重新导出为有效的 SVG 图片。');
    }
    // A viewBox-only SVG needs explicit dimensions for consistent image decoding.
    const viewBox = svg
      .getAttribute('viewBox')
      ?.trim()
      .split(/[\s,]+/)
      .map(Number);
    if (
      viewBox?.length === 4 &&
      viewBox.every(Number.isFinite) &&
      viewBox[2] > 0 &&
      viewBox[3] > 0 &&
      (!svg.hasAttribute('width') || !svg.hasAttribute('height'))
    ) {
      const scale = 128 / Math.max(viewBox[2], viewBox[3]);
      svg.setAttribute('width', String(viewBox[2] * scale));
      svg.setAttribute('height', String(viewBox[3] * scale));
    }
    // Decode in an isolated image context, never insert uploaded SVG into the DOM.
    source = new Blob([new XMLSerializer().serializeToString(svg)], {
      type: 'image/svg+xml',
    });
  }
  const url = URL.createObjectURL(source);
  try {
    const img = new Image();
    img.src = url;
    try {
      await img.decode();
    } catch {
      throw new Error('无法读取这张图片，请换一张图片重试。');
    }
    if (!img.naturalWidth || !img.naturalHeight)
      throw new Error('图片尺寸无效。');
    const canvas = document.createElement('canvas');
    canvas.width = canvas.height = 128;
    const ctx = canvas.getContext('2d');
    if (!ctx) throw new Error('当前浏览器无法处理图片，请更换浏览器重试。');
    // Fit the whole image so platform logos and identifying details are not cropped.
    const scale = Math.min(128 / img.naturalWidth, 128 / img.naturalHeight);
    const width = img.naturalWidth * scale;
    const height = img.naturalHeight * scale;
    ctx.imageSmoothingQuality = 'high';
    ctx.drawImage(img, (128 - width) / 2, (128 - height) / 2, width, height);
    for (const quality of [0.85, 0.65, 0.45]) {
      const data = canvas.toDataURL('image/webp', quality);
      if (data.length <= ACCOUNT_IMAGE_MAX_LENGTH && validAccountImage(data))
        return data;
    }
    // Fallback for browsers without a compact WebP encoder.
    ctx.globalCompositeOperation = 'destination-over';
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, 128, 128);
    const data = canvas.toDataURL('image/jpeg', 0.5);
    if (validAccountImage(data)) return data;
    throw new Error('这张图片细节过多，请换一张更简洁的图片。');
  } finally {
    URL.revokeObjectURL(url);
  }
}
