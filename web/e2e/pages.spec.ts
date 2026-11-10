import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";
import { expectTexts, gold, noHorizontalScroll, openCase, shot } from "./helpers";

test.describe("동네 진단", () => {
  test("기본 동네의 배지·요약·차트 4종과 근거·한계", async ({ page }, info) => {
    await page.goto("/diagnosis/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("노형동 생활 진단");
    await expect(page.getByTestId("badges")).toBeVisible();
    await expectTexts(page, [gold.stores["노형동"]]);
    for (const id of ["detail-summary", "chart-open-close", "chart-survival", "chart-bus", "chart-visit", "map", "evidence"]) await expect(page.getByTestId(id)).toBeVisible();
    await noHorizontalScroll(page);
    await shot(page, "동네진단", info.project.name);
  });

  test("목록에서 동네를 바꾸면 주소와 수치가 함께 바뀐다", async ({ page }) => {
    await page.goto("/diagnosis/");
    await page.getByLabel("동네", { exact: true }).selectOption("연동");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("연동 생활 진단");
    await expect(page).toHaveURL(/dong=/);
    await expectTexts(page, [gold.stores["연동"]]);
  });

  test("지도 원을 누르면 동네가 바뀌고 키보드로도 고를 수 있다", async ({ page }) => {
    await page.goto("/diagnosis/");
    await page.locator('[data-dong="애월읍"]').click();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("애월읍 생활 진단");
    await page.locator('[data-dong="구좌읍"]').focus();
    await page.keyboard.press("Enter");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("구좌읍 생활 진단");
  });

  test("지도 범위와 표시 값을 바꿀 수 있다", async ({ page }, info) => {
    await page.goto("/diagnosis/");
    await page.getByRole("button", { name: "제주시 도심" }).click();
    await expect(page.locator('[data-dong="노형동"] text')).toBeVisible();
    await expect(page.locator('[data-dong="아라동"] text')).toBeVisible();
    await page.getByLabel("지도에 표시할 값").selectOption("버스일평균");
    await expect(page.getByTestId("map-focus")).toContainText("버스 일평균 이용");
    await shot(page, "지도_제주시도심", info.project.name);
  });

  test("방문/거주 지수를 지도에 띄우면 손님 수가 아니라고 알린다", async ({ page }) => {
    await page.goto("/diagnosis/?metric=" + encodeURIComponent("방문거주비"));
    await expect(page.getByTestId("map")).toContainText("손님 수가 아닙니다");
  });

  test("동네 + 업종 창업 진단", async ({ page }) => {
    await page.goto("/diagnosis/?dong=" + encodeURIComponent("애월읍"));
    await page.getByLabel("업종").selectOption("카페");
    await expect(page.getByTestId("startup-summary")).toContainText(gold.Q04.must[0]);
  });

  test("없는 동네 주소는 안내를 보여 준다", async ({ page }) => {
    await page.goto("/diagnosis/?dong=" + encodeURIComponent("없는동"));
    await expect(page.getByTestId("error-state")).toContainText("지명을 찾지 못함");
  });
});

test.describe("동네 비교", () => {
  test("비교표와 근거·한계, 동네 추가와 빼기", async ({ page }, info) => {
    await page.goto("/compare/");
    await expect(page.getByTestId("compare-table")).toContainText(gold.stores["아라동"].replace("곳", ""));
    await expect(page.getByTestId("compare-table")).toContainText(gold.stores["이도2동"].replace("곳", ""));
    await page.getByLabel("동네 추가").selectOption("연동");
    await expect(page.getByTestId("compare-table")).toContainText(gold.stores["연동"].replace("곳", ""));
    await shot(page, "동네비교", info.project.name);
    await page.getByRole("button", { name: "연동 빼기" }).click();
    await page.getByRole("button", { name: "이도2동 빼기" }).click();
    await expect(page.getByTestId("empty-state")).toContainText("2곳 이상");
    await noHorizontalScroll(page);
  });

  test("4곳이 차면 더 고르지 못한다", async ({ page }) => {
    await page.goto("/compare/?dongs=" + encodeURIComponent("아라동,연동,노형동,애월읍"));
    await expect(page.getByLabel("동네 추가")).toBeDisabled();
  });
});

test.describe("오류·로딩", () => {
  test("서버 오류 뒤 다시 시도하면 회복한다", async ({ page }) => {
    let fail = true;
    await page.route("**/api/ask", (route) => (fail ? route.fulfill({ status: 500, json: { detail: "처리 중 문제가 생겼습니다. 잠시 뒤 다시 시도해 주세요." } }) : route.continue()));
    await page.goto("/?q=" + encodeURIComponent(gold.Q04.question));
    await expect(page.getByTestId("error-state")).toContainText("처리 중 문제가", { timeout: 15_000 });
    fail = false;
    await page.getByRole("button", { name: "다시 시도" }).click();
    await expect(page.getByTestId("answer-panel")).toBeVisible();
  });

  test("서버에 연결하지 못하면 안내한다", async ({ page }) => {
    await page.route("**/api/dong/**", (route) => route.abort());
    await page.goto("/diagnosis/");
    await expect(page.getByTestId("error-state")).toContainText("서버에 연결하지 못했습니다", { timeout: 15_000 });
  });

  test("응답을 기다리는 동안 처리 중 화면을 보여 준다", async ({ page }) => {
    await page.route("**/api/ask", async (route) => {
      await new Promise((r) => setTimeout(r, 1500));
      await route.continue();
    });
    await page.goto("/");
    await openCase(page, "Q04");
    await expect(page.getByTestId("pending")).toBeVisible();
    await expect(page.getByTestId("answer-panel")).toBeVisible();
    await expect(page.getByTestId("pending")).toBeHidden();
  });

  test("LLM 호출이 실패하면 기본 계획으로 답하고 실패 사실을 알린다", async ({ page }) => {
    await page.route("**/api/ask", async (route) => {
      const res = await route.fetch();
      const body = await res.json();
      body.trace.splice(1, 0, { stage: "계획", source: "LLM 실패", error: "AuthenticationError" });
      body.process.llm_plan = false;
      await route.fulfill({ response: res, json: body });
    });
    await page.goto("/?q=" + encodeURIComponent(gold.Q04.question));
    await expect(page.getByTestId("process")).toContainText("LLM 호출 실패 → 기본 계획으로 진행");
    await expect(page.getByTestId("answer")).toContainText(gold.Q04.must[0]);
  });

  test("자료가 없으면 도구를 실행했다고 정확히 알린다", async ({ page }) => {
    await page.route("**/api/ask", (route) =>
      route.fulfill({
        json: {
          question: "자료 없는 질문", backend: "rule", status: "no_data", answer: "답할 자료를 찾지 못했습니다.", seconds: 0.1, limits: [], sources: [], tool_results: [],
          trace: [{ stage: "해석", result: { scope: "in", dongs: ["노형동"], category: null, user_type: null, weather: false, years: null } }, { stage: "실행", calls: [] }],
        },
      }),
    );
    await page.goto("/?q=" + encodeURIComponent("자료 없는 질문"));
    await expect(page.getByTestId("notice-no_data")).toContainText("답할 자료를 찾지 못했습니다");
    await expect(page.getByTestId("process")).toContainText("도구를 실행했지만 자료 없음");
  });

  test("요약 실패를 작업 기록에 통과로 적지 않는다", async ({ page }) => {
    await page.route("**/api/ask", async (route) => {
      const res = await route.fetch();
      const body = await res.json();
      body.trace.find((t: { stage: string }) => t.stage === "검증").attempts = [{ attempt: 1, error: "APIError" }];
      await route.fulfill({ response: res, json: body });
    });
    await page.goto("/?q=" + encodeURIComponent(gold.Q04.question));
    await page.getByRole("button", { name: "자세히 보기" }).click();
    await expect(page.getByTestId("trace")).toContainText("요약 1회차: 실패(APIError)");
    await expect(page.getByTestId("trace")).not.toContainText("요약 1회차: 통과");
  });

  test("슬래시 없는 주소와 쿼리로 바로 들어가도 열린다", async ({ page }) => {
    await page.goto("/diagnosis?dong=" + encodeURIComponent("연동"));
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("연동 생활 진단");
    await page.reload();
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("연동 생활 진단");
  });

  test("없는 주소는 안내 페이지를 보여 준다", async ({ page }) => {
    await page.goto("/없는주소/");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("페이지를 찾지 못했습니다");
  });
});

test.describe("화면 설정과 인쇄", () => {
  test("글자 크기와 화면 모드가 새로고침 뒤에도 유지된다", async ({ page }, info) => {
    await page.goto("/");
    await page.getByRole("button", { name: "화면 설정" }).click();
    await page.getByText("크게", { exact: true }).click();
    await page.getByText("선명하게").click();
    await page.keyboard.press("Escape");
    await page.reload();
    expect(await page.evaluate(() => document.documentElement.style.fontSize)).toBe("125%");
    expect(await page.evaluate(() => document.documentElement.dataset.contrast)).toBe("high");
    await noHorizontalScroll(page);
    await shot(page, "선명하게_크게", info.project.name);
  });

  test("가장 큰 글자에서도 가로 스크롤이 없다", async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem("display-settings", JSON.stringify({ size: 150, contrast: "normal" })));
    for (const url of ["/", "/diagnosis/", "/compare/"]) {
      await page.goto(url);
      await expect(page.locator("footer")).toBeVisible();
      await noHorizontalScroll(page);
    }
  });

  test("인쇄 모드에서는 메뉴를 숨기고 수치를 남긴다", async ({ page }, info) => {
    await page.goto("/compare/");
    await expect(page.getByTestId("compare-table")).toBeVisible();
    await page.emulateMedia({ media: "print" });
    await expect(page.locator("header").first()).toBeHidden();
    await expect(page.getByTestId("compare-table")).toBeVisible();
    await expect(page.getByTestId("limits")).toBeVisible();
    // 받은 사람이 언제·무엇으로 만든 종이인지 알 수 있어야 한다.
    await expect(page.getByTestId("print-stamp")).toContainText(/출력일 \d{4}-\d{2}-\d{2}/);
    await expect(page.locator("footer")).toContainText("제주데이터허브");
    await expect(page.getByTestId("llm-path")).toBeHidden();
    await shot(page, "인쇄_비교표", info.project.name);
  });
});

