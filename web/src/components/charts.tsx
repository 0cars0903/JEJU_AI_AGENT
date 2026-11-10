"use client";

import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PRINT_CHART_HEIGHT, PRINT_CHART_WIDTH, usePrinting } from "@/lib/print";

/**
 * 차트 4종과 순위 막대. 색은 KRDS 토큰을 CSS 변수로 쓴다(개업 primary-50, 폐업 point-50: 색약 검증 통과).
 * '제주 전체'는 비교 대상이 아니라 기준선이라 회색으로 둔다. 애니메이션은 인쇄와 시험에서 값이 흔들리지 않게 끈다.
 */
function Frame({ height, children }: { height: number; children: React.ReactElement }) {
  const printing = usePrinting();
  return (
    <ResponsiveContainer width={printing ? PRINT_CHART_WIDTH : "100%"} height={printing ? PRINT_CHART_HEIGHT : height}>
      {children}
    </ResponsiveContainer>
  );
}

const AXIS = { fontSize: 13, fill: "var(--krds-text-subtle)" };
const TIP = {
  contentStyle: { background: "var(--krds-surface-white)", border: "1px solid var(--krds-border-gray)", borderRadius: 6, fontSize: 14, color: "var(--krds-text-basic)" },
  itemStyle: { color: "var(--krds-text-basic)" },
  labelStyle: { color: "var(--krds-text-basic)", fontWeight: 600 },
};
const num = (v: unknown) => (typeof v === "number" ? v.toLocaleString("ko-KR") : String(v));
const legendText = (value: string) => <span style={{ color: "var(--krds-text-basic)", fontSize: 14 }}>{value}</span>;

function grid() {
  return <CartesianGrid vertical={false} stroke="var(--chart-grid)" strokeWidth={1} />;
}

export function OpenCloseChart({ rows }: { rows: { year: number; open: number; close: number }[] }) {
  return (
    <Frame height={260}>
      <BarChart data={rows} barGap={2} barCategoryGap="30%" margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
        {grid()}
        <XAxis dataKey="year" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--chart-grid)" }} />
        <YAxis tick={AXIS} width={40} tickLine={false} axisLine={false} allowDecimals={false} />
        <Tooltip {...TIP} cursor={{ fill: "var(--krds-surface-gray-subtler)" }} formatter={(v) => [`${num(v)}건`]} />
        <Legend verticalAlign="top" align="left" height={30} iconType="square" formatter={legendText} />
        <Bar dataKey="open" name="개업" fill="var(--chart-open)" maxBarSize={24} radius={[4, 4, 0, 0]} isAnimationActive={false} />
        <Bar dataKey="close" name="폐업" fill="var(--chart-close)" maxBarSize={24} radius={[4, 4, 0, 0]} isAnimationActive={false} />
      </BarChart>
    </Frame>
  );
}

export function SurvivalChart({ dong, rows }: { dong: string; rows: { year: number; dong: number; jeju: number | null }[] }) {
  return (
    <Frame height={260}>
      <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        {grid()}
        <XAxis dataKey="year" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--chart-grid)" }} tickFormatter={(y) => `${y}년`} />
        <YAxis domain={[0, 100]} tick={AXIS} width={40} tickLine={false} axisLine={false} />
        <Tooltip {...TIP} labelFormatter={(y) => `개업 후 ${y}년`} formatter={(v, n) => [`${num(v)}%`, n]} />
        <Legend verticalAlign="top" align="left" height={30} formatter={legendText} />
        <Line dataKey="dong" name={dong} stroke="var(--chart-open)" strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--krds-surface-white)", fill: "var(--chart-open)" }} isAnimationActive={false} />
        <Line dataKey="jeju" name="제주 전체" stroke="var(--chart-reference)" strokeWidth={2} dot={{ r: 4, strokeWidth: 2, stroke: "var(--krds-surface-white)", fill: "var(--chart-reference)" }} isAnimationActive={false} />
      </LineChart>
    </Frame>
  );
}

export function TrendChart({ rows, unit, seriesName, reference }: {
  rows: { ym: string; value: number | null; reference?: number | null }[];
  unit: string;
  seriesName: string;
  reference?: boolean;
}) {
  return (
    <Frame height={240}>
      <LineChart data={rows} margin={{ top: 8, right: 16, bottom: 0, left: 0 }}>
        {grid()}
        <XAxis dataKey="ym" tick={AXIS} tickLine={false} axisLine={{ stroke: "var(--chart-grid)" }} minTickGap={36} />
        <YAxis tick={AXIS} width={48} tickLine={false} axisLine={false} domain={["auto", "auto"]} tickFormatter={num} />
        <Tooltip {...TIP} formatter={(v, n) => [`${num(v)}${unit}`, n]} />
        {reference && <Legend verticalAlign="top" align="left" height={30} formatter={legendText} />}
        <Line dataKey="value" name={seriesName} stroke="var(--chart-open)" strokeWidth={2} dot={false} activeDot={{ r: 5 }} isAnimationActive={false} connectNulls={false} />
        {reference && <Line dataKey="reference" name="제주 전체" stroke="var(--chart-reference)" strokeWidth={2} dot={false} activeDot={{ r: 5 }} isAnimationActive={false} />}
      </LineChart>
    </Frame>
  );
}

export function RankChart({ rows, label }: { rows: { dong: string; value: number }[]; label: string }) {
  return (
    <Frame height={Math.max(140, rows.length * 38 + 30)}>
      <BarChart data={rows} layout="vertical" margin={{ top: 0, right: 24, bottom: 0, left: 0 }}>
        <CartesianGrid horizontal={false} stroke="var(--chart-grid)" />
        <XAxis type="number" tick={AXIS} tickLine={false} axisLine={false} />
        <YAxis type="category" dataKey="dong" tick={AXIS} width={72} tickLine={false} axisLine={{ stroke: "var(--chart-grid)" }} />
        <Tooltip {...TIP} cursor={{ fill: "var(--krds-surface-gray-subtler)" }} formatter={(v) => [num(v), label]} />
        <Bar dataKey="value" fill="var(--chart-open)" maxBarSize={24} radius={[0, 4, 4, 0]} isAnimationActive={false} />
      </BarChart>
    </Frame>
  );
}
