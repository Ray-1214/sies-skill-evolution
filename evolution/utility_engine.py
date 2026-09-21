"""
utility_engine.py — 效用函數計算引擎 (W11)
=============================================
論文 Section 4.2:  U(σ) = α·r + β·f - γc·c
衰減規則:          Ut+1 ← (1-γ)·Ut + ΔUt

資料來源：
  memory/episodic/run_summary.jsonl   ← agent_runner 每次完成後寫入

依賴：
  parse_graph_index.py
  config.yaml

用法：
    from evolution.utility_engine import UtilityEngine
    engine = UtilityEngine("config.yaml")
    stats = engine.scan_run_summaries()
    engine.update_all_utilities(graph)
    engine.apply_decay(graph)
"""

import json
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml
import networkx as nx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class SkillStats:
    """單一技能從歷史 trace 統計出的原始數據。"""
    name: str
    reinforcement: float = 0.0     # r: 被選中且任務成功的累計次數
    frequency: int = 0             # f: 被 A2 選中的總次數
    total_steps: int = 0           # 所有參與任務的步驟總和
    task_count: int = 0            # 參與的任務數（用於算平均 cost）
    success_count: int = 0         # 參與且任務成功的次數
    failure_count: int = 0         # 參與且任務失敗的次數
    # [P1-a / B′] r 的證據強度。舊紀錄與只驗 liveness 的紀錄算「未知」，
    # 不是 r=0 —— 當成 0 會讓第一次 Φ-i 把 58/59 技能一次歸檔（實測）。
    verified_count: int = 0        # 有 verified_independent 判定的次數（True 或 False 都算）
    unverified_count: int = 0      # r 未知的次數（舊 schema / liveness / 沒驗）


@dataclass
class UtilityUpdate:
    """一次效用更新的結果。"""
    name: str
    old_utility: float
    new_utility: float
    r: float
    f_norm: float
    c_norm: float
    detail: str = ""


@dataclass
class DecayResult:
    """一次衰減操作的結果。"""
    name: str
    old_utility: float
    new_utility: float
    was_reinforced: bool


# ---------------------------------------------------------------------------
# UtilityEngine
# ---------------------------------------------------------------------------

