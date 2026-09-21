"""
scripts/audit_theta_dup.py — θdup 閾值決策 audit
==================================================
列出 LanceDB 中所有 cosine ∈ [0.78, 0.86] 的 skill pair，看在
0.80 / 0.82 / 0.85 三個候選閾值下分別會多攔下幾個 candidate。

跑完肉眼掃 0.80-0.85 區間的 pair 是否多為 TD-7 cluster 同義詞。
若是 → 設 θdup=0.80。若有 1-2 對是合理相近 → 設 0.82 折衷。

Usage (從專案根目錄):
    python scripts/audit_theta_dup.py
"""

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np
import yaml


def load_lancedb_table():
    """直接連 lancedb，繞過 vector_store wrapper（拿全表用）。"""
    import lancedb

    with open('config.yaml', encoding='utf-8') as f:
        cfg = yaml.safe_load(f)

    db_path = cfg.get('vector_store', {}).get('path', './data/lancedb')
    tbl_name = cfg.get('vector_store', {}).get('table_name', 'skill_embeddings')

    db = lancedb.connect(db_path)
    tbl = db.open_table(tbl_name)
    return tbl.to_pandas()


def main():
    df = load_lancedb_table()
    print(f'LanceDB table: {len(df)} entries')
    print(f'Columns: {list(df.columns)}')

    if 'name' not in df.columns or 'vector' not in df.columns:
        print('ERROR: expected columns "name" and "vector" not found')
        return

    names = df['name'].tolist()
    vectors = np.array(df['vector'].tolist(), dtype=np.float32)
    print(f'Vector matrix shape: {vectors.shape}')

    # vectors 應已 normalize（embed_text uses normalize_embeddings=True）；
    # 為保險再 normalize 一次，避免量化或路徑差異造成誤差
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    vectors = vectors / norms

    cos_matrix = vectors @ vectors.T  # (N, N) cosine = dot for normalized vectors

    # 提取 upper triangle pairs in band
    pairs = []
    n = len(names)
    for i in range(n):
        for j in range(i + 1, n):
            cos = float(cos_matrix[i, j])
            if 0.78 <= cos <= 0.86:
                pairs.append((names[i], names[j], cos))

    pairs.sort(key=lambda x: -x[2])

    # 三個閾值統計
    n_85 = sum(1 for *_, c in pairs if c >= 0.85)
    n_82 = sum(1 for *_, c in pairs if c >= 0.82)
    n_80 = sum(1 for *_, c in pairs if c >= 0.80)

    print(f'\n{"=" * 70}')
    print(f'θdup threshold impact')
    print(f'{"=" * 70}')
    print(f'  Pairs with cosine ≥ 0.85 (current θdup): {n_85}')
    print(f'  Pairs with cosine ≥ 0.82 (intermediate): {n_82}')
    print(f'  Pairs with cosine ≥ 0.80 (proposed):     {n_80}')
    print(f'  Pairs in [0.78, 0.86] band:              {len(pairs)}')
    print(f'')
    print(f'  Switching 0.85 → 0.80 would catch +{n_80 - n_85} additional pair(s)')
    print(f'  Switching 0.85 → 0.82 would catch +{n_82 - n_85} additional pair(s)')

    print(f'\n{"=" * 70}')
    print(f'Pair list (sorted by cosine descending)')
    print(f'{"=" * 70}')
    print(f'{"cosine":>7}  {"@status":^16} {"A":<50}  {"B":<50}')
    print('-' * 130)
    for a, b, c in pairs:
        if c >= 0.85:
            marker = '[blocked@0.85]'
        elif c >= 0.82:
            marker = '[blocked@0.82]'
        elif c >= 0.80:
            marker = '[blocked@0.80]'
        else:
            marker = '[passes all]'
        print(f'{c:>7.4f}  {marker:^16} {a:<50}  {b:<50}')

    print(f'\n{"=" * 70}')
    print(f'Decision aid')
    print(f'{"=" * 70}')
    print('Inspect pairs in the 0.80-0.85 band:')
    print('  1. If most are TD-7 cluster synonyms (test-driven-*, ')
    print('     algorithm-impl-with-*, class-impl-with-*) → set θdup=0.80')
    print('  2. If 1-2 pairs are legitimately distinct skills with high')
    print('     lexical overlap → set θdup=0.82 as compromise')
    print('  3. If most should be kept distinct → keep θdup=0.85 and')
    print('     rely on Φ-iii contraction (slower convergence but safer)')


if __name__ == '__main__':
    main()