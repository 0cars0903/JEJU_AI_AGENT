/** 인쇄(PDF) 쪽 나눔 규칙(사용자 지시 2026-11-13: 한 장(지금 상태·분석·부록 등)이 쪽을 넘어가며 잘리지 않게).
 *
 * 1. 장(.report-part)은 안에서 자르지 않는다(CSS break-inside: avoid). 남은 쪽에 안 들어가면 다음 쪽에서 시작한다.
 * 2. 한 쪽보다 긴 장은 어차피 잘린다. 그 장 앞 쪽에 남은 자리가 1/3보다 적으면 새 쪽에서 시작하고(.report-long → break-before: page),
 *    많으면 그 자리에서 이어 쓴다(첫 쪽이 제목만 남고 비는 것을 막음). 길이와 쪽 위치는 인쇄 직전에 재서 흉내 낸다.
 * 3. 첫 부록(.report-appendix)은 늘 새 쪽에서 시작한다. 장 제목 뒤에서는 자르지 않는다(globals.css).
 */

// A4 297mm − 위아래 여백 32mm(globals.css @page) = 본문 265mm. 글자 크기 차이를 생각해 95%를 넘으면 긴 장으로 본다.
const PAGE_MM = 265;
// 210mm − 좌우 여백 12mm − 보고서 안쪽 여백 24mm
const WIDTH_MM = 174;
const PX_PER_MM = 96 / 25.4;

export function markLongParts(root: HTMLElement | null) {
  if (!root) return;
  const prev = root.getAttribute("style");
  // 화면에서는 숨겨져 있어 높이가 0이다. 잠깐 화면 밖에서 인쇄 폭으로 펼쳐 잰다.
  root.style.cssText = `display:block;position:absolute;left:-10000px;top:0;width:${WIDTH_MM}mm;font-size:12pt;visibility:hidden;`;
  const page = PAGE_MM * PX_PER_MM * 0.95;
  const parts = Array.from(root.querySelectorAll<HTMLElement>(".report-part"));
  parts.forEach((el) => el.classList.remove("report-long", "report-big"));
  // 쪽 나눔 흉내: y = 지금 쪽에서 이미 쓴 높이. 장 앞의 머리(제목·한눈에)는 첫 장 위치로 센다.
  let y = parts.length ? parts[0].offsetTop % page : 0;
  for (const el of parts) {
    const h = el.offsetHeight;
    if (h > page) el.classList.add("report-big"); // 한 쪽보다 긴 장은 안에서 잘리도록 허용(그래야 앞 쪽 빈자리를 쓴다)
    if (el.classList.contains("report-appendix")) y = 0;
    else if (h <= page) {
      if (y + h > page) y = 0; // 규칙 1: 안 들어가면 다음 쪽(break-inside: avoid)
    } else if (page - y < page / 3) {
      el.classList.add("report-long"); // 규칙 2: 남은 자리가 적으면 새 쪽에서
      y = 0;
    }
    y = (y + h) % page;
  }
  if (prev === null) root.removeAttribute("style");
  else root.setAttribute("style", prev);
}
