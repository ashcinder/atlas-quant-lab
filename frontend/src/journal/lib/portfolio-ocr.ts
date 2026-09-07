export type OcrWord = {
  text: string;
  confidence: number;
  x: number;
  y: number;
  width: number;
  height: number;
};

export type RecognizedAsset = {
  symbol: string;
  currentValue: number | null;
  invested: number | null;
  profit: number | null;
  roi: number | null;
  currency: "USD" | "CNY";
  confidence: number;
};

const ignoredSymbols = new Set([
  "USD",
  "USDT",
  "CNY",
  "SPDR",
  "CHAIN",
  "STATE",
  "STREET",
  "BITCOIN",
  "ETHEREUM",
  "DOGECOIN",
  "AVALANCHE",
  "POLKADOT",
  "ET",
  "INU",
]);
const round = (value: number) =>
  Math.round((value + Number.EPSILON) * 100000000) / 100000000;
const numeric = (value: string) => {
  const parsed = Number(value.replaceAll(",", "").replace(/[()]/g, ""));
  return Number.isFinite(parsed) ? parsed : null;
};
const normalizedText = (value: string) =>
  value
    .replace(/[−–—]/g, "-")
    .replace(/([+-])\s+(?=[$¥￥₮])/g, "$1")
    .replace(/([¥￥])\s+/g, "$1")
    .replace(/₮/g, "$");

export function wordsFromTsv(tsv: string): OcrWord[] {
  return tsv
    .split(/\r?\n/)
    .slice(1)
    .map((line) => line.split("\t"))
    .filter((columns) => columns.length >= 12 && columns[0] === "5")
    .map((columns) => ({
      text: columns.slice(11).join("\t").trim(),
      confidence: Number(columns[10]) || 0,
      x: Number(columns[6]) || 0,
      y: Number(columns[7]) || 0,
      width: Number(columns[8]) || 0,
      height: Number(columns[9]) || 0,
    }))
    .filter((word) => word.text);
}

