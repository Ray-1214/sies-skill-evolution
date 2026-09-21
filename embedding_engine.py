"""
embedding_engine.py — Skill 語義向量化引擎

功能：
  1. 載入 embedding 模型（nvidia/llama-embed-nemotron-8b，CPU 推理）
  2. 將任意文字轉為 4096 維向量
  3. 讀取 SKILL.md 並擷取關鍵語義段落後向量化

對應論文：
  - Eq. 20-21: Activation Score 中的 semantic similarity 分量
  - A2 Memory-Guided Planner 的技能檢索基礎

依賴：
  pip install sentence-transformers pyyaml --break-system-packages

用法：
  # 作為模組
  from embedding_engine import EmbeddingEngine
  engine = EmbeddingEngine("config.yaml")
  vec = engine.embed_text("搜尋網路資料")
  skill = engine.embed_skill("skills/active/web-search/SKILL.md")

  # 直接執行測試
  python embedding_engine.py
"""

import re
import yaml
import numpy as np
from pathlib import Path
from typing import Optional
from embedding_profile import embedding_profile, LEGACY_MODEL


class EmbeddingEngine:
    """
    Skill 語義向量化引擎。

    設計原則：
    - 模型只載入一次（8B 模型 ~16GB RAM，載入 ~30 秒）
    - embed_text() 是原子操作：文字 → numpy array
    - embed_skill() 從 SKILL.md 擷取最有辨識度的段落再向量化
    """

    def __init__(self, config_path: str = "config.yaml"):
        """
        從 config.yaml 讀取 embedding 設定並載入模型。

        config.yaml 需要的欄位：
          embedding:
            model: "nvidia/llama-embed-nemotron-8b"
            device: "cpu"
            batch_size: 8
            max_seq_length: 512
        """
        self.config = self._load_config(config_path)
        self._client = None
        self.model = None
        if self.profile["provider"] == "local":
            self.model = self._load_model()
            if self.model.get_sentence_embedding_dimension() != self.profile["dimension"]:
                raise ValueError("Local model dimension does not match the embedding profile")
        else:
            import httpx
            from agents.provider_support import api_key
            self.api_key = api_key(self.config)
            self._client = httpx.Client(timeout=self.config.get("timeout", 120))

    def _load_config(self, config_path: str) -> dict:
        """讀取 config.yaml 中的 embedding 區塊"""
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config not found: {config_path}")

        with open(path, encoding="utf-8") as f:
            full_config = yaml.safe_load(f)

        emb_config = full_config.get("embedding", {})
        self.profile = embedding_profile(full_config)

        # 提供預設值，避免 config 缺欄位時 crash
        return {
            **emb_config,
            "model": emb_config.get("model", "nvidia/llama-embed-nemotron-8b"),
            "device": emb_config.get("device", "cpu"),
            "batch_size": emb_config.get("batch_size", 8),
            "max_seq_length": emb_config.get("max_seq_length", 512),
        }

    def _load_model(self):
        """
        載入 SentenceTransformer 模型。

        注意：
        - trust_remote_code=True 是 nvidia 模型的必要參數
        - CPU 載入約 30 秒，~16GB RAM
        - 模型物件建議全程只建一個實例
        """
        from sentence_transformers import SentenceTransformer

        print(f"[embedding_engine] Loading {self.config['model']} on {self.config['device']}...")
        options = {"device": self.config["device"],
                   "trust_remote_code": self.config.get("trust_remote_code", self.config["model"] == LEGACY_MODEL)}
        if self.config.get("revision"):
            options["revision"] = self.config["revision"]
        model = SentenceTransformer(self.config["model"], **options)
        # 限制最大 token 長度，避免超長輸入爆記憶體
        model.max_seq_length = self.config["max_seq_length"]
        print(f"[embedding_engine] Model loaded. dim={model.get_sentence_embedding_dimension()}")
        return model

    # ── 核心 API ──────────────────────────────────────────────

    def embed_text(self, text: str) -> np.ndarray:
        """
        將一段文字轉為向量。

        Args:
            text: 任意字串（會被 tokenizer 截斷到 max_seq_length）
        Returns:
            numpy array, shape=(4096,), dtype=float32
        """
        if self.model is None:
            return self.embed_texts([text])[0]
        return self.model.encode(text, normalize_embeddings=True)

    def embed_texts(self, texts: list[str]) -> np.ndarray:
        """
        批次向量化（比逐筆快，因為可以利用 CPU 的 batch 並行）。

        Args:
            texts: 字串列表
        Returns:
            numpy array, shape=(len(texts), 4096), dtype=float32
        """
        if self.model is None:
            return self._remote_texts(texts)
        return self.model.encode(
            texts,
            normalize_embeddings=True,
            batch_size=self.config["batch_size"],
            show_progress_bar=len(texts) > 5,
        )

    def _remote_texts(self, texts):
        from urllib.parse import quote
        from agents.provider_support import endpoint, post_json, ACTIVE_BUDGET, ProviderError
        if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
            raise ValueError("Embedding input must be a list of text strings")
        size = self.config["batch_size"]
        if type(size) is not int or size < 1:
            raise ValueError("embedding.batch_size must be positive")
        output = []
        for start in range(0, len(texts), size):
            batch = texts[start:start+size]
            model = self.config["model"]
            base = self.profile["endpoint"]
            if self.profile["provider"] == "google":
                model = "models/"+model.removeprefix("models/")
                url = endpoint(base, "models/"+quote(model.removeprefix("models/"), safe="-._")+":batchEmbedContents", "v1beta")
                options = {"outputDimensionality": self.profile["dimension"]}
                if self.config.get("task_type"):
                    options["taskType"] = self.config["task_type"]
                payload = {"requests": [{"model": model, "content": {"parts": [{"text": text}]},
                                          "embedContentConfig": options} for text in batch]}
                headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
            else:
                url = endpoint(base, "embeddings")
                payload = {"model": model, "input": batch, "encoding_format": "float"}
                if self.config.get("send_dimensions", False):
                    payload["dimensions"] = self.profile["dimension"]
                headers = {"Authorization": "Bearer "+self.api_key, "Content-Type": "application/json"}
            data = post_json(self._client, url, headers, payload, self.config.get("max_retries", 0))
            if self.profile["provider"] == "google":
                vectors = [row["values"] for row in data.get("embeddings", [])]
                usage = {"input_tokens": (data.get("usageMetadata") or {}).get("promptTokenCount", 0)}
            else:
                rows = sorted(data.get("data", []), key=lambda row: row.get("index", -1))
                if [row.get("index") for row in rows] != list(range(len(batch))):
                    raise ProviderError("Embedding response indices do not match the input batch")
                vectors = [row["embedding"] for row in rows]
                usage = data.get("usage") or {}
            if ACTIVE_BUDGET.get():
                ACTIVE_BUDGET.get().observe(usage)
            array = np.asarray(vectors, dtype=np.float32)
            if array.shape != (len(batch), self.profile["dimension"]) or not np.isfinite(array).all():
                raise ProviderError("Embedding shape or values do not match the configured profile")
            norms = np.linalg.norm(array, axis=1, keepdims=True)
            if (norms == 0).any() or not np.isfinite(norms).all():
                raise ProviderError("Embedding contains an invalid zero/overflow vector")
            output.extend(array/norms)
        return np.asarray(output, dtype=np.float32).reshape((-1, self.profile["dimension"]))

    def close(self):
        if self._client is not None:
            self._client.close()

    def embed_skill(self, skill_path: str) -> Optional[dict]:
        """
        讀取一個 SKILL.md，擷取關鍵語義段落，向量化。

        擷取策略：拼接 name + description + execution policy 前 200 字。
        這三個欄位是技能最有辨識度的部分，512 token 足夠覆蓋。

        Args:
            skill_path: SKILL.md 的路徑
        Returns:
            {
                "name": str,
                "path": str,
                "text": str,      # 送去 embed 的原始文字（方便 debug）
                "vector": np.ndarray (4096,)
            }
            如果檔案不存在或解析失敗，回傳 None
        """
        path = Path(skill_path)
        if not path.exists():
            print(f"[embedding_engine] WARN: {skill_path} not found, skipping")
            return None

        content = path.read_text(encoding="utf-8")

        # 解析 YAML frontmatter
        frontmatter = self._parse_frontmatter(content)
        if frontmatter is None:
            print(f"[embedding_engine] WARN: no frontmatter in {skill_path}, skipping")
            return None

        name = frontmatter.get("name", path.parent.name)
        description = frontmatter.get("description", "")

        # [P2-1] 原本硬找 "Execution Policy"，但 A3 產的 SKILL.md 寫的是
        # "## Strategy Steps (πσ)"（base_extractor.py:470），舊檔是 "## 執行策略"。
        # 結果 90 個向量裡 85 個只編碼了 name|description，**唯一真正被重複的
        # 東西（執行步驟）94% 沒進索引**，去重因此看不見行為重複。
        # 改用 skill_md_sections 的共用 alias 表，並記下抽取來源。
        _n, _d, text, source = self._skill_embed_text(content, path)
        if source == "empty":
            print(f"[embedding_engine] WARN: {path} 抽不到任何行為描述，"
                  f"這個向量只有 name|description，去重對它是盲的")

        vector = self.embed_text(text)

        return {
            "name": name,
            "path": str(path),
            "strategy_source": source,   # [P2-1] alias / body_fallback / empty
            "text": text,
            "vector": vector,
            "embedding_profile": self.profile["id"],
        }

    @staticmethod
    def _skill_embed_text(content: str, path) -> tuple[str, str, str, str]:
        """[P2-1] 技能向量文字的**唯一**組裝點。embed_skill 與 embed_skills_batch
        共用，避免兩條路徑再度分歧。回傳 (name, description, text, strategy_source)。"""
        from skill_md_sections import strategy_text, embed_text_for
        import yaml as _yaml
        fm = {}
        if content.startswith("---"):
            parts = content.split("---", 2)
            if len(parts) >= 3:
                try:
                    fm = _yaml.safe_load(parts[1]) or {}
                except _yaml.YAMLError:
                    fm = {}
        name = fm.get("name", path.parent.name)
        description = fm.get("description", "")
        strategy, source = strategy_text(content)
        return name, description, embed_text_for(name, description, strategy), source

    def embed_skills_batch(self, skill_paths: list[str]) -> list[dict]:
        """
        批次向量化多個 SKILL.md。

        先擷取所有文字，再一次性 batch encode（比逐筆快）。

        Args:
            skill_paths: SKILL.md 路徑列表
        Returns:
            成功向量化的 skill 列表（跳過不存在或解析失敗的）
        """
        # Phase 1: 擷取文字
        entries = []
        for sp in skill_paths:
            path = Path(sp)
            if not path.exists():
                print(f"[embedding_engine] WARN: {sp} not found, skipping")
                continue

            content = path.read_text(encoding="utf-8")
            frontmatter = self._parse_frontmatter(content)
            if frontmatter is None:
                print(f"[embedding_engine] WARN: no frontmatter in {sp}, skipping")
                continue

            # [P2-1] 這裡原本有一份跟 embed_skill 重複的文字組裝，而且是硬找
            # "Execution Policy" 的舊版。rebuild_index 走的是這條路徑，所以只補
            # embed_skill 的話**重建出來的索引仍然是殘缺的**（實測：補完 embed_skill
            # 後重建，90 個 text 一個字都沒變）。改成兩條路徑共用同一個 helper。
            name, description, text, source = self._skill_embed_text(content, path)
            if source == "empty":
                print(f"[embedding_engine] WARN: {sp} 抽不到任何行為描述，"
                      f"這個向量只有 name|description，去重對它是盲的")
            entries.append({"name": name, "path": str(path), "text": text,
                            "strategy_source": source})

        if not entries:
            return []

        # Phase 2: 批次向量化
        texts = [e["text"] for e in entries]
        vectors = self.embed_texts(texts)

        # Phase 3: 組合結果
        for i, entry in enumerate(entries):
            entry["vector"] = vectors[i]
            entry["embedding_profile"] = self.profile["id"]

        return entries

    # ── 內部工具 ──────────────────────────────────────────────

    @staticmethod
    def _parse_frontmatter(content: str) -> Optional[dict]:
        """
        解析 SKILL.md 的 YAML frontmatter（--- ... --- 區塊）。

        Returns:
            解析後的 dict，或 None（如果沒有 frontmatter）
        """
        # 匹配第一個 ---...--- 區塊
        match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
        if not match:
            return None
        try:
            return yaml.safe_load(match.group(1))
        except yaml.YAMLError:
            return None

    @staticmethod
    def _extract_section(content: str, section_name: str) -> str:
        """
        從 markdown body 中擷取指定 section 的內容。

        支援格式：
          ## Execution Policy (πσ)
          ## Execution Policy
          兩種都能匹配。

        Returns:
            section 內容（不含標題行），或空字串
        """
        # 匹配 ## Section Name 開頭（忽略括號裡的內容）
        pattern = rf"^##\s+{re.escape(section_name)}.*?\n(.*?)(?=^##\s|\Z)"
        match = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if match:
            return match.group(1).strip()
        return ""


