"use client";

import { useEffect, useRef, useState, type DragEvent } from "react";
import workerPath from 'tesseract.js/dist/worker.min.js?url';
import corePath from 'tesseract.js-core/tesseract-core-lstm.wasm.js?url';
import {
  CheckCircle2,
  ImageUp,
  Plus,
  RefreshCw,
  ScanLine,
  X,
} from "lucide-react";
import { Button } from "@/journal/components/ui/button";
import { Input } from "@/journal/components/ui/input";
import { NativeSelect } from "@/journal/components/ui/native-select";
import {
  parsePortfolioWords,
  wordsFromTsv,
  type RecognizedAsset,
} from "@/journal/lib/portfolio-ocr";
import {
  money,
  today,
  unallocated,
  type Currency,
  type Ledger,
} from "@/journal/lib/ledger";

export type PortfolioOcrRow = {
  id: string;
  selected: boolean;
  holdingId: string;
  symbol: string;
  currentValue: string;
  invested: string;
  profit: string;
  roi: string;
  basis: "principal" | "profit" | "roi";
  confidence: number;
};

type Props = {
  state: Ledger;
  accountId: string;
  busy: boolean;
  onSubmit: (
    rows: PortfolioOcrRow[],
    currency: Currency,
    date: string,
    source: "existing" | "new",
  ) => Promise<void>;
};

const cleanNumber = (value: number | null) =>
  value === null ? "" : String(Number(value.toFixed(8)));
const finite = (value: string) =>
  value.trim() !== "" && Number.isFinite(Number(value));
const normalized = (value: string) =>
  value.replace(/[^A-Za-z0-9]/g, "").toUpperCase();
const rowId = () => crypto.randomUUID();

async function imageCanvas(file: File) {
  const bitmap = await createImageBitmap(file);
  const scale = Math.min(1, 2600 / Math.max(bitmap.width, bitmap.height));
  const canvas = document.createElement("canvas");
  canvas.width = Math.max(1, Math.round(bitmap.width * scale));
  canvas.height = Math.max(1, Math.round(bitmap.height * scale));
  const context = canvas.getContext("2d", { willReadFrequently: true });
  if (!context) throw Error("浏览器无法读取这张图片");
  context.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
  bitmap.close();
  const pixels = context.getImageData(0, 0, canvas.width, canvas.height);
  let luminance = 0;
  let samples = 0;
  const sampleStep = Math.max(
    4,
    Math.floor(pixels.data.length / 12000 / 4) * 4,
  );
  for (let index = 0; index < pixels.data.length; index += sampleStep) {
    luminance +=
      pixels.data[index] * 0.299 +
      pixels.data[index + 1] * 0.587 +
      pixels.data[index + 2] * 0.114;
    samples++;
  }
  const invert = luminance / Math.max(1, samples) < 118;
  for (let index = 0; index < pixels.data.length; index += 4) {
    let grey =
      pixels.data[index] * 0.299 +
      pixels.data[index + 1] * 0.587 +
      pixels.data[index + 2] * 0.114;
    if (invert) grey = 255 - grey;
    grey = Math.max(0, Math.min(255, (grey - 128) * 1.32 + 128));
    pixels.data[index] = grey;
    pixels.data[index + 1] = grey;
    pixels.data[index + 2] = grey;
    pixels.data[index + 3] = 255;
  }
  context.putImageData(pixels, 0, 0);
  return canvas;
}

function toReviewRow(asset: RecognizedAsset, state: Ledger, accountId: string) {
  const holdings = (state.holdings ?? []).filter(
    (holding) => holding.accountId === accountId && !holding.archived,
  );
  const match = holdings.find(
    (holding) =>
      normalized(holding.symbol) === normalized(asset.symbol) ||
      normalized(holding.name) === normalized(asset.symbol),
  );
  const basis =
    asset.profit !== null ? "profit" : asset.roi !== null ? "roi" : "principal";
  const hasBasis =
    (basis === "profit" && asset.profit !== null) ||
    (basis === "roi" && asset.roi !== null) ||
    (basis === "principal" && asset.invested !== null);
  return {
    id: rowId(),
    selected: asset.currentValue !== null && hasBasis,
    holdingId: match?.id ?? "",
    symbol: asset.symbol,
    currentValue: cleanNumber(asset.currentValue),
    invested: cleanNumber(asset.invested),
    profit: cleanNumber(asset.profit),
    roi: cleanNumber(asset.roi),
    basis,
    confidence: asset.confidence,
  } satisfies PortfolioOcrRow;
}

