"""상세 분석 코드 검사·격리 실행(설계 11-2절 ③④, 2026-11-13).

규약: 코드는 이미 들어 있는 `T`(표 이름 → DataFrame)와 `pd`·`np`·`stats`(scipy.stats)·`sk`(sklearn 일부)만 쓴다.
결과는 `result` 딕셔너리에 담는다:
  result = {"numbers": {"이름": 숫자}, "tables": [{"title", "columns", "rows"}], "series": [{"title", "kind": "line|bar|scatter", "x", "y", "name"}]}
막는 것(AST): import 문, 밑줄로 시작하는 이름·속성, 파일·실행·반사 함수, 파일 입출력 메서드(read_*/to_* 등).
격리: 별도 Python 프로세스(-I), 시간 상한, 결과 크기 상한. Windows에서도 같다. 완전한 격리는 아니다(설계 11-2절 한계).
"""
import ast
import json
import os
import subprocess
import sys
from pathlib import Path

TIME_LIMIT = float(os.environ.get("JEJU_EXPERT_TIMEOUT", "20"))
MAX_BYTES = 1_000_000
MAX_CODE = 6000

BANNED_NAMES = {"open", "exec", "eval", "compile", "__import__", "input", "breakpoint", "help", "globals", "locals", "vars",
                "getattr", "setattr", "delattr", "hasattr", "dir", "type", "object", "memoryview", "super", "classmethod",
                "staticmethod", "property", "exit", "quit", "os", "sys", "subprocess", "socket", "shutil", "pathlib", "importlib",
                "builtins", "pickle", "marshal", "ctypes", "requests", "urllib", "http", "io", "tempfile", "threading", "multiprocessing"}
BANNED_ATTRS = {"read_csv", "read_parquet", "read_excel", "read_json", "read_pickle", "read_sql", "read_html", "read_table", "read_feather",
                "read_hdf", "read_stata", "read_sas", "read_spss", "read_fwf", "read_clipboard", "read_xml", "read_orc",
                "to_csv", "to_parquet", "to_excel", "to_json", "to_pickle", "to_sql", "to_html", "to_feather", "to_hdf",
                "to_stata", "to_clipboard", "to_xml", "to_orc", "to_latex", "to_markdown", "to_string_file",
                "load", "loads", "save", "savez", "savez_compressed", "savetxt", "loadtxt", "genfromtxt", "fromfile", "tofile",
                "memmap", "DataSource", "dump", "dumps", "eval", "query", "system", "popen", "spawn", "fork", "remove", "unlink",
                "rmdir", "mkdir", "chdir", "environ", "getenv", "putenv", "pipe", "style", "plot", "hist", "boxplot",
                "io", "lib", "api", "ctypeslib", "testing", "core", "compat", "util", "utils", "os", "sys", "f2py", "distutils",
                "read", "write", "open", "fromregex", "from_file", "to_records_file", "set_option", "options"}


class CodeRejected(ValueError):
    pass


def check(code):
    """허용 규칙 위반을 찾으면 CodeRejected. 통과하면 None."""
    if not isinstance(code, str) or not code.strip():
        raise CodeRejected("코드가 비어 있음")
    if len(code) > MAX_CODE:
        raise CodeRejected(f"코드가 너무 김({len(code)}자 > {MAX_CODE})")
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        raise CodeRejected(f"문법 오류: {e.msg} (줄 {e.lineno})")
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            raise CodeRejected("import 문은 쓸 수 없음(pd·np·stats·sk가 이미 있음)")
        if isinstance(node, (ast.Global, ast.Nonlocal, ast.AsyncFunctionDef, ast.Await, ast.With, ast.AsyncWith,
                             ast.ClassDef, ast.Try, ast.Raise, ast.Delete, ast.Lambda)):
            # Try는 예외 삼키기로 검사를 피해 가지 못하게, Lambda·ClassDef는 우회 경로를 줄이려고 막는다
            raise CodeRejected(f"허용하지 않는 문법: {type(node).__name__}")
        if isinstance(node, ast.Name) and (node.id in BANNED_NAMES or (node.id.startswith("_") and node.id != "_")):
            raise CodeRejected(f"쓸 수 없는 이름: {node.id}")
        if isinstance(node, ast.Attribute) and (node.attr.startswith("_") or node.attr in BANNED_ATTRS):
            raise CodeRejected(f"쓸 수 없는 속성: .{node.attr}")
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool) \
                and abs(node.value) > 1e8:
            raise CodeRejected("1억이 넘는 숫자 상수는 쓸 수 없음(메모리 폭탄 방지, 금액은 표에서 읽기)")
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow) and isinstance(node.right, ast.Constant) \
                and isinstance(node.right.value, (int, float)) and node.right.value >= 8:
            raise CodeRejected("8제곱 이상 거듭제곱은 쓸 수 없음(메모리 폭탄 방지)")
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and ("__" in node.value):
            raise CodeRejected("밑줄 두 개가 든 문자열은 쓸 수 없음")
        if isinstance(node, ast.FunctionDef) and node.name.startswith("_"):
            raise CodeRejected(f"쓸 수 없는 함수 이름: {node.name}")
    return None


