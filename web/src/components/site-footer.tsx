export function SiteFooter() {
  return (
    <footer className="border-t border-(--krds-border-gray-light) bg-muted text-[length:var(--krds-fs-body-small)] text-(--krds-text-subtle) print:break-inside-avoid print:bg-transparent print:text-black">
      <div className="mx-auto flex w-full max-w-[75rem] flex-col gap-1 px-4 py-6 md:px-6 print:px-0 print:py-3">
        <p>자료 출처: 제주데이터허브(유동인구·카드 매출 746·외국인 유동인구), 제주관광공사 제주관광빅데이터플랫폼(카드 소비), 공공데이터포털(상가·음식점 인허가·기상). 수치 문장은 LLM이 아니라 코드가 씁니다.</p>
      </div>
    </footer>
  );
}
