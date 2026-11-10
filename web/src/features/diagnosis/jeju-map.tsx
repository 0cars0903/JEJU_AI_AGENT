"use client";

import { useMemo, useState } from "react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import type { MapData } from "@/lib/api";
import { formatMetric } from "@/lib/content";

/**
 * 타일 없는 지도: 점포 격자(회색)와 동네 원(색)만 SVG로 그려 인터넷 없이 동작한다.
 * 위치는 점포 좌표의 중앙값이고 경계가 아니다. 추자면은 멀리 떨어져 있어 위치를 옮겨 그리고 점선으로 표시한다.
 */
const LON0 = 126.12;
const LAT0 = 33.6;
const K = 1000;
const COS = Math.cos((33.4 * Math.PI) / 180);
const CHUJA_LAT = 33.7;
const CHUJA_SHIFT = 0.4;

function project(lon: number, lat: number): [number, number] {
  const shifted = lat > CHUJA_LAT ? lat - CHUJA_SHIFT : lat;
  return [(lon - LON0) * COS * K, (LAT0 - shifted) * K];
}

const FULL = [0, 0, 720, 480] as const;
const JEJU_CITY = ["건입동", "도두동", "봉개동", "삼도1동", "삼도2동", "삼양동", "아라동", "연동", "오라동", "외도동", "용담1동", "용담2동", "이도1동", "이도2동", "이호동", "일도1동", "일도2동", "노형동", "화북동"];
const SEOGWIPO_CITY = ["대륜동", "대천동", "동홍동", "서홍동", "송산동", "영천동", "예래동", "정방동", "중문동", "중앙동", "천지동", "효돈동"];
type Box = readonly [number, number, number, number];
type Dong = MapData["dongs"][number];

/** 동네 좌표를 모두 담는 3:2 범위. 값을 코드에 박지 않아 좌표가 바뀌어도 어긋나지 않는다. */
function boxFor(dongs: Dong[], names: string[]): Box {
  const pts = dongs.filter((d) => names.includes(d.dong)).map((d) => project(d.lon, d.lat));
  if (pts.length === 0) return FULL;
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
  const cy = (Math.min(...ys) + Math.max(...ys)) / 2;
  const w = Math.max((Math.max(...xs) - Math.min(...xs)) * 1.2, (Math.max(...ys) - Math.min(...ys)) * 1.2 * 1.5);
  return [cx - w / 2, cy - w / 3, w, (w * 2) / 3];
}

/** 이름표가 겹치면 위·아래·오른쪽·왼쪽 순서로 옮기고, 자리가 없으면 숨긴다. 선택한 동네를 먼저 놓는다. */
function placeLabels(items: { dong: string; x: number; y: number }[], selected: string, u: number, r: number) {
  const placed: { x0: number; y0: number; x1: number; y1: number }[] = [];
  const out = new Map<string, { x: number; y: number; anchor: "middle" | "start" | "end" }>();
  const h = 1.15 * 13 * u;
  const hits = (b: (typeof placed)[number]) => placed.some((p) => b.x0 < p.x1 && b.x1 > p.x0 && b.y0 < p.y1 && b.y1 > p.y0);
  // 원 자체도 가리지 않게 먼저 자리를 차지한다.
  for (const it of items) placed.push({ x0: it.x - r, y0: it.y - r, x1: it.x + r, y1: it.y + r });
  const order = [...items].sort((a, b) => Number(b.dong === selected) - Number(a.dong === selected));
  for (const it of order) {
    const w = it.dong.length * 13 * u * 1.02;
    const gap = r + 2 * u;
    const options = [
      { x: it.x, y: it.y - gap, anchor: "middle" as const, b: { x0: it.x - w / 2, y0: it.y - gap - h, x1: it.x + w / 2, y1: it.y - gap } },
      { x: it.x, y: it.y + gap + h * 0.8, anchor: "middle" as const, b: { x0: it.x - w / 2, y0: it.y + gap, x1: it.x + w / 2, y1: it.y + gap + h } },
      { x: it.x + gap, y: it.y + h * 0.3, anchor: "start" as const, b: { x0: it.x + gap, y0: it.y - h / 2, x1: it.x + gap + w, y1: it.y + h / 2 } },
      { x: it.x - gap, y: it.y + h * 0.3, anchor: "end" as const, b: { x0: it.x - gap - w, y0: it.y - h / 2, x1: it.x - gap, y1: it.y + h / 2 } },
    ];
    const pick = options.find((o) => !hits(o.b)) ?? (it.dong === selected ? options[0] : null);
    if (pick) {
      placed.push(pick.b);
      out.set(it.dong, { x: pick.x, y: pick.y, anchor: pick.anchor });
    }
  }
  return out;
}

