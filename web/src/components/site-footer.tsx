"use client";

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { queries } from "@/lib/queries";

export function SiteFooter() {
  const { data } = useQuery(queries.meta());
  // 출력일은 정적 빌드 시점이 아니라 화면을 연 날짜여야 하므로 브라우저에서 정한다.
  const [today, setToday] = useState("");
  useEffect(() => {
    const d = new Date();
    setToday(`${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`);
  }, []);
  return (
    <footer className="border-t border-(--krds-border-gray-light) bg-muted text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle) print:break-inside-avoid print:bg-transparent print:text-black">
      <div className="mx-auto flex w-full max-w-[75rem] flex-col gap-1 px-4 py-6 md:px-6 print:px-0 print:py-3">
        {/* 인쇄물을 받은 사람이 언제, 무엇으로 만든 종이인지 알 수 있게 한다. */}
        <p className="hidden font-semibold print:block" data-testid="print-stamp">
          동네 생활 진단{today && ` · 출력일 ${today}`}
        </p>
        <p>자료 출처: 제주데이터허브 상가, 음식점, 유동인구, 버스, 기상. 과거 기록을 설명하며 미래 예측은 하지 않습니다.</p>
        {data && <p data-testid="llm-path" className="print:hidden">현재 LLM 경로: {data.backend_label}. 수치 문장은 LLM이 아니라 코드가 씁니다.</p>}
      </div>
    </footer>
  );
}
