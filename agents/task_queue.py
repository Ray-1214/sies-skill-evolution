"""
task_queue.py — FIFO 單線程任務佇列 (W14 子任務 3，§3.10.1)
============================================================
append-only event log（data/queue.jsonl），與 run_summary.jsonl /
evolution_log.jsonl 統一風格：每筆寫「完整 item 快照」，replay 取
last-write-per-queue_id 為最終態。

設計（§3.10.1 簡化版，v4.9 砍除優先級公式 / topological sort / 排班 agent）：
  - 純 FIFO（created_at 最小者先出）
  - 單一 jsonl，"a" mode 每筆一行，crash 不 truncate
  - 無 in-memory 狀態：每次讀都 replay 整檔（佇列規模小，正確性優先）

item schema（§3.10.1，欄位固定不增減）：
  queue_id, source, task_description, status, created_at, finished_at, result_summary

用法：
    from agents.task_queue import TaskQueue
    q = TaskQueue()
    qid = q.enqueue("user", "查詢 PEP 703 狀態")
    item = q.peek_next()
    q.mark_running(qid)
    q.mark_done(qid, "已回答：Accepted")
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

TZ_TPE = timezone(timedelta(hours=8))

VALID_SOURCES = {"user", "curriculum", "learning"}


def _now_iso() -> str:
    return datetime.now(TZ_TPE).isoformat()


class TaskQueue:
    """append-only FIFO 任務佇列（§3.10.1）。"""

    def __init__(self, path: str = "data/queue.jsonl"):
        self.path = Path(path)

    # ── 內部讀取 ─────────────────────────────────────────

    def _load(self) -> dict[str, dict]:
        """
        Replay 整檔，group by queue_id 取「最後出現那筆」= 最終態。

        檔案不存在 → 回空 dict（不報錯）。malformed 行跳過。
        """
        items: dict[str, dict] = {}
        if not self.path.exists():
            return items

        with self.path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(f"[TaskQueue] skipping malformed line in {self.path.name}")
                    continue
                qid = rec.get("queue_id")
                if qid:
                    items[qid] = rec  # 後出現的覆蓋先出現的 → 最終態
        return items

    def _append(self, item: dict) -> None:
        """單筆完整 item 寫入（"a" mode，一行 + \\n）。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")

    # ── 公開 API ──────────────────────────────────────────

    def enqueue(self, source: str, task_description: str, cluster: Optional[str] = None,
                **meta) -> str:
        """
        新增 pending item，回傳 queue_id。

        source 不在 {user, curriculum, learning} → ValueError。
        queue_id = f"q_{n+1:04d}"，n = 現有最大 queue_id 序號（replay 算出）。
        """
        if source not in VALID_SOURCES:
            raise ValueError(
                f"invalid source '{source}', must be one of {sorted(VALID_SOURCES)}"
            )

        existing = self._load()
        max_n = 0
        for qid in existing:
            # qid 形如 "q_0001"，取數字部分
            try:
                n = int(qid.split("_")[-1])
                max_n = max(max_n, n)
            except (ValueError, IndexError):
                continue
        new_id = f"q_{max_n + 1:04d}"

        # [P5-a] meta 帶出題器產出的其餘欄位：domain / level / mode /
        # path_id / path_pos / parent_task_id / input_files / reference_solution /
        # expected / oracle。全部可選，舊呼叫者不受影響。
        item = {
            "queue_id": new_id,
            "source": source,
            "task_description": task_description,
            "cluster": cluster,
            "domain": meta.get("domain"),
            "level": meta.get("level"),
            "mode": meta.get("mode"),
            "path_id": meta.get("path_id"),
            "path_pos": meta.get("path_pos"),
            "parent_task_id": meta.get("parent_task_id"),
            # 四元組（生成即可驗，見 scripts/verify_runner.py）
            "input_files": meta.get("input_files"),
            "reference_solution": meta.get("reference_solution"),
            "expected": meta.get("expected"),
            "oracle": meta.get("oracle"),
            "status": "pending",
            "created_at": _now_iso(),
            "finished_at": None,
            "result_summary": None,
        }
        self._append(item)
        logger.info(f"[TaskQueue] enqueued {new_id} (source={source})")
        return new_id

    def peek_next(self) -> Optional[dict]:
        """回傳 status=='pending' 中 created_at 最小者（FIFO），無則 None。"""
        pending = [it for it in self._load().values() if it.get("status") == "pending"]
        if not pending:
            return None
        return min(pending, key=lambda it: it.get("created_at", ""))

    def mark_running(self, queue_id: str) -> None:
        """append 同 qid 完整 item，status='running'（其餘欄位沿用最新值）。"""
        item = self._get_or_raise(queue_id)
        item["status"] = "running"
        self._append(item)
        logger.info(f"[TaskQueue] {queue_id} → running")

    def mark_done(self, queue_id: str, result_summary: str) -> None:
        """append，status='done', finished_at=now, result_summary=summary。"""
        item = self._get_or_raise(queue_id)
        item["status"] = "done"
        item["finished_at"] = _now_iso()
        item["result_summary"] = result_summary
        self._append(item)
        logger.info(f"[TaskQueue] {queue_id} → done")

    def mark_failed(self, queue_id: str, result_summary: str) -> None:
        """append，status='failed', finished_at=now, result_summary=summary。"""
        item = self._get_or_raise(queue_id)
        item["status"] = "failed"
        item["finished_at"] = _now_iso()
        item["result_summary"] = result_summary
        self._append(item)
        logger.info(f"[TaskQueue] {queue_id} → failed")

    def all_items(self) -> list[dict]:
        """回傳所有 item 最終態，按 created_at 排序。"""
        return sorted(
            self._load().values(),
            key=lambda it: it.get("created_at", ""),
        )

    def reset_stale_running(self) -> int:
        """把所有 status=='running' 的 item 改回 'pending'，回傳重置筆數。

        前次 loop 在 mark_running 後、mark_done/failed 前被 Ctrl-C / crash，
        會留下 running 殭屍；重啟時這些 item 不在 pending、peek_next 跳過 → 該題靜默遺失。
        loop 啟動時呼叫一次即可恢復。
        """
        stale = [it for it in self._load().values() if it.get("status") == "running"]
        for it in stale:
            item = dict(it)
            item["status"] = "pending"
            self._append(item)
        if stale:
            logger.info(f"[TaskQueue] reset {len(stale)} stale running → pending")
        return len(stale)

    # ── 內部工具 ──────────────────────────────────────────

    def _get_or_raise(self, queue_id: str) -> dict:
        """取 qid 最新態的副本；不存在 → KeyError。"""
        items = self._load()
        if queue_id not in items:
            raise KeyError(f"queue_id '{queue_id}' not found")
        return dict(items[queue_id])  # 副本，避免改到 _load 暫存


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # 用臨時檔，不污染正式 data/queue.jsonl
    tmp = Path(tempfile.mkdtemp()) / "queue_smoke.jsonl"
    print(f"=== TaskQueue smoke test (path={tmp}) ===\n")

    q = TaskQueue(path=str(tmp))

    # enqueue 3 筆（不同 source）
    qid1 = q.enqueue("user", "查詢 PEP 703 狀態")
    qid2 = q.enqueue("curriculum", "出一題 backtracking 練習")
    qid3 = q.enqueue("learning", "從失敗 trace 學 retry 策略")
    print(f"enqueued: {qid1}, {qid2}, {qid3}\n")

    # peek_next 確認最舊
    nxt = q.peek_next()
    print(f"peek_next (expect {qid1}): {nxt['queue_id']} | {nxt['task_description']}")
    assert nxt["queue_id"] == qid1, "FIFO order broken"

    # mark_running → mark_done
    q.mark_running(qid1)
    q.mark_done(qid1, "已回答：Accepted")

    # peek_next 現在應該是 qid2
    nxt2 = q.peek_next()
    print(f"peek_next after done (expect {qid2}): {nxt2['queue_id']}\n")
    assert nxt2["queue_id"] == qid2

    # mark_failed qid3 測失敗路徑
    q.mark_failed(qid3, "server timeout")

    # all_items 印出（replay 後最終態）
    print("=== all_items (replay 後最終態) ===")
    for it in q.all_items():
        print(
            f"  {it['queue_id']} | {it['source']:<10} | {it['status']:<8} | "
            f"finished={it['finished_at']} | result={it['result_summary']}"
        )

    # 驗證最終態正確
    items = {it["queue_id"]: it for it in q.all_items()}
    assert items[qid1]["status"] == "done" and items[qid1]["finished_at"] is not None
    assert items[qid1]["result_summary"] == "已回答：Accepted"
    assert items[qid2]["status"] == "pending" and items[qid2]["finished_at"] is None
    assert items[qid3]["status"] == "failed" and items[qid3]["result_summary"] == "server timeout"

    # 驗證 append-only：3 enqueue + 1 running + 1 done + 1 failed = 6 行
    n_lines = sum(1 for _ in open(tmp, encoding="utf-8"))
    print(f"\nappend-only log lines: {n_lines} (expect 6: 3 enqueue + running + done + failed)")
    assert n_lines == 6, f"expected 6 lines, got {n_lines}"

    print("\n✓ all assertions passed")
