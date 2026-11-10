"use client";

import { useIconHover } from "@animateicons/react";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogTrigger } from "@/components/ui/dialog";
import { BookOpenIcon } from "@/components/icons";
import { GLOSSARY } from "@/lib/content";

export function GlossaryButton({ variant = "outline" }: { variant?: "outline" | "ghost" }) {
  const { ref, triggerProps } = useIconHover();
  return (
    <Dialog>
      <DialogTrigger render={<Button variant={variant} size="sm" {...triggerProps} className="print:hidden" />}>
        <BookOpenIcon ref={ref} size={18} aria-hidden />
        용어 풀이
      </DialogTrigger>
      <DialogContent className="sm:max-w-[35rem]">
        <DialogHeader>
          <DialogTitle className="text-[length:var(--krds-fs-heading-medium)] font-bold">용어 풀이</DialogTitle>
        </DialogHeader>
        <dl className="flex flex-col gap-4">
          {GLOSSARY.map((g) => (
            <div key={g.term}>
              <dt className="font-semibold">{g.term}</dt>
              <dd className="mt-0.5 text-(--krds-text-subtle)">{g.body}</dd>
            </div>
          ))}
        </dl>
      </DialogContent>
    </Dialog>
  );
}
