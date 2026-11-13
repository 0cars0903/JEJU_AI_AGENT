"use client";

/** 접힌 사이드바 아이콘 말풍선(사용자 요청 2026-11-13: 펼친 상태에서는 띄우지 않음).
 * 마우스를 올리거나 키보드 초점이 오면 오른쪽에 바로 뜬다. 사이드바가 넘침을 잘라 내므로 화면 기준(fixed) 자리에 그린다.
 * 이름은 단추 안 sr-only 글로 이미 읽히므로 말풍선은 화면 읽기 프로그램에서 숨긴다. */
import { useState } from "react";

export function Tip({ text, on, children }: { text: string; on: boolean; children: React.ReactNode }) {
  const [at, setAt] = useState<{ x: number; y: number } | null>(null);
  if (!on) return <>{children}</>;
  const show = (e: React.SyntheticEvent<HTMLElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setAt({ x: r.right + 8, y: r.top + r.height / 2 });
  };
  return (
    <span className="block" onMouseEnter={show} onMouseLeave={() => setAt(null)} onFocus={show} onBlur={() => setAt(null)}>
      {children}
      {at && (
        <span
          data-testid="tip"
          aria-hidden
          style={{ left: at.x, top: at.y }}
          className="pointer-events-none fixed z-[60] -translate-y-1/2 whitespace-nowrap rounded-(--radius) bg-(--krds-text-basic,#1e2124) px-2 py-1 text-[length:var(--krds-fs-body-small)] text-white shadow-lg"
        >
          {text}
        </span>
      )}
    </span>
  );
}
