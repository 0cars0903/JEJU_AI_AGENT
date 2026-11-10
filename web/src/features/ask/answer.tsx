"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useIconHover } from "@animateicons/react";
import { Button } from "@/components/ui/button";
import { CircleXIcon, InfoIcon, MapPinnedIcon, PrinterIcon, TableIcon, TriangleAlertIcon } from "@/components/icons";
import { BadgeRow } from "@/components/badges";
import { ChartFrame, OpenCloseChart, RankChart, SurvivalChart, TrendChart } from "@/components/chart-frame";
import { CompareTable, type CompareRow } from "@/components/compare-table";
import { Evidence } from "@/components/evidence";
import { Panel } from "@/components/section";
import type { AskResult, ToolResult } from "@/lib/api";
import { printPage } from "@/lib/print";
import { queries } from "@/lib/queries";
import { ProcessSteps } from "./process-steps";
import { askedDongs } from "./trace";

const COMPARE_LABELS: Record<string, string> = {
  stores: "점포 수(곳)", close_3y_pct: "음식점 3년 폐업률(%)", close_label: "폐업률 판정", survival_5y_pct: "음식점 5년 생존율(%)", survival_n: "생존율 표본(건)", survival_label: "생존율 판정",
  visit_index: "방문/거주 지수", work_index: "근무/거주 지수", old_pct: "거주 60대 이상 비중(%)", young_pct: "거주 20~30대 비중(%)", bus_daily: "버스 일평균 이용(명)",
};

function compareRows(profiles: ToolResult[]): CompareRow[] {
  const rows: CompareRow[] = Object.entries(COMPARE_LABELS).map(([k, label]) => ({
    label,
    values: Object.fromEntries(profiles.map((p) => {
      const v = p.values?.[k];
      return [p.dong as string, typeof v === "number" ? v.toLocaleString("en-US") : String(v)];
    })),
  }));
  rows.push({
    label: "특화계수 최고 업종",
    values: Object.fromEntries(profiles.map((p) => [p.dong as string, `${p.values?.top_lq?.[0]?.major} ${p.values?.top_lq?.[0]?.lq}`])),
  });
  return rows;
}

function AnswerLines({ answer }: { answer: string }) {
  const lines = answer.split("\n").filter((l) => l.trim());
  return (
    <ul className="flex flex-col gap-1.5" data-testid="answer">
      {lines.map((line, i) =>
        line.startsWith("[") ? (
          <li key={i} className="mt-2 list-none font-bold text-(--krds-text-bolder) first:mt-0">{line}</li>
        ) : (
          <li key={i} className="ml-5 list-disc">{line}</li>
        ),
      )}
    </ul>
  );
}

const TONES = {
  clarify: { Icon: InfoIcon, label: "확인이 필요합니다", cls: "border-(--krds-border-information,var(--krds-border-primary)) bg-(--krds-surface-information-subtler)", icon: "text-(--krds-text-information)" },
  out_of_scope: { Icon: TriangleAlertIcon, label: "답할 수 없는 질문입니다", cls: "border-(--krds-border-warning,var(--krds-border-gray)) bg-(--krds-surface-warning-subtler)", icon: "text-(--krds-text-warning)" },
  no_data: { Icon: InfoIcon, label: "자료를 찾지 못했습니다", cls: "border-(--krds-border-gray-light) bg-muted", icon: "text-(--krds-text-subtle)" },
  blocked: { Icon: CircleXIcon, label: "검증을 통과하지 못해 답을 막았습니다", cls: "border-(--krds-border-danger,var(--krds-border-gray)) bg-(--krds-surface-danger-subtler)", icon: "text-(--krds-text-danger)" },
};

function suggestions(r: AskResult): string[] {
  if (r.status === "out_of_scope") {
    const part = r.answer.split("답할 수 있습니다:")[1];
    return part ? part.split(" / ").map((s) => s.trim()).filter(Boolean) : [];
  }
  if (r.status === "clarify") {
    const amb = ((r.trace[0]?.result as { ambiguous?: Record<string, string[]> } | undefined)?.ambiguous ?? {});
    const entry = Object.entries(amb)[0];
    if (entry) return entry[1].map((c) => r.question.replace(entry[0], c));
    return ["애월읍", "노형동"].map((d) => (r.question.includes("우리 동네") ? r.question.replace("우리 동네", d) : `${d} ${r.question}`));
  }
  return [];
}

