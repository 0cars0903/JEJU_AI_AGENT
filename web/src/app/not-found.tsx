import Link from "next/link";

export default function NotFound() {
  return (
    <div className="flex flex-col gap-3 py-10">
      <h1>페이지를 찾지 못했습니다</h1>
      <p className="text-(--krds-text-subtle)">주소를 확인하거나 첫 화면에서 다시 시작해 주세요.</p>
      <Link href="/">첫 화면으로</Link>
    </div>
  );
}
