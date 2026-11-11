"use client";

import { useState } from "react";
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Button } from "@/components/ui/button";
import { type AskResult, type DataRequest, type DatasetMeta, type View, uploadDataset } from "@/lib/api";

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

function rows(v: View) {
  const xs: (string | number)[] = [];
  for (const s of v.series) for (const [x] of s.points) if (!xs.includes(x)) xs.push(x);
  return xs.map((x) => {
    const r: Record<string, string | number | null> = { x };
    for (const s of v.series) r[s.name] = s.points.find((p) => p[0] === x)?.[1] ?? null;
    return r;
  });
}

/** 나눠 보기 차트 하나. width를 주면 고정 크기(인쇄용 보고서), 없으면 화면 폭에 맞춘다. */
export function ViewChart({ v, width }: { v: View; width?: number }) {
  const data = rows(v);
  const many = v.series.length > 1;
  const inner =
    v.kind === "bar" ? (
      <BarChart data={data} width={width} height={260} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="x" tick={{ fontSize: 13 }} interval="preserveStartEnd" />
        <YAxis tickFormatter={shortNum} tick={{ fontSize: 13 }} width={56} />
        <Tooltip formatter={(val) => shortNum(Number(val))} />
        {many && <Legend />}
        {v.series.map((s, i) => (
          <Bar key={s.name} dataKey={s.name} fill={COLORS[i % COLORS.length]} isAnimationActive={false} />
        ))}
      </BarChart>
    ) : (
      <LineChart data={data} width={width} height={260} margin={{ top: 8, right: 8, bottom: 8, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" vertical={false} />
        <XAxis dataKey="x" tick={{ fontSize: 13 }} interval="preserveStartEnd" minTickGap={24} />
        <YAxis tickFormatter={shortNum} tick={{ fontSize: 13 }} width={56} />
        <Tooltip formatter={(val) => shortNum(Number(val))} />
        {many && <Legend />}
        {v.series.map((s, i) => (
          <Line key={s.name} dataKey={s.name} stroke={COLORS[i % COLORS.length]} strokeWidth={i === 0 ? 3 : 2} dot={false} connectNulls isAnimationActive={false} />
        ))}
      </LineChart>
    );
  return width ? inner : <ResponsiveContainer width="100%" height={260}>{inner}</ResponsiveContainer>;
}

/** 나눠 보기: 칩 기본 3개 + 더 보기. 칩마다 한 줄 요약. 계산은 서버가 미리 했으므로 칩을 눌러도 기다림이 없다. */
export function Views({ views, n }: { views: View[]; n: number }) {
  const [sel, setSel] = useState(views[0]?.id);
  const [more, setMore] = useState(false);
  if (!views.length) return null;
  const shown = more ? views : views.slice(0, n);
  const cur = views.find((v) => v.id === sel) ?? views[0];
  return (
    <section data-testid="views" aria-label="나눠 보기" className="flex flex-col gap-3">
      <h3>나눠 보기</h3>
      <div className="flex flex-wrap gap-2" role="tablist">
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
          <button type="button" data-testid="views-more" onClick={() => setMore(!more)} className="min-h-11 px-2 underline">
            {more ? "접기" : `더 보기(${views.length - n})`}
          </button>
        )}
      </div>
      <p className="text-[length:var(--krds-fs-body-medium)]">{cur.summary}</p>
      <div className="w-full" data-testid="view-chart">
        <ViewChart v={cur} />
      </div>
    </section>
  );
}

function CopyButton({ value }: { value: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button
      size="sm"
      variant="outline"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setDone(true);
          setTimeout(() => setDone(false), 1500);
        } catch {
          /* 복사가 막힌 환경: 값은 화면에 그대로 보인다 */
        }
      }}
    >
      {done ? "복사됨" : "복사"}
    </Button>
  );
}

