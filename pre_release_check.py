import subprocess
import sys


CHECKS = [
    ("Compile check", [sys.executable, "-m", "py_compile", "main.py", "face_recognition.py", "data_sync.py", "cloud/cloud_api.py", "cloud/face_recognition_cloud.py"]),
    ("Unit tests", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py", "-v"]),
]


def run_check(name: str, cmd: list[str]) -> bool:
    print(f"\n=== {name} ===")
    print(" ".join(cmd))
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"[FAIL] {name} (exit={result.returncode})")
        return False
    print(f"[PASS] {name}")
    return True


def main() -> int:
    all_ok = True
    for name, cmd in CHECKS:
        if not run_check(name, cmd):
            all_ok = False
            break
    if all_ok:
        print("\nPre-release check: PASS")
        return 0
    print("\nPre-release check: FAIL")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
