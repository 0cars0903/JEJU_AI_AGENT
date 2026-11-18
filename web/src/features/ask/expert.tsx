"use client";

/** 상세 분석(설계 11-2절, 2026-11-13; 2026-11-14 구조 수정): 센터 담당자가 자유 문장으로 분석을 요청하면
 * 로컬 분석 담당 Agent(qwen2.5:7b, app/analyst.py)가 요청을 기법 12종에 연결해 계산·해석한다(Claude 없이 동작).
 * Claude는 담당자 계정으로 로그인한 뒤 [Claude로 분석]을 누른 요청에만 쓴다. 코드·결과표·그래프를 함께 보여 주고 내려받게 한다. */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, Bar, BarChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { type ExpertResult, type ExpertSeries, type ExpertTable, type StepReport, askExpert, getExpertStatus } from "@/lib/api";
import { ViewChart, shortNum } from "./views";
import { LoginForm } from "@/components/login";
import { markLongParts } from "./print-layout";

const EXAMPLES = ["노형동 음식점 월 매출을 시계열 분해해서 추세와 계절성 보여줘", "43개 동네를 방문·매출·가게 수로 군집분석 해줘", "동네별 음식점 매출에 방문 인구와 가게 수가 미치는 영향을 회귀분석해줘"];

function save(name: string, text: string, type: string) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  URL.revokeObjectURL(url);
}

function tableCsv(t: ExpertTable) {
  const esc = (v: unknown) => `"${String(v ?? "").replace(/"/g, '""')}"`;
  return "﻿" + [t.columns.map(esc).join(","), ...t.rows.map((r) => r.map(esc).join(","))].join("\n");
}

function SeriesChart({ s, width }: { s: ExpertSeries; width?: number }) {
  const data = s.x.map((x, i) => ({ x, y: s.y[i] }));
  // 인쇄용은 폭을 정해 그린다(숨겨진 칸에서는 크기 맞춤 부품의 폭이 0이 된다)
  const fixed = width ? { width, height: 240 } : {};
  const common = { data, margin: { top: 8, right: 28, bottom: 8, left: 8 }, ...fixed };
  return (
    <figure className="flex flex-col gap-1" data-testid={width ? undefined : "expert-chart"}>
      <figcaption className="font-semibold">{s.title ?? s.name ?? "그래프"}</figcaption>
      <div className={width ? "" : "h-64 w-full"}>
        <Fit fixed={!!width}>
          {s.kind === "scatter" ? (
            <ScatterChart margin={common.margin} {...fixed}>
              <CartesianGrid stroke="#e5e7eb" />
              <XAxis dataKey="x" type="number" tickFormatter={(v) => shortNum(v)} name="x" />
              <YAxis dataKey="y" type="number" tickFormatter={(v) => shortNum(v)} name="y" />
              <Tooltip formatter={(v) => shortNum(Number(v))} />
              <Scatter data={data} fill="var(--krds-element-primary, #256ef4)" isAnimationActive={false} />
            </ScatterChart>
          ) : s.kind === "bar" ? (
            <BarChart {...common}>
              <CartesianGrid stroke="#e5e7eb" vertical={false} />
              <XAxis dataKey="x" />
              <YAxis tickFormatter={(v) => shortNum(v)} />
              <Tooltip formatter={(v) => shortNum(Number(v))} />
              <Bar dataKey="y" fill="var(--krds-element-primary, #256ef4)" isAnimationActive={false} />
            </BarChart>
          ) : (
            <LineChart {...common}>
              <CartesianGrid stroke="#e5e7eb" vertical={false} />
              <XAxis dataKey="x" minTickGap={24} />
              <YAxis tickFormatter={(v) => shortNum(v)} />
              <Tooltip formatter={(v) => shortNum(Number(v))} />
              <Line dataKey="y" dot={false} stroke="var(--krds-element-primary, #256ef4)" isAnimationActive={false} />
            </LineChart>
          )}
        </Fit>
      </div>
    </figure>
  );
}

