"use client";

import { useQuery } from "@tanstack/react-query";
import { parseAsArrayOf, parseAsString, useQueryState } from "nuqs";
import { Button } from "@/components/ui/button";
import { PrinterIcon, XIcon } from "@/components/icons";
import { CompareTable } from "@/components/compare-table";
import { Evidence } from "@/components/evidence";
import { Panel } from "@/components/section";
import { BlockSkeleton, EmptyState, ErrorState } from "@/components/states";
import { printPage } from "@/lib/print";
import { queries } from "@/lib/queries";

const MAX = 4;

export function CompareView() {
  const [dongs, setDongs] = useQueryState("dongs", parseAsArrayOf(parseAsString).withDefault(["아라동", "이도2동"]));
  const meta = useQuery(queries.meta());
  const query = useQuery(queries.compare(dongs));
  const left = meta.data?.dongs.filter((d) => !dongs.includes(d)) ?? [];

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1>동네 비교</h1>
          <p className="mt-1 text-(--krds-text-subtle) print:hidden">동네를 2곳에서 {MAX}곳까지 골라 지표를 나란히 봅니다.</p>
        </div>
        <Button variant="outline" onClick={printPage} className="print:hidden" disabled={!query.data} data-testid="print">
          <PrinterIcon size={18} aria-hidden />
          A4 인쇄
        </Button>
      </header>

      <div className="flex flex-col gap-3 print:hidden">
        <ul className="flex flex-wrap gap-2" aria-label="고른 동네">
          {dongs.map((d) => (
            <li key={d}>
              <Button variant="secondary" size="sm" aria-label={`${d} 빼기`} onClick={() => setDongs(dongs.filter((x) => x !== d))}>
                {d}
                <XIcon size={16} aria-hidden />
              </Button>
            </li>
          ))}
        </ul>
        <div className="sm:max-w-xs">
          <label htmlFor="add-dong" className="mb-1.5 block font-semibold">동네 추가</label>
          <select
            id="add-dong"
            className="field"
            value=""
            disabled={dongs.length >= MAX || !meta.data}
            onChange={(e) => e.target.value && setDongs([...dongs, e.target.value])}
          >
            <option value="">{dongs.length >= MAX ? `최대 ${MAX}곳까지 고를 수 있습니다` : "동네를 고르세요"}</option>
            {left.map((d) => <option key={d} value={d}>{d}</option>)}
          </select>
        </div>
      </div>

      {dongs.length < 2 && <EmptyState title="동네를 2곳 이상 고르세요">비교표는 2곳부터 만들 수 있습니다.</EmptyState>}
      {dongs.length >= 2 && query.isPending && <BlockSkeleton className="h-96 w-full" />}
      {dongs.length >= 2 && query.isError && <ErrorState error={query.error} onRetry={() => query.refetch()} />}
      {dongs.length >= 2 && query.data && (
        <>
          <Panel title={`${query.data.dongs.join(" · ")} 비교표`} description="폐업률·생존율은 표본 오차가 커서 순위를 내지 않습니다. 판정은 제주 평균과의 차이를 다중 비교 보정 뒤에 확인한 결과입니다.">
            <CompareTable dongs={query.data.dongs} rows={query.data.rows} />
          </Panel>
          <Evidence sources={query.data.profiles[0].sources ?? []} periods={query.data.profiles[0].period} limits={query.data.limits} />
        </>
      )}
    </div>
  );
}
