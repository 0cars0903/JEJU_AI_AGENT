"use client";

import { useEffect, useRef, useState } from "react";
import { Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { LoaderCircleIcon } from "@/components/icons";
import type { Answer, AskResult, BizTab, CompareTable as CompareData, Line, Slots, SummaryCell, Suggestion } from "@/lib/api";

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
  // 판단 층(L3·L4)은 굵은 글씨, 사실(L1·L2)·판단 재료(L5)는 보통 글씨. 둘 다 회색 바탕이다.
  // 강조색 윤곽은 버튼처럼 보여 누르려는 사람이 있어 뺐다(UI 검토 2026-11-13, 색은 강조색 하나만 버튼에 쓴다).
  const strong = layer === "L3" || layer === "L4";
  return (
    <span
      className={
        "inline-block w-fit rounded-(--radius) bg-muted px-2 py-0.5 text-[length:var(--krds-fs-label-medium)] " +
        (strong ? "font-semibold text-(--krds-text-basic)" : "text-(--krds-text-bolder)")
      }
    >
      {text}
    </span>
  );
}

/** 문서 23 P3: 출처는 줄 끝 번호 [n]으로 줄이고, 맨 아래 출처 목록에 번호와 기준 시점을 모은다. */
export function sourceList(a: Answer): { name: string; as_of?: string; next?: string }[] {
  const out: { name: string; as_of?: string; next?: string }[] = [];
  const add = (name?: string | null) => {
    if (name && !out.some((x) => x.name === name)) out.push({ name });
  };
  add(a.conclusion.source);
  for (const b of a.blocks) for (const l of b.lines) add(l.source);
  for (const f of a.footer ?? []) add(f.source);
  for (const x of out) {
    const f = (a.footer ?? []).find((y) => y.source === x.name);
    if (f) Object.assign(x, { as_of: f.as_of, next: f.next });
  }
  return out;
}

function SrcMark({ n, sample }: { n: number; sample?: boolean }) {
  if (n < 1) return null;
  return (
    <a href={sample ? undefined : "#answer-source"} data-testid={sample ? undefined : "src-mark"} aria-label={`출처 ${n}번 보기`} className="ml-1 align-super text-[length:var(--krds-fs-body-small)] text-(--krds-text-primary) no-underline">
      [{n}]
    </a>
  );
}

/** 종합 진단 5칸 요약(문서 23, 사람 시험 H3): 칸마다 값 하나와 위치 한 줄. 나머지는 아래 접힌 묶음에 둔다. */
function SummaryGrid({ cells, sample }: { cells: SummaryCell[]; sample?: boolean }) {
  const tone = (lv: string) => (/많은|높은|늘어/.test(lv) ? "text-(--krds-text-primary)" : /적은|낮은|줄어/.test(lv) ? "text-(--krds-text-danger)" : "text-(--krds-text-bolder)");
  return (
    <ul data-testid={sample ? undefined : "summary-grid"} aria-label="5칸 요약" className="grid grid-cols-2 gap-2 md:grid-cols-5">
      {cells.map((c) => (
        <li key={c.key} className="flex flex-col gap-0.5 rounded-(--radius) border border-(--krds-border-gray) px-3 py-2">
          <span className="text-[length:var(--krds-fs-body-small)] font-semibold text-(--krds-text-bolder)">
            {c.label} · {c.name}
          </span>
          <span className="text-[length:var(--krds-fs-heading-small)] leading-tight font-bold">{c.value}</span>
          <span className={`font-semibold ${tone(c.level)}`}>{c.level}</span>
          <span className="text-[length:var(--krds-fs-body-small)] text-(--krds-text-bolder)">{c.note}</span>
          {c.sub && <span className="text-[length:var(--krds-fs-body-small)] text-(--krds-text-bolder)">{c.sub}</span>}
        </li>
      ))}
    </ul>
  );
}

