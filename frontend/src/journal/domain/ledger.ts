import { validAccountImage } from "./account-image.ts";

export type Currency = "USD" | "CNY";
export type Category = "crypto" | "stock" | "grid" | "fund";
export type Market = "CRYPTO" | "CN" | "US";
export type EntryKind = "deposit" | "withdraw" | "valuation" | "income" | "fee";
export type Account = {
  image?: string;
  id: string;
  name: string;
  platform: string;
  category: Category;
  currency: Currency;
  archived: boolean;
  note: string;
};
export type Holding = {
  trackingMode?: "amount" | "quantity";
  assetType?: Category;
  side?: "long" | "short" | "neutral";
  leverage?: number;
  id: string;
  accountId: string;
  symbol: string;
  name: string;
  archived: boolean;
};
export type Entry = {
  id: string;
  accountId: string;
  kind: EntryKind;
  amount: number;
  date: string;
  fx: number;
  note: string;
  createdAt: string;
  holdingId?: string;
  automatic?: boolean;
  reportedRoi?: number;
  principalAdjustment?: number;
  quantitySet?: number;
  quantityDelta?: number;
  unitPrice?: number;
  unitCost?: number;
  planKey?: string;
  transferId?: string;
};
export type Plan = {
  currency?: Currency;
  allocationMode?: "amounts" | "ratios";
  allocations?: Array<{
    holdingId: string;
    amount?: number;
    ratio?: number;
  }>;
  id: string;
  accountId: string;
  name: string;
  amount: number;
  frequency: "daily" | "weekdays" | "weekly" | "monthly";
  holdingId?: string;
  mode?: "auto" | "manual";
  autoFrom?: string;
  day: number;
  time: string;
  startDate: string;
  market: Market;
  paused: boolean;
};
export type Journal = {
  id: string;
  date: string;
  title: string;
  body: string;
  tag: string;
};
export type FxRate = { date: string; rate: number; source: string };
export type CalendarConfig = {
  CN: Record<string, string[]>;
  US: Record<string, string[]>;
};
export type Ledger = {
  version: 1;
  accounts: Account[];
  holdings?: Holding[];
  entries: Entry[];
  plans: Plan[];
  journals: Journal[];
  fxRates: FxRate[];
  calendar: CalendarConfig;
  skipped: string[];
  settings: { name: string; monthlyBudget: number; autoFx: boolean };
};
export const categories: Record<
  Category,
  { label: string; color: string; symbol: string; desc: string }
> = {
  crypto: {
    label: "Crypto 现货",
    color: "#238f7d",
    symbol: "₿",
    desc: "长期持有，持续积累",
  },
  stock: {
    label: "美股 · ETF",
    color: "#7292c5",
    symbol: "S",
    desc: "与优秀的公司同行",
  },
  grid: {
    label: "合约网格",
    color: "#c49b5b",
    symbol: "⊞",
    desc: "独立策略，独立记录",
  },
  fund: {
    label: "人民币基金",
    color: "#a296c4",
    symbol: "¥",
    desc: "小额定投，日积月累",
  },
};
export const kinds: Record<EntryKind, string> = {
  deposit: "投入",
  withdraw: "取出",
  valuation: "估值更新",
  income: "分红 / 收益入账",
  fee: "手续费",
};
export const money = (n: number, c: Currency = "USD") =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: c,
    currencyDisplay: "narrowSymbol",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(n);
export const pct = (n: number | null) =>
  n === null ? "—" : `${n > 0 ? "+" : ""}${n.toFixed(2)}%`;
