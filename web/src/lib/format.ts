// 보고서·화면 공통 표기(2026-11-16)
/** 기준 시점 문구: 값에 이미 '기준'이 있으면 다시 붙이지 않는다(2026-11-16 보고서 '기준 2025-09-18 기준' 수정) */
export const asOfText = (s?: string | null) => (s ? (/기준$/.test(s) ? ` · ${s}` : ` · 기준 ${s}`) : "");

/** 세는 단위는 숫자에 붙여 쓴다(175곳). 원·지수는 띄운다(백엔드 v3.fmt와 같은 규칙, 2026-11-16) */
export const withUnit = (n: string, unit?: string | null) => (!unit ? n : unit === "%" || unit === "%p" || /^(곳|건|명|개)/.test(unit) ? `${n}${unit}` : `${n} ${unit}`);
