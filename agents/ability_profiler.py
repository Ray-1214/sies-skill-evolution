"""
ability_profiler.py — 能力畫像生成 (W14 子任務 1)
==================================================
讀 W13 run_summary → 算 per-cluster 能力畫像 → 寫 data/ability_profile.json。
供 Curriculum Agent 依 frontier_signal（too_hard / calibrated / too_easy）調整出題難度。

資料來源（無 variant 欄位，靠檔案區分 baseline / improved）：
  w13_baseline → data/w13/baseline_jsonl/run_summary.jsonl   (23 seed + 50 baseline)
  w13_improved → memory/episodic/run_summary.jsonl           (23 seed + 1 + 50 improved)
  live         → memory/episodic/run_summary.jsonl           (當前)

cluster 對齊：[TD-27 step③] 改成讀每筆紀錄自帶的 `cluster` 標籤分組，不再對
TASKS_50 做位置對齊。CLUSTER_RANGES 現在只當合法 cluster 名的白名單。

per_domain：skills/{active,cold,archive}/**/SKILL.md frontmatter 的 domain(list) + 目錄當 tier。
            success_rate 一律 None（run_summary 無 per-task domain tag，無法歸因）。
"""

import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import yaml

logger = logging.getLogger(__name__)

TZ_TPE = timezone(timedelta(hours=8))

SOURCE_FILES = {
    "w13_baseline": "data/w13/baseline_jsonl/run_summary.jsonl",
    "w13_improved": "memory/episodic/run_summary.jsonl",
    "live":         "memory/episodic/run_summary.jsonl",
}

CLUSTER_RANGES = {
    "C1": (0, 12),
    "C2": (12, 24),
    "C3": (24, 34),
    "C4": (34, 42),
    "C5": (42, 50),
}

# 七個 registry domain（domain_registry.py 白名單）
REGISTRY_DOMAINS = [
    "software-engineering",
    "research",
    "data-analysis",
    "content-creation",
    "web-automation",
    "system-ops",
    "planning",
]

TIERS = ["active", "cold", "archive"]

# frontier 閾值
FRONTIER_LOW = 0.40
FRONTIER_HIGH = 0.70

OUTPUT_DIR = Path("data")
SKILLS_ROOT = Path("skills")


def _now_iso() -> str:
    return datetime.now(TZ_TPE).isoformat()


def _load_jsonl(path: Path) -> list[dict]:
    records = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def _cluster_of(pos: int) -> Optional[str]:
    """0-indexed 位置 → cluster 短名（C1..C5）。"""
    for cname, (lo, hi) in CLUSTER_RANGES.items():
        if lo <= pos < hi:
            return cname
    return None


def _read_skill_frontmatter(skill_md: Path) -> dict:
    """讀 SKILL.md YAML frontmatter（--- ... --- 之間），yaml.safe_load 自動解 anchor。"""
    text = skill_md.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    # 取第一個 --- 與第二個 --- 之間
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}
    try:
        fm = yaml.safe_load(parts[1])
        return fm if isinstance(fm, dict) else {}
    except yaml.YAMLError:
        logger.warning(f"[ability_profiler] bad frontmatter in {skill_md}")
        return {}


def _scan_skills() -> tuple[dict, dict]:
    """
    掃 skills/{active,cold,archive}/**/SKILL.md。

    回傳:
      skill_coverage = {tier: count}
      per_domain     = {domain: {tier: count}}（同一 skill 多 domain 各記一次）
    """
    skill_coverage = {t: 0 for t in TIERS}
    per_domain = {d: {t: 0 for t in TIERS} for d in REGISTRY_DOMAINS}

    for tier in TIERS:
        tier_dir = SKILLS_ROOT / tier
        if not tier_dir.exists():
            continue
        for skill_md in tier_dir.glob("**/SKILL.md"):
            skill_coverage[tier] += 1
            fm = _read_skill_frontmatter(skill_md)
            domains = fm.get("domain", [])
            if isinstance(domains, str):
                domains = [domains]
            if not isinstance(domains, list):
                domains = []
            for d in domains:
                if d in per_domain:
                    per_domain[d][tier] += 1

    return skill_coverage, per_domain


# 每 cluster 的滾動窗與最小樣本數（跟 utility_engine 的 min_verified_for_r 同一種紀律）
PER_CLUSTER_WINDOW = 10
MIN_SAMPLES = 4


def _outcome(rec: dict) -> tuple[bool, str]:
    """
    一筆紀錄算成功還是失敗，以及**用的是哪一層**（§7.1）。

    優先序：verified_independent > verified_liveness > execution_completed。
    回傳 (成功?, 用了哪一層)。`verified_success is None` 絕不能當 True。
    """
    st = rec.get("verification_status")
    vs = rec.get("verified_success")
    if st in ("verified_independent", "verified_liveness") and vs is not None:
        return bool(vs), st
    if "execution_completed" in rec:
        return bool(rec.get("execution_completed")), "execution_completed"
    # 舊 schema：只有自報的 success
    return bool(rec.get("success")), "self_reported"


