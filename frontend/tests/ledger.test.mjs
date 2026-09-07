import test from 'node:test';
import assert from 'node:assert/strict';
import {
  seedLedger,
  portfolio,
  accountStats,
  history,
  tradingDay,
  defaultCalendar,
  scheduledDates,
  occurrences,
  isDue,
  validateLedger,
  fxAt,
  validDate,
  activePlans,
} from '../src/journal/domain/ledger.ts';
const date = '2026-09-04';
let id = 0;
function entry(s, kind, amount, accountId = 'spot-a', extra = {}) {
  s.entries.push({
    id: 'test-' + ++id,
    accountId,
    kind,
    amount,
    date,
    fx: 6.7157,
    note: '',
    createdAt: `2026-09-04T12:00:${String(id % 60).padStart(2, '0')}.000Z`,
    ...extra,
  });
  return s.entries.at(-1);
}
const near = (a, b) => assert.ok(Math.abs(a - b) < 0.000001, `${a} != ${b}`);
function plan(extra = {}) {
  return {
    id: 'plan',
    accountId: 'liquor',
    name: 'test',
    amount: 20,
    frequency: 'daily',
    day: 1,
    time: '14:00',
    market: 'CN',
    startDate: '2026-01-01',
    paused: false,
    ...extra,
  };
}
test('initial state has four directions, two spot accounts and exactly $1220', () => {
  const s = seedLedger(date);
  validateLedger(s);
  assert.equal(s.accounts.filter((a) => a.category === 'crypto').length, 2);
  assert.equal(new Set(s.accounts.map((a) => a.category)).size, 4);
  assert.equal(portfolio(s).value, 1220);
  near(portfolio(s, 'CNY').value, 1220 * 6.7157);
  assert.equal(portfolio(s).profit, 0);
});
test('cash contributions do not create profit', () => {
  const s = seedLedger(date);
  entry(s, 'deposit', 60);
  assert.equal(portfolio(s).profit, 0);
  assert.equal(portfolio(s).value, 1280);
});
test('valuation, withdrawals, income and fees preserve economic return', () => {
  const s = seedLedger(date);
  entry(s, 'valuation', 1320);
  entry(s, 'withdraw', 200);
  entry(s, 'income', 10);
  entry(s, 'fee', 2);
  const a = accountStats(s, s.accounts[0]);
  assert.equal(a.value, 1128);
  assert.equal(a.net, 1000);
  assert.equal(a.profit, 128);
  near(a.roi, (128 / 1200) * 100);
  validateLedger(s);
});
test('a loss and zero closing equity remain valid', () => {
  const s = seedLedger(date);
  entry(s, 'valuation', 0);
  assert.equal(accountStats(s, s.accounts[0]).roi, -100);
  validateLedger(s);
});
test('same currency transfer changes account allocation, not portfolio flows or profit', () => {
  const s = seedLedger(date);
  entry(s, 'withdraw', 600, 'spot-a', { transferId: 'x' });
  entry(s, 'deposit', 600, 'spot-b', { transferId: 'x' });
  validateLedger(s);
  assert.equal(portfolio(s).value, 1220);
  assert.equal(portfolio(s).invested, 1220);
  assert.equal(portfolio(s).profit, 0);
  assert.equal(accountStats(s, s.accounts[1]).value, 600);
});
test('archive preserves equity and history', () => {
  const s = seedLedger(date);
  s.accounts[0].archived = true;
  assert.equal(portfolio(s).value, 1220);
  assert.equal(
    occurrences(s, '2026-10-01', '2026-10-01').some(
      (o) => o.account.id === 'spot-a',
    ),
    false,
  );
});
test('USD and CNY use original cash-flow FX, current asset FX', () => {
  const s = seedLedger(date);
  s.entries = [];
  s.fxRates = [{ date, rate: 6, source: 'test' }];
  entry(s, 'deposit', 700, 'liquor', { fx: 7 });
  near(portfolio(s).value, 700 / 6);
  near(portfolio(s).net, 100);
  near(portfolio(s).profit, 700 / 6 - 100);
  assert.equal(accountStats(s, s.accounts[4]).profit, 0);
  assert.equal(portfolio(s, 'CNY').profit, 0);
});
test('editing historical records recomputes later snapshots', () => {
  const s = seedLedger('2026-09-01');
  entry(s, 'deposit', 60, 'spot-a', { date: '2026-09-02' });
  entry(s, 'valuation', 1400, 'spot-a', { date: '2026-09-03' });
  const h = history(s, 'USD', 'all', date);
  assert.deepEqual(
    h.map((x) => x.value),
    [1220, 1280, 1420, 1420],
  );
  assert.equal(h.at(-1).profit, 140);
  s.entries = s.entries.filter((e) => e.amount !== 60);
  assert.equal(history(s, 'USD', 'all', date).at(-1).profit, 200);
});
test('history starts at first actual record; no invented points', () => {
  const s = seedLedger(date);
  assert.equal(history(s, 'USD', 30, date).length, 1);
});
test('Chinese market excludes holidays and compensatory weekends', () => {
  for (const d of [
    '2026-02-16',
    '2026-02-23',
    '2026-02-28',
    '2026-05-09',
    '2026-09-20',
    '2026-10-10',
  ])
    assert.equal(tradingDay(d, 'CN', defaultCalendar).open, false, d);
  assert.equal(tradingDay('2026-02-24', 'CN', defaultCalendar).open, true);
  assert.equal(tradingDay('2026-04-03', 'CN', defaultCalendar).open, true);
});
test('crypto trades every calendar day and unknown years fail closed', () => {
  assert.equal(tradingDay('2026-10-01', 'CRYPTO', defaultCalendar).open, true);
  assert.equal(tradingDay('2030-02-03', 'CRYPTO', defaultCalendar).open, true);
  assert.equal(tradingDay('2027-01-04', 'CN', defaultCalendar).known, false);
});
test('US has independent Good Friday and Labor Day calendar', () => {
  assert.equal(tradingDay('2026-04-03', 'US', defaultCalendar).open, false);
  assert.equal(tradingDay('2026-09-07', 'US', defaultCalendar).open, false);
  assert.equal(tradingDay('2026-09-07', 'CN', defaultCalendar).open, true);
});
test('daily funds skip all National Day closures, crypto does not', () => {
  assert.deepEqual(
    scheduledDates(plan(), '2026-10-01', '2026-10-09', defaultCalendar),
    ['2026-10-08', '2026-10-09'],
  );
  assert.equal(
    scheduledDates(
      plan({ market: 'CRYPTO' }),
      '2026-10-01',
      '2026-10-09',
      defaultCalendar,
    ).length,
    9,
  );
});
test('monthly holiday and month-end roll forward without duplicate dates', () => {
  assert.deepEqual(
    scheduledDates(
      plan({ frequency: 'monthly' }),
      '2026-10-01',
      '2026-10-10',
      defaultCalendar,
    ),
    ['2026-10-08'],
  );
  assert.deepEqual(
    scheduledDates(
      plan({ frequency: 'monthly', day: 31 }),
      '2026-02-01',
      '2026-03-04',
      defaultCalendar,
    ),
    ['2026-02-02', '2026-03-02'],
  );
});
test('weekly holiday shifts to next US trading day', () => {
  assert.deepEqual(
    scheduledDates(
      plan({ frequency: 'weekly', market: 'US', day: 1 }),
      '2026-09-07',
      '2026-09-13',
      defaultCalendar,
    ),
    ['2026-09-08'],
  );
});
test('paused plans and future starts never generate occurrences', () => {
  assert.equal(
    scheduledDates(plan({ paused: true }), '2026-09-01', date, defaultCalendar)
      .length,
    0,
  );
  assert.equal(
    scheduledDates(
      plan({ startDate: '2026-10-01' }),
      '2026-09-01',
      date,
      defaultCalendar,
    ).length,
    0,
  );
});
test('plan dashboard data follows pause, resume and delete immediately', () => {
  const state = seedLedger(date);
  const planId = state.plans[0].id;
  assert.ok(activePlans(state).some((item) => item.id === planId));
  assert.ok(
    occurrences(state, date, '2026-10-31').some(
      (item) => item.plan.id === planId,
    ),
  );

  state.plans.find((item) => item.id === planId).paused = true;
  assert.equal(
    activePlans(state).some((item) => item.id === planId),
    false,
  );
  assert.equal(
    occurrences(state, date, '2026-10-31').some(
      (item) => item.plan.id === planId,
    ),
    false,
  );

  state.plans.find((item) => item.id === planId).paused = false;
  assert.ok(activePlans(state).some((item) => item.id === planId));
  state.plans = state.plans.filter((item) => item.id !== planId);
  assert.equal(
    activePlans(state).some((item) => item.id === planId),
    false,
  );
  assert.equal(
    occurrences(state, date, '2026-10-31').some(
      (item) => item.plan.id === planId,
    ),
    false,
  );
});
test('all markets use Beijing time in summer and winter', () => {
  const s = seedLedger(date);
  const o = {
    plan: plan({ market: 'US', time: '10:00' }),
    date,
    key: 'x',
    account: s.accounts[2],
    done: false,
    skipped: false,
  };
  assert.equal(isDue(o, new Date('2026-09-04T01:59:00Z')), false);
  assert.equal(isDue(o, new Date('2026-09-04T02:00:00Z')), true);
  assert.equal(
    isDue({ ...o, date: '2026-01-05' }, new Date('2026-01-05T01:59:00Z')),
    false,
  );
  assert.equal(
    isDue({ ...o, date: '2026-01-05' }, new Date('2026-01-05T02:00:00Z')),
    true,
  );
});
test('confirmed and skipped instances are idempotent', () => {
  const s = seedLedger(date);
  const o = occurrences(s, date, date).find((o) => o.account.id === 'liquor');
  assert.ok(o);
  entry(s, 'deposit', 20, 'liquor', { planKey: o.key });
  assert.equal(
    occurrences(s, date, date).find((x) => x.key === o.key).done,
    true,
  );
  entry(s, 'deposit', 20, 'liquor', { planKey: o.key });
  assert.throws(() => validateLedger(s), /重复/);
});
test('rejects negative balance, NaN, invalid dates, currencies and dangling references', () => {
  let s = seedLedger(date);
  entry(s, 'withdraw', 1300);
  assert.throws(() => validateLedger(s), /余额/);
  s = seedLedger(date);
  s.entries[0].amount = NaN;
  assert.throws(() => validateLedger(s));
  s = seedLedger(date);
  s.entries[0].date = '2026-02-30';
  assert.throws(() => validateLedger(s));
  s = seedLedger(date);
  s.accounts[0].currency = 'CNY';
  assert.throws(() => validateLedger(s));
  s = seedLedger(date);
  s.entries[0].accountId = 'missing';
  assert.throws(() => validateLedger(s));
  assert.equal(validDate('2026-02-29'), false);
});
test('rejects partial transfers and malformed imports', () => {
  const s = seedLedger(date);
  entry(s, 'withdraw', 200, 'spot-a', { transferId: 'bad' });
  assert.throws(() => validateLedger(s), /转账/);
  for (const v of [null, {}, [], { version: 2 }])
    assert.throws(() => validateLedger(v));
});
test('fx history uses nearest prior rate and explicit earliest fallback', () => {
  const s = seedLedger(date);
  s.fxRates = [
    { date: '2026-09-01', rate: 7, source: 'test' },
    { date, rate: 6.7, source: 'test' },
  ];
  assert.equal(fxAt(s, '2026-09-02').rate, 7);
  assert.equal(fxAt(s, '2026-08-01').rate, 7);
});
