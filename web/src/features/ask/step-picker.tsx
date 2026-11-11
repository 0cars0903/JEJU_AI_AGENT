"use client";

import { useMemo, useState } from "react";
import { cn } from "cn";
import { Button } from "@/components/ui/button";
import { BedDouble, Coffee, Drumstick, Fish, ShoppingBag, Soup, Store, UtensilsCrossed } from "lucide-react";
import { type Guide, type Slots, ready } from "@/lib/api";
import { JejuMap } from "./jeju-map";

// 패턴 B: 업종은 아이콘 타일(소상공인365·SGIS 방식). 아이콘이 없는 값은 가게 그림
const BIZ_ICON: Record<string, typeof Store> = { 음식점: UtensilsCrossed, 카페: Coffee, 한식: Soup, 치킨: Drumstick, 횟집: Fish, 숙박: BedDouble, 소매: ShoppingBag };

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

function BizTile({ on, label, onClick, testId }: { on: boolean; label: string; onClick: () => void; testId: string }) {
  const Icon = BIZ_ICON[label] ?? Store;
  return (
    <button
      type="button"
      aria-pressed={on}
      data-testid={testId}
      onClick={onClick}
      className={cn(
        "flex min-h-20 flex-col items-center justify-center gap-1 rounded-(--radius) border px-2 py-2",
        on ? "border-(--krds-border-primary) bg-primary font-semibold text-primary-foreground" : "border-(--krds-border-gray) bg-background hover:bg-muted",
      )}
    >
      <Icon size={26} aria-hidden />
      <span>{label}</span>
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
  const [allTopics, setAllTopics] = useState(false);
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
    <section data-testid="step-picker" aria-label="조건 고르기" className="flex flex-col gap-5 rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) bg-card p-4 md:p-6">
      {notice && (
        <p role="status" data-testid="choose-notice" className="rounded-(--radius) bg-(--krds-surface-primary-subtler) p-3 font-semibold">
          {notice}
        </p>
      )}
      <div>
        <h3 className="mb-2">1. 무엇이 궁금하세요?</h3>
        {/* B3: 주제를 고르면 고른 주제만 남겨, 다음 칸(동네·업종)이 스크롤 없이 이어서 보이게 한다. 다른 주제는 [다른 주제 보기]로 다시 편다 */}
        <div className="flex flex-wrap gap-2">
          {guide.topics
            .filter((t) => !topic || allTopics || t.id === topic.id)
            .map((t) => (
              <Chip
                key={t.id}
                on={s.topic === t.id}
                testId={`topic-${t.id}`}
                onClick={() => {
                  setAllTopics(false);
                  setS((p) => (p.topic === t.id ? {} : { space: p.space?.slice(0, t.min_space > 1 ? 4 : 1), topic: t.id }));
                }}
              >
                {t.label}
              </Chip>
            ))}
          {topic && (
            <button type="button" data-testid="topics-more" aria-expanded={allTopics} className="min-h-11 rounded-(--radius) px-3 underline hover:bg-muted" onClick={() => setAllTopics(!allTopics)}>
              {allTopics ? "고른 주제만 보기" : `다른 주제 보기(${guide.topics.length - 1})`}
            </button>
          )}
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
              {/* C9: 고르지 않아도 되는 칸은 고른 뒤에도 풀 수 있게 한다 */}
              {topic.optional.includes(f) && s[f as keyof Slots] ? (
                <button type="button" data-testid={`clear-${f}`} onClick={() => setS((p) => ({ ...p, [f]: undefined }))} className="ml-2 min-h-11 rounded-(--radius) px-3 font-normal underline hover:bg-muted">
                  선택 풀기
                </button>
              ) : null}
            </h3>
            {f === "space" ? (
              <div className="flex flex-col gap-2">
                <details className="rounded-(--radius) border border-(--krds-border-gray-light) px-2">
                  <summary className="flex min-h-11 cursor-pointer items-center font-semibold">지도에서 고르기</summary>
                  <JejuMap selected={s.space ?? []} onPick={toggleDong} label="제주 43개 동네 지도. 눌러서 동네를 고르세요." testId="picker-map" />
                </details>
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
                    <button type="button" data-testid="dongs-more" className="min-h-11 rounded-(--radius) px-3 underline hover:bg-muted" onClick={() => setAllDongs(!allDongs)}>
                      {allDongs ? "자주 찾는 동네만" : `동네 더 보기(전체 ${guide.dongs.length}곳)`}
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div className={f === "target" ? "grid grid-cols-3 gap-2 sm:grid-cols-4" : "flex flex-wrap gap-2"}>
                {(f === "variant" ? topic.variants : topic.options[f] ?? []).map((o) => (
                  f === "target" ? (
                    <BizTile
                      key={o.value}
                      on={s[f as keyof Slots] === o.value}
                      label={o.label}
                      testId={`${f}-${o.value}`}
                      onClick={() => setS((p) => ({ ...p, [f]: p[f as keyof Slots] === o.value && topic.optional.includes(f) ? undefined : o.value }))}
                    />
                  ) : (
                  <Chip
                    key={o.value}
                    on={s[f as keyof Slots] === o.value}
                    testId={`${f}-${o.value}`}
                    onClick={() => setS((p) => ({ ...p, [f]: p[f as keyof Slots] === o.value && topic.optional.includes(f) ? undefined : o.value }))}
                  >
                    {o.label}
                  </Chip>
                  )
                ))}
              </div>
            )}
          </div>
        ))}

      {/* B3: 칸을 고르는 동안에도 [이대로 답 보기]가 화면 아래에 붙어 있게 한다 */}
      <div data-testid="picker-actions" className="sticky bottom-0 z-10 -mx-4 -mb-4 flex flex-wrap items-center gap-2 border-t border-(--krds-border-gray-light) bg-card p-3 md:-mx-6 md:-mb-6 md:px-6">
        <Button data-testid="picker-submit" disabled={!ready(topic, s)} onClick={() => onSubmit(s)}>
          이대로 답 보기
        </Button>
        {!ready(topic, s) && missingMsg && (
          <span data-testid="picker-missing" className="font-semibold text-(--krds-text-bolder)">
            {missingMsg}
          </span>
        )}
        <Button variant="outline" data-testid="picker-close" onClick={onClose} className="lg:hidden">
          닫기
        </Button>
      </div>
    </section>
  );
}
