import test from "node:test";
import assert from "node:assert/strict";
import {
  seedLedger,
  emptyLedger,
  clearLedger,
  recordPosition,
  updateHoldingAmounts,
  updateHoldingCurrentValue,
  principalFromCurrentValue,
  principalFromCurrentProfit,
  profitFromCurrentPrincipal,
  updateHoldingCurrentProfit,
  allocateHolding,
  holdingStats,
  positionStats,
  portfolio,
  validateLedger,
  deleteHolding,
  today,
} from "../src/journal/domain/ledger.ts";
import { materializeAutomatic } from "./reference/automation.ts";
const date = today();
const input = (quantity, unitCost, unitPrice) => ({
  quantity,
  unitCost,
  unitPrice,
  margin: 0,
  equity: 0,
});
function fixture() {
  const s = emptyLedger();
  s.accounts = [
    {
      id: "wallet",
      name: "我的账户",
      currency: "USD",
      category: "crypto",
      platform: "test",
      archived: false,
      note: "",
    },
  ];
  return s;
}
function add(s, id, type, data) {
  const h = {
    id,
    accountId: "wallet",
    symbol: id,
    name: id,
    archived: false,
    assetType: type,
  };
  s.holdings.push(h);
  s.entries.push(recordPosition(s, h, data, date));
  return h;
}
test("one account contains crypto counts and fractional US shares with independent valuations", () => {
  const s = fixture();
  const btc = add(s, "BTC", "crypto", input(0.02, 60000, 65000));
  const spy = add(s, "SPY", "stock", input(1.5, 500, 550));
  validateLedger(s);
  assert.equal(positionStats(s, btc).quantity, 0.02);
  assert.equal(positionStats(s, spy).quantity, 1.5);
  assert.equal(portfolio(s).value, 2125);
  assert.equal(portfolio(s).profit, 175);
  assert.equal(
    portfolio(s).categoryAssets.find((a) => a.id === "SPY").category,
    "stock",
  );
  s.entries.push(recordPosition(s, btc, input(0.01, 60000, 62000), date));
  assert.equal(positionStats(s, btc).value, 620);
  assert.equal(portfolio(s).value, 1445);
});
test("fund units use NAV; grid totals use equity, never leveraged notional", () => {
  const s = fixture();
  s.accounts[0].currency = "CNY";
  s.accounts[0].category = "fund";
  const fund = add(s, "FUND", "fund", input(100, 1.2, 1.1));
  const grid = add(s, "GRID", "grid", {
    quantity: 0.03,
    unitCost: 0,
    unitPrice: 0,
    margin: 20,
    equity: 23,
  });
  grid.leverage = 10;
  grid.side = "long";
  validateLedger(s);
  assert.equal(positionStats(s, fund).value, 110);
  assert.equal(positionStats(s, grid).value, 23);
  assert.equal(portfolio(s, "CNY").value, 133);
});
test("automatic contribution adds estimated units using last recorded price", () => {
  const s = fixture();
  const h = add(s, "ETH", "crypto", input(1, 2000, 2500));
  s.entries[0].date = "2026-09-01";
  s.plans = [
    {
      id: "p",
      accountId: "wallet",
      holdingId: h.id,
      name: "买入",
      amount: 50,
      currency: "USD",
      frequency: "daily",
      day: 1,
      time: "00:00",
      market: "CRYPTO",
      mode: "auto",
      autoFrom: date,
      startDate: date,
      paused: false,
    },
  ];
  const result = materializeAutomatic(s);
  assert.equal(result.added, 1);
  assert.equal(positionStats(result.state, h).quantity, 1.02);
  assert.equal(positionStats(result.state, h).value, 2550);
});
test("clear data removes automatic plans and never restores test entries", () => {
  const s = seedLedger();
  for (const keep of [true, false]) {
    const cleared = clearLedger(s, keep);
    validateLedger(cleared);
    assert.equal(cleared.accounts.length, keep ? s.accounts.length : 0);
    assert.equal(materializeAutomatic(cleared).state.entries.length, 0);
    assert.equal(cleared.plans.length, 0);
    assert.equal(cleared.holdings.length, 0);
  }
});
test("delete one position leaves the other quantities and values intact", () => {
  const s = fixture();
  const a = add(s, "BTC", "crypto", input(0.1, 50000, 60000));
  const b = add(s, "SOL", "crypto", input(3, 100, 150));
  deleteHolding(s, a);
  validateLedger(s);
  assert.equal(positionStats(s, b).quantity, 3);
  assert.equal(portfolio(s).value, 450);
});

