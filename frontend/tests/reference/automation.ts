// Test-only reference for parity with the original Clarity implementation.
import {
  type Ledger,
  type Plan,
  occurrences,
  isDue,
  today,
  fxAt,
  validateLedger,
  planAccountAllocations,
  planEntryKeys,
  money,
  uid,
  positionStats,
  assetType,
} from "../../src/journal/domain/ledger.ts";
export function upgradeLedger(input: Ledger, now = new Date()): Ledger {
  const state = structuredClone(input);
  state.holdings ??= [];
  // Existing users requested automatic recording now; never invent earlier unconfirmed contributions.
  state.plans = state.plans.map((p) =>
    p.mode
      ? p
      : {
          ...p,
          mode: "auto",
          autoFrom: today("Asia/Shanghai", now),
        },
  );
  return state;
}
export function scheduledInstant(date: string, plan: Plan): string {
  const target = Date.parse(date + "T" + plan.time + ":00Z");
  let value = target;
  const zone = "Asia/Shanghai";
  for (let i = 0; i < 2; i++) {
    const parts = new Intl.DateTimeFormat("en-CA", {
      timeZone: zone,
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hourCycle: "h23",
    }).formatToParts(new Date(value));
    const get = (key: string) => parts.find((p) => p.type === key)!.value;
    const observed = Date.parse(
      `${get("year")}-${get("month")}-${get("day")}T${get("hour")}:${get("minute")}:${get("second")}Z`,
    );
    value += target - observed;
  }
  return new Date(value).toISOString();
}
export function materializeAutomatic(
  input: Ledger,
  now = new Date(),
): { state: Ledger; added: number } {
  const state = upgradeLedger(input, now);
  let added = 0;
  for (const plan of state.plans) {
    if (plan.mode !== "auto" || plan.paused) continue;
    const from = [plan.startDate, plan.autoFrom ?? plan.startDate]
      .sort()
      .at(-1)!;
    const end = today("Asia/Shanghai", now);
    const single = { ...state, plans: [plan] };
    for (const o of occurrences(single, from, end)) {
      if (o.done || o.skipped || !isDue(o, now)) continue;
      const entryKeys = planEntryKeys(plan, o.date);
      const allocations = planAccountAllocations(state, plan, o.date)
        .map((allocation, index) => ({
          allocation,
          entryKey: entryKeys[index],
        }))
        .filter(
          ({ entryKey }) =>
            !state.entries.some((entry) => entry.planKey === entryKey),
        );
      if (state.entries.length + allocations.length > 10000)
        throw Error("流水已达上限，请先备份并整理历史记录后再自动记账");
      allocations.forEach(({ allocation, entryKey }) => {
        const holding = state.holdings?.find(
          (h) => h.id === allocation.holdingId,
        );
        const position = holding ? positionStats(state, holding, o.date) : null;
        const estimatedQuantity =
          holding &&
          holding.trackingMode !== "amount" &&
          assetType(state, holding) !== "grid" &&
          position?.unitPrice &&
          position.unitPrice > 0
            ? allocation.amount / position.unitPrice
            : undefined;
        state.entries.push({
          id: uid(),
          accountId: plan.accountId,
          ...(allocation.holdingId
            ? { holdingId: allocation.holdingId }
            : {}),
          kind: "deposit",
          amount: allocation.amount,
          ...(estimatedQuantity !== undefined
            ? {
                quantityDelta: estimatedQuantity,
                unitPrice: position!.unitPrice!,
              }
            : {}),
          date: o.date,
          fx: fxAt(state, o.date).rate,
          note:
            "按计划自动记账：" +
            plan.name +
            " · " +
            money(
              allocation.plannedAmount,
              plan.currency ?? o.account.currency,
            ) +
            "（北京时间；不代表实际成交）" +
            (holding?.trackingMode === "amount"
              ? "；已累计投入金额，可在资产中更新收益率"
              : estimatedQuantity !== undefined
                ? "；数量按最近手动价格估算"
                : "；数量待实际成交后更新"),
          createdAt: scheduledInstant(o.date, plan),
          planKey: entryKey,
          automatic: true,
        });
        added++;
      });
    }
  }
  validateLedger(state);
  return { state, added };
}
