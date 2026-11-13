"use client";

/** 전문가 모드(설계 11-2절, 2026-11-13): 센터 담당자가 자유 문장으로 분석을 요청하면 Claude가 계획·코드를 짜고 격리 실행한다.
 * Claude 키가 있을 때만 보인다. 코드·결과표·그래프를 함께 보여 주고 코드·결과를 내려받게 한다. */
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useMutation, useQuery } from "@tanstack/react-query";
import { CartesianGrid, Line, LineChart, Bar, BarChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { type ExpertResult, type ExpertSeries, type ExpertTable, askExpert, getExpertStatus } from "@/lib/api";
import { shortNum } from "./views";
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

/** 전문가 모드 PDF(사용자 지적 2026-11-13: 내려받기 없음). 인쇄할 때만 보이는 정리본. 장은 일반 보고서와 같은 쪽 나눔 규칙을 따른다. */
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
  return createPortal(
    <div ref={rootRef} className="print-only print-expert" data-testid="expert-report" aria-hidden>
      <h1>제주 상권 EDA 전문가 모드 분석</h1>
      <p>요청: {q}</p>
      <p>
        기법: {r.method} · AI가 짠 코드를 제출본 자료로 실행한 결과(설명 숫자는 실행 결과와 대조함) · 만든 때 {now}
      </p>
      <div className="report-part">
        <h2>설명</h2>
        <ul>{(r.lines ?? []).map((l, i) => <li key={i}>{l}</li>)}</ul>
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
        <h2>부록. 분석 계획과 코드</h2>
        <ol>{(r.plan ?? []).map((p, i) => <li key={i}>{p}</li>)}</ol>
        <pre>{r.code}</pre>
      </div>
    </div>,
    host,
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

function ResultView({ r, q }: { r: ExpertResult; q: string }) {
  if (r.status !== "성공") {
    return (
      <div data-testid="expert-fail" className="flex flex-col gap-1 rounded-(--radius) border border-(--krds-border-gray) p-3">
        <p className="font-semibold">분석을 끝내지 못했어요</p>
        <p>{r.error}</p>
        {r.hint && <p className="text-(--krds-text-bolder)">{r.hint}</p>}
      </div>
    );
  }
  const res = r.result ?? {};
  const nums = Object.entries(res.numbers ?? {});
  return (
    <div data-testid="expert-result" className="flex flex-col gap-3">
      <ExpertPrint q={q} r={r} />
      <Button variant="outline" data-testid="expert-print" onClick={printExpert} className="self-start">
        PDF로 저장(인쇄)
      </Button>
      <p className="text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)">
        기법: {r.method} · {r.by === "AI" ? "AI가 짠 코드 · 실행 결과(설명 숫자는 실행 결과와 대조함)" : r.by} · {r.sec}초
      </p>
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
        <pre className="mt-2 overflow-x-auto rounded bg-muted p-2 text-[length:var(--krds-fs-body-small)]">{r.code}</pre>
        <Button variant="outline" size="sm" onClick={() => save("analysis.py", r.code ?? "", "text/x-python;charset=utf-8")}>
          코드 내려받기
        </Button>
      </details>
    </div>
  );
}

const AREA = "expert-area";

/** 머리말 바로 가기(UI 검토 2026-11-13): 2차 사용자(센터 담당자)가 화면 맨 아래 접힌 전문가 모드를 찾지 않아도 되게 한다. */
export function ExpertLink() {
  const st = useQuery({ queryKey: ["expert-status"], queryFn: getExpertStatus, staleTime: Infinity, retry: false });
  if (!st.data?.available && !st.data?.enabled) return null;
  return (
    <a
      href={`#${AREA}`}
      data-testid="expert-link"
      onClick={(e) => {
        const el = document.getElementById(AREA) as HTMLDetailsElement | null;
        if (!el) return;
        e.preventDefault();
        el.open = true;
        el.scrollIntoView({ behavior: "smooth", block: "start" });
        el.querySelector("summary")?.focus({ preventScroll: true });
      }}
      // 폰에서는 머리말이 두 줄로 늘어나 숨긴다(센터 담당자는 PC를 쓰고, 전문가 모드 칸은 화면 아래에 그대로 있다)
      className="hidden min-h-9 items-center rounded-(--radius) px-2 font-semibold text-(--krds-text-bolder) underline hover:bg-muted sm:inline-flex"
    >
      전문가 모드
    </a>
  );
}

export function ExpertMode() {
  const st = useQuery({ queryKey: ["expert-status"], queryFn: getExpertStatus, staleTime: Infinity, retry: false });
  const [q, setQ] = useState("");
  const m = useMutation({ mutationFn: askExpert });
  if (st.data?.available && st.data.login_required)
    return (
      <details id={AREA} data-testid="expert-locked" className="scroll-mt-24 rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) p-3 print:hidden">
        <summary className="cursor-pointer font-semibold">전문가 모드: 분석 기법을 직접 요청하기(로그인 필요)</summary>
        <div className="mt-2 flex max-w-sm flex-col gap-2">
          <p className="text-(--krds-text-bolder)">AI가 분석 코드를 짜서 실행하는 기능이라 로그인한 사용자만 쓸 수 있어요.</p>
          <LoginForm />
        </div>
      </details>
    );
  if (!st.data?.enabled) return null;
  return (
    <details id={AREA} data-testid="expert" className="scroll-mt-24 rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) p-3 print:hidden">
      <summary className="cursor-pointer font-semibold">전문가 모드: 분석 기법을 직접 요청하기(AI가 코드를 짜서 실행)</summary>
      <div className="mt-2 flex flex-col gap-2">
        <p className="text-(--krds-text-bolder)">
          센터 담당자처럼 분석 기법을 정해 묻고 싶을 때 씁니다. AI가 분석 계획과 Python 코드를 짜고, 제출본에 든 표로만 실행합니다. 코드와 결과를 모두 보여 드려요.
        </p>
        <Textarea data-testid="expert-input" value={q} onChange={(e) => setQ(e.target.value)} rows={2} maxLength={500} placeholder={EXAMPLES[0]} />
        <div className="flex flex-wrap gap-2">
          {EXAMPLES.map((x) => (
            <button key={x} type="button" onClick={() => setQ(x)} className="min-h-11 rounded-(--radius) border border-(--krds-border-gray) px-3 text-left hover:bg-muted">
              {x}
            </button>
          ))}
        </div>
        <Button data-testid="expert-submit" disabled={!q.trim() || m.isPending} onClick={() => m.mutate(q.trim())} className="self-start">
          {m.isPending ? "분석하는 중이에요(30초~1분)" : "분석 요청"}
        </Button>
        {m.isError && <p data-testid="expert-fail">요청을 보내지 못했어요. 다시 시도해 주세요.</p>}
        {m.data && <ResultView r={m.data} q={m.variables ?? q} />}
      </div>
    </details>
  );
}