// KRDS primary 10 → 70 사이를 잇는 한 색상 단계. 진할수록 값이 크다.
const LOW = [0xd8, 0xe5, 0xfd];
const HIGH = [0x08, 0x38, 0x91];
function ramp(t: number) {
  return `rgb(${LOW.map((l, i) => Math.round(l + (HIGH[i] - l) * t)).join(",")})`;
}

export function JejuMap({ data, metric, metricLabel, selected, onSelect }: {
  data: MapData;
  metric: string;
  metricLabel: string;
  selected: string;
  onSelect: (dong: string) => void;
}) {
  const [viewKey, setViewKey] = useState<"all" | "jeju" | "seogwipo">("all");
  const [hover, setHover] = useState<string | null>(null);
  const views = useMemo(
    () => [
      { key: "all" as const, label: "제주 전체", box: FULL as Box },
      { key: "jeju" as const, label: "제주시 도심", box: boxFor(data.dongs, JEJU_CITY) },
      { key: "seogwipo" as const, label: "서귀포 도심", box: boxFor(data.dongs, SEOGWIPO_CITY) },
    ],
    [data.dongs],
  );
  const view = views.find((v) => v.key === viewKey) ?? views[0];
  // u: 화면 1px에 해당하는 지도 단위(지도 폭 약 560px 기준). 확대해도 원과 글자의 화면 크기를 일정하게 둔다.
  const u = view.box[2] / 560;
  const radius = 9 * u;
  const labels = useMemo(() => {
    if (viewKey === "all") return new Map();
    const [bx, by, bw, bh] = view.box;
    const items = data.dongs
      .map((d) => {
        const [x, y] = project(d.lon, d.lat);
        return { dong: d.dong, x, y };
      })
      .filter((d) => d.x >= bx && d.x <= bx + bw && d.y >= by && d.y <= by + bh);
    return placeLabels(items, selected, u, radius);
  }, [viewKey, view, data.dongs, selected, u, radius]);

  const points = useMemo(() => data.grid.map(([lon, lat]) => project(lon, lat)), [data.grid]);
  const { lo, hi } = useMemo(() => {
    const vals = data.dongs.map((d) => d.values[metric]).filter((v): v is number => v !== null);
    return { lo: Math.min(...vals), hi: Math.max(...vals) };
  }, [data.dongs, metric]);
  const focus = data.dongs.find((d) => d.dong === (hover ?? selected));
  const ordered = useMemo(() => [...data.dongs].sort((a) => (a.dong === selected ? 1 : -1)), [data.dongs, selected]);
  const chuja = project(126.297, 33.96);

  return (
    <div data-testid="map">
      <div role="group" aria-label="지도 범위" className="mb-2 flex flex-wrap gap-1.5 print:hidden">
        {views.map((v) => (
          <Button key={v.key} size="sm" variant={v.key === viewKey ? "secondary" : "outline"} aria-pressed={v.key === viewKey} onClick={() => setViewKey(v.key)}>
            {v.label}
          </Button>
        ))}
      </div>
      <div className="overflow-hidden rounded-(--radius) border border-(--krds-border-gray-light) bg-(--krds-surface-white)">
        <svg viewBox={view.box.join(" ")} className="block w-full" role="group" aria-label={`제주 지도. 동네별 ${metricLabel}`}>
          <g aria-hidden>
            {points.map(([x, y], i) => (
              <rect key={i} x={x - 10} y={y - 10} width={20} height={20} fill="var(--krds-surface-gray-subtle)" />
            ))}
          </g>
          <rect x={chuja[0] - 40} y={chuja[1] - 34} width={80} height={68} fill="none" stroke="var(--krds-border-gray-dark)" strokeDasharray="4 3" strokeWidth={u} aria-hidden />
          {ordered.map((d) => {
            const [x, y] = project(d.lon, d.lat);
            const v = d.values[metric];
            const t = v === null ? 0 : (v - lo) / (hi - lo || 1);
            const isSelected = d.dong === selected;
            return (
              <g
                key={d.dong}
                role="button"
                tabIndex={0}
                aria-pressed={isSelected}
                aria-label={`${d.dong}, ${metricLabel} ${formatMetric(metric, v)}`}
                data-dong={d.dong}
                className="cursor-pointer outline-none [&:focus-visible>circle:last-of-type]:stroke-(--krds-border-primary)"
                onClick={() => onSelect(d.dong)}
                onMouseEnter={() => setHover(d.dong)}
                onMouseLeave={() => setHover(null)}
                onFocus={() => setHover(d.dong)}
                onBlur={() => setHover(null)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") {
                    e.preventDefault();
                    onSelect(d.dong);
                  }
                }}
              >
                {/* 보이는 원보다 넓은 누름 영역 */}
                <circle cx={x} cy={y} r={radius * 1.6} fill="transparent" />
                <circle
                  cx={x}
                  cy={y}
                  r={isSelected ? radius * 1.25 : radius}
                  fill={v === null ? "var(--krds-surface-disabled)" : ramp(t)}
                  stroke={isSelected ? "var(--krds-text-bolder)" : "var(--krds-surface-white)"}
                  strokeWidth={(isSelected ? 3 : 1.5) * u}
                />
                {(() => {
                  const fallback = isSelected || d.dong === hover ? { x, y: y - radius * 1.6, anchor: "middle" as const } : null;
                  const pos = labels.get(d.dong) ?? fallback;
                  if (!pos) return null;
                  return (
                    <text
                      x={pos.x}
                      y={pos.y}
                      textAnchor={pos.anchor}
                      fontSize={13 * u}
                      fontWeight={isSelected ? 700 : 500}
                      fill="var(--krds-text-bolder)"
                      stroke="var(--krds-surface-white)"
                      strokeWidth={3 * u}
                      paintOrder="stroke"
                      className="pointer-events-none"
                    >
                      {d.dong}
                    </text>
                  );
                })()}
              </g>
            );
          })}
        </svg>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[length:var(--krds-fs-body-small)]">
        <p className={cn("min-h-6 font-semibold")} aria-live="off" data-testid="map-focus">
          {focus ? `${focus.dong}: ${metricLabel} ${formatMetric(metric, focus.values[metric])}` : ""}
        </p>
        <div className="flex items-center gap-2 text-(--krds-text-subtle)" aria-hidden>
          <span>{formatMetric(metric, lo)}</span>
          <span className="h-3 w-24 rounded-sm" style={{ background: `linear-gradient(to right, ${ramp(0)}, ${ramp(1)})` }} />
          <span>{formatMetric(metric, hi)}</span>
        </div>
      </div>
      <p className="mt-1 text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)">
        {metric === "방문거주비" && <strong className="font-semibold text-(--krds-text-basic)">거주 값에 대한 방문 값의 비율이며 손님 수가 아닙니다. 거주 값이 작은 섬 지역은 높게 나옵니다. </strong>}
        원 하나가 동네 하나이고, 색이 진할수록 값이 큽니다. 위치는 점포 좌표의 중앙값이고 회색은 점포가 있는 곳입니다. 점선 칸의 추자면은 실제로 더 북쪽에 있습니다.
      </p>
    </div>
  );
}
