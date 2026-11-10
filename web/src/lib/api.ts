import { z } from "zod";

/** 화면이 실제로 쓰는 필드만 검증한다. 도구별 수치는 tools.py가 정하므로 그대로 통과시킨다. */
const StringList = z.array(z.string());

export const ToolResult = z.looseObject({
  tool: z.string().optional(),
  dong: z.union([z.string(), z.array(z.string())]).optional(),
  summary: StringList.optional(),
  values: z.record(z.string(), z.any()).optional(),
  badges: z.record(z.string(), z.string()).optional(),
  period: z.union([z.record(z.string(), z.string()), z.string()]).optional(),
  sources: StringList.optional(),
  limits: StringList.optional(),
  error: z.string().optional(),
});
export type ToolResult = z.infer<typeof ToolResult>;

export const TraceStep = z.looseObject({ stage: z.string() });
export type TraceStep = z.infer<typeof TraceStep> & Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

export const AskResult = z.looseObject({
  question: z.string(),
  effective_question: z.string().optional(),
  carried_dongs: StringList.optional(),
  backend: z.string(),
  status: z.enum(["ok", "clarify", "out_of_scope", "blocked", "no_data"]),
  answer: z.string(),
  seconds: z.number(),
  trace: z.array(TraceStep),
  limits: StringList,
  sources: StringList,
  tool_results: z.array(ToolResult),
  tool_errors: StringList.optional(),
  process: z
    .looseObject({
      llm_plan: z.boolean().optional(),
      replanned: z.boolean().optional(),
      code_fills: z.number().optional(),
      exec_fixed: z.boolean().optional(),
      tools_ok: z.number().optional(),
      numbers_outside: z.union([z.number(), z.array(z.any())]).optional(),
    })
    .nullish(),
});
export type AskResult = z.infer<typeof AskResult>;

export const Meta = z.object({
  backend: z.string(),
  backend_label: z.string(),
  dongs: StringList,
  categories: StringList,
  metrics: z.array(z.object({ key: z.string(), label: z.string(), unit: z.string() })),
  jeju_survival: z.array(z.object({ year: z.number(), pct: z.number() })),
  jeju_visit: z.record(z.string(), z.number().nullable()),
  pop_days: z.number().nullish(),
  pop_last: z.string().nullish(),
  bus_last: z.string().nullish(),
  rest_last: z.string().nullish(),
});
export type Meta = z.infer<typeof Meta>;

export const MapData = z.object({
  dongs: z.array(
    z.object({ dong: z.string(), lon: z.number(), lat: z.number(), values: z.record(z.string(), z.number().nullable()) }),
  ),
  grid: z.array(z.tuple([z.number(), z.number()])),
});
export type MapData = z.infer<typeof MapData>;

export const DongDetail = z.object({
  profile: ToolResult,
  biz: ToolResult,
  population: ToolResult,
  bus: ToolResult,
  category_biz: ToolResult.optional(),
});
export type DongDetail = z.infer<typeof DongDetail>;

export const CompareData = z.object({
  dongs: StringList,
  rows: z.array(z.object({ label: z.string(), values: z.record(z.string(), z.string()) })),
  profiles: z.array(ToolResult),
  limits: StringList,
});
export type CompareData = z.infer<typeof CompareData>;

/** 서버가 준 안내 문구를 그대로 보여 주려고 따로 둔다. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

async function request<T>(path: string, schema: z.ZodType<T>, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, init);
  } catch {
    throw new ApiError("서버에 연결하지 못했습니다. 프로그램이 켜져 있는지 확인한 뒤 다시 시도해 주세요.", 0);
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = body && typeof body.detail === "string" ? body.detail : "요청을 처리하지 못했습니다. 다시 시도해 주세요.";
    throw new ApiError(detail, res.status);
  }
  const parsed = schema.safeParse(body);
  if (!parsed.success) throw new ApiError("서버 응답 형식이 예상과 달라 표시하지 못했습니다.", res.status);
  return parsed.data;
}

export const api = {
  meta: () => request("/api/meta", Meta),
  map: () => request("/api/map", MapData),
  dong: (dong: string, category?: string) =>
    request(`/api/dong/${encodeURIComponent(dong)}${category ? `?category=${encodeURIComponent(category)}` : ""}`, DongDetail),
  compare: (dongs: string[]) =>
    request(`/api/compare?${dongs.map((d) => `dongs=${encodeURIComponent(d)}`).join("&")}`, CompareData),
  ask: (question: string, contextDongs: string[]) =>
    request("/api/ask", AskResult, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, context_dongs: contextDongs }),
    }),
};
