"""
skill_md_sections.py — SKILL.md 段落標題的單一真相
==================================================
[P2-1] 這份 alias 表原本是 `EvolutionOperator._SECTION_ALIASES`（class 內私有
屬性），只有 Φ-ii 解析候選技能時用得到。另外三個地方各自硬寫死一個標題字串：

    embedding_engine.embed_skill      找 "Execution Policy"
    memory_planner._assemble_working_memory  找 "Execution Policy"
    skill_validator._candidate_to_embed_text 用另一種拼接配方

而 **A3 產出的 SKILL.md 從來不寫 "Execution Policy"** —— `base_extractor.py:470`
寫的是 `## Strategy Steps (πσ)`，更舊的檔案是 `## 執行策略 (πσ)`。後果是
90 個向量裡有 85 個只編碼了 `name | description`（平均 185 字元），
**唯一真正被重複的東西（執行步驟）94% 沒進索引**，去重因此看不見行為重複。

把它抽成模組層常數，三方共用同一份，並附一個測試斷言三邊讀到同一個 dict。
"""

import re

SECTION_ALIASES = {
    "invocation": [
        "使用條件",              # A3 舊輸出：## 使用條件 (Iσ)
        "Invocation Condition",
    ],
    "termination": [
        "終止條件",              # A3 舊輸出：## 終止條件 (βσ)
        "Termination Condition",
    ],
    "strategy": [
        "Strategy Steps",        # A3 現行輸出：## Strategy Steps (πσ)（base_extractor.py:470）
        "執行策略",              # A3 舊輸出：## 執行策略 (πσ)
        "Execution Policy",      # 手寫 bootstrap 技能用的
    ],
}

# 向量文字的拼接分隔符 —— 索引側與查詢側必須用同一個，否則不對稱
EMBED_JOIN = " | "
# 策略段截斷長度
EMBED_STRATEGY_CHARS = 400


def extract_section(content: str, kind: str) -> str:
    """
    從 markdown body 抽出某類段落，依序試 SECTION_ALIASES[kind] 的每個別名。

    Args:
        content: SKILL.md 的 body（含或不含 frontmatter 都可）
        kind:    "invocation" | "termination" | "strategy"

    Returns:
        段落內容（不含標題行），找不到回空字串。
    """
    for alias in SECTION_ALIASES[kind]:
        pattern = rf"^#+\s*{re.escape(alias)}.*?\n(.*?)(?=^#+\s|\Z)"
        m = re.search(pattern, content, re.MULTILINE | re.DOTALL)
        if m and m.group(1).strip():
            return m.group(1).strip()
    return ""


def embed_text_for(name: str, description: str, strategy: str) -> str:
    """
    技能向量的文字配方 —— **索引側與查詢側都必須用這一個函式**。

    P2-1 之前索引側是 `" | ".join([name, desc, policy[:200]])`、查詢側是
    `f"{name} {description} {strategy[:200]}"`（空白接），兩邊不對稱。
    """
    parts = [name, description]
    if strategy:
        parts.append(strategy[:EMBED_STRATEGY_CHARS])
    return EMBED_JOIN.join(p for p in parts if p)


def strip_frontmatter(content: str) -> str:
    """去掉 YAML frontmatter，只留 markdown body。"""
    if content.startswith("---"):
        parts = content.split("---", 2)
        if len(parts) >= 3:
            return parts[2]
    return content


def strategy_text(content: str) -> tuple[str, str]:
    """
    取一個技能的「行為描述」文字，供向量索引用。

    回傳 (text, source)：
      source == "alias"          從四段式的策略段抽到（A3 產的技能）
      source == "body_fallback"  沒有策略段，退回整個 body（vendored 種子技能是
                                 散文結構，本來就沒有四段式 —— 用整個 body 比
                                 用空字串正確）
      source == "empty"          兩者都沒有 → 呼叫端該當成異常處理，不要靜默索引

    **不要靜默回空字串**：P2-1 之前 embedding_engine 找不到 "Execution Policy"
    就默默只索引 name|description，90 個向量裡 85 個是殘缺的，去重因此失效。
    """
    sec = extract_section(content, "strategy")
    if sec:
        return sec, "alias"
    body = strip_frontmatter(content)
    # 去掉 seed_postprocess 留下的 === ... === 註解區塊與 frontmatter 殘影
    lines = [l for l in body.splitlines()
             if not l.strip().startswith("#") or "===" not in l]
    body = "\n".join(lines).strip()
    if body:
        return body, "body_fallback"
    return "", "empty"
