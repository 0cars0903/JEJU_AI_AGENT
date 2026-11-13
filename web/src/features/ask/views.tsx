"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { type AskResult, type DataRequest, type DatasetMeta, type View, uploadDataset } from "@/lib/api";
import { JejuMap } from "./jeju-map";
import { sourceList } from "./answer";
import { markLongParts } from "./print-layout";

// 색은 흰 배경 + 강조색 하나, 나머지는 회색 계열(사용자 PPT·화면 규칙과 같은 원칙)
const COLORS = ["var(--krds-element-primary, #256ef4)", "#6b7280", "#a3a3a3", "#d4d4d4", "#374151", "#9ca3af"];

/** 큰 수를 읽기 쉽게: 억·만 단위(축과 툴팁 표시용, 계산은 서버 값 그대로). */
export function shortNum(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "-";
  const a = Math.abs(v);
  if (a >= 1e8) return `${(v / 1e8).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}억`;
  if (a >= 1e4) return `${(v / 1e4).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}만`;
  return v.toLocaleString("ko-KR", { maximumFractionDigits: 1 });
}

/** A10: 그래프·표의 값 단위. 서버가 view.unit을 주면 그대로 쓰고, 없으면 이름과 크기로 알아낸다. 금액은 본문처럼 억 원·만 원으로 보여 준다. */
type UnitInfo = { kind: "money" | "pct" | "index" | "none"; div: number; label: string };
function unitInfo(vals: number[], unit: string | undefined, names: string[], id: string, definition?: string | null): UnitInfo {
  const max = vals.reduce((m, x) => Math.max(m, Math.abs(x)), 0);
  if (unit === "%" || unit === "%p" || names.some((n) => /\(%p?\)/.test(n))) return { kind: "pct", div: 1, label: unit === "%p" ? "%p" : "%" };
  if (unit === "지수" || id === "index" || /지수/.test(definition ?? "")) return { kind: "index", div: 1, label: "지수" };
  if (unit === "원" || (!unit && max >= 1e6)) {
    if (max >= 1e8) return { kind: "money", div: 1e8, label: "억 원" };
    if (max >= 1e4) return { kind: "money", div: 1e4, label: "만 원" };
    return { kind: "money", div: 1, label: "원" };
  }
  return { kind: "none", div: 1, label: unit ?? "" };
}
function viewUnit(v: View): UnitInfo {
  const vals = v.kind === "map" ? Object.values(v.values ?? {}) : v.series.flatMap((s) => s.points.map((p) => p[1]).filter((x): x is number => typeof x === "number"));
  const names = v.kind === "map" ? [] : [...v.series.map((s) => s.name), ...v.series.flatMap((s) => s.points.map((p) => String(p[0])))];
  return unitInfo(vals, v.unit, names, v.id, v.definition);
}
const fmtVal = (x: number | null | undefined, u: UnitInfo) =>
  x === null || x === undefined || Number.isNaN(x) ? "-" : (x / u.div).toLocaleString("ko-KR", { maximumFractionDigits: 1 });

function rows(v: View) {
  const xs: (string | number)[] = [];
  for (const s of v.series) for (const [x] of s.points) if (!xs.includes(x)) xs.push(x);
  return xs.map((x) => {
    const r: Record<string, string | number | null> = { x };
    for (const s of v.series) r[s.name] = s.points.find((p) => p[0] === x)?.[1] ?? null;
    return r;
  });
}

