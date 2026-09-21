"""
w16_run.py — W16 長跑的最小儀器（P6′）
======================================
一次長跑要留下「不靠終端輸出、不靠人的記憶」就能重建全部數據的 run 目錄。

    data/w16/runs/<run_id>/
      manifest.json        git commit / worktree hash / config 快照 / 參數
      tasks.jsonl      ⭐ 凍結題庫 —— 課程是即時生成的，題目在跑完之前不存在。
                          沒有這個，事後**無法**重跑 no-skill 對照組，ρ 會重蹈
                          W13 覆轍（那次 within-variant batch-1 當參照，
                          cross-variant 區辨力弱）。跑完 cp 進 data/frozen_tasksets/
      attempts.jsonl       一題一筆，**保證每次 dequeue 恰好一筆**（含 A1 就失敗的）
      events.jsonl         ts + type 的事件流（給圖表腳本與未來的前端）
      checkpoints/NNN.json 每 10 題：Φ 前後的圖狀態 + 三方一致性
      graph_snapshots/graph_NNN.md
      run.log

不變式：`wc -l attempts.jsonl` == 題數，attempt_no 連續。

⚠️ 這支會打本地 Gemma（實測 86-145 秒/題），50 題約 1.2-2 小時。
   啟動前先跑 scripts/w16_preflight.py。
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNTIME_ROOT = ROOT
RUNTIME_CONFIG = ROOT / "config.yaml"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

TZ = timezone(timedelta(hours=8))
CONTAINER = "sies-agent-zero"
RUNS = ROOT / "data" / "w16" / "runs"
LOCK = ROOT / "data" / "w16" / ".runlock"
TMP_KEEP = {"models", "pulse-PKdhtXMmr18n"}


def now():
    return datetime.now(TZ).isoformat()


# ── PID lock ────────────────────────────────────────────────────────
# GRAPH_INDEX.md 是 read-modify-write 且**沒有鎖**（evolution_operator:551-558），
# 兩個長跑同時跑會互相覆蓋。

class RunLock:
    @staticmethod
    def archive():
        if LOCK.exists():
            import uuid
            destination = RUNTIME_ROOT / "backups/runlocks"
            destination.mkdir(parents=True, exist_ok=True)
            LOCK.rename(destination / f"runlock-{uuid.uuid4().hex}.txt")

    def __enter__(self):
        LOCK.parent.mkdir(parents=True, exist_ok=True)
        if LOCK.exists():
            try:
                pid = int(LOCK.read_text().split()[0])
                if Path(f"/proc/{pid}").exists():
                    raise SystemExit(f"另一個長跑在跑 (pid={pid})：{LOCK}")
            except (ValueError, IndexError):
                pass
            self.archive()
        LOCK.write_text(f"{os.getpid()} {now()}\n")
        return self

    def __exit__(self, *a):
        self.archive()


# ── 沙箱 ────────────────────────────────────────────────────────────

def sh(cmd, timeout=180):
    r = subprocess.run(["docker", "exec", "-e", "SDL_VIDEODRIVER=dummy",
                        CONTAINER, "bash", "-lc", cmd],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout, r.stderr


def clean_tmp():
    """TD-11：任務間無隔離。C4 的範本題是「列出 /tmp 下所有 .py 並計數」，
    它的正確答案會是前面所有題殘留物的函數。不清就沒有可重現的結果。"""
    keep = " ".join(f"! -name '{k}'" for k in TMP_KEEP)
    _, out, _ = sh("ls -A /tmp | wc -l")
    before = int((out or "0").strip() or 0)
    sh(f"find /tmp -mindepth 1 -maxdepth 1 {keep} -exec rm -rf {{}} + 2>/dev/null; true")
    _, out, _ = sh("ls -A /tmp | wc -l")
    return before, int((out or "0").strip() or 0)


# ── run 目錄 ────────────────────────────────────────────────────────

class RunDir:
    def __init__(self, run_id):
        self.dir = RUNS / run_id
        for sub in ("", "checkpoints", "graph_snapshots"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)
        self.run_id = run_id

    def append(self, name, obj):
        with (self.dir / name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")

    def event(self, etype, **kw):
        """events.jsonl：每筆有 ts + type（圖表腳本與未來前端的來源）。"""
        self.append("events.jsonl", {"ts": now(), "type": etype, **kw})

    def write(self, rel, text):
        p = self.dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


def worktree_hash() -> str:
    """未 commit 的改動也要能對得上 —— manifest 記工作樹的雜湊。"""
    h = hashlib.sha256()
    for pat in ("agents/*.py", "evolution/*.py", "scripts/*.py", "*.py", "config.yaml"):
        for f in sorted(ROOT.glob(pat)):
            h.update(f.read_bytes())
    return h.hexdigest()[:16]


def graph_stats():
    import parse_graph_index as pgi
    d = pgi.parse_graph_index(str(RUNTIME_ROOT / "skills" / "GRAPH_INDEX.md"))
    nodes = d["nodes"]; edges = d["edges"]
    names = {n["name"] for n in nodes}
    touched = {e["source"] for e in edges} | {e["target"] for e in edges}
    boot = {"web-search", "data-analysis", "text-summary", "code-execution", "file-io"}
    return {
        "nodes": len(nodes), "edges": len(edges),
        "isolates": len(names - touched),
        "isolate_ratio": round(len(names - touched) / max(len(names), 1), 4),
        "macros": len([n for n in names if str(n).startswith("macro-")]),
        "composes_into": len([e for e in edges if e.get("relation") == "composes_into"]),
        "provenance": len([e for e in edges if e.get("provenance") == "curriculum_path"]),
        "bootstrap": len([e for e in edges
                          if e["source"] in boot and e["target"] in boot]),
        "tiers": {t: len([n for n in nodes if n.get("tier") == t])
                  for t in ("active", "cold", "archive")},
    }


def integrity():
    import parse_graph_index as pgi
    # 排除 candidates/（還沒進圖的候選）
    fs = len([p for p in (RUNTIME_ROOT / "skills").glob("**/SKILL.md")
              if p.relative_to(RUNTIME_ROOT / "skills").parts[0] in ("active", "cold", "archive")])
    g = len(pgi.parse_graph_index(str(RUNTIME_ROOT / "skills" / "GRAPH_INDEX.md"))["nodes"])
    try:
        import lancedb
        import yaml
        cfg = yaml.safe_load(RUNTIME_CONFIG.read_text())
        vs = cfg.get("vector_store", {})
        l = lancedb.connect(str(RUNTIME_CONFIG.parent / vs.get("path", "./data/lancedb"))) \
            .open_table(vs.get("table_name", "skill_embeddings")).count_rows()
    except Exception:  # noqa: BLE001
        l = -1
    return {"filesystem_skills": fs, "graph_nodes": g, "lancedb_rows": l,
            "consistent": fs == g == l}


# ── 主流程 ──────────────────────────────────────────────────────────

def main():
    global RUNTIME_ROOT, RUNTIME_CONFIG, RUNS, LOCK
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--direction", required=True)
    ap.add_argument("--domain", default="pipeline")
    ap.add_argument("--tasks", type=int, default=50, help="總題數")
    ap.add_argument("--phi-every", type=int, default=10)
    ap.add_argument("--config", default=str(ROOT / "config.yaml"))
    ap.add_argument("--run-id")
    ap.add_argument("--no-skill", "--no-skills", dest="no_skill", action="store_true",
                    help="對照組：關閉 A2 技能檢索，跑凍結題庫")
    ap.add_argument("--taskset", help="用既有的凍結題庫（no-skill 對照組用）")
    ap.add_argument("--dry-run", type=int, metavar="N",
                    help="只跑 N 題驗證儀器，不做 Φ")
    args = ap.parse_args()
    if args.phi_every < 1:
        ap.error("--phi-every must be positive")
    import yaml
    RUNTIME_CONFIG = Path(args.config).resolve()
    cfg = yaml.safe_load(RUNTIME_CONFIG.read_text(encoding="utf-8"))
    RUNTIME_ROOT = Path(cfg.get("system", {}).get("project_root", ".")).resolve()
    RUNS = RUNTIME_ROOT / "data/w16/runs"
    LOCK = RUNTIME_ROOT / "data/w16/.runlock"

    n_target = args.dry_run or args.tasks
    run_id = args.run_id or (
        f"w16-{args.domain}-{datetime.now(TZ).strftime('%Y%m%dT%H%M%S')}"
        + ("-noskill" if args.no_skill else ""))

    with RunLock():
        rd = RunDir(run_id)
        import yaml
        from agents.agent_runner import AgentRunner
        from agents.llm_client import LLMClient
        from agents.path_generator import PathGenerator
        from verify_runner import check_only

        cfg = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
        from evolution.evolution_triggers import EvolutionTriggers, evolution_decision
        triggers = EvolutionTriggers(args.config)
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                                capture_output=True, text=True).stdout.strip()
        rd.write("manifest.json", json.dumps({
            "run_id": run_id, "started_at": now(),
            "git_commit": commit, "worktree_hash": worktree_hash(),
            "args": vars(args), "config": cfg,
            "graph_before": graph_stats(), "integrity_before": integrity(),
        }, ensure_ascii=False, indent=2))
        rd.event("run_start", run_id=run_id, target=n_target)
        print(f"[W16] run_id={run_id}  target={n_target}  no_skill={args.no_skill}")

        # ── 題庫：凍結既有的，或現生 ──
        if args.taskset:
            quads = json.loads(Path(args.taskset).read_text(encoding="utf-8"))
            print(f"[W16] 用凍結題庫 {args.taskset}（{len(quads)} 題）")
        else:
            llm = LLMClient({**cfg.get("llm", {}), "temperature": 0.6})
            gen = PathGenerator(llm, domain=args.domain)
            quads = []
            pi = 0
            empty = 0
            while len(quads) < n_target and pi < 40:
                pi += 1
                # 出題階段炸掉不該賠掉整場長跑（掛機時沒人在旁邊重啟）。
                # 例外一律降級成「這條路徑收 0 題」，跟下面的空批走同一個門檻。
                try:
                    batch = gen.generate(args.direction, path_id=f"{run_id}-p{pi:02d}")
                except Exception as e:  # noqa: BLE001
                    print(f"[W16] 路徑 p{pi:02d} 出題例外，跳過："
                          f"{type(e).__name__}: {e}")
                    batch = []
                if not batch:
                    empty += 1
                    if empty >= 2:
                        print("[W16] 出題連續失敗，停"); break
                    continue
                empty = 0
                quads.extend(batch)
                rd.event("path_generated", path_id=f"{run_id}-p{pi:02d}", n=len(batch))
                print(f"[W16] 路徑 p{pi:02d}: {len(batch)} 題（累計 {len(quads)}/{n_target}）")

        quads = quads[:n_target]

        for q in quads:
            rd.append("tasks.jsonl", {**q, "run_id": run_id, "frozen_at": now()})
        print(f"[W16] 凍結題庫 {len(quads)} 題 → tasks.jsonl")

        runner = AgentRunner(args.config, no_skills=args.no_skill)

        # 對照組不演化。技能庫若在背景成長、A2 又因 no_skills 不去檢索它，
        # 比較的就不是「有技能庫 vs 無技能庫」，而是
        # 「有技能庫 vs 技能庫在背景演化但用不到」—— 那不是對照組。
        # 這個條件在 2026-09-17 的合併中曾被無意間移除，
        # 由 tests/test_no_skill_never_evolves.py 守住。
        EVOLUTION_ENABLED = not args.no_skill

        for i, q in enumerate(quads, 1):
            res = None
            before, after = clean_tmp()          # TD-11
            wd = f"/tmp/w16_{q['task_id']}"
            t0 = time.time()
            rd.event("attempt_start", attempt_no=i, task_id=q["task_id"],
                     tmp_cleaned=before - after)
            rec = {"run_id": run_id, "attempt_no": i, "task_id": q["task_id"],
                   "cluster": q.get("cluster"), "domain": q.get("domain"),
                   "level": q.get("level"), "path_id": q.get("path_id"),
                   "path_pos": q.get("path_pos"), "started_at": now()}
            try:
                from verify_runner import derive_expected, put_file, clean_workdir
                exp, why = derive_expected(q, wd)
                if exp is None:
                    raise RuntimeError(f"參考解失敗: {why}")
                q2 = {**q, "expected": exp}
                for name, content in (q.get("input_files") or {}).items():
                    put_file(f"{wd}/{name}", content)
                # 題目寫「read X in the current directory」，但 code_execution 的
                # cwd 不確定 —— dry-run 實測 agent 全部在跟路徑搏鬥，抽出來的技能
                # 是 file-location-discovery / path-resolution-debugging 而不是
                # 領域技能（P5-0 的「跟環境搏鬥」現象重現）。改成給絕對路徑。
                prompt = (
                    f"{q['task_description']}\n\n"
                    f"IMPORTANT: every file in this task lives in {wd}. "
                    f"Read inputs from and write outputs to that exact directory using "
                    f"absolute paths, e.g. {wd}/<filename>. Do not assume the current "
                    f"working directory is {wd}.\n"
                    f"Files already present there: "
                    f"{', '.join(f'{wd}/{n}' for n in (q.get('input_files') or {}))}")
                res = runner.run(
                    prompt,
                    cluster=q.get("cluster"),
                    meta={k: q.get(k) for k in ("domain", "level", "path_id", "path_pos")},
                    # check_only 而不是 verify_task —— 後者會重新 derive，
                    # 而 derive 的第一步是 clean_workdir()，會洗掉 agent 的產出
                    verify=lambda _r, _e=exp, _w=wd, _i=q.get("oracle"):
                        check_only(_e, _w, _i))
                rec.update(
                    pipeline_success=res.pipeline_success,
                    execution_completed=res.execution_success,
                    verified_success=res.verified_success,
                    verification_status=res.verification_status,
                    verify_detail=res.verify_detail,
                    total_steps=res.execution_steps,
                    skills_used=res.skills_used,
                    produced_skills=[c.name for c in res.evaluation.validated_candidates]
                                    if res.evaluation else [],
                    error_stage=res.error_stage, error=res.error,
                    llm_calls=res.llm_calls, prompt_tokens=res.prompt_tokens,
                    completion_tokens=res.completion_tokens, tool_calls=res.tool_calls,
                    stage_status=AgentRunner._stage_status(res))
            except Exception as e:  # noqa: BLE001
                # 不變式：**每次 dequeue 恰好一筆**，連 harness 自己炸掉也要留紀錄
                rec.update(pipeline_success=False, execution_completed=False,
                           verified_success=None, verification_status="not_available",
                           verify_detail=f"harness error: {type(e).__name__}: {e}",
                           total_steps=0, skills_used=[], produced_skills=[],
                           error_stage="harness", error=str(e)[:300],
                           stage_status={"harness": "error"})
            rec["elapsed_seconds"] = round(time.time() - t0, 1)
            rec["finished_at"] = now()
            rd.append("attempts.jsonl", rec)
            rd.event("attempt_done", attempt_no=i, task_id=q["task_id"],
                     verified=rec["verified_success"],
                     execution_completed=rec["execution_completed"],
                     steps=rec["total_steps"], elapsed=rec["elapsed_seconds"],
                     produced=len(rec["produced_skills"]))
            print(f"[W16] {i}/{len(quads)} {q['task_id']} "
                  f"exec={rec['execution_completed']} verified={rec['verified_success']} "
                  f"{rec['elapsed_seconds']}s  (/tmp 清 {before}→{after})")

            if EVOLUTION_ENABLED and not args.dry_run:
                decision = evolution_decision(triggers, res, i, args.phi_every)
                if decision.triggered:
                    checkpoint(rd, i, args, run_id, trigger_result=decision)
                    runner.planner.reload_graph()

        # final 只記錄圖狀態 / 三方一致性 / 快照：不傳 trigger_result，
        # checkpoint() 內部因此不會跑 Φ（對照組也需要這份收尾紀錄）。
        checkpoint(rd, len(quads), args, run_id, final=True)
        rd.event("run_end", attempts=len(quads))

        frozen = RUNTIME_ROOT / "data" / "frozen_tasksets" / f"{run_id}.jsonl"
        frozen.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(rd.dir / "tasks.jsonl", frozen)
        print(f"\n[W16] 凍結題庫 → {frozen}（記得 git add）")
        print(f"[W16] run 目錄 → {rd.dir}")
    return 0


def checkpoint(rd, n, args, run_id, final=False, trigger_result=None):
    """每 N 題：Φ 前後圖狀態 + 三方一致性 + 圖快照。"""
    before = graph_stats()
    phi = None
    if args.no_skill:
        phi = None   # 對照組不演化，見主迴圈 EVOLUTION_ENABLED 的註解。
                     # 這裡是第二道防線：呼叫端已經擋過一次，但那個意圖
                     # 曾經只寫在呼叫端的條件裡，合併時就被拿掉了。
    elif not args.dry_run and trigger_result is not None and trigger_result.triggered:
        from evolution.evolution_operator import EvolutionOperator
        from embedding_engine import EmbeddingEngine
        from vector_store import VectorStore
        # TD-15：不注入單例的話每次 Φ 都冷載一個 8B CPU 模型
        op = EvolutionOperator(args.config)
        try:
            op._engine = _shared_engine(args.config)
            op._store = _shared_store(args.config)
        except Exception:  # noqa: BLE001
            pass
        rep = op.evolve(trigger_result=trigger_result, force=True)
        phi = {"inserted": len(rep.inserted_skills), "rejected": len(rep.rejected_skills),
               "macros": len(rep.macro_skills_created),
               "migrations": len(rep.tier_migrations),
               "candidates_found": rep.candidates_found,
               "triggered_by": rep.triggered_by}
        # provenance 邊：把課程路徑的順序落地（P3-5）
        import parse_graph_index as pgi
        from evolution.provenance_edges import run as prov_run
        g = pgi.build_graph(pgi.parse_graph_index(str(RUNTIME_ROOT / "skills" / "GRAPH_INDEX.md")))
        recs = [json.loads(l) for l in (rd.dir / "attempts.jsonl").read_text().splitlines() if l.strip()]
        prep = prov_run(g, records=recs)
        if prep.edges_added or prep.edges_upgraded:
            pgi.graph_to_index_md(g, str(RUNTIME_ROOT / "skills" / "GRAPH_INDEX.md"))
        phi["provenance_edges_added"] = prep.edges_added
        phi["provenance_edges_upgraded"] = prep.edges_upgraded

    after = graph_stats()
    ck = {"run_id": run_id, "checkpoint": n, "at": now(), "final": final,
          "graph_before_phi": before, "phi": phi, "graph_after_phi": after,
          "integrity": integrity()}
    suffix = "_final" if final else ""
    rd.write(f"checkpoints/{n:03d}{suffix}.json", json.dumps(ck, ensure_ascii=False, indent=2))
    shutil.copy(RUNTIME_ROOT / "skills" / "GRAPH_INDEX.md",
                rd.dir / "graph_snapshots" / f"graph_{n:03d}.md")
    rd.event("checkpoint", n=n, **{f"after_{k}": v for k, v in after.items()
                                   if isinstance(v, (int, float))})
    print(f"[W16] --- checkpoint {n}: nodes {before['nodes']}→{after['nodes']} "
          f"edges {before['edges']}→{after['edges']} "
          f"isolates {before['isolate_ratio']:.1%}→{after['isolate_ratio']:.1%} "
          f"integrity={'OK' if ck['integrity']['consistent'] else 'MISMATCH'}")


_ENG = _STORE = None


def _shared_engine(config_path="config.yaml"):
    global _ENG
    if _ENG is None:
        from embedding_engine import EmbeddingEngine
        _ENG = EmbeddingEngine(config_path)
    return _ENG


def _shared_store(config_path="config.yaml"):
    global _STORE
    if _STORE is None:
        from vector_store import VectorStore
        _STORE = VectorStore(config_path)
    return _STORE


if __name__ == "__main__":
    sys.exit(main())
