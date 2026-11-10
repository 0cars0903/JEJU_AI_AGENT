"use client";

import { useEffect, useRef, useState } from "react";
import type { IconHandle } from "@animateicons/react";
import { useIconHover } from "@animateicons/react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { CircleCheckIcon, CircleXIcon, ListChecksIcon, LoaderCircleIcon } from "@/components/icons";
import type { AskResult } from "@/lib/api";
import { processSteps, traceLines, type StepView } from "./trace";

function StepIcon({ state }: { state: StepView["state"] }) {
  const ref = useRef<IconHandle>(null);
  useEffect(() => {
    ref.current?.startAnimation();
  }, []);
  if (state === "failed") return <CircleXIcon ref={ref} size={22} className="shrink-0 text-(--krds-text-danger)" aria-hidden />;
  if (state === "skipped") return <span aria-hidden className="mt-0.5 size-[22px] shrink-0 rounded-full border-2 border-dashed border-(--krds-border-gray)" />;
  return <CircleCheckIcon ref={ref} size={22} className="shrink-0 text-(--krds-text-success)" aria-hidden />;
}

const STATE_LABEL = { done: "완료", skipped: "건너뜀", failed: "실패" };

export function ProcessSteps({ result }: { result: AskResult }) {
  const steps = processSteps(result);
  const { ref, triggerProps } = useIconHover();
  return (
    <section aria-labelledby="process-title" className="print-avoid rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) bg-muted p-4 md:p-5" data-testid="process">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <h3 id="process-title">Agent 작업 과정</h3>
        <Dialog>
          <DialogTrigger render={<Button variant="outline" size="sm" {...triggerProps} className="print:hidden" />}>
            <ListChecksIcon ref={ref} size={18} aria-hidden />
            자세히 보기
          </DialogTrigger>
          <DialogContent className="sm:max-w-[47.5rem]">
            <DialogHeader>
              <DialogTitle className="text-[length:var(--krds-fs-heading-medium)] font-bold">작업 기록</DialogTitle>
              <DialogDescription className="text-(--krds-text-subtle)">실제로 일어난 일만 순서대로 적었습니다.</DialogDescription>
            </DialogHeader>
            <ol className="flex flex-col gap-3" data-testid="trace">
              {result.trace.map((t, i) => (
                <li key={i} className="border-l-2 border-(--krds-border-gray-light) pl-3">
                  <p className="font-semibold">{t.stage}</p>
                  {traceLines(t).map((l, j) => (
                    <p key={j} className="text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)">{l}</p>
                  ))}
                </li>
              ))}
            </ol>
          </DialogContent>
        </Dialog>
      </div>
      <ol className="grid gap-3 md:grid-cols-5">
        {steps.map((s) => (
          <li key={s.name} className="flex items-start gap-2 md:flex-col md:gap-1.5" data-state={s.state}>
            <StepIcon state={s.state} />
            <div className="min-w-0">
              <p className="font-semibold">
                {s.name}
                <span className="sr-only"> {STATE_LABEL[s.state]}</span>
              </p>
              <p className={cn("text-[length:var(--krds-fs-body-small)]", s.state === "skipped" ? "text-(--krds-text-subtle)" : "text-(--krds-text-basic)")}>{s.text}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** 처리 중 화면. 응답 전에는 단계별 진행을 알 수 없으므로 어느 단계인지 꾸며 내지 않고 경과 시간만 보여 준다. */
export function ProcessPending({ question }: { question: string }) {
  const [seconds, setSeconds] = useState(0);
  const ref = useRef<IconHandle>(null);
  useEffect(() => {
    ref.current?.startAnimation();
    const timer = setInterval(() => {
      setSeconds((s) => s + 1);
      ref.current?.startAnimation();
    }, 1000);
    return () => clearInterval(timer);
  }, []);
  return (
    <section role="status" aria-live="polite" className="rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) bg-muted p-4 md:p-5" data-testid="pending">
      <p className="flex items-center gap-2 font-semibold">
        <LoaderCircleIcon ref={ref} size={22} className="shrink-0 text-(--krds-text-primary)" aria-hidden />
        Agent가 답을 준비하고 있습니다…
      </p>
      <p className="mt-1 text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)">
        질문 해석, 계획, 실행, 검증, 설명 순서로 처리합니다. 끝나면 단계별 기록을 보여 드립니다. 컴퓨터 성능에 따라 시간이 더 걸릴 수 있습니다.
      </p>
      <p className="mt-1 text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)" aria-hidden>
        “{question}” · {seconds}초 경과
      </p>
    </section>
  );
}
