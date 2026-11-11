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
export type Topic = { id: string; label: string; need: string[]; optional: string[]; min_space: number; options: Record<string, Option[]>; variants: Option[] };
export type Representative = { use_case: string; slots: Slots; text: string };
export type Guide = { topics: Topic[]; dongs: string[]; representative: Representative[] };

export type Evidence = { text: string; dataset?: string; as_of?: string; value?: number; unit?: string; dong?: string; metric?: string };
export type Card = { conclusion: string; evidence: Evidence[]; intervals: string[]; limits: string[]; next_questions: string[] };
export type Suggestion = { text: string; slots: Slots };
export type Step = { id: string; sub: string; name: string; status: string; metric?: string | null; recipe?: string | null };
export type AskResult = {
  question: string | null;
  status: string;
  understood?: { text: string; by: string; assumed: boolean; slots: Slots };
  card?: Card;
  suggestions?: Suggestion[];
  choose?: { message: string; step: string; candidates: string[]; preset: Slots };
  process?: { type?: string; steps: Step[]; data: Record<string, string>; explain?: { text: string; by: string }; relaxed: string[]; unused: string[] };
  downloads?: { name: string; rows?: number; export?: string; csv?: string }[];
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
export const ask = (body: { question?: string; slots?: Slots }) => call<AskResult>("/api/ask", { method: "POST", body: JSON.stringify(body) });

/** 주제에 꼭 필요한 칸이 다 골라졌는지(app/guide.py missing과 같은 규칙). */
export function ready(topic: Topic | undefined, s: Slots) {
  if (!topic) return false;
  return topic.need.every((k) => {
    if (k === "space") return (s.space?.length ?? 0) >= topic.min_space;
    return Boolean(s[k as keyof Slots]);
  });
}
