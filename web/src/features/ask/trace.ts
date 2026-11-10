import type { AskResult, TraceStep } from "@/lib/api";
import { TOOL_NAMES } from "@/lib/content";

const ARG_NAMES: Record<string, string> = {
  dong: "동네", dongs: "동네", category: "업종", user_type: "이용자", metric: "지표", include_weather: "날씨 포함",
  year: "연도", start_year: "시작 연도", end_year: "끝 연도", top: "상위 개수",
};

type Call = { name: string; arguments: Record<string, unknown>; ok?: boolean };

function callText(c: Call): string {
  const val = (v: unknown) => (v === true ? "예" : Array.isArray(v) ? v.join("·") : String(v));
  const order = Object.keys(ARG_NAMES);
  // LLM이 내는 인자 순서와 무관하게 같은 순서로 보여 준다.
  const args = Object.entries(c.arguments ?? {})
    .sort(([a], [b]) => order.indexOf(a) - order.indexOf(b))
    .filter(([, v]) => v !== null && v !== undefined && v !== false && !(Array.isArray(v) && v.length === 0))
    .map(([k, v]) => `${ARG_NAMES[k] ?? k} ${val(v)}`)
    .join(", ");
  return `${TOOL_NAMES[c.name] ?? c.name}(${args})`;
}

const HOW: Record<string, string> = {
  llm_summary: "LLM 요약 + 코드가 쓴 수치 문장",
  rule_fallback: "요약이 검사를 통과하지 못해 코드가 쓴 수치 문장만 표시",
  facts_only: "코드가 쓴 수치 문장",
};

/** 작업 기록 한 단계를 읽을 수 있는 문장으로 옮긴다. 실제 기록에 있는 것만 적는다. */
export function traceLines(t: TraceStep): string[] {
  const s = t.stage;
  const lines: string[] = [];
  if (s === "해석") {
    const r = t.result;
    if (r.scope === "out") return [`범위 밖 질문으로 판정: ${r.kind}`];
    let text = `동네 ${r.dongs.join(", ") || "없음"}`;
    if (r.category) text += ` · 업종 ${r.category}`;
    if (r.user_type) text += ` · 이용자 ${r.user_type}`;
    if (r.weather) text += " · 날씨 포함";
    if (r.years) text += ` · 기간 ${r.years[0]}~${r.years[1]}`;
    return [text];
  }
  if (s === "계획" || s === "재계획") {
    if (t.source === "LLM 실패") return [`LLM 호출 실패(${t.error}): 기본 계획으로 진행`];
    const picked = (t.plan ?? []).filter((p: Call) => p.name in TOOL_NAMES).map(callText);
    lines.push(`LLM이 고른 도구: ${picked.join(" → ") || "없음"}`);
    for (const p of t.problems ?? []) lines.push(`점검에서 찾은 문제: ${p}`);
    return lines;
  }
  if (s === "계획 확정") {
    lines.push((t.plan ?? []).map(callText).join(" → "));
    return lines.concat(t.notes ?? []);
  }
  if (s === "실행" || s === "실행 수정") {
    return (t.calls ?? []).map((c: Call) => `${c.ok ? "성공" : "실패"}: ${callText(c)}`);
  }
  if (s === "검증") {
    lines.push(t.final_problems?.length ? `차단: ${t.final_problems.map(String).join(", ")}` : "수치 대조·표현 검사 통과");
    for (const a of t.attempts ?? []) if ("attempt" in a) lines.push(`요약 ${a.attempt}회차: ${a.error ? `실패(${a.error}), 요약 없이 진행` : a.problems?.length ? "재작성 요청" : "통과"}`);
    return lines;
  }
  if (s === "설명") return [HOW[t.how] ?? String(t.how)];
  return lines;
}

export type StepView = { name: string; text: string; state: "done" | "skipped" | "failed" };

/** 답변 위에 항상 보여 줄 다섯 단계. 거치지 않은 단계는 건너뜀으로 적는다. */
export function processSteps(r: AskResult): StepView[] {
  const it = r.trace[0]?.result as Record<string, any> | undefined; // eslint-disable-line @typescript-eslint/no-explicit-any
  const what = it
    ? [...(it.dongs ?? []), it.category, it.user_type, it.weather ? "비 오는 날" : null, it.years ? `${it.years[0]}~${it.years[1]}년` : null].filter(Boolean).join(" · ") || (it.scope === "out" ? `범위 밖: ${it.kind}` : "동네 미지정")
    : "";
  const pr = r.process;
  if (r.status === "no_data") {
    return [
      { name: "질문 해석", text: what, state: "done" },
      { name: "계획", text: r.trace.some((t) => t.source === "LLM 실패") ? "LLM 호출 실패 → 기본 계획으로 진행" : "계획 확정", state: "done" },
      { name: "실행", text: "도구를 실행했지만 자료 없음", state: "done" },
      { name: "검증", text: "수치가 없어 해당 없음", state: "skipped" },
      { name: "설명", text: "자료가 없는 이유 제시", state: "done" },
    ];
  }
  if (!pr) {
    const reason = r.status === "out_of_scope" ? "범위 밖 질문이라 멈춤" : "되물어야 해서 멈춤";
    return [
      { name: "질문 해석", text: what, state: "done" },
      { name: "계획", text: reason, state: "skipped" },
      { name: "실행", text: "실행하지 않음", state: "skipped" },
      { name: "검증", text: "수치가 없어 해당 없음", state: "skipped" },
      { name: "설명", text: r.status === "out_of_scope" ? "거절 이유와 대안 제시" : "되묻는 문장 제시", state: "done" },
    ];
  }
  const llmFailed = r.trace.some((t) => t.source === "LLM 실패");
  let plan = llmFailed ? "LLM 호출 실패 → 기본 계획으로 진행" : "기본 계획으로 진행";
  if (pr.llm_plan) {
    // 첫 계획 점검에서 찾은 문제 수를 함께 적어, 재계획이 왜 일어났는지 카드만 보고도 알 수 있게 한다.
    const found = ((r.trace.find((t) => t.stage === "계획")?.problems ?? []) as unknown[]).length;
    plan = `LLM 계획 → ${pr.replanned ? `점검(문제 ${found}건) → 재계획` : "점검 통과"}`;
    if (pr.code_fills) plan += ` → 코드가 ${pr.code_fills}건 보충`;
    if (pr.exec_fixed) plan += " → 실행 후 수정";
  }
  // 최종 확정된 도구를 붙인다. 기록에 있는 계획만 쓴다.
  const fixed = (r.trace.find((t) => t.stage === "계획 확정")?.plan ?? []) as Call[];
  const tools = fixed.map((c) => TOOL_NAMES[c.name] ?? c.name).join(" → ");
  if (tools) plan += ` · 확정: ${tools}`;
  const how = r.trace.find((t) => t.stage === "설명")?.how as string | undefined;
  const outside = pr.numbers_outside;
  const failed = Array.isArray(outside) ? outside.length > 0 : Boolean(outside);
  return [
    { name: "질문 해석", text: what, state: "done" },
    { name: "계획", text: plan, state: "done" },
    { name: "실행", text: `도구 ${pr.tools_ok ?? 0}개 · ${r.seconds}초`, state: "done" },
    { name: "검증", text: failed ? "검증 실패" : "도구 결과에 없는 숫자 0건", state: failed ? "failed" : "done" },
    { name: "설명", text: (how && HOW[how]) || "코드가 쓴 수치 문장", state: "done" },
  ];
}

export function askedDongs(r: AskResult): string[] {
  const it = r.trace[0]?.result as { dongs?: string[] } | undefined;
  return it?.dongs ?? [];
}
