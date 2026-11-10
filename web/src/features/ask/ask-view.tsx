"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { parseAsArrayOf, parseAsString, useQueryStates } from "nuqs";
import { useIconHover } from "@animateicons/react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { HistoryIcon, SendIcon } from "@/components/icons";
import { ErrorState } from "@/components/states";
import { CASES, type DemoCase } from "@/lib/content";
import { queries } from "@/lib/queries";
import { AnswerView } from "./answer";
import { ProcessPending } from "./process-steps";
import { askedDongs } from "./trace";

const params = {
  q: parseAsString.withDefault("").withOptions({ history: "push" }),
  ctx: parseAsArrayOf(parseAsString).withDefault([]).withOptions({ history: "push" }),
};
const MAX_LENGTH = 200;

const MOBILE_CASES = 4; // 휴대폰에서는 먼저 4개만 보여 스크롤을 줄인다

function CaseCard({ c, onAsk, active, hiddenOnMobile }: { c: DemoCase; onAsk: (q: string) => void; active: boolean; hiddenOnMobile: boolean }) {
  const { ref, triggerProps } = useIconHover();
  return (
    <li className={hiddenOnMobile ? "hidden sm:block" : undefined}>
      <button
        type="button"
        {...triggerProps}
        aria-pressed={active}
        onClick={() => onAsk(c.question)}
        data-testid={`case-${c.testCase}`}
        data-use-case={c.useCase}
        className="flex h-full w-full cursor-pointer flex-col gap-2 rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) bg-card p-4 text-left transition-colors hover:border-(--krds-border-primary) hover:bg-(--krds-surface-primary-subtler) aria-pressed:border-2 aria-pressed:border-(--krds-border-primary) aria-pressed:bg-(--krds-surface-primary-subtler)"
      >
        <Badge variant="secondary" className="h-6 border-transparent text-[length:var(--krds-fs-label-xsmall)]">{c.persona}</Badge>
        <span className="flex-1 font-semibold text-(--krds-text-bolder)">{c.question}</span>
        <span className="flex items-center justify-between gap-2 text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)">
          {c.shows}
          <SendIcon ref={ref} size={18} className="shrink-0 text-(--krds-text-primary)" aria-hidden />
        </span>
      </button>
    </li>
  );
}

export function AskView() {
  const [{ q, ctx }, setParams] = useQueryStates(params);
  const [draft, setDraft] = useState("");
  const [formError, setFormError] = useState("");
  const [history, setHistory] = useState<string[]>([]);
  const [showAllCases, setShowAllCases] = useState(false);
  const resultRef = useRef<HTMLHeadingElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const send = useIconHover();
  const context = useMemo(() => ctx, [ctx]);
  const query = useQuery({ ...queries.ask(q, context), enabled: q.length > 0 });
  const lastDongs = query.data ? askedDongs(query.data) : [];

  const ask = (question: string, carry: string[] = []) => {
    const text = question.trim();
    setFormError("");
    setDraft("");
    setHistory((h) => [text, ...h.filter((x) => x !== text)].slice(0, 6));
    setParams({ q: text, ctx: carry.length ? carry : null });
  };

  useEffect(() => {
    if (q && resultRef.current) {
      resultRef.current.focus({ preventScroll: true });
      const smooth = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      resultRef.current.scrollIntoView({ behavior: smooth ? "smooth" : "auto", block: "start" });
    }
  }, [q]);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = draft.trim();
    if (!text) {
      setFormError("질문을 입력해 주세요. 예: 노형동에 카페가 많은 편이야?");
      inputRef.current?.focus();
      return;
    }
    ask(text, lastDongs);
  };

  return (
    <div className="flex flex-col gap-8">
      <header className="flex flex-col gap-2 print:hidden">
        <h1>우리 동네를 자료로 확인합니다</h1>
        <p className="max-w-[46rem] text-(--krds-text-subtle)">
          제주 43개 읍면동의 상가, 음식점, 유동인구, 버스, 기상 자료를 묶어 과거 기록으로 동네를 설명합니다. 미래 예측은 하지 않습니다.
        </p>
      </header>

      <form onSubmit={submit} noValidate className="print:hidden" aria-label="질문 입력">
        <label htmlFor="question" className="mb-1.5 block font-semibold">무엇이 궁금한가요?</label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            id="question"
            ref={inputRef}
            name="question"
            className="field"
            maxLength={MAX_LENGTH}
            autoComplete="off"
            enterKeyHint="send"
            placeholder="예: 노형동에 카페가 많은 편이야?"
            value={draft}
            aria-invalid={formError ? true : undefined}
            aria-describedby={formError ? "question-error" : undefined}
            onChange={(e) => {
              setDraft(e.target.value);
              if (formError) setFormError("");
            }}
          />
          <Button type="submit" size="lg" className="sm:w-auto" {...send.triggerProps} disabled={query.isFetching}>
            <SendIcon ref={send.ref} size={20} aria-hidden />
            질문하기
          </Button>
        </div>
        {formError && <p id="question-error" role="alert" className="mt-1.5 text-[length:var(--krds-fs-body-small)] text-(--krds-text-danger)">{formError}</p>}
        {lastDongs.length > 0 && !formError && (
          <p className="mt-1.5 text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)">
            동네를 말하지 않으면 앞 질문의 {lastDongs.join(", ")} 기준으로 답합니다. 예: 버스는 어때?
          </p>
        )}
      </form>

      {q && (
        <section aria-labelledby="result-title" className="flex flex-col gap-4">
          <h2 id="result-title" ref={resultRef} tabIndex={-1} className="scroll-mt-24 outline-none">{q}</h2>
          {query.isPending || (query.isFetching && !query.data) ? (
            <ProcessPending question={q} />
          ) : query.isError ? (
            <ErrorState error={query.error} onRetry={() => query.refetch()} />
          ) : query.data ? (
            <AnswerView result={query.data} onAsk={(x) => ask(x)} />
          ) : null}
        </section>
      )}

      {history.length > 1 && (
        <section aria-label="이번에 한 질문" className="flex flex-col gap-2 print:hidden" data-testid="history">
          <p className="flex items-center gap-1.5 font-semibold">
            <HistoryIcon size={20} aria-hidden />
            이번에 한 질문
          </p>
          <div className="flex flex-wrap gap-2">
            {history.filter((h) => h !== q).map((h) => (
              <Button key={h} variant="ghost" size="sm" className="h-auto min-h-10 whitespace-normal border-(--krds-border-gray-light) py-2 text-left" onClick={() => ask(h)}>{h}</Button>
            ))}
          </div>
        </section>
      )}

      <section aria-labelledby="cases-title" className="print:hidden">
        <h2 id="cases-title" className="mb-1">사용자별 대표 질문</h2>
        <p className="mb-4 text-(--krds-text-subtle)">누르면 바로 답을 찾아 보여 줍니다.</p>
        <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" data-testid="cases">
          {CASES.map((c, i) => (
            <CaseCard key={c.testCase} c={c} onAsk={(x) => ask(x)} active={q === c.question} hiddenOnMobile={!showAllCases && i >= MOBILE_CASES && q !== c.question} />
          ))}
        </ul>
        {!showAllCases && (
          <Button variant="outline" className="mt-3 w-full sm:hidden" onClick={() => setShowAllCases(true)}>
            대표 질문 {CASES.length - MOBILE_CASES}개 더 보기
          </Button>
        )}
      </section>
    </div>
  );
}
