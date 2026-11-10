"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { parseAsString, useQueryState } from "nuqs";
import { Button } from "@/components/ui/button";
import { PrinterIcon } from "@/components/icons";
import { BadgeRow } from "@/components/badges";
import { ChartFrame, OpenCloseChart, SurvivalChart, TrendChart } from "@/components/chart-frame";
import { Evidence } from "@/components/evidence";
import { Panel } from "@/components/section";
import { BlockSkeleton, EmptyState, ErrorState } from "@/components/states";
import { printPage } from "@/lib/print";
import { queries } from "@/lib/queries";
import { JejuMap } from "./jeju-map";

const DEFAULT_DONG = "노형동";

function CategorySection({ dong, categories }: { dong: string; categories: string[] }) {
  const [category, setCategory] = useQueryState("category", parseAsString.withDefault(""));
  const query = useQuery({ ...queries.dong(dong, category || undefined), enabled: Boolean(category) });
  const cb = query.data?.category_biz;
  const years = cb?.values?.restaurant_years as { year: number; open: number; close: number }[] | undefined;
  return (
    <Panel breakable className={category ? undefined : "print:hidden"} title={category ? `창업 진단: ${category}` : "창업 진단"} description="동네와 업종을 함께 봅니다. 점포 수와 업종 비중은 업종별 값이고, 폐업률과 생존율은 음식점 전체 값입니다." testId="startup">
      <label htmlFor="category" className="mb-1.5 block font-semibold print:hidden">업종</label>
      <select id="category" className="field sm:max-w-xs print:hidden" value={category} onChange={(e) => setCategory(e.target.value || null)}>
        <option value="">업종을 고르세요</option>
        {categories.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      {category && query.isPending && <BlockSkeleton className="mt-4 h-40 w-full" />}
      {category && query.isError && <div className="mt-4"><ErrorState error={query.error} onRetry={() => query.refetch()} /></div>}
      {cb && (
        <div className="mt-4 flex flex-col gap-4">
          <ul className="flex list-disc flex-col gap-1.5 pl-5" data-testid="startup-summary">
            {cb.summary?.map((s) => <li key={s}>{s}</li>)}
          </ul>
          {years && years.length > 0 && (
            <ChartFrame title={`${dong} ${category} 개업·폐업`} description="단위: 건" columns={["연도", "개업", "폐업"]} rows={years.map((y) => [String(y.year), y.open, y.close])}>
              <OpenCloseChart rows={years} />
            </ChartFrame>
          )}
        </div>
      )}
    </Panel>
  );
}

export function DiagnosisView() {
  const [dong, setDong] = useQueryState("dong", parseAsString.withDefault(DEFAULT_DONG));
  const [metric, setMetric] = useQueryState("metric", parseAsString.withDefault("점포수"));
  const meta = useQuery(queries.meta());
  const map = useQuery(queries.map());
  const detail = useQuery(queries.dong(dong));
  const metricInfo = meta.data?.metrics.find((m) => m.key === metric);
  const d = detail.data;
  const jeju = new Map(meta.data?.jeju_survival.map((x) => [x.year, x.pct]));
  const years = d?.biz.values?.restaurant_years as { year: number; open: number; close: number }[] | undefined;
  const curve = d?.biz.values?.survival_curve as { year: number; pct: number }[] | undefined;
  const busTrend = d?.bus.values?.trend as { ym: string; daily: number }[] | undefined;
  const visit = (d?.population.values?.trend as { ym: string; visit_index: number; days: number }[] | undefined)?.filter((r) => r.days >= 28);

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1>{dong} 생활 진단</h1>
          <p className="mt-1 text-(--krds-text-subtle) print:hidden">지도에서 동네를 누르거나 목록에서 고르세요.</p>
        </div>
        <Button variant="outline" onClick={printPage} className="print:hidden" data-testid="print">
          <PrinterIcon size={18} aria-hidden />
          A4 인쇄
        </Button>
      </header>

      <div className="grid items-start gap-6 lg:grid-cols-2">
        <div className="flex flex-col gap-3 print:hidden">
          <div className="grid gap-3 sm:grid-cols-2">
            <div>
              <label htmlFor="dong" className="mb-1.5 block font-semibold">동네</label>
              <select id="dong" className="field" value={dong} onChange={(e) => setDong(e.target.value)}>
                {meta.data?.dongs.map((x) => <option key={x} value={x}>{x}</option>)}
                {!meta.data && <option value={dong}>{dong}</option>}
              </select>
            </div>
            <div>
              <label htmlFor="metric" className="mb-1.5 block font-semibold">지도에 표시할 값</label>
              <select id="metric" className="field" value={metric} onChange={(e) => setMetric(e.target.value)}>
                {meta.data?.metrics.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
              </select>
            </div>
          </div>
          {map.isPending && <BlockSkeleton className="aspect-[3/2] w-full" />}
          {map.isError && <ErrorState error={map.error} onRetry={() => map.refetch()} />}
          {map.data && <JejuMap data={map.data} metric={metric} metricLabel={metricInfo?.label ?? metric} selected={dong} onSelect={(x) => setDong(x)} />}
        </div>

        <div className="flex min-w-0 flex-col gap-4">
          {detail.isPending && <BlockSkeleton className="h-72 w-full" />}
          {detail.isError && <ErrorState error={detail.error} onRetry={() => detail.refetch()} />}
          {d && (
            <>
              {d.profile.badges && <BadgeRow badges={d.profile.badges} />}
              <Panel title="요약" testId="summary">
                <ul className="flex list-disc flex-col gap-1.5 pl-5">
                  {d.profile.summary?.map((s) => <li key={s}>{s}</li>)}
                </ul>
              </Panel>
            </>
          )}
        </div>
      </div>

      {d && (
        <Panel title="상권·인구·버스 자세히" testId="detail-summary" breakable>
          <div className="grid gap-5 lg:grid-cols-3 print:grid-cols-1 print:gap-3">
            {[
              { label: "상권", lines: d.biz.summary },
              { label: "인구", lines: d.population.summary },
              { label: "버스", lines: d.bus.summary ?? ["버스 자료가 없습니다."] },
            ].map((s) => (
              <div key={s.label} className="print-avoid">
                <p className="mb-1 font-semibold">{s.label}</p>
                <ul className="flex list-disc flex-col gap-1 pl-5 text-[length:var(--krds-fs-body-small)]">
                  {s.lines?.map((l) => <li key={l}>{l}</li>)}
                </ul>
              </div>
            ))}
          </div>
        </Panel>
      )}

      {d && meta.data && <CategorySection dong={dong} categories={meta.data.categories} />}

      {d && (
        <div className="grid gap-4 md:grid-cols-2 print:grid-cols-2">
          {years && (
            <ChartFrame testId="chart-open-close" title="음식점 개업·폐업" description="단위: 건" columns={["연도", "개업", "폐업"]} rows={years.map((y) => [String(y.year), y.open, y.close])}>
              <OpenCloseChart rows={years} />
            </ChartFrame>
          )}
          {curve && (
            <ChartFrame testId="chart-survival" title="음식점 영업 지속 곡선" description="2015-01~2020-08 개업 기준. 단위: %" columns={["개업 후 연수", dong, "제주 전체"]} rows={curve.map((c) => [`${c.year}년`, c.pct, jeju.get(c.year) ?? null])}>
              <SurvivalChart dong={dong} rows={curve.map((c) => ({ year: c.year, dong: c.pct, jeju: jeju.get(c.year) ?? null }))} />
            </ChartFrame>
          )}
          {busTrend ? (
            <ChartFrame testId="chart-bus" title="월별 버스 일평균 이용" description="단위: 명" columns={["월", "일평균(명)"]} rows={busTrend.map((r) => [r.ym, r.daily])}>
              <TrendChart rows={busTrend.map((r) => ({ ym: r.ym, value: r.daily }))} unit="명" seriesName="일평균 이용" />
            </ChartFrame>
          ) : (
            <EmptyState title="버스 자료가 없습니다">이 동네에 연결된 정류소 이용 기록이 없습니다.</EmptyState>
          )}
          {visit && visit.length > 0 ? (
            <ChartFrame testId="chart-visit" title="월별 방문/거주 지수" description="28일 이상 수집한 달만 그립니다. 손님 수가 아닙니다." columns={["월", dong, "제주 전체"]} rows={visit.map((r) => [r.ym, r.visit_index, meta.data?.jeju_visit[r.ym] ?? null])}>
              <TrendChart reference rows={visit.map((r) => ({ ym: r.ym, value: r.visit_index, reference: meta.data?.jeju_visit[r.ym] ?? null }))} unit="" seriesName={dong} />
            </ChartFrame>
          ) : (
            <EmptyState title="유동인구 추이를 그릴 자료가 부족합니다">28일 이상 수집한 달이 없습니다.</EmptyState>
          )}
        </div>
      )}

      {d && <Evidence sources={d.profile.sources ?? []} periods={d.profile.period} limits={[...new Set([...(d.profile.limits ?? []), ...(d.biz.limits ?? []), ...(d.population.limits ?? [])])]} />}
    </div>
  );
}