/** 나눠 보기 차트 하나. width를 주면 고정 크기(인쇄용 보고서: 말풍선 없음), 없으면 화면 폭에 맞춘다. */
/** 점그래프(기법 분석의 상관·회귀, 2026-11-13): 점마다 이름을 말풍선에 보인다. 축 값은 짧은 숫자로. */
function ScatterView({ v, width }: { v: View; width?: number }) {
  const pts = (v.series[0]?.points ?? []).map((p, i) => ({ x: Number(p[0]), y: p[1], name: v.names?.[i] ?? String(p[0]) }));
  const [ax, ay] = v.axes ?? ["가로", "세로"];
  const chart = (
    <ScatterChart width={width} height={280} margin={{ top: 16, right: 28, bottom: 24, left: 8 }}>
      <CartesianGrid strokeDasharray="3 3" />
      <XAxis dataKey="x" type="number" name={ax} tickFormatter={(x: number) => shortNum(x)} tick={{ fontSize: 13 }} domain={["auto", "auto"]} label={{ value: ax, position: "insideBottom", offset: -12 }} />
      <YAxis dataKey="y" type="number" name={ay} tickFormatter={(x: number) => shortNum(x)} tick={{ fontSize: 13 }} width={56} domain={["auto", "auto"]} />
      {!width && (
        <Tooltip
          content={({ payload }) => {
            const d = payload?.[0]?.payload as { x: number; y: number; name: string } | undefined;
            return d ? (
              <div className="rounded border bg-background px-2 py-1 text-[length:var(--krds-fs-body-small)]">
                <strong>{d.name}</strong> · {ax} {shortNum(d.x)} · {ay} {shortNum(d.y)}
              </div>
            ) : null;
          }}
        />
      )}
      <Scatter data={pts} fill={COLORS[0]} isAnimationActive={false} />
    </ScatterChart>
  );
  return (
    <div>
      <p data-testid="chart-unit" className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">
        가로: {ax} · 세로: {ay}
      </p>
      {width ? chart : <ResponsiveContainer width="100%" height={280}>{chart}</ResponsiveContainer>}
    </div>
  );
}

export function ViewChart({ v, width }: { v: View; width?: number }) {
  if (v.kind === "scatter") return <ScatterView v={v} width={width} />;
  const data = rows(v);
  const many = v.series.length > 1;
  const u = viewUnit(v);
  const margin = { top: width && many ? 44 : 16, right: 28, bottom: 8, left: 8 }; // 오른쪽 끝 눈금 글자(예: 5년)가 잘리지 않게 글자 반 폭보다 넓게(문서 23 H2) // 인쇄용은 범례 자리를 위쪽 여백으로 미리 잡는다(숨긴 채 그려져 범례 높이를 재지 못함)
  const tick = (x: number) => fmtVal(x, u);
  const tip = (val: unknown) => `${fmtVal(Number(val), u)}${u.label ? ` ${u.label}` : ""}`;
  const inner =
    v.kind === "bar" ? (
      <BarChart data={data} width={width} height={260} margin={margin}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="x" tick={{ fontSize: 13 }} interval="preserveStartEnd" />
        <YAxis tickFormatter={tick} tick={{ fontSize: 13 }} width={56} />
        {!width && <Tooltip formatter={tip} />}
        {many && (width ? <Legend verticalAlign="top" wrapperStyle={{ top: 4 }} /> : <Legend />)}
        {v.series.map((s, i) => (
          <Bar key={s.name} dataKey={s.name} fill={COLORS[i % COLORS.length]} isAnimationActive={false} />
        ))}
      </BarChart>
    ) : (
      <LineChart data={data} width={width} height={260} margin={margin}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="x" tick={{ fontSize: 13 }} interval="preserveStartEnd" minTickGap={24} />
        <YAxis tickFormatter={tick} tick={{ fontSize: 13 }} width={56} />
        {!width && <Tooltip formatter={tip} />}
        {many && (width ? <Legend verticalAlign="top" wrapperStyle={{ top: 4 }} /> : <Legend />)}
        {v.series.map((s, i) => (
          <Line key={s.name} dataKey={s.name} stroke={COLORS[i % COLORS.length]} strokeWidth={i === 0 ? 3 : 2} dot={false} connectNulls isAnimationActive={false} />
        ))}
      </LineChart>
    );
  return (
    <div>
      {u.label && (
        <p data-testid="chart-unit" className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">
          세로 눈금 단위: {u.label}
        </p>
      )}
      {width ? inner : <ResponsiveContainer width="100%" height={260}>{inner}</ResponsiveContainer>}
    </div>
  );
}

