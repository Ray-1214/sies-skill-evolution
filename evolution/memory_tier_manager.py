"""
memory_tier_manager.py — Φ-iv 記憶分層更新 (W12)
==================================================
論文 Definition 5 + 磁滯機制（避免邊界震盪）。

決策邏輯（標準 hysteresis）：
  cold/archive → active:  U ≥ θhigh + εh = 0.75
  active → cold:          U < θhigh - εh = 0.65
  cold → archive:         U < θlow - εl = 0.25
  archive → cold:         U ≥ θlow + εl = 0.35

Grace period:
  frequency == 0 的技能不參與遷移（新技能保留 active 機會被 A2 檢索）。

職責分離:
  - utility_engine: 算 utility（Φ-i）
  - graph_contractor: 改 tier 屬性（Φ-iii，不搬檔案）
  - memory_tier_manager (本模組): 統一物理搬移 + GRAPH_INDEX path 同步

依賴:
  parse_graph_index.py
  config.yaml (memory_tiers 區塊)
"""

import logging
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml
import networkx as nx

logger = logging.getLogger(__name__)


@dataclass
class TierMigration:
    name: str
    old_tier: str
    new_tier: str
    utility: float
    frequency: int
    old_path: str
    new_path: str
    file_moved: bool
    skipped_reason: Optional[str] = None


