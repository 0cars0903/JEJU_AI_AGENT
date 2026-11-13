"use client";

import { useEffect, useState } from "react";
import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { type Slots, getSummary } from "@/lib/api";
import { JejuMap } from "./jeju-map";
import { shortNum } from "./views";

const HINT = (picked: boolean) => (picked ? "지도에서 눌러도 바뀌어요." : "지도에서 눌러서 골라도 돼요.");
const MAP_BASE = "노형동"; // 지도 색(43곳 값)을 받는 데만 쓴다. 43곳 값은 어느 동네로 물어도 같다.
const fmt = (v: number, unit: string) => (unit === "원" ? `${shortNum(v)} 원` : unit === "지수" ? shortNum(v) : `${Math.round(v).toLocaleString("ko-KR")} ${unit}`);

/** Notion '텍스트 등장' 카운트 업: 0 → 값으로 0.6초. 운영체제의 '움직임 줄이기'면 바로 값을 보여 준다. */
function useCountUp(target: number, ms = 600) {
  const [v, setV] = useState(target);
  useEffect(() => {
    if (!Number.isFinite(target)) return setV(target);
    const reduce = typeof window !== "undefined" && window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;
    if (reduce) return setV(target);
    let raf = 0;
    const t0 = performance.now();
    const tick = (t: number) => {
      const k = Math.min(1, (t - t0) / ms);
      setV(target * (1 - Math.pow(1 - k, 3)));
      if (k < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [target, ms]);
  return v;
}

function CountValue({ value, unit }: { value: number; unit: string }) {
  const v = useCountUp(value);
  return (
    <span data-testid="count-value" data-final={value} aria-label={fmt(value, unit)}>
      <span aria-hidden>{fmt(v, unit)}</span>
    </span>
  );
}

/** 패턴 A(소상공인365 '한 눈에 보는 상권정보' 참고): 동네를 고르면 질문형 카드 3장 + 같은 값으로 칠한 지도. 카드를 누르면 그 주제로 답한다. 첫 방문에는 카드 대신 동네 고르기 안내와 지도만 보인다. */
export function DongHome({ dongs, onAsk }: { dongs: string[]; onAsk: (slots: Slots, text: string) => void }) {
  const [dong, setDongState] = useState("");
  // B6: 사용자가 고른 동네는 기억해 다음에도 그 동네부터 보여 준다. 고르기 전(첫 방문)에는 숫자 카드 대신 동네를 먼저 고르게 한다(문서 20 7.5절 7번).
  useEffect(() => {
    try {
      const d = localStorage.getItem("jeju.dong");
      if (d && dongs.includes(d)) setDongState(d);
    } catch {
      /* 저장이 막혀도 동작은 그대로 */
    }
  }, [dongs]);
  const setDong = (d: string) => {
    setDongState(d);
    try {
      localStorage.setItem("jeju.dong", d);
    } catch {
      /* 저장이 막혀도 동작은 그대로 */
    }
  };
  const [kind, setKind] = useState("visit");
  // 동네를 바꿔 새 값을 받는 동안에도 앞의 값을 들고 있어 지도를 그대로 둔다(지도의 43곳 값은 동네와 무관하다. 지도가 다시 만들어지면 확대한 자리가 풀린다).
  const q = useQuery({ queryKey: ["summary", dong || MAP_BASE], queryFn: () => getSummary(dong || MAP_BASE), placeholderData: keepPreviousData });
  const loading = q.isPending || q.isPlaceholderData; // 숫자 카드는 그 동네 값이 왔을 때만 보인다
  const cur = q.data?.cards.find((c) => c.kind === kind) ?? q.data?.cards[0];
  return (
    <section data-testid="dong-home" aria-label="동네 한눈에" className="flex flex-col gap-2 rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) p-3">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="text-[length:var(--krds-fs-heading-small)]">동네 한눈에</h2>
        <label className="flex items-center gap-2">
          <span className="sr-only">동네 고르기</span>
          <select
            data-testid="home-dong"
            value={dong}
            onChange={(e) => e.target.value && setDong(e.target.value)}
            // 첫 방문(B6): 좁은 화면에서는 "먼저 골라 주세요" 상자가 지도 아래에 있으므로, 첫 화면에 보이는 이 상자를 굵은 테두리로 강조한다
            className={(dong ? "border border-(--krds-border-gray)" : "border-2 border-(--krds-border-primary)") + " h-11 rounded-(--radius) bg-background px-3 text-[length:var(--krds-fs-body-large)] font-semibold"}
          >
            {!dong && <option value="">내 동네 고르기</option>}
            {dongs.map((d) => (
              <option key={d} value={d}>
                {d}
              </option>
            ))}
          </select>
        </label>
        {/* 이중 검토 034·035: 동네를 고르면 한 번 더 눌러 종합 진단(조건 패널 7번 → 2번) */}
        {dong && (
          <button
            type="button"
            data-testid="home-diagnose"
            onClick={() => onAsk({ topic: "diagnose", space: [dong] }, `${dong} 상권 종합 진단해줘`)}
            className="hidden min-h-11 rounded-(--radius) bg-(--krds-text-primary) px-4 font-semibold text-white hover:opacity-90 lg:block"
          >
            {dong} 종합 진단 보기
          </button>
        )}
        <span className="hidden text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder) md:inline">{HINT(!!dong)}</span>
      </div>
      {/* 스플릿 배치(Notion '화면 배치'): 데스크톱은 카드 3장 세로 | 지도, 한 화면에 들어오게 */}
      <div className="grid gap-4 lg:grid-cols-[minmax(240px,300px)_1fr] lg:items-start">
      {/* B1: 카드는 세 줄로 줄여 1366×768에서도 세 장이 다 보이게 한다. 작은 화면에서는 지도를 카드 위에 둬, 지도에서 고른 동네의 값이 바로 아래에 보인다(B4). */}
      <div className="order-2 grid gap-2 md:grid-cols-3 lg:order-none lg:grid-cols-1">
        {!dong && (
          <div data-testid="home-first" className="flex flex-col gap-1 rounded-(--radius) border-2 border-(--krds-border-primary) bg-(--krds-surface-primary-subtler) px-3 py-3 md:col-span-3 lg:col-span-1">
            <p className="text-[length:var(--krds-fs-heading-small)] font-bold">내 동네를 먼저 골라 주세요</p>
            <p className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">위 상자에서 고르거나 지도에서 동네를 누르면 그 동네의 값이 나와요.</p>
            <ul className="list-disc pl-5 text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">
              {(q.data?.cards ?? []).map((c) => (
                <li key={c.kind}>{c.question}</li>
              ))}
            </ul>
          </div>
        )}
        {dong && (
          // 좁은 화면: 지도 아래 카드 자리 맨 앞(머리 줄에 두면 지도가 화면 밖으로 밀린다, 사용성 점검 B1)
          <button
            type="button"
            data-testid="home-diagnose"
            onClick={() => onAsk({ topic: "diagnose", space: [dong] }, `${dong} 상권 종합 진단해줘`)}
            className="min-h-11 rounded-(--radius) bg-(--krds-text-primary) px-4 font-semibold text-white hover:opacity-90 md:col-span-3 lg:hidden"
          >
            {dong} 종합 진단 보기
          </button>
        )}
        {(dong && !loading ? (q.data?.cards ?? []) : []).map((c) => (
          <button
            key={c.kind}
            type="button"
            data-testid={`home-card-${c.kind}`}
            aria-pressed={c.kind === (cur?.kind ?? "")}
            onMouseEnter={() => setKind(c.kind)}
            onFocus={() => setKind(c.kind)}
            onClick={() => onAsk(c.slots, `${dong} ${c.question}`)}
            className={
              c.kind === cur?.kind
                ? "flex flex-col items-start gap-0 rounded-(--radius) border-2 border-(--krds-border-primary) bg-(--krds-surface-primary-subtler) px-3 py-1 text-left"
                : "flex flex-col items-start gap-0 rounded-(--radius) border border-(--krds-border-gray) px-3 py-1 text-left hover:bg-muted"
            }
          >
            <span className="font-bold">{c.question}</span>
            <span className="flex w-full flex-wrap items-baseline justify-between gap-x-2">
              <span className="text-[length:max(1.75rem,var(--krds-fs-heading-medium))] font-bold leading-tight">
                <CountValue value={c.value} unit={c.unit} />
              </span>
              <span className="font-semibold text-(--krds-text-primary)">자세히 보기 →</span>
            </span>
            <span className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">
              기준 {c.as_of} · 제주 {c.of}곳 중 {c.rank}위{c.unit === "지수" ? " · 사람 수 아님" : ""}
            </span>
            {/* 화면 높이가 충분할 때만 한 줄 더 보여 준다(B1: 낮은 화면에서도 카드 세 장이 다 보이게) */}
            <span className="hidden text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder) [@media(min-height:860px)]:inline">중간값 {fmt(c.median, c.unit)}</span>
          </button>
        ))}
        {dong && loading && [0, 1, 2].map((i) => <div key={i} className="h-24 rounded-(--radius) bg-muted" aria-hidden />)}
      </div>
      {/* 지도 경계는 동네 값을 기다리지 않고 바로 그린다. 값이 오면 색을 칠한다. 예전에는 값 요청이 늦거나 실패하면 지도 자리가 통째로 비었다(운영 '처음 화면' 지도 없음, 2026-11-13) */}
      {(
        <div className="order-1 lg:order-none lg:max-w-[calc((100dvh-32rem)*1.5)]">
        {q.isError && !q.data && (
          <p data-testid="home-map-error" role="alert" className="mb-2 flex flex-wrap items-center gap-2 text-[length:var(--krds-fs-body-medium)]">
            지도 값을 불러오지 못했어요.
            <button type="button" onClick={() => q.refetch()} className="min-h-11 rounded-(--radius) border border-(--krds-border-gray) px-3 hover:bg-muted">
              다시 시도
            </button>
          </p>
        )}
        {/* 문서 21 6.2절: 조건 패널이 본문을 밀지 않아 지도 칸이 넓어졌다. 지도 높이가 첫 화면을 넘지 않게 폭을 화면 높이에 맞춘다(B1) */}
        <JejuMap
          values={cur?.values}
          unit={cur?.unit}
          selected={dong ? [dong] : []}
          onPick={setDong}
          label={`제주 43개 동네 ${cur ? cur.question.replace("?", "") : "행정동"} 지도. 동네를 누르면 그 동네${dong ? "로 바뀝니다" : "를 고릅니다"}.`}
          testId="home-map"
        />
        {/* B1: 좁은 화면에서는 안내 글을 지도 아래로 내려, 지도가 첫 화면 안에 다 들어오게 한다 */}
        <p data-testid="home-hint-narrow" className="mt-2 text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder) md:hidden">
          {HINT(!!dong)}
        </p>
        </div>
      )}
      </div>
    </section>
  );
}