function moneyValues(words: OcrWord[]) {
  const lines: Array<{ y: number; x: number; words: OcrWord[] }> = [];
  for (const word of [...words].sort((a, b) => a.y - b.y || a.x - b.x)) {
    const center = word.y + word.height / 2;
    const line = lines.find(
      (candidate) =>
        Math.abs(candidate.y - center) <= Math.max(8, word.height * 0.65),
    );
    if (line) {
      line.words.push(word);
      line.y =
        line.words.reduce((sum, item) => sum + item.y + item.height / 2, 0) /
        line.words.length;
      line.x = Math.min(line.x, word.x);
    } else lines.push({ y: center, x: word.x, words: [word] });
  }
  const values: Array<{
    value: number;
    signed: boolean;
    percentLine: boolean;
    x: number;
    y: number;
  }> = [];
  const percentages: number[] = [];
  for (const line of lines) {
    const text = normalizedText(
      line.words
        .sort((a, b) => a.x - b.x)
        .map((word) => word.text)
        .join(" "),
    );
    for (const match of text.matchAll(
      /([+-]?)\s*(?:USDT|USD|CNY|[$¥￥])\s*([0-9][0-9,.]*)/gi,
    )) {
      const amount = numeric(match[2]);
      if (amount === null) continue;
      const sign = match[1] === "-" ? -1 : 1;
      values.push({
        value: sign * amount,
        signed: !!match[1],
        percentLine: /[+-]?\s*\(?\d+(?:\.\d+)?\s*%/.test(text),
        x: line.x,
        y: line.y,
      });
    }
    for (const match of text.matchAll(/([+-]?)\s*\(?([0-9]+(?:\.\d+)?)\s*%/g)) {
      const value = numeric(match[2]);
      if (value !== null) percentages.push((match[1] === "-" ? -1 : 1) * value);
    }
  }
  return { values, percentages, lines };
}

export function parsePortfolioWords(
  words: OcrWord[],
  imageWidth = Math.max(1, ...words.map((word) => word.x + word.width)),
): RecognizedAsset[] {
  if (!words.length) return [];
  const candidates = words
    .filter((word) => {
      const symbol = word.text.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
      const original = word.text.replace(/[^A-Za-z0-9]/g, "");
      return (
        word.x < imageWidth * 0.38 &&
        original === original.toUpperCase() &&
        /^[A-Z][A-Z0-9]{1,11}$/.test(symbol) &&
        !ignoredSymbols.has(symbol) &&
        !/^\d+$/.test(symbol)
      );
    })
    .map((word) => ({
      ...word,
      symbol: word.text.replace(/[^A-Za-z0-9]/g, "").toUpperCase(),
      center: word.y + word.height / 2,
    }))
    .sort((a, b) => a.center - b.center || b.x - a.x);
  const anchors: typeof candidates = [];
  for (const candidate of candidates) {
    const nearby = anchors.find(
      (anchor) =>
        Math.abs(anchor.center - candidate.center) <
        Math.max(38, Math.min(anchor.height, candidate.height) * 3.5),
    );
    if (!nearby) anchors.push(candidate);
    else if (
      candidate.height > nearby.height * 1.08 ||
      (candidate.height >= nearby.height * 0.92 && candidate.x < nearby.x)
    ) {
      anchors[anchors.indexOf(nearby)] = candidate;
    }
  }
  anchors.sort((a, b) => a.center - b.center);
  return anchors
    .map((anchor, index): RecognizedAsset | null => {
      const top =
        index === 0 ? 0 : (anchors[index - 1].center + anchor.center) / 2;
      const bottom =
        index === anchors.length - 1
          ? Number.POSITIVE_INFINITY
          : (anchor.center + anchors[index + 1].center) / 2;
      const rowWords = words.filter((word) => {
        const center = word.y + word.height / 2;
        return center >= top && center < bottom;
      });
      const { values, percentages, lines } = moneyValues(rowWords);
      const rowText = normalizedText(
        rowWords.map((word) => word.text).join(" "),
      );
      const currency: "USD" | "CNY" = /[¥￥]|\bCNY\b/i.test(rowText)
        ? "CNY"
        : "USD";
      const profitCandidate =
        values.find((value) => value.signed) ??
        values.find((value) => value.percentLine);
      const unsigned = values.filter(
        (value) => value !== profitCandidate && !value.signed,
      );
      const plainNumbers = lines.flatMap((line) =>
        line.words
          .filter(
            (word) =>
              word.x > imageWidth * 0.35 &&
              !/[$¥￥₮%]/.test(word.text) &&
              /^[0-9][0-9,.]*$/.test(word.text),
          )
          .map((word) => numeric(word.text))
          .filter((value): value is number => value !== null),
      );
      let current = unsigned[0]?.value ?? null;
      if (unsigned.length >= 2 && plainNumbers.length) {
        let best: { value: number; error: number } | null = null;
        for (const quantity of plainNumbers) {
          for (const price of unsigned) {
            for (const possibleValue of unsigned) {
              if (price === possibleValue) continue;
              const expected = quantity * price.value;
              const error =
                Math.abs(expected - possibleValue.value) /
                Math.max(0.01, possibleValue.value);
              if (error < 0.08 && (!best || error < best.error))
                best = { value: possibleValue.value, error };
            }
          }
        }
        if (best) current = best.value;
      }
      const profit = profitCandidate?.value ?? null;
      const roi = percentages[0] ?? null;
      const invested =
        current !== null && profit !== null
          ? round(current - profit)
          : current !== null && roi !== null && roi > -100
            ? round(current / (1 + roi / 100))
            : null;
      if (current === null && profit === null && roi === null) return null;
      return {
        symbol: anchor.symbol,
        currentValue: current,
        invested,
        profit,
        roi,
        currency,
        confidence: Math.round(
          rowWords.reduce((sum, word) => sum + word.confidence, 0) /
            Math.max(1, rowWords.length),
        ),
      };
    })
    .filter((asset): asset is RecognizedAsset => asset !== null);
}