class MemoryTierManager:
    """
    Φ-iv 記憶分層管理器。

    每次 evolve() 呼叫時：
      1. 對所有節點根據 utility + 當前 tier 決定 target_tier（hysteresis）
      2. frequency == 0 的技能跳過（grace period）
      3. tier 變更：改 graph 屬性 + 搬移目錄 + 更新 path
    """

    def __init__(self, config_path: str = "config.yaml"):
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        tiers = config.get("memory_tiers", {})
        self.theta_high = tiers.get("theta_high", 0.7)
        self.theta_low = tiers.get("theta_low", 0.3)
        self.epsilon_high = tiers.get("epsilon_high", 0.05)
        self.epsilon_low = tiers.get("epsilon_low", 0.05)

        # Hysteresis 閾值
        self.upper_in = self.theta_high + self.epsilon_high   # 0.75 進 active
        self.upper_out = self.theta_high - self.epsilon_high  # 0.65 出 active
        self.lower_out = self.theta_low + self.epsilon_low    # 0.35 出 archive
        self.lower_in = self.theta_low - self.epsilon_low     # 0.25 進 archive

        # 三層目錄根路徑
        project_root = Path(config.get("system", {}).get("project_root", "."))
        self.skills_root = project_root / "skills"
        self.active_dir = self.skills_root / "active"
        self.cold_dir = self.skills_root / "cold"
        self.archive_dir = self.skills_root / "archive"

        # 確保目錄存在
        self.cold_dir.mkdir(parents=True, exist_ok=True)
        self.archive_dir.mkdir(parents=True, exist_ok=True)

        logger.info(
            f"[MemoryTierManager] thresholds: "
            f"active≥{self.upper_in:.2f} (out<{self.upper_out:.2f}), "
            f"archive≤{self.lower_in:.2f} (out≥{self.lower_out:.2f})"
        )

    # ── 公開 API ──────────────────────────────────────────

    def determine_target_tier(self, utility: float, current_tier: str) -> str:
        """
        根據 utility 與當前 tier 決定 target_tier（標準 hysteresis）。

        - 在當前 tier 的「正常區間」內 → 不變
        - 跨越升級閾值 → 升一級
        - 跨越降級閾值 → 降一級
        """
        if current_tier == "active":
            if utility < self.upper_out:
                # active 的下退閾值是 0.65（嚴於 0.75）
                if utility < self.lower_in:
                    return "archive"  # 直接跳兩級
                return "cold"
            return "active"

        elif current_tier == "cold":
            if utility >= self.upper_in:
                return "active"
            if utility < self.lower_in:
                return "archive"
            return "cold"

        elif current_tier == "archive":
            if utility >= self.upper_in:
                return "active"  # 直接跳兩級
            if utility >= self.lower_out:
                # archive 的上退閾值是 0.35（嚴於 0.25）
                return "cold"
            return "archive"

        # 未知 tier，預設 cold
        logger.warning(f"[MemoryTierManager] Unknown tier '{current_tier}', defaulting to cold")
        return "cold"

    def migrate_all(
    self,
    graph: nx.DiGraph,
    vector_store=None,
) -> list[TierMigration]:
        """
        對 graph 所有節點執行 tier migration。

        流程（每節點）:
        1. determine_target_tier(utility, current_tier)
        2. frequency == 0 → skip with reason (grace period)
        3. target == current → skip
        4. 更新 graph node.tier
        5. 物理搬移目錄（_move_skill_dir）
        6. 更新 graph node.path
        7. 累積 LanceDB path 更新

        Args:
            graph: 要遷移的 NetworkX DiGraph（會被原地修改）
            vector_store: 若提供，遷移完成後 batch 更新 LanceDB path 欄位
                        （避免 A2 查詢命中已搬移的 SKILL.md 時 FileNotFoundError）

        Returns:
            所有遷移記錄（包含 grace skip 紀錄，但不包含 target == current 的無變動）
        """
        migrations = []
        path_updates = []  # 累積要同步到 LanceDB 的 path 變更

        for name, attrs in list(graph.nodes(data=True)):
            current_tier = attrs.get("tier", "active")
            utility = float(attrs.get("utility", 0.5))
            frequency = int(attrs.get("frequency", 0))
            old_path = attrs.get("path", "")

            target_tier = self.determine_target_tier(utility, current_tier)

            # Grace period: frequency 0 跳過遷移
            if frequency == 0 and target_tier != current_tier:
                migrations.append(TierMigration(
                    name=name,
                    old_tier=current_tier,
                    new_tier=current_tier,  # unchanged
                    utility=utility,
                    frequency=frequency,
                    old_path=old_path,
                    new_path=old_path,
                    file_moved=False,
                    skipped_reason="grace_period (frequency=0)",
                ))
                continue

            # 無變動跳過（不記錄，避免淹沒 log）
            if target_tier == current_tier:
                # 補充檢查：graph 上 tier 與實際 path 是否一致（Φ-iii 改 tier 後的 catch-up）
                expected_prefix = f"skills/{current_tier}/"
                if old_path and not old_path.startswith(expected_prefix):
                    # graph tier 與 path 不一致，需搬
                    new_path, moved = self._move_skill_dir(name, old_path, current_tier)
                    if moved:
                        graph.nodes[name]["path"] = new_path
                        path_updates.append({"name": name, "new_path": new_path})
                        migrations.append(TierMigration(
                            name=name,
                            old_tier=current_tier,
                            new_tier=current_tier,
                            utility=utility,
                            frequency=frequency,
                            old_path=old_path,
                            new_path=new_path,
                            file_moved=True,
                            skipped_reason="catch_up (Φ-iii tier change)",
                        ))
                        logger.info(
                            f"[Φ-iv] {name}: catch-up move to {current_tier} "
                            f"(graph tier already {current_tier}, path was {old_path})"
                        )
                continue

            # 執行遷移
            new_path, moved = self._move_skill_dir(name, old_path, target_tier)

            # 更新 graph
            graph.nodes[name]["tier"] = target_tier
            if new_path:
                graph.nodes[name]["path"] = new_path

            # 累積 LanceDB path 更新
            if moved and new_path:
                path_updates.append({"name": name, "new_path": new_path})

            migrations.append(TierMigration(
                name=name,
                old_tier=current_tier,
                new_tier=target_tier,
                utility=utility,
                frequency=frequency,
                old_path=old_path,
                new_path=new_path or old_path,
                file_moved=moved,
                skipped_reason=None if moved else "directory not found",
            ))

            logger.info(
                f"[Φ-iv] {name}: {current_tier} → {target_tier} "
                f"(U={utility:.4f}, f={frequency}) "
                f"{'✓ moved' if moved else '✗ no dir'}"
            )

        # Batch 同步 LanceDB
        if vector_store is not None and path_updates:
            try:
                updated = vector_store.update_paths(path_updates)
                logger.info(
                    f"[Φ-iv] LanceDB paths synced: {updated}/{len(path_updates)}"
                )
            except Exception as e:
                logger.error(f"[Φ-iv] LanceDB path sync failed: {e}")

        # Summary
        actual = [m for m in migrations if m.skipped_reason is None]
        skipped = [m for m in migrations if m.skipped_reason is not None]
        logger.info(
            f"[Φ-iv] {len(actual)} migrations executed, "
            f"{len(skipped)} skipped (mostly grace period)"
        )

        return migrations

    # ── 內部 ──────────────────────────────────────────────

    def _move_skill_dir(
        self, name: str, old_path: str, new_tier: str
    ) -> tuple[str, bool]:
        """
        實際搬移 SKILL.md 所在目錄。

        old_path 範例:
          skills/active/web-search/SKILL.md
          skills/active/seed/test-driven-development/SKILL.md

        新路徑規則:
          skills/{new_tier}/{name}/SKILL.md
          (拆掉 seed/ 等中間層級，因為已被使用過，seed 標記失效)

        Returns:
            (new_path_str, success_bool)
        """
        if not old_path:
            return ("", False)

        # 從 old_path 推算來源目錄（包含 SKILL.md 的那層）
        old_skill_md = self.skills_root.parent / old_path  # project_root + path
        # 上一行假設 path 是相對於 project_root 的；若 path 已含 ./ 也能 resolve
        old_skill_md = Path(old_path)
        if not old_skill_md.is_absolute():
            old_skill_md = self.skills_root.parent / old_path

        old_dir = old_skill_md.parent

        if not old_dir.exists():
            logger.warning(f"[Φ-iv] Source dir not found: {old_dir}")
            return ("", False)

        # 目標路徑
        new_dir = self.skills_root / new_tier / name
        new_path_str = f"skills/{new_tier}/{name}/SKILL.md"

        if new_dir.exists():
            logger.warning(
                f"[Φ-iv] Target dir already exists: {new_dir}, removing first"
            )
            shutil.rmtree(new_dir)

        try:
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(old_dir), str(new_dir))
            return (new_path_str, True)
        except Exception as e:
            logger.error(f"[Φ-iv] Move failed for {name}: {e}")
            return ("", False)