function LineItems({ lines, srcNo, sample }: { lines: Line[]; srcNo: (s?: string | null) => number; sample?: boolean }) {
  return (
    <ul className="flex flex-col gap-3">
      {lines.map((l, i) => (
        <li key={i} className="flex flex-col gap-1">
          {/* 같은 꼬리표가 줄마다 되풀이되지 않게, 앞 줄과 다를 때만 보인다(UI 검토 2026-11-13) */}
          {(i === 0 || lines[i - 1].tag !== l.tag) && <Tag text={l.tag} layer={l.layer} />}
          <span className="text-[length:var(--krds-fs-body-large)]">
            {l.text}
            <SrcMark n={srcNo(l.source)} sample={sample} />
          </span>
        </li>
      ))}
    </ul>
  );
}

/** 손익분기 계산 칸(사용자 결정 2026-11-12). 식: 손익분기 매출 = 고정비 ÷ (1 − 변동비율). 소상공인시장진흥공단 창업가이드(편의점편) 77~79쪽과 같은 식이고,
 *  가이드 예시(고정비 455만 원, 변동비율 35%)는 월 700만 원이 나온다. 입력값은 이 화면에서만 쓰고 저장하지 않는다. */
export function bepMonthly(fixedMan: number, varPct: number) {
  if (!(fixedMan > 0) || !(varPct >= 0) || varPct >= 100) return null;
  return fixedMan / (1 - varPct / 100);
}

function NumField({ label, value, onChange, unit, testId, hint }: { label: string; value: string; onChange: (v: string) => void; unit: string; testId: string; hint?: string }) {
  return (
    <label className="flex flex-col gap-1">
      <span className="font-semibold">{label}</span>
      <span className="flex items-center gap-1">
        <input
          inputMode="decimal"
          data-testid={testId}
          value={value}
          onChange={(e) => onChange(e.target.value.replace(/[^0-9.]/g, ""))}
          className="h-11 w-32 rounded-(--radius) border border-(--krds-border-gray) px-3 text-right"
        />
        <span>{unit}</span>
      </span>
      {hint && <span className="text-[length:var(--krds-fs-body-small)] text-(--krds-text-bolder)">{hint}</span>}
    </label>
  );
}

export function BepCalc({ bep }: { bep?: { ticket: number; basis: string } }) {
  const [fixed, setFixed] = useState("");
  const [vr, setVr] = useState("");
  const [days, setDays] = useState("30");
  const [ticket, setTicket] = useState(bep ? String(bep.ticket) : "");
  const m = bepMonthly(Number(fixed), Number(vr));
  const d = m && Number(days) > 0 ? m / Number(days) : null;
  const cnt = d && Number(ticket) > 0 ? Math.ceil((d * 10000) / Number(ticket)) : null;
  const man = (x: number) => `${Math.round(x).toLocaleString("ko-KR")}만 원`;
  return (
    <details data-testid="bep" className="rounded-(--radius) border border-(--krds-border-gray) px-3 py-1">
      <summary className="flex min-h-11 cursor-pointer items-center font-semibold">손익분기 매출 계산해 보기</summary>
      <div className="flex flex-col gap-3 pt-2 pb-3">
        <p className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">
          내 가게 비용을 넣으면 한 달에 얼마를 팔아야 비용을 메우는지 계산해요. 넣은 값은 저장하지 않아요.
        </p>
        <div className="flex flex-wrap gap-4">
          <NumField label="한 달 고정비" unit="만 원" value={fixed} onChange={setFixed} testId="bep-fixed" hint="임대료·인건비·관리비 등 매출과 상관없이 나가는 돈" />
          <NumField label="변동비 비율" unit="%" value={vr} onChange={setVr} testId="bep-var" hint="매출 100원당 재료비·수수료 등으로 나가는 돈" />
          <NumField label="한 달 영업일" unit="일" value={days} onChange={setDays} testId="bep-days" hint="쉬는 날을 빼고 고쳐 넣어 주세요" />
          <NumField label="결제 1건당 금액" unit="원" value={ticket} onChange={setTicket} testId="bep-ticket" hint={bep ? `기본값: ${bep.basis}` : undefined} />
        </div>
        <button
          type="button"
          data-testid="bep-example"
          onClick={() => {
            setFixed("455");
            setVr("35");
          }}
          className="w-fit min-h-11 rounded-(--radius) px-2 underline hover:bg-muted"
        >
          예시 넣기(창업가이드 예: 고정비 455만 원, 변동비 35%)
        </button>
        {m ? (
          <div data-testid="bep-result" role="status" className="rounded-(--radius) bg-(--krds-surface-primary-subtler) p-3">
            <p className="text-[length:var(--krds-fs-heading-small)] font-bold">한 달 {man(m)} 이상 팔아야 해요</p>
            {d && <p>하루로 나누면 {man(d)}이에요({days}일 영업).</p>}
            {cnt && <p>결제 1건당 {Number(ticket).toLocaleString("ko-KR")}원이면 하루 약 {cnt.toLocaleString("ko-KR")}건이에요.</p>}
            <p className="text-[length:var(--krds-fs-body-small)] text-(--krds-text-bolder)">
              식: 손익분기 매출 = 고정비 ÷ (1 − 변동비 비율). 출처: 소상공인시장진흥공단 창업가이드(편의점편) 77~79쪽.
            </p>
          </div>
        ) : (
          <p data-testid="bep-empty" className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">
            고정비와 변동비 비율을 넣으면 결과가 나와요(변동비 비율은 100% 미만).
          </p>
        )}
      </div>
    </details>
  );
}

