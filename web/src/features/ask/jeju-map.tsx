"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getMap } from "@/lib/api";
import { shortNum } from "./views";

// 5단계 색(같은 색의 진하기, SGIS 범례 방식). 강조색 계열 하나만 쓴다.
const SHADES = ["#e8eef9", "#bcd0f3", "#7ea6ea", "#3f78dc", "#1d4fb3"];
const NONE = "#f1f3f5";
// C8: 도심의 작은 동은 눌러 보기 어려워 두 도심은 한 번에 확대해서 볼 수 있게 한다(가운데 좌표와 가로 폭은 viewBox 1000 기준).
const ZOOMS = { jeju: { label: "제주시 도심 확대", cx: 470, cy: 93, w: 110 }, seogwipo: { label: "서귀포 도심 확대", cx: 505, cy: 468, w: 90 } } as const;
const LABEL_PX = 10; // 글자 크기 '보통'(100%)에서 구역 이름이 화면에서 차지하는 높이(px)
type ZoomKey = keyof typeof ZOOMS;
// 자유 확대(사용자 지시 2026-11-12): [+]·[−]·끌기·두 손가락 벌리기. 보는 자리는 가운데 좌표와 배율로 둔다(null = 전체 지도).
type View = { cx: number; cy: number; k: number };
const K_MAX = 12; // 서귀포 도심 확대(가로 90 → 약 11배)가 들어가는 값
const DRAG_PX = 5; // 이보다 적게 움직이면 끌기가 아니라 누르기로 본다
type Dir = "ArrowLeft" | "ArrowRight" | "ArrowUp" | "ArrowDown";

function breaks(vals: number[]) {
  const s = [...vals].sort((a, b) => a - b);
  return [0.2, 0.4, 0.6, 0.8].map((q) => s[Math.min(s.length - 1, Math.floor(q * s.length))]);
}