/** 패턴 F: 같은 값을 표로(그래프·지도와 같은 숫자, 같은 단위). */
function ViewTable({ v }: { v: View }) {
  const u = viewUnit(v);
  const unitNote = u.label ? <p className="mb-1 text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">단위: {u.label}</p> : null;
  if (v.kind === "map") {
    const rs = Object.entries(v.values ?? {}).sort((a, b) => b[1] - a[1]);
    return (
      <div className="max-h-96 overflow-auto">
        {unitNote}
        <table data-testid="view-table" className="w-full text-left">
          <thead><tr className="border-b"><th className="py-1">순위</th><th>동네</th><th className="text-right">값{u.label ? `(${u.label})` : ""}</th></tr></thead>
          <tbody>{rs.map(([d, x], i) => <tr key={d} className={v.highlight?.includes(d) ? "border-b font-bold" : "border-b"}><td className="py-1">{i + 1}</td><td>{d}</td><td className="text-right">{fmtVal(x, u)}</td></tr>)}</tbody>
        </table>
      </div>
    );
  }
  if (v.kind === "scatter") {
    const [ax, ay] = v.axes ?? ["가로", "세로"];
    return (
      <div className="max-h-96 overflow-auto">
        <table data-testid="view-table" className="w-full text-left">
          <thead><tr className="border-b"><th className="py-1">이름</th><th className="text-right">{ax}</th><th className="text-right">{ay}</th></tr></thead>
          <tbody>{(v.series[0]?.points ?? []).map((p, i) => <tr key={i} className="border-b"><td className="py-1">{v.names?.[i] ?? p[0]}</td><td className="text-right">{shortNum(Number(p[0]))}</td><td className="text-right">{shortNum(Number(p[1]))}</td></tr>)}</tbody>
        </table>
      </div>
    );
  }
  const data = rows(v);
  return (
    <div className="max-h-96 overflow-auto">
      {unitNote}
      <table data-testid="view-table" className="w-full text-left">
        <thead><tr className="border-b"><th className="py-1">{v.x === "ym" ? "월" : v.x === "year" ? "연도" : "항목"}</th>{v.series.map((s) => <th key={s.name} className="text-right">{s.name}</th>)}</tr></thead>
        <tbody>{data.map((r) => <tr key={String(r.x)} className="border-b"><td className="py-1">{r.x}</td>{v.series.map((s) => <td key={s.name} className="text-right">{fmtVal(r[s.name] as number | null, u)}</td>)}</tr>)}</tbody>
      </table>
    </div>
  );
}

/** 나눠 보기: 칩 기본 3개 + 더 보기. 칩마다 한 줄 요약. 계산은 서버가 미리 했으므로 칩을 눌러도 기다림이 없다. */
export function Views({ views, n }: { views: View[]; n: number }) {
  const [sel, setSel] = useState(views[0]?.id);
  const [more, setMore] = useState(false);
  const [asTable, setAsTable] = useState(false);
  if (!views.length) return null;
  const shown = more ? views : views.slice(0, n);
  const cur = views.find((v) => v.id === sel) ?? views[0];
  return (
    <section data-testid="views" aria-label="나눠 보기" className="flex flex-col gap-3">
      <h3>나눠 보기</h3>
      <div className="flex flex-wrap items-center gap-2" role="tablist">
        {shown.map((v) => (
          <button
            key={v.id}
            type="button"
            role="tab"
            aria-selected={v.id === cur.id}
            data-testid={`view-${v.id}`}
            onClick={() => setSel(v.id)}
            className={
              v.id === cur.id
                ? "min-h-11 rounded-(--radius) border border-(--krds-border-primary) bg-primary px-3 font-semibold text-primary-foreground"
                : "min-h-11 rounded-(--radius) border border-(--krds-border-gray) bg-background px-3 hover:bg-muted"
            }
          >
            {v.label}
          </button>
        ))}
        {views.length > n && (
          <button type="button" data-testid="views-more" onClick={() => setMore(!more)} className="min-h-11 rounded-(--radius) px-3 underline hover:bg-muted">
            {more ? "접기" : `더 보기(${views.length - n})`}
          </button>
        )}
        {/* B6: 표로 보기는 보기 탭과 같은 줄에 둔다 */}
        <button type="button" data-testid="view-as-table" onClick={() => setAsTable(!asTable)} className="ml-auto min-h-11 rounded-(--radius) border border-(--krds-border-gray) px-3 hover:bg-muted">
          {asTable ? (cur.kind === "map" ? "지도로 보기" : "그래프로 보기") : "표로 보기"}
        </button>
      </div>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="flex flex-col gap-1">
          <p className="text-[length:var(--krds-fs-body-large)] font-semibold">{cur.summary}</p>
          {cur.definition && <p data-testid="view-definition" className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">{cur.definition}</p>}
        </div>
      </div>
      <div className="w-full" data-testid="view-chart">
        {asTable ? <ViewTable v={cur} /> : cur.kind === "map" ? <JejuMap values={cur.values} unit={cur.unit} highlight={cur.highlight} label={cur.label} testId="view-jeju-map" /> : <ViewChart v={cur} />}
      </div>
    </section>
  );
}

/** 클립보드에 복사. 막힌 환경(주소가 https가 아닌 경우 등)에서는 임시 입력 칸으로 한 번 더 시도한다. */
export async function copyText(value: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(value);
    return true;
  } catch {
    try {
      const t = document.createElement("textarea");
      t.value = value;
      t.setAttribute("readonly", "");
      t.style.position = "fixed";
      t.style.opacity = "0";
      document.body.appendChild(t);
      t.select();
      const ok = document.execCommand("copy");
      t.remove();
      return ok;
    } catch {
      return false;
    }
  }
}

