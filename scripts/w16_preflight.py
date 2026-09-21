"""
w16_preflight.py — 長跑啟動前的檢查（P6′）
==========================================
PASS 才准啟動。任何一項 FAIL 就不要跑 —— 一次長跑是 1-2 小時 GPU，中途才發現
容器沒開、或三方不一致，整輪數據作廢。

    python scripts/w16_preflight.py            # 檢查
    python scripts/w16_preflight.py --snapshot # 順便做 rsync 還原點
"""
import argparse
import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
CONTAINER = "sies-agent-zero"
TZ = timezone(timedelta(hours=8))


def _ok(label, val, good, hint=""):
    mark = "PASS" if good else "FAIL"
    dots = "." * max(1, 26 - len(label))
    print(f"  {label} {dots} {val}   [{mark}]" + (f"  {hint}" if hint and not good else ""))
    return good


def check_git():
    try:
        c = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT,
                           capture_output=True, text=True).stdout.strip()
        dirty = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                               capture_output=True, text=True).stdout.strip()
        return _ok("Git commit", c or "?", bool(c)), c, bool(dirty)
    except Exception as e:  # noqa: BLE001
        return _ok("Git commit", f"error {e}", False), "?", True


def check_consistency():
    import parse_graph_index as pgi
    fs = len([p for p in (ROOT / "skills").glob("**/SKILL.md")
              if p.relative_to(ROOT / "skills").parts[0] in ("active", "cold", "archive")])
    graph = len(pgi.parse_graph_index(str(ROOT / "skills" / "GRAPH_INDEX.md"))["nodes"])
    try:
        import lancedb
        lance = lancedb.connect(str(ROOT / "data" / "lancedb")) \
            .open_table("skill_embeddings").count_rows()
    except Exception as e:  # noqa: BLE001
        lance = f"err({type(e).__name__})"
    good = (fs == graph == lance)
    return _ok("FS=Graph=Lance", f"{fs}/{graph}/{lance}", good,
               "三者不等，任何實驗數據都不可信"), (fs, graph, lance)


def check_llm(url="http://localhost:8080/health"):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            code = r.status
    except Exception:  # noqa: BLE001
        code = 0
    return _ok("LLM :8080", code or "down", code == 200,
               "啟動 reasoning_model_server")


def check_docker():
    r = subprocess.run(["docker", "ps", "--filter", f"name={CONTAINER}",
                        "--format", "{{.Status}}"], capture_output=True, text=True)
    st = r.stdout.strip()
    return _ok("Docker sandbox", st or "not running", st.startswith("Up"),
               f"docker start {CONTAINER}")


def check_sandbox_deps():
    mods = ["pptx", "pygame", "pandas", "numpy"]
    r = subprocess.run(
        ["docker", "exec", CONTAINER, "/opt/venv/bin/python3", "-c",
         "import " + ", ".join(mods) + "; print('ok')"],
        capture_output=True, text=True)
    good = "ok" in r.stdout
    return _ok("Sandbox deps", ",".join(mods) if good else "missing", good,
               "docker exec sies-agent-zero /opt/venv/bin/pip install python-pptx pygame pillow")


def check_tmp_clean():
    r = subprocess.run(["docker", "exec", CONTAINER, "bash", "-lc", "ls -A /tmp | wc -l"],
                       capture_output=True, text=True)
    try:
        n = int(r.stdout.strip())
    except ValueError:
        n = -1
    # 只是提示：runner 每題之間會清，這裡不擋
    _ok("/tmp 殘留（TD-11）", f"{n} 項", True, "")
    return True


def check_no_running_lock():
    lock = ROOT / "data" / "w16" / ".runlock"
    if not lock.exists():
        return _ok("PID lock", "free", True)
    try:
        pid = int(lock.read_text().split()[0])
        alive = Path(f"/proc/{pid}").exists()
    except Exception:  # noqa: BLE001
        alive = False
    return _ok("PID lock", f"held by {lock.read_text().strip()}" if alive else "stale",
               not alive, f"另一個長跑在跑，或手動刪 {lock}")


def make_snapshot():
    ts = datetime.now(TZ).strftime("%Y%m%d-%H%M%S")
    dst = ROOT / "snapshots" / f"pre-longrun-{ts}"
    subprocess.run([
        "rsync", "-a", "--delete",
        "--exclude=/.git", "--exclude=/snapshots",
        "--exclude=/everything-claude-code", "--exclude=/superpowers",
        "--exclude=__pycache__", "--exclude=.pytest_cache",
        f"{ROOT}/", f"{dst}/"], check=True)
    return _ok("Snapshot", dst.name, dst.exists()), str(dst)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", action="store_true", help="順便做 rsync 還原點")
    args = ap.parse_args()

    print("=" * 62)
    print("W16 PREFLIGHT")
    print("=" * 62)
    checks = []
    g, commit, dirty = check_git(); checks.append(g)
    c, triple = check_consistency(); checks.append(c)
    checks.append(check_llm())
    checks.append(check_docker())
    checks.append(check_sandbox_deps())
    check_tmp_clean()
    checks.append(check_no_running_lock())
    snap = None
    if args.snapshot:
        s, snap = make_snapshot(); checks.append(s)

    if dirty:
        print("  ⚠ 工作樹有未 commit 的改動 —— manifest 會記 worktree hash，但建議先 commit")

    ok = all(checks)
    print("=" * 62)
    print(f"PREFLIGHT {'PASS —— 可以啟動長跑' if ok else 'FAIL —— 不要啟動'}")
    print("=" * 62)
    if ok:
        print("\n啟動指令（背景跑，不要用 tmux）：")
        print("  nohup python scripts/w16_run.py --tasks 50 \\")
        print("      --direction \"learn to build a data processing pipeline: "
              "parse, validate, aggregate, join, report\" \\")
        print("      > data/logs/longrun_$(date +%Y%m%dT%H%M%S).log 2>&1 & disown")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
