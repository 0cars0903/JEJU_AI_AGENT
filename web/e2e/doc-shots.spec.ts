import path from "node:path";
import { expect, test } from "@playwright/test";
import { gold } from "./helpers";

// 제출 문서(docs/제출/build_docs.py)에 들어가는 캡처. 화면을 고치면 함께 갱신된다.
const OUT = path.resolve(__dirname, "../../docs/제출/화면");
const CLIP = { x: 0, y: 0, width: 1280, height: 1000 };

test("제출 문서 캡처", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "문서에는 데스크톱 화면만 넣는다");
  await page.goto("/?q=" + encodeURIComponent(gold.Q04.question));
  await expect(page.getByTestId("chart-survival").locator(".recharts-wrapper > svg")).toBeVisible();
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(1200);
  await page.screenshot({ path: path.join(OUT, "질문_답변.png"), fullPage: true, clip: CLIP });
  await page.goto("/diagnosis/");
  await expect(page.getByTestId("chart-visit").locator(".recharts-wrapper > svg")).toBeVisible();
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, "동네진단.png"), fullPage: true, clip: CLIP });
});

// 기획서 PPTX(docs/제출/build_pptx.py)에 넣는 실제 결과물. 꾸민 화면이 아니라 실행한 그대로를 찍는다.
test("기획서 결과물 캡처", async ({ page }, info) => {
  test.skip(info.project.name !== "desktop", "문서에는 데스크톱 화면만 넣는다");
  test.setTimeout(120_000);
  await page.goto("/?q=" + encodeURIComponent(gold.Q21.question));
  await expect(page.getByTestId("answer-panel")).toBeVisible({ timeout: 60_000 });
  await page.waitForTimeout(1500); // 단계 아이콘 애니메이션이 끝난 뒤 찍는다
  await page.getByTestId("process").screenshot({ path: path.join(OUT, "작업과정.png") });
  await page.getByTestId("answer-panel").screenshot({ path: path.join(OUT, "답변.png") });
  await page.getByRole("button", { name: "자세히 보기" }).click();
  await expect(page.getByTestId("trace")).toBeVisible();
  await page.waitForTimeout(500);
  await page.getByRole("dialog").screenshot({ path: path.join(OUT, "작업기록.png") });
  await page.keyboard.press("Escape");
  await page.goto("/?q=" + encodeURIComponent(gold.Q19.question));
  await expect(page.getByTestId("notice-out_of_scope")).toBeVisible({ timeout: 60_000 });
  await page.getByTestId("notice-out_of_scope").screenshot({ path: path.join(OUT, "범위밖.png") });
  await page.goto("/compare/?dongs=" + encodeURIComponent("아라동,이도2동"));
  await expect(page.getByTestId("compare-table")).toBeVisible();
  await page.waitForTimeout(800);
  await page.getByTestId("compare-table").screenshot({ path: path.join(OUT, "비교표.png") });
  await page.emulateMedia({ media: "print" });
  await page.setViewportSize({ width: 794, height: 1123 }); // A4 비율
  await page.waitForTimeout(800);
  await page.screenshot({ path: path.join(OUT, "인쇄_비교.png"), fullPage: false });
});
