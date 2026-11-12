"""데모 로그인(사용자 결정 2026-11-13, 안 (가)): 로그인해야 Claude를 부르는 기능(계획 해설·전문가 모드)이 켜진다.

- 계정을 설정하지 않으면(센터 PC·로컬) 로그인 없이 지금처럼 동작한다(`required()`가 False).
- 계정: 환경 변수 `JEJU_ACCOUNTS="아이디:해시,아이디:해시"`. 해시는 `python -m app.auth hash`로 만든다(PBKDF2-SHA256, 소금 포함).
- 세션: 서명한 쿠키(`JEJU_SESSION_SECRET`, HMAC-SHA256). 서버는 세션을 저장하지 않는다(Vercel 인스턴스가 바뀌어도 유지).
- 로그인 시도 제한: IP마다 10분에 5번(인스턴스 안에서만 셈, 보조 수단).
- 비밀번호·해시·비밀값은 출력·로그에 남기지 않는다.
"""
import base64
import hashlib
import hmac
import os
import sys
import time

COOKIE = "jeju_session"
TTL = int(os.environ.get("JEJU_SESSION_HOURS", "12")) * 3600
ITER = 200_000
_fails = {}


def accounts():
    out = {}
    for part in (os.environ.get("JEJU_ACCOUNTS") or "").split(","):
        if ":" in part:
            uid, h = part.strip().split(":", 1)
            if uid and h:
                out[uid] = h
    return out


def required():
    """Claude 기능에 로그인이 필요한가. 계정이 설정돼 있거나, 공개 서버(Vercel)·JEJU_REQUIRE_LOGIN=1이면 필요하다.
    공개 서버에서 계정 변수가 빠지면 아무도 로그인할 수 없어 Claude 기능이 꺼진다(설정 누락 시 닫힌 쪽으로, 2026-11-13)."""
    return bool(accounts()) or bool(os.environ.get("VERCEL")) or os.environ.get("JEJU_REQUIRE_LOGIN") == "1"


def make_hash(password, salt=None):
    salt = salt or os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITER)
    return "pbkdf2$" + base64.urlsafe_b64encode(salt).decode() + "$" + base64.urlsafe_b64encode(dk).decode()


def check_password(password, stored):
    try:
        kind, s, d = stored.split("$")
        if kind != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), base64.urlsafe_b64decode(s), ITER)
        return hmac.compare_digest(dk, base64.urlsafe_b64decode(d))
    except (ValueError, TypeError):
        return False


def _secret():
    s = os.environ.get("JEJU_SESSION_SECRET")
    if not s:  # 비밀값이 없으면 로그인 자체를 막는다(위조 방지)
        raise RuntimeError("JEJU_SESSION_SECRET이 설정되지 않음")
    return s.encode("utf-8")


def sign(uid, now=None):
    exp = int((now or time.time()) + TTL)
    body = f"{uid}|{exp}"
    sig = hmac.new(_secret(), body.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{body}|{sig}"


def verify(token, now=None):
    """유효하면 아이디, 아니면 None."""
    try:
        uid, exp, sig = (token or "").rsplit("|", 2)
        good = hmac.new(_secret(), f"{uid}|{exp}".encode("utf-8"), hashlib.sha256).hexdigest()
        if hmac.compare_digest(sig, good) and int(exp) > (now or time.time()) and uid in accounts():
            return uid
    except (ValueError, RuntimeError):
        pass
    return None


def allow_attempt(ip, now=None):
    now = now or time.time()
    recent = [t for t in _fails.get(ip, []) if now - t < 600]
    _fails[ip] = recent
    return len(recent) < 5


def record_fail(ip, now=None):
    _fails.setdefault(ip, []).append(now or time.time())


def login(uid, password, ip="?"):
    """성공하면 쿠키 값, 실패하면 (None, 이유)."""
    if not allow_attempt(ip):
        return None, "로그인 시도가 많아요. 10분 뒤 다시 시도해 주세요."
    stored = accounts().get(uid)
    if not stored or not check_password(password, stored):
        record_fail(ip)
        return None, "아이디 또는 비밀번호가 맞지 않아요."
    return sign(uid), None


if __name__ == "__main__":  # 계정 해시 만들기: python -m app.auth hash
    if sys.argv[1:2] == ["hash"]:
        import getpass
        pw = getpass.getpass("비밀번호: ")
        if pw != getpass.getpass("한 번 더: "):
            sys.exit("두 비밀번호가 다릅니다.")
        print(make_hash(pw))
    elif sys.argv[1:2] == ["secret"]:
        print(base64.urlsafe_b64encode(os.urandom(32)).decode())
    else:
        print("사용: python -m app.auth hash | secret")
