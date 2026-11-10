"""설치 파일 시험: Windows의 pip과 cmd는 파일을 운영체제 기본 인코딩(cp1252, 한국어 Windows는 cp949)으로 읽는다.
UTF-8 한글이 들어가면 센터 PC 설치가 멈추므로 ASCII만 허용한다(2026-11-10 GitHub Actions Windows 실패에서 확인).
실행: .venv/bin/python -m unittest discover -s tests"""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = ["requirements.txt", "scripts/setup_windows.bat", "scripts/run_windows.bat", "scripts/setup_mac.sh", "scripts/run_mac.sh"]


class Package(unittest.TestCase):
    def test_install_files_are_ascii(self):
        for name in FILES:
            with self.subTest(name=name):
                data = (ROOT / name).read_bytes()
                bad = [i for i, b in enumerate(data) if b > 127]
                self.assertEqual(bad[:5], [], f"{name}에 ASCII 밖 글자가 있다(앞 위치 {bad[:5]})")


if __name__ == "__main__":
    unittest.main()
