import test from "node:test";
import assert from "node:assert/strict";
import {
  seedLedger,
  allocateHolding,
  holdingStats,
  updateHoldingAmounts,
  deleteHolding,
  accountStats,
  unallocated,
  roiValuation,
  portfolio,
  history,
  validateLedger,
  scheduledDates,
  planAccountAmount,
  planAccountAllocations,
  planEntryKeys,
  occurrences,
} from "../src/journal/domain/ledger.ts";
import {
  materializeAutomatic,
  upgradeLedger,
  scheduledInstant,
} from "./reference/automation.ts";
const date = "2026-09-04";
function fixture() {
  const s = seedLedger(date);
  s.holdings = [];
  s.plans = [];
  return s;
}
function holding(s, symbol = "BTC", accountId = "spot-a") {
  const h = {
    id: crypto.randomUUID(),
    accountId,
    symbol,
    name: symbol,
    archived: false,
  };
  s.holdings.push(h);
  return h;
}
function plan(extra = {}) {
  return {
    id: "auto-plan",
    accountId: "spot-a",
    name: "自动测试",
    amount: 10,
    frequency: "daily",
    day: 1,
    time: "14:00",
    market: "CRYPTO",
    startDate: "2026-09-01",
    autoFrom: "2026-09-01",
    mode: "auto",
    paused: false,
    ...extra,
  };
}
test("allocating existing principal and setting ROI never duplicates account assets", () => {
  const s = fixture();
  const h = holding(s);
  s.entries.push(...allocateHolding(s, h, 600, "existing", date));
  validateLedger(s);
  assert.equal(portfolio(s).value, 1220);
  assert.equal(accountStats(s, s.accounts[0]).invested, 1200);
  assert.equal(unallocated(s, s.accounts[0]), 600);
  s.entries.push(roiValuation(s, h, 10, date));
  validateLedger(s);
  assert.equal(holdingStats(s, h).value, 660);
  assert.equal(accountStats(s, s.accounts[0]).value, 1260);
  assert.equal(portfolio(s).profit, 60);
  assert.equal(portfolio(s).invested, 1220);
});
test("multiple crypto positions and CNY funds have independent manually entered returns", () => {
  const s = fixture();
  for (const symbol of ["BTC", "DOGE", "ETH", "SOL"]) {
    const h = holding(s, symbol);
    s.entries.push(...allocateHolding(s, h, 100, "existing", date));
    s.entries.push(roiValuation(s, h, 20, date));
    assert.equal(holdingStats(s, h).roi, 20);
  }
  const fund = holding(s, "161725", "liquor");
  s.entries.push(...allocateHolding(s, fund, 100, "new", date));
  s.entries.push(roiValuation(s, fund, -5, date));
  validateLedger(s);
  assert.equal(holdingStats(s, fund).value, 95);
  assert.equal(holdingStats(s, fund).roi, -5);
  assert.equal(accountStats(s, s.accounts[0]).profit, 80);
});
test("invalid over-allocation and whole-account estimates below holdings are rejected", () => {
  const s = fixture();
  const h = holding(s);
  s.entries.push(...allocateHolding(s, h, 1201, "existing", date));
  assert.throws(() => validateLedger(s));
  const s2 = fixture();
  const h2 = holding(s2);
  s2.entries.push(...allocateHolding(s2, h2, 600, "existing", date));
  s2.entries.push({
    ...roiValuation(s2, h2, 0, date),
    id: "total",
    holdingId: undefined,
    amount: 500,
  });
  assert.throws(() => validateLedger(s2));
});
test("future contributions do not carry a stale manually reported ROI", () => {
  const s = fixture();
  const h = holding(s);
  s.entries.push(...allocateHolding(s, h, 100, "new", date));
  s.entries.push(roiValuation(s, h, 10, date));
  const extra = allocateHolding(s, h, 100, "new", date)[0];
  extra.createdAt = new Date(
    Date.parse(s.entries.at(-1).createdAt) + 1,
  ).toISOString();
  s.entries.push(extra);
  assert.equal(holdingStats(s, h).value, 210);
  assert.equal(holdingStats(s, h).roi, 5);
});
test("daily auto catchup is idempotent and honors time, skips and pause", () => {
  const s = fixture();
  s.plans = [plan()];
  const first = materializeAutomatic(s, new Date("2026-09-04T05:59:00Z"));
  assert.equal(first.added, 3);
  const second = materializeAutomatic(
    first.state,
    new Date("2026-09-04T06:01:00Z"),
  );
  assert.equal(second.added, 1);
  assert.equal(
    materializeAutomatic(second.state, new Date("2026-09-04T10:00:00Z")).added,
    0,
  );
  s.skipped = ["auto-plan:2026-09-02"];
  assert.equal(
    materializeAutomatic(s, new Date("2026-09-04T10:00:00Z")).added,
    3,
  );
  s.plans[0].paused = true;
  assert.equal(
    materializeAutomatic(s, new Date("2026-09-04T10:00:00Z")).added,
    0,
  );
});
test("weekdays excludes weekends; Chinese daily excludes exchange holidays", () => {
  const s = fixture();
  assert.deepEqual(
    scheduledDates(
      plan({ frequency: "weekdays" }),
      "2026-09-04",
      "2026-09-07",
      s.calendar,
    ),
    ["2026-09-04", "2026-09-07"],
  );
  assert.deepEqual(
    scheduledDates(
      plan({ accountId: "liquor", market: "CN", startDate: "2026-02-13" }),
      "2026-02-13",
      "2026-02-24",
      s.calendar,
    ),
    ["2026-02-13", "2026-02-24"],
  );
});
test("old plans become automatic only from upgrade date, preserving existing entries", () => {
  const s = fixture();
  const p = plan();
  delete p.mode;
  delete p.autoFrom;
  s.plans = [p];
  const upgraded = upgradeLedger(s, new Date("2026-09-04T10:00:00Z"));
  assert.equal(upgraded.plans[0].autoFrom, date);
  assert.equal(
    materializeAutomatic(upgraded, new Date("2026-09-04T10:00:00Z")).added,
    1,
  );
  assert.deepEqual(upgraded.entries, s.entries);
});
test("automatic deposits target the correct holding and manual plans do not auto post", () => {
  const s = fixture();
  const h = holding(s, "SOL", "spot-b");
  s.plans = [plan({ accountId: "spot-b", holdingId: h.id })];
  const { state, added } = materializeAutomatic(
    s,
    new Date("2026-09-04T10:00:00Z"),
  );
  assert.equal(added, 4);
  assert.equal(holdingStats(state, h).value, 40);
  assert.equal(accountStats(state, state.accounts[1]).value, 40);
  s.plans[0].mode = "manual";
  assert.equal(
    materializeAutomatic(s, new Date("2026-09-04T10:00:00Z")).added,
    0,
  );
});
test("one automatic plan distributes fixed amounts across multiple assets", () => {
  const s = fixture();
  const btc = holding(s, "BTC");
  const eth = holding(s, "ETH");
  s.plans = [
    plan({
      amount: 60,
      allocationMode: "amounts",
      allocations: [
        { holdingId: btc.id, amount: 40 },
        { holdingId: eth.id, amount: 20 },
      ],
    }),
  ];
  validateLedger(s);
  const { state, added } = materializeAutomatic(
    s,
    new Date("2026-09-04T10:00:00Z"),
  );
  assert.equal(added, 8);
  assert.equal(holdingStats(state, btc).value, 160);
  assert.equal(holdingStats(state, eth).value, 80);
  assert.equal(new Set(state.entries.filter((e) => e.automatic).map((e) => e.planKey)).size, 8);
  assert.equal(
    materializeAutomatic(state, new Date("2026-09-04T10:00:00Z")).added,
    0,
  );
});
test("ratio plans split the total exactly and complete only after every asset", () => {
  const s = fixture();
  const btc = holding(s, "BTC");
  const eth = holding(s, "ETH");
  const p = plan({
    amount: 100,
    allocationMode: "ratios",
    allocations: [
      { holdingId: btc.id, ratio: 33.33 },
      { holdingId: eth.id, ratio: 66.67 },
    ],
  });
  s.plans = [p];
  validateLedger(s);
  assert.deepEqual(
    planAccountAllocations(s, p, date).map((item) => item.amount),
    [33.33, 66.67],
  );
  const keys = planEntryKeys(p, date);
  s.entries.push({
    id: "partial-plan",
    accountId: p.accountId,
    holdingId: btc.id,
    kind: "deposit",
    amount: 33.33,
    date,
    fx: 7.12,
    note: "partial",
    createdAt: new Date().toISOString(),
    planKey: keys[0],
  });
  assert.equal(occurrences(s, date, date).find((o) => o.date === date).done, false);
  const completed = materializeAutomatic(
    s,
    new Date("2026-09-04T10:00:00Z"),
  );
  assert.equal(completed.added, 7);
  assert.equal(
    occurrences(completed.state, date, date).find((o) => o.date === date).done,
    true,
  );
  assert.throws(
    () =>
      validateLedger({
        ...s,
        plans: [
          {
            ...p,
            allocations: [
              { holdingId: btc.id, ratio: 40 },
              { holdingId: eth.id, ratio: 50 },
            ],
          },
        ],
      }),
    /100%/,
  );
});
test("multi-asset plans reject mixed market calendars and are removed with a target", () => {
  const s = fixture();
  const btc = holding(s, "BTC");
  const spy = holding(s, "SPY");
  spy.assetType = "stock";
  s.plans = [
    plan({
      amount: 100,
      allocationMode: "ratios",
      allocations: [
        { holdingId: btc.id, ratio: 50 },
        { holdingId: spy.id, ratio: 50 },
      ],
    }),
  ];
  assert.throws(() => validateLedger(s), /相同市场日历/);
  spy.assetType = "crypto";
  validateLedger(s);
  deleteHolding(s, btc);
  assert.equal(s.plans.length, 0);
  validateLedger(s);
});
test("US plans execute at the same Beijing time throughout the year", () => {
  assert.equal(
    scheduledInstant("2026-09-04", plan({ market: "US", time: "10:00" })),
    "2026-09-04T02:00:00.000Z",
  );
  assert.equal(
    scheduledInstant("2026-01-05", plan({ market: "US", time: "10:00" })),
    "2026-01-05T02:00:00.000Z",
  );
});

