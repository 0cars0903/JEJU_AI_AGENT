import { expect, type Page, test } from "@playwright/test";

// Skullet은 뼈대 → 답 전환 순간(교차 페이드) 결론 복사본을 잠깐 함께 둔다. 하나로 정리된 뒤 내용을 본다.
// 조건 패널 열기: 모바일은 '입력 없이 골라서 묻기', 데스크톱은 늘 열린 패널(사용자가 접었으면 [입력 없이 골라서 묻기]로 펼침)
async function openPicker(page: Page) {
  // 정적 HTML이 먼저 보이고 화면이 나중에 붙으므로, 열릴 때까지 다시 누른다
  await expect(async () => {
    if (await page.getByTestId("step-picker").isVisible()) return;
    if (await page.getByTestId("open-picker").isVisible()) await page.getByTestId("open-picker").click();
    else if (await page.getByTestId("panel-open").isVisible()) await page.getByTestId("panel-open").click();
    await expect(page.getByTestId("step-picker")).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 15000 });
}

// 주제는 묶음(가게 / 손님·매출 / 비교·순위 / 진단·예상)을 먼저 고른 뒤에 보인다(문서 21 6.2절 3단계)
const GROUP: Record<string, string> = {
  stores: "shop", openclose: "shop", market: "shop",
  sales: "people", customers: "people", hourly: "people", visit: "people", rain: "people",
  compare: "compare", bizcompare: "compare", rank: "compare", similar: "compare",
  diagnose: "outlook", forecast: "outlook",
};
async function pickTopic(page: Page, id: string) {
  const chip = page.getByTestId(`topic-${id}`);
  if (!(await chip.isVisible())) await page.getByTestId(`group-${GROUP[id]}`).click();
  await chip.click();
}

async function conclusion(page: Page) {
  await expect(page.locator('[data-testid="conclusion"]')).toHaveCount(1);
  return page.getByTestId("conclusion");
}

// P13 질문 화면 시험(docs/기획/07_화면API명세.md). 기본은 LLM 없는 경로. 녹화: RECORD=1 npx playwright test
test.describe("질문 유도 4가지와 이해 카드", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "제주 상권, 자료로 물어보세요" })).toBeVisible();
    await expect(page.getByTestId("dong-home")).toBeVisible(); // 화면이 붙은 뒤(정적 HTML 단계 제외)
  });

  test("④ 대표 질문을 누르면 해석 없이 답한다", async ({ page }) => {
    const rep = page.getByTestId("representative");
    await expect(rep.getByRole("button")).toHaveCount(4); // 대표 질문 3개 + 더 보기
    await rep.getByTestId("rep-more").click();
    await expect(rep.getByRole("button")).toHaveCount(8); // 7개 + 접기
    await rep.getByRole("button", { name: "노형동 카페 가게는 몇 곳이야?" }).click();
    await expect(await conclusion(page)).toContainText("노형동");
    await expect(page.getByTestId("understood")).toContainText("이렇게 이해했어요");
    await expect(page.getByTestId("understood")).not.toContainText("추정했어요");
    await expect(page.getByTestId("suggestions").getByRole("button")).toHaveCount(3);
  });

  test("① 자유 입력은 추정해서 답하고 [바꾸기]로 단계별 선택을 연다", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동 카페 몇 개야?");
    await page.getByTestId("ask-submit").click();
    await expect(await conclusion(page)).toContainText("노형동");
    await page.getByTestId("understood-change").click();
    const picker = page.getByTestId("step-picker");
    await expect(picker.getByTestId("sum-topic")).toContainText("가게 수"); // 요약 칩에 알아들은 주제가 적힌다
    await expect(picker.getByTestId("dong-노형동")).toHaveAttribute("aria-pressed", "true");
    await picker.getByTestId("dong-연동").click();
    await picker.getByTestId("picker-submit").click();
    await expect(page.getByTestId("conclusion").filter({ hasText: "연동" })).toHaveCount(1); // 전환 중 복사본이 잠깐 둘
  });

  test("동네가 없으면 상황을 알리고 동네 선택으로 넘어간 뒤 다시 묻지 않는다", async ({ page }) => {
    await page.getByTestId("question-input").fill("카페 몇 개야?");
    await page.getByTestId("ask-submit").click();
    await expect(page.getByTestId("choose-notice")).toContainText("동네를 찾지 못했어요");
    await expect(page.getByTestId("choose-notice")).toBeInViewport();
    const picker = page.getByTestId("step-picker");
    await expect(picker.getByTestId("picker-submit")).toBeDisabled();
    await picker.getByTestId("dong-아라동").click();
    await picker.getByTestId("picker-submit").click();
    await expect(await conclusion(page)).toContainText("아라동");
    await expect(page.getByTestId("choose-notice")).toHaveCount(0);
  });

  test("③ 단계별 선택: 궁금한 것 → 필요한 칸만", async ({ page }) => {
    await openPicker(page);
    const picker = page.getByTestId("step-picker");
    await pickTopic(page, "rank");
    await expect(picker.getByText("동네 이름으로 찾기")).toHaveCount(0); // 순위는 동네를 묻지 않는다
    await picker.getByTestId("metric-점포수").click();
    await picker.getByTestId("picker-submit").click();
    await expect(await conclusion(page)).toContainText("점포 수");
  });

  test("② 추천 질문을 누르면 이어서 답한다", async ({ page }) => {
    await page.getByTestId("representative").getByRole("button").first().click();
    await expect(await conclusion(page)).toBeVisible();
    const first = page.getByTestId("suggestions").getByRole("button").first();
    const label = (await first.textContent()) ?? "";
    await first.click();
    await expect(page.getByTestId("asked")).toContainText(label.trim());
    await expect(await conclusion(page)).toBeVisible();
  });

  test("v3: 몇 시에 손님이 많은지는 카드 매출 시간대로 답하고 업종 한계를 밝힌다", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동 카페 몇 시에 손님 많아?");
    await page.getByTestId("ask-submit").click();
    await expect(await conclusion(page)).toContainText("매출이 많은 시간");
    await expect(page.getByText("음식점업 전체 기준", { exact: false }).first()).toBeVisible();
  });

  test("범위 밖 질문은 답하지 않고 대신 물을 수 있는 질문을 보여 준다", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동 임대료 얼마야?");
    await page.getByTestId("ask-submit").click();
    await expect(page.getByTestId("suggestions")).toContainText("대신 이런 걸 물어볼 수 있어요");
    await expect(page.getByTestId("understood")).toHaveCount(0);
  });
});

