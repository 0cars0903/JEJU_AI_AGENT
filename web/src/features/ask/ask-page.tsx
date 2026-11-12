"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Skeleton } from "skullet/react";
import { ChevronLeft, ChevronRight, ExternalLink, House, Link2, Printer, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ErrorState } from "@/components/states";
import { SendIcon } from "@/components/icons";
import { ApiError, type AskBody, type AskResult, type CenterFile, type DatasetMeta, type Slots, ask, getGuide, readCenter, writeCenter } from "@/lib/api";
import { StepPicker } from "./step-picker";
import { CenterUpload, Report, Requests, Views, copyText } from "./views";
import { DongHome } from "./dong-home";
import { ExpertMode } from "./expert";
import { AnswerCard, BizTabs, CompareWith, Downloads, Process, SuggestionList, Understood, Waiting } from "./answer";

// 로딩 뼈대의 모양을 그리기 위한 예시 답(화면에 보이지 않는다).
const SAMPLE: AskResult = {
  question: "노형동 카페 가게는 몇 곳이야?",
  status: "성공",
  card: {
    conclusion: "노형동 카페 가게 수를 정리했어요.",
    evidence: [
      { text: "노형동 카페 가게 수는 000 곳이에요.", dataset: "상가 정보", as_of: "2025-09-18 기준" },
      { text: "근거 한 줄 더", dataset: "자료", as_of: "기준일" },
    ],
    intervals: [],
    limits: ["한계 문장 한 줄"],
    next_questions: [],
  },
};
const MAX = 200;

type Picker = { preset?: Slots; notice?: string };
type Body = AskBody;
const PICK_LABEL = "고른 항목으로 묻기";

/** A6·A7: 센터 파일을 한 번 넣었으면 그 뒤 질문에도 번호와 열쇠를 함께 보낸다. 열쇠는 주소에 넣지 않는다. */
function withCenter(body: Body): Body {
  const c = readCenter();
  if (!c) return body;
  if (!body.dataset_id) return { ...body, dataset_id: c.id, dataset_key: c.key };
  if (body.dataset_id === c.id) return { ...body, dataset_key: c.key };
  return body;
}

/** 결과 주소: 같은 탭에서 열고(뒤로 가기로 첫 화면), 같은 주소를 [새 탭으로 열기]로도 연다(사용자 결정 2026-11-12). */
function toUrl(body: Body, label: string) {
  const p = new URLSearchParams();
  if (body.question) p.set("q", body.question);
  if (body.slots) p.set("s", JSON.stringify(body.slots));
  if (body.dataset_id) p.set("d", body.dataset_id);
  if (label && label !== body.question) p.set("l", label);
  return `/?${p}`;
}

function fromParams(sp: URLSearchParams): { body: Body; label: string } | null {
  const q = sp.get("q");
  const s = sp.get("s");
  if (!q && !s) return null;
  let slots: Slots | undefined;
  try {
    slots = s ? (JSON.parse(s) as Slots) : undefined;
  } catch {
    slots = undefined;
  }
  const body: Body = { question: q ?? undefined, slots, dataset_id: sp.get("d") ?? undefined };
  return { body, label: sp.get("l") ?? q ?? PICK_LABEL };
}