test("네 동네 비교표를 인쇄해도 값이 잘리지 않는다", async ({ page }) => {
  await page.goto("/compare/?dongs=" + encodeURIComponent("아라동,이도2동,노형동,애월읍"));
  await expect(page.getByTestId("compare-table")).toBeVisible();
  await page.setViewportSize({ width: 680, height: 1000 }); // A4 인쇄 폭(여백 제외)
  await page.emulateMedia({ media: "print" });
  const clipped = await page.getByTestId("compare-table").evaluate((el) => {
    const box = el.getBoundingClientRect();
    return [...el.querySelectorAll("th, td")].filter((c) => c.getBoundingClientRect().right > box.right + 0.5 || c.scrollWidth > c.clientWidth + 1).map((c) => c.textContent);
  });
  expect(clipped).toEqual([]);
});

test("인쇄물에 상권·인구·버스 요약과 고른 업종이 들어간다", async ({ page }) => {
  await page.goto("/diagnosis/?category=" + encodeURIComponent("카페"));
  await expect(page.getByTestId("startup-summary")).toBeVisible();
  await page.emulateMedia({ media: "print" });
  await expect(page.getByTestId("detail-summary")).toBeVisible();
  await expect(page.getByTestId("detail-summary")).toContainText("개업");
  await expect(page.getByTestId("startup-summary")).toBeVisible();
  await expect(page.getByLabel("업종")).toBeHidden();
});

