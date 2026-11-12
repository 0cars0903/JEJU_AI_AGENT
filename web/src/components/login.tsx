"use client";

/** 데모 로그인(2026-11-13): 계정이 설정된 데모에서만 보인다. 로그인해야 Claude를 쓰는 기능(판단 과정 AI 설명·전문가 모드)이 켜진다. */
import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import { ApiError, getMe, login, logout } from "@/lib/api";

export function LoginForm({ onDone }: { onDone?: () => void }) {
  const qc = useQueryClient();
  const [id, setId] = useState("");
  const [pw, setPw] = useState("");
  const m = useMutation({
    mutationFn: () => login(id.trim(), pw),
    onSuccess: () => {
      setPw("");
      qc.invalidateQueries();
      onDone?.();
    },
  });
  return (
    <form
      data-testid="login-form"
      className="flex flex-col gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (id.trim() && pw) m.mutate();
      }}
    >
      <label className="flex flex-col gap-1">
        <span>아이디</span>
        <input data-testid="login-id" value={id} onChange={(e) => setId(e.target.value)} autoComplete="username" className="h-11 rounded-(--radius) border border-(--krds-border-gray) px-3" />
      </label>
      <label className="flex flex-col gap-1">
        <span>비밀번호</span>
        <input data-testid="login-pw" type="password" value={pw} onChange={(e) => setPw(e.target.value)} autoComplete="current-password" className="h-11 rounded-(--radius) border border-(--krds-border-gray) px-3" />
      </label>
      {m.isError && (
        <p data-testid="login-error" role="alert" className="text-(--krds-text-danger,#c0392b)">
          {m.error instanceof ApiError ? m.error.message : "로그인하지 못했어요."}
        </p>
      )}
      <Button type="submit" data-testid="login-submit" disabled={!id.trim() || !pw || m.isPending} className="self-start">
        {m.isPending ? "확인하는 중" : "로그인"}
      </Button>
    </form>
  );
}

export function LoginButton() {
  const qc = useQueryClient();
  const me = useQuery({ queryKey: ["me"], queryFn: getMe, retry: false, staleTime: 60_000 });
  const [open, setOpen] = useState(false);
  const out = useMutation({ mutationFn: logout, onSuccess: () => qc.invalidateQueries() });
  if (!me.data?.login_required) return null;
  if (me.data.logged_in)
    return (
      <div className="flex items-center gap-2" data-testid="login-state">
        <span className="text-(--krds-text-subtle)">{me.data.id} 로그인</span>
        <Button variant="outline" size="sm" data-testid="logout" onClick={() => out.mutate()}>
          로그아웃
        </Button>
      </div>
    );
  return (
    <div className="relative">
      <Button variant="outline" size="sm" data-testid="login-open" aria-expanded={open} onClick={() => setOpen((v) => !v)}>
        로그인
      </Button>
      {open && (
        <div className="absolute right-0 z-50 mt-2 w-72 rounded-(--krds-radius-large1) border border-(--krds-border-gray-light) bg-card p-3 shadow-xl">
          <p className="mb-2 text-[length:var(--krds-fs-body-small)] text-(--krds-text-bolder)">로그인하면 AI 설명과 전문가 모드가 켜져요. 질문과 답은 로그인 없이도 쓸 수 있어요.</p>
          <LoginForm onDone={() => setOpen(false)} />
        </div>
      )}
    </div>
  );
}