/** 제주 행정동 43곳 경계 색칠 지도(v3, 타일·API 키 없는 SVG). values가 있으면 5등분으로 칠하고, onPick이 있으면 눌러서 동네를 고른다. */
export function JejuMap({
  values,
  unit,
  highlight = [],
  selected = [],
  onPick,
  label,
  testId = "jeju-map",
}: {
  values?: Record<string, number>;
  unit?: string;
  highlight?: string[];
  selected?: string[];
  onPick?: (dong: string) => void;
  label: string;
  testId?: string;
}) {
  const map = useQuery({ queryKey: ["jeju-map"], queryFn: getMap, staleTime: Infinity });
  const [hover, setHover] = useState<string | null>(null);
  const [view, setView] = useState<View | null>(null);
  const kNow = view?.k ?? 1;
  // 끌기·두 손가락 벌리기에 쓰는 손가락(포인터) 기록. 화면을 다시 그리지 않도록 ref에 둔다.
  const pts = useRef(new Map<number, { x: number; y: number }>());
  const drag = useRef<{ x: number; y: number; cx: number; cy: number } | null>(null);
  const pinch = useRef<{ d: number; k: number; ax: number; ay: number } | null>(null);
  const moved = useRef(false);
  const [stop, setStop] = useState<string | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const cuts = useMemo(() => (values ? breaks(Object.values(values)) : []), [values]);
  // C8: 화면에서 짧은 변이 24px보다 작은 동은 손가락·마우스로 정확히 누를 수 없어 지도에서는 누름 대상에서 빼고, '도심 확대'나 목록으로 고르게 한다.
  const [tiny, setTiny] = useState<Set<string>>(() => new Set());
  const mapData = map.data;
  // C9: 구역 이름 글자는 '화면 설정'의 글자 크기를 따른다. 그림 안의 글자는 그림 배율로 줄어들므로, 화면에서 보이는 크기를 기준으로 거꾸로 계산한다.
  const [w, setW] = useState(0);
  const [scale, setScale] = useState(1);
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const ro = new ResizeObserver(() => setW(svg.getBoundingClientRect().width));
    ro.observe(svg);
    const read = () => setScale((parseFloat(getComputedStyle(document.documentElement).fontSize) || 16) / 16);
    read();
    const mo = new MutationObserver(read);
    mo.observe(document.documentElement, { attributes: true, attributeFilter: ["style"] });
    return () => {
      ro.disconnect();
      mo.disconnect();
    };
  }, [mapData]);
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg || !onPick || !mapData) {
      setTiny((prev) => (prev.size ? new Set() : prev));
      return;
    }
    const calc = () => {
      const px = (svg.getBoundingClientRect().width * kNow) / mapData.viewBox[2];
      const t = new Set<string>();
      svg.querySelectorAll<SVGGraphicsElement>("path[data-dong]").forEach((el) => {
        const b = el.getBBox();
        if (Math.min(b.width, b.height) * px < 24) t.add(el.dataset.dong ?? "");
      });
      setTiny((prev) => (prev.size === t.size && [...t].every((x) => prev.has(x)) ? prev : t));
    };
    calc();
    const ro = new ResizeObserver(calc);
    ro.observe(svg);
    return () => ro.disconnect();
  }, [mapData, onPick, kNow]);
  if (!map.data) return <div className="h-48 rounded-(--radius) bg-muted" aria-hidden />;
  const m = map.data;
  const color = (d: string) => {
    if (!values) return selected.includes(d) ? SHADES[3] : SHADES[0];
    const v = values[d];
    if (v === undefined) return NONE;
    return SHADES[cuts.filter((c) => v > c).length];
  };
  const fmt = (v: number) => `${shortNum(v)}${unit ? (unit === "%" || unit === "%p" ? unit : ` ${unit}`) : ""}`;
  const hv = hover ?? highlight[0] ?? selected[0];
  // 확대 영역: 가로세로 비율을 전체 지도와 같게 두어 화면 높이가 변하지 않는다
  const [X0, Y0, W, H] = m.viewBox;
  const k = kNow; // 확대 배율. 글자·선 굵기를 배율만큼 줄여 화면에서 같은 크기로 보이게 한다
  const z = k > 1;
  // 보는 자리가 지도 밖으로 나가지 않게 가운데 좌표를 지도 안쪽으로 맞춘다
  const fit = (v: View): View | null => {
    const kk = Math.min(K_MAX, Math.max(1, v.k));
    if (kk <= 1.01) return null;
    const hw = W / kk / 2;
    const hh = H / kk / 2;
    return { k: kk, cx: Math.min(X0 + W - hw, Math.max(X0 + hw, v.cx)), cy: Math.min(Y0 + H - hh, Math.max(Y0 + hh, v.cy)) };
  };
  const cur: View = view ?? { cx: X0 + W / 2, cy: Y0 + H / 2, k: 1 };
  const vb = [cur.cx - W / k / 2, cur.cy - H / k / 2, W / k, H / k];
  const preset = (key: ZoomKey): View => ({ cx: ZOOMS[key].cx, cy: ZOOMS[key].cy, k: W / ZOOMS[key].w });
  const same = (a: View | null, b: View | null) => a === b || (!!a && !!b && Math.abs(a.cx - b.cx) < 0.5 && Math.abs(a.cy - b.cy) < 0.5 && Math.abs(a.k - b.k) < 0.01);
  const atPreset = (Object.keys(ZOOMS) as ZoomKey[]).find((key) => same(view, fit(preset(key))));
  // [+]·[−]: 2배씩. 고른(강조한) 동네가 보이는 동안에는 그 동네가 화면의 같은 자리에 머물도록 키우고, 아니면 보는 자리의 가운데를 기준으로 키운다.
  const step = (dir: 1 | -1) => {
    const first = m.dongs.find((d) => d.dong === (selected[0] ?? highlight[0]));
    const seen = first && first.cx >= vb[0] && first.cx <= vb[0] + vb[2] && first.cy >= vb[1] && first.cy <= vb[1] + vb[3];
    const ax = seen ? first.cx : cur.cx;
    const ay = seen ? first.cy : cur.cy;
    const kk = Math.min(K_MAX, Math.max(1, dir > 0 ? k * 2 : k / 2));
    setView(fit({ k: kk, cx: ax - ((ax - vb[0]) / vb[2] - 0.5) * (W / kk), cy: ay - ((ay - vb[1]) / vb[3] - 0.5) * (H / kk) }));
  };
  const onDown = (e: React.PointerEvent<SVGSVGElement>) => {
    pts.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pts.current.size === 1) {
      moved.current = false;
      drag.current = { x: e.clientX, y: e.clientY, cx: cur.cx, cy: cur.cy };
    } else if (pts.current.size === 2) {
      const [a, b] = [...pts.current.values()];
      const r = e.currentTarget.getBoundingClientRect();
      // 두 손가락 가운데가 가리키는 지도 위의 점. 벌리는 동안 이 점이 손가락 아래에 머문다.
      pinch.current = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, k, ax: vb[0] + (((a.x + b.x) / 2 - r.left) / r.width) * vb[2], ay: vb[1] + (((a.y + b.y) / 2 - r.top) / r.height) * vb[3] };
      drag.current = null;
      moved.current = true;
    }
  };
  const onMove = (e: React.PointerEvent<SVGSVGElement>) => {
    if (!pts.current.has(e.pointerId)) return;
    pts.current.set(e.pointerId, { x: e.clientX, y: e.clientY });
    const r = e.currentTarget.getBoundingClientRect();
    if (pts.current.size === 2 && pinch.current) {
      const [a, b] = [...pts.current.values()];
      const p = pinch.current;
      const kk = Math.min(K_MAX, Math.max(1, (p.k * Math.hypot(a.x - b.x, a.y - b.y)) / p.d));
      const fx = ((a.x + b.x) / 2 - r.left) / r.width;
      const fy = ((a.y + b.y) / 2 - r.top) / r.height;
      setView(fit({ k: kk, cx: p.ax - (fx - 0.5) * (W / kk), cy: p.ay - (fy - 0.5) * (H / kk) }));
    } else if (pts.current.size === 1 && drag.current && z) {
      const g = drag.current;
      const dx = e.clientX - g.x;
      const dy = e.clientY - g.y;
      if (!moved.current && Math.hypot(dx, dy) < DRAG_PX) return;
      if (!moved.current) e.currentTarget.setPointerCapture(e.pointerId);
      moved.current = true;
      setView(fit({ k, cx: g.cx - (dx / r.width) * vb[2], cy: g.cy - (dy / r.height) * vb[3] }));
    }
  };
  const onUp = (e: React.PointerEvent<SVGSVGElement>) => {
    pts.current.delete(e.pointerId);
    pinch.current = null;
    const rest = [...pts.current.values()][0];
    drag.current = rest ? { x: rest.x, y: rest.y, cx: cur.cx, cy: cur.cy } : null; // 한 손가락이 남으면 그 자리에서 끌기를 잇는다
  };
  const labelSize = w ? (LABEL_PX * scale * vb[2]) / w : 15 / k; // 그림 안 글자 크기(그림 단위)
  const inView = (d: { cx: number; cy: number }) => d.cx >= vb[0] && d.cx <= vb[0] + vb[2] && d.cy >= vb[1] && d.cy <= vb[1] + vb[3];
  const usable = (d: string) => !tiny.has(d);
  const stopDong = stop && m.dongs.some((d) => d.dong === stop) && usable(stop) ? stop : (selected.find(usable) ?? m.dongs.find((d) => usable(d.dong))?.dong);
  // 방향키: 그 방향에서 가장 가까운 동네로 초점을 옮긴다. 지도 전체는 Tab 정지점 하나다(B5).
  const move = (from: string, key: Dir) => {
    const cur = m.dongs.find((d) => d.dong === from);
    if (!cur) return;
    const horizontal = key === "ArrowLeft" || key === "ArrowRight";
    const sign = key === "ArrowRight" || key === "ArrowDown" ? 1 : -1;
    let best: { dong: string; score: number } | null = null;
    for (const d of m.dongs) {
      if (d.dong === from || (z && !inView(d)) || !usable(d.dong)) continue;
      const along = (horizontal ? d.cx - cur.cx : d.cy - cur.cy) * sign;
      const across = Math.abs(horizontal ? d.cy - cur.cy : d.cx - cur.cx);
      if (along <= 0) continue;
      const score = along + 2 * across;
      if (!best || score < best.score) best = { dong: d.dong, score };
    }
    if (best) {
      setStop(best.dong);
      svgRef.current?.querySelector<SVGElement>(`[data-dong="${best.dong}"]`)?.focus();
    }
  };
  const hoverD = hover ? m.dongs.find((d) => d.dong === hover) : undefined;
  return (
    <figure data-testid={testId} className="flex flex-col gap-2">
      <svg
        ref={svgRef}
        viewBox={vb.join(" ")}
        role={onPick ? "group" : "img"}
        aria-label={label}
        className={"h-auto w-full select-none " + (z ? "cursor-grab" : "")}
        // 전체 지도에서는 한 손가락으로 쪽을 위아래로 넘길 수 있게 두고, 확대한 동안에는 손가락 움직임을 지도가 받는다
        style={{ touchAction: z ? "none" : "pan-y" }}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerCancel={onUp}
        onClickCapture={(e) => {
          // 끌거나 벌린 직후의 누름은 동네 고르기로 보지 않는다
          if (!moved.current) return;
          moved.current = false;
          e.stopPropagation();
          e.preventDefault();
        }}
      >
        <rect x={m.inset.x} y={m.inset.y} width={m.inset.w} height={m.inset.h} fill="none" stroke="#9ca3af" strokeDasharray="4 4" vectorEffect="non-scaling-stroke" />
        <text x={m.inset.x + 4 / k} y={m.inset.y + m.inset.h - 6 / k} fontSize={labelSize * 0.9} fill="#6b7280">
          {m.inset.label}
        </text>
        {m.dongs.map((d) => {
          const strong = highlight.includes(d.dong) || selected.includes(d.dong);
          const v = values?.[d.dong];
          return (
            <path
              key={d.dong}
              d={d.d}
              fill={color(d.dong)}
              stroke={strong ? "#111827" : "#ffffff"}
              strokeWidth={strong ? 3 : 1}
              vectorEffect="non-scaling-stroke"
              data-dong={d.dong}
              tabIndex={onPick && d.dong === stopDong ? 0 : -1}
              role={onPick && usable(d.dong) ? "button" : undefined}
              pointerEvents={onPick && !usable(d.dong) ? "none" : undefined}
              aria-label={`${d.dong}${v !== undefined ? ` ${fmt(v)}` : ""}`}
              aria-pressed={onPick && usable(d.dong) ? selected.includes(d.dong) : undefined}
              onMouseEnter={() => setHover(d.dong)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => {
                setHover(d.dong);
                setStop(d.dong);
              }}
              onBlur={() => setHover(null)}
              onClick={() => onPick?.(d.dong)}
              onKeyDown={(e) => {
                if (!onPick) return;
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  onPick(d.dong);
                } else if (e.key === "ArrowLeft" || e.key === "ArrowRight" || e.key === "ArrowUp" || e.key === "ArrowDown") {
                  e.preventDefault();
                  move(d.dong, e.key);
                }
              }}
              className={onPick && usable(d.dong) ? "cursor-pointer outline-none" : undefined}
            >
              <title>{`${d.dong}${v !== undefined ? ` ${fmt(v)}` : ""}`}</title>
            </path>
          );
        })}
        {/* C1: 올린·초점이 간 동네는 굵은 테두리로 보이고 이름이 붙는다 */}
        {hoverD && <path d={hoverD.d} fill="none" stroke="#0b3fa8" strokeWidth={3} vectorEffect="non-scaling-stroke" pointerEvents="none" />}
        {m.dongs
          .filter((d) => (inView(d) && d.area * k * k > 1500) || highlight.includes(d.dong) || selected.includes(d.dong) || d.dong === hover)
          .map((d) => (
            <text key={d.dong} x={d.cx} y={d.cy} fontSize={labelSize} textAnchor="middle" pointerEvents="none" fill="#111827" stroke="#ffffff" strokeWidth={labelSize / 5} paintOrder="stroke">
              {d.dong}
            </text>
          ))}
      </svg>
      <div className="flex flex-wrap items-center gap-2" data-testid={`${testId}-zoom`}>
        <button type="button" data-testid={`${testId}-zoom-in`} aria-label="지도 확대" disabled={k >= K_MAX} onClick={() => step(1)} className="min-h-11 rounded-(--radius) border border-(--krds-border-gray) px-3 hover:bg-muted disabled:opacity-40">
          + 확대
        </button>
        <button type="button" data-testid={`${testId}-zoom-out`} aria-label="지도 축소" disabled={!z} onClick={() => step(-1)} className="min-h-11 rounded-(--radius) border border-(--krds-border-gray) px-3 hover:bg-muted disabled:opacity-40">
          − 축소
        </button>
        {z && (
          <button type="button" data-testid={`${testId}-zoom-reset`} onClick={() => setView(null)} className="min-h-11 rounded-(--radius) border border-(--krds-border-gray) px-3 hover:bg-muted">
            전체 지도로 돌아가기
          </button>
        )}
        {(Object.keys(ZOOMS) as ZoomKey[]).map((key) => (
          <button
            key={key}
            type="button"
            aria-pressed={atPreset === key}
            onClick={() => setView(fit(preset(key)))}
            className={"min-h-11 rounded-(--radius) border px-3 hover:bg-muted " + (atPreset === key ? "border-(--krds-border-primary) bg-(--krds-surface-primary-subtler) font-semibold" : "border-(--krds-border-gray)")}
          >
            {ZOOMS[key].label}
          </button>
        ))}
        {z && (
          <span data-testid={`${testId}-zoom-level`} aria-live="polite" className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">
            {Math.round(k * 10) / 10}배 · 끌어서 옮길 수 있어요
          </span>
        )}
      </div>
      {onPick && m.dongs.some((d) => tiny.has(d.dong) && inView(d)) && (
        <p data-testid={`${testId}-tiny-hint`} className="text-[length:var(--krds-fs-body-medium)] text-(--krds-text-bolder)">
          작은 동네({m.dongs.filter((d) => tiny.has(d.dong) && inView(d)).length}곳)는 지도에서 누르기 어려워요. [+ 확대]나 '도심 확대'를 누르거나 목록에서 골라 주세요.
        </p>
      )}
      <figcaption className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[length:var(--krds-fs-body-medium)]">
        {hv && (
          <span data-testid={`${testId}-focus`} className="font-semibold">
            {hv}
            {values?.[hv] !== undefined ? `: ${fmt(values[hv])}` : ""}
          </span>
        )}
        {values && (
          <span className="flex flex-wrap items-center gap-1" aria-label="범례(43곳을 5단계로 나눔)">
            {SHADES.map((c, i) => (
              <span key={c} className="flex items-center gap-1">
                <span className="inline-block h-3 w-5 rounded-sm" style={{ background: c }} />
                <span className="text-(--krds-text-bolder)">{i === 0 ? `~${shortNum(cuts[0])}` : i === 4 ? `${shortNum(cuts[3])}~` : `${shortNum(cuts[i - 1])}~${shortNum(cuts[i])}`}</span>
              </span>
            ))}
          </span>
        )}
      </figcaption>
      <p className="text-[length:var(--krds-fs-body-small)] text-(--krds-text-bolder)">경계: 통계청 SGIS(공공누리 1유형), vuski/admdongkor(CC BY 4.0)</p>
    </figure>
  );
}
