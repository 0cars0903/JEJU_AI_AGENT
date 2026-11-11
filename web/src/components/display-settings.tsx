"use client";

import { useEffect, useState } from "react";
import { useIconHover } from "@animateicons/react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { SettingsIcon } from "@/components/icons";

const SIZES = [
  { value: 90, label: "작게" },
  { value: 100, label: "보통" },
  { value: 110, label: "조금 크게" },
  { value: 125, label: "크게" },
  { value: 150, label: "가장 크게" },
];
const CONTRASTS = [
  { value: "normal", label: "기본" },
  { value: "high", label: "선명하게" },
];
type Settings = { size: number; contrast: string };
const KEY = "display-settings";

function read(): Settings {
  try {
    return { size: 100, contrast: "normal", ...JSON.parse(localStorage.getItem(KEY) ?? "{}") };
  } catch {
    return { size: 100, contrast: "normal" };
  }
}

function apply(s: Settings) {
  document.documentElement.style.fontSize = `${s.size}%`;
  if (s.contrast === "high") document.documentElement.dataset.contrast = "high";
  else delete document.documentElement.dataset.contrast;
  try {
    localStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    // 저장이 막힌 브라우저에서도 이번 화면에는 적용된다.
  }
}

function Choice({ legend, name, options, value, onChange }: {
  legend: string;
  name: string;
  options: { value: string | number; label: string }[];
  value: string | number;
  onChange: (v: string) => void;
}) {
  return (
    <fieldset>
      <legend className="mb-2 font-semibold">{legend}</legend>
      <div className="flex flex-wrap gap-1.5">
        {options.map((o) => (
          <label
            key={o.value}
            className="flex min-h-10 cursor-pointer items-center rounded-(--radius) border border-(--krds-border-gray) px-3 has-checked:border-(--krds-border-primary) has-checked:bg-(--krds-surface-primary-subtler) has-checked:font-semibold has-focus-visible:outline-2 has-focus-visible:outline-(--krds-border-primary)"
          >
            <input type="radio" className="sr-only" name={name} checked={String(value) === String(o.value)} onChange={() => onChange(String(o.value))} />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function DisplaySettings() {
  const [s, setS] = useState<Settings>({ size: 100, contrast: "normal" });
  const { ref, triggerProps } = useIconHover();
  // localStorage는 브라우저에만 있어 마운트 뒤에 읽는다.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => setS(read()), []);
  const update = (next: Settings) => {
    setS(next);
    apply(next);
  };
  return (
    <Popover>
      <PopoverTrigger render={<Button variant="ghost" size="default" {...triggerProps} />}>
        <SettingsIcon ref={ref} size={20} aria-hidden />
        <span>화면 설정</span>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-80 gap-4 border border-(--krds-border-gray) p-4 text-[length:var(--krds-fs-body-small)]">
        <Choice legend="글자 크기" name="size" options={SIZES} value={s.size} onChange={(v) => update({ ...s, size: Number(v) })} />
        <Choice legend="화면 모드" name="contrast" options={CONTRASTS} value={s.contrast} onChange={(v) => update({ ...s, contrast: v })} />
      </PopoverContent>
    </Popover>
  );
}