/** 접기(문서 23 P1: 펼치기 전 요점 6개 이하). 5칸 요약이 있으면 묶음을 모두 접고, 없으면 묶음마다 앞 2줄만 보인다. */
const SHOW_LINES = 2;

/** 패턴 G 바닥 줄(자료·기준 시점·다음 갱신, OWID 방식). 근거 차트(나눠 보기)를 먼저 보이도록 답 카드 밖, 차트 뒤에 둔다(UI 검토 2026-11-13). */
export function SourceList({ r }: { r: AskResult }) {
  const srcs = r.answer ? sourceList(r.answer) : [];
  if (srcs.length === 0) return null;
  return (
    <div id="answer-source" data-testid="answer-footer" className="scroll-mt-24 flex flex-col gap-1 border-t border-(--krds-border-gray-light) pt-3 text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">
      <h3 className="text-[length:var(--krds-fs-body-medium)] font-semibold">출처</h3>
      <ol className="flex flex-col gap-1">
        {srcs.map((f, i) => (
          <li key={f.name}>
            [{i + 1}] {f.name}
            {f.as_of ? ` · 기준 ${f.as_of}` : ""}
            {f.next ? ` · 다음 갱신: ${f.next}` : ""}
          </li>
        ))}
      </ol>
    </div>
  );
}

