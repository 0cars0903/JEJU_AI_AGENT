import { expect, type Page, test } from "@playwright/test";

// Skullet은 뼈대 → 답 전환 순간(교차 페이드) 결론 복사본을 잠깐 함께 둔다. 하나로 정리된 뒤 내용을 본다.
// 조건 패널 열기: 모바일은 '조건으로 묻기', 데스크톱은 늘 열린 패널(사용자가 접었으면 [조건으로 묻기]로 펼침)
async function openPicker(page: Page) {
  // 정적 HTML이 먼저 보이고 화면이 나중에 붙으므로, 열릴 때까지 다시 누른다
  await expect(async () => {
    if (await page.getByTestId("step-picker").isVisible()) return;
    if (await page.getByTestId("open-picker").isVisible()) await page.getByTestId("open-picker").click();
    else if (await page.getByTestId("panel-open").isVisible()) await page.getByTestId("panel-open").click();
    await expect(page.getByTestId("step-picker")).toBeVisible({ timeout: 1000 });
  }).toPass({ timeout: 15000 });
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
    await expect(picker.getByTestId("topic-stores")).toHaveAttribute("aria-pressed", "true");
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
    await picker.getByTestId("topic-stores").click();
    await expect(picker.getByTestId("topic-stores")).toHaveAttribute("aria-pressed", "true");
    await picker.getByTestId("topic-stores").click();
    await expect(picker.getByTestId("topic-stores")).toHaveAttribute("aria-pressed", "false");
    await expect(picker.getByText("동네 이름으로 찾기")).toHaveCount(0);
  });

  test("가치 판단 질문: 판단 재료 블록과 '직접 판단' 맺음말", async ({ page }) => {
    await page.getByTestId("question-input").fill("노형동에 카페 차려도 될까?");
    await page.getByTestId("ask-submit").click();
    await expect(await conclusion(page)).toContainText("43개 동네 가운데 위치");
    await expect(page.getByTestId("block-guide")).toContainText("직접 판단");
    await expect(page.getByTestId("block-facts")).toContainText("억 원");
  });

  test("업종 시장 추이: 나눠 보기 칩 3개 + 더 보기, 칩을 누르면 차트가 바뀜", async ({ page }) => {
    await openPicker(page);
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
    await openPicker(page);
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
    await expect(page.getByTestId("block-facts").first()).toContainText("비알콜 음료점업", { timeout: 20000 }); // 전환 중 복사본이 잠깐 둘
    await expect(page.getByTestId("block-facts")).toHaveCount(1);
    await expect(page.getByTestId("block-facts").first()).toContainText("이용자 불러옴");
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

  test("B: 업종 아이콘 타일과 지도에서 동네 고르기", async ({ page }) => {
    await openPicker(page);
    const picker = page.getByTestId("step-picker");
    await picker.getByTestId("topic-sales").click();
    await picker.getByText("지도에서 고르기").click(); // 지도는 접어 두었다가 펼친다(B3)
    await picker.locator('[data-testid="picker-map"] path[data-dong="아라동"]').click();
    await expect(picker.getByTestId("dong-아라동")).toHaveAttribute("aria-pressed", "true");
    await picker.getByTestId("target-카페").click();
    await expect(picker.getByTestId("target-카페")).toHaveAttribute("aria-pressed", "true");
    await picker.getByTestId("picker-submit").click();
    await expect(await conclusion(page)).toContainText("아라동");
  });

  test("지도 보기·정의·표로 보기, 바닥 줄, 묶음 내려받기(D·F·G·I)", async ({ page }) => {
    await openPicker(page);
    const picker = page.getByTestId("step-picker");
    await picker.getByTestId("topic-market").click();
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
    await picker.getByTestId("topic-market").click();
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

  test("B3·C7 답이 나와도 조건 패널은 저절로 접히지 않고, [이대로 답 보기]는 패널 아래에 붙어 있다", async ({ page }, info) => {
    test.skip(info.project.name !== "desktop");
    await page.getByTestId("representative").getByRole("button").first().click();
    await expect(await conclusion(page)).toBeVisible();
    await expect(page.getByTestId("step-picker")).toBeVisible();
    await page.getByTestId("topic-stores").click();
    await expect(page.getByTestId("picker-submit")).toBeInViewport();
    // 접기를 사용자가 누르면 그 상태를 기억한다(다시 열 때까지)
    await page.getByTestId("panel-close").click();
    await expect(page.getByTestId("panel-open")).toBeVisible();
    await expect(page.getByTestId("panel-open")).toContainText("조건으로 묻기");
    await page.reload();
    await expect(page.getByTestId("panel-open")).toBeVisible();
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
    for (const loc of [page.getByTestId("rep-more"), page.getByTestId("topic-stores"), page.getByTestId("home-card-visit")]) {
      expect(await loc.evaluate((e) => getComputedStyle(e).cursor)).toBe("pointer");
    }
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

  test("C9 글자 크기 '크게'(125%)에서 회색 안내글·지도 글자도 1.25배가 된다", async ({ browser }, info) => {
    test.skip(info.project.name !== "desktop");
    const sizes: Record<number, { help: number; label: number }> = {};
    for (const size of [100, 125]) {
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      await ctx.addInitScript((s) => localStorage.setItem("display-settings", JSON.stringify({ size: s, contrast: "normal" })), size);
      const p = await ctx.newPage();
      await p.goto("/");
      await expect(p.locator('[data-testid="home-map"] svg')).toBeVisible();
      await p.waitForTimeout(800);
      sizes[size] = await p.evaluate(() => ({
        help: parseFloat(getComputedStyle(document.querySelector('[data-testid="question-help"]')!).fontSize),
        label: document.querySelector('[data-testid="home-map"] svg text[pointer-events="none"]')!.getBoundingClientRect().height,
      }));
      await ctx.close();
    }
    expect(sizes[125].help / sizes[100].help).toBeCloseTo(1.25, 1);
    expect(sizes[125].label / sizes[100].label).toBeGreaterThan(1.15);
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

  test("B3 주제를 고르면 주제 목록이 접혀 업종 칸이 스크롤 없이 보인다(1280×900)", async ({ page }, info) => {
    test.skip(info.project.name !== "desktop", "조건 패널이 처음부터 펼쳐진 데스크톱 배치만 본다");
    await page.setViewportSize({ width: 1280, height: 900 });
    await page.goto("/");
    const picker = page.getByTestId("step-picker");
    await picker.getByTestId("topic-sales").click();
    await expect(picker.getByTestId("topic-stores")).toHaveCount(0);
    await expect(picker.getByTestId("topic-sales")).toHaveAttribute("aria-pressed", "true");
    const biz = await picker.getByTestId("target-카페").boundingBox();
    const bar = await picker.getByTestId("picker-actions").boundingBox();
    expect(biz!.y + biz!.height).toBeLessThanOrEqual(bar!.y);
    await picker.getByTestId("topics-more").click();
    await expect(picker.getByTestId("topic-stores")).toBeVisible();
    await picker.getByTestId("topic-stores").click();
    await expect(picker.getByTestId("topic-sales")).toHaveCount(0);
  });
});
