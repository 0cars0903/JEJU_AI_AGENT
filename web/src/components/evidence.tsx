"use client";

import { Panel } from "@/components/section";
import { GlossaryButton } from "@/components/glossary";
import { SOURCE_NAMES } from "@/lib/content";

/** 근거(자료·기준 시점)와 한계를 답변과 떼어 항상 보여 준다. */
export function Evidence({ sources, periods: rawPeriods, limits }: { sources: string[]; periods?: Record<string, string> | string; limits: string[] }) {
  const periods = typeof rawPeriods === "string" ? { 기간: rawPeriods } : rawPeriods;
  return (
    <div className="grid gap-4 md:grid-cols-2" data-testid="evidence">
      <Panel title="근거" action={<GlossaryButton />}>
        <p className="font-semibold">사용한 자료(제주데이터허브)</p>
        <ul className="mt-1 list-disc pl-5 text-[length:var(--krds-fs-body-small)]">
          {sources.map((s) => (
            <li key={s}>
              {SOURCE_NAMES[s] ?? "자료"} ({s})
            </li>
          ))}
        </ul>
        {periods && Object.keys(periods).length > 0 && (
          <>
            <p className="mt-3 font-semibold">기준 시점</p>
            <ul className="mt-1 list-disc pl-5 text-[length:var(--krds-fs-body-small)]">
              {Object.entries(periods).map(([k, v]) => (
                <li key={k}>
                  {k}: {v}
                </li>
              ))}
            </ul>
          </>
        )}
      </Panel>
      <Panel title="한계">
        <ul className="list-disc pl-5 text-[length:var(--krds-fs-body-small)]" data-testid="limits">
          {limits.map((l) => (
            <li key={l} className="mb-1">
              {l}
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}
