"""실행 스크립트의 브라우저 열기 시험(문서 20 A7): 기록을 남기지 않는 창을 여는 명령을 고르는지 확인한다. 브라우저는 실제로 띄우지 않는다.
실행: .venv/bin/python -m unittest tests.test_open_browser"""
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "app"))
import open_browser as B  # noqa: E402

ENV = {"ProgramFiles(x86)": r"C:\Program Files (x86)", "ProgramFiles": r"C:\Program Files", "LOCALAPPDATA": r"C:\Users\u\AppData\Local"}


class Command(unittest.TestCase):
    def test_windows_prefers_edge_inprivate(self):
        cmd = B.command("win32", ENV, lambda p: True)
        self.assertTrue(cmd[0].endswith("msedge.exe"))
        self.assertEqual(cmd[1], "--inprivate")

    def test_windows_falls_back_to_chrome_incognito(self):
        cmd = B.command("win32", ENV, lambda p: p.endswith("chrome.exe") and "Local" in p)
        self.assertTrue(cmd[0].startswith(ENV["LOCALAPPDATA"]))
        self.assertEqual(cmd[1], "--incognito")

    def test_mac_and_none(self):
        self.assertEqual(B.command("darwin", {}, lambda p: "Google Chrome" in p), ["open", "-na", "Google Chrome", "--args", "--incognito"])
        self.assertIsNone(B.command("win32", {}, lambda p: True))  # 환경 변수가 없으면 찾지 않는다
        self.assertIsNone(B.command("linux", ENV, lambda p: True))


class Main(unittest.TestCase):
    def test_if_running_does_nothing_when_server_is_down(self):
        with mock.patch.object(B, "wait", return_value=False), mock.patch.object(B.subprocess, "Popen") as popen, mock.patch.object(B.webbrowser, "open") as wb:
            self.assertEqual(B.main(["--if-running", "http://localhost:8501"]), 1)
        popen.assert_not_called()
        wb.assert_not_called()

    def test_opens_private_window_with_url(self):
        with mock.patch.object(B, "wait", return_value=True), mock.patch.object(B, "command", return_value=["x", "--inprivate"]), mock.patch.object(B.subprocess, "Popen") as popen:
            self.assertEqual(B.main(["http://localhost:8501"]), 0)
        popen.assert_called_once_with(["x", "--inprivate", "http://localhost:8501"])

    def test_no_private_browser_opens_default_and_says_so(self):
        with mock.patch.object(B, "wait", return_value=True), mock.patch.object(B, "command", return_value=None), mock.patch.object(B.webbrowser, "open") as wb, mock.patch("builtins.print") as pr:
            self.assertEqual(B.main([]), 0)
        wb.assert_called_once_with(B.URL)
        self.assertIn("방문 기록", pr.call_args[0][0])


if __name__ == "__main__":
    unittest.main()
