import { Suspense } from "react";
import { AskPage } from "@/features/ask/ask-page";

// 결과 주소(?q=…·?s=…)를 읽으므로 Suspense 안에서 그린다(정적 내보내기에서 useSearchParams 사용 조건).
export default function Page() {
  return (
    <Suspense>
      <AskPage />
    </Suspense>
  );
}