test("인쇄 버튼을 누르면 차트를 인쇄 폭으로 다시 그린다", async ({ page }) => {
  await page.addInitScript(() => {
    (window as unknown as { printed: number }).printed = 0;
    window.print = () => {
      (window as unknown as { printed: number }).printed += 1;
    };
  });
  await page.goto("/diagnosis/");
  await expect(page.getByTestId("chart-visit").locator("svg.recharts-surface").first()).toBeVisible();
  await page.getByTestId("print").click();
  await expect.poll(() => page.evaluate(() => (window as unknown as { printed: number }).printed)).toBe(1);
  await page.emulateMedia({ media: "print" });
  await page.setViewportSize({ width: 794, height: 1123 });
  const sizes = await page.evaluate(() =>
    [...document.querySelectorAll('figure[role="img"]')].map((f) => {
      const frame = f.closest("section")!.getBoundingClientRect();
      const svg = f.querySelector(".recharts-wrapper > svg")!.getBoundingClientRect();
      const other = [...document.querySelectorAll('figure[role="img"]')].filter((x) => x !== f).map((x) => x.closest("section")!.getBoundingClientRect());
      return { overflow: svg.right - frame.right, svgHeight: svg.height, inside: svg.bottom <= frame.bottom + 1, overlap: other.some((o) => frame.left < o.right && frame.right > o.left && frame.top < o.bottom && frame.bottom > o.top) };
    }),
  );
  expect(sizes.length).toBe(4);
  for (const v of sizes) {
    expect(v.overflow).toBeLessThanOrEqual(0);
    expect(v.svgHeight).toBeGreaterThan(150);
    expect(v.inside).toBe(true);
    expect(v.overlap).toBe(false);
  }
});

