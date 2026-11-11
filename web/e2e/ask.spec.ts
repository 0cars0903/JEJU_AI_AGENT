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
    await expect(page.getByRole("heading", { name: "동네에 대해 물어보세요" })).toBeVisible();
  });

  test("④ 대표 질문을 누르면 해석 없이 답한다", async ({ page }) => {
    const rep = page.getByTestId("representative");
    await expect(rep.getByRole("button")).toHaveCount(6);
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

  test("범위 밖 질문은 답하지 않고 대신 물을 수 있는 질문을 보여 준다", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동 임대료 얼마야?");
    await page.getByTestId("ask-submit").click();
    await expect(page.getByTestId("suggestions")).toContainText("대신 이런 걸 물어볼 수 있어요");
    await expect(page.getByTestId("understood")).toHaveCount(0);
  });
});