// v3 답 구조·화면(docs/기획/v3_설계.md 6절, Stageshow 지적 1~9)
test.describe("v3 3블록·나눠 보기·자료 요청·보고서", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("dong-home")).toBeVisible(); // 화면이 붙은 뒤(정적 HTML 단계 제외)
  });

  test("첫 화면: 대표 질문 한 줄 + 동네 한눈에, 결과는 같은 탭 주소 + 새 탭으로 열기", async ({ page }) => {
    await expect(page.getByTestId("representative")).toBeVisible();
    await expect(page.getByTestId("dong-home")).toBeVisible();
    await page.getByTestId("representative").getByRole("button").first().click();
    await expect(await conclusion(page)).toBeVisible();
    await expect(page).toHaveURL(/\?s=/);
    await expect(page.getByTestId("open-new-tab")).toHaveAttribute("target", "_blank");
    await page.goBack();
    await expect(page.getByTestId("dong-home")).toBeVisible();
  });

  test("주제 칩을 다시 누르면 선택이 풀린다", async ({ page }) => {
    await openPicker(page);
    const picker = page.getByTestId("step-picker");
    await pickTopic(page, "stores");
    await expect(picker.getByTestId("topic-stores")).toHaveCount(0); // 주제를 고르면 다음 단계(동네)로 넘어간다
    await picker.getByTestId("sum-topic").click(); // 요약 칩을 누르면 그 단계로 돌아간다
    await expect(picker.getByTestId("topic-stores")).toHaveAttribute("aria-pressed", "true");
    await pickTopic(page, "stores");
    await expect(picker.getByTestId("topic-stores")).toHaveAttribute("aria-pressed", "false");
    await expect(picker.getByTestId("picker-summary")).toHaveCount(0);
    await expect(picker.getByText("동네 이름으로 찾기")).toHaveCount(0);
  });

  test("가치 판단 질문: 판단 재료 블록과 '직접 판단' 맺음말", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동에 카페 차려도 될까?");
    await page.getByTestId("ask-submit").click();
    await expect(await conclusion(page)).toContainText("43개 동네 중");
    await expect(await conclusion(page)).toContainText(/\d+위/); // 결론에 실제 위치(문서 23)
    await expect(page.getByTestId("summary-grid").locator("li")).toHaveCount(5); // 5칸 요약: 수요·매출·경쟁·생존·앞으로
    await expect(page.getByTestId("block-guide")).toContainText("직접 판단");
    await expect(page.getByTestId("block-facts")).toContainText("억 원");
  });

  test("업종 시장 추이: 나눠 보기 칩 3개 + 더 보기, 칩을 누르면 차트가 바뀜", async ({ page }) => {
    await openPicker(page);
    const picker = page.getByTestId("step-picker");
    await pickTopic(page, "market");
    await expect(picker.getByTestId("picker-missing")).toContainText("업종");
    await picker.getByTestId("target-음식점").click();
    await picker.getByTestId("picker-submit").click();
    await expect(await conclusion(page)).toContainText("음식점업");
    const views = page.getByTestId("views");
    await expect(views.getByRole("tab")).toHaveCount(3);
    await views.getByTestId("views-more").click();
    await expect(views.getByTestId("view-index")).toBeVisible();
    await views.getByTestId("view-index").click();
    await expect(views).toContainText("지수");
    await expect(page.getByTestId("view-chart").locator("svg").first()).toBeVisible();
  });

  test("세부 업종 매출: 갱신 요청 카드와 센터 조회 조건(복사) 카드", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동 카페 매출은?");
    await page.getByTestId("ask-submit").click();
    await expect(await conclusion(page)).toBeVisible();
    await expect(page.getByTestId("request-update")).toContainText("data.ijto.or.kr");
    await expect(page.getByTestId("request-center")).toContainText("비알콜 음료점업");
    await expect(page.getByTestId("request-center").getByRole("button", { name: "복사" }).first()).toBeVisible();
  });

  test("보고서: 인쇄용 정리본이 있고 화면에서는 숨김", async ({ page }) => {
    await page.getByTestId("representative").getByRole("button").first().click();
    await expect(await conclusion(page)).toBeVisible();
    await expect(page.getByTestId("print-report")).toBeVisible();
    await expect(page.getByTestId("report")).toBeHidden();
    await page.emulateMedia({ media: "print" });
    await expect(page.getByTestId("report")).toBeVisible();
  });

  test("종합 진단: 방법과 검증 접힌 설명, 인쇄 보고서는 절 구성과 부록", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동 카페 차려도 될까?");
    await page.getByTestId("question-input").press("Enter");
    await expect(await conclusion(page)).toBeVisible();
    const methods = page.getByTestId("methods");
    await expect(methods.locator("li").first()).toBeHidden();
    await methods.locator("summary").click();
    await expect(methods).toContainText("쓸 수 없는 경우");
    await expect(methods).toContainText("7일 전 값을 그대로 쓰는 단순 예상");
    await expect(methods).not.toContainText(/MASE|레시피|관문/);
    const box = await methods.boundingBox();
    expect(box!.x + box!.width).toBeLessThanOrEqual(page.viewportSize()!.width);
    await page.emulateMedia({ media: "print" });
    const report = page.getByTestId("report");
    const titles = await report.locator("h2").allTextContents();
    await expect(page.getByTestId("report-summary").locator("th")).toHaveCount(5); // 첫 쪽은 화면과 같은 5칸 요약(문서 23 H3)
    expect(titles).toEqual(["한눈에", "판단할 때 볼 것", "지금 상태", "앞으로", "업종 생존", "비슷한 동네와 계절", "날씨", "알 수 있는 것과 없는 것", "부록 A. 방법과 검증", "부록 B. 자료 목록과 기준 시점"]);
    await expect(page.getByTestId("report-methods").locator("tbody tr")).toHaveCount(await methods.locator("li").count());
  });

  test("종합 진단 업종 탭: 지금 업종이 골라져 있고, 다른 탭을 누르면 그 업종으로 다시 진단한다(문서 22 2단계)", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동 카페 상권 종합 진단해줘");
    await page.getByTestId("question-input").press("Enter");
    await expect(await conclusion(page)).toBeVisible();
    const tabs = page.getByTestId("biz-tabs");
    await expect(tabs.getByRole("tab", { selected: true })).toContainText("카페");
    await expect(page.getByTestId("biz-tab-note")).toContainText("음식점업 전체");
    await tabs.getByRole("tab", { name: /^숙박/ }).click();
    await expect(page).toHaveURL(/%EC%88%99%EB%B0%95|숙박/);
    await expect(page.getByTestId("biz-tab-note").filter({ hasText: "음식점만" })).toHaveCount(1); // 새 답이 온 뒤
    await expect(page.getByTestId("biz-tab-note")).toHaveCount(1); // 답이 바뀌는 순간의 사본이 정리된 뒤
    await expect(page.getByTestId("biz-tabs").getByRole("tab", { selected: true })).toContainText("숙박");
  });

  test("단순 주제에도 Agent 분석 블록이 붙는다: 비슷한 동네 대비 위치(문서 22 3단계)", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동 카페 가게는 몇 곳이야?");
    await page.getByTestId("question-input").press("Enter");
    await expect(await conclusion(page)).toContainText("175");
    await expect(page.getByTestId("block-analysis")).toContainText("비슷한 동네 5곳");
  });

  test("동네 비교: 종합 진단에서 비슷한 동네 후보를 눌러 5절 표로 견준다(문서 22 3절)", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동 카페 상권 종합 진단해줘");
    await page.getByTestId("question-input").press("Enter");
    await expect(await conclusion(page)).toBeVisible();
    await page.getByTestId("compare-open").click();
    await expect(page.getByTestId("compare-candidate")).toHaveCount(5);
    await page.getByTestId("compare-candidate").filter({ hasText: "연동" }).click();
    await expect(page.getByTestId("compare-table")).toHaveCount(1); // 답이 바뀌는 순간의 사본이 정리된 뒤
    await expect(await conclusion(page)).toContainText("지표로 견줬어요");
    const table = page.getByTestId("compare-table");
    await expect(table.locator("thead")).toContainText("노형동");
    await expect(table.locator("thead")).toContainText("연동");
    for (const title of ["수요", "매출 흐름", "경쟁", "생존", "앞으로"]) await expect(table.getByText(title, { exact: true }).locator("visible=true")).toHaveCount(1);
    await expect(table).not.toContainText(/유망|추천|유리|더 좋/);
    await expect(page.getByTestId("biz-tabs").getByRole("tab", { selected: true })).toContainText("카페");
  });

  test("첫 화면: 동네를 고르면 [종합 진단 보기]로 바로 진단하고, 카페 질문에는 업종 단위 안내가 붙는다(이중 검토 035)", async ({ page }) => {
    await page.getByTestId("home-dong").selectOption("노형동");
    await page.getByTestId("home-diagnose").locator("visible=true").click();
    await expect(await conclusion(page)).toContainText("노형동");
    await expect(page.getByTestId("biz-tabs").getByRole("tab", { selected: true })).toContainText("전 업종");
    await page.getByTestId("biz-tabs").getByRole("tab", { name: /^카페/ }).click();
    await expect(page.getByTestId("biz-notice")).toHaveCount(1);
    await expect(page.getByTestId("biz-notice")).toContainText("카페만의 카드 매출 자료는 없어요");
  });

  test("동네 비교: 자유 입력도 같은 표로 답한다", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동이랑 연동 카페 비교해줘");
    await page.getByTestId("question-input").press("Enter");
    await expect(await conclusion(page)).toContainText("지표로 견줬어요");
    await expect(page.getByTestId("compare-table")).toContainText("차이 있음");
  });

  test("단계별 선택: 자주 찾는 동네 먼저, 고른 칩은 채움, 꺼진 이유 안내", async ({ page }) => {
    await openPicker(page);
    const picker = page.getByTestId("step-picker");
    await pickTopic(page, "stores");
    await expect(picker.getByTestId("picker-missing")).toContainText("동네를 골라 주세요");
    await expect(picker.getByTestId("dong-추자면")).toHaveCount(0);
    await picker.getByTestId("dongs-more").click();
    await expect(picker.getByTestId("dong-추자면")).toBeVisible();
    await picker.getByTestId("dong-추자면").click();
    await expect(picker.getByTestId("dong-추자면")).toHaveAttribute("aria-pressed", "true");
    await expect(picker.getByTestId("picker-missing")).toHaveCount(0);
  });

  test("F9: 센터 CSV를 넣으면 알아보고 그 자료로 다시 계산(746으로 칸 구성 시험)", async ({ page }) => {
    const raw = require("path").resolve(__dirname, "../../data/raw");
    const file = require("fs").readdirSync(raw).find((f: string) => f.includes("주제1") && f.endsWith("_21.csv"));
    await page.getByTestId("question-input").fill("노형동 카페 매출은?");
    await page.getByTestId("ask-submit").click();
    await expect(await conclusion(page)).toBeVisible();
    const card = page.getByTestId("request-center");
    await card.getByTestId("center-file").setInputFiles(require("path").join(raw, file));
    await expect(card.getByTestId("center-meta")).toContainText("허브 746", { timeout: 30000 });
    await card.getByTestId("center-use").click();
    await expect(page.getByTestId("answer-card").first()).toContainText("비알콜 음료점업", { timeout: 20000 }); // 전환 중 복사본이 잠깐 둘
    await expect(page.getByTestId("answer-card")).toHaveCount(1);
    await expect(page.getByTestId("answer-card")).toContainText("이용자 불러옴"); // 결론과 같은 줄은 블록에서 빠지고 출처는 결론 아래(이중 검토 035)
  });

  test("F9: 카드 자료가 아닌 파일은 이유와 다시 받을 방법을 알린다", async ({ page }) => {
    const raw = require("path").resolve(__dirname, "../../data/raw");
    await page.getByTestId("question-input").fill("노형동 카페 매출은?");
    await page.getByTestId("ask-submit").click();
    await expect(await conclusion(page)).toBeVisible();
    await page.getByTestId("request-center").getByTestId("center-file").setInputFiles(require("path").join(raw, "일별시간대별버스승차인원수현황.csv"));
    await expect(page.getByTestId("center-error")).toContainText("다시 받아 주세요");
  });
});