function Fit({ fixed, children }: { fixed: boolean; children: React.ReactElement }) {
  return fixed ? children : <ResponsiveContainer>{children}</ResponsiveContainer>;
}

function fmtNum(v: unknown) {
  return typeof v === "number" ? v.toLocaleString("ko-KR", { maximumFractionDigits: 4 }) : String(v ?? "");
}

/** 상세 분석 PDF(사용자 지적 2026-11-13: 내려받기 없음). 인쇄할 때만 보이는 정리본. 장은 일반 보고서와 같은 쪽 나눔 규칙을 따른다. */
function ExpertPrint({ q, r }: { q: string; r: ExpertResult }) {
  const [host, setHost] = useState<HTMLElement | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => setHost(document.body), []);
  useEffect(() => {
    const f = () => markLongParts(rootRef.current);
    window.addEventListener("beforeprint", f);
    return () => window.removeEventListener("beforeprint", f);
  }, []);
  if (!host) return null;
  const res = r.result ?? {};
  const nums = Object.entries(res.numbers ?? {});
  const now = new Date().toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
  const stepped = /^(단계형 Agent|질문 나누기)/.test(r.method ?? "");
  if (stepped && r.steps?.length) {
    return createPortal(
      <div ref={rootRef} className="print-only print-expert" data-testid="expert-report" aria-hidden>
        <StepBody q={q} r={r} steps={r.steps} now={now} />
      </div>,
      host,
    );
  }
  return createPortal(
    <div ref={rootRef} className="print-only print-expert" data-testid="expert-report" aria-hidden>
      {/* 여러 단계 질문(단계형 Agent·질문 나누기)은 도민 질문의 보고서다. 상세 분석과 머리말을 나눈다(2026-11-16) */}
      <h1>제주빅데이터센터 빅데이터 분석·컨설팅 지원 보조 Agent · {stepped ? "보고서" : "상세 분석"}</h1>
      <p>{stepped ? "질문" : "요청"}: {q}</p>
      <p>
        {stepped
          ? `처리: ${r.method} · 단계마다 정해진 계산 코드로 답한 결과(설명 숫자는 계산 결과와 대조함) · 도구 ${r.trace?.length ?? 0}회 · 만든 때 ${now}`
          : `기법: ${r.method} · ${r.code ? "AI가 작성한 코드" : "정해진 기법 코드"}를 제출본 자료로 실행한 결과(설명 숫자는 실행 결과와 대조함) · 도구 ${r.trace?.length ?? 0}단계 · 만든 때 ${now}`}
      </p>
      <div className="report-part">
        <h2>설명</h2>
        {/* 하위 줄('   · ...')은 글머리를 겹쳐 찍지 않고 들여 쓴다(2026-11-16 Windows PDF 검토) */}
        <ul>{(r.lines ?? []).map((l, i) => (/^\s*·\s*/.test(l) ? <li key={i} style={{ listStyle: "none", marginLeft: "12pt" }}>{l.replace(/^\s*·\s*/, "– ")}</li> : <li key={i}>{l}</li>))}</ul>
        {nums.length > 0 && (
          <table className="report-table">
            <tbody>
              {nums.map(([k, v]) => (
                <tr key={k}>
                  <th>{k}</th>
                  <td>{fmtNum(v)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {(res.notes ?? []).length > 0 && <ul>{res.notes!.map((n, i) => <li key={i}>주의: {n}</li>)}</ul>}
      </div>
      {(res.series ?? []).length > 0 && (
        <div className="report-part">
          <h2>그래프</h2>
          {res.series!.map((s, i) => (
            <div key={i} className="report-chart">
              <SeriesChart s={s} width={640} />
            </div>
          ))}
        </div>
      )}
      {(res.tables ?? []).map((t, i) => (
        <div key={i} className="report-part">
          <h2>{t.title ?? `표 ${i + 1}`}</h2>
          <table className="report-table">
            <thead>
              <tr>{t.columns.map((c) => <th key={c}>{c}</th>)}</tr>
            </thead>
            <tbody>
              {t.rows.slice(0, 50).map((row, j) => (
                <tr key={j}>{row.map((v, k) => <td key={k}>{fmtNum(v)}</td>)}</tr>
              ))}
            </tbody>
          </table>
          {t.rows.length > 50 && <p>앞 50행만 실었어요(전체 {t.rows.length}행은 화면의 [CSV 내려받기]로 받아 주세요).</p>}
        </div>
      ))}
      <div className="report-part report-appendix">
        <h2>{r.code ? "부록. 분석 계획과 코드" : "부록. 분석 계획"}</h2>
        <ul className="report-srcs">{(r.plan ?? []).map((p, i) => <li key={i}>{p}</li>)}</ul>
        {r.code ? <pre>{r.code}</pre> : <p>이 분석은 AI가 코드를 쓰지 않고, 정해진 계산 코드로 조각마다 답했어요.</p>}
      </div>
    </div>,
    host,
  );
}

const STEP_KIND: Record<string, string> = {
  answer_question: "일반 답(정해진 계산)", run_technique: "통계 기법", compare_steps: "비교·종합(앞 단계 숫자로)", rank_industries: "업종 순위",
  skip_step: "넘김(자료 범위 밖)", search_center_catalog: "센터 자료 찾기", dup: "앞 단계와 같음", fail: "답하지 못함",
};

/** 여러 단계 질문 보고서(2026-11-18 마스터: 여러 단계 보고서가 읽기 어렵다). 일반 보고서와 같은 뼈대:
 * 한눈에 → 단계별 절(질문 원문 구절 제목·결론·근거·그래프) → 알 수 있는 것과 없는 것 → 부록 A 처리 과정 → 부록 B 자료와 기준 시점 */
function StepBody({ q, r, steps, now }: { q: string; r: ExpertResult; steps: StepReport[]; now: string }) {
  const base = (x: string) => x.replace(/\(.*$/, "").replace(/ 기록$/, "").trim();
  const asOf = new Map<string, string>();
  for (const s of steps) for (const f of s.freshness ?? []) if (f.source && !asOf.has(base(f.source))) asOf.set(base(f.source), f.as_of);
  const srcs = Array.from(asOf.keys());
  const mark = (name?: string | null) => {
    const n = name ? srcs.indexOf(base(name)) + 1 : 0;
    return n > 0 ? ` [${n}]` : "";
  };
  const answered = steps.filter((s) => s.state === "끝남" && s.kind !== "dup");
  const cmp = [...answered].reverse().find((s) => s.kind === "compare_steps");
  const splitBy = r.trace?.[0]?.tool === "plan" ? r.trace[0].by : "AI(로컬 모델)";
  return (
    <>
      <h1>제주빅데이터센터 빅데이터 분석·컨설팅 지원 보조 Agent 보고서</h1>
      <p>질문: {q}</p>
      <p>이렇게 이해했어요: 물은 일이 {steps.length}가지라 {steps.length}단계로 나눠 답했어요.</p>
      <h2>한눈에</h2>
      {cmp && (
        <p>
          <strong>{cmp.text}</strong>
        </p>
      )}
      <ul data-testid="report-step-summary">
        {steps
          .filter((s) => s !== cmp)
          .map((s) => (
            <li key={s.no}>
              <span className="report-tag">{s.no}단계</span>
              {s.text}
              {mark(s.source)}
            </li>
          ))}
      </ul>
      {steps.map((s) => (
        <div key={s.no} className="report-part" data-testid="report-step">
          <h2>
            {s.no}. {s.title}
          </h2>
          {s.tag && <span className="report-tag">{s.tag}</span>}
          <p>
            <strong>{s.text}</strong>
            {mark(s.source)}
          </p>
          {(s.evidence ?? []).length > 0 && (
            <ul>
              {s.evidence!.map((e, i) => (
                <li key={i}>
                  {e.tag && <span className="report-tag">{e.tag}</span>}
                  {e.text}
                  {mark(e.source)}
                </li>
              ))}
            </ul>
          )}
          {(s.views ?? []).length > 0 && (
            <div className="report-charts">
              {s.views!.map((v) => (
                <div key={v.id} className="report-chart">
                  <h3>
                    {v.label} — {v.summary}
                  </h3>
                  <ViewChart v={v} width={640} />
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
      {(r.limits ?? []).length > 0 && (
        <div data-testid="report-limits" className="report-part">
          <h2>알 수 있는 것과 없는 것</h2>
          <ul>
            {r.limits!.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </div>
      )}
      <div data-testid="report-process" className="report-part report-appendix">
        <h2>부록 A. 처리 과정</h2>
        <table className="report-table">
          <thead>
            <tr>
              <th>단계</th>
              <th>한 일</th>
              <th>방법</th>
              <th>고른 쪽</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>-</td>
              <td>질문을 단계로 나눔</td>
              <td>{steps.length}단계</td>
              <td>{splitBy}</td>
            </tr>
            {steps.map((s) => (
              <tr key={s.no}>
                <td>{s.no}</td>
                <td>{s.title}</td>
                <td>{STEP_KIND[s.kind] ?? s.kind}</td>
                <td>{s.by}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p>숫자는 모두 정해진 계산 코드가 냈고, 설명 문장의 숫자는 계산 결과와 대조했어요.</p>
      </div>
      <div data-testid="report-sources" className="report-part">
        <h2>부록 B. 자료 목록과 기준 시점</h2>
        <table className="report-table">
          <thead>
            <tr>
              <th>자료</th>
              <th>기준 시점</th>
            </tr>
          </thead>
          <tbody>
            {srcs.map((x, i) => (
              <tr key={x}>
                <td>
                  [{i + 1}] {x}
                </td>
                <td>{asOf.get(x)}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p>생성 {now} · 제주빅데이터센터 빅데이터 분석·컨설팅 지원 보조 Agent</p>
      </div>
    </>
  );
}

function printExpert() {
  // 인쇄하는 동안만 전문가 정리본을 보이게 표시한다. 인쇄 창이 닫히면(afterprint) 지운다.
  document.body.classList.add("printing-expert");
  const done = () => {
    document.body.classList.remove("printing-expert");
    window.removeEventListener("afterprint", done);
  };
  window.addEventListener("afterprint", done);
  window.print();
}

export function ResultView({ r, q }: { r: ExpertResult; q: string }) {
  if (r.status !== "성공") {
    return (
      <div data-testid="expert-fail" className="flex flex-col gap-1 rounded-(--radius) border border-(--krds-border-gray) p-3">
        <p className="font-semibold">분석을 끝내지 못했어요</p>
        <p>{r.error}</p>
        {r.hint && <p className="text-(--krds-text-bolder)">{r.hint}</p>}
        <AgentTrace r={r} />
      </div>
    );
  }
  if (r.steps?.length) return <StepScreen r={r} q={q} steps={r.steps} />;
  const res = r.result ?? {};
  const nums = Object.entries(res.numbers ?? {});
  return (
    <div data-testid="expert-result" className="flex flex-col gap-3">
      <ExpertPrint q={q} r={r} />
      <Button variant="outline" data-testid="expert-print" onClick={printExpert} className="self-start">
        PDF로 저장(인쇄)
      </Button>
      <p className="text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)">
        기법: {r.method} · {r.code ? "AI가 작성한 코드 · 실행 결과" : r.backend === "code" ? "조각마다 일반 경로 계산" : "정해진 기법 코드 · 실행 결과"} · 설명: {r.by === "AI" ? "AI(숫자는 실행 결과와 대조함)" : r.by} · {r.sec}초
      </p>
      <AgentTrace r={r} />
      <ul className="flex list-disc flex-col gap-1 pl-5" data-testid="expert-lines">
        {(r.lines ?? []).map((l, i) => (
          <li key={i}>{l}</li>
        ))}
      </ul>
      {nums.length > 0 && (
        <table className="w-full max-w-xl border-collapse text-left" data-testid="expert-numbers">
          <tbody>
            {nums.map(([k, v]) => (
              <tr key={k} className="border-b border-(--krds-border-gray-light)">
                <th className="py-1 pr-4 font-normal text-(--krds-text-bolder)">{k}</th>
                <td className="py-1">{typeof v === "number" ? v.toLocaleString("ko-KR", { maximumFractionDigits: 4 }) : String(v)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      {(res.series ?? []).map((s, i) => (
        <SeriesChart key={i} s={s} />
      ))}
      {(res.tables ?? []).map((t, i) => (
        <div key={i} className="flex flex-col gap-1 overflow-x-auto">
          <div className="flex items-center gap-2">
            <span className="font-semibold">{t.title ?? `표 ${i + 1}`}</span>
            <Button variant="outline" size="sm" onClick={() => save(`분석표_${i + 1}.csv`, tableCsv(t), "text/csv;charset=utf-8")}>
              CSV 내려받기
            </Button>
          </div>
          <table className="border-collapse text-left">
            <thead>
              <tr>
                {t.columns.map((c) => (
                  <th key={c} className="border-b border-(--krds-border-gray) px-2 py-1">
                    {c}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {t.rows.slice(0, 50).map((row, j) => (
                <tr key={j}>
                  {row.map((v, k) => (
                    <td key={k} className="border-b border-(--krds-border-gray-light) px-2 py-1">
                      {typeof v === "number" ? v.toLocaleString("ko-KR", { maximumFractionDigits: 4 }) : String(v ?? "")}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}
      {(res.notes ?? []).length > 0 && (
        <ul className="flex flex-col gap-1 text-(--krds-text-bolder)" data-testid="expert-notes">
          {res.notes!.map((n, i) => (
            <li key={i}>주의: {n}</li>
          ))}
        </ul>
      )}
      <details data-testid="expert-code" className="rounded-(--radius) border border-(--krds-border-gray-light) p-2">
        <summary className="cursor-pointer font-semibold">분석 계획과 코드 보기</summary>
        <ol className="list-decimal pl-5">
          {(r.plan ?? []).map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ol>
        {r.code && (
          <>
            <pre className="mt-2 overflow-x-auto rounded bg-muted p-2 text-[length:var(--krds-fs-body-small)]">{r.code}</pre>
            <Button variant="outline" size="sm" onClick={() => save("analysis.py", r.code ?? "", "text/x-python;charset=utf-8")}>
              코드 내려받기
            </Button>
          </>
        )}
      </details>
    </div>
  );
}

function Chip({ text }: { text: string }) {
  return <span className="inline-block w-fit rounded-(--radius) bg-muted px-2 py-0.5 text-[length:var(--krds-fs-label-medium)] text-(--krds-text-bolder)">{text}</span>;
}

/** 여러 단계 질문의 화면 답(2026-11-18 마스터: 보고서와 같은 뼈대로). 한눈에 → 단계별(원문 구절 제목·결론·근거·그래프) → 알 수 있는 것과 없는 것 → 처리 기록 */
function StepScreen({ r, q, steps }: { r: ExpertResult; q: string; steps: StepReport[] }) {
  const answered = steps.filter((s) => s.state === "끝남" && s.kind !== "dup");
  const cmp = [...answered].reverse().find((s) => s.kind === "compare_steps");
  return (
    <div data-testid="expert-result" className="flex flex-col gap-4">
      <ExpertPrint q={q} r={r} />
      <section data-testid="step-summary" className="flex flex-col gap-2 rounded-(--radius) border border-(--krds-border-gray) p-4">
        <h3 className="font-semibold">한눈에 · {steps.length}단계로 나눠 답했어요</h3>
        {cmp && <p className="text-lg font-semibold">{cmp.text}</p>}
        <ol className="flex flex-col gap-1">
          {steps
            .filter((s) => s !== cmp)
            .map((s) => (
              <li key={s.no}>
                <span className="font-semibold">{s.no}단계</span> · {s.text}
              </li>
            ))}
        </ol>
      </section>
      {steps.map((s) => (
        <section key={s.no} data-testid="step-section" className="flex flex-col gap-2 border-t border-(--krds-border-gray-light) pt-3">
          <h3 className="text-base font-semibold">
            {s.no}. {s.title}
          </h3>
          {s.tag && <Chip text={s.tag} />}
          <p className="font-semibold">{s.text}</p>
          {(s.evidence ?? []).length > 0 && (
            <ul className="flex flex-col gap-2">
              {s.evidence!.map((e, i) => (
                <li key={i} className="flex flex-col gap-0.5">
                  {e.tag && <Chip text={e.tag} />}
                  <span>{e.text}</span>
                </li>
              ))}
            </ul>
          )}
          {(s.views ?? []).map((v) => (
            <figure key={v.id} className="flex flex-col gap-1" data-testid="step-chart">
              <figcaption className="font-semibold">
                {v.label} — {v.summary}
              </figcaption>
              <ViewChart v={v} />
            </figure>
          ))}
        </section>
      ))}
      {(r.limits ?? []).length > 0 && (
        <section data-testid="step-limits" className="flex flex-col gap-1 border-t border-(--krds-border-gray-light) pt-3">
          <h3 className="font-semibold">알 수 있는 것과 없는 것</h3>
          <ul className="flex list-disc flex-col gap-1 pl-5">
            {r.limits!.map((x) => (
              <li key={x}>{x}</li>
            ))}
          </ul>
        </section>
      )}
      <Button variant="outline" data-testid="expert-print" onClick={printExpert} className="self-start">
        PDF로 저장(인쇄)
      </Button>
      <p className="text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)">
        처리: {r.method} · 숫자는 정해진 계산 코드가 냄 · 판단: {r.by} · {r.sec}초
      </p>
      <AgentTrace r={r} />
    </div>
  );
}

/** Agent 처리 기록(문서 26 안 A·D): AI가 고른 도구를 순서대로 보인다. */
function AgentTrace({ r }: { r: ExpertResult }) {
  if (!r.trace?.length) return null;
  const who = r.backend === "ollama" ? "로컬 모델(qwen2.5:7b)" : r.backend === "code" ? "프로그램" : "Claude";
  return (
    <div data-testid="expert-trace" className="rounded-(--radius) border border-(--krds-border-gray-light) p-2">
      <p className="font-semibold">
        Agent 처리 기록 <span className="font-normal text-(--krds-text-subtle)">· {r.backend === "code" ? "질문을 나눠 조각마다 일반 경로로 답했어요" : `${who}가 도구를 골라 실행했어요`}</span>
      </p>
      <ol className="mt-1 flex flex-col gap-1 text-[length:var(--krds-fs-body-small)]">
        {r.trace.map((t) => (
          <li key={t.step} data-testid="expert-trace-step" className="grid grid-cols-[1.5rem_1fr] gap-x-2">
            <span className="font-semibold text-(--krds-text-subtle)">{t.step}</span>
            <span>
              <span className="font-semibold">{t.name}</span>
              <span className="ml-1 text-(--krds-text-subtle)">· {t.by} · {t.ok ? "성공" : "실패"} · {t.sec}초</span>
              {t.note && <span className="block">{t.note}</span>}
            </span>
          </li>
        ))}
      </ol>
    </div>
  );
}

const AREA = "expert-area";

export function ExpertMode() {
  const st = useQuery({ queryKey: ["expert-status"], queryFn: getExpertStatus, staleTime: Infinity, retry: false });
  const [q, setQ] = useState("");
  const m = useMutation({ mutationFn: askExpert });
  const local = !!st.data?.enabled && st.data.backend === "ollama";
  // 요청 단위 Claude(2026-11-14 마스터 결정): 기본은 로컬 모델, 담당자가 로그인한 뒤 [Claude로 분석]을 누른 요청에만 Claude
  if (!st.data?.available || (!local && !st.data.claude && !st.data.claude_locked)) return null;
  if (!local && !st.data.claude)
    return (
      <details id={AREA} data-testid="expert-locked" className="scroll-mt-24 rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) p-3 print:hidden">
        <summary className="cursor-pointer font-semibold">상세 분석: 분석 기법을 직접 요청하기(담당자 로그인 필요)</summary>
        <div className="mt-2 flex max-w-sm flex-col gap-2">
          <p className="text-(--krds-text-bolder)">이 화면에는 로컬 분석 모델이 없어요. 센터 담당자가 로그인하면 Claude로 분석할 수 있어요.</p>
          <LoginForm />
        </div>
      </details>
    );
  const send = (useClaude: boolean) => m.mutate({ question: q.trim(), useClaude });
  return (
    <details id={AREA} data-testid="expert" className="scroll-mt-24 rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) p-3 print:hidden">
      <summary className="cursor-pointer font-semibold">상세 분석: 분석 기법을 직접 요청하기(AI가 도구를 골라 실행)</summary>
      <div className="mt-2 flex flex-col gap-2">
        <p className="text-(--krds-text-bolder)">
          센터 담당자처럼 분석 기법을 정해 묻고 싶을 때 써요. AI가 자료 확인·통계 기법 12종·센터 자료 찾기 가운데 필요한 도구를 골라 제출본 표로 실행하고, 고른 순서와 결과를 모두 보여 드려요.
          {local && " 기본은 이 PC의 로컬 모델이 처리해요."}
        </p>
        <Textarea data-testid="expert-input" value={q} onChange={(e) => setQ(e.target.value)} rows={2} maxLength={500} placeholder={EXAMPLES[0]} />
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((x) => (
            <button key={x} type="button" onClick={() => setQ(x)} className="min-h-11 rounded-(--radius) border border-(--krds-border-gray) px-3 text-left hover:bg-muted">
              {x}
            </button>
          ))}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {local && (
            <Button data-testid="expert-submit" disabled={!q.trim() || m.isPending} onClick={() => send(false)}>
              {m.isPending && !m.variables?.useClaude ? "분석하는 중이에요" : "분석 요청"}
            </Button>
          )}
          {st.data.claude && (
            <Button data-testid="expert-claude" variant={local ? "outline" : "default"} disabled={!q.trim() || m.isPending} onClick={() => send(true)}>
              {m.isPending && m.variables?.useClaude ? "Claude가 분석하는 중이에요(30초~1분)" : "Claude로 분석(담당자)"}
            </Button>
          )}
        </div>
        {local && st.data.claude_locked && (
          <details data-testid="expert-claude-login">
            <summary className="cursor-pointer text-(--krds-text-subtle)">목록에 없는 분석(AI가 코드 작성)은 담당자 로그인 뒤 Claude로 할 수 있어요</summary>
            <div className="mt-2 max-w-sm">
              <LoginForm />
            </div>
          </details>
        )}
        {local && st.data.claude_setup && (
          <p data-testid="expert-claude-setup" className="text-(--krds-text-subtle)">
            목록에 없는 분석(AI가 코드 작성)은 담당자 계정(JEJU_ACCOUNTS)을 설정하고 로그인하면 Claude로 할 수 있어요.
          </p>
        )}
        {m.isError && <p data-testid="expert-fail">요청을 보내지 못했어요. 다시 시도해 주세요.</p>}
        {m.data && <ResultView r={m.data} q={m.variables?.question ?? q} />}
      </div>
    </details>
  );
}
