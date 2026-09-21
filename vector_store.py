"""
vector_store.py — LanceDB 向量儲存封裝

功能：
  1. 初始化 LanceDB 資料庫與 skill_embeddings table
  2. 插入/更新技能向量
  3. 語義查詢：給定查詢向量，回傳 top-k 最相似的技能
  4. 重建索引：從 GRAPH_INDEX.md 重新向量化所有技能

對應論文：
  - Eq. 20-21: Activation Score 的 semantic similarity 分量
  - A2 Memory-Guided Planner 的技能檢索後端

依賴：
  pip install lancedb pyarrow numpy --break-system-packages

用法：
  from vector_store import VectorStore
  from embedding_engine import EmbeddingEngine

  engine = EmbeddingEngine("config.yaml")
  store = VectorStore("config.yaml")

  # 重建全部索引
  store.rebuild_index(engine)

  # 查詢
  query_vec = engine.embed_text("搜尋網路資料")
  results = store.query(query_vec, top_k=6)

  # 直接執行測試
  python vector_store.py
"""

import yaml
import json
import numpy as np
import pyarrow as pa
import lancedb
from pathlib import Path
from typing import Optional
from embedding_profile import embedding_profile


class VectorStore:
    """
    LanceDB 向量儲存封裝。

    設計原則：
    - LanceDB 是 serverless 的（直接讀寫本地資料夾，不需要跑 server）
    - table schema: name(str), path(str), text(str), vector(float32[4096])
    - 查詢用 LanceDB 內建的 L2 距離（但我們存的是 normalized 向量，
      所以 L2 距離和 cosine similarity 是單調等價的）
    """

    def __init__(self, config_path: str = "config.yaml"):
        self.config = self._load_config(config_path)
        if not self.profile["legacy"]:
            directory = Path(self.config["path"])
            directory.mkdir(parents=True, exist_ok=True)
            identity = directory / "embedding-profile.json"
            if identity.exists():
                if json.loads(identity.read_text()) != self.profile:
                    raise ValueError("Vector database embedding identity mismatch")
            else:
                # A pre-existing unidentified database must not be silently adopted.
                if any(directory.iterdir()):
                    raise ValueError("Refusing existing vector directory without embedding identity")
                with identity.open("x") as f:
                    json.dump(self.profile, f, sort_keys=True, indent=2)
        self.db = lancedb.connect(self.config["path"])
        self.table_name = self.config["table_name"]
        self._table = None  # lazy init

    def _load_config(self, config_path: str) -> dict:
        """讀取 config.yaml 中的 vector_store 區塊"""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")

        with open(path, encoding="utf-8") as f:
            full_config = yaml.safe_load(f)

        vs_config = full_config.get("vector_store", {})
        self.profile = embedding_profile(full_config)
        # [P2-1] 解析成絕對路徑（相對 config.yaml 所在目錄）。
        # config 寫的是 "./data/lancedb"，從不同 cwd 啟動會建到/查到不同的庫 ——
        # 磁碟上已經因此存在兩個分歧的庫（90 筆 vs 63 筆，sies_doctor §1 會列出）。
        raw = vs_config.get("path", "./data/lancedb")
        abs_path = (path.resolve().parent / raw).resolve()
        if not self.profile["legacy"]:
            abs_path = abs_path / ("embedding-"+self.profile["id"])
        return {
            "backend": vs_config.get("backend", "lancedb"),
            "path": str(abs_path),
            "table_name": vs_config.get("table_name", "skill_embeddings"),
        }

    @property
    def table(self):
        """Lazy access to the table. Returns None if table doesn't exist yet."""
        if self.table_name in [str(t) for t in self.db.list_tables().tables]:
            if self.table_name in self.db.list_tables().tables:
                self._table = self.db.open_table(self.table_name)
        return self._table

    # ── 核心 API ──────────────────────────────────────────────

    def upsert_skills(self, skill_entries: list[dict]):
        """
        插入或更新技能向量。

        如果 table 不存在會自動建立。
        如果 skill name 已存在會覆蓋（先刪再插）。

        Args:
            skill_entries: embed_skill() 或 embed_skills_batch() 的回傳結果
                每個 entry: {"name": str, "path": str, "text": str, "vector": np.ndarray}
        """
        if not skill_entries:
            return

        # 轉成 LanceDB 接受的格式
        records = []
        for entry in skill_entries:
            if not self.profile["legacy"] and entry.get("embedding_profile") != self.profile["id"]:
                raise ValueError("Cannot insert vectors from another or unknown embedding profile")
            vector = np.asarray(entry["vector"])
            if not self.profile["legacy"] and (vector.shape != (self.profile["dimension"],) or not np.isfinite(vector).all()):
                raise ValueError("Vector dimensions/values do not match this store")
            records.append({
                "name": entry["name"],
                "path": entry["path"],
                "text": entry["text"],
                "vector": entry["vector"].tolist(),  # LanceDB 接受 list[float]
            })

        if self.table is None:
            # 首次建立 table
            self._table = self.db.create_table(self.table_name, data=records)
            print(f"[vector_store] Created table '{self.table_name}' with {len(records)} records")
        else:
            # 刪除已存在的同名 skill，再插入新的
            existing_names = [r["name"] for r in records]
            try:
                name_list = ", ".join(f"'{n}'" for n in existing_names)
                self._table.delete(f"name IN ({name_list})")
            except Exception:
                pass  # table 可能是空的或欄位不存在，忽略
            self._table.add(records)
            print(f"[vector_store] Upserted {len(records)} records into '{self.table_name}'")

    def query(self, query_vector: np.ndarray, top_k: int = 6) -> list[dict]:
        if not self.profile["legacy"] and (np.asarray(query_vector).shape != (self.profile["dimension"],) or not np.isfinite(query_vector).all()):
            raise ValueError("Query dimensions/values do not match this store")
        if self.table is None:
            print("[vector_store] WARN: table not found, returning empty results")
            return []

        results = (
            self.table.search(query_vector.tolist())
            .limit(top_k)
            .to_arrow()
            .to_pylist()
        )

        output = []
        for row in results:
            output.append({
                "name": row["name"],
                "path": row["path"],
                "text": row["text"],
                "score": float(row["_distance"]),
            })
        return output

    def rebuild_index(self, engine, graph_index_path: str = "skills/GRAPH_INDEX.md"):
        """
        從 GRAPH_INDEX.md 重新向量化所有技能，重建 LanceDB table。

        這是一次性操作（W5 初始化 + 每次 Φ 演化後呼叫）。

        Args:
            engine: EmbeddingEngine 實例
            graph_index_path: GRAPH_INDEX.md 路徑
        """
        from parse_graph_index import parse_graph_index

        parsed = parse_graph_index(graph_index_path)
        skill_paths = [node["path"] for node in parsed["nodes"]]

        print(f"[vector_store] Rebuilding index from {len(skill_paths)} skills...")
        entries = engine.embed_skills_batch(skill_paths)

        try:
            self.db.drop_table(self.table_name)
            self._table = None
            print(f"[vector_store] Dropped old table '{self.table_name}'")
        except Exception:
            pass  # table 不存在，正常

        self.upsert_skills(entries)
        print(f"[vector_store] Rebuild complete: {len(entries)} skills indexed")

    def build_new_index(self, engine, graph_index_path: str):
        """Build a fresh provider namespace; never drop or overwrite an existing table."""
        from parse_graph_index import parse_graph_index
        if self.table is not None:
            raise ValueError("Index already exists; use a new vector_store.path for another snapshot")
        if engine.profile["id"] != self.profile["id"]:
            raise ValueError("Engine and store embedding profiles differ")
        graph_path = Path(graph_index_path).resolve()
        root = graph_path.parent.parent
        paths = []
        for node in parse_graph_index(str(graph_path))["nodes"]:
            path = (root / node["path"]).resolve()
            if not path.is_relative_to(root / "skills") or not path.is_file():
                raise ValueError("Graph references missing or external skill file")
            paths.append(str(path))
        entries = engine.embed_skills_batch(paths)
        if len(entries) != len(paths):
            raise ValueError("Some skills could not be embedded; no index was written")
        self.upsert_skills(entries)
        return len(entries)

    def list_all(self) -> list[dict]:
        """列出 table 中所有記錄（debug 用）"""
        if self.table is None:
            return []
        rows = self.table.to_arrow().to_pylist()
        records = []
        for row in rows:
            records.append({
                "name": row["name"],
                "path": row["path"],
                "text": row["text"][:80] + "...",
            })
        return records

    def count(self) -> int:
        """回傳 table 中的記錄數"""
        if self.table is None:
            return 0
        return self.table.count_rows()
    
    def update_paths(self, updates: list[dict]) -> int:
        """
        批次更新 path 欄位（不重新 embed）。
        
        Args:
            updates: [{"name": str, "new_path": str}, ...]
        Returns:
            更新成功數量
        """
        if not updates or self.table is None:
            return 0
        
        count = 0
        for u in updates:
            try:
                # LanceDB update API: where + set
                self._table.update(
                    where=f"name = '{u['name']}'",
                    values={"path": u["new_path"]},
                )
                count += 1
            except Exception as e:
                print(f"[vector_store] update_paths failed for {u['name']}: {e}")
        
        print(f"[vector_store] Updated {count}/{len(updates)} paths")
        return count