// UI 역설계 적용(docs/조사/19_UI_참고_역설계.md): A 동네 한눈에, B 조건 패널·업종 아이콘, D·F·G·I, 경계 색칠 지도
test.describe("역설계 패턴과 경계 색칠 지도", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("dong-home")).toBeVisible(); // 화면이 붙은 뒤(정적 HTML 단계 제외)
  });

  test("A: 동네 한눈에 카드 3장, 지도로 동네 바꾸기, 카드를 누르면 답", async ({ page }) => {
    const home = page.getByTestId("dong-home");
    await home.getByTestId("home-dong").selectOption("애월읍");
    await expect(home.getByTestId("home-card-visit")).toContainText("43곳 중");
    await expect(home.getByTestId("home-map-focus")).toContainText("애월읍");
    await home.locator('[data-testid="home-map"] path[data-dong="한림읍"]').click();
    await expect(home.getByTestId("home-dong")).toHaveValue("한림읍");
    await home.getByTestId("home-card-stores").click();
    await expect(await conclusion(page)).toContainText("한림읍");
  });

  test("B: 업종 아이콘 타일과 동네 칩으로 고르기", async ({ page }) => {
    await openPicker(page);
    const picker = page.getByTestId("step-picker");
    await pickTopic(page, "sales");
    await expect(picker.getByTestId("picker-map")).toHaveCount(0); // 패널 안 지도는 뺐다(사용자 지시 2026-11-12: 너무 작다)
    await picker.getByTestId("dong-아라동").click();
    await expect(picker.getByTestId("dong-아라동")).toHaveAttribute("aria-pressed", "true");
    await expect(picker.getByTestId("target-카페")).toHaveCount(0); // 한 번에 한 단계만 보인다
    await picker.getByTestId("picker-next").click();
    await picker.getByTestId("target-카페").click();
    await expect(picker.getByTestId("target-카페")).toHaveAttribute("aria-pressed", "true");
    await picker.getByTestId("picker-submit").click();
    await expect(await conclusion(page)).toContainText("아라동");
  });

  test("지도 보기·정의·표로 보기, 바닥 줄, 묶음 내려받기(D·F·G·I)", async ({ page }) => {
    await openPicker(page);
    const picker = page.getByTestId("step-picker");
    await pickTopic(page, "market");
    await picker.getByTestId("target-음식점").click();
    await picker.getByTestId("picker-submit").click();
    await expect(await conclusion(page)).toBeVisible();
    const views = page.getByTestId("views");
    await expect(views.getByTestId("view-jeju-map")).toBeVisible();
    await expect(views.getByTestId("view-definition")).toContainText("=");
    await views.getByTestId("view-biz_yearly").click();
    await views.getByTestId("view-as-table").click();
    await expect(views.getByTestId("view-table")).toContainText("음식점업");
    await expect(page.getByTestId("answer-footer")).toContainText("다음 갱신");
    await expect(page.getByTestId("download-bundle")).toBeVisible();
  });
});