function CopyButton({ value }: { value: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      size="sm"
      variant="outline"
      onClick={async () => {
        if (await copyText(value)) {
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        }
      }}
    >
      {done ? "복사했어요" : "복사"}
    </Button>
  );
}

/** F9 ④⑤: 센터에서 받은 엑셀 파일(CSV) 넣기(파일 선택·끌어다 놓기) → 칸 이름으로 알아본 결과 → ⑥ 이 자료로 다시 계산. q가 없으면 조건 확인 없이 파일만 받는다(A7). */
export function CenterUpload({ q, onUse }: { q?: DataRequest; onUse: (meta: DatasetMeta) => void }) {
  const [meta, setMeta] = useState<DatasetMeta | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const dong = q?.query?.find((f) => f.field === "법정동")?.value;
  const biz = q?.query?.find((f) => f.field === "업종명")?.value;
  const send = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    setErr(null);
    setMeta(null);
    try {
      setMeta(await uploadDataset(file, { dong: dong && dong !== "전체" ? dong : undefined, biz }));
    } catch (e) {
      setErr(e instanceof Error ? e.message : "파일을 읽지 못했습니다.");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="flex flex-col gap-2">
      <label
        data-testid="center-drop"
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          e.preventDefault();
          setOver(false);
          send(e.dataTransfer.files?.[0]);
        }}
        className={
          over
            ? "flex min-h-20 cursor-pointer flex-col items-start justify-center gap-1 rounded-(--radius) border-2 border-dashed border-(--krds-border-primary) bg-(--krds-surface-primary-subtler) p-4 text-left"
            : "flex min-h-20 cursor-pointer flex-col items-start justify-center gap-1 rounded-(--radius) border-2 border-dashed border-(--krds-border-gray) p-4 text-left has-focus-visible:outline-2 has-focus-visible:outline-(--krds-border-primary)"
        }
      >
        <span className="font-semibold">센터에서 받은 파일(CSV)을 여기에 끌어다 놓거나, 눌러서 고르세요</span>
        <span className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">파일은 이 PC 안에서만 계산에 쓰고 하루 뒤 지웁니다. 답에는 집계 결과만 나옵니다.</span>
        <input data-testid="center-file" type="file" accept=".csv,text/csv" className="sr-only" onChange={(e) => send(e.target.files?.[0])} />
      </label>
      {busy && <p role="status">파일을 읽고 있어요…</p>}
      {err && (
        <p role="alert" data-testid="center-error" className="font-semibold text-(--krds-text-danger)">
          {err}
        </p>
      )}
      {meta && (
        <div data-testid="center-meta" className="flex flex-col items-start gap-2 rounded-(--radius) bg-(--krds-surface-gray-subtler) p-3">
          <p>
            알아본 자료: <strong>{meta.label}</strong> · {meta.rows.toLocaleString("ko-KR")}줄 · {meta.period[0]}~{meta.period[1]} · 동네 {meta.dongs.length}곳
          </p>
          {meta.problems.length > 0 && (
            <ul className="list-disc pl-5 text-(--krds-text-danger)">
              {meta.problems.map((p) => (
                <li key={p}>{p}</li>
              ))}
            </ul>
          )}
          <Button data-testid="center-use" disabled={meta.problems.length > 0} onClick={() => onUse(meta)}>
            이 자료로 다시 계산
          </Button>
        </div>
      )}
    </div>
  );
}

