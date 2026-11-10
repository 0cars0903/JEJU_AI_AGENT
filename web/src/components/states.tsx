"use client";

import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { RotateCwIcon, TriangleAlertIcon } from "@/components/icons";

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "문제가 생겼습니다. 다시 시도해 주세요.";
  return (
    <div role="alert" data-testid="error-state" className="flex flex-col items-start gap-3 rounded-(--radius) border border-(--krds-border-danger,var(--krds-border-gray)) bg-(--krds-surface-danger-subtler) p-4 text-(--krds-text-basic)">
      <p className="flex items-start gap-2 font-semibold">
        <TriangleAlertIcon size={22} className="mt-0.5 shrink-0 text-(--krds-text-danger)" aria-hidden />
        {message}
      </p>
      {onRetry && (
        <Button variant="outline" size="sm" onClick={onRetry}>
          <RotateCwIcon size={18} aria-hidden />
          다시 시도
        </Button>
      )}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: React.ReactNode }) {
  return (
    <Alert className="border-(--krds-border-gray-light) bg-muted p-4" data-testid="empty-state">
      <AlertTitle className="font-semibold">{title}</AlertTitle>
      {children && <AlertDescription className="text-(--krds-text-subtle)">{children}</AlertDescription>}
    </Alert>
  );
}

export function BlockSkeleton({ className }: { className?: string }) {
  return <Skeleton className={className ?? "h-48 w-full"} />;
}