// 사용성 점검 반영(docs/조사/20_페르소나_사용성점검.md): 화면 쪽 A 1~6, B1~B7, C1~C9
const ASK_OK = {
  question: "노형동 카페 가게는 몇 곳이야?",
  status: "성공",
  understood: { text: "이렇게 이해했어요: 노형동 · 카페 — 현황", by: "test", assumed: true, slots: { topic: "stores", space: ["노형동"], target: "카페" }, notes: ["'하귀'는 애월읍으로 읽었어요.", "'스타벅스 옆'처럼 가게 단위 위치는 자료에 없어 노형동 전체 값으로 답해요."] },
  card: { conclusion: "노형동 카페 점포 수는 194 곳이에요.", evidence: [], intervals: [], limits: [], next_questions: [] },
};
const DATASET = { id: "ds1", key: "key1", dataset: "x", label: "카드 이용 자료", file: "센터_카드.csv", rows: 10, period: ["2021-01", "2021-05"], dongs: ["노형동"], biz: ["카페"], problems: [] };

test.describe("사용성 점검 반영", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("dong-home")).toBeVisible();
  });

  test("A1 이해 상자에 주석을 줄마다 보여 주고, C5 [맞아요]는 확인 표시와 초점을 준다", async ({ page }) => {
    await page.route("**/api/ask", (route) => route.fulfill({ json: ASK_OK }));
    await page.getByTestId("question-input").fill("노형동 카페 몇 개야?");
    await page.getByTestId("ask-submit").click();
    const notes = page.getByTestId("understood-notes").locator("li");
    await expect(notes).toHaveCount(2);
    await expect(notes.first()).toContainText("애월읍으로 읽었어요");
    await page.getByTestId("understood-ok").click();
    await expect(page.getByTestId("understood-done")).toContainText("확인했어요");
    await expect(page.getByTestId("understood-done")).toBeFocused();
  });

  test("A7·A6 센터 파일 열쇠를 보내고, 원래 질문과 칸을 함께 다시 계산하며, 이후 질문에도 계속 보낸다", async ({ page }) => {
    const bodies: Record<string, unknown>[] = [];
    await page.route("**/api/ask", (route) => {
      bodies.push(route.request().postDataJSON());
      return route.fulfill({
        json: { ...ASK_OK, answer: { conclusion: { text: "c", layer: null, tag: null }, blocks: [], views: [], default_views: 0, value_question: false, freshness: [], requests: [{ kind: "center", title: "센터 자료로 더 정확하게", data: "카드", why: "w", where: "센터", query: [{ field: "법정동", value: "노형동" }] }] } },
      });
    });
    await page.route("**/api/dataset**", (route) => route.fulfill({ json: DATASET }));
    await page.getByTestId("question-input").fill("노형동 카페 몇 개야?");
    await page.getByTestId("ask-submit").click();
    await page.getByTestId("center-file").setInputFiles({ name: "센터_카드.csv", mimeType: "text/csv", buffer: Buffer.from("a,b\n1,2\n") });
    await page.getByTestId("center-use").click();
    await expect(page.getByTestId("center-using")).toContainText("센터_카드.csv");
    await expect.poll(() => bodies.length).toBe(2);
    expect(bodies[1]).toMatchObject({ question: "노형동 카페 몇 개야?", slots: { topic: "stores" }, dataset_id: "ds1", dataset_key: "key1" });
    expect(page.url()).not.toContain("key1");
    // 새 질문에도 번호와 열쇠를 계속 보낸다
    await page.getByTestId("question-input").fill("연동 카페 몇 개야?");
    await page.getByTestId("ask-submit").click();
    await expect.poll(() => bodies.length).toBe(3);
    expect(bodies[2]).toMatchObject({ question: "연동 카페 몇 개야?", dataset_id: "ds1", dataset_key: "key1" });
    // 빼기
    await page.getByTestId("center-drop-file").click();
    await expect(page.getByTestId("center-using")).toHaveCount(0);
  });

  test("A7 열쇠 없이 d= 주소만 열면 서버 안내 문구와 파일 넣기 카드를 보여 준다", async ({ page }) => {
    await page.route("**/api/ask", (route) => route.fulfill({ status: 422, json: { detail: "센터 파일을 다시 넣어 주세요. 이 브라우저에는 파일이 없어요." } }));
    await page.goto("/?q=" + encodeURIComponent("노형동 카페 몇 개야?") + "&d=ds1");
    await expect(page.getByTestId("error-state")).toContainText("파일을 다시 넣어 주세요");
    await expect(page.getByTestId("need-file").getByTestId("center-file")).toHaveCount(1);
  });

  test("A9 [링크 복사]는 현재 주소를 복사하고 '복사했어요'를 보여 준다", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => {});
    await page.getByTestId("representative").getByRole("button").first().click();
    await expect(await conclusion(page)).toBeVisible();
    await page.getByTestId("copy-link").click();
    await expect(page.getByTestId("copied")).toHaveText("복사했어요");
  });

  test("A10 그래프에 세로 눈금 단위를 적고 표도 억 원 단위로 보여 준다", async ({ page }) => {
    await openPicker(page);
    const picker = page.getByTestId("step-picker");
    await pickTopic(page, "market");
    await picker.getByTestId("target-음식점").click();
    await picker.getByTestId("picker-submit").click();
    await expect(await conclusion(page)).toBeVisible();
    const views = page.getByTestId("views");
    await views.getByTestId("view-biz_yearly").click();
    await expect(views.getByTestId("chart-unit")).toContainText("억 원");
    await views.getByTestId("view-as-table").click();
    await expect(views.getByTestId("view-table")).toBeVisible();
    await expect(views).toContainText("단위: 억 원");
    expect(await views.getByTestId("view-table").innerText()).not.toMatch(/\d{1,3}(,\d{3}){3}/); // 원 단위 원숫자(2,089,958,214)가 없다
  });

  test("겹침형 조건 패널: 열고 닫아도 본문 자리가 그대로이고, 답을 받으면 닫힌다(문서 21 6.2절 1단계)", async ({ page }) => {
    const box = async () => {
      const i = await page.getByTestId("question-input").boundingBox();
      const m = await page.getByTestId("home-map").boundingBox();
      return [i!.x, i!.y + (await page.evaluate(() => window.scrollY)), i!.width, m?.width, m?.height].map((v) => Math.round(v ?? 0));
    };
    await expect(page.getByTestId("home-map")).toBeVisible();
    const closed = await box();
    await openPicker(page);
    await expect(page.getByTestId("panel-backdrop")).toBeVisible();
    expect(await box()).toEqual(closed); // 입력 칸 좌표와 지도 크기가 같다(밀림 0px)
    const panel = await page.getByTestId("panel").boundingBox();
    expect(panel!.height).toBeLessThanOrEqual(page.viewportSize()!.height);
    await pickTopic(page, "stores");
    await expect(page.getByTestId("picker-submit")).toBeInViewport();
    await page.getByTestId("picker-close").or(page.getByTestId("panel-close")).locator("visible=true").first().click();
    await expect(page.getByTestId("step-picker")).toBeHidden();
    expect(await box()).toEqual(closed);
    await openPicker(page);
    await pickTopic(page, "stores");
    await page.getByTestId("dong-노형동").click();
    await page.getByTestId("picker-submit").click();
    await expect(await conclusion(page)).toBeVisible();
    await expect(page.getByTestId("step-picker")).toBeHidden(); // 답을 가리지 않는다
  });

  test("B5 지도는 Tab 정지점이 하나이고 방향키로 옮긴다", async ({ page }, info) => {
    test.skip(info.project.name !== "desktop");
    const map = page.locator('[data-testid="home-map"] path[data-dong]');
    await expect(map.first()).toBeAttached();
    expect(await page.locator('[data-testid="home-map"] path[tabindex="0"]').count()).toBe(1);
    const first = page.locator('[data-testid="home-map"] path[tabindex="0"]');
    const name = await first.getAttribute("data-dong");
    await first.focus();
    await page.keyboard.press("ArrowRight");
    const now = await page.evaluate(() => document.activeElement?.getAttribute("data-dong"));
    expect(now).toBeTruthy();
    expect(now).not.toBe(name);
  });

  test("B5 Tab을 처음부터 눌러 질문 입력 칸까지 10번 안에 닿는다", async ({ page }, info) => {
    test.skip(info.project.name !== "desktop");
    let n = 0;
    for (; n < 12; n++) {
      await page.keyboard.press("Tab");
      if (await page.evaluate(() => document.activeElement?.tagName === "TEXTAREA")) break;
    }
    expect(n + 1).toBeLessThanOrEqual(10);
  });

  test("C1 누를 수 있는 것 위에서 커서가 손가락 모양이고, 지도 구역은 올리면 테두리가 생긴다", async ({ page }, info) => {
    test.skip(info.project.name !== "desktop");
    await page.getByTestId("home-dong").selectOption("노형동"); // 숫자 카드는 동네를 고른 뒤에 나온다
    await openPicker(page);
    for (const loc of [page.getByTestId("rep-more"), page.getByTestId("group-shop"), page.getByTestId("home-card-visit")]) {
      expect(await loc.evaluate((e) => getComputedStyle(e).cursor)).toBe("pointer");
    }
    await page.getByTestId("panel-close").click(); // 겹침형 패널을 닫아야 지도 위에 마우스를 올릴 수 있다
    await page.locator('[data-testid="home-map"] path[data-dong="애월읍"]').hover();
    await expect(page.locator('[data-testid="home-map"] path[fill="none"][stroke="#0b3fa8"]')).toHaveCount(1);
  });

  test("C3·C4 [묻기]를 마우스로 눌러도 초점은 입력 칸에 남고, 입력 칸 글은 '질문:' 줄과 같다", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동 카페 몇 개야?");
    await page.getByTestId("ask-submit").click();
    await expect(await conclusion(page)).toBeVisible();
    await expect(page.getByTestId("question-input")).toBeFocused();
    await page.goBack();
    await page.getByTestId("representative").getByRole("button").first().click();
    await expect(await conclusion(page)).toBeVisible();
    await expect(page.getByTestId("question-input")).toBeFocused();
    const asked = ((await page.getByTestId("asked").textContent()) ?? "").replace("질문: ", "").trim();
    await expect(page.getByTestId("question-input")).toHaveValue(asked);
  });

  test("C6 빈 칸에서 Enter를 누르면 안내를 보여 준다", async ({ page }) => {
    await page.getByTestId("question-input").focus();
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("question-help")).toContainText("질문을 먼저 적어 주세요");
  });

  test("B6 첫 방문에는 동네를 먼저 고르게 하고, 고른 동네는 다음에도 보여 준다", async ({ page }) => {
    // 문서 20 7.5절 7번: 첫 방문에는 다른 동네(노형동) 숫자를 보여 주지 않는다
    await expect(page.getByTestId("home-first")).toContainText("내 동네를 먼저 골라 주세요");
    await expect(page.getByTestId("home-dong")).toHaveValue("");
    await expect(page.locator('[data-testid^="home-card-"]')).toHaveCount(0);
    await expect(page.locator('[data-testid="home-map"] path[aria-pressed="true"]')).toHaveCount(0);
    await page.locator('[data-testid="home-map"] path[data-dong="애월읍"]').click();
    await expect(page.getByTestId("home-dong")).toHaveValue("애월읍");
    await expect(page.getByTestId("home-first")).toHaveCount(0);
    await expect(page.getByTestId("home-card-stores")).toBeVisible();
    await page.reload();
    await expect(page.getByTestId("home-dong")).toHaveValue("애월읍");
    await expect(page.getByTestId("home-card-visit")).toContainText("43곳 중");
  });

  test("B7 인쇄 화면은 보고서만 찍고 첫 쪽 맨 위에서 시작한다", async ({ page }, info) => {
    test.skip(info.project.name !== "desktop");
    await page.getByTestId("representative").getByRole("button").first().click();
    await expect(await conclusion(page)).toBeVisible();
    await page.emulateMedia({ media: "print" });
    const top = await page.getByTestId("report").evaluate((e) => Math.round(e.getBoundingClientRect().top + window.scrollY));
    expect(top).toBeLessThanOrEqual(2);
    await expect(page.getByTestId("report").locator(".recharts-tooltip-wrapper")).toHaveCount(0);
  });

  test("C8 작은 동은 도심 확대로 눌러 고를 수 있다", async ({ page }) => {
    await page.getByTestId("home-map-zoom").getByRole("button", { name: "제주시 도심 확대" }).click();
    const box = await page.locator('[data-testid="home-map"] path[data-dong="일도1동"]').boundingBox();
    expect(Math.min(box!.width, box!.height)).toBeGreaterThanOrEqual(24);
    await page.locator('[data-testid="home-map"] path[data-dong="일도1동"]').click();
    await expect(page.getByTestId("home-dong")).toHaveValue("일도1동");
  });

  // 사용자 지시 2026-11-12: 지도 자유 확대([+]·[−]·끌기·두 손가락 벌리기)
  test("지도 확대: [+ 확대]로 키우고 끌어서 옮긴 뒤 작은 동을 고른다", async ({ page }) => {
    const svg = page.locator('[data-testid="home-map"] svg');
    await page.getByTestId("home-dong").selectOption("이도1동");
    const plus = page.getByTestId("home-map-zoom-in");
    while (await plus.isEnabled()) await plus.click(); // 2 → 4 → 8 → 12배
    await expect(page.getByTestId("home-map-zoom-level")).toContainText("12배");
    const small = page.locator('[data-testid="home-map"] path[data-dong="일도1동"]');
    const box = await small.boundingBox();
    expect(Math.min(box!.width, box!.height)).toBeGreaterThanOrEqual(24);
    // 끌기: 보는 자리가 옮겨지고, 끌기를 끝낸 자리의 동네는 골라지지 않는다
    await svg.scrollIntoViewIfNeeded();
    const before = await svg.getAttribute("viewBox");
    const b = (await svg.boundingBox())!;
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
    await page.mouse.down();
    await page.mouse.move(b.x + b.width / 2 + 20, b.y + b.height / 2 + 80, { steps: 4 }); // 위쪽에 잘려 있던 일도1동을 아래로 끌어 내린다
    await page.mouse.up();
    expect(await svg.getAttribute("viewBox")).not.toBe(before);
    await expect(page.getByTestId("home-dong")).toHaveValue("이도1동");
    await small.click();
    await expect(page.getByTestId("home-dong")).toHaveValue("일도1동");
    await page.getByTestId("home-map-zoom-out").click();
    await expect(page.getByTestId("home-map-zoom-level")).toContainText("6배");
    await page.getByTestId("home-map-zoom-reset").click();
    await expect(svg).toHaveAttribute("viewBox", "0 0 1000 664.6");
    await expect(page.getByTestId("home-map-zoom-out")).toBeDisabled();
  });

  test("지도 확대: 두 손가락을 벌리면 그 자리가 커진다", async ({ page }, info) => {
    test.skip(info.project.name !== "mobile");
    const svg = page.locator('[data-testid="home-map"] svg');
    await svg.scrollIntoViewIfNeeded();
    const b = (await svg.boundingBox())!;
    const cx = b.x + b.width / 2;
    const cy = b.y + b.height / 2;
    const two = (dx: number) => [{ x: cx - dx, y: cy, id: 0 }, { x: cx + dx, y: cy, id: 1 }];
    const cdp = await page.context().newCDPSession(page);
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: two(20) });
    for (const dx of [40, 60, 80]) await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: two(dx) });
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await expect(page.getByTestId("home-map-zoom-level")).toContainText("4배"); // 손가락 사이 40px → 160px
    const [x, y, w] = ((await svg.getAttribute("viewBox")) ?? "").split(" ").map(Number);
    expect(w).toBeCloseTo(250, 0);
    expect(x + w / 2).toBeCloseTo(500, 0); // 벌린 자리(지도 가운데)가 그대로 가운데에 있다
    expect(y).toBeGreaterThan(0);
    await expect(page.getByTestId("home-dong")).toHaveValue(""); // 벌리기는 동네 고르기가 아니다
  });
});