test("외부 주소로 요청하지 않아 인터넷 없이 동작한다", async ({ page, baseURL }) => {
  const outside: string[] = [];
  page.on("request", (r) => {
    if (!r.url().startsWith(baseURL ?? "") && !r.url().startsWith("data:")) outside.push(r.url());
  });
  for (const url of ["/", "/diagnosis/", "/compare/", "/?q=" + encodeURIComponent(gold.Q04.question)]) {
    await page.goto(url);
    await expect(page.locator("footer [data-testid=llm-path]")).toBeVisible();
  }
  await expect(page.getByTestId("answer-panel")).toBeVisible();
  expect(outside).toEqual([]);
});

test.describe("접근성(axe)", () => {
  test.use({ reducedMotion: "reduce" }); // 색 전환 도중의 값을 재지 않게 한다
  for (const [name, url] of [["질문", "/"], ["답변", "/?q=" + encodeURIComponent("노형동 생활 진단해 줘")], ["진단", "/diagnosis/"], ["비교", "/compare/"]] as const) {
    test(`${name} 화면에 심각한 위반이 없다`, async ({ page }) => {
      await page.goto(url);
      await expect(page.locator("footer [data-testid=llm-path]")).toBeVisible();
      if (name === "답변") await expect(page.getByTestId("answer-panel")).toBeVisible();
      if (name === "비교") await expect(page.getByTestId("compare-table")).toBeVisible();
      if (name === "진단") await expect(page.getByTestId("chart-visit")).toBeVisible();
      const { violations } = await new AxeBuilder({ page }).analyze();
      const serious = violations.filter((v) => v.impact === "serious" || v.impact === "critical");
      expect(serious.map((v) => `${v.id}: ${v.nodes.slice(0, 4).map((n) => `${n.target} ${n.any[0]?.message ?? ""}`).join(" | ")}`)).toEqual([]);
    });
  }
});
