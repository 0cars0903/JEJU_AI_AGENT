import { Suspense } from "react";
import { BlockSkeleton } from "@/components/states";
import { AskView } from "@/features/ask/ask-view";

export default function Page() {
  return (
    <Suspense fallback={<BlockSkeleton className="h-96 w-full" />}>
      <AskView />
    </Suspense>
  );
}