/** 질문 화면. 첫 화면 = 왼쪽 조건 패널 + 입력 + 동네 한눈에(스플릿). 결과 화면 = 같은 탭의 결과 주소, 패널은 접어 두고 [<]·[입력 없이 골라서 묻기]로 연다. */
export function AskPage() {
  const router = useRouter();
  const sp = useSearchParams();
  const req = useMemo(() => fromParams(new URLSearchParams(sp.toString())), [sp]);
  const guide = useQuery({ queryKey: ["guide"], queryFn: getGuide, staleTime: Infinity });
  const [text, setText] = useState("");
  const [picker, setPicker] = useState<Picker | null>(null);
  const [panel, setPanel] = useState(false);
  const [moreRep, setMoreRep] = useState(false);
  const [center, setCenterState] = useState<CenterFile | null>(null);
  const [emptyHint, setEmptyHint] = useState(false);
  const [copied, setCopied] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const resultRef = useRef<HTMLDivElement>(null);
  // B2·B7: 답이 펼쳐지는 동안 누른 바로 가기의 목적지. 펼침이 끝나면 한 번 더 맞춘다.
  const jumpRef = useRef<string | null>(null);
  const pickerRef = useRef<HTMLElement>(null);

  const m = useMutation({
    mutationFn: ask,
    onSuccess: (r) => {
      if (r.status === "선택필요" && r.choose) setPicker({ preset: r.choose.preset, notice: r.choose.message });
    },
  });

  // 조건 패널은 본문 위에 겹쳐 뜬다(문서 21 5.3절 1안). 처음에는 닫혀 있고, 답을 받으면 닫아 답을 가리지 않는다.
  useEffect(() => {
    setCenterState(readCenter());
  }, []);

  // 주소가 바뀌면(질문·뒤로 가기) 그 질문으로 답을 받는다. 입력 칸 글을 '질문:' 줄과 맞춘다(C4).
  const key = sp.toString();
  useEffect(() => {
    if (req) {
      m.mutate(withCenter(req.body));
      setText(req.body.question ?? (req.label !== PICK_LABEL ? req.label : ""));
      requestAnimationFrame(() => resultRef.current?.scrollIntoView({ behavior: "smooth", block: "start" }));
    } else {
      m.reset();
      setText("");
    }
    setPicker(null);
    setPanel(false);
    setEmptyHint(false);
    jumpRef.current = null;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  // 조건 패널이 열리면 패널로 이동하고 초점도 첫 칸으로 옮긴다(B4·C3).
  useEffect(() => {
    if (picker) {
      requestAnimationFrame(() => pickerRef.current?.querySelector<HTMLElement>("[data-testid^='topic-']")?.focus({ preventScroll: true }));
    }
  }, [picker]);

  // 답이 나온 뒤 눌렀던 버튼이 사라져 초점이 없어졌으면 입력 칸으로 돌려준다(C3).
  useEffect(() => {
    const d = m.data;
    if (!d || d.status === "선택필요") return;
    const a = document.activeElement;
    const lost = !a || a === document.body || !document.body.contains(a);
    if (lost || (a as HTMLElement).dataset?.testid === "ask-submit") inputRef.current?.focus({ preventScroll: true });
  }, [m.data]);

  const togglePanel = (open: boolean) => setPanel(open);
  const closePanel = () => {
    setPicker(null);
    setPanel(false);
  };
  const run = (body: Body, label: string) => router.push(toUrl(withCenter(body), label));
  const submitText = () => {
    const q = text.trim();
    if (!q) return setEmptyHint(true);
    if (m.isPending) return;
    run({ question: q }, q);
  };
  const adoptCenter = (meta: DatasetMeta) => {
    const c = { id: meta.id, key: meta.key ?? "", file: meta.file, label: meta.label };
    writeCenter(c);
    setCenterState(c);
    return c;
  };
  const dropCenter = () => {
    writeCenter(null);
    setCenterState(null);
    if (req?.body.dataset_id) router.push(toUrl({ ...req.body, dataset_id: undefined, dataset_key: undefined }, req.label));
  };
  const goHome = (e: React.MouseEvent) => {
    // [처음 화면]: 센터 파일 열쇠를 지우고, 이 답을 뒤로 가기 기록에서 빼기 위해 현재 기록을 바꿔 치기한다(A7).
    e.preventDefault();
    writeCenter(null);
    window.location.replace("/");
  };
  const copyLink = async () => {
    if (await copyText(window.location.href)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 2500);
    }
  };

  const r = m.data;
  const answered = r && r.status !== "선택필요";
  const asked = req?.label ?? null;
  const showPanel = panel || Boolean(picker);
  const needFile = m.isError && m.error instanceof ApiError && m.error.status === 422 && Boolean(req?.body.dataset_id);

  return (
    <div className="flex flex-col gap-6 lg:grid lg:grid-cols-[auto_1fr] lg:items-start lg:gap-6">
      {/* 화면 순서와 Tab 순서를 맞추려고 질문 칸(main)을 먼저 두고, 큰 화면에서만 패널을 왼쪽으로 보낸다(B5). */}
      <div className="flex min-w-0 flex-col gap-4 lg:order-2">
        <section className="flex flex-col gap-2" aria-label="질문하기">
          {req ? (
            <div className="flex flex-wrap items-center gap-2">
              <a href="/" onClick={goHome} data-testid="go-home" className="inline-flex min-h-11 items-center gap-1 rounded-(--radius) border border-(--krds-border-gray) px-3 font-semibold hover:bg-muted">
                <House size={18} aria-hidden /> 처음 화면
              </a>
              <Button variant="outline" data-testid="copy-link" onClick={copyLink} className="gap-1">
                <Link2 size={18} aria-hidden /> 링크 복사
              </Button>
              <a
                href={toUrl(req.body, req.label)}
                target="_blank"
                rel="noopener"
                data-testid="open-new-tab"
                className="inline-flex min-h-11 items-center gap-1 rounded-(--radius) border border-(--krds-border-gray) px-3 hover:bg-muted"
              >
                <ExternalLink size={18} aria-hidden /> 새 탭으로 열기<span className="sr-only">(새 탭에서 열려요)</span>
              </a>
              {r?.answer?.requests?.some((q) => q.kind === "center") && (
                <a href="#request-center" data-testid="go-center" className="inline-flex min-h-11 items-center gap-1 rounded-(--radius) border border-(--krds-border-gray) px-3 hover:bg-muted">
                  센터 자료 넣기
                </a>
              )}
              {r?.answer && (
                <Button variant="outline" data-testid="print-report" onClick={() => window.print()} className="gap-1">
                  <Printer size={18} aria-hidden /> 보고서 인쇄(PDF 저장)
                </Button>
              )}
              <span role="status" data-testid="copied" className="font-semibold text-(--krds-text-primary)">
                {copied ? "복사했어요" : ""}
              </span>
            </div>
          ) : (
            <h1 className="text-[length:var(--krds-fs-heading-medium)]">제주 상권, 자료로 물어보세요</h1>
          )}
          {/* 입력창(Notion '입력창 디자인' 기준): 라벨 · 입력 · 도움말 또는 오류 문구 */}
          <form
            className="flex flex-col gap-1"
            onSubmit={(e) => {
              e.preventDefault();
              submitText();
            }}
          >
            <label htmlFor="question" className="sr-only">
              질문
            </label>
            <div className="flex flex-col gap-2 md:flex-row">
              <Textarea
                id="question"
                ref={inputRef}
                data-testid="question-input"
                aria-describedby="question-help"
                placeholder="예: 노형동에 카페 차려도 될까?"
                value={text}
                maxLength={MAX}
                rows={1}
                onChange={(e) => {
                  setText(e.target.value);
                  setEmptyHint(false);
                }}
                // 앞 질문이 남아 있으면 글 전체를 골라 두어, 바로 치면 새 질문으로 바뀐다(C4)
                onFocus={(e) => e.currentTarget.select()}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                    e.preventDefault();
                    submitText();
                  }
                }}
                className="min-h-12 flex-1 text-[length:var(--krds-fs-body-large)] md:text-[length:var(--krds-fs-body-large)]"
              />
              <Button type="submit" size="lg" data-testid="ask-submit" disabled={!text.trim()} aria-busy={m.isPending} className="md:h-auto">
                <SendIcon size={20} aria-hidden />
                묻기
              </Button>
            </div>
            <p
              id="question-help"
              role={emptyHint ? "alert" : undefined}
              data-testid="question-help"
              className={"text-[length:var(--krds-fs-body-medium)] " + (text.length >= MAX || emptyHint ? "font-semibold text-(--krds-text-danger)" : "text-(--krds-text-bolder)")}
            >
              {emptyHint ? "질문을 먼저 적어 주세요." : text.length >= MAX ? `질문은 ${MAX}자까지 쓸 수 있어요. 조금 줄여 주세요.` : "동네와 업종을 함께 쓰면 더 정확해요."} ({text.length}/{MAX})
            </p>
          </form>
          {center && (
            <p data-testid="center-using" className="flex flex-wrap items-center gap-2 rounded-(--radius) bg-(--krds-surface-primary-subtler) px-3 py-1 font-semibold">
              센터 자료 {center.label}({center.file}) 사용 중
              <button type="button" data-testid="center-drop-file" onClick={dropCenter} className="inline-flex min-h-11 items-center gap-1 rounded-(--radius) border border-(--krds-border-gray) bg-background px-3 font-normal hover:bg-muted">
                <X size={16} aria-hidden /> 빼기
              </button>
            </p>
          )}
          <Button
            variant="outline"
            data-testid="open-picker"
            onClick={() => setPicker({})}
            disabled={!guide.data}
            className="w-fit border-2 border-(--krds-border-primary) font-semibold text-(--krds-text-primary) lg:hidden"
          >
            입력 없이 골라서 묻기
          </Button>
        </section>

        {!req && guide.data && (
          <section data-testid="representative" aria-label="이런 걸 물어볼 수 있어요" className="flex flex-wrap items-center gap-2">
            <span className="font-semibold">이런 걸 물어볼 수 있어요</span>
            {guide.data.representative.slice(0, moreRep ? undefined : 3).map((x) => (
              <Button key={x.text} variant="outline" className="h-auto min-h-11 whitespace-normal py-2 text-left" onClick={() => run({ slots: x.slots }, x.text)}>
                {x.text}
              </Button>
            ))}
            {guide.data.representative.length > 3 && (
              <button type="button" data-testid="rep-more" className="min-h-11 rounded-(--radius) px-3 underline hover:bg-muted" onClick={() => setMoreRep(!moreRep)}>
                {moreRep ? "접기" : `더 보기(${guide.data.representative.length - 3})`}
              </button>
            )}
          </section>
        )}
        {!req && guide.data && <DongHome dongs={guide.data.dongs} onAsk={(s, t) => run({ slots: s }, t)} />}
        {guide.isError && <ErrorState error={guide.error} onRetry={() => guide.refetch()} />}
        {/* 설계 11-2절: Claude 키가 있을 때만 보이는 전문가 모드 */}
        <ExpertMode />

        <div
          ref={resultRef}
          className="flex flex-col gap-4 scroll-mt-24"
          aria-live="polite"
          onClickCapture={(e) => {
            const a = (e.target as HTMLElement).closest('a[href^="#"]');
            if (a) jumpRef.current = a.getAttribute("href")!.slice(1);
          }}
        >
          {asked && (
            <p className="text-(--krds-text-bolder)" data-testid="asked">
              질문: {r?.question ?? req?.body.question ?? asked}
            </p>
          )}
          {m.isPending && <Waiting />}
          {m.isError && <ErrorState error={m.error} onRetry={needFile ? undefined : () => req && m.mutate(withCenter(req.body))} />}
          {needFile && req && (
            <div data-testid="need-file" className="flex flex-col gap-2 rounded-(--radius) border border-(--krds-border-gray) p-4">
              <h3>센터 파일을 다시 넣어 주세요</h3>
              <CenterUpload
                onUse={(meta) => {
                  const c = adoptCenter(meta);
                  run({ ...req.body, dataset_id: c.id, dataset_key: c.key }, req.label);
                }}
              />
            </div>
          )}
          {req && !m.isError && (m.isPending || answered) && (
            <Skeleton
              // 질문(주소)마다 전환 부품을 새로 만든다. 같은 부품에서 '앞 답 → 대기 → 새 답'을 연달아 바꾸면 사라져야 할 대기 층이
              // 새 답 위에 남는 경우가 있었다(화면 시험 '추천 질문 이어 답하기' 불안정의 원인, 2026-11-13).
              key={sp.toString()}
              data={m.isPending ? null : r}
              sample={SAMPLE}
              label="답을 만들고 있어요"
              // 대기 뼈대 높이에서 답 높이로 늘어나는 동안에는 문서가 아직 짧아, 그때 누른 바로 가기가 목적지에 못 미친다.
              onReveal={() => {
                const id = jumpRef.current;
                jumpRef.current = null;
                if (id) document.getElementById(id)?.scrollIntoView();
              }}
            >
              {(res: AskResult) => (
                <div className="flex flex-col gap-4">
                  <Understood key={JSON.stringify(res.understood)} r={res} sample={res === SAMPLE} onChange={(s) => setPicker({ preset: s })} />
                  {res !== SAMPLE && res.answer?.biz_tabs && <BizTabs tabs={res.answer.biz_tabs} onPick={(x) => run({ slots: x.slots }, x.text)} />}
                  {res !== SAMPLE && res.answer?.compare_with && (
                    <CompareWith cw={res.answer.compare_with} onPick={(s, text) => run({ slots: s }, text)} onOther={(preset) => setPicker({ preset })} />
                  )}
                  {/* 문서 23 P5: 폰에서는 결론이 첫 화면에 오게 답 카드를 이해한 내용·업종 탭보다 앞에 둔다 */}
                  <div className="max-md:-order-1">
                    <AnswerCard r={res} sample={res === SAMPLE} />
                  </div>
                  {res !== SAMPLE && res.answer && <Views key={res.question ?? ""} views={res.answer.views} n={res.answer.default_views} />}
                  {/* 이어서 물어보기는 자료 요청·내려받기보다 앞에 둔다(B2) */}
                  {res !== SAMPLE && res.suggestions && (
                    <SuggestionList
                      testId="suggestions"
                      title={res.status === "범위밖" ? "대신 이런 걸 물어볼 수 있어요" : "이어서 물어보기"}
                      items={res.suggestions}
                      onPick={(x) => run({ slots: x.slots }, x.text)}
                    />
                  )}
                  {res !== SAMPLE && res.answer && (
                    <Requests
                      items={res.answer.requests}
                      onCenter={
                        res.understood
                          ? (meta) => {
                              const c = adoptCenter(meta);
                              // A6: 원래 질문 문장과 이해한 칸을 함께 보내 '질문:' 줄이 그대로 남게 한다
                              const original = req.body.question ?? (req.label !== PICK_LABEL ? req.label : (res.question ?? undefined));
                              run({ question: original, slots: res.understood!.slots, dataset_id: c.id, dataset_key: c.key }, req.label);
                            }
                          : undefined
                      }
                    />
                  )}
                  <Process r={res} />
                  <Downloads r={res} />
                  {res !== SAMPLE && <Report r={res} />}
                </div>
              )}
            </Skeleton>
          )}
        </div>
      </div>

      {/* 겹침형 패널: 큰 화면은 왼쪽 단추 자리에서 본문 위로 뜨고, 폰은 화면 아래에서 올라오는 시트다. 열고 닫아도 본문 자리는 그대로다. */}
      <aside ref={pickerRef} aria-label="입력 없이 골라서 묻기" className="max-lg:fixed max-lg:inset-x-0 max-lg:bottom-0 max-lg:z-40 lg:sticky lg:top-20 lg:z-30 lg:order-1">
        <button
          type="button"
          data-testid="panel-open"
          onClick={() => togglePanel(true)}
          className={"hidden min-h-11 items-center gap-2 rounded-(--radius) border border-(--krds-border-gray) bg-card px-3 font-semibold hover:bg-muted lg:flex" + (showPanel ? " lg:invisible" : "")}
          aria-label="조건 패널 펼치기: 입력 없이 골라서 묻기"
          aria-expanded={showPanel}
        >
          <ChevronRight size={18} aria-hidden />
          <span>입력 없이 골라서 묻기</span>
        </button>
        {showPanel && (
          <div className={picker ? "" : "max-lg:hidden"}>
            <div data-testid="panel-backdrop" aria-hidden onClick={closePanel} className="fixed inset-0 -z-10 bg-black/40" />
            <div
              data-testid="panel"
              className="flex max-h-[85dvh] flex-col gap-2 overflow-y-auto rounded-t-(--krds-radius-large1) bg-card shadow-2xl lg:absolute lg:top-0 lg:left-0 lg:max-h-[calc(100vh-6rem)] lg:w-[343px] lg:rounded-(--krds-radius-large1)"
            >
              <button
                type="button"
                data-testid="panel-close"
                onClick={closePanel}
                className="hidden min-h-11 items-center gap-1 self-end rounded-(--radius) px-3 text-(--krds-text-bolder) hover:bg-muted lg:flex"
                aria-label="조건 패널 접기"
              >
                <ChevronLeft size={18} aria-hidden /> 접기
              </button>
              {guide.data && (
                <StepPicker
                  key={JSON.stringify(picker ?? {})}
                  guide={guide.data}
                  preset={picker?.preset}
                  notice={picker?.notice}
                  onSubmit={(s) => {
                    closePanel();
                    run({ slots: s }, PICK_LABEL);
                  }}
                  onClose={closePanel}
                />
              )}
            </div>
          </div>
        )}
      </aside>
    </div>
  );
}