export const uid = () => crypto.randomUUID();
export const today = (zone = "Asia/Shanghai", now = new Date()) =>
  new Intl.DateTimeFormat("en-CA", {
    timeZone: zone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
export const round = (x: number) =>
  Math.round((x + Number.EPSILON) * 100000000) / 100000000;
export function addDays(date: string, n: number) {
  const d = new Date(date + "T12:00:00Z");
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}
export function daysBetween(a: string, b: string) {
  return Math.round(
    (Date.parse(b + "T00:00:00Z") - Date.parse(a + "T00:00:00Z")) / 86400000,
  );
}
export function range(a: string, b: string) {
  const r: string[] = [];
  for (let d = a; d <= b; d = addDays(d, 1)) {
    r.push(d);
    if (r.length > 36600) throw Error("日期范围过大");
  }
  return r;
}
export const defaultCalendar: CalendarConfig = {
  CN: {
    "2026": [
      ...range("2026-01-01", "2026-01-03"),
      ...range("2026-02-15", "2026-02-23"),
      ...range("2026-04-04", "2026-04-06"),
      ...range("2026-05-01", "2026-05-05"),
      ...range("2026-06-19", "2026-06-21"),
      ...range("2026-09-25", "2026-09-27"),
      ...range("2026-10-01", "2026-10-07"),
    ],
  },
  US: {
    "2026": [
      "2026-01-01",
      "2026-01-19",
      "2026-02-16",
      "2026-04-03",
      "2026-05-25",
      "2026-06-19",
      "2026-07-03",
      "2026-09-07",
      "2026-11-26",
      "2026-12-25",
    ],
    "2027": [
      "2027-01-01",
      "2027-01-18",
      "2027-02-15",
      "2027-03-26",
      "2027-05-31",
      "2027-06-18",
      "2027-07-05",
      "2027-09-06",
      "2027-11-25",
      "2027-12-24",
    ],
    "2028": [
      "2028-01-17",
      "2028-02-21",
      "2028-04-14",
      "2028-05-29",
      "2028-06-19",
      "2028-07-04",
      "2028-09-04",
      "2028-11-23",
      "2028-12-25",
    ],
  },
};
export function tradingDay(
  date: string,
  market: Market,
  calendar: CalendarConfig,
): { open: boolean; known: boolean; reason: string } {
  if (market === "CRYPTO")
    return { open: true, known: true, reason: "全年可交易" };
  const holidays = calendar[market][date.slice(0, 4)];
  if (!holidays)
    return { open: false, known: false, reason: "该年度交易日历待更新" };
  const dow = new Date(date + "T12:00:00Z").getUTCDay();
  if (dow === 0 || dow === 6)
    return { open: false, known: true, reason: "周末休市" };
  if (holidays.includes(date))
    return { open: false, known: true, reason: "节假日休市" };
  return { open: true, known: true, reason: "交易日" };
}
export function seedLedger(date = today()): Ledger {
  const accounts: Account[] = [
    {
      id: "spot-a",
      name: "现货账户 A",
      platform: "待设置平台",
      category: "crypto",
      currency: "USD",
      archived: false,
      note: "初始 1,200 USD 暂放在账户 A；可通过账户间转账调整分配。",
    },
    {
      id: "spot-b",
      name: "现货账户 B",
      platform: "待设置平台",
      category: "crypto",
      currency: "USD",
      archived: false,
      note: "",
    },
    {
      id: "spy",
      name: "SPY 长期定投",
      platform: "美股账户",
      category: "stock",
      currency: "USD",
      archived: false,
      note: "SPDR S&P 500 ETF Trust",
    },
    {
      id: "grid",
      name: "Crypto 合约网格",
      platform: "网格策略账户",
      category: "grid",
      currency: "USD",
      archived: false,
      note: "用策略总权益更新估值；已包含在权益中的网格利润无需重复记收入。",
    },
    {
      id: "liquor",
      name: "白酒指数基金",
      platform: "基金账户",
      category: "fund",
      currency: "CNY",
      archived: false,
      note: "可在名称中补充实际基金代码",
    },
    {
      id: "fund",
      name: "我的基金",
      platform: "基金账户",
      category: "fund",
      currency: "CNY",
      archived: false,
      note: "",
    },
  ];
  const plan = (
    id: string,
    accountId: string,
    name: string,
    amount: number,
    frequency: Plan["frequency"],
    market: Market,
    time: string,
  ): Plan => ({
    id,
    accountId,
    name,
    amount,
    frequency,
    market,
    time,
    day: 1,
    startDate: date,
    paused: false,
  });
  return {
    version: 1,
    accounts,
    entries: [
      {
        id: "opening-spot",
        accountId: "spot-a",
        kind: "deposit",
        amount: 1200,
        date,
        fx: 6.7157,
        note: "初始本金；估值暂按本金，尚未录入实际收益",
        createdAt: date + "T00:00:00.000Z",
      },
      {
        id: "opening-grid",
        accountId: "grid",
        kind: "deposit",
        amount: 20,
        date,
        fx: 6.7157,
        note: "初始策略资金；请更新实际总权益",
        createdAt: date + "T00:00:01.000Z",
      },
    ],
    plans: [
      plan(
        "p-crypto",
        "spot-a",
        "Crypto 现货定投",
        60,
        "monthly",
        "CRYPTO",
        "10:00",
      ),
      plan("p-spy", "spy", "SPY 月度定投", 100, "monthly", "US", "10:00"),
      plan("p-liquor", "liquor", "白酒交易日定投", 20, "daily", "CN", "14:00"),
      plan("p-fund", "fund", "基金交易日定投", 10, "daily", "CN", "14:00"),
    ],
    journals: [],
    fxRates: [
      { date: "2026-09-04", rate: 6.7157, source: "Frankfurter · 参考汇率" },
    ],
    calendar: structuredClone(defaultCalendar),
    skipped: [],
    settings: { name: "我的投资空间", monthlyBudget: 2000, autoFx: true },
  };
}
export function fxAt(state: Ledger, date = today()): FxRate {
  const sorted = [...state.fxRates].sort((a, b) =>
    a.date.localeCompare(b.date),
  );
  return sorted.filter((r) => r.date <= date).at(-1) ?? sorted[0];
}
export const convert = (v: number, from: Currency, to: Currency, fx: number) =>
  from === to ? v : from === "USD" ? v * fx : v / fx;
export function sortedEntries(entries: Entry[]) {
  return [...entries].sort(
    (a, b) =>
      a.date.localeCompare(b.date) ||
      a.createdAt.localeCompare(b.createdAt) ||
      a.id.localeCompare(b.id),
  );
}
// A bucket per holding plus an unallocated balance prevents double-counting.
export function applyEntry(buckets: Map<string, number>, e: Entry) {
  const key = e.accountId + ":" + (e.holdingId ?? "");
  if (e.kind === "valuation" && !e.holdingId) {
    let positions = 0;
    for (const [k, v] of buckets)
      if (k.startsWith(e.accountId + ":") && k !== key) positions += v;
    buckets.set(key, round(e.amount - positions));
  } else
    buckets.set(
      key,
      round(
        e.kind === "valuation"
          ? e.amount
          : (buckets.get(key) ?? 0) +
              (["withdraw", "fee"].includes(e.kind) ? -e.amount : e.amount),
      ),
    );
}
export function accountStats(
  state: Ledger,
  account: Account,
  end = today(),
  holdingId?: string,
) {
  const buckets = new Map<string, number>();
  let invested = 0,
    withdrawn = 0,
    fees = 0,
    income = 0;
  let marked: string | null = null;
  const internal = new Set(
    state.entries
      .filter(
        (e) =>
          e.transferId &&
          state.entries.some(
            (x) =>
              x.transferId === e.transferId &&
              x.id !== e.id &&
              x.accountId === e.accountId,
          ),
      )
      .map((e) => e.transferId),
  );
  for (const e of sortedEntries(
    state.entries.filter(
      (e) =>
        e.accountId === account.id &&
        e.date <= end &&
        (holdingId === undefined || e.holdingId === holdingId),
    ),
  )) {
    applyEntry(buckets, e);
    if (holdingId !== undefined || !internal.has(e.transferId)) {
      if (e.kind === "deposit") invested += e.amount;
      if (e.kind === "withdraw") withdrawn += e.amount;
    }
    invested += e.principalAdjustment ?? 0;
    if (e.kind === "income") income += e.amount;
    if (e.kind === "fee") fees += e.amount;
    if (e.kind === "valuation") marked = e.date;
  }
  const value = round([...buckets.values()].reduce((a, b) => a + b, 0));
  const net = round(invested - withdrawn),
    profit = round(value - net);
  return {
    value,
    invested: round(invested),
    withdrawn: round(withdrawn),
    net,
    profit,
    fees,
    income,
    roi: invested > 0 ? (profit / invested) * 100 : null,
    marked,
  };
}
export function holdingStats(state: Ledger, holding: Holding, end = today()) {
  return accountStats(
    state,
    state.accounts.find((a) => a.id === holding.accountId)!,
    end,
    holding.id,
  );
}
export function unallocated(state: Ledger, account: Account, end = today()) {
  return round(
    accountStats(state, account, end).value -
      (state.holdings ?? [])
        .filter((h) => h.accountId === account.id)
        .reduce((sum, h) => sum + holdingStats(state, h, end).value, 0),
  );
}
export function roiValuation(
  state: Ledger,
  holding: Holding,
  rate: number,
  date = today(),
): Entry {
  if (!Number.isFinite(rate) || rate < -100 || rate > 100000)
    throw Error("收益率需在 -100% 至 100000% 之间");
  const stats = holdingStats(state, holding, date);
  if (stats.invested <= 0) throw Error("请先向标的分配本金，再填写收益率");
  const amount = round(stats.invested * (1 + rate / 100) - stats.withdrawn);
  if (amount < 0) throw Error("此收益率与已取出金额冲突，计算后的估值不能为负");
  return {
    id: uid(),
    accountId: holding.accountId,
    holdingId: holding.id,
    kind: "valuation",
    amount,
    date,
    fx: fxAt(state, date).rate,
    note: "手动填写累计投入收益率 " + rate + "%",
    reportedRoi: rate,
    createdAt: new Date(
      Math.max(
        Date.now(),
        ...state.entries
          .filter((e) => e.date === date)
          .map((e) => Date.parse(e.createdAt) + 1),
      ),
    ).toISOString(),
  };
}
export function allocateHolding(
  state: Ledger,
  holding: Holding,
  amount: number,
  source: "existing" | "new",
  date = today(),
): Entry[] {
  if (!Number.isFinite(amount) || amount <= 0) throw Error("本金必须大于零");
  const common = {
    amount,
    date,
    fx: fxAt(state, date).rate,
    note: "标的本金：" + holding.symbol,
    createdAt: new Date().toISOString(),
  };
  if (source === "new")
    return [
      {
        ...common,
        id: uid(),
        accountId: holding.accountId,
        holdingId: holding.id,
        kind: "deposit",
      },
    ];
  const transferId = uid();
  return [
    {
      ...common,
      id: uid(),
      accountId: holding.accountId,
      kind: "withdraw",
      transferId,
    },
    {
      ...common,
      id: uid(),
      accountId: holding.accountId,
      holdingId: holding.id,
      kind: "deposit",
      transferId,
    },
  ];
}
export function portfolio(
  state: Ledger,
  currency: Currency = "USD",
  end = today(),
) {
  const fx = fxAt(state, end).rate;
  const assets = state.accounts.map((a) => ({
    ...a,
    ...accountStats(state, a, end),
  }));
  const value = assets.reduce(
    (sum, a) => sum + convert(a.value, a.currency, currency, fx),
    0,
  );
  let invested = 0,
    withdrawn = 0;
  for (const e of state.entries.filter((e) => e.date <= end && !e.transferId)) {
    const a = state.accounts.find((a) => a.id === e.accountId)!;
    invested += convert(e.principalAdjustment ?? 0, a.currency, currency, e.fx);
    if (e.kind === "deposit")
      invested += convert(e.amount, a.currency, currency, e.fx);
    if (e.kind === "withdraw")
      withdrawn += convert(e.amount, a.currency, currency, e.fx);
  }
  const net = invested - withdrawn,
    profit = value - net;
  return {
    value,
    invested,
    withdrawn,
    net,
    profit,
    roi: invested > 0 ? (profit / invested) * 100 : null,
    assets,
    categoryAssets: assets.flatMap((a) => {
      const positions = (state.holdings ?? [])
        .filter((h) => h.accountId === a.id)
        .map((h) => ({
          ...holdingStats(state, h, end),
          id: h.id,
          accountId: a.id,
          category: assetType(state, h),
          currency: a.currency,
        }));
      return [
        ...positions,
        {
          id: a.id,
          accountId: a.id,
          category: a.category,
          currency: a.currency,
          value: a.value - positions.reduce((n, h) => n + h.value, 0),
          profit: a.profit - positions.reduce((n, h) => n + h.profit, 0),
        },
      ];
    }),
    fx,
  };
}
export function history(
  state: Ledger,
  currency: Currency,
  days: number | "all",
  end = today(),
) {
  const entries = sortedEntries(state.entries.filter((e) => e.date <= end));
  const first = entries[0]?.date ?? end;
  const start =
    days === "all" ? first : [first, addDays(end, -days + 1)].sort().at(-1)!;
  const dates = range(start, end);
  const step = Math.max(1, Math.ceil(dates.length / 366));
  const sample = dates.filter(
    (_, i) => i % step === 0 || i === dates.length - 1,
  );
  const accounts = new Map(state.accounts.map((a) => [a.id, a]));
  const values = new Map<string, number>();
  let index = 0,
    net = 0;
  return sample.map((date) => {
    while (index < entries.length && entries[index].date <= date) {
      const e = entries[index++],
        a = accounts.get(e.accountId)!;
      applyEntry(values, e);
      net += convert(e.principalAdjustment ?? 0, a.currency, currency, e.fx);
      if (!e.transferId && (e.kind === "deposit" || e.kind === "withdraw"))
        net +=
          convert(e.amount, a.currency, currency, e.fx) *
          (e.kind === "withdraw" ? -1 : 1);
    }
    const fx = fxAt(state, date).rate;
    let value = 0;
    for (const [id, balance] of values)
      value += convert(
        balance,
        accounts.get(id.split(":")[0])!.currency,
        currency,
        fx,
      );
    return {
      date,
      label: date.slice(5).replace("-", "/"),
      value: round(value),
      net: round(net),
      profit: round(value - net),
    };
  });
}
export type Occurrence = {
  plan: Plan;
  date: string;
  key: string;
  account: Account;
  done: boolean;
  skipped: boolean;
};
export function scheduledDates(
  plan: Plan,
  from: string,
  to: string,
  calendar: CalendarConfig,
) {
  if (plan.paused || to < plan.startDate) return [];
  const start = [from, plan.startDate].sort().at(-1)!;
  const result = new Set<string>();
  // Look back one month so month-end deferrals into the following month are included.
  const scan = [addDays(start, -32), plan.startDate].sort().at(-1)!;
  for (const date of range(scan, to)) {
    const d = new Date(date + "T12:00:00Z");
    const lastDay = new Date(
      Date.UTC(d.getUTCFullYear(), d.getUTCMonth() + 1, 0),
    ).getUTCDate();
    const matches =
      plan.frequency === "daily" ||
      (plan.frequency === "weekdays" &&
        d.getUTCDay() > 0 &&
        d.getUTCDay() < 6) ||
      (plan.frequency === "weekly" && d.getUTCDay() === plan.day % 7) ||
      (plan.frequency === "monthly" &&
        d.getUTCDate() === Math.min(plan.day, lastDay));
    if (!matches) continue;
    let due = date;
    let status = tradingDay(due, plan.market, calendar);
    if (plan.frequency === "daily" || plan.frequency === "weekdays") {
      if (!status.open) continue;
    } else {
      for (let i = 0; i < 16 && status.known && !status.open; i++) {
        due = addDays(due, 1);
        status = tradingDay(due, plan.market, calendar);
      }
      if (!status.known || !status.open) continue;
    }
    if (due >= start && due <= to) result.add(due);
  }
  return [...result].sort();
}

export function planHoldingIds(plan: Plan): string[] {
  return (
    plan.allocations?.map((allocation) => allocation.holdingId) ??
    (plan.holdingId ? [plan.holdingId] : [])
  );
}

export function planEntryKeys(plan: Plan, date: string): string[] {
  const root = plan.id + ":" + date;
  return plan.allocations?.map((_, index) => root + ":" + index) ?? [root];
}

export function planIsActive(state: Ledger, plan: Plan): boolean {
  const account = state.accounts.find((item) => item.id === plan.accountId);
  return Boolean(
    account &&
    !account.archived &&
    !plan.paused &&
    planHoldingIds(plan).every((id) => {
      const holding = (state.holdings ?? []).find((item) => item.id === id);
      return holding && !holding.archived;
    }),
  );
}

export function activePlans(state: Ledger): Plan[] {
  return state.plans.filter((plan) => planIsActive(state, plan));
}

export function planCurrencyAllocations(
  plan: Plan,
): Array<{ holdingId?: string; amount: number }> {
  if (!plan.allocations)
    return [
      {
        ...(plan.holdingId ? { holdingId: plan.holdingId } : {}),
        amount: plan.amount,
      },
    ];
  if (plan.allocationMode === "amounts")
    return plan.allocations.map((allocation) => ({
      holdingId: allocation.holdingId,
      amount: allocation.amount!,
    }));
  let allocated = 0;
  return plan.allocations.map((allocation, index) => {
    const amount =
      index === plan.allocations!.length - 1
        ? round(plan.amount - allocated)
        : round((plan.amount * allocation.ratio!) / 100);
    allocated = round(allocated + amount);
    return { holdingId: allocation.holdingId, amount };
  });
}

export function occurrences(
  state: Ledger,
  from: string,
  to: string,
): Occurrence[] {
  return state.plans
    .flatMap((plan) => {
      const account = state.accounts.find((a) => a.id === plan.accountId);
      if (!account || !planIsActive(state, plan)) return [];
      return scheduledDates(plan, from, to, state.calendar).map((date) => {
        const key = plan.id + ":" + date;
        return {
          plan,
          account,
          date,
          key,
          done: planEntryKeys(plan, date).every((entryKey) =>
            state.entries.some((e) => e.planKey === entryKey),
          ),
          skipped: state.skipped.includes(key),
        };
      });
    })
    .sort(
      (a, b) =>
        a.date.localeCompare(b.date) || a.plan.time.localeCompare(b.plan.time),
    );
}
export function isDue(o: Occurrence, now = new Date()) {
  const zone = "Asia/Shanghai";
  const localDate = today(zone, now);
  const time = new Intl.DateTimeFormat("en-GB", {
    timeZone: zone,
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  }).format(now);
  return o.date < localDate || (o.date === localDate && o.plan.time <= time);
}
export function nextOccurrence(state: Ledger, plan: Plan, from = today()) {
  return (
    occurrences(state, from, addDays(from, 65)).find(
      (o) => o.plan.id === plan.id && !o.done && !o.skipped,
    )?.date ?? null
  );
}
export function validDate(s: unknown): s is string {
  return (
    typeof s === "string" &&
    /^\d{4}-\d{2}-\d{2}$/.test(s) &&
    !Number.isNaN(Date.parse(s + "T00:00:00Z")) &&
    new Date(s + "T00:00:00Z").toISOString().slice(0, 10) === s
  );
}
function assert(ok: unknown, msg: string): asserts ok {
  if (!ok) throw Error(msg);
}
function str(s: unknown, max = 200): s is string {
  return typeof s === "string" && s.length <= max;
}
function num(v: unknown, min = 0, max = 1e12): v is number {
  return typeof v === "number" && Number.isFinite(v) && v >= min && v <= max;
}
export function validateLedger(input: unknown): Ledger {
  assert(input && typeof input === "object", "账本格式无效");
  const s = input as Ledger;
  assert(s.version === 1, "不支持此账本版本");
  assert(
    Array.isArray(s.accounts) && s.accounts.length <= 100,
    "账户最多 100 个",
  );
  assert(
    Array.isArray(s.entries) && s.entries.length <= 10000,
    "流水最多 10,000 条",
  );
  assert(Array.isArray(s.plans) && s.plans.length <= 100, "计划最多 100 个");
  assert(
    Array.isArray(s.journals) && s.journals.length <= 5000,
    "手记格式无效",
  );
  const ids = new Set<string>();
  for (const a of s.accounts) {
    assert(
      str(a.id, 100) &&
        a.id.length > 0 &&
        !a.id.includes(":") &&
        !ids.has(a.id),
      "账户编号重复",
    );
    ids.add(a.id);
    assert(
      a.image === undefined || validAccountImage(a.image),
      "账户图片无效，请重新上传 PNG、JPG 或 WebP 缩略图",
    );
    assert(
      str(a.name, 80) &&
        a.name.trim().length > 0 &&
        str(a.platform, 80) &&
        str(a.note, 2000),
      "账户信息无效",
    );
    assert(
      Object.hasOwn(categories, a.category) &&
        ["USD", "CNY"].includes(a.currency) &&
        typeof a.archived === "boolean",
      "账户类型无效",
    );
    assert(
      a.currency === (a.category === "fund" ? "CNY" : "USD"),
      "Crypto、美股使用 USD；基金使用 CNY",
    );
  }
  assert(
    s.holdings === undefined ||
      (Array.isArray(s.holdings) && s.holdings.length <= 500),
    "标的最多 500 个",
  );
  const holdingIds = new Set<string>();
  for (const h of s.holdings ?? []) {
    assert(
      str(h.id, 100) &&
        h.id.length > 0 &&
        !h.id.includes(":") &&
        !holdingIds.has(h.id) &&
        ids.has(h.accountId) &&
        str(h.symbol, 30) &&
        h.symbol.trim().length > 0 &&
        str(h.name, 80) &&
        h.name.trim().length > 0 &&
        typeof h.archived === "boolean",
      "标的信息无效",
    );
    if (h.assetType !== undefined)
      assert(Object.hasOwn(categories, h.assetType), "资产类型无效");
    if (h.trackingMode !== undefined)
      assert(
        ["amount", "quantity"].includes(h.trackingMode),
        "资产记录方式无效",
      );
    if (h.side !== undefined)
      assert(["long", "short", "neutral"].includes(h.side), "仓位方向无效");
    if (h.leverage !== undefined)
      assert(num(h.leverage, 1, 1000), "杠杆倍数无效");
    holdingIds.add(h.id);
  }
  const entryIds = new Set<string>(),
    keys = new Set<string>();
  for (const e of s.entries) {
    assert(
      str(e.id, 100) && e.id.length > 0 && !entryIds.has(e.id),
      "流水编号重复",
    );
    entryIds.add(e.id);
    assert(
      ids.has(e.accountId) && Object.hasOwn(kinds, e.kind),
      "流水账户或类型无效",
    );
    assert(
      num(e.amount) &&
        (e.kind === "valuation" || e.amount > 0) &&
        num(e.fx, 0.01, 1000),
      "金额和汇率必须为有效正数",
    );
    assert(
      validDate(e.date) && e.date <= today() && e.date >= "2000-01-01",
      "记账日期必须在 2000 年至今天之间",
    );
    assert(
      str(e.note, 2000) &&
        str(e.createdAt, 40) &&
        /^\d{4}-\d{2}-\d{2}T/.test(e.createdAt) &&
        Number.isFinite(Date.parse(e.createdAt)),
      "流水信息无效",
    );
    if (e.holdingId)
      assert(
        holdingIds.has(e.holdingId) &&
          (s.holdings ?? []).find((h) => h.id === e.holdingId)?.accountId ===
            e.accountId,
        "标的必须属于所选账户",
      );
    for (const key of [
      "quantitySet",
      "quantityDelta",
      "unitPrice",
      "unitCost",
    ] as const)
      if (e[key] !== undefined)
        assert(
          num(e[key]) && !!e.holdingId,
          "资产数量与价格必须是非负数且归属资产",
        );
    if (e.principalAdjustment !== undefined)
      assert(
        num(e.principalAdjustment, -1e12, 1e12) &&
          e.kind === "valuation" &&
          !!e.holdingId,
        "本金更正格式无效",
      );
    if (e.reportedRoi !== undefined)
      assert(
        num(e.reportedRoi, -100, 100000) && e.kind === "valuation",
        "手动收益率格式无效",
      );
    if (e.automatic !== undefined)
      assert(
        typeof e.automatic === "boolean" && !!e.planKey,
        "自动流水格式无效",
      );
    if (e.planKey) {
      assert(
        str(e.planKey, 150) && !keys.has(e.planKey) && e.kind === "deposit",
        "定投不可重复确认",
      );
      keys.add(e.planKey);
    }
    if (e.transferId)
      assert(
        str(e.transferId, 100) && ["deposit", "withdraw"].includes(e.kind),
        "转账格式错误",
      );
  }
  for (const transferId of new Set(
    s.entries.map((e) => e.transferId).filter(Boolean),
  )) {
    const legs = s.entries.filter((e) => e.transferId === transferId);
    assert(
      legs.length === 2 &&
        legs[0].kind !== legs[1].kind &&
        (legs[0].accountId !== legs[1].accountId ||
          legs[0].holdingId !== legs[1].holdingId) &&
        legs[0].amount === legs[1].amount &&
        legs[0].date === legs[1].date &&
        legs[0].fx === legs[1].fx &&
        s.accounts.find((a) => a.id === legs[0].accountId)?.currency ===
          s.accounts.find((a) => a.id === legs[1].accountId)?.currency,
      "转账必须包含同币种、同金额、同日期的两笔流水",
    );
  }
  const balances = new Map<string, number>();
  // Transfer pairs can share a timestamp; replay withdrawals before deposits is safe as buckets are distinct.
  for (const e of sortedEntries(s.entries)) {
    applyEntry(balances, e);
    const value = balances.get(e.accountId + ":" + (e.holdingId ?? "")) ?? 0;
    assert(
      value >= -0.000001,
      "取出、分配或费用超过该日可用余额；账户整体估值不能低于标的估值合计",
    );
  }
  const plans = new Set<string>();
  for (const p of s.plans) {
    assert(
      str(p.id, 100) && p.id.length > 0 && !plans.has(p.id),
      "计划编号重复",
    );
    plans.add(p.id);
    assert(
      ids.has(p.accountId) &&
        str(p.name, 80) &&
        p.name.trim().length > 0 &&
        num(p.amount, 0.01) &&
        ["daily", "weekdays", "weekly", "monthly"].includes(p.frequency) &&
        ["CRYPTO", "CN", "US"].includes(p.market) &&
        typeof p.paused === "boolean",
      "定投信息无效",
    );
    if (p.currency !== undefined)
      assert(["USD", "CNY"].includes(p.currency), "定投币种必须为 USD 或 CNY");
    if (p.mode !== undefined)
      assert(["auto", "manual"].includes(p.mode), "记账方式无效");
    if (p.autoFrom !== undefined)
      assert(validDate(p.autoFrom), "自动开始日期无效");
    if (p.allocations !== undefined) {
      assert(
        ["amounts", "ratios"].includes(p.allocationMode ?? "") &&
          p.allocations.length > 0 &&
          p.allocations.length <= 100,
        "定投资产分配无效",
      );
      const allocationIds = new Set<string>();
      for (const allocation of p.allocations) {
        assert(
          str(allocation.holdingId, 100) &&
            !allocationIds.has(allocation.holdingId) &&
            holdingIds.has(allocation.holdingId) &&
            (s.holdings ?? []).find((h) => h.id === allocation.holdingId)
              ?.accountId === p.accountId,
          "定投资产必须唯一且属于所选账户",
        );
        allocationIds.add(allocation.holdingId);
        if (p.allocationMode === "amounts")
          assert(
            num(allocation.amount, 0.01) && allocation.ratio === undefined,
            "每项定投金额必须大于 0",
          );
        else
          assert(
            num(allocation.ratio, 0.0001, 100) &&
              allocation.amount === undefined,
            "定投占比必须大于 0 且不超过 100%",
          );
      }
      if (p.allocationMode === "amounts")
        assert(
          round(
            p.allocations.reduce(
              (sum, allocation) => sum + allocation.amount!,
              0,
            ),
          ) === round(p.amount),
          "各资产定投金额之和必须等于计划总额",
        );
      else
        assert(
          Math.abs(
            p.allocations.reduce(
              (sum, allocation) => sum + allocation.ratio!,
              0,
            ) - 100,
          ) < 0.0001,
          "各资产定投占比合计必须为 100%",
        );
      assert(p.holdingId === undefined, "组合定投不能同时设置旧版单一标的");
    } else assert(p.allocationMode === undefined, "定投资产分配无效");
    if (p.holdingId)
      assert(
        holdingIds.has(p.holdingId) &&
          (s.holdings ?? []).find((h) => h.id === p.holdingId)?.accountId ===
            p.accountId,
        "定投标的必须属于所选账户",
      );
    const a = s.accounts.find((a) => a.id === p.accountId)!;
    const selectedHoldings = planHoldingIds(p).map((id) =>
      (s.holdings ?? []).find((h) => h.id === id)!,
    );
    const assetTypes = selectedHoldings.length
      ? selectedHoldings.map((h) => h.assetType ?? a.category)
      : [a.category];
    assert(
      new Set(
        assetTypes.map((type) =>
          type === "fund" ? "CN" : type === "stock" ? "US" : "CRYPTO",
        ),
      ).size === 1,
      "同一定投计划中的资产必须使用相同市场日历",
    );
    const assetType = assetTypes[0];
    assert(
      p.market ===
        (assetType === "fund" ? "CN" : assetType === "stock" ? "US" : "CRYPTO"),
      "市场必须与账户资产类型一致",
    );
    assert(
      Number.isInteger(p.day) &&
        p.day >= 1 &&
        p.day <= (p.frequency === "weekly" ? 7 : 31) &&
        validDate(p.startDate) &&
        p.startDate >= "2000-01-01" &&
        /^([01]\d|2[0-3]):[0-5]\d$/.test(p.time),
      "定投日期或时间无效",
    );
  }
  const journals = new Set<string>();
  for (const j of s.journals) {
    assert(
      str(j.id, 100) &&
        !journals.has(j.id) &&
        validDate(j.date) &&
        j.date <= today() &&
        str(j.title, 120) &&
        j.title.trim().length > 0 &&
        str(j.body, 10000) &&
        str(j.tag, 30),
      "手记格式无效",
    );
    journals.add(j.id);
  }
  assert(
    Array.isArray(s.fxRates) &&
      s.fxRates.length > 0 &&
      s.fxRates.length <= 10000,
    "至少保留一个有效汇率",
  );
  const fxDates = new Set<string>();
  for (const r of s.fxRates) {
    assert(
      validDate(r.date) &&
        r.date <= today() &&
        num(r.rate, 0.01, 1000) &&
        str(r.source, 100) &&
        !fxDates.has(r.date),
      "汇率记录无效或日期重复",
    );
    fxDates.add(r.date);
  }
  assert(s.calendar && typeof s.calendar === "object", "缺少交易日历");
  for (const m of ["CN", "US"] as const) {
    assert(
      s.calendar[m] &&
        typeof s.calendar[m] === "object" &&
        !Array.isArray(s.calendar[m]),
      "交易日历无效",
    );
    for (const [year, dates] of Object.entries(s.calendar[m]))
      assert(
        /^20\d{2}$/.test(year) &&
          Array.isArray(dates) &&
          dates.length <= 366 &&
          dates.every((d) => validDate(d) && d.startsWith(year)),
        "休市日期必须与年份相符",
      );
  }
  assert(
    Array.isArray(s.skipped) &&
      s.skipped.length <= 10000 &&
      s.skipped.every((k) => str(k, 150)),
    "跳过记录无效",
  );
  assert(
    s.settings &&
      str(s.settings.name, 80) &&
      s.settings.name.trim().length > 0 &&
      num(s.settings.monthlyBudget, 0) &&
      typeof s.settings.autoFx === "boolean",
    "设置无效",
  );
  return s;
}

export function principalFromCurrentValue(
  value: number,
  rate: number,
  withdrawn = 0,
  totalLossPrincipal?: number,
): number {
  if (!Number.isFinite(value) || value < 0 || value > 1e12)
    throw Error("当前金额必须在 0 至 1 万亿之间");
  if (!Number.isFinite(rate) || rate < -100 || rate > 100000)
    throw Error("收益率需在 -100% 至 100000% 之间");
  if (!Number.isFinite(withdrawn) || withdrawn < 0)
    throw Error("历史取出金额无效");
  if (rate === -100) {
    if (value !== 0 || withdrawn !== 0)
      throw Error("收益率为 -100% 时，当前金额与历史取出金额必须为 0");
    if (
      totalLossPrincipal === undefined ||
      !Number.isFinite(totalLossPrincipal) ||
      totalLossPrincipal <= 0 ||
      totalLossPrincipal > 1e12
    )
      throw Error("亏损 100% 时无法反算本金，请填写原始投入金额");
    return totalLossPrincipal;
  }
  const principal = (value + withdrawn) / (1 + rate / 100);
  if (!Number.isFinite(principal) || principal > 1e12)
    throw Error("反算本金超过上限，请核对当前金额和收益率");
  return round(principal);
}

export function principalFromCurrentProfit(
  value: number,
  profit: number,
  withdrawn = 0,
): number {
  if (!Number.isFinite(value) || value < 0 || value > 1e12)
    throw Error("当前金额必须在 0 至 1 万亿之间");
  if (!Number.isFinite(profit) || profit < -1e12 || profit > 1e12)
    throw Error("收益额必须在负 1 万亿至 1 万亿之间");
  const principal = value + withdrawn - profit;
  if (principal < 0) throw Error("收益额不能大于当前金额与历史取出金额之和");
  if (principal > 1e12) throw Error("反算本金超过上限，请核对当前金额和收益额");
  if (principal > 0 && (profit / principal) * 100 > 100000)
    throw Error("收益额对应的收益率超过 100000%，请核对输入");
  return round(principal);
}

export function profitFromCurrentPrincipal(
  value: number,
  principal: number,
  withdrawn = 0,
): number {
  if (!Number.isFinite(value) || value < 0 || value > 1e12)
    throw Error("当前金额必须在 0 至 1 万亿之间");
  if (!Number.isFinite(principal) || principal < 0 || principal > 1e12)
    throw Error("总投入金额必须在 0 至 1 万亿之间");
  if (!Number.isFinite(withdrawn) || withdrawn < 0)
    throw Error("历史取出金额无效");
  const profit = value + withdrawn - principal;
  if (profit < -1e12 || profit > 1e12)
    throw Error("计算出的收益额超过上限，请核对当前金额和总投入金额");
  if (principal > 0 && (profit / principal) * 100 > 100000)
    throw Error("总投入金额对应的收益率超过 100000%，请核对输入");
  return round(profit);
}

export function updateHoldingCurrentValue(
  state: Ledger,
  holding: Holding,
  value: number,
  rate: number,
  totalLossPrincipal?: number,
  date = today(),
): Entry {
  const stats = holdingStats(state, holding, date);
  const principal = principalFromCurrentValue(
    value,
    rate,
    stats.withdrawn,
    totalLossPrincipal ?? stats.invested,
  );
  return {
    ...updateHoldingAmounts(state, holding, principal, rate, date),
    amount: round(value),
    note:
      "编辑资产：当前金额 " +
      value +
      "，收益率 " +
      rate +
      "%（本金按收益率反算）",
  };
}

export function updateHoldingCurrentProfit(
  state: Ledger,
  holding: Holding,
  value: number,
  profit: number,
  date = today(),
): Entry {
  const stats = holdingStats(state, holding, date);
  const principal = principalFromCurrentProfit(value, profit, stats.withdrawn);
  const rate = principal > 0 ? (profit / principal) * 100 : 0;
  return {
    ...updateHoldingAmounts(state, holding, principal, rate, date),
    amount: round(value),
    ...(principal > 0 ? { reportedRoi: rate } : { reportedRoi: undefined }),
    note:
      "编辑资产：当前金额 " +
      value +
      "，收益额 " +
      profit +
      "（本金按收益额反算）",
  };
}

// Editing a holding is a dated principal correction plus valuation, not another full deposit.
export function updateHoldingAmounts(
  state: Ledger,
  holding: Holding,
  principal: number,
  rate: number,
  date = today(),
): Entry {
  if (!Number.isFinite(principal) || principal < 0 || principal > 1e12)
    throw Error("投入金额必须在 0 至 1 万亿之间");
  if (!Number.isFinite(rate) || rate < -100 || rate > 100000)
    throw Error("收益率需在 -100% 至 100000% 之间");
  const stats = holdingStats(state, holding, date);
  const value = round(principal * (1 + rate / 100) - stats.withdrawn);
  if (value < 0)
    throw Error("投入金额和收益率不能使估值低于已取出金额，请核对历史取出记录");
  if (value > 1e12)
    throw Error("计算后的资产价值超过上限，请核对投入金额和收益率");
  return {
    id: uid(),
    accountId: holding.accountId,
    holdingId: holding.id,
    kind: "valuation",
    amount: value,
    date,
    fx: fxAt(state, date).rate,
    reportedRoi: rate,
    principalAdjustment: round(principal - stats.invested),
    note: "编辑标的：投入金额 " + principal + "，收益率 " + rate + "%",
    createdAt: new Date(
      Math.max(
        Date.now(),
        ...state.entries
          .filter((e) => e.date === date)
          .map((e) => Date.parse(e.createdAt) + 1),
      ),
    ).toISOString(),
  };
}
// Remove the position, its records and plans. Keep counterpart transfers as external flows.
export function deleteHolding(state: Ledger, holding: Holding): void {
  const transfers = new Set(
    state.entries
      .filter((e) => e.holdingId === holding.id && e.transferId)
      .map((e) => e.transferId),
  );
  const buckets = new Map<string, number>();
  const removedPlans = new Set(
    state.plans
      .filter((p) => planHoldingIds(p).includes(holding.id))
      .map((p) => p.id),
  );
  const retained: Entry[] = [];
  for (const entry of sortedEntries(state.entries)) {
    const e = { ...entry };
    if (
      e.accountId === holding.accountId &&
      e.kind === "valuation" &&
      !e.holdingId
    )
      e.amount = round(
        e.amount - (buckets.get(holding.accountId + ":" + holding.id) ?? 0),
      );
    applyEntry(buckets, entry);
    if (e.holdingId === holding.id) continue;
    if (e.transferId && transfers.has(e.transferId)) {
      delete e.transferId;
      e.note += "（关联标的已删除）";
    }
    retained.push(e);
  }
  state.entries = retained;
  state.holdings = state.holdings?.filter((h) => h.id !== holding.id);
  state.plans = state.plans.filter(
    (p) => !planHoldingIds(p).includes(holding.id),
  );
  state.skipped = state.skipped.filter(
    (k) => ![...removedPlans].some((id) => k.startsWith(id + ":")),
  );
}

export function planAccountAmount(
  state: Ledger,
  plan: Plan,
  date = today(),
): number {
  const account = state.accounts.find((a) => a.id === plan.accountId);
  if (!account) throw Error("定投账户不存在");
  return round(
    convert(
      plan.amount,
      plan.currency ?? account.currency,
      account.currency,
      fxAt(state, date).rate,
    ),
  );
}

export function planAccountAllocations(
  state: Ledger,
  plan: Plan,
  date = today(),
): Array<{ holdingId?: string; amount: number; plannedAmount: number }> {
  const account = state.accounts.find((a) => a.id === plan.accountId);
  if (!account) throw Error("定投账户不存在");
  const allocations = planCurrencyAllocations(plan);
  const total = planAccountAmount(state, plan, date);
  let allocated = 0;
  return allocations.map((allocation, index) => {
    const amount =
      index === allocations.length - 1
        ? round(total - allocated)
        : round(
            convert(
              allocation.amount,
              plan.currency ?? account.currency,
              account.currency,
              fxAt(state, date).rate,
            ),
          );
    allocated = round(allocated + amount);
    return {
      ...(allocation.holdingId ? { holdingId: allocation.holdingId } : {}),
      amount,
      plannedAmount: allocation.amount,
    };
  });
}

export function assetType(state: Ledger, h: Holding): Category {
  return (
    h.assetType ?? state.accounts.find((a) => a.id === h.accountId)!.category
  );
}
export function positionStats(state: Ledger, h: Holding, end = today()) {
  let quantity: number | null = null,
    unitPrice: number | null = null,
    unitCost: number | null = null;
  for (const e of sortedEntries(
    state.entries.filter((e) => e.holdingId === h.id && e.date <= end),
  )) {
    if (e.quantitySet !== undefined) quantity = e.quantitySet;
    if (e.quantityDelta !== undefined)
      quantity = (quantity ?? 0) + e.quantityDelta;
    if (e.unitPrice !== undefined) unitPrice = e.unitPrice;
    if (e.unitCost !== undefined) unitCost = e.unitCost;
  }
  const stats = holdingStats(state, h, end);
  return {
    ...stats,
    quantity,
    unitPrice,
    unitCost: quantity && quantity > 0 ? stats.invested / quantity : unitCost,
  };
}
export type PositionInput = {
  quantity: number;
  unitCost: number;
  unitPrice: number;
  margin: number;
  equity: number;
};
export function recordPosition(
  state: Ledger,
  h: Holding,
  input: PositionInput,
  date = today(),
): Entry {
  for (const value of Object.values(input))
    if (!Number.isFinite(value) || value < 0 || value > 1e12)
      throw Error("资产数量、价格和权益必须是有效非负数");
  const grid = assetType(state, h) === "grid";
  const principal = grid
    ? input.margin
    : round(input.quantity * input.unitCost);
  const value = grid ? input.equity : round(input.quantity * input.unitPrice);
  if (principal > 1e12 || value > 1e12) throw Error("持仓金额超过上限");
  const stats = holdingStats(state, h, date);
  return {
    id: uid(),
    accountId: h.accountId,
    holdingId: h.id,
    kind: "valuation",
    amount: value,
    principalAdjustment: round(principal - stats.invested),
    quantitySet: input.quantity,
    unitCost: input.unitCost,
    unitPrice: input.unitPrice,
    date,
    fx: fxAt(state, date).rate,
    note: grid ? "更新网格仓位、保证金与权益" : "更新资产数量、成本和价格",
    createdAt: new Date(
      Math.max(
        Date.now(),
        ...state.entries
          .filter((e) => e.date === date)
          .map((e) => Date.parse(e.createdAt) + 1),
      ),
    ).toISOString(),
  };
}
export function clearLedger(state: Ledger, keepAccounts: boolean): Ledger {
  return {
    ...structuredClone(state),
    accounts: keepAccounts ? structuredClone(state.accounts) : [],
    holdings: [],
    entries: [],
    plans: [],
    journals: [],
    skipped: [],
  };
}
export function emptyLedger(): Ledger {
  return clearLedger(seedLedger(), false);
}
