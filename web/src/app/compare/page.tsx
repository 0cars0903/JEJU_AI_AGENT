import type { Metadata } from "next";
import { Suspense } from "react";
import { BlockSkeleton } from "@/components/states";
import { CompareView } from "@/features/compare/compare-view";

export const metadata: Metadata = { title: "동네 비교 | 동네 생활 진단" };

export default function Page() {
  return (
    <Suspense fallback={<BlockSkeleton className="h-96 w-full" />}>
      <CompareView />
    </Suspense>
  );
}
