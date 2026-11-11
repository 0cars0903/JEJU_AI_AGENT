"use client";

import { useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { LoaderCircleIcon } from "@/components/icons";
import type { AskResult, Slots, Suggestion } from "@/lib/api";

/** "이렇게 이해했어요": 해석한 칸과 주석을 보여 주고 [맞아요] [조건 바꾸기]. 답은 이미 이 내용으로 계산한 것이라 결론보다 약하게 둔다(B2). [조건 바꾸기]는 단계별 선택을 연다. */
/** sample: 로딩 뼈대용 예시 답(보이지 않음). 시험 표시(data-testid)를 붙이지 않는다. */
export function Understood({ r, onChange, sample }: { r: AskResult; onChange: (s: Slots) => void; sample?: boolean }) {
  const [ok, setOk] = useState(false);
  const doneRef = useRef<HTMLParagraphElement>(null);
  useEffect(() => {
    if (ok) doneRef.current?.focus({ preventScroll: true });
  }, [ok]);
  if (!r.understood) return null;
  const u = r.understood;
  const strong = u.assumed && !ok;
  const notes = (u.notes ?? []).filter(Boolean);
  return (
    <div
      data-testid={sample ? undefined : "understood"}
      className={
        strong
          ? "flex flex-col gap-2 rounded-(--radius) border-2 border-(--krds-border-primary) bg-(--krds-surface-primary-subtler) p-3"
          : "flex flex-col gap-2 rounded-(--radius) border border-(--krds-border-gray) p-3"
      }
    >
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[length:var(--krds-fs-body-medium)] font-semibold">{u.text}</p>
        {strong && <Badge variant="outline" className="h-auto py-1 text-[length:var(--krds-fs-label-medium)]">질문을 읽고 추정했어요</Badge>}
      </div>
      {notes.length > 0 && (
        <ul data-testid="understood-notes" className="flex list-disc flex-col gap-1 pl-5 text-[length:var(--krds-fs-body-medium)]">
          {notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      {ok && (
        <p ref={doneRef} tabIndex={-1} role="status" data-testid="understood-done" className="flex items-center gap-1 font-semibold text-(--krds-text-primary) outline-none">
          <Check size={18} aria-hidden /> 확인했어요. 아래 답은 이 내용으로 계산했어요.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        {!ok && (
          <>
            <span className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">아래 답은 이 내용으로 계산했어요. 다르면 고쳐 주세요.</span>
            <Button variant="outline" size="sm" onClick={() => setOk(true)} data-testid="understood-ok">
              맞아요
            </Button>
          </>
        )}
        <Button variant="outline" size="sm" onClick={() => onChange(u.slots)} data-testid="understood-change">
          조건 바꾸기
        </Button>
      </div>
    </div>
  );
}

function Tag({ text, layer }: { text: string; layer: string | null }) {
  // 판단 층(L3·L4)은 강조색 윤곽, 사실(L1·L2)·판단 재료(L5)는 회색
  const strong = layer === "L3" || layer === "L4";
  return (
    <span
      className={
        strong
          ? "inline-block w-fit rounded-(--radius) border border-(--krds-border-primary) px-2 py-0.5 text-[length:var(--krds-fs-label-medium)] font-semibold text-(--krds-text-primary)"
          : "inline-block w-fit rounded-(--radius) bg-muted px-2 py-0.5 text-[length:var(--krds-fs-label-medium)] text-(--krds-text-bolder)"
      }
    >
      {text}
    </span>
  );
}

/** v3 답 카드: 결론 한 줄(층 꼬리표) → 3블록(① 사실·비교 ② Agent 분석·예상 ③ 판단 재료) → 한계. answer가 없으면 card를 그대로 보여 준다. */
export function AnswerCard({ r, sample }: { r: AskResult; sample?: boolean }) {
  const c = r.card;
  const a = r.answer;
  if (!c && !a) return null;
  const t = (id: string) => (sample ? undefined : id);
  return (
    <article data-testid={t("answer-card")} className="flex flex-col gap-5 rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) bg-card p-4 md:p-6">
      <div className="flex flex-col gap-2">
        {a?.conclusion.tag && <Tag text={a.conclusion.tag} layer={a.conclusion.layer} />}
        {/* Stageshow 지적 4: 결론은 28px 이상으로 다른 글보다 확실히 크게 */}
        <p data-testid={t("conclusion")} className="text-[length:max(1.75rem,var(--krds-fs-heading-medium))] leading-snug font-bold">
          {a?.conclusion.text ?? c?.conclusion}
        </p>
        {/* B2·B7: 답이 길어도 결론 가까이에서 출처·내려받기·센터 자료 칸으로 바로 간다(순서는 그대로) */}
        {a && !sample && (
          <nav aria-label="이 답의 아래쪽 바로 가기" data-testid="answer-shortcuts" className="flex flex-wrap items-center gap-x-1 gap-y-0 text-[length:var(--krds-fs-body-medium)]">
            <span className="text-(--krds-text-bolder)">바로 가기:</span>
            {(a.footer?.length ?? 0) > 0 && (
              <a href="#answer-source" className="inline-flex min-h-11 items-center px-2 underline">
                출처 보기
              </a>
            )}
            {(r.downloads?.length ?? 0) > 0 && (
              <a href="#answer-downloads" className="inline-flex min-h-11 items-center px-2 underline">
                내려받기
              </a>
            )}
            <button type="button" data-testid="shortcut-print" onClick={() => window.print()} className="inline-flex min-h-11 items-center px-2 underline">
              인쇄(PDF 저장)
            </button>
            {a.requests?.some((q) => q.kind === "center") && (
              <a href="#request-center" className="inline-flex min-h-11 items-center px-2 underline">
                센터 자료 넣기
              </a>
            )}
          </nav>
        )}
      </div>
      {a ? (
        <div data-testid={t("evidence")} className="flex flex-col gap-5">
          {a.blocks.map((b) => (
            <section key={b.id} data-testid={t(`block-${b.id}`)} className="flex flex-col gap-2">
              <h3 className="border-b border-(--krds-border-gray-light) pb-1">{b.title}</h3>
              <ul className="flex flex-col gap-3">
                {b.lines.map((l, i) => (
                  <li key={i} className="flex flex-col gap-1">
                    <Tag text={l.tag} layer={l.layer} />
                    <span className="text-[length:var(--krds-fs-body-large)]">{l.text}</span>
                    {l.source && <span className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">출처: {l.source}</span>}
                  </li>
                ))}
              </ul>
              {b.closing && <p className="rounded-(--radius) bg-(--krds-surface-gray-subtler) p-3 font-semibold">{b.closing}</p>}
            </section>
          ))}
        </div>
      ) : (
        c!.evidence.length > 0 && (
          <ul className="flex flex-col gap-1" data-testid={t("evidence")}>
            {c!.evidence.map((e, i) => (
              <li key={i}>
                {e.text}
                {e.dataset && <span className="ml-2 text-(--krds-text-bolder)">[{e.dataset}{e.as_of ? `, ${e.as_of}` : ""}]</span>}
              </li>
            ))}
          </ul>
        )
      )}
      {c && c.intervals.length > 0 && (
        <div>
          <h3 className="mb-1">값이 달라질 수 있는 폭</h3>
          <ul>{c.intervals.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </div>
      )}
      {/* 패턴 G: 바닥 줄 — 자료·기준 시점·다음 갱신(OWID 방식) */}
      {a?.footer && a.footer.length > 0 && (
        <div id={sample ? undefined : "answer-source"} data-testid={t("answer-footer")} className="scroll-mt-24 order-last flex flex-col gap-1 border-t border-(--krds-border-gray-light) pt-3 text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">
          {a.footer.map((f) => (
            <p key={f.source}>
              자료: {f.source} · 기준 {f.as_of} · 다음 갱신: {f.next}
            </p>
          ))}
        </div>
      )}
      {c && c.limits.length > 0 && (
        <div data-testid={t("limits")}>
          <h3 className="mb-1">한계</h3>
          <ul className="flex list-disc flex-col gap-1 pl-5 text-(--krds-text-bolder)">{c.limits.map((x, i) => <li key={i}>{x}</li>)}</ul>
        </div>
      )}
    </article>
  );
}

export function Process({ r }: { r: AskResult }) {
  const p = r.process;
  if (!p) return null;
  return (
    <details data-testid="process" className="rounded-(--radius) border border-(--krds-border-gray-light) px-3 py-1">
      <summary className="flex min-h-11 cursor-pointer items-center font-semibold">판단 과정 보기</summary>
      <div className="mt-3 flex flex-col gap-2">
        {p.explain?.text && <p>{p.explain.text}</p>}
        <ol className="flex flex-wrap gap-2">
          {p.steps.map((s) => (
            <li key={s.id} className="rounded-(--radius) bg-muted px-2 py-1 text-[length:var(--krds-fs-body-small)]">
              {s.name} · {s.status}
            </li>
          ))}
        </ol>
        {Object.keys(p.data ?? {}).length > 0 && (
          <p className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">
            자료 기준: {Object.entries(p.data).map(([k, v]) => `${k} ${v}`).join(" · ")}
          </p>
        )}
        {p.unused.length > 0 && <p className="text-[length:var(--krds-fs-body-small)]">쓰지 못한 것: {p.unused.join(" / ")}</p>}
        {(r.answer?.freshness?.length ?? 0) > 0 && (
          <div data-testid="freshness">
            <p className="font-semibold">자료 기준 시점</p>
            <ul className="list-disc pl-5">
              {r.answer!.freshness.map((f) => (
                <li key={f.source}>
                  {f.source}: {f.as_of} ({f.months_old}개월 전){f.stale ? " — 오래된 자료" : ""}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </details>
  );
}

export function Downloads({ r }: { r: AskResult }) {
  const files = (r.downloads ?? []).filter((d) => d.kind === "csv" && d.csv);
  const bundle = (r.downloads ?? []).find((d) => d.kind === "bundle" && d.csv);
  if (!files.length && !bundle) return null;
  const save = (name: string, csv: string) => {
    const url = URL.createObjectURL(new Blob(["﻿" + csv], { type: "text/csv;charset=utf-8" }));
    const a = document.createElement("a");
    a.href = url;
    a.download = name;
    a.click();
    URL.revokeObjectURL(url);
  };
  return (
    <div id="answer-downloads" className="flex scroll-mt-24 flex-wrap items-center gap-2" data-testid="downloads">
      {/* 패턴 I: 이 답의 자료를 한 파일로, 자료별 파일은 접어 둔다 */}
      {bundle && (
        <Button variant="outline" data-testid="download-bundle" onClick={() => save(bundle.name, bundle.csv!)}>
          이 답의 자료 내려받기(CSV, {bundle.rows}줄)
        </Button>
      )}
      {files.length > 0 && (
        <details>
          <summary className="flex min-h-11 cursor-pointer items-center px-2">자료별로 받기({files.length})</summary>
          <div className="mt-2 flex flex-wrap gap-2">
            {files.map((d) => (
              <Button key={d.name} size="sm" variant="outline" onClick={() => save(d.name, d.csv!)}>
                {d.name} ({d.rows}줄)
              </Button>
            ))}
          </div>
        </details>
      )}
    </div>
  );
}

export function SuggestionList({ items, title, onPick, testId }: { items: Suggestion[]; title: string; onPick: (s: Suggestion) => void; testId: string }) {
  if (!items.length) return null;
  return (
    <div data-testid={testId}>
      <h3 className="mb-2">{title}</h3>
      <div className="flex flex-col gap-2 md:flex-row md:flex-wrap">
        {items.map((x) => (
          <Button key={x.text} variant="outline" className="h-auto min-h-12 w-full justify-start whitespace-normal py-2 text-left text-[length:var(--krds-fs-body-large)] md:w-auto" onClick={() => onPick(x)}>
            {x.text}
          </Button>
        ))}
      </div>
    </div>
  );
}

const STAGES = ["질문 이해", "자료 고르기", "조회·계산", "검수", "답 만들기"];

/** P12 축소판: 응답은 한 번에 오므로 진행률을 꾸며 내지 않는다. 처리 순서와 대기 문구만 보여 준다. */
export function Waiting() {
  const [slow, setSlow] = useState(false);
  useEffect(() => {
    const t = setTimeout(() => setSlow(true), 5000);
    return () => clearTimeout(t);
  }, []);
  return (
    <div role="status" aria-live="polite" data-testid="waiting" className="flex flex-col gap-2 rounded-(--radius) border border-(--krds-border-gray-light) p-3">
      <p className="flex items-center gap-2 font-semibold">
        <LoaderCircleIcon size={20} className="animate-spin" aria-hidden />
        {slow ? "자료가 많아 조금 더 걸리고 있어요. 잠시만 기다려 주세요." : "자료를 찾아 계산하고 있어요."}
      </p>
      <p className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">처리 순서: {STAGES.join(" → ")}</p>
    </div>
  );
}
