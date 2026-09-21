"""curriculum_smoke.py — W15 時代的 CurriculumAgent smoke script。

[P5-a] 從 agents/curriculum_agent.py 的 __main__ 搬過來 —— 那裡現在是有 argparse
的 CLI（--direction）。這支保留原樣供回歸對照，沒有 argparse，直接跑就好。
"""

import sys, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

if True:
    import shutil
    import tempfile
    import yaml

    from agents.llm_client import LLMClient
    from agents.task_queue import TaskQueue

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    # ── 確保 ability_profile_live.json 存在 ──
    live_path = Path("data/ability_profile_live.json")
    if not live_path.exists():
        imp = Path("data/ability_profile_w13_improved.json")
        if imp.exists():
            shutil.copy(imp, live_path)
            print(f"[smoke] copied improved profile → {live_path}")
        else:
            from agents.ability_profiler import build_profile
            build_profile("live")
            print(f"[smoke] built {live_path} via build_profile('live')")

    # ── LLM client（bump temperature 0.6 for 出題多樣性）──
    cfg = yaml.safe_load(open("config.yaml", encoding="utf-8"))
    llm_cfg = {**cfg.get("llm", {}), "temperature": 0.6}
    llm = LLMClient(llm_cfg)

    # ── TaskQueue 用臨時檔（不污染 data/queue.jsonl）──
    tmp_queue = Path(tempfile.mkdtemp()) / "queue_smoke.jsonl"
    q = TaskQueue(path=str(tmp_queue))

    # ── curriculum state 也用臨時檔（每次 smoke 從 level=1 起跳）──
    tmp_state = Path(tempfile.mkdtemp()) / "curriculum_state.json"

    agent = CurriculumAgent(
        profile_path=str(live_path),
        state_path=str(tmp_state),
        llm_client=llm,
        queue=q,
    )

    print("\n=== generate_tasks(k_per_cluster=1) ===\n")
    tasks = agent.generate_tasks(k_per_cluster=1)

    for t in tasks:
        print(f"--- {t['cluster']} (level {t['level']}) ---")
        print(t["task_description"])
        print()

    # 肉眼確認輔助
    levels = {t["cluster"]: t["level"] for t in tasks}
    print("=== cluster levels (frontier 全 too_easy → 應全 1→2) ===")
    print(levels)
    print(f"\n[check] all level==2? {all(v == 2 for v in levels.values())}")
    print(f"[check] 5 tasks non-empty & len>20? "
          f"{all(t['task_description'] and len(t['task_description']) > 20 for t in tasks)}")
    print(f"[check] queue items enqueued: {len(q.all_items())}")