/** v3 답 카드: 결론 한 줄(층 꼬리표) → 3블록(① 사실·비교 ② Agent 분석·예상 ③ 판단 재료) → 한계. answer가 없으면 card를 그대로 보여 준다. */
export function AnswerCard({ r, sample }: { r: AskResult; sample?: boolean }) {
  const c = r.card;
  const a = r.answer;
  if (!c && !a) return null;
  const t = (id: string) => (sample ? undefined : id);
  const srcs = a ? sourceList(a) : [];
  const srcNo = (name?: string | null) => (name ? srcs.findIndex((x) => x.name === name) + 1 : 0);
  const totalLines = a ? a.blocks.reduce((n, b) => n + b.lines.length, 0) : 0;
  return (
    <article data-testid={t("answer-card")} className="flex flex-col gap-5 rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) bg-card p-4 md:p-6">
      <div className="flex flex-col gap-2">
        {a?.conclusion.tag && <Tag text={a.conclusion.tag} layer={a.conclusion.layer} />}
        {/* Stageshow 지적 4: 결론은 28px 이상으로 다른 글보다 확실히 크게 */}
        <p data-testid={t("conclusion")} className="text-[length:max(1.75rem,var(--krds-fs-heading-medium))] leading-snug font-bold">
          {a?.conclusion.text ?? c?.conclusion}
        </p>
        {a?.conclusion.source && (
          <p data-testid={t("conclusion-source")} className="text-[length:var(--krds-fs-body-small)] text-muted-foreground">
            출처: {a.conclusion.source}
            <SrcMark n={srcNo(a.conclusion.source)} sample={sample} />
          </p>
        )}
        {/* B2·B7: 답이 길어도 결론 가까이에서 출처·내려받기·센터 자료 칸으로 바로 간다(순서는 그대로) */}
        {a && !sample && (
          <nav aria-label="이 답의 아래쪽 바로 가기" data-testid="answer-shortcuts" className="flex flex-wrap items-center gap-x-1 gap-y-0 text-[length:var(--krds-fs-body-medium)] lg:hidden">
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
      {a?.summary && <SummaryGrid cells={a.summary} sample={sample} />}
      {a?.summary && !sample && <BepCalc bep={a.bep} />}
      {a?.notice && !sample && (
        <p data-testid="biz-notice" className="rounded-(--radius) border-l-4 border-(--krds-border-primary) bg-(--krds-surface-primary-subtler) px-3 py-2 text-[length:var(--krds-fs-body-medium)]">
          {a.notice}
        </p>
      )}
      {a?.compare && !sample && <CompareTable c={a.compare} />}
      {a ? (
        <div data-testid={t("evidence")} className="flex flex-col gap-5">
          {a.blocks.map((b) => {
            const head = <h3 className="border-b border-(--krds-border-gray-light) pb-1">{b.title}</h3>;
            const folded = !!a.summary || totalLines > 6;
            const first = a.summary ? [] : folded ? b.lines.slice(0, SHOW_LINES) : b.lines;
            const rest = b.lines.slice(first.length);
            return (
              <section key={b.id} data-testid={t(`block-${b.id}`)} className="flex flex-col gap-2">
                {a.summary ? null : head}
                {first.length > 0 && <LineItems lines={first} srcNo={srcNo} sample={sample} />}
                {rest.length > 0 && (
                  <details data-testid={t(`more-${b.id}`)} className="rounded-(--radius) border border-(--krds-border-gray-light) px-3 py-1">
                    <summary className="flex min-h-11 cursor-pointer items-center font-semibold">
                      {a.summary ? `${b.title} 보기(${rest.length}줄)` : `${b.title} 나머지 ${rest.length}줄 보기`}
                    </summary>
                    <div className="pt-2 pb-3">
                      <LineItems lines={rest} srcNo={srcNo} sample={sample} />
                    </div>
                  </details>
                )}
                {b.closing && <p className="rounded-(--radius) bg-(--krds-surface-gray-subtler) p-3 font-semibold">{b.closing}</p>}
              </section>
            );
          })}
          {(a.gaps?.length ?? 0) > 0 && (
            <details data-testid={t("gaps")} className="rounded-(--radius) border border-(--krds-border-gray-light) px-3 py-1">
              <summary className="flex min-h-11 cursor-pointer items-center font-semibold">이 답에 없는 것과 확인할 곳({a.gaps!.length})</summary>
              <ul className="flex flex-col gap-2 pb-3">
                {a.gaps!.map((g) => (
                  <li key={g.what}>
                    <strong>{g.what}</strong>: {g.why} 확인할 곳: {g.where}
                  </li>
                ))}
              </ul>
            </details>
          )}
          {(a.methods?.length ?? 0) > 0 && (
            <details data-testid={t("methods")} className="rounded-(--radius) border border-(--krds-border-gray-light) px-3 py-1">
              <summary className="flex min-h-11 cursor-pointer items-center font-semibold">방법과 검증 보기({a.methods!.length})</summary>
              <ul className="flex flex-col gap-4 pb-3">
                {a.methods!.map((m) => (
                  <li key={m.kind} className="flex flex-col gap-1">
                    <strong>{m.title}</strong>
                    <span>방법: {m.how}</span>
                    <span>검증: {m.check}{m.result ? ` ${m.result}` : ""}</span>
                    <span>쓸 수 없는 경우: {m.limit}</span>
                  </li>
                ))}
              </ul>
            </details>
          )}
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
        {p.explain?.text && (
          <p data-testid="process-explain">
            {p.explain.text}
            {p.explain.by === "LLM" && <span data-testid="ai-label" className="ml-1 text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)">(AI가 쓴 설명 · 숫자는 프로그램이 계산)</span>}
          </p>
        )}
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

/** 동네 비교 5절 표(문서 22 3절): 행은 지표, 열은 두 동네와 제주 43곳 중간값, 끝 열은 차이 판정. 어느 쪽이 낫다는 판단은 쓰지 않는다. */
function CompareTable({ c }: { c: CompareData }) {
  const [a, b] = c.dongs;
  return (
    <section data-testid="compare-table" className="flex flex-col gap-2">
      <h3 className="border-b border-(--krds-border-gray-light) pb-1">두 동네 나란히 보기</h3>
      {/* 폰: 지표마다 세로로 쌓는다(표는 지표 이름 칸이 너무 좁아진다) */}
      <div className="flex flex-col gap-3 md:hidden">
        {c.sections.map((s) => (
          <div key={s.id} className="flex flex-col gap-2">
            <h4 className="font-bold">{s.title}</h4>
            {s.note && <p className="text-muted-foreground">{s.note}</p>}
            {s.rows.map((r) => (
              <div key={r.label} className="flex flex-col gap-1 border-b border-(--krds-border-gray-light) pb-2 text-[length:var(--krds-fs-body-medium)]">
                <div className="flex items-start justify-between gap-2">
                  <span>{r.label}</span>
                  <span className={"shrink-0 " + (r.verdict === "차이 있음" ? "font-bold text-(--krds-text-primary)" : "text-muted-foreground")}>{r.verdict}</span>
                </div>
                <dl className="grid grid-cols-[auto_1fr] gap-x-3 tabular-nums">
                  {[0, 1].map((i) => (
                    <div key={i} className="contents">
                      <dt className="font-semibold">{c.dongs[i]}</dt>
                      <dd>
                        {r.texts[i]}
                        {r.ranks && ` (${r.ranks[i]}위)`}
                        {r.ci && ` (구간 ${r.ci[i][0]}~${r.ci[i][1]}%)`}
                      </dd>
                    </div>
                  ))}
                  {r.texts[2] !== "-" && (
                    <>
                      <dt className="text-muted-foreground">제주 중간값</dt>
                      <dd className="text-muted-foreground">{r.texts[2]}</dd>
                    </>
                  )}
                </dl>
                <span className="text-[length:var(--krds-fs-body-small)] text-muted-foreground">{r.method}</span>
              </div>
            ))}
          </div>
        ))}
      </div>
      <div className="hidden md:block">
        <table className="w-full border-collapse text-[length:var(--krds-fs-body-medium)]">
          <thead>
            <tr className="border-b border-(--krds-border-gray) text-left">
              <th scope="col" className="py-2 pr-2 font-semibold">지표</th>
              <th scope="col" className="px-2 py-2 text-right font-semibold">{a}</th>
              <th scope="col" className="px-2 py-2 text-right font-semibold">{b}</th>
              <th scope="col" className="px-2 py-2 text-right font-normal text-muted-foreground">제주 중간값</th>
              <th scope="col" className="py-2 pl-2 font-semibold">차이</th>
            </tr>
          </thead>
          {c.sections.map((s) => (
            <tbody key={s.id} data-testid={`compare-${s.id}`}>
              <tr>
                <th scope="rowgroup" colSpan={5} className="pt-3 pb-1 text-left font-bold">
                  {s.title}
                </th>
              </tr>
              {s.note && (
                <tr>
                  <td colSpan={5} className="pb-2 text-muted-foreground">
                    {s.note}
                  </td>
                </tr>
              )}
              {s.rows.map((r) => (
                <tr key={r.label} className="border-b border-(--krds-border-gray-light) align-top">
                  <th scope="row" className="py-2 pr-2 text-left font-normal">
                    {r.label}
                    <span className="block text-[length:var(--krds-fs-body-small)] text-muted-foreground">{r.method}</span>
                  </th>
                  {[0, 1].map((i) => (
                    <td key={i} className="px-2 py-2 text-right whitespace-nowrap tabular-nums">
                      {r.texts[i]}
                      {r.ranks && <span className="block text-[length:var(--krds-fs-body-small)] text-muted-foreground">{r.ranks[i]}위</span>}
                      {r.ci && <span className="block text-[length:var(--krds-fs-body-small)] text-muted-foreground">{r.ci[i][0]}~{r.ci[i][1]}%</span>}
                    </td>
                  ))}
                  <td className="px-2 py-2 text-right whitespace-nowrap text-muted-foreground tabular-nums">{r.texts[2]}</td>
                  <td data-testid="compare-verdict" className={"py-2 pl-2 whitespace-nowrap " + (r.verdict === "차이 있음" ? "font-bold text-(--krds-text-primary)" : "text-muted-foreground")}>
                    {r.verdict}
                  </td>
                </tr>
              ))}
            </tbody>
          ))}
        </table>
      </div>
      <p className="text-[length:var(--krds-fs-body-small)] text-muted-foreground">{c.rule}</p>
    </section>
  );
}

/** 종합 진단 → 다른 동네와 비교(문서 22 3절). 누르면 비슷한 동네 5곳을 후보로 먼저 보여 주고, 다른 동네는 조건 패널에서 고른다. */
export function CompareWith({ cw, onPick, onOther }: { cw: NonNullable<Answer["compare_with"]>; onPick: (slots: Slots, text: string) => void; onOther: (preset: Slots) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <div data-testid="compare-with" className="flex flex-col gap-2">
      <div>
        <Button variant="outline" aria-expanded={open} onClick={() => setOpen(!open)} data-testid="compare-open">
          다른 동네와 비교
        </Button>
      </div>
      {open && (
        <div className="flex flex-col gap-2">
          <p className="text-[length:var(--krds-fs-body-medium)]">{cw.dong}과 비슷한 동네(업종 구성·연령·방문·버스가 가까운 5곳)부터 보여 드려요.</p>
          <div className="flex flex-wrap gap-2">
            {cw.candidates.map((x) => (
              <Button key={x.dong} variant="outline" className="min-h-11" data-testid="compare-candidate" onClick={() => onPick(x.slots, x.text)}>
                {x.dong}
              </Button>
            ))}
            <Button
              variant="ghost"
              className="min-h-11 underline"
              data-testid="compare-other"
              onClick={() => onOther({ topic: "compare", space: [cw.dong], ...(cw.target ? { target: cw.target } : {}) })}
            >
              다른 동네 고르기
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}

/** 종합 진단 답 위의 업종 탭(문서 22 2단계). 누르면 같은 동네를 그 업종으로 다시 진단한다. 고른 업종에서 빠지는 분석은 탭 아래에 한 줄로 알린다. */
export function BizTabs({ tabs, onPick }: { tabs: BizTab[]; onPick: (t: BizTab) => void }) {
  if (tabs.length < 2) return null;
  const cur = tabs.find((t) => t.current) ?? tabs[0];
  return (
    <nav aria-label="업종 고르기" data-testid="biz-tabs" className="flex flex-col gap-1">
      <div role="tablist" className="-mx-1 flex gap-1 overflow-x-auto px-1 pb-1">
        {tabs.map((t) => (
          <button
            key={t.label}
            type="button"
            role="tab"
            aria-selected={t === cur}
            data-testid="biz-tab"
            onClick={() => t !== cur && onPick(t)}
            className={
              "min-h-11 shrink-0 rounded-(--radius) border px-3 text-[length:var(--krds-fs-body-medium)] whitespace-nowrap " +
              (t === cur ? "border-(--krds-text-primary) bg-(--krds-text-primary) font-semibold text-white" : "border-(--krds-border-gray) bg-card hover:bg-muted")
            }
          >
            {t.label}
            {t.stores != null && <span className={t === cur ? "" : "text-muted-foreground"}> {t.stores.toLocaleString()}곳</span>}
          </button>
        ))}
      </div>
      {cur.note && (
        <p data-testid="biz-tab-note" className="text-[length:var(--krds-fs-body-small)] text-muted-foreground">
          {cur.label}: {cur.note}
        </p>
      )}
    </nav>
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
