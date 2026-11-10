/**
 * 첫 화면 대표 질문. 배열 순서가 시연 순서다(이중 검토 011 추천안).
 * useCase·testCase는 화면에 보이지 않고, docs/기획/01_개발방향.md(U)와 eval/run_eval.py(Q)를 가리킨다.
 */
export type DemoCase = { persona: string; useCase: string; testCase: string; question: string; shows: string };

export const CASES: DemoCase[] = [
  { persona: "예비 창업자", useCase: "U1", testCase: "Q04", question: "애월읍에 카페가 많은 편이야?", shows: "카페 수와 개업·폐업, 영업 지속 곡선을 봅니다" },
  { persona: "상담 직원", useCase: "U6", testCase: "Q14", question: "아라동과 이도2동 비교표 뽑아 줘", shows: "두 동네를 표로 나란히 놓고 A4로 인쇄합니다" },
  { persona: "소상공인", useCase: "U3", testCase: "Q21", question: "연동 오가는 사람 구성이랑 버스는 어떻게 바뀌었나?", shows: "오가는 사람 구성과 버스 이용 변화를 함께 봅니다" },
  { persona: "생활 도민", useCase: "U5", testCase: "Q13", question: "비 오는 날 노형동 버스 이용은?", shows: "비 오는 날과 그렇지 않은 날의 이용 차이를 봅니다" },
  { persona: "생활 도민", useCase: "U4", testCase: "Q12", question: "한림읍 어르신 버스 이용은 얼마나 돼?", shows: "어르신 이용 수와 비중을 봅니다" },
  { persona: "창업자·소상공인", useCase: "U2", testCase: "Q05", question: "최근 2년 노형동 음식점 개업·폐업은?", shows: "연도별 개업·폐업 건수를 봅니다" },
  { persona: "모든 사용자", useCase: "U7", testCase: "Q19", question: "내일 동문시장 매출 얼마나 나올까?", shows: "답할 수 없는 이유와 대신 볼 수 있는 질문을 알려 줍니다" },
  { persona: "모든 사용자", useCase: "되묻기", testCase: "Q18", question: "서귀동 상권 어때?", shows: "동네 이름이 모호하면 어느 동인지 되묻습니다" },
  { persona: "모든 사용자", useCase: "순위 제한", testCase: "Q16", question: "음식점 폐업률 순위 알려줘", shows: "순위를 내지 않는 이유와 확인된 차이를 보여 줍니다" },
];

export const SOURCE_NAMES: Record<string, string> = {
  "793": "상가(상권) 정보",
  "780": "음식점 목록(통합)",
  "583": "읍면동 유동인구",
  "743": "버스정류소 이용",
  "612": "정류소 기본정보",
  "743+612": "버스정류소 이용·정류소 기본정보",
  "579": "일별 기상",
};

export const BADGE_NOTES: Record<string, string> = {
  "상권 규모": "점포 수의 동네 분포 위치",
  "상권 지속": "음식점 5년 생존율",
  "거주 대비 방문": "방문/거주 지수의 분포 위치. 손님 수가 아닙니다",
  대중교통: "버스 일평균의 분포 위치",
};

export const GLOSSARY: { term: string; body: string }[] = [
  { term: "특화계수", body: "그 동네의 업종 비중을 제주 전체 비중으로 나눈 값입니다. 1이면 제주 평균과 같고, 2면 비중이 제주 평균의 2배입니다. 점포 수 자체가 많다는 뜻은 아닙니다." },
  { term: "방문/거주 지수", body: "유동인구 자료의 방문 값을 거주 값으로 나눈 비율입니다. 집계 단위를 확인하지 못해 사람 수로 읽지 않습니다. 거주 값이 큰 동네는 방문이 많아도 낮게 나오며, 손님 수가 아닙니다." },
  { term: "95% 구간", body: "점포 수가 적어 생기는 우연한 변동을 감안한 값의 범위입니다. 해마다 오르내린 폭이 아닙니다." },
  { term: "제주 평균과 뚜렷한 차이가 확인되지 않음", body: "자료가 없다는 뜻이 아닙니다. 값의 차이가 우연한 변동으로도 설명되어 높다·낮다고 말할 수 없다는 뜻입니다. 동네 43곳을 함께 비교할 때 우연히 차이가 나 보이는 경우도 걸러 냈습니다." },
  { term: "상위 25%·중간 50%·하위 25%", body: "섬 지역을 뺀 동네 41곳 안에서의 위치입니다." },
  { term: "5년 생존율", body: "2015-01~2020-08에 개업한 음식점 가운데 5년 뒤 영업 중일 비율의 추정값입니다. 앞으로의 예측이 아닙니다." },
];

export const TOOL_NAMES: Record<string, string> = {
  dong_profile: "동네 요약",
  biz_diagnostic: "상권 진단",
  population_mix: "인구 구성",
  bus_usage: "버스 이용",
  compare_rank: "동네 비교",
};

export function formatMetric(key: string, value: number | null | undefined): string {
  if (value === null || value === undefined) return "자료 없음";
  if (key === "점포수") return `${Math.round(value).toLocaleString("ko-KR")}곳`;
  if (key === "버스일평균") return `${value.toLocaleString("ko-KR", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}명`;
  if (key === "고령비중") return `${value.toFixed(1)}%`;
  return value.toFixed(2);
}