test("holding snapshots produce the same final chart value as account totals", () => {
  const s = fixture();
  const h = holding(s);
  s.entries.push(...allocateHolding(s, h, 600, "existing", date));
  s.entries.push(roiValuation(s, h, 10, date));
  const last = history(s, "USD", "all", date).at(-1);
  assert.equal(last.value, portfolio(s).value);
  assert.equal(last.net, 1220);
  assert.equal(last.profit, 60);
});
test("archiving a holding transfers its balance without losing historical profit", () => {
  const s = fixture();
  const h = holding(s);
  s.entries.push(...allocateHolding(s, h, 100, "existing", date));
  s.entries.push(roiValuation(s, h, 10, date));
  const createdAt = new Date(
    Date.parse(s.entries.at(-1).createdAt) + 1,
  ).toISOString();
  const base = {
    date,
    createdAt,
    fx: 6.7157,
    accountId: h.accountId,
    amount: 110,
    transferId: "close",
    note: "",
  };
  s.entries.push(
    { ...base, id: "close-out", kind: "withdraw", holdingId: h.id },
    { ...base, id: "close-in", kind: "deposit" },
  );
  h.archived = true;
  validateLedger(s);
  assert.equal(holdingStats(s, h).value, 0);
  assert.equal(holdingStats(s, h).profit, 10);
  assert.equal(accountStats(s, s.accounts[0]).value, 1210);
  assert.equal(portfolio(s).profit, 10);
});

