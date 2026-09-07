"use client";
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  PieChart,
  Pie,
} from "recharts";
import { ChartContainer } from "@/journal/components/ui/chart";
import {
  categories,
  history,
  money,
  portfolio,
  convert,
  type Ledger,
  type Currency,
} from "@/journal/lib/ledger";
export function TrendChart({
  state,
  currency,
  period,
  mode = "value",
}: {
  state: Ledger;
  currency: Currency;
  period: number | "all";
  mode?: "value" | "profit";
}) {
  const data = history(state, currency, period);
  const profit = mode === "profit";
  return (
    <>
      <ChartContainer
        config={{
          value: { label: "总资产", color: "#22c7a9" },
          net: { label: "净投入", color: "#8b98a8" },
        }}
        className="trend-chart"
      >
        <ComposedChart
          data={data}
          margin={{ top: 18, right: 15, bottom: 8, left: 5 }}
          accessibilityLayer
        >
          <defs>
            <linearGradient id="balance-fill" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor="#56ad98" stopOpacity={0.22} />
              <stop offset="100%" stopColor="#56ad98" stopOpacity={0.015} />
            </linearGradient>
          </defs>
          <CartesianGrid
            vertical={false}
            strokeDasharray="3 5"
            stroke="#253140"
          />
          <XAxis
            dataKey="label"
            axisLine={false}
            tickLine={false}
            tickMargin={12}
            minTickGap={35}
            tick={{ fontSize: 10, fill: "#93a1a6" }}
          />
          <YAxis
            axisLine={false}
            tickLine={false}
            tick={{ fontSize: 10, fill: "#93a1a6" }}
            width={55}
            tickFormatter={(v) =>
              `${currency === "USD" ? "$" : "¥"}${Math.abs(v) >= 1000 ? (v / 1000).toFixed(1) + "k" : v}`
            }
            domain={["auto", "auto"]}
          />
          <Tooltip
            labelFormatter={(_, items) => items[0]?.payload.date ?? ""}
            formatter={(v, name) => [
              money(Number(v), currency),
              name === "value"
                ? "总资产"
                : name === "profit"
                  ? "累计盈亏"
                  : "净投入",
            ]}
            contentStyle={{
              border: "1px solid #e0eae7",
              borderRadius: 10,
              fontSize: 12,
              boxShadow: "0 8px 25px #163c3410",
            }}
          />
          <Area
            dataKey={profit ? "profit" : "value"}
            type="linear"
            stroke="#22c7a9"
            strokeWidth={2.5}
            fill="url(#balance-fill)"
            dot={
              data.length < 3
                ? { r: 5, fill: "#22c7a9", stroke: "#111821", strokeWidth: 3 }
                : false
            }
            isAnimationActive={false}
          />
          {!profit && (
            <Line
              dataKey="net"
              type="linear"
              stroke="#bccbd0"
              strokeWidth={1.5}
              strokeDasharray="5 5"
              dot={false}
              isAnimationActive={false}
            />
          )}
        </ComposedChart>
      </ChartContainer>
      <div className="chart-caption">
        {data.length === 1
          ? "今天是第一笔记录。后续流水与估值会自然连成资产曲线。"
          : "每日沿用最近一次已记录估值；历史汇率缺失时沿用最早参考值。"}
      </div>
    </>
  );
}
export function AllocationChart({
  state,
  currency,
}: {
  state: Ledger;
  currency: Currency;
}) {
  const p = portfolio(state, currency);
  const data = Object.entries(categories).map(([key, info]) => ({
    ...info,
    fill: info.color,
    name: info.label,
    value: p.categoryAssets
      .filter((a) => a.category === key)
      .reduce(
        (sum, a) => sum + convert(a.value, a.currency, currency, p.fx),
        0,
      ),
  }));
  return (
    <>
      <div className="donut-wrap">
        <ChartContainer
          config={{ value: { label: "资产占比" } }}
          className="donut-chart"
        >
          <PieChart accessibilityLayer>
            <Pie
              data={
                p.value > 0
                  ? data.filter((x) => x.value > 0)
                  : [
                      {
                        name: "暂无资产",
                        value: 1,
                        color: "#edf2f4",
                        fill: "#edf2f4",
                      },
                    ]
              }
              dataKey="value"
              nameKey="name"
              innerRadius={65}
              outerRadius={85}
              paddingAngle={p.value > 0 ? 3 : 0}
              cornerRadius={4}
              stroke="none"
              startAngle={90}
              endAngle={-270}
              isAnimationActive={false}
            ></Pie>
            {p.value > 0 && (
              <Tooltip
                formatter={(v) => money(Number(v), currency)}
                contentStyle={{
                  borderRadius: 10,
                  border: "1px solid #e0eae7",
                  fontSize: 11,
                }}
              />
            )}
          </PieChart>
        </ChartContainer>
        <div className="donut-center">
          <b>
            {data.filter((x) => x.value > 0).length}
            <span> / 4</span>
          </b>
          <small>已投入方向</small>
        </div>
      </div>
      <div className="allocation-legend">
        {data.map((d) => (
          <div key={d.name}>
            <span className="dot" style={{ background: d.color }} />
            <span>{d.name}</span>
            <strong>
              {p.value > 0 ? ((d.value / p.value) * 100).toFixed(1) : "0.0"}%
            </strong>
          </div>
        ))}
      </div>
    </>
  );
}
