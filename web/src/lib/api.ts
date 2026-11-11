/** 화면이 부르는 API(docs/기획/07_화면API명세.md). 같은 주소의 FastAPI(app/api.py)를 부른다. */

export type Slots = {
  topic?: string;
  space?: string[];
  target?: string;
  variant?: string;
  metric?: string;
  keyword?: string;
};

export type Option = { value: string; label: string };
export type Topic = { id: string; label: string; need: string[]; optional: string[]; min_space: number; center_only: boolean; options: Record<string, Option[]>; variants: Option[] };
export type Representative = { use_case: string; slots: Slots; text: string };
export type Guide = { topics: Topic[]; dongs: string[]; representative: Representative[] };

export type Evidence = { text: string; dataset?: string; as_of?: string; value?: number; unit?: string; dong?: string; metric?: string };
export type Card = { conclusion: string; evidence: Evidence[]; intervals: string[]; limits: string[]; next_questions: string[] };
export type Suggestion = { text: string; slots: Slots };
/** v3 답 구조(docs/기획/v3_설계.md 6절): 내부 L1~L5 → 화면 3블록, 나눠 보기, 신선도, 자료 요청 카드 */
export type Line = { layer: "L1" | "L2" | "L3" | "L4" | "L5"; block: string; tag: string; text: string; source?: string | null; as_of?: string | null; kind?: string | null };
export type Block = { id: "facts" | "analysis" | "guide"; title: string; lines: Line[]; closing?: string };
export type ViewSeries = { name: string; points: [string | number, number | null][] };
export type View = { id: string; label: string; kind: "line" | "bar"; x: string; series: ViewSeries[]; summary: string };
export type Freshness = { source: string; as_of: string; months_old: number; stale: boolean };
export type QueryField = { field: string; value: string };
export type DataRequest = { kind: "update" | "center"; title: string; data: string; why: string; where: string; now?: string; steps?: string[]; query?: QueryField[] };
export type Answer = {
  conclusion: { text: string; layer: string | null; tag: string | null };
  blocks: Block[];
  views: View[];
  default_views: number;
  value_question: boolean;
  freshness: Freshness[];
  requests: DataRequest[];
};
export type Step = { id: string; sub: string; name: string; status: string; metric?: string | null; recipe?: string | null };
export type AskResult = {
  question: string | null;
  status: string;
  understood?: { text: string; by: string; assumed: boolean; slots: Slots };
  card?: Card;
  answer?: Answer;
  suggestions?: Suggestion[];
  choose?: { message: string; step: string; candidates: string[]; preset: Slots };
  process?: { type?: string; steps: Step[]; data: Record<string, string>; explain?: { text: string; by: string }; relaxed: string[]; unused: string[] };
  downloads?: { kind: "csv" | "chart"; name: string; rows?: number; export?: string; csv?: string }[];
  sec?: number;
};

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) } });
  if (!res.ok) {
    let msg = "문제가 생겼습니다. 다시 시도해 주세요.";
    try {
      const body = await res.json();
      if (typeof body?.detail === "string") msg = body.detail;
    } catch {
      /* 본문이 JSON이 아니면 기본 문구 */
    }
    throw new ApiError(res.status, msg);
  }
  return res.json() as Promise<T>;
}

export const getGuide = () => call<Guide>("/api/guide");
export const ask = (body: { question?: string; slots?: Slots; dataset_id?: string }) => call<AskResult>("/api/ask", { method: "POST", body: JSON.stringify(body) });

/** F9: 센터에서 받은 CSV를 그대로 보낸다(본문 = 파일, 파일 이름은 머리글). 서버가 칸 이름으로 자료를 알아본다. */
export type DatasetMeta = { id: string; dataset: string; label: string; file: string; rows: number; period: [string, string]; dongs: string[]; biz: string[]; problems: string[] };
export async function uploadDataset(file: File, check: { dong?: string; biz?: string }) {
  const q = new URLSearchParams();
  if (check.dong) q.set("check_dong", check.dong);
  if (check.biz) q.set("check_biz", check.biz);
  return call<DatasetMeta>(`/api/dataset?${q}`, { method: "POST", body: file, headers: { "Content-Type": "text/csv", "X-Filename": encodeURIComponent(file.name) } });
}

/** 주제에 꼭 필요한 칸이 다 골라졌는지(app/guide.py missing과 같은 규칙). */
export function ready(topic: Topic | undefined, s: Slots) {
  if (!topic) return false;
  return topic.need.every((k) => {
    if (k === "space") return (s.space?.length ?? 0) >= topic.min_space;
    return Boolean(s[k as keyof Slots]);
  });
}