test("editing holding principal in both directions replaces its basis without duplicating money", () => {
  const s = fixture();
  const h = holding(s);
  s.entries.push(...allocateHolding(s, h, 100, "new", date));
  s.entries.push(updateHoldingAmounts(s, h, 200, 10, date));
  validateLedger(s);
  assert.equal(holdingStats(s, h).invested, 200);
  assert.equal(holdingStats(s, h).value, 220);
  assert.equal(holdingStats(s, h).roi, 10);
  assert.equal(portfolio(s).invested, 1420);
  s.entries.push(updateHoldingAmounts(s, h, 50, -20, date));
  validateLedger(s);
  assert.equal(holdingStats(s, h).invested, 50);
  assert.equal(holdingStats(s, h).value, 40);
  assert.equal(holdingStats(s, h).roi, -20);
  assert.equal(portfolio(s).invested, 1270);
  assert.equal(history(s, "USD", "all", date).at(-1).value, 1260);
  s.entries.push(updateHoldingAmounts(s, h, 0, 0, date));
  validateLedger(s);
  assert.equal(portfolio(s).value, 1220);
});
test("deleting a holding removes its value, records and plans while preserving other holdings", () => {
  const s = fixture();
  const h = holding(s);
  const other = holding(s, "ETH");
  s.entries.push(...allocateHolding(s, h, 100, "existing", date));
  s.entries.push(...allocateHolding(s, other, 50, "new", date));
  s.entries.push(updateHoldingAmounts(s, h, 200, 10, date));
  s.plans = [plan({ holdingId: h.id })];
  const before = portfolio(s).value;
  deleteHolding(s, h);
  validateLedger(s);
  assert.equal(portfolio(s).value, before - 220);
  assert.equal(holdingStats(s, other).value, 50);
  assert.equal(s.plans.length, 0);
  assert.ok(!s.entries.some((e) => e.holdingId === h.id));
  assert.ok(!s.holdings.some((x) => x.id === h.id));
  assert.equal(portfolio(s).profit, 0);
});
test("deletion corrects later whole-account valuations so removed assets never reappear", () => {
  const s = fixture();
  const h = holding(s);
  s.entries.push(...allocateHolding(s, h, 100, "existing", date));
  const mark = updateHoldingAmounts(s, h, 100, 10, date);
  s.entries.push(mark);
  s.entries.push({
    ...mark,
    id: "account-mark",
    holdingId: undefined,
    principalAdjustment: undefined,
    amount: 1300,
    createdAt: new Date(Date.parse(mark.createdAt) + 1).toISOString(),
  });
  validateLedger(s);
  deleteHolding(s, h);
  validateLedger(s);
  assert.equal(accountStats(s, s.accounts[0]).value, 1190);
  assert.equal(history(s, "USD", "all", date).at(-1).value, 1210);
});