RUNNER = r'''
import json, sys, math
for _p in json.loads(sys.argv[2]):  # 부모의 라이브러리 경로(-I는 PYTHONPATH를 무시. Vercel은 라이브러리가 기본 위치 밖, 2026-11-13)
    if _p not in sys.path:
        sys.path.append(_p)
import numpy as np, pandas as pd
from scipy import stats
import sklearn.cluster, sklearn.preprocessing, sklearn.linear_model, sklearn.metrics, sklearn.decomposition
from types import SimpleNamespace
sys.path.insert(0, sys.argv[1])
import datadict
T = {k: v.copy() for k, v in datadict.load_tables().items()}
sk = SimpleNamespace(cluster=sklearn.cluster, preprocessing=sklearn.preprocessing, linear_model=sklearn.linear_model,
                     metrics=sklearn.metrics, decomposition=sklearn.decomposition)
code = sys.stdin.read()
SAFE = {k: __builtins__[k] if isinstance(__builtins__, dict) else getattr(__builtins__, k) for k in
        ("abs", "all", "any", "bool", "dict", "enumerate", "float", "int", "len", "list", "max", "min", "range", "round",
         "set", "sorted", "str", "sum", "tuple", "zip", "map", "filter", "reversed", "isinstance", "print", "ValueError")}
import builtins as _b
_ALLOWED_TOP = {"numpy", "pandas", "scipy", "sklearn", "math", "datetime", "decimal", "numbers", "collections", "functools",
                "itertools", "operator", "warnings", "copy", "re", "statistics", "fractions", "threadpoolctl", "joblib"}
def _lib_import(name, globals=None, locals=None, fromlist=(), level=0):
    # 라이브러리의 C 코드가 실행 중에 지연 import를 할 때 현재 프레임의 __builtins__를 쓴다(numpy 거듭제곱 등).
    # 사용자 코드는 AST 검사로 __import__ 이름을 못 쓰므로, 이미 불러온 모듈과 허용한 분석 라이브러리만 열어 준다.
    if level == 0 and name not in sys.modules and name.split(".")[0] not in _ALLOWED_TOP:
        raise ImportError(f"허용하지 않는 모듈: {name}")
    return _b.__import__(name, globals, locals, fromlist, level)
SAFE["__import__"] = _lib_import
g = {"__builtins__": SAFE, "pd": pd, "np": np, "stats": stats, "sk": sk, "T": T, "math": math, "result": {}}
def plain(x):
    if isinstance(x, dict): return {str(k): plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)): return [plain(v) for v in x]
    if isinstance(x, (np.integer,)): return int(x)
    if isinstance(x, (np.floating, float)):
        x = float(x); return None if (math.isnan(x) or math.isinf(x)) else x
    if isinstance(x, np.ndarray): return plain(x.tolist())
    if isinstance(x, pd.Timestamp): return str(x)
    return x
try:
    exec(compile(code, "<expert>", "exec"), g)
    out = {"ok": True, "result": plain(g.get("result") or {})}
except Exception as e:
    out = {"ok": False, "error": f"{type(e).__name__}: {e}"[:500]}
sys.stdout.write(json.dumps(out, ensure_ascii=False, default=str))
'''


MEM_LIMIT = int(os.environ.get("JEJU_EXPERT_MEM_MB", "1536")) * 1024 * 1024


def _posix_limits():  # 자식 프로세스에서 실행(macOS·Linux): 주소 공간 상한
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_AS, (MEM_LIMIT, MEM_LIMIT))
    except (ImportError, ValueError, OSError):
        pass


