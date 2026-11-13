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
export type Group = { id: string; label: string; topics: string[]; hint?: string };
export type Guide = { topics: Topic[]; groups: Group[]; dongs: string[]; representative: Representative[] };

export type Evidence = { text: string; dataset?: string; as_of?: string; value?: number; unit?: string; dong?: string; metric?: string };
export type Card = { conclusion: string; evidence: Evidence[]; intervals: string[]; limits: string[]; next_questions: string[] };
export type Suggestion = { text: string; slots: Slots };
/** v3 답 구조(docs/기획/v3_설계.md 6절): 내부 L1~L5 → 화면 3블록, 나눠 보기, 신선도, 자료 요청 카드 */
export type Line = { layer: "L1" | "L2" | "L3" | "L4" | "L5"; block: string; tag: string; text: string; source?: string | null; as_of?: string | null; kind?: string | null };
export type Block = { id: "facts" | "analysis" | "guide"; title: string; lines: Line[]; closing?: string };
export type ViewSeries = { name: string; points: [string | number, number | null][] };
export type View = {
  id: string; label: string; kind: "line" | "bar" | "map" | "scatter"; x: string; series: ViewSeries[]; summary: string; definition?: string | null;
  values?: Record<string, number>; unit?: string; highlight?: string[];
  /** 점그래프(기법 분석의 상관·회귀): 점마다 이름(동네·월)과 가로·세로 축 이름 */
  names?: string[]; axes?: string[];
};
export type FooterItem = { source: string; as_of: string; next: string };
export type JejuMapData = { viewBox: [number, number, number, number]; dongs: { dong: string; d: string; cx: number; cy: number; area: number }[]; inset: { x: number; y: number; w: number; h: number; label: string }; attribution: string };
export type SummaryCard = { kind: string; question: string; value: number; unit: string; as_of: string; median: number; rank: number; of: number; slots: Slots; values: Record<string, number> };
export type DongSummary = { dong: string; cards: SummaryCard[] };
export type Freshness = { source: string; as_of: string; months_old: number; stale: boolean };
export type QueryField = { field: string; value: string };
export type DataRequest = { kind: "update" | "center"; title: string; data: string; why: string; where: string; now?: string; steps?: string[]; query?: QueryField[] };
/** 답에 쓰인 모델의 방법·검증 설명(문서 21 3.2절): 화면의 접힌 설명과 인쇄 보고서 부록 A가 함께 쓴다 */
export type Method = { kind: string; title: string; how: string; check: string; result: string; limit: string };
/** 종합 진단 5칸 요약(문서 23, 사람 시험 H3): 수요·매출·경쟁·생존·앞으로 */
export type SummaryCell = { key: string; label: string; name: string; value: string; level: string; note: string; sub?: string };
export type Answer = {
  summary?: SummaryCell[];
  /** 손익분기 계산 칸의 결제 1건당 금액 기본값(문서 23, 사용자 결정 2026-11-12) */
  bep?: { ticket: number; basis: string };
  /** 이 답에 없는 것과 확인할 곳(문서 23) */
  gaps?: { what: string; why: string; where: string }[];
  conclusion: { text: string; layer: string | null; tag: string | null; source?: string | null };
  blocks: Block[];
  views: View[];
  default_views: number;
  value_question: boolean;
  freshness: Freshness[];
  requests: DataRequest[];
  footer?: FooterItem[];
  methods?: Method[];
  /** 종합 진단 답 위의 업종 탭(문서 22 2단계): 그 동네에 가게가 있는 업종만 */
  biz_tabs?: BizTab[];
  /** 업종 단위 안내(카페 질문에 음식점업 전체 매출이 나올 때, 이중 검토 035) */
  notice?: string;
  /** 동네 비교 5절 표(문서 22 3절) */
  compare?: CompareTable;
  /** 종합 진단 → 다른 동네와 비교. 후보는 비슷한 동네 5곳 */
  compare_with?: { dong: string; target: string | null; candidates: { dong: string; slots: Slots; text: string }[] };
};
export type BizTab = { target: string | null; label: string; stores: number | null; note: string | null; slots: Slots; text: string; current: boolean };
export type CompareRow = { label: string; unit: string; texts: [string, string, string]; verdict: string; method: string; p?: number; n?: number; ranks?: [number, number]; ci?: [[number, number], [number, number]] };
export type CompareTable = { dongs: [string, string]; target: string | null; sections: { id: string; title: string; rows: CompareRow[]; note?: string | null }[]; rule: string };
export type Step = { id: string; sub: string; name: string; status: string; metric?: string | null; recipe?: string | null };
export type AskResult = {
  question: string | null;
  status: string;
  understood?: { text: string; by: string; assumed: boolean; slots: Slots; notes?: string[] };
  card?: Card;
  answer?: Answer;
  suggestions?: Suggestion[];
  choose?: { message: string; step: string; candidates: string[]; preset: Slots };
  process?: {
    type?: string; steps: Step[]; data: Record<string, string>; explain?: { text: string; by: string }; relaxed: string[]; unused: string[];
    /** 검수 기록(app/verify.py review): 단계·문제·조치 */
    review?: { stage: string; type: string; detail: string; action: string }[];
    retries?: { sub: number; main: number; total: number };
  };
  downloads?: { kind: "csv" | "chart" | "bundle"; name: string; rows?: number; export?: string; csv?: string }[];
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
export const getMap = () => call<JejuMapData>("/api/map");
export const getSummary = (dong: string) => call<DongSummary>(`/api/summary?dong=${encodeURIComponent(dong)}`);
export type AskBody = { question?: string; slots?: Slots; dataset_id?: string; dataset_key?: string };
export const ask = (body: AskBody) => call<AskResult>("/api/ask", { method: "POST", body: JSON.stringify(body) });

/** F9: 센터에서 받은 CSV를 그대로 보낸다(본문 = 파일, 파일 이름은 머리글). 서버가 칸 이름으로 자료를 알아본다. */
export type DatasetMeta = { id: string; key?: string; dataset: string; label: string; file: string; rows: number; period: [string, string]; dongs: string[]; biz: string[]; problems: string[] };
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

/** A7: 센터 파일 열쇠. 파일 번호·열쇠·이름은 이 탭의 sessionStorage에만 둔다(주소에는 번호만). [처음 화면]에서 지운다. */
export type CenterFile = { id: string; key: string; file: string; label: string };
const DS_KEY = "jeju.center";
export function readCenter(): CenterFile | null {
  try {
    const v = JSON.parse(sessionStorage.getItem(DS_KEY) ?? "null");
    return v && v.id ? (v as CenterFile) : null;
  } catch {
    return null;
  }
}
export function writeCenter(c: CenterFile | null) {
  try {
    if (c) sessionStorage.setItem(DS_KEY, JSON.stringify(c));
    else sessionStorage.removeItem(DS_KEY);
  } catch {
    /* 저장이 막혀도 이번 화면에서는 그대로 쓴다 */
  }
}

/** 전문가 모드(설계 11-2절): Claude가 계획·pandas 코드를 짜고 격리 실행한 결과 */
export type ExpertTable = { title?: string; columns: string[]; rows: (string | number | null)[][] };
export type ExpertSeries = { title?: string; kind?: "line" | "bar" | "scatter"; name?: string; x: (string | number)[]; y: (number | null)[] };
export type ExpertResult = {
  status: "성공" | "실패" | "꺼짐" | "상한" | "오류";
  method?: string;
  plan?: string[];
  code?: string;
  result?: { numbers?: Record<string, number | string | null>; tables?: ExpertTable[]; series?: ExpertSeries[]; notes?: string[] };
  lines?: string[];
  by?: string;
  attempts?: { stage?: string; ok?: boolean; error?: string }[];
  error?: string;
  hint?: string;
  sec?: number;
  usage?: { input_tokens?: number; output_tokens?: number };
};
export type ExpertStatus = { enabled: boolean; available?: boolean; login_required?: boolean; daily_limit: number };
export const getExpertStatus = () => call<ExpertStatus>("/api/expert/status");
/** 데모 로그인(2026-11-13): 계정이 설정된 환경에서만 login_required가 true. 로그인해야 Claude 기능이 켜진다. */
export type Me = { login_required: boolean; logged_in: boolean; id: string | null; claude: boolean };
export const getMe = () => call<Me>("/api/me");
export const login = (id: string, password: string) => call<{ logged_in: boolean; id: string }>("/api/login", { method: "POST", body: JSON.stringify({ id, password }) });
export const logout = () => call<{ logged_in: boolean }>("/api/logout", { method: "POST" });
export const askExpert = (question: string) => call<ExpertResult>("/api/expert", { method: "POST", body: JSON.stringify({ question }) });
