"""Only reviewed isolated tests are collected. Historical integration scripts stay intact."""
from pathlib import Path
import socket
import uuid

import pytest

ROOT = Path(__file__).resolve().parent
# pytest 的 basetemp 只允許開在這底下，且必須是新目錄 —— 既有產物永不刪除。
# 目錄本身空著進版控（.gitkeep），不存在的話 pytest 會 FileNotFoundError。
AREA = ROOT / "data/_pytest_tmp"
SAFE_TESTS = {"test_triggers_wired.py", "test_no_skills.py", "test_plan_references.py",
    "test_curriculum_round_robin.py", "test_memory_catalog.py", "test_memory_associations.py",
    "test_contraction_isolated.py", "test_memory_autonomy.py", "test_memory_eval.py",
    "test_provider_clients.py", "test_remote_embedding.py",
    # [2026-09-17] 兩個歷史測試檔，涵蓋本輪改動的區域，經逐行檢查後加回：
    #   test_w9_unit.py    PatternRecognizer —— T3 的新實作直接依賴它
    #                      （evolution_triggers.py 的 check_t3）。寫檔都在
    #                      tempfile.TemporaryDirectory() 內。
    #   test_p1_signals.py curriculum / TD-27 —— 本輪改了 curriculum_agent 的
    #                      輪流出題。唯一碰真實路徑的是
    #                      test_write_false_does_not_touch_disk，它「讀」
    #                      data/ability_profile_live.json 的 mtime 前後比對，
    #                      是證明 write=False 不寫磁碟的負控制，本身不寫入。
    "test_w9_unit.py", "test_p1_signals.py",
    # [2026-09-17] 合併回歸守門：--no-skill 不得執行 Φ（w16_run.py 的 EVOLUTION_ENABLED）
    "test_no_skill_never_evolves.py"}


def pytest_configure(config):
    for arg in config.args:
        path = Path(str(arg).split("::", 1)[0]).resolve()
        if path.is_file() and (path.parent != ROOT / "tests" or path.name not in SAFE_TESTS):
            raise pytest.UsageError("Unreviewed test blocked before import. Migrate it to isolated fixtures and add it to SAFE_TESTS first.")
    temp = Path(config.option.basetemp).resolve() if config.option.basetemp else AREA / ("pytest-auto-"+uuid.uuid4().hex)
    if not temp.is_relative_to(AREA) or temp.exists():
        raise pytest.UsageError("basetemp must be a NEW directory under data/_pytest_tmp; existing artifacts are never deleted")
    config.option.basetemp = str(temp)


def pytest_ignore_collect(collection_path, config):
    path = Path(collection_path).resolve()
    if path.is_file() and path.suffix == ".py" and path.name.startswith("test"):
        return path.parent != ROOT / "tests" or path.name not in SAFE_TESTS
    return None


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """讓「N collected」自帶脈絡。

    白名單是靜默的 —— 被排除的檔案不會出現在 pytest 輸出裡（連 skipped 都不算），
    所以單看收集數會以為那就是專案的全部測試。這裡把涵蓋範圍明講出來。
    """
    present = sorted(p.name for p in (ROOT / "tests").glob("test*.py"))
    collected = [n for n in present if n in SAFE_TESTS]
    excluded = [n for n in present if n not in SAFE_TESTS]
    terminalreporter.write_sep("-", "SAFE_TESTS 白名單")
    terminalreporter.write_line(
        f"已收集 {len(collected)} 個檔案，排除 {len(excluded)} 個未遷移的歷史測試檔。")
    if excluded:
        terminalreporter.write_line("排除清單（未經隔離改寫，可能碰真實資料）：")
        for name in excluded:
            terminalreporter.write_line(f"  - {name}")
        terminalreporter.write_line(
            "這些檔案不會被收集、也不計入上方統計。遷移到隔離 fixture 後加進 SAFE_TESTS 即可納入。")


@pytest.fixture(autouse=True)
def no_live_network_or_model(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("Live network/model access is forbidden in the isolated unit suite")
    monkeypatch.setattr(socket.socket, "connect", blocked)
    monkeypatch.setattr(socket.socket, "connect_ex", blocked)
    monkeypatch.setattr(socket, "getaddrinfo", blocked)
    from embedding_engine import EmbeddingEngine
    monkeypatch.setattr(EmbeddingEngine, "_load_model", blocked)