// 사용성 점검 2차 반영(남은 항목): 첫 화면 크기, 바로 가기, 한글 조합, 글자 크기, 대기 화면
test.describe("사용성 점검 2차 반영", () => {
  test("B1 첫 화면에서 지도(스마트폰)와 숫자 카드 세 장(1366×768)이 잘리지 않는다", async ({ page }, info) => {
    if (info.project.name === "desktop") await page.setViewportSize({ width: 1366, height: 768 });
    await page.goto("/");
    await expect(page.locator('[data-testid="home-map"] svg')).toBeVisible();
    const vh = page.viewportSize()!.height;
    const first = await page.locator('[data-testid="home-map"] svg').boundingBox(); // 첫 방문(동네 고르기 안내 + 지도)
    expect(first!.y + first!.height).toBeLessThanOrEqual(vh);
    await page.getByTestId("home-dong").selectOption("노형동");
    await expect(page.getByTestId("home-card-stores")).toBeVisible();
    await page.waitForTimeout(1200); // 숫자 올라가기·안내 글 배치가 끝난 뒤
    const map = await page.locator('[data-testid="home-map"] svg').boundingBox();
    expect(map!.y + map!.height).toBeLessThanOrEqual(vh);
    if (info.project.name === "desktop") {
      const last = await page.getByTestId("home-card-stores").boundingBox();
      expect(last!.y + last!.height).toBeLessThanOrEqual(vh);
    }
  });

  test("B2·B7 답 위쪽 한 줄 바로 가기로 출처·내려받기 칸에 바로 간다", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("question-input").fill("노형동 카페 장사 잘 돼?");
    await page.keyboard.press("Enter");
    const nav = page.getByTestId("answer-shortcuts");
    await expect(nav).toBeVisible();
    await expect(nav).toContainText("출처 보기");
    await expect(nav).toContainText("내려받기");
    const concl = await page.getByTestId("conclusion").boundingBox();
    const navBox = await nav.boundingBox();
    expect(navBox!.y - concl!.y).toBeLessThan(300);
    await nav.getByRole("link", { name: "출처 보기" }).click();
    await expect(page.locator("#answer-source")).toBeInViewport();
    await nav.getByRole("link", { name: "내려받기" }).click();
    await expect(page.locator("#answer-downloads")).toBeInViewport();
  });

  test("C6 한글 조합 중 Enter는 질문을 보내지 않고, 조합이 끝난 뒤 Enter는 보낸다", async ({ page, context }, info) => {
    test.skip(info.project.name !== "desktop"); // CDP 입력기 흉내는 데스크톱에서만
    await page.goto("/");
    await expect(page.getByTestId("dong-home")).toBeVisible();
    let asks = 0;
    page.on("request", (r) => {
      if (r.url().includes("/api/ask")) asks++;
    });
    await page.getByTestId("question-input").click();
    const cdp = await context.newCDPSession(page);
    await cdp.send("Input.imeSetComposition", { text: "노형동", selectionStart: 3, selectionEnd: 3 });
    await cdp.send("Input.dispatchKeyEvent", { type: "rawKeyDown", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13, nativeVirtualKeyCode: 13 });
    await cdp.send("Input.dispatchKeyEvent", { type: "keyUp", key: "Enter", code: "Enter", windowsVirtualKeyCode: 13 });
    await page.waitForTimeout(600);
    expect(asks).toBe(0);
    expect(new URL(page.url()).search).toBe("");
    await cdp.send("Input.insertText", { text: "노형동 카페 가게는 몇 곳이야?" });
    await page.keyboard.press("Enter");
    await expect(page).toHaveURL(/\?q=/);
    await expect.poll(() => asks).toBe(1); // 주소가 바뀐 직후에는 요청이 아직 안 나갔을 수 있어 기다려서 센다
    await page.waitForTimeout(300);
    expect(asks).toBe(1); // 두 번 보내지 않는다
  });

  test("H4 화면 설정은 없고 기본 글자 크기는 '작게'(90%)다", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("dong-home")).toBeVisible();
    await expect(page.getByRole("button", { name: "화면 설정" })).toHaveCount(0);
    const px = await page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));
    expect(px).toBeCloseTo(14.4, 1);
  });

  test("C2 응답이 4초 늦어도 안내 문구·뼈대가 보이고 초점이 입력 칸에 남으며 화면이 밀리지 않는다", async ({ page }) => {
    await page.route("**/api/ask", async (route) => {
      await new Promise((r) => setTimeout(r, 3000));
      await route.continue();
    });
    await page.goto("/");
    await expect(page.getByTestId("dong-home")).toBeVisible();
    await page.getByTestId("question-input").fill("노형동 카페 가게는 몇 곳이야?");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("waiting")).toContainText("자료를 찾아 계산하고 있어요");
    await expect(page.getByTestId("ask-submit")).toHaveAttribute("aria-busy", "true");
    await expect(page.getByTestId("question-input")).toBeFocused();
    const docY = () => page.getByTestId("waiting").evaluate((e) => Math.round(e.getBoundingClientRect().top + window.scrollY));
    await page.waitForTimeout(600); // 결과 위치로 부드럽게 이동하는 동안은 제외
    const y0 = await docY();
    await page.waitForTimeout(1500);
    expect(await docY()).toBe(y0);
    await expect(page.getByTestId("answer-card")).toBeVisible({ timeout: 8000 });
  });

  test("C7 못 알아들으면 조건 패널이 열리고 이유 문구가 보인다", async ({ page }) => {
    await page.goto("/");
    await page.getByTestId("question-input").fill("카페 얼마나 벌어?");
    await page.keyboard.press("Enter");
    await expect(page.getByTestId("choose-notice")).toBeVisible();
    await expect(page.getByTestId("choose-notice")).toContainText("골라 주세요");
  });

  test("한 번에 한 단계만 보이고, 요약 칩을 누르면 그 단계로 돌아간다(문서 21 6.2절 2·4단계)", async ({ page }) => {
    await page.goto("/");
    await openPicker(page);
    const picker = page.getByTestId("step-picker");
    await expect(picker.getByTestId("picker-submit")).toBeDisabled();
    await expect(picker.getByTestId("picker-missing")).toContainText("궁금한 것을 골라 주세요");
    await expect(picker.locator('[data-testid^="group-"]')).toHaveCount(4); // 첫 단계 선택지는 묶음 4개뿐이다(6개 이하)
    await expect(picker.locator('[data-testid^="topic-"]')).toHaveCount(0);
    await pickTopic(page, "sales");
    await expect(picker.getByTestId("topic-stores")).toHaveCount(0); // 주제 단계는 접히고 동네 단계만 보인다
    await expect(picker.getByTestId("sum-space")).toHaveAttribute("aria-current", "step");
    await expect(picker.getByTestId("sum-space")).toContainText("골라 주세요"); // 빠진 칸은 요약 칩에도 적힌다
    await expect(picker.getByTestId("picker-submit")).toBeDisabled();
    await expect(picker.getByTestId("picker-missing")).toContainText("동네를 골라 주세요");
    await picker.getByTestId("dong-노형동").click();
    await expect(picker.getByTestId("sum-space")).toContainText("노형동");
    await expect(picker.getByTestId("picker-submit")).toBeEnabled();
    await picker.getByTestId("picker-next").click();
    await expect(picker.getByTestId("dong-노형동")).toHaveCount(0);
    await picker.getByTestId("target-카페").click();
    await expect(picker.getByTestId("sum-target")).toContainText("카페");
    const panel = await page.getByTestId("panel").boundingBox();
    expect(panel!.height).toBeLessThanOrEqual(page.viewportSize()!.height); // 412×839에서도 패널이 화면 높이 안에 든다
    await expect(picker.getByTestId("picker-submit")).toBeInViewport();
    await picker.getByTestId("sum-space").click();
    await expect(picker.getByTestId("dong-노형동")).toHaveAttribute("aria-pressed", "true");
    await picker.getByTestId("sum-topic").click();
    await expect(picker.getByTestId("topic-sales")).toHaveAttribute("aria-pressed", "true");
    await pickTopic(page, "stores"); // 주제를 바꾸면 동네는 남고 다음 단계로 간다
    await expect(picker.getByTestId("sum-topic")).toContainText("가게 수");
    await expect(picker.getByTestId("dong-노형동")).toHaveAttribute("aria-pressed", "true");
  });
});