test("amount-only assets calculate manual returns for crypto, stock, grid and CNY funds", () => {
  for (const type of ["crypto", "stock", "grid", "fund"]) {
    const s = fixture();
    if (type === "fund") Object.assign(s.accounts[0], { category: "fund", currency: "CNY" });
    const h = { id: type, accountId: "wallet", symbol: type, name: type, assetType: type, trackingMode: "amount", archived: false };
    s.holdings.push(h);
    s.entries.push(...allocateHolding(s, h, 1200, "new", date));
    s.entries.push(updateHoldingAmounts(s, h, 1200, 10, date));
    validateLedger(s);
    assert.equal(holdingStats(s, h).value, 1320);
    assert.equal(holdingStats(s, h).profit, 120);
    assert.equal(positionStats(s, h).quantity, null);
    s.entries.push(updateHoldingAmounts(s, h, 1500, -10, date));
    validateLedger(s);
    assert.equal(holdingStats(s, h).invested, 1500);
    assert.equal(holdingStats(s, h).value, 1350);
    assert.equal(holdingStats(s, h).profit, -150);
  }
});

test("simplifying an existing position preserves history; auto deposits add money without invented units or profit", () => {
  const s = fixture();
  const h = add(s, "BTC", "crypto", input(0.02, 60000, 66000));
  s.entries[0].date = "2026-09-01";
  const original = structuredClone(s.entries[0]);
  h.trackingMode = "amount";
  s.entries.push(updateHoldingAmounts(s, h, 1200, 10, "2026-09-02"));
  s.plans.push({ id: "simple-auto", accountId: "wallet", holdingId: h.id, name: "定投", amount: 60,
    currency: "USD", frequency: "daily", day: 1, time: "14:00", market: "CRYPTO", mode: "auto",
    autoFrom: "2026-09-04", startDate: "2026-09-04", paused: false });
  const result = materializeAutomatic(s, new Date("2026-09-04T06:00:00Z"));
  assert.equal(result.added, 1);
  assert.deepEqual(result.state.entries[0], original);
  assert.equal(result.state.entries.at(-1).quantityDelta, undefined);
  assert.equal(holdingStats(result.state, h).invested, 1260);
  assert.equal(holdingStats(result.state, h).value, 1380);
  assert.equal(holdingStats(result.state, h).profit, 120);
  assert.equal(holdingStats(result.state, h).roi, 120 / 1260 * 100);
  assert.equal(materializeAutomatic(result.state, new Date("2026-09-04T06:00:00Z")).added, 0);
  validateLedger(result.state);
});

test("current-value entry derives principal for gains and losses and never changes the entered value", () => {
  const s = fixture();
  const h = { id: "current", accountId: "wallet", name: "Doge", symbol: "Doge", trackingMode: "amount", archived: false };
  s.holdings.push(h);
  const principal = principalFromCurrentValue(1100, 10);
  assert.ok(Math.abs(principal - 1000) < 1e-8);
  s.entries.push(...allocateHolding(s, h, principal, "new", date));
  s.entries.push(updateHoldingCurrentValue(s, h, 1100, 10, undefined, date));
  assert.equal(holdingStats(s, h).invested, 1000);
  assert.equal(holdingStats(s, h).value, 1100);
  assert.equal(holdingStats(s, h).profit, 100);
  s.entries.push(updateHoldingCurrentValue(s, h, 900, -10, undefined, date));
  assert.equal(holdingStats(s, h).invested, 1000);
  assert.equal(holdingStats(s, h).profit, -100);
  s.entries.push(updateHoldingCurrentValue(s, h, 1234.56, 7.3, undefined, date));
  assert.equal(holdingStats(s, h).value, 1234.56);
  validateLedger(s);
});