# ── 直接執行測試 ─────────────────────────────────────────────

if __name__ == "__main__":
    import time
    import sys

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"

    print("=" * 60)
    print("embedding_engine.py — 測試")
    print("=" * 60)

    t0 = time.time()
    engine = EmbeddingEngine(config_path)
    print(f"Model load time: {time.time() - t0:.1f}s\n")

    # 測試 1: 單筆文字
    print("--- Test 1: embed_text ---")
    vec = engine.embed_text("搜尋網路取得最新資訊")
    print(f"dim={len(vec)}, norm={np.linalg.norm(vec):.4f}, first 3={vec[:3]}\n")

    # 測試 2: 批次文字
    print("--- Test 2: embed_texts (batch) ---")
    texts = [
        "search the web for information",
        "execute Python code in sandbox",
        "analyze data and generate reports",
    ]
    vecs = engine.embed_texts(texts)
    print(f"batch shape={vecs.shape}")
    # 印出兩兩相似度，驗證語義差異
    from numpy.linalg import norm
    for i in range(len(texts)):
        for j in range(i + 1, len(texts)):
            sim = np.dot(vecs[i], vecs[j]) / (norm(vecs[i]) * norm(vecs[j]))
            print(f"  sim('{texts[i][:30]}', '{texts[j][:30]}') = {sim:.4f}")
    print()

    # 測試 3: 向量化單一 SKILL.md
    print("--- Test 3: embed_skill ---")
    test_skill = "skills/active/web-search/SKILL.md"
    result = engine.embed_skill(test_skill)
    if result:
        print(f"name={result['name']}, path={result['path']}")
        print(f"text preview: {result['text'][:100]}...")
        print(f"vector dim={len(result['vector'])}, first 3={result['vector'][:3]}")
    else:
        print(f"WARN: {test_skill} 解析失敗")
    print()

    # 測試 4: 批次向量化所有 active skills
    print("--- Test 4: embed_skills_batch (all active) ---")
    from parse_graph_index import parse_graph_index
    parsed = parse_graph_index()
    skill_paths = [n["path"] for n in parsed["nodes"]]
    print(f"Found {len(skill_paths)} skills in GRAPH_INDEX.md")

    t0 = time.time()
    results = engine.embed_skills_batch(skill_paths)
    elapsed = time.time() - t0

    print(f"Successfully embedded: {len(results)}/{len(skill_paths)}")
    print(f"Batch embed time: {elapsed:.1f}s ({elapsed/max(len(results),1):.2f}s per skill)")
    print()
    for r in results:
        print(f"  [{r['name']}] vec[:3]={r['vector'][:3]}")