// 문서 23 개선(2026-11-12 사용자 실행 지시): 5칸 요약·손익분기 칸·골라서 묻기 안내·AI 고지·출처 번호·인쇄 여백
test.describe("문서 23 답 화면 편의성", () => {
  test("종합 진단: 5칸 요약, 묶음은 접혀 있고 출처는 번호로, 손익분기 예시는 월 700만 원", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("dong-home")).toBeVisible();
    await page.getByTestId("question-input").fill("노형동 상권 종합 진단해줘");
    await page.keyboard.press("Enter");
    await expect(await conclusion(page)).toContainText("43개 동네 중");
    const grid = page.getByTestId("summary-grid");
    await expect(grid.locator("li")).toHaveCount(5);
    await expect(grid).toContainText("결제 건수"); // 매출 칸: 건수·1건당 금액 흐름
    await expect(page.getByTestId("more-facts")).not.toHaveAttribute("open", "");
    await expect(page.getByTestId("src-mark").first()).toBeAttached();
    await expect(page.getByTestId("answer-footer")).toContainText("[1]");
    await expect(page.getByTestId("gaps")).toContainText("임대료·권리금");
    const bep = page.getByTestId("bep");
    await bep.locator("summary").click();
    await expect(bep.getByTestId("bep-empty")).toBeVisible();
    await bep.getByTestId("bep-example").click();
    await expect(bep.getByTestId("bep-result")).toContainText("한 달 700만 원 이상");
    await expect(bep.getByTestId("bep-ticket")).not.toHaveValue("");
  });

  test("폰: 결론이 이해한 내용보다 위에 있다", async ({ page }, info) => {
    test.skip(info.project.name !== "mobile");
    await page.goto("/");
    await page.getByTestId("question-input").fill("노형동 상권 종합 진단해줘");
    await page.keyboard.press("Enter");
    const c = await (await conclusion(page)).boundingBox();
    const u = await page.getByTestId("understood").boundingBox();
    expect(c!.y).toBeLessThan(u!.y);
  });

  test("골라서 묻기: 무엇을 돕는지 한 줄, 묶음 설명, 몇 단계 중 몇 단계", async ({ page }) => {
    await page.goto("/");
    await expect(page.getByTestId("dong-home")).toBeVisible();
    await openPicker(page);
    const picker = page.getByTestId("step-picker");
    await expect(picker.getByTestId("picker-intro")).toContainText("단추로 골라서");
    await picker.getByTestId("group-outlook").click();
    await expect(picker.getByTestId("group-hint")).toContainText("5칸");
    await picker.getByTestId("topic-diagnose").click();
    await expect(picker.getByTestId("picker-step")).toHaveText("3단계 중 2단계");
  });

  test("AI 고지는 첫 화면 맨 아래 작은 글씨, 인쇄에서는 빠지고 보고서에 좌우 여백이 있다", async ({ page }) => {
    await page.goto("/");
    const n = page.getByTestId("ai-notice");
    await expect(n).toContainText("AI");
    const body = await page.evaluate(() => parseFloat(getComputedStyle(document.body).fontSize));
    const small = await n.evaluate((e) => parseFloat(getComputedStyle(e).fontSize));
    expect(small).toBeLessThan(body);
    await page.getByTestId("question-input").fill("노형동 상권 종합 진단해줘");
    await page.keyboard.press("Enter");
    await expect(await conclusion(page)).toBeVisible();
    await page.emulateMedia({ media: "print" });
    await expect(n).toBeHidden();
    const pad = await page.getByTestId("report").evaluate((e) => parseFloat(getComputedStyle(e).paddingLeft));
    expect(pad).toBeGreaterThan(40); // 12mm ≈ 45px: 인쇄 창에서 여백 '없음'을 골라도 남는 여백
  });
});