test("reverse-calculated principal includes historical withdrawals and unchanged edits preserve return", () => {
  const s = fixture();
  const h = add(s, "BTC", "crypto", input(1, 1000, 1100));
  s.entries.push({ id: "withdraw-current", accountId: "wallet", holdingId: h.id, kind: "withdraw", amount: 200, date,
    fx: s.fxRates[0].rate, note: "test", createdAt: new Date(Date.now() + 10).toISOString() });
  const before = holdingStats(s, h);
  assert.equal(before.value, 900);
  s.entries.push(updateHoldingCurrentValue(s, h, before.value, before.roi, undefined, date));
  const after = holdingStats(s, h);
  assert.equal(after.value, 900);
  assert.equal(after.invested, 1000);
  assert.equal(after.profit, 100);
  validateLedger(s);
});

test("total loss uses known or explicitly supplied principal and rejects inconsistent values", () => {
  assert.throws(() => principalFromCurrentValue(0, -100), /原始投入/);
  assert.throws(() => principalFromCurrentValue(1, -100, 0, 1000), /必须为 0/);
  assert.throws(() => principalFromCurrentValue(0, -100, 100, 1000), /必须为 0/);
  assert.throws(() => principalFromCurrentValue(100, -101), /收益率/);
  assert.throws(() => principalFromCurrentValue(1e12, -99), /超过上限/);
  const s = fixture();
  const h = add(s, "BTC", "crypto", input(1, 1000, 1100));
  s.entries.push(updateHoldingCurrentValue(s, h, 0, -100, undefined, date));
  assert.equal(holdingStats(s, h).invested, 1000);
  assert.equal(holdingStats(s, h).profit, -1000);
  assert.equal(holdingStats(s, h).roi, -100);
  validateLedger(s);
});

test("profit-amount entry derives principal and return rate from the current value", () => {
  const s = fixture();
  const h = { id: "profit-entry", accountId: "wallet", name: "Doge", symbol: "Doge", trackingMode: "amount", archived: false };
  s.holdings.push(h);
  const principal = principalFromCurrentProfit(112.1, -216.74);
  assert.equal(principal, 328.84);
  s.entries.push(...allocateHolding(s, h, principal, "new", date));
  s.entries.push(updateHoldingCurrentProfit(s, h, 112.1, -216.74, date));
  const stats = holdingStats(s, h);
  assert.equal(stats.value, 112.1);
  assert.equal(stats.invested, 328.84);
  assert.equal(stats.profit, -216.74);
  assert.ok(Math.abs(stats.roi - (-216.74 / 328.84) * 100) < 1e-8);
  validateLedger(s);
});

test("profit-amount entry accounts for withdrawals and rejects impossible profit", () => {
  assert.equal(principalFromCurrentProfit(800, 100, 200), 900);
  assert.throws(() => principalFromCurrentProfit(100, 101), /不能大于/);
  assert.throws(() => principalFromCurrentProfit(100, Number.NaN), /收益额/);
  assert.throws(() => principalFromCurrentProfit(1e12, -1e12, 1), /超过上限/);
});

test("current amount and total invested derive profit and return rate", () => {
  const profit = profitFromCurrentPrincipal(112.1, 328.84);
  assert.equal(profit, -216.74);
  assert.equal(profitFromCurrentPrincipal(800, 900, 200), 100);
  assert.throws(() => profitFromCurrentPrincipal(100, -1), /总投入金额/);
  assert.throws(() => profitFromCurrentPrincipal(100, Number.NaN), /总投入金额/);

  const s = fixture();
  const h = { id: "principal-entry", accountId: "wallet", name: "BTC", symbol: "BTC", trackingMode: "amount", archived: false };
  s.holdings.push(h);
  s.entries.push(...allocateHolding(s, h, 328.84, "new", date));
  s.entries.push(updateHoldingCurrentProfit(s, h, 112.1, profit, date));
  const stats = holdingStats(s, h);
  assert.equal(stats.value, 112.1);
  assert.equal(stats.invested, 328.84);
  assert.equal(stats.profit, -216.74);
  assert.ok(Math.abs(stats.roi - (-216.74 / 328.84) * 100) < 1e-8);
  validateLedger(s);
});
