"use client";

import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Skeleton } from "skullet/react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ErrorState } from "@/components/states";
import { SendIcon } from "@/components/icons";
import { type AskResult, type Slots, ask, getGuide } from "@/lib/api";
import { StepPicker } from "./step-picker";
import {
  AnswerCard,
  Downloads,
  Process,
  SuggestionList,
  Understood,
  Waiting,
} from "./answer";

// 로딩 뼈대의 모양을 그리기 위한 예시 답(화면에 보이지 않는다).
const SAMPLE: AskResult = {
  question: "노형동 카페 가게는 몇 곳이야?",
  status: "성공",
  card: {
    conclusion: "노형동 카페 점포 수를 정리했습니다.",
    evidence: [
      {
        text: "노형동 점포 수 000 곳",
        dataset: "793 상가",
        as_of: "최신 단면",
      },
      { text: "근거 한 줄 더", dataset: "자료", as_of: "기준일" },
    ],
    intervals: [],
    limits: ["한계 문장 한 줄"],
    next_questions: [],
  },
};

type Picker = { preset?: Slots; notice?: string };

/** 질문 화면: ① 자유 입력 ② 추천 질문 ③ 단계별 선택 ④ 대표 질문(docs/기획/07_화면API명세.md). */
export function AskPage() {
  const guide = useQuery({
    queryKey: ["guide"],
    queryFn: getGuide,
    staleTime: Infinity,
  });
  const [text, setText] = useState("");
  const [picker, setPicker] = useState<Picker | null>(null);
  const [asked, setAsked] = useState<string | null>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);
  // 단계별 선택이 열리면(선택필요 안내·[바꾸기]) 그 자리로 옮긴다. 결과 쪽에 머물면 안내가 화면 밖에 남는다(모바일 캡처 점검).
  useEffect(() => {
    if (picker)
      pickerRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [picker]);

  const m = useMutation({
    mutationFn: ask,
    onSuccess: (r) => {
      if (r.status === "선택필요" && r.choose)
        setPicker({ preset: r.choose.preset, notice: r.choose.message });
    },
  });

  const run = (body: { question?: string; slots?: Slots }, label: string) => {
    setAsked(label);
    setPicker(null);
    m.mutate(body);
    requestAnimationFrame(() =>
      resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }),
    );
  };
  const submitText = () => {
    const q = text.trim();
    if (q) run({ question: q }, q);
  };

  const r = m.data;
  const answered = r && r.status !== "선택필요";

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-3" aria-label="질문하기">
        <h1>동네에 대해 물어보세요</h1>
        <form
          className="flex flex-col gap-2 md:flex-row"
          onSubmit={(e) => {
            e.preventDefault();
            submitText();
          }}
        >
          <Textarea
            data-testid="question-input"
            aria-label="질문"
            placeholder="예: 노형동에 카페가 몇 곳 있어?"
            value={text}
            maxLength={200}
            rows={2}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (
                e.key === "Enter" &&
                !e.shiftKey &&
                !e.nativeEvent.isComposing
              ) {
                e.preventDefault();
                submitText();
              }
            }}
            className="min-h-14 flex-1 text-[length:var(--krds-fs-body-large)]"
          />
          <Button
            type="submit"
            size="lg"
            data-testid="ask-submit"
            disabled={!text.trim() || m.isPending}
            className="md:h-auto"
          >
            <SendIcon size={20} aria-hidden />
            묻기
          </Button>
        </form>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="secondary"
            data-testid="open-picker"
            onClick={() => setPicker({})}
            disabled={!guide.data}
          >
            하나씩 골라서 묻기
          </Button>
          <span className="text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle)">
            질문을 쓰기 어려우면 궁금한 것과 동네를 골라 주세요.
          </span>
        </div>
      </section>

      {picker && guide.data && (
        <div ref={pickerRef} className="scroll-mt-24">
          <StepPicker
            key={JSON.stringify(picker)}
            guide={guide.data}
            preset={picker.preset}
            notice={picker.notice}
            onSubmit={(s) => run({ slots: s }, "고른 항목으로 묻기")}
            onClose={() => setPicker(null)}
          />
        </div>
      )}

      {!asked && guide.data && (
        <SuggestionList
          testId="representative"
          title="이런 걸 물어볼 수 있어요"
          items={guide.data.representative.map((x) => ({
            text: x.text,
            slots: x.slots,
          }))}
          onPick={(x) => run({ slots: x.slots }, x.text)}
        />
      )}
      {guide.isError && (
        <ErrorState error={guide.error} onRetry={() => guide.refetch()} />
      )}

      <div
        ref={resultRef}
        className="flex flex-col gap-4 scroll-mt-24"
        aria-live="polite"
      >
        {asked && (
          <p className="text-(--krds-text-subtle)" data-testid="asked">
            질문: {r?.question ?? asked}
          </p>
        )}
        {m.isPending && <Waiting />}
        {m.isError && <ErrorState error={m.error} onRetry={() => m.reset()} />}
        {asked && !m.isError && (m.isPending || answered) && (
          <Skeleton
            data={m.isPending ? null : r}
            sample={SAMPLE}
            label="답을 만들고 있어요"
          >
            {(res: AskResult) => (
              <div className="flex flex-col gap-4">
                <Understood
                  key={JSON.stringify(res.understood)}
                  r={res}
                  sample={res === SAMPLE}
                  onChange={(s) => setPicker({ preset: s })}
                />
                <AnswerCard r={res} sample={res === SAMPLE} />
                <Process r={res} />
                <Downloads r={res} />
              </div>
            )}
          </Skeleton>
        )}
        {answered && r?.suggestions && (
          <SuggestionList
            testId="suggestions"
            title={
              r.status === "범위밖"
                ? "대신 이런 걸 물어볼 수 있어요"
                : "이어서 물어보기"
            }
            items={r.suggestions}
            onPick={(x) => run({ slots: x.slots }, x.text)}
          />
        )}
      </div>
    </div>
  );
}