# ── 直接執行測試 ─────────────────────────────────────────────

if __name__ == "__main__":
    import time
    import sys

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"

    print("=" * 60)
    print("vector_store.py — 測試")
    print("=" * 60)

    # 載入 embedding engine
    from embedding_engine import EmbeddingEngine

    engine = EmbeddingEngine(config_path)

    # 初始化 store
    store = VectorStore(config_path)

    # 重建索引
    print("\n--- Test 1: rebuild_index ---")
    t0 = time.time()
    store.rebuild_index(engine)
    print(f"Rebuild time: {time.time() - t0:.1f}s")
    print(f"Total records: {store.count()}")

    # 列出所有記錄
    print("\n--- Test 2: list_all ---")
    for r in store.list_all():
        print(f"  [{r['name']}] {r['text']}")

    # 語義查詢測試
    print("\n--- Test 3: semantic query ---")
    test_queries = [
        "搜尋網路上最新的資訊",
        "執行 Python 程式碼",
        "分析資料並產出報告",
        "寫一個完整的功能規劃",
        "debug a failing test case",
    ]

    for q in test_queries:
        vec = engine.embed_text(q)
        results = store.query(vec, top_k=3)
        print(f"\n  Query: '{q}'")
        for i, r in enumerate(results):
            print(f"    #{i+1} [{r['name']}] L2={r['score']:.4f}")
