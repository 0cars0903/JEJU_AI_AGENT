import { expect, test } from "@playwright/test";
import { expectTexts, gold, noHorizontalScroll, openCase, shot, showAllCases } from "./helpers";

// 요구사항 3절: 각 케이스의 통과 기준 = 수치 정답(독립 계산) + 화면 요소 + 실제 캡처
const CASES: { q: string; elements: string[]; steps?: "stopped" }[] = [
  { q: "Q04", elements: ["process", "answer-panel", "evidence", "chart-open-close", "chart-survival", "follow-ups"] },
  { q: "Q14", elements: ["process", "answer-panel", "evidence", "compare-table"] },
  { q: "Q21", elements: ["process", "answer-panel", "evidence", "chart-visit", "chart-bus"] },
  { q: "Q13", elements: ["process", "answer-panel", "evidence", "chart-bus"] },
  { q: "Q12", elements: ["process", "answer-panel", "evidence", "chart-bus"] },
  { q: "Q05", elements: ["process", "answer-panel", "evidence", "chart-open-close"] },
  { q: "Q19", elements: ["process", "notice-out_of_scope"], steps: "stopped" },
  { q: "Q18", elements: ["process", "notice-clarify"], steps: "stopped" },
  { q: "Q16", elements: ["process", "answer-panel", "evidence", "unranked-table"] },
];

for (const [i, c] of CASES.entries()) {
  test(`케이스 ${String(i + 1)} ${c.q}`, async ({ page }, info) => {
    const g = gold[c.q];
    await page.goto("/");
    await openCase(page, c.q);
    await expect(page.getByRole("heading", { level: 2, name: g.question })).toBeVisible();
    for (const id of c.elements) await expect(page.getByTestId(id).first()).toBeVisible({ timeout: 30_000 });
    await expectTexts(page, g.must, g.mustnot);
    await expect(page.getByTestId("process").locator("li[data-state]")).toHaveCount(5);
    await expect(page.getByTestId("process")).not.toContainText("LLM 호출 실패"); // 키가 무효여도 기본 계획으로 답하므로, 없으면 다른 경로를 시험한 것을 놓친다
    if (c.steps === "stopped") await expect(page.getByTestId("process").locator('li[data-state="skipped"]')).toHaveCount(3);
    else await expect(page.getByTestId("process")).toContainText("도구 결과에 없는 숫자 0건");
    await noHorizontalScroll(page);
    await shot(page, `케이스${i + 1}_${c.q}`, info.project.name);
  });
}

test("첫 화면은 케이스 9개와 질문창으로 시작한다", async ({ page }, info) => {
  await page.goto("/");
  await expect(page.getByTestId("cases")).toBeVisible();
  const more = page.getByRole("button", { name: /대표 질문 \d+개 더 보기/ });
  if (await more.isVisible()) await expect(page.getByTestId("cases").getByRole("button")).toHaveCount(4);
  await showAllCases(page);
  await expect(page.getByTestId("cases").getByRole("button")).toHaveCount(9);
  await expect(page.getByTestId("cases")).not.toContainText("Q04"); // 내부 시험 번호는 화면에 내지 않는다
  await expect(page.getByLabel("무엇이 궁금한가요?")).toBeVisible();
  await noHorizontalScroll(page);
  await shot(page, "첫화면", info.project.name);
});

test("작업 기록 창이 실제 단계를 보여 주고 닫힌다", async ({ page }) => {
  await page.goto("/?q=" + encodeURIComponent(gold.Q04.question));
  await page.getByRole("button", { name: "자세히 보기" }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("상권 진단(동네 애월읍, 업종 카페)");
  await expect(dialog).toContainText("수치 대조·표현 검사 통과");
  await page.keyboard.press("Escape");
  await expect(dialog).toBeHidden();
  await expect(page.getByRole("button", { name: "자세히 보기" })).toBeFocused();
});

test("되묻기 선택지를 누르면 그 동네로 답한다", async ({ page }) => {
  await page.goto("/?q=" + encodeURIComponent(gold.Q18.question));
  await page.getByRole("button", { name: "정방동 상권 어때?" }).click();
  await expect(page.getByTestId("answer-panel")).toContainText("정방동");
});

test("범위 밖 질문의 대안을 누르면 실행한다", async ({ page }) => {
  await page.goto("/?q=" + encodeURIComponent(gold.Q19.question));
  await page.getByRole("button", { name: "노형동 생활 진단해 줘" }).click();
  await expect(page.getByTestId("badges")).toBeVisible();
});

test("앞 동네와 비교를 이어 물으면 비교표가 나온다", async ({ page }) => {
  await page.goto("/?q=" + encodeURIComponent("아라동 생활 진단해 줘"));
  await expect(page.getByTestId("answer-panel")).toBeVisible();
  await page.getByLabel("무엇이 궁금한가요?").fill("이도2동과 비교해 줘");
  await page.getByRole("button", { name: "질문하기", exact: true }).click();
  await expect(page.getByTestId("compare-table")).toContainText(gold.stores["이도2동"].replace("곳", ""));
  await expect(page.getByTestId("carried")).toContainText("아라동");
});

test("이어지는 질문은 앞 동네를 이어받고 그 사실을 알린다", async ({ page }) => {
  await page.goto("/");
  await openCase(page, "Q04");
  await expect(page.getByTestId("answer-panel")).toBeVisible();
  await page.getByLabel("무엇이 궁금한가요?").fill("버스는 어때?");
  await page.getByRole("button", { name: "질문하기", exact: true }).click();
  await expect(page.getByTestId("carried")).toContainText("애월읍");
  await expect(page.getByTestId("chart-bus")).toBeVisible();
  await expect(page.getByTestId("history")).toContainText(gold.Q04.question);
});

test("빈 질문은 보내지 않고 입력창에서 안내한다", async ({ page }) => {
  let asked = false;
  page.on("request", (r) => { if (r.url().includes("/api/ask")) asked = true; });
  await page.goto("/");
  await page.getByRole("button", { name: "질문하기", exact: true }).click();
  await expect(page.locator("#question-error")).toContainText("질문을 입력해 주세요");
  await expect(page.getByLabel("무엇이 궁금한가요?")).toHaveAttribute("aria-invalid", "true");
  expect(asked).toBe(false);
});