/** 자료 요청 카드(v3 C·D): 파일 자료 갱신 요청, 센터 자료 조회 조건(F9, 칸마다 복사)과 CSV 넣기. */
export function Requests({ items, onCenter }: { items: DataRequest[]; onCenter?: (meta: DatasetMeta) => void }) {
  if (!items.length) return null;
  return (
    <section data-testid="requests" aria-label="자료 요청" className="flex flex-col gap-3">
      {items.map((q) => (
        <div key={q.title} id={`request-${q.kind}`} data-testid={`request-${q.kind}`} className="flex scroll-mt-24 flex-col gap-2 rounded-(--radius) border border-(--krds-border-gray) p-4">
          <h3>{q.title}</h3>
          <p>{q.why}</p>
          <p className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">
            자료: {q.data} · 받는 곳: {q.where}
          </p>
          {q.steps && (
            <ol className="list-decimal pl-6">
              {q.steps.map((s) => (
                <li key={s}>{s}</li>
              ))}
            </ol>
          )}
          {q.query && (
            <ol className="flex flex-col gap-2">
              {q.query.map((f, i) => (
                <li key={f.field} className="flex flex-wrap items-center gap-2">
                  <span className="min-w-24 font-semibold">
                    {i + 1}. {f.field}
                  </span>
                  <code className="rounded bg-muted px-2 py-1">{f.value}</code>
                  <CopyButton value={f.value} />
                </li>
              ))}
            </ol>
          )}
          {q.kind === "center" && onCenter && <CenterUpload q={q} onUse={onCenter} />}
        </div>
      ))}
    </section>
  );
}

/** 동네 비교 표의 인쇄본(문서 23 H2: 화면에만 있고 PDF에서 빠지던 표) */
function ReportCompare({ c }: { c: NonNullable<NonNullable<AskResult["answer"]>["compare"]> }) {
  return (
    <div data-testid="report-compare">
      <h2>
        {c.dongs[0]}·{c.dongs[1]} 비교
      </h2>
      <table className="report-table">
        <thead>
          <tr>
            <th>항목</th>
            <th>{c.dongs[0]}</th>
            <th>{c.dongs[1]}</th>
            <th>제주 중간값</th>
            <th>판정</th>
          </tr>
        </thead>
        {c.sections.map((sec) => (
          <tbody key={sec.id}>
            <tr>
              <th colSpan={5}>{sec.title}</th>
            </tr>
            {sec.rows.map((row) => (
              <tr key={row.label}>
                <td>{row.label}</td>
                <td>{row.texts[0]}</td>
                <td>{row.texts[1]}</td>
                <td>{row.texts[2]}</td>
                <td>{row.verdict}</td>
              </tr>
            ))}
          </tbody>
        ))}
      </table>
      <p>{c.rule}</p>
    </div>
  );
}

/** F7 분석 보고서: 인쇄할 때만 보이는 정리본(질문·이해한 내용·3블록·차트 기본 3개·한계·출처·생성 시각). 브라우저 인쇄에서 PDF로 저장한다.
 *  화면 맨 바깥(body)에 붙여, 인쇄할 때 나머지 화면을 완전히 빼고 이 정리본만 찍는다(B7: 첫 쪽 위 빈칸·쪽수 늘어남 해소). */