function recalculate(
  row: PortfolioOcrRow,
  field: "currentValue" | "invested" | "profit" | "roi",
  value: string,
): PortfolioOcrRow {
  const next = { ...row, [field]: value };
  if (field !== "currentValue")
    next.basis =
      field === "invested"
        ? "principal"
        : field === "profit"
          ? "profit"
          : "roi";
  const current = Number(next.currentValue);
  const basisValue = Number(
    next.basis === "principal"
      ? next.invested
      : next.basis === "profit"
        ? next.profit
        : next.roi,
  );
  if (!finite(next.currentValue) || !Number.isFinite(basisValue)) return next;
  if (next.basis === "principal") {
    const profit = current - basisValue;
    next.profit = cleanNumber(profit);
    next.roi = basisValue > 0 ? cleanNumber((profit / basisValue) * 100) : "0";
  } else if (next.basis === "profit") {
    const principal = current - basisValue;
    next.invested = cleanNumber(principal);
    next.roi =
      principal > 0 ? cleanNumber((basisValue / principal) * 100) : "0";
  } else if (basisValue > -100) {
    const principal = current / (1 + basisValue / 100);
    next.invested = cleanNumber(principal);
    next.profit = cleanNumber(current - principal);
  }
  return next;
}

export default function PortfolioOcrForm({
  state,
  accountId,
  busy,
  onSubmit,
}: Props) {
  const account = state.accounts.find((item) => item.id === accountId)!;
  const holdings = (state.holdings ?? []).filter(
    (holding) => holding.accountId === accountId && !holding.archived,
  );
  const inputRef = useRef<HTMLInputElement>(null);
  const [rows, setRows] = useState<PortfolioOcrRow[]>([]);
  const [processing, setProcessing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const [status, setStatus] = useState("准备识别引擎");
  const [error, setError] = useState("");
  const [preview, setPreview] = useState("");
  const [detectedCurrency, setDetectedCurrency] = useState<Currency>();
  const [screenshotCurrency, setScreenshotCurrency] = useState<Currency>(
    account.currency,
  );
  const [date, setDate] = useState(today());
  const [source, setSource] = useState<"existing" | "new">("new");
  useEffect(
    () => () => {
      if (preview) URL.revokeObjectURL(preview);
    },
    [preview],
  );

  const updateRow = (
    id: string,
    update: (row: PortfolioOcrRow) => PortfolioOcrRow,
  ) =>
    setRows((current) =>
      current.map((row) => (row.id === id ? update(row) : row)),
    );

  const recognize = async (file: File) => {
    if (!file.type.startsWith("image/"))
      throw Error("请选择 PNG、JPG 或 WebP 截图");
    if (file.size > 15 * 1024 * 1024) throw Error("截图不能超过 15 MB");
    setError("");
    setRows([]);
    setProcessing(true);
    setProgress(0.02);
    setStatus("正在优化图片清晰度");
    if (preview) URL.revokeObjectURL(preview);
    setPreview(URL.createObjectURL(file));
    let worker: Awaited<
      ReturnType<(typeof import("tesseract.js"))["createWorker"]>
    > | null = null;
    try {
      const canvas = await imageCanvas(file);
      setStatus("正在加载本地识别引擎");
      const { createWorker, PSM } = await import("tesseract.js");
      worker = await createWorker("eng", 1, {
        // Version-locked executable code is served by Atlas, not a remote CDN.
        workerPath, corePath, workerBlobURL: false,
        logger: (message) => {
          if (typeof message.progress === "number")
            setProgress(message.progress);
          if (message.status === "recognizing text")
            setStatus("正在识别资产和金额");
          else if (message.status === "loading language traineddata")
            setStatus("首次使用正在加载英文数字模型");
        },
      });
      await worker.setParameters({
        tessedit_pageseg_mode: PSM.SPARSE_TEXT,
        preserve_interword_spaces: "1",
      });
      const result = await worker.recognize(
        canvas,
        {},
        { text: true, tsv: true },
      );
      const parsed = parsePortfolioWords(
        wordsFromTsv(result.data.tsv ?? ""),
        canvas.width,
      );
      if (!parsed.length)
        throw Error("没有识别到资产行，请上传包含资产名称和金额的完整清晰截图");
      const currencies = parsed.map((asset) => asset.currency);
      setDetectedCurrency(
        currencies.filter((currency) => currency === "CNY").length >
          currencies.length / 2
          ? "CNY"
          : "USD",
      );
      setRows(parsed.map((asset) => toReviewRow(asset, state, accountId)));
      setProgress(1);
      setStatus("识别完成，请逐行核对");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "图片识别失败，请重试");
    } finally {
      await worker?.terminate();
      setProcessing(false);
    }
  };

  const acceptFile = (file?: File) => {
    if (file)
      void recognize(file).catch((cause) => {
        setProcessing(false);
        setError(
          cause instanceof Error ? cause.message : "图片识别失败，请重试",
        );
      });
  };

  if (!rows.length)
    return (
      <div className="ocr-upload-stage">
        <input
          ref={inputRef}
          className="sr-only"
          type="file"
          accept="image/png,image/jpeg,image/webp"
          onChange={(event) => {
            acceptFile(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
        <button
          type="button"
          className={"ocr-dropzone" + (dragging ? " dragging" : "")}
          disabled={processing}
          onClick={() => inputRef.current?.click()}
          onDragEnter={(event) => {
            event.preventDefault();
            setDragging(true);
          }}
          onDragOver={(event) => event.preventDefault()}
          onDragLeave={() => setDragging(false)}
          onDrop={(event: DragEvent<HTMLButtonElement>) => {
            event.preventDefault();
            setDragging(false);
            acceptFile(event.dataTransfer.files?.[0]);
          }}
        >
          <span className="ocr-drop-icon">
            {processing ? <ScanLine size={27} /> : <ImageUp size={27} />}
          </span>
          <strong>{processing ? status : "拖入账户资产截图"}</strong>
          <p>
            {processing
              ? `${Math.round(progress * 100)}% · 大图通常需要几秒至半分钟`
              : "也可以点击选择 PNG、JPG 或 WebP，最大 15 MB"}
          </p>
          {processing && (
            <span className="ocr-progress">
              <i style={{ width: `${Math.max(4, progress * 100)}%` }} />
            </span>
          )}
        </button>
        <div className="ocr-privacy-note">
          <CheckCircle2 size={16} />
          <span>
            截图由浏览器内的 OCR
            引擎处理，不上传到理财账本服务器。首次使用会按需加载识别模型。
          </span>
        </div>
        {error && <p className="form-error">{error}</p>}
      </div>
    );

  const selected = rows.filter((row) => row.selected);
  const hasNew = selected.some((row) => !row.holdingId);
  return (
    <form
      className="ocr-review"
      onSubmit={(event) => {
        event.preventDefault();
        setError("");
        try {
          if (!selected.length) throw Error("请至少选择一项资产");
          const matched = selected.map((row) => row.holdingId).filter(Boolean);
          if (new Set(matched).size !== matched.length)
            throw Error("同一个账本资产只能匹配一行识别结果");
          for (const row of selected) {
            if (!row.holdingId && !normalized(row.symbol))
              throw Error("新资产必须填写名称");
            if (!finite(row.currentValue) || Number(row.currentValue) < 0)
              throw Error(`${row.symbol || "资产"} 的当前金额无效`);
            const basisValue =
              row.basis === "principal"
                ? row.invested
                : row.basis === "profit"
                  ? row.profit
                  : row.roi;
            if (!finite(basisValue))
              throw Error(`${row.symbol || "资产"} 的计算依据尚未填写`);
          }
          void onSubmit(rows, screenshotCurrency, date, source).catch((cause) =>
            setError(cause instanceof Error ? cause.message : "批量保存失败"),
          );
        } catch (cause) {
          setError(cause instanceof Error ? cause.message : "请检查识别结果");
        }
      }}
    >
      <div className="ocr-review-toolbar">
        <div>
          <strong>识别到 {rows.length} 项资产</strong>
          <span>{selected.length} 项将在确认后写入</span>
        </div>
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => {
            setRows([]);
            setError("");
          }}
        >
          <RefreshCw size={12} />
          更换截图
        </Button>
      </div>
      <div className="ocr-settings">
        <label htmlFor="ocr-currency">
          <span>截图金额币种</span>
          <NativeSelect
            id="ocr-currency"
            value={screenshotCurrency}
            onChange={(event) =>
              setScreenshotCurrency(event.target.value as Currency)
            }
          >
            <option value="USD">USD · 美元 / USDT</option>
            <option value="CNY">CNY · 人民币</option>
          </NativeSelect>
          {detectedCurrency && detectedCurrency !== account.currency && (
            <small>
              符号可能识别为 {detectedCurrency}，请以截图实际币种为准
            </small>
          )}
        </label>
        <label htmlFor="ocr-date">
          <span>资产日期</span>
          <Input
            id="ocr-date"
            type="date"
            min="2000-01-01"
            max={today()}
            value={date}
            onChange={(event) => setDate(event.target.value)}
            required
          />
        </label>
        {hasNew && unallocated(state, account) > 0 && (
          <label htmlFor="ocr-source">
            <span>新资产本金来源</span>
            <NativeSelect
              id="ocr-source"
              value={source}
              onChange={(event) =>
                setSource(event.target.value as "existing" | "new")
              }
            >
              <option value="new">新的外部投入</option>
              <option value="existing">
                账户未分配资金（
                {money(unallocated(state, account), account.currency)}）
              </option>
            </NativeSelect>
          </label>
        )}
      </div>
      <div className="ocr-result-list">
        {rows.map((row) => (
          <section
            className={"ocr-result-row" + (row.selected ? " selected" : "")}
            key={row.id}
          >
            <div className="ocr-result-head">
              <label className="ocr-select-row">
                <input
                  aria-label={`选择 ${row.symbol || "这项资产"}`}
                  type="checkbox"
                  checked={row.selected}
                  onChange={(event) =>
                    updateRow(row.id, (current) => ({
                      ...current,
                      selected: event.target.checked,
                    }))
                  }
                />
                <span>
                  <b>{row.symbol || "未命名资产"}</b>
                  <small>
                    OCR {row.confidence}% ·{" "}
                    {row.holdingId ? "更新已有资产" : "准备新建"}
                  </small>
                </span>
              </label>
              <button
                type="button"
                aria-label="移除此行"
                onClick={() =>
                  setRows((current) =>
                    current.filter((item) => item.id !== row.id),
                  )
                }
              >
                <X size={14} />
              </button>
            </div>
            <div className="ocr-row-grid">
              <label htmlFor={`${row.id}-holding`}>
                <span>匹配到账本资产</span>
                <NativeSelect
                  id={`${row.id}-holding`}
                  value={row.holdingId}
                  disabled={!row.selected}
                  onChange={(event) =>
                    updateRow(row.id, (current) => ({
                      ...current,
                      holdingId: event.target.value,
                    }))
                  }
                >
                  <option value="">新建识别到的资产</option>
                  {holdings.map((holding) => (
                    <option value={holding.id} key={holding.id}>
                      {holding.symbol} · {holding.name}
                    </option>
                  ))}
                </NativeSelect>
              </label>
              <label htmlFor={`${row.id}-symbol`}>
                <span>资产名称</span>
                <Input
                  id={`${row.id}-symbol`}
                  value={row.symbol}
                  disabled={!row.selected || !!row.holdingId}
                  maxLength={30}
                  onChange={(event) =>
                    updateRow(row.id, (current) => ({
                      ...current,
                      symbol: event.target.value,
                    }))
                  }
                  required={row.selected && !row.holdingId}
                />
              </label>
              <label htmlFor={`${row.id}-current`}>
                <span>当前金额</span>
                <Input
                  id={`${row.id}-current`}
                  type="number"
                  min="0"
                  max={1e12}
                  step="any"
                  value={row.currentValue}
                  disabled={!row.selected}
                  onChange={(event) =>
                    updateRow(row.id, (current) =>
                      recalculate(current, "currentValue", event.target.value),
                    )
                  }
                  required={row.selected}
                />
              </label>
              <label htmlFor={`${row.id}-basis`}>
                <span>采用的计算依据</span>
                <NativeSelect
                  id={`${row.id}-basis`}
                  value={row.basis}
                  disabled={!row.selected}
                  onChange={(event) =>
                    updateRow(row.id, (current) => ({
                      ...current,
                      basis: event.target.value as PortfolioOcrRow["basis"],
                    }))
                  }
                >
                  <option value="profit">收益额</option>
                  <option value="roi">收益率</option>
                  <option value="principal">总投入金额</option>
                </NativeSelect>
              </label>
              <label
                className={row.basis === "principal" ? "active-basis" : ""}
                htmlFor={`${row.id}-principal`}
              >
                <span>总投入金额</span>
                <Input
                  id={`${row.id}-principal`}
                  type="number"
                  min="0"
                  max={1e12}
                  step="any"
                  value={row.invested}
                  disabled={!row.selected}
                  onChange={(event) =>
                    updateRow(row.id, (current) =>
                      recalculate(current, "invested", event.target.value),
                    )
                  }
                />
              </label>
              <label
                className={row.basis === "profit" ? "active-basis" : ""}
                htmlFor={`${row.id}-profit`}
              >
                <span>收益额</span>
                <Input
                  id={`${row.id}-profit`}
                  type="number"
                  min={-1e12}
                  max={1e12}
                  step="any"
                  value={row.profit}
                  disabled={!row.selected}
                  onChange={(event) =>
                    updateRow(row.id, (current) =>
                      recalculate(current, "profit", event.target.value),
                    )
                  }
                />
              </label>
              <label
                className={row.basis === "roi" ? "active-basis" : ""}
                htmlFor={`${row.id}-roi`}
              >
                <span>收益率（%）</span>
                <Input
                  id={`${row.id}-roi`}
                  type="number"
                  min="-100"
                  max="100000"
                  step="0.0001"
                  value={row.roi}
                  disabled={!row.selected}
                  onChange={(event) =>
                    updateRow(row.id, (current) =>
                      recalculate(current, "roi", event.target.value),
                    )
                  }
                />
              </label>
            </div>
          </section>
        ))}
      </div>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() =>
          setRows((current) => [
            ...current,
            {
              id: rowId(),
              selected: true,
              holdingId: "",
              symbol: "",
              currentValue: "",
              invested: "",
              profit: "",
              roi: "",
              basis: "profit",
              confidence: 0,
            },
          ])
        }
      >
        <Plus size={12} />
        补充遗漏资产
      </Button>
      <div className="ocr-review-footer">
        <span>
          OCR 可能混淆
          USDT（₮）与人民币符号，也可能漏掉小数点。保存前请对照原图核对。
        </span>
        <Button type="submit" className="primary-button" disabled={busy}>
          {busy ? "正在批量保存…" : `确认更新 ${selected.length} 项资产`}
        </Button>
      </div>
      {error && <p className="form-error">{error}</p>}
    </form>
  );
}