function Notice({ result, onAsk }: { result: AskResult; onAsk: (q: string) => void }) {
  const tone = TONES[result.status as keyof typeof TONES];
  const options = suggestions(result);
  return (
    <section className={`rounded-(--krds-radius-large1) border p-4 md:p-6 ${tone.cls}`} data-testid={`notice-${result.status}`}>
      <p className="flex items-center gap-2 font-bold">
        <tone.Icon size={22} className={`shrink-0 ${tone.icon}`} aria-hidden />
        {tone.label}
      </p>
      <p className="mt-2" data-testid="answer">{result.answer}</p>
      {options.length > 0 && (
        <div className="mt-3 flex flex-wrap gap-2 print:hidden">
          {options.map((o) => (
            <Button key={o} variant="outline" size="sm" className="h-auto min-h-10 whitespace-normal bg-background py-2 text-left" onClick={() => onAsk(o)}>
              {o}
            </Button>
          ))}
        </div>
      )}
    </section>
  );
}

function ToolCharts({ result }: { result: AskResult }) {
  const { data: meta } = useQuery(queries.meta());
  const profiles = result.tool_results.filter((t) => t.tool === "dong_profile");
  return (
    <>
      {result.tool_results.map((t, i) => {
        const v = t.values ?? {};
        const dong = String(t.dong ?? "");
        if (t.tool === "compare_rank" && v.ranked && v.rows?.length >= 2) {
          const rows = v.rows.filter((r: { value: number | null }) => r.value !== null);
          return (
            <ChartFrame key={i} testId="chart-rank" title={v.metric_label} columns={["동네", v.metric_label]} rows={rows.map((r: { dong: string; value: number }) => [r.dong, r.value])}>
              <RankChart rows={rows} label={v.metric_label} />
            </ChartFrame>
          );
        }
        if (t.tool === "compare_rank" && !v.ranked && v.rows) {
          return (
            <Panel key={i} title="제주 평균과 차이가 확인된 동네" description="표본 오차가 커서 순위를 내지 않습니다. 가나다순입니다." testId="unranked-table">
              <div className="overflow-x-auto" tabIndex={0} role="region" aria-label="제주 평균과 차이가 확인된 동네 표">
                <table className="w-full min-w-[34rem] text-left text-[length:var(--krds-fs-body-small)]">
                  <thead className="bg-muted">
                    <tr>{["동네", "판정", "값(%)", "95% 구간", "표본"].map((h) => <th key={h} className="px-3 py-2 font-semibold">{h}</th>)}</tr>
                  </thead>
                  <tbody>
                    {v.rows.map((r: { dong: string; value_pct: number; lo_pct: number; hi_pct: number; n: number; label: string; small_sample: boolean }) => (
                      <tr key={r.dong} className="border-t border-(--krds-border-gray-light)">
                        <td className="px-3 py-2 font-semibold">{r.dong}</td>
                        <td className="px-3 py-2">{r.label}</td>
                        <td className="px-3 py-2">{r.value_pct}</td>
                        <td className="px-3 py-2">{r.lo_pct}~{r.hi_pct}</td>
                        <td className="px-3 py-2">{r.n.toLocaleString("ko-KR")}{r.small_sample ? " (표본 적음)" : ""}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Panel>
          );
        }
        if (t.tool === "biz_diagnostic") {
          const years = v.restaurant_years as { year: number; open: number; close: number }[] | undefined;
          const curve = v.survival_curve as { year: number; pct: number }[] | undefined;
          const jeju = new Map(meta?.jeju_survival.map((x) => [x.year, x.pct]));
          return (
            <div key={i} className="grid gap-4 md:grid-cols-2">
              {years && years.length > 0 && (
                <ChartFrame testId="chart-open-close" title={`${dong} ${v.category ?? "음식점"} 개업·폐업`} description="단위: 건" columns={["연도", "개업", "폐업"]} rows={years.map((y) => [String(y.year), y.open, y.close])}>
                  <OpenCloseChart rows={years} />
                </ChartFrame>
              )}
              {curve && (
                <ChartFrame testId="chart-survival" title="음식점 영업 지속 곡선" description="2015-01~2020-08 개업 기준. 단위: %" columns={["개업 후 연수", dong, "제주 전체"]} rows={curve.map((c) => [`${c.year}년`, c.pct, jeju.get(c.year) ?? null])}>
                  <SurvivalChart dong={dong} rows={curve.map((c) => ({ year: c.year, dong: c.pct, jeju: jeju.get(c.year) ?? null }))} />
                </ChartFrame>
              )}
            </div>
          );
        }
        if (t.tool === "bus_usage" && v.trend) {
          const rows = v.trend as { ym: string; daily: number }[];
          return (
            <ChartFrame key={i} testId="chart-bus" title={`${dong} 월별 버스 일평균 이용`} description="단위: 명" columns={["월", "일평균(명)"]} rows={rows.map((r) => [r.ym, r.daily])}>
              <TrendChart rows={rows.map((r) => ({ ym: r.ym, value: r.daily }))} unit="명" seriesName="일평균 이용" />
            </ChartFrame>
          );
        }
        if (t.tool === "population_mix" && v.trend) {
          const rows = (v.trend as { ym: string; visit_index: number; days: number }[]).filter((r) => r.days >= 28);
          if (rows.length === 0) return null;
          return (
            <ChartFrame key={i} testId="chart-visit" title={`${dong} 월별 방문/거주 지수`} description="28일 이상 수집한 달만 그립니다. 손님 수가 아니라 거주 값에 대한 방문 값의 비율입니다." columns={["월", dong, "제주 전체"]} rows={rows.map((r) => [r.ym, r.visit_index, meta?.jeju_visit[r.ym] ?? null])}>
              <TrendChart reference rows={rows.map((r) => ({ ym: r.ym, value: r.visit_index, reference: meta?.jeju_visit[r.ym] ?? null }))} unit="" seriesName={dong} />
            </ChartFrame>
          );
        }
        if (t.tool === "dong_profile" && profiles.length === 1 && t.badges) return <BadgeRow key={i} badges={t.badges} />;
        return null;
      })}
    </>
  );
}

function FollowUps({ result, onAsk }: { result: AskResult; onAsk: (q: string) => void }) {
  const { ref, triggerProps } = useIconHover();
  const dongs = askedDongs(result);
  if (dongs.length === 0) return null;
  const single = dongs.length === 1 ? dongs[0] : null;
  const asks = single ? [`${single} 생활 진단해 줘`, `${single} 버스 이용 현황 어때?`, `${single} 오가는 사람 구성은?`].filter((q) => q !== result.question) : [];
  return (
    <section aria-label="이어서 보기" className="flex flex-col gap-2 print:hidden" data-testid="follow-ups">
      <p className="font-semibold">이어서 보기</p>
      <div className="flex flex-wrap gap-2">
        {asks.map((q) => (
          <Button key={q} variant="secondary" size="sm" className="h-auto min-h-10 whitespace-normal py-2" onClick={() => onAsk(q)}>
            {q}
          </Button>
        ))}
        {single && (
          <Button variant="outline" size="sm" {...triggerProps} render={<Link href={`/diagnosis/?dong=${encodeURIComponent(single)}`} className="text-foreground no-underline hover:text-foreground" />} nativeButton={false}>
            <MapPinnedIcon ref={ref} size={18} aria-hidden />
            {single} 지도와 전체 진단
          </Button>
        )}
        <Button variant="outline" size="sm" render={<Link href={`/compare/?dongs=${dongs.map(encodeURIComponent).join(",")}`} className="text-foreground no-underline hover:text-foreground" />} nativeButton={false}>
          <TableIcon size={18} aria-hidden />
          {dongs.length > 1 ? "비교표 화면으로" : "다른 동네와 비교"}
        </Button>
      </div>
    </section>
  );
}

export function AnswerView({ result, onAsk }: { result: AskResult; onAsk: (q: string) => void }) {
  const profiles = result.tool_results.filter((t) => t.tool === "dong_profile");
  const isCompare = result.status === "ok" && profiles.length > 1;
  const periods = result.tool_results.length === 1 ? result.tool_results[0].period : undefined;
  return (
    <div className="flex flex-col gap-4">
      <ProcessSteps result={result} />
      {(result.carried_dongs?.length ?? 0) > 0 && (
        <p className="flex items-center gap-2 text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)" data-testid="carried">
          <InfoIcon size={18} className="shrink-0" aria-hidden />
          동네를 말하지 않아 앞 질문의 {result.carried_dongs?.join(", ")} 기준으로 답했습니다.
        </p>
      )}
      {result.status !== "ok" ? (
        <Notice result={result} onAsk={onAsk} />
      ) : (
        <>
          <Panel
            title="답변"
            testId="answer-panel"
            action={
              <Button variant="outline" size="sm" onClick={printPage}>
                <PrinterIcon size={18} aria-hidden />
                A4 인쇄
              </Button>
            }
          >
            {isCompare && (
              <div className="mb-4">
                <CompareTable dongs={profiles.map((p) => p.dong as string)} rows={compareRows(profiles)} />
              </div>
            )}
            <AnswerLines answer={result.answer} />
            {result.tool_errors?.map((e) => (
              <p key={e} className="mt-2 text-[length:var(--krds-fs-body-small)] text-(--krds-text-danger)">일부 자료를 가져오지 못했습니다: {e}</p>
            ))}
          </Panel>
          <ToolCharts result={result} />
        </>
      )}
      {result.limits.length > 0 && <Evidence sources={result.sources} periods={periods} limits={result.limits} />}
      <FollowUps result={result} onAsk={onAsk} />
    </div>
  );
}