test("CNY plans fund USD accounts using each occurrence date rate", () => {
  const s = fixture();
  s.fxRates = [
    { date: "2026-09-01", rate: 7, source: "test" },
    { date: "2026-09-04", rate: 8, source: "test" },
  ];
  s.plans = [
    plan({
      currency: "CNY",
      amount: 56,
      startDate: "2026-09-03",
      autoFrom: "2026-09-03",
    }),
  ];
  const result = materializeAutomatic(s, new Date("2026-09-04T10:00:00Z"));
  const entries = result.state.entries.filter((e) => e.automatic);
  assert.deepEqual(
    entries.map((e) => e.amount),
    [8, 7],
  );
  assert.deepEqual(
    entries.map((e) => e.fx),
    [7, 8],
  );
  assert.equal(result.state.plans[0].currency, "CNY");
  assert.equal(planAccountAmount(s, s.plans[0], "2026-09-03"), 8);
  assert.equal(
    materializeAutomatic(result.state, new Date("2026-09-04T10:00:00Z")).added,
    0,
  );
});
test("USD plans fund CNY accounts without changing their native currency", () => {
  const s = fixture();
  s.fxRates = [{ date: "2026-09-01", rate: 7, source: "test" }];
  s.plans = [
    plan({
      currency: "USD",
      accountId: "liquor",
      market: "CN",
      amount: 20,
      startDate: date,
      autoFrom: date,
    }),
  ];
  const result = materializeAutomatic(s, new Date("2026-09-04T10:00:00Z"));
  assert.equal(result.state.entries.find((e) => e.automatic).amount, 140);
  assert.equal(
    result.state.accounts.find((a) => a.id === "liquor").currency,
    "CNY",
  );
});
test("Beijing midnight determines the US plan execution date", () => {
  const s = fixture();
  s.plans = [
    plan({
      accountId: "spy",
      market: "US",
      time: "00:01",
      startDate: date,
      autoFrom: date,
    }),
  ];
  assert.equal(
    materializeAutomatic(s, new Date("2026-09-03T16:00:00Z")).added,
    0,
  );
  const result = materializeAutomatic(s, new Date("2026-09-03T16:01:00Z"));
  assert.equal(result.added, 1);
  const entry = result.state.entries.find((e) => e.automatic);
  assert.equal(entry.date, date);
  assert.equal(entry.createdAt, "2026-09-03T16:01:00.000Z");
});
test("old plan currency falls back to account currency and unsupported units are rejected", () => {
  const s = fixture();
  s.plans = [plan({ amount: 20 })];
  assert.equal(planAccountAmount(s, s.plans[0], date), 20);
  s.plans[0].currency = "EUR";
  assert.throws(() => validateLedger(s), /币种/);
});