export function Report({ r }: { r: AskResult }) {
  const [host, setHost] = useState<HTMLElement | null>(null);
  useEffect(() => setHost(document.body), []);
  const rootRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const f = () => markLongParts(rootRef.current); // 쪽 나눔 규칙 2: 한 쪽보다 긴 장은 새 쪽에서(print-layout.ts)
    window.addEventListener("beforeprint", f);
    return () => window.removeEventListener("beforeprint", f);
  }, []);
  const a = r.answer;
  if (!a || !host) return null;
  const now = new Date().toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
  const lines = a.blocks.flatMap((b) => b.lines);
  const srcs = sourceList(a); // 화면과 같은 출처 번호(문서 23 P3)
  const mark = (name?: string | null) => {
    const n = name ? srcs.findIndex((x) => x.name === name) + 1 : 0;
    return n > 0 ? ` [${n}]` : "";
  };
  const sources = Array.from(new Set(lines.map((l) => l.source).filter(Boolean))) as string[];
  // 문서 21 3.2절 구성: 줄의 종류(kind)로 절을 나눈다. 해당 줄이 없는 절은 찍지 않는다.
  const SECTION: Record<string, string> = { forecast: "next", salesfc: "next", reference: "next", anomaly: "next", trend: "now", decomp: "now", survival: "surv", similar: "near", season: "near", rain: "rain" };
  const sec = (l: (typeof lines)[number]) => (l.block === "guide" ? "guide" : (l.kind && SECTION[l.kind]) || (l.block === "facts" ? "now" : "etc"));
  const pick = (id: string) => lines.filter((l) => sec(l) === id);
  const CHART: Record<string, string> = { survcurve: "surv", validation: "next" };
  const shown = a.views.filter((v, i) => i < a.default_views || CHART[v.id]);
  const charts = (id: string) =>
    shown
      .filter((v) => (CHART[v.id] ?? "now") === id)
      .map((v) => (
        <div key={v.id} className={v.kind === "map" ? "report-chart report-map" : "report-chart"}>
          <h3>
            {v.label} — {v.summary}
          </h3>
          {v.kind === "map" ? <JejuMap values={v.values} unit={v.unit} highlight={v.highlight} label={v.label} testId="report-map" /> : <ViewChart v={v} width={640} />}
        </div>
      ));
  const part = (id: string, title: string) => {
    const ls = pick(id);
    const cs = charts(id);
    if (!ls.length && !cs.length) return null;
    return (
      <div key={id} data-testid={`report-${id}`} className="report-part">
        <h2>{title}</h2>
        <ul>
          {ls.map((l, i) => (
            <li key={i}>
              <span className="report-tag">{l.tag}</span>
              {l.text}
              {mark(l.source)}
            </li>
          ))}
        </ul>
        {cs.length > 0 && <div className="report-charts">{cs}</div>}
      </div>
    );
  };
  // 부록 B: 계산식이 붙은 출처 이름(예: '카드 소비(매출 ÷ 결제 건수)')은 자료 이름으로 줄여 한 번만 적는다
  const base = (x: string) => x.replace(/\(.*$/, "").replace(/ 기록$/, "").trim();
  const asOf = new Map<string, string>();
  for (const f of a.freshness) if (!asOf.has(base(f.source))) asOf.set(base(f.source), f.as_of);
  const named = new Map<string, string>(); // 같은 자료는 제공처가 붙은 이름 하나로
  for (const x of sources) if (!named.has(base(x)) || /포털|허브|행정안전부/.test(x)) named.set(base(x), /÷|−|합계|계산/.test(x) ? base(x) : x);
  const dataList = Array.from(named.entries());
  const guide = a.blocks.find((b) => b.id === "guide");
  const limits = r.card?.limits ?? [];
  const center = a.requests.filter((q) => q.kind === "center");
  return createPortal(
    <div ref={rootRef} className="print-only" data-testid="report" aria-hidden>
      <h1>제주 상권 EDA 보고서</h1>
      <p>질문: {r.question}</p>
      {r.understood && <p>{r.understood.text}</p>}
      {(r.understood?.notes ?? []).map((n) => (
        <p key={n}>{n}</p>
      ))}
      <h2>한눈에</h2>
      {a.conclusion.tag && <span className="report-tag">{a.conclusion.tag}</span>}
      <p>
        <strong>{a.conclusion.text}</strong>
        {mark(a.conclusion.source)}
      </p>
      {a.summary && (
        // 문서 23 H3: 첫 쪽은 화면과 같은 5칸 요약. 줄 목록은 뒤쪽 절로 보낸다
        <table className="report-table report-summary" data-testid="report-summary">
          <thead>
            <tr>
              {a.summary.map((c) => (
                <th key={c.key}>
                  {c.label} · {c.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            <tr>
              {a.summary.map((c) => (
                <td key={c.key}>
                  <strong>{c.value}</strong>
                  <br />
                  {c.level} · {c.note}
                  {c.sub ? (
                    <>
                      <br />
                      {c.sub}
                    </>
                  ) : null}
                </td>
              ))}
            </tr>
          </tbody>
        </table>
      )}
      {a.compare && <ReportCompare c={a.compare} />}
      {guide && (
        <div data-testid="report-guide" className="report-part">
          {a.summary && <h2>판단할 때 볼 것</h2>}
          <ul>
            {guide.lines.map((l, i) => (
              <li key={i}>
                {l.text}
                {mark(l.source)}
              </li>
            ))}
          </ul>
          {guide.closing && <p>{guide.closing}</p>}
        </div>
      )}
      {part("now", "지금 상태")}
      {part("etc", "분석")}
      {part("next", "앞으로")}
      {part("surv", "업종 생존")}
      {part("near", "비슷한 동네와 계절")}
      {part("rain", "날씨")}
      {(limits.length > 0 || center.length > 0 || (a.gaps?.length ?? 0) > 0) && (
        <div data-testid="report-limits" className="report-part">
          <h2>알 수 있는 것과 없는 것</h2>
          <ul>
            {(a.gaps ?? []).map((g) => (
              <li key={g.what}>
                {g.what}: {g.why} 확인할 곳: {g.where}
              </li>
            ))}
            {limits.map((x) => (
              <li key={x}>{x}</li>
            ))}
            {center.map((q) => (
              <li key={q.title}>
                센터 자료가 있으면 볼 수 있어요: {q.title} — {q.why}
              </li>
            ))}
          </ul>
        </div>
      )}
      {(a.methods?.length ?? 0) > 0 && (
        <div data-testid="report-methods" className="report-part report-appendix">
          <table className="report-table report-methods">
            <thead>
              <tr>
                <th colSpan={4} className="report-caption">
                  <h2>부록 A. 방법과 검증</h2>
                </th>
              </tr>
              <tr>
                <th>모델</th>
                <th>방법</th>
                <th>검증 방식과 결과</th>
                <th>쓸 수 없는 경우</th>
              </tr>
            </thead>
            <tbody>
              {a.methods!.map((m) => (
                <tr key={m.kind}>
                  <th>{m.title}</th>
                  <td>{m.how}</td>
                  <td>
                    {m.check} {m.result}
                  </td>
                  <td>{m.limit}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {/* 첫 부록만 새 쪽에서 시작한다(부록 B만 몇 줄 남은 쪽을 따로 쓰지 않게) */}
      <div data-testid="report-sources" className={(a.methods?.length ?? 0) > 0 ? "report-part" : "report-part report-appendix"}>
        <h2>부록 B. 자료 목록과 기준 시점</h2>
        <ol className="report-srcs">
          {srcs.map((x, i) => (
            <li key={x.name}>
              [{i + 1}] {x.name}
              {x.as_of ? ` · 기준 ${x.as_of}` : ""}
            </li>
          ))}
        </ol>
        <table className="report-table">
          <thead>
            <tr>
              <th>자료</th>
              <th>기준 시점</th>
            </tr>
          </thead>
          <tbody>
            {dataList.map(([k, name]) => (
              <tr key={k}>
                <td>{name}</td>
                <td>{asOf.get(k) ?? "답의 해당 줄에 적음"}</td>
              </tr>
            ))}
          </tbody>
        </table>
        <p>
          생성 {now} · 제주 상권 EDA Agent
        </p>
      </div>
    </div>,
    host,
  );
}