# ---------------------------------------------------------------------------
# CLI / 自我測試
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    m = MemoryTierManager(config_path)

    # 單元測試 hysteresis 邏輯
    print("=== Hysteresis Decision Tests ===\n")

    cases = [
        # (utility, current_tier, expected_target)
        (0.80, "cold",    "active"),
        (0.75, "cold",    "active"),
        (0.74, "cold",    "cold"),
        (0.70, "active",  "active"),  # 在 active 正常區
        (0.66, "active",  "active"),  # 在 active 正常區（>0.65）
        (0.64, "active",  "cold"),    # 跨過下退閾值
        (0.50, "cold",    "cold"),
        (0.34, "cold",    "cold"),
        (0.24, "cold",    "archive"),
        (0.30, "archive", "archive"), # 在 archive 正常區
        (0.34, "archive", "archive"), # 在 archive 正常區（<0.35）
        (0.36, "archive", "cold"),    # 跨過上退閾值
        (0.80, "archive", "active"),  # 直接跳兩級
        (0.20, "active",  "archive"), # 直接跳兩級
    ]

    passed = 0
    for u, cur, expected in cases:
        actual = m.determine_target_tier(u, cur)
        status = "✓" if actual == expected else "✗"
        if actual == expected:
            passed += 1
        print(f"  {status} U={u:.2f} {cur:>7s} → {actual:>7s} (expected {expected})")

    print(f"\n{passed}/{len(cases)} hysteresis cases passed")