def build_profile(source: str, n_recent: int = 50,
                  path: str | None = None, write: bool = True) -> dict:
    """
    從 run_summary 算 per-cluster 能力畫像，回傳 dict。

    [TD-27 step③] 不再對 TASKS_50 做位置對齊。改成**依每筆紀錄自帶的 cluster
    標籤分組**，所以任何任務集（包含 curriculum 自動出的題）都算得出 frontier。
    位置對齊的三個相依（assert / recent[lo:hi] 切片 / _cluster_of(pos)）全部移除。

    每 cluster 只看最近 PER_CLUSTER_WINDOW 筆；不足 MIN_SAMPLES 筆時標
    insufficient_data 並且**不進 frontier_signal**（不足樣本不亂調難度）。

    Args:
        source: SOURCE_FILES 的 key
        n_recent: 從檔尾取幾筆（0 或 None = 全部）
        path: 覆寫來源檔路徑（測試用，不動 live 檔）
        write: False 時不寫 data/ability_profile_{source}.json
    """
    if source not in SOURCE_FILES:
        raise ValueError(
            f"invalid source '{source}', must be one of {sorted(SOURCE_FILES)}"
        )

    src = Path(path) if path else Path(SOURCE_FILES[source])
    all_records = _load_jsonl(src)
    recent = all_records[-n_recent:] if n_recent else all_records

    # ── 依 cluster 標籤分組（取代位置切片）──
    by_cluster: dict[str, list] = {c: [] for c in CLUSTER_RANGES}
    ignored = {"null_cluster": 0, "unknown_cluster": 0}
    for rec in recent:
        c = rec.get("cluster")
        if c is None:
            ignored["null_cluster"] += 1
        elif c in by_cluster:
            by_cluster[c].append(rec)
        else:
            ignored["unknown_cluster"] += 1

    per_cluster = {}
    for cname, group in by_cluster.items():
        group = group[-PER_CLUSTER_WINDOW:]          # 滾動窗
        attempted = len(group)
        outcomes = [_outcome(r) for r in group]
        succeeded = sum(1 for ok, _ in outcomes if ok)
        layers = sorted({lay for _, lay in outcomes})
        steps = [r.get("total_steps") or 0 for r in group]
        enough = attempted >= MIN_SAMPLES
        per_cluster[cname] = {
            "attempted": attempted,
            "succeeded": succeeded,
            "success_rate": round(succeeded / attempted, 3) if attempted else 0.0,
            "avg_steps": round(sum(steps) / attempted, 2) if attempted else 0.0,
            # 哪一層的訊號算出來的 —— 論文主表只能用 verified_independent
            "outcome_layers": layers,
            "sufficient": enough,
        }

    # ── frontier_signal：樣本不足的 cluster 不進任何一類 ──
    frontier_signal = {"too_hard": [], "calibrated": [], "too_easy": [],
                       "insufficient_data": []}
    for cname, st in per_cluster.items():
        if not st["sufficient"]:
            frontier_signal["insufficient_data"].append(cname)
            continue
        sr = st["success_rate"]
        if sr < FRONTIER_LOW:
            frontier_signal["too_hard"].append(cname)
        elif sr <= FRONTIER_HIGH:
            frontier_signal["calibrated"].append(cname)
        else:
            frontier_signal["too_easy"].append(cname)

    skill_coverage, per_domain_counts = _scan_skills()
    per_domain = {
        d: {"skill_count": per_domain_counts[d], "success_rate": None}
        for d in REGISTRY_DOMAINS
    }

    recent_failures = []
    for rec in recent:
        ok, layer = _outcome(rec)
        if not ok:
            recent_failures.append({
                "task_id": rec.get("task_id"),
                "cluster": rec.get("cluster"),      # 直接讀標籤，不再靠位置推
                "layer": layer,
                "ts": rec.get("timestamp"),
            })

    profile = {
        "source": source,
        "last_updated": _now_iso(),
        "window_policy": {"per_cluster_recent": PER_CLUSTER_WINDOW,
                          "minimum_samples": MIN_SAMPLES},
        "per_cluster": per_cluster,
        "per_domain": per_domain,
        "skill_coverage": skill_coverage,
        "recent_failures": recent_failures,
        "frontier_signal": frontier_signal,
        "ignored_records": ignored,
    }

    if write:
        out_path = OUTPUT_DIR / f"ability_profile_{source}.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(profile, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"[ability_profiler] wrote {out_path} (source={source})")
    return profile


# ---------------------------------------------------------------------------
# Smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    from pprint import pprint

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    print("=" * 70)
    print("=== build_profile('w13_baseline') ===")
    print("=" * 70)
    p_base = build_profile("w13_baseline")
    pprint(p_base, width=100, sort_dicts=False)

    base_succeeded = sum(c["succeeded"] for c in p_base["per_cluster"].values())
    base_attempted = sum(c["attempted"] for c in p_base["per_cluster"].values())
    print(f"\n[check] baseline: attempted={base_attempted} (expect 50), "
          f"succeeded={base_succeeded} (expect 49), "
          f"recent_failures={len(p_base['recent_failures'])} (expect 1)")

    print("\n" + "=" * 70)
    print("=== build_profile('w13_improved') ===")
    print("=" * 70)
    p_imp = build_profile("w13_improved")
    pprint(p_imp, width=100, sort_dicts=False)

    imp_succeeded = sum(c["succeeded"] for c in p_imp["per_cluster"].values())
    imp_attempted = sum(c["attempted"] for c in p_imp["per_cluster"].values())
    print(f"\n[check] improved: attempted={imp_attempted} (expect 50), "
          f"succeeded={imp_succeeded} (expect 50), "
          f"recent_failures={len(p_imp['recent_failures'])} (expect 0)")