/** F9 ④⑤: 센터에서 받은 CSV 넣기(파일 선택·끌어다 놓기) → 칸 이름으로 알아본 결과 → ⑥ 이 자료로 다시 계산 */
function CenterUpload({ q, onUse }: { q: DataRequest; onUse: (id: string) => void }) {
  const [meta, setMeta] = useState<DatasetMeta | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [over, setOver] = useState(false);
  const dong = q.query?.find((f) => f.field === "법정동")?.value;
  const biz = q.query?.find((f) => f.field === "업종명")?.value;
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
            ? "flex min-h-20 cursor-pointer flex-col items-center justify-center gap-1 rounded-(--radius) border-2 border-dashed border-(--krds-border-primary) bg-(--krds-surface-primary-subtler) p-4 text-center"
            : "flex min-h-20 cursor-pointer flex-col items-center justify-center gap-1 rounded-(--radius) border-2 border-dashed border-(--krds-border-gray) p-4 text-center"
        }
      >
        <span className="font-semibold">센터에서 받은 CSV를 여기에 끌어다 놓거나 눌러서 고르세요</span>
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
        <div data-testid="center-meta" className="flex flex-col gap-2 rounded-(--radius) bg-(--krds-surface-gray-subtler) p-3">
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
          <Button data-testid="center-use" className="w-fit" disabled={meta.problems.length > 0} onClick={() => onUse(meta.id)}>
            이 자료로 다시 계산
          </Button>
        </div>
      )}
    </div>
  );
}

/** 자료 요청 카드(v3 C·D): 파일 자료 갱신 요청, 센터 자료 조회 조건(F9, 칸마다 복사)과 CSV 넣기. */
export function Requests({ items, onCenter }: { items: DataRequest[]; onCenter?: (id: string) => void }) {
  if (!items.length) return null;
  return (
    <section data-testid="requests" aria-label="자료 요청" className="flex flex-col gap-3">
      {items.map((q) => (
        <div key={q.title} data-testid={`request-${q.kind}`} className="flex flex-col gap-2 rounded-(--radius) border border-(--krds-border-gray) p-4">
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

/** F7 분석 보고서: 인쇄할 때만 보이는 정리본(질문·이해한 내용·3블록·차트 기본 3개·한계·출처·생성 시각). 브라우저 인쇄에서 PDF로 저장한다. */
export function Report({ r }: { r: AskResult }) {
  const a = r.answer;
  if (!a) return null;
  const now = new Date().toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
  const sources = Array.from(new Set(a.blocks.flatMap((b) => b.lines.map((l) => l.source).filter(Boolean)))) as string[];
  return (
    <div className="print-only" data-testid="report" aria-hidden>
      <h1>제주 상권 EDA 보고서</h1>
      <p>질문: {r.question}</p>
      {r.understood && <p>{r.understood.text}</p>}
      <h2>결론</h2>
      <p>
        <strong>{a.conclusion.text}</strong>
        {a.conclusion.tag ? ` [${a.conclusion.tag}]` : ""}
      </p>
      {a.blocks.map((b) => (
        <div key={b.id}>
          <h2>{b.title}</h2>
          <ul>
            {b.lines.map((l, i) => (
              <li key={i}>
                [{l.tag}] {l.text}
                {l.source ? ` (${l.source})` : ""}
              </li>
            ))}
          </ul>
          {b.closing && <p>{b.closing}</p>}
        </div>
      ))}
      {a.views.slice(0, a.default_views).map((v) => (
        <div key={v.id} className="report-chart">
          <h3>
            {v.label} — {v.summary}
          </h3>
          <ViewChart v={v} width={640} />
        </div>
      ))}
      {(r.card?.limits?.length ?? 0) > 0 && (
        <>
          <h2>한계</h2>
          <ul>{r.card!.limits.map((x) => <li key={x}>{x}</li>)}</ul>
        </>
      )}
      <h2>출처</h2>
      <ul>{sources.map((s) => <li key={s}>{s}</li>)}</ul>
      <p>
        자료 기준: {a.freshness.map((f) => `${f.source} ${f.as_of}`).join(" · ") || "-"} · 생성 {now} · 제주 상권 EDA Agent
      </p>
    </div>
  );
}
