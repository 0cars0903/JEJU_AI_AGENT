"use client";

import dynamic from "next/dynamic";
import { Panel } from "@/components/section";
import { BlockSkeleton } from "@/components/states";

const loading = () => <BlockSkeleton className="h-60 w-full" />;
// recharts는 무거워 차트가 있는 화면에서만 받는다. 자리표시 높이를 차트와 맞춰 화면 밀림을 막는다.
export const OpenCloseChart = dynamic(() => import("./charts").then((m) => m.OpenCloseChart), { ssr: false, loading });
export const SurvivalChart = dynamic(() => import("./charts").then((m) => m.SurvivalChart), { ssr: false, loading });
export const TrendChart = dynamic(() => import("./charts").then((m) => m.TrendChart), { ssr: false, loading });
export const RankChart = dynamic(() => import("./charts").then((m) => m.RankChart), { ssr: false, loading });

/** 차트 칸. 색을 읽지 못해도 값을 볼 수 있게 표 보기를 함께 둔다. */
export function ChartFrame({ title, description, columns, rows, children, testId }: {
  title: string;
  description?: string;
  columns: string[];
  rows: (string | number | null)[][];
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <Panel title={title} description={description} testId={testId}>
      <figure role="img" aria-label={`${title}. 값은 아래 표 보기에서 읽을 수 있습니다.`}>
        {children}
      </figure>
      <details className="mt-2 text-[length:var(--krds-fs-body-small)] print:hidden">
        <summary className="min-h-10 cursor-pointer py-2 text-(--krds-text-subtle)">표로 보기</summary>
        <div className="max-h-60 overflow-auto rounded-(--radius) border border-(--krds-border-gray-light)">
          <table className="w-full text-left">
            <thead className="sticky top-0 bg-muted">
              <tr>{columns.map((c) => <th key={c} className="px-3 py-1.5 font-semibold">{c}</th>)}</tr>
            </thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={i} className="border-t border-(--krds-border-gray-light)">
                  {r.map((v, j) => <td key={j} className="px-3 py-1.5">{v === null ? "자료 없음" : typeof v === "number" ? v.toLocaleString("ko-KR") : v}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </Panel>
  );
}
