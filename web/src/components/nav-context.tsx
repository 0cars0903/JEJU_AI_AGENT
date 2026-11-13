"use client";

/** 사이드바와 질문 화면이 함께 쓰는 상태(2026-11-13, 사이드바 안 1).
 * - 질문 화면이 '골라서 묻기 열기'를 등록하면 사이드바가 부른다.
 * - 지금 화면에 답이 있는지(hasAnswer)와 센터 자료 요청 카드가 있는지를 사이드바 '이 답' 묶음이 본다.
 * - 폰 서랍(drawer)과 PC 접힘(collapsed)을 머리말 ☰·사이드바 단추가 함께 바꾼다.
 *   접힘은 저장하지 않는다: 공용 센터 PC에서 앞사람이 접어 두면 뒷사람이 메뉴를 못 찾는다(이중 검토 040). 새로 열면 늘 펼침. */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

type Answer = { hasAnswer: boolean; hasCenter: boolean; dong?: string };
type Nav = {
  answer: Answer;
  setAnswer: (a: Answer) => void;
  openPicker: () => void;
  registerPicker: (fn: (() => void) | null) => void;
  drawer: boolean;
  setDrawer: (v: boolean) => void;
  collapsed: boolean;
  setCollapsed: (v: boolean) => void;
};

const Ctx = createContext<Nav | null>(null);

export function NavProvider({ children }: { children: React.ReactNode }) {
  const [answer, setAnswer] = useState<Answer>({ hasAnswer: false, hasCenter: false });
  const [drawer, setDrawer] = useState(false);
  const [collapsed, setCollapsedState] = useState(false);
  const picker = useRef<(() => void) | null>(null);
  const setCollapsed = useCallback((v: boolean) => setCollapsedState(v), []);
  // KRDS·shadcn과 같은 단축키: Ctrl/Cmd+B로 사이드바를 접고 편다(폰에서는 서랍을 연다).
  useEffect(() => {
    const key = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        if (window.matchMedia("(min-width: 1024px)").matches) setCollapsed(!collapsed);
        else setDrawer(!drawer);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [collapsed, drawer, setCollapsed]);
  const value = useMemo<Nav>(
    () => ({
      answer,
      setAnswer,
      openPicker: () => picker.current?.(),
      registerPicker: (fn) => {
        picker.current = fn;
      },
      drawer,
      setDrawer,
      collapsed,
      setCollapsed,
    }),
    [answer, drawer, collapsed, setCollapsed],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useNav() {
  const v = useContext(Ctx);
  if (!v) throw new Error("NavProvider 밖에서 useNav를 썼어요");
  return v;
}
