"""실행 스크립트가 부르는 브라우저 열기(문서 20 A7, 7.5절 4번): 서버가 뜨면 기록을 남기지 않는 창(Edge InPrivate·Chrome 시크릿)으로 화면을 연다.
센터 PC는 여러 방문자가 함께 쓴다. 이 창은 질문 주소를 방문 기록에 남기지 않고, 창을 닫으면 뒤로 가기 목록과 브라우저 저장 값(고른 동네·센터 자료 열쇠)도 지워진다.
사용: python -m app.open_browser [--if-running] [주소]   (--if-running: 서버가 이미 떠 있을 때만 창을 열고 0, 아니면 1)"""
import os
import subprocess
import sys
import time
import urllib.request
import webbrowser

URL = "http://localhost:8501"
WIN = [(r"Microsoft\Edge\Application\msedge.exe", "--inprivate"), (r"Google\Chrome\Application\chrome.exe", "--incognito")]
WIN_ROOTS = ["ProgramFiles(x86)", "ProgramFiles", "LOCALAPPDATA"]
MAC = [("Google Chrome", "--incognito"), ("Microsoft Edge", "--inprivate")]


def command(platform=sys.platform, env=os.environ, exists=os.path.exists):
    """기록을 남기지 않는 창을 여는 명령(주소는 뒤에 붙인다). 쓸 브라우저를 찾지 못하면 None."""
    if platform.startswith("win"):
        for rel, flag in WIN:
            for root in WIN_ROOTS:
                path = os.path.join(env[root], rel) if env.get(root) else None
                if path and exists(path):
                    return [path, flag]
    elif platform == "darwin":
        for name, flag in MAC:
            if exists(f"/Applications/{name}.app"):
                return ["open", "-na", name, "--args", flag]
    return None


def wait(url, sec):
    """서버가 답할 때까지 기다린다. sec초 안에 답하면 True."""
    end = time.time() + sec
    while True:
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/api/health", timeout=2) as r:
                if r.status == 200:
                    return True
        except Exception:
            pass
        if time.time() >= end:
            return False
        time.sleep(0.5)


def main(argv):
    only = "--if-running" in argv
    url = next((a for a in argv if a.startswith("http")), URL)
    if not wait(url, 1 if only else 120):
        if not only:
            print(f"서버가 응답하지 않아 브라우저를 열지 못했어요. 브라우저에서 {url} 을 직접 열어 주세요.")
        return 1
    cmd = command()
    if cmd:
        subprocess.Popen(cmd + [url])
    else:
        webbrowser.open(url)
        print("Edge·Chrome을 찾지 못해 기본 브라우저로 열었어요. 이 창은 방문 기록을 남기니, 방문자가 바뀌면 방문 기록을 지워 주세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