def _windows_job(proc):
    """Windows: Job Object로 메모리 상한과 '부모가 닫히면 자식 종료'를 건다. 실패하면 False(실행은 계속)."""
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)

        class IO(ctypes.Structure):
            _fields_ = [(n, ctypes.c_ulonglong) for n in ("r", "w", "o", "rb", "wb", "ob")]

        class BASIC(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_longlong), ("PerJobUserTimeLimit", ctypes.c_longlong),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD)]

        class EXT(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BASIC), ("IoInfo", IO), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        job = k32.CreateJobObjectW(None, None)
        info = EXT()
        info.BasicLimitInformation.LimitFlags = 0x100 | 0x2000  # PROCESS_MEMORY | KILL_ON_JOB_CLOSE
        info.ProcessMemoryLimit = MEM_LIMIT
        ok = k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # 9 = ExtendedLimitInformation
        ok = ok and k32.AssignProcessToJobObject(job, wintypes.HANDLE(proc._handle))
        proc._jeju_job = job  # 프로세스가 끝날 때까지 핸들을 붙잡아 둔다
        return bool(ok)
    except Exception:
        return False


def lib_paths():
    """하위 프로세스가 쓸 라이브러리 경로: 부모 프로세스의 sys.path 가운데 있는 폴더만(현재 폴더 '' 제외)."""
    return [p for p in sys.path if p and os.path.isdir(p)]


def run(code, timeout=None):
    """검사 뒤 별도 프로세스에서 실행. {"ok", "result"|"error", "stage"}를 돌려준다."""
    try:
        check(code)
    except CodeRejected as e:
        return {"ok": False, "stage": "검사", "error": str(e)}
    import tempfile
    app_dir = str(Path(__file__).resolve().parent)
    env = {k: v for k, v in os.environ.items() if k in ("PATH", "SYSTEMROOT", "TEMP", "TMP", "LANG")}  # 키는 넘기지 않는다
    env["PYTHONIOENCODING"] = "utf-8"
    # -I(격리 모드)는 PYTHON* 환경 변수를 무시하므로 UTF-8 모드는 명령줄 -X utf8로 켠다(2026-11-19 Windows 시험: 입력 코드의 한글이 cp1252로 읽혀 깨짐)
    limit = timeout or TIME_LIMIT
    with tempfile.TemporaryDirectory(prefix="jeju_expert_") as work:  # 빈 임시 폴더에서 실행
        win = os.name == "nt"
        p = subprocess.Popen([sys.executable, "-I", "-X", "utf8", "-c", RUNNER, app_dir, json.dumps(lib_paths())], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, env=env, cwd=work, preexec_fn=None if win else _posix_limits)
        if win:
            _windows_job(p)
        try:
            raw, err = p.communicate(code.encode("utf-8"), timeout=limit)
        except subprocess.TimeoutExpired:
            p.kill()
            p.communicate()
            return {"ok": False, "stage": "실행", "error": f"시간 상한 {limit:.0f}초를 넘음"}
    if len(raw) > MAX_BYTES:
        return {"ok": False, "stage": "실행", "error": "결과가 1MB를 넘음(표 행 수를 줄여 주세요)"}
    try:
        out = json.loads(raw.decode("utf-8"))
    except ValueError:
        tail = err.decode("utf-8", "replace")[-300:]
        why = "메모리 상한을 넘음" if ("MemoryError" in tail or p.returncode not in (0, 1)) else "실행 결과를 읽지 못함"
        return {"ok": False, "stage": "실행", "error": f"{why}: {tail[-150:]}"}
    out["stage"] = "실행"
    if out.get("ok"):
        bad = shape_error(out["result"])
        if bad:
            return {"ok": False, "stage": "형식", "error": bad}
    elif "MemoryError" in str(out.get("error")):
        out["error"] = "메모리 상한을 넘음(자료를 줄여 계산해 주세요)"
    return out


def shape_error(r):
    """result 형식이 규약과 다르면 이유 문자열."""
    if not isinstance(r, dict) or not r:
        return "result가 비어 있음"
    if set(r) - {"numbers", "tables", "series", "notes"}:
        return f"result에 모르는 키: {sorted(set(r) - {'numbers', 'tables', 'series', 'notes'})}"
    for t in r.get("tables", []):
        if not isinstance(t, dict) or not {"columns", "rows"} <= set(t):
            return "tables 항목에는 columns·rows가 있어야 함"
        if len(t["rows"]) > 200:
            return "표는 200행까지"
    for s in r.get("series", []):
        if not isinstance(s, dict) or not {"x", "y"} <= set(s) or len(s["x"]) != len(s["y"]):
            return "series 항목에는 길이가 같은 x·y가 있어야 함"
        if s.get("kind", "line") not in ("line", "bar", "scatter"):
            return "series kind는 line·bar·scatter"
    return None
