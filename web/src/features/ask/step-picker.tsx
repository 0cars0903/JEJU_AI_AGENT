"use client";

import { useMemo, useState } from "react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { type Guide, type Slots, ready } from "@/lib/api";

const FIELD_LABEL: Record<string, string> = { space: "동네", target: "업종", variant: "보고 싶은 것", metric: "순위 기준", keyword: "찾을 자료" };
// Stageshow 지적 6: 동네 43곳을 한꺼번에 늘어놓지 않고 자주 찾는 곳을 먼저, 나머지는 '더 보기'(상가 수가 많은 동네 기준)
const FREQUENT = ["노형동", "연동", "이도2동", "아라동", "애월읍", "조천읍", "한림읍", "중문동", "성산읍", "구좌읍", "대정읍", "표선면"];

function Chip({ on, children, onClick, testId }: { on: boolean; children: React.ReactNode; onClick: () => void; testId?: string }) {
  return (
    <button
      type="button"
      aria-pressed={on}
      data-testid={testId}
      onClick={onClick}
      className={cn(
        "min-h-11 rounded-(--radius) border px-3 text-[length:var(--krds-fs-body-medium)]",
        on // Stageshow 지적 7: 고른 칩은 강조색 채움 + 흰 글자
          ? "border-(--krds-border-primary) bg-primary font-semibold text-primary-foreground"
          : "border-(--krds-border-gray) bg-background hover:bg-muted",
      )}
    >
      {children}
    </button>
  );
}

/** ③ 단계별 선택: 궁금한 것 → 그 주제에 필요한 칸만 이어서 고른다. 고른 값은 해석 없이 그대로 답에 쓴다. */
export function StepPicker({ guide, preset, notice, onSubmit, onClose }: {
  guide: Guide;
  preset?: Slots;
  notice?: string;
  onSubmit: (s: Slots) => void;
  onClose: () => void;
}) {
  const [s, setS] = useState<Slots>(preset ?? {});
  const [query, setQuery] = useState("");
  const [allDongs, setAllDongs] = useState(false);
  const topic = guide.topics.find((t) => t.id === s.topic);
  const fields = topic ? [...topic.need, ...topic.optional] : [];
  const dongs = useMemo(() => {
    const q = query.trim();
    if (q) return guide.dongs.filter((d) => d.includes(q));
    if (allDongs) return guide.dongs;
    const picked = s.space ?? [];
    return [...picked.filter((d) => !FREQUENT.includes(d)), ...FREQUENT.filter((d) => guide.dongs.includes(d))];
  }, [guide.dongs, query, allDongs, s.space]);
  // Stageshow 지적 8: 버튼이 꺼진 이유를 보여 준다
  const missingMsg = !topic
    ? "궁금한 것을 골라 주세요."
    : topic.need.map((k) => (k === "space" ? ((s.space?.length ?? 0) < topic.min_space ? (topic.min_space > 1 ? `동네를 ${topic.min_space}곳 이상 골라 주세요.` : "동네를 골라 주세요.") : null) : !s[k as keyof Slots] ? `${FIELD_LABEL[k] ?? k}을(를) 골라 주세요.` : null)).find(Boolean);
  const multi = (topic?.min_space ?? 1) > 1;

  const toggleDong = (d: string) =>
    setS((p) => {
      const cur = p.space ?? [];
      if (!multi) return { ...p, space: [d] };
      return { ...p, space: cur.includes(d) ? cur.filter((x) => x !== d) : [...cur, d].slice(0, 4) };
    });

  return (
    <section data-testid="step-picker" aria-label="하나씩 골라서 묻기" className="flex flex-col gap-5 rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) bg-card p-4 md:p-6">
      {notice && (
        <p role="status" data-testid="choose-notice" className="rounded-(--radius) bg-(--krds-surface-primary-subtler) p-3 font-semibold">
          {notice}
        </p>
      )}
      <div>
        <h3 className="mb-2">1. 무엇이 궁금하세요?</h3>
        <div className="flex flex-wrap gap-2">
          {guide.topics.map((t) => (
            <Chip key={t.id} on={s.topic === t.id} testId={`topic-${t.id}`} onClick={() => setS((p) => ({ space: p.space?.slice(0, t.min_space > 1 ? 4 : 1), topic: t.id }))}>
              {t.label}
            </Chip>
          ))}
        </div>
      </div>

      {topic?.center_only && (
        <p data-testid="center-only" className="text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)">
          이 주제는 빅데이터센터 PC의 센터 자료로만 볼 수 있어요. 센터 밖에서는 대신 볼 수 있는 질문을 안내해 드려요.
        </p>
      )}

      {topic &&
        fields.map((f, i) => (
          <div key={f}>
            <h3 className="mb-2">
              {i + 2}. {FIELD_LABEL[f]}
              {topic.optional.includes(f) ? <span className="ml-1 font-normal text-(--krds-text-subtle)">(고르지 않아도 돼요)</span> : null}
              {f === "space" && multi ? <span className="ml-1 font-normal text-(--krds-text-subtle)">(2곳 이상, 최대 4곳)</span> : null}
            </h3>
            {f === "space" ? (
              <div className="flex flex-col gap-2">
                <input
                  aria-label="동네 이름으로 찾기"
                  placeholder="동네 이름으로 찾기 (예: 노형)"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  className="h-11 rounded-(--radius) border border-(--krds-border-gray) px-3"
                />
                <div className="flex flex-wrap gap-2">
                  {dongs.map((d) => (
                    <Chip key={d} on={s.space?.includes(d) ?? false} testId={`dong-${d}`} onClick={() => toggleDong(d)}>
                      {d}
                    </Chip>
                  ))}
                  {!query.trim() && (
                    <button type="button" data-testid="dongs-more" className="min-h-11 px-2 underline" onClick={() => setAllDongs(!allDongs)}>
                      {allDongs ? "자주 찾는 동네만" : `동네 더 보기(전체 ${guide.dongs.length}곳)`}
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div className="flex flex-wrap gap-2">
                {(f === "variant" ? topic.variants : topic.options[f] ?? []).map((o) => (
                  <Chip
                    key={o.value}
                    on={s[f as keyof Slots] === o.value}
                    testId={`${f}-${o.value}`}
                    onClick={() => setS((p) => ({ ...p, [f]: p[f as keyof Slots] === o.value && topic.optional.includes(f) ? undefined : o.value }))}
                  >
                    {o.label}
                  </Chip>
                ))}
              </div>
            )}
          </div>
        ))}

      <div className="flex flex-wrap items-center gap-2">
        <Button data-testid="picker-submit" disabled={!ready(topic, s)} onClick={() => onSubmit(s)}>
          이대로 답 보기
        </Button>
        {!ready(topic, s) && missingMsg && (
          <span data-testid="picker-missing" className="font-semibold text-(--krds-text-bolder)">
            {missingMsg}
          </span>
        )}
        <Button variant="outline" onClick={onClose}>
          닫기
        </Button>
      </div>
    </section>
  );
}