class UtilityEngine:
    """
    效用函數計算引擎。

    核心公式（論文 Eq. 16-17）：
      U(σ) = α·r_norm + β·f_norm - γc·c_norm
      Ut+1 ← (1-γ)·Ut + ΔUt

    Lemma 1 保證：
      若技能持續不被使用（ΔU=0），Ut = U0·(1-γ)^t，
      在 t* = ceil(log(θlow/U0) / log(1-γ)) 步後必定 < θlow。
    """

    def __init__(self, config_path: str = "config.yaml"):
        """
        從 config.yaml 載入效用函數參數。

        讀取的 config 區塊：
          utility:   {alpha, beta, gamma_cost, gamma_decay}
          system:    {trace_dir}
        """
        with open(config_path, encoding="utf-8") as f:
            config = yaml.safe_load(f)

        util_cfg = config.get("utility", {})
        self.alpha = util_cfg.get("alpha", 0.4)
        self.beta = util_cfg.get("beta", 0.4)
        self.gamma_cost = util_cfg.get("gamma_cost", 0.2)
        # [P1-a / B′] r 要有幾筆 verified_independent 判定才算「已知」。
        # 低於這個數維持「未知」分支，避免單一筆驗證結果讓 U 大幅跳動。
        # 與 ability_profiler 的「至少 4 筆才調難度」是同一種紀律。
        self.min_verified_for_r = util_cfg.get("min_verified_for_r", 3)
        self.gamma_decay = util_cfg.get("gamma_decay", 0.1)

        # SimpleAgent 最大步數（用於 cost 正規化）
        self.max_steps = config.get("agent_zero", {}).get("max_steps", 15)

        # trace 目錄
        self.trace_dir = Path(
            config.get("system", {}).get("trace_dir", "./memory/episodic")
        )

        # 記憶分層閾值（供外部查詢，Φ-iv 用）
        tiers = config.get("memory_tiers", {})
        self.theta_high = tiers.get("theta_high", 0.7)
        self.theta_low = tiers.get("theta_low", 0.3)

        logger.info(
            f"[UtilityEngine] α={self.alpha}, β={self.beta}, "
            f"γc={self.gamma_cost}, γ={self.gamma_decay}, "
            f"max_steps={self.max_steps}"
        )

    # ── 資料掃描 ──────────────────────────────────────────

    def get_run_summary_path(self) -> Path:
        """回傳 run_summary.jsonl 的完整路徑。"""
        return self.trace_dir / "run_summary.jsonl"

    def scan_run_summaries(self) -> dict[str, SkillStats]:
        """
        掃描 run_summary.jsonl，統計每個技能的 r, f, c 原始數據。

        Returns:
            dict[skill_name, SkillStats]
        """
        summary_path = self.get_run_summary_path()

        if not summary_path.exists():
            logger.warning(
                f"[UtilityEngine] run_summary.jsonl not found at {summary_path}"
            )
            return {}

        stats: dict[str, SkillStats] = {}

        with open(summary_path, encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    logger.warning(
                        f"[UtilityEngine] Invalid JSON at line {line_num}, skipping"
                    )
                    continue

                # `.get(k, default)` 在 key 存在但值是 null 時回傳 None，不是 default。
                # P1-a 之後 record 會有更多失敗路徑可能寫出 null，用 `or` 一併擋掉。
                skills_used = record.get("skills_used") or []
                total_steps = record.get("total_steps") or 0

                # ── [P1-a / B′] r 的三態判定 ──
                # 只有 verified_independent 的判定才算數（§7.1：只有這一層能叫
                # 正確率）。舊 schema、liveness、沒驗過 → r 未知，排除在 α·r 之外。
                if record.get("verification_status") == "verified_independent" \
                        and record.get("verified_success") is not None:
                    r_known = True
                    reinforce = record.get("verified_success") is True
                else:
                    r_known = False
                    reinforce = False

                for skill_name in skills_used:
                    if skill_name not in stats:
                        stats[skill_name] = SkillStats(name=skill_name)

                    s = stats[skill_name]
                    s.frequency += 1
                    s.total_steps += total_steps
                    s.task_count += 1

                    if not r_known:
                        s.unverified_count += 1
                    elif reinforce:
                        s.verified_count += 1
                        s.reinforcement += 1.0
                        s.success_count += 1
                    else:
                        s.verified_count += 1
                        s.failure_count += 1

        logger.info(
            f"[UtilityEngine] Scanned run_summary: "
            f"{len(stats)} skills with activity"
        )
        return stats

    # ── 效用計算 ──────────────────────────────────────────

    def compute_utility(
        self,
        stats: SkillStats,
        max_frequency: int = 1,
        max_reinforcement: float = 1.0,
    ) -> tuple[float, str]:
        """
        計算單一技能的靜態效用值。

        U(σ) = α·r_norm + β·f_norm - γc·c_norm

        Args:
            stats: 該技能的統計數據
            max_frequency: 所有技能中的最高使用頻率（用於正規化）
            max_reinforcement: 所有技能中的最高強化值（用於正規化）

        Returns:
            (utility_value, detail_string)
        """
        # ── [P1-a / B′] r 未知時把 α 的權重併給 β，而不是當成 r=0 ──
        # 為什麼不能當 0：實測舊 74 筆全部 r 未知，當 0 會讓 mean U 從 0.075 掉到
        # 0.029、58/59 技能低於歸檔門檻 0.25，第一次 Φ-i 就把整個 active 層清空。
        # 「排除」的意思是：沒有 r 的證據時，不因為缺證據而扣分，把該項的權重
        # 分配給還有證據的 f 項。α、β、γc 的值不動，U 的定義（Definition 4）不動，
        # 這只是「r 未定義時怎麼量」的資料處理慣例。
        r_known = stats.verified_count >= self.min_verified_for_r

        if r_known:
            r_norm = stats.reinforcement / max(max_reinforcement, 1.0)
            alpha, beta = self.alpha, self.beta
        else:
            r_norm = 0.0
            alpha, beta = 0.0, self.alpha + self.beta

        # f_norm: 相對頻率
        f_norm = stats.frequency / max(max_frequency, 1)

        # c_norm: 平均步驟數 / max_steps
        if stats.task_count > 0:
            avg_steps = stats.total_steps / stats.task_count
            c_norm = min(avg_steps / self.max_steps, 1.0)
        else:
            c_norm = 0.0

        # U(σ) = α·r + β·f - γc·c
        raw = alpha * r_norm + beta * f_norm - self.gamma_cost * c_norm

        # Clamp to [0.0, 1.0]
        utility = max(0.0, min(1.0, raw))

        detail = (
            f"U = {alpha}×{r_norm:.3f} + "
            f"{beta}×{f_norm:.3f} - "
            f"{self.gamma_cost}×{c_norm:.3f} = {raw:.4f} → {utility:.4f}"
            + ("" if r_known else
               f"  [r 未知 v={stats.verified_count}<{self.min_verified_for_r}，α 併入 β]")
        )

        return utility, detail

    def update_all_utilities(
        self,
        graph: nx.DiGraph,
    ) -> list[UtilityUpdate]:
        """
        批次更新所有 active 技能的效用值。

        流程：
          1. scan_run_summaries() 取得統計
          2. 計算 max_frequency / max_reinforcement（正規化分母）
          3. 對每個 active 節點計算 compute_utility()
          4. 寫入 graph node attributes

        不在 run_summary 中的技能保持現有效用值（僅受 decay 影響）。
        """
        all_stats = self.scan_run_summaries()

        if not all_stats:
            logger.info("[UtilityEngine] No run summaries found, skipping update")
            return []

        # 計算正規化分母
        max_freq = max((s.frequency for s in all_stats.values()), default=1)
        max_reinf = max((s.reinforcement for s in all_stats.values()), default=1.0)

        updates = []
        for name, attrs in graph.nodes(data=True):
            if attrs.get("tier") != "active":
                continue

            if name not in all_stats:
                # 沒有使用紀錄的技能，不做靜態效用更新
                continue

            stats = all_stats[name]
            old_u = attrs.get("utility", 0.5)
            new_u, detail = self.compute_utility(stats, max_freq, max_reinf)

            # 寫入 graph
            graph.nodes[name]["utility"] = round(new_u, 4)
            graph.nodes[name]["frequency"] = stats.frequency

            updates.append(UtilityUpdate(
                name=name,
                old_utility=old_u,
                new_utility=round(new_u, 4),
                r=stats.reinforcement,
                f_norm=stats.frequency / max(max_freq, 1),
                c_norm=(stats.total_steps / stats.task_count / self.max_steps
                        if stats.task_count > 0 else 0.0),
                detail=detail,
            ))

            logger.debug(f"[UtilityEngine] {name}: {old_u:.4f} → {new_u:.4f} ({detail})")

        logger.info(
            f"[UtilityEngine] Updated {len(updates)} skill utilities "
            f"(max_freq={max_freq}, max_reinf={max_reinf:.1f})"
        )
        return updates

    # ── 時間衰減 ──────────────────────────────────────────

    def apply_decay(
        self,
        graph: nx.DiGraph,
        reinforced_skills: Optional[set[str]] = None,
    ) -> list[DecayResult]:
        """
        對所有 active 技能施加一步時間衰減。

        公式: Ut+1 ← (1-γ)·Ut
        若技能在 reinforced_skills 中，標記 was_reinforced=True
        （但衰減仍然施加——ΔU 已在 update_all_utilities 中算進去了）。

        Lemma 1 保證：
          持續不使用 → Ut = U0×(1-γ)^t → 指數衰減到 θlow 以下。
        """
        if reinforced_skills is None:
            reinforced_skills = set()

        results = []
        for name, attrs in graph.nodes(data=True):
            if attrs.get("tier") != "active":
                continue

            old_u = attrs.get("utility", 0.5)
            new_u = old_u * (1.0 - self.gamma_decay)
            new_u = max(0.0, round(new_u, 6))  # 6 位精度，避免浮點誤差

            graph.nodes[name]["utility"] = new_u

            was_reinforced = name in reinforced_skills
            results.append(DecayResult(
                name=name,
                old_utility=old_u,
                new_utility=new_u,
                was_reinforced=was_reinforced,
            ))

        logger.info(
            f"[UtilityEngine] Decay applied to {len(results)} skills "
            f"(γ={self.gamma_decay}, {len(reinforced_skills)} reinforced)"
        )
        return results

    # ── 輔助工具 ──────────────────────────────────────────

    @staticmethod
    def predict_decay_steps(
        u0: float,
        gamma: float,
        threshold: float,
    ) -> int:
        """
        預測效用從 u0 衰減到 threshold 所需步數（Lemma 1）。

        t* = ceil(log(threshold / u0) / log(1 - gamma))

        若 u0 <= threshold，回傳 0（已經在閾值以下）。
        若 gamma <= 0 或 gamma >= 1，raise ValueError。
        """
        if gamma <= 0 or gamma >= 1:
            raise ValueError(f"gamma must be in (0, 1), got {gamma}")
        if u0 <= 0:
            return 0
        if u0 <= threshold:
            return 0

        # t* = ceil(log(threshold / u0) / log(1 - gamma))
        ratio = threshold / u0
        t_star = math.log(ratio) / math.log(1.0 - gamma)
        return math.ceil(t_star)

    @staticmethod
    def compute_entropy(utilities: list[float]) -> float:
        """
        計算效用分佈的 Shannon 熵 H(G)。
        論文 Proposition 3：H(Gt) 有界收斂。

        H = -Σ p_i × log2(p_i)  其中 p_i = u_i / Σu
        若所有效用為 0，回傳 0。
        """
        total = sum(utilities)
        if total <= 0:
            return 0.0

        entropy = 0.0
        for u in utilities:
            if u <= 0:
                continue
            p = u / total
            entropy -= p * math.log2(p)

        return round(entropy, 6)

    @staticmethod
    def compute_gini(utilities: list[float]) -> float:
        """
        計算效用分佈的 Gini 係數。
        論文 Proposition 4：Gini 係數非遞減。

        Gini = (Σ_i Σ_j |u_i - u_j|) / (2 × n × Σ u_i)
        若所有效用為 0，回傳 0。
        """
        n = len(utilities)
        if n == 0:
            return 0.0

        total = sum(utilities)
        if total <= 0:
            return 0.0

        # 排序加速計算
        sorted_u = sorted(utilities)
        # Gini = (2 × Σ_i (i+1)×u_i) / (n × Σu) - (n+1)/n
        cumsum = sum((i + 1) * u for i, u in enumerate(sorted_u))
        gini = (2.0 * cumsum) / (n * total) - (n + 1.0) / n

        return round(max(0.0, gini), 6)