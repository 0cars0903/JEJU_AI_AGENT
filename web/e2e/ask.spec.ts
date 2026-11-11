import { expect, type Page, test } from "@playwright/test";

// Skullet은 뼈대 → 답 전환 순간(교차 페이드) 결론 복사본을 잠깐 함께 둔다. 하나로 정리된 뒤 내용을 본다.
async function conclusion(page: Page) {
  await expect(page.locator('[data-testid="conclusion"]')).toHaveCount(1);
  return page.getByTestId("conclusion");
}

// P13 질문 화면 시험(docs/기획/07_화면API명세.md). 기본은 LLM 없는 경로. 녹화: RECORD=1 npx playwright test
test.describe("질문 유도 4가지와 이해 카드", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/");
    await expect(page.getByRole("heading", { name: "제주 상권, 자료로 물어보세요" })).toBeVisible();
  });

  test("④ 대표 질문을 누르면 해석 없이 답한다", async ({ page }) => {
    const rep = page.getByTestId("representative");
    await expect(rep.getByRole("button")).toHaveCount(7);
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
    await expect(picker.getByTestId("topic-stores")).toHaveAttribute("aria-pressed", "true");
    await expect(picker.getByTestId("dong-노형동")).toHaveAttribute("aria-pressed", "true");
    await picker.getByTestId("dong-연동").click();
    await picker.getByTestId("picker-submit").click();
    await expect(await conclusion(page)).toContainText("연동");
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
    await page.getByTestId("open-picker").click();
    const picker = page.getByTestId("step-picker");
    await picker.getByTestId("topic-rank").click();
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
  });

  test("첫 화면: 처음이면 이렇게 3단계와 강조된 '하나씩 골라서 묻기'", async ({ page }) => {
    await expect(page.getByTestId("howto")).toBeVisible();
    await expect(page.getByTestId("open-picker")).toBeEnabled();
  });

  test("가치 판단 질문: 판단 재료 블록과 '직접 판단' 맺음말", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동에 카페 차려도 될까?");
    await page.getByTestId("ask-submit").click();
    await expect(await conclusion(page)).toContainText("판단 재료");
    await expect(page.getByTestId("block-guide")).toContainText("직접 판단");
    await expect(page.getByTestId("block-facts")).toContainText("억 원");
  });

  test("업종 시장 추이: 나눠 보기 칩 3개 + 더 보기, 칩을 누르면 차트가 바뀜", async ({ page }) => {
    await page.getByTestId("open-picker").click();
    const picker = page.getByTestId("step-picker");
    await picker.getByTestId("topic-market").click();
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

  test("단계별 선택: 자주 찾는 동네 먼저, 고른 칩은 채움, 꺼진 이유 안내", async ({ page }) => {
    await page.getByTestId("open-picker").click();
    const picker = page.getByTestId("step-picker");
    await picker.getByTestId("topic-stores").click();
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
    await expect(page.getByTestId("block-facts")).toContainText("비알콜 음료점업");
    await expect(page.getByTestId("block-facts")).toContainText("이용자 불러옴");
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
