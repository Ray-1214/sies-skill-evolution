"""
scripts/repair_filesystem_graph_consistency.py
================================================
修正 GRAPH_INDEX.md 中 path/tier 與 filesystem 實際位置不一致的 skill。

W12 mini pilot 暴露的問題：mock fixture 期間搬過某些 SKILL.md 目錄，
但當時的 GRAPH_INDEX.md 被 reset 回 mock 前的狀態，於是 path 指向
skills/active/... 但檔案實際在 skills/cold/ 或 skills/archive/。Φ-iv
觸發遷移時看不到源目錄就 skip，導致 graph tier 與 filesystem 越離
越遠。

策略：信任 filesystem。掃 skills/{active,cold,archive}/ 找實際存在的
SKILL.md，修正 graph node 的 tier 與 path 屬性，同步 LanceDB path。

Usage (從專案根目錄):
    python scripts/repair_filesystem_graph_consistency.py            # dry-run
    python scripts/repair_filesystem_graph_consistency.py --apply    # actually fix
"""

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
os.chdir(PROJECT_ROOT)
sys.path.insert(0, str(PROJECT_ROOT))

from parse_graph_index import parse_graph_index, build_graph, graph_to_index_md


def scan_filesystem():
    """
    掃 skills/{active,cold,archive}/ 找所有 SKILL.md。
    回傳 (found, duplicates):
      found: dict[skill_name] -> (actual_tier, relative_path)
      duplicates: list of (name, path1, path2) — 同一 skill name 出現在多處

    skill_name 取 SKILL.md 父目錄的 basename：
      skills/active/seed/test-driven-development/SKILL.md → "test-driven-development"
      skills/cold/file-io/SKILL.md                       → "file-io"
    """
    found = {}
    duplicates = []
    for tier in ['active', 'cold', 'archive']:
        tier_dir = Path(f'skills/{tier}')
        if not tier_dir.exists():
            continue
        for skill_md in tier_dir.rglob('SKILL.md'):
            name = skill_md.parent.name
            rel_path = str(skill_md)
            if name in found:
                duplicates.append((name, found[name][1], rel_path))
                continue
            found[name] = (tier, rel_path)
    return found, duplicates


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true',
                        help='Apply fixes (default: dry-run)')
    args = parser.parse_args()

    print('=' * 70)
    mode = 'APPLY' if args.apply else 'DRY-RUN'
    print(f'Repair Filesystem ↔ GRAPH_INDEX consistency  [{mode}]')
    print('=' * 70)

    # Step 1: load graph
    parsed = parse_graph_index('skills/GRAPH_INDEX.md')
    G = build_graph(parsed)
    print(f'\nLoaded GRAPH_INDEX.md: {G.number_of_nodes()} nodes')

    # Step 2: scan filesystem
    fs_found, duplicates = scan_filesystem()
    print(f'Filesystem scan: {len(fs_found)} unique SKILL.md files')

    if duplicates:
        print(f'\n⚠️  Duplicate skill names (same name in multiple tiers):')
        for name, p1, p2 in duplicates:
            print(f'    {name}:')
            print(f'      {p1}')
            print(f'      {p2}')
        print('  → Resolve manually before running with --apply')

    # Step 3: diff
    fixes = []             # (name, old_tier, old_path, new_tier, new_path)
    missing_in_fs = []     # graph 有但 fs 沒有
    missing_in_graph = []  # fs 有但 graph 沒有

    for name in G.nodes:
        graph_tier = G.nodes[name].get('tier', '?')
        graph_path = G.nodes[name].get('path', '')
        if name not in fs_found:
            missing_in_fs.append((name, graph_tier, graph_path))
            continue
        actual_tier, actual_path = fs_found[name]
        if graph_tier != actual_tier or graph_path != actual_path:
            fixes.append((name, graph_tier, graph_path, actual_tier, actual_path))

    for name, (tier, path) in fs_found.items():
        if name not in G.nodes:
            missing_in_graph.append((name, tier, path))

    # Step 4: report
    print(f'\n{"=" * 70}')
    print(f'Fixes needed: {len(fixes)}')
    print(f'{"=" * 70}')
    for name, ot, op, nt, np_ in fixes:
        tier_change = f'{ot} → {nt}' if ot != nt else f'{ot}'
        print(f'  • {name}')
        print(f'      tier: {tier_change}')
        print(f'      path: {op}')
        print(f'         →  {np_}')

    print(f'\n{"=" * 70}')
    print(f'Missing in filesystem: {len(missing_in_fs)}')
    print(f'  (graph node exists but no SKILL.md found at any tier)')
    print(f'{"=" * 70}')
    for name, t, p in missing_in_fs:
        print(f'  • {name}  (graph: tier={t}, path={p})')

    print(f'\n{"=" * 70}')
    print(f'Missing in graph: {len(missing_in_graph)}')
    print(f'  (filesystem dir exists but not in GRAPH_INDEX)')
    print(f'{"=" * 70}')
    for name, t, p in missing_in_graph:
        print(f'  • {name}  (filesystem: {p})')

    if not args.apply:
        print('\n[DRY-RUN] No changes made. Re-run with --apply to fix.')
        if duplicates:
            print('  Duplicates exist — resolve manually before --apply.')
        return

    if duplicates:
        print('\n✗ Refusing to apply: duplicates exist. Resolve manually first.')
        return

    # Step 5: apply fixes
    print(f'\n{"=" * 70}')
    print('Applying fixes')
    print(f'{"=" * 70}')
    for name, ot, op, nt, np_ in fixes:
        G.nodes[name]['tier'] = nt
        G.nodes[name]['path'] = np_
        print(f'  ✓ {name}: tier {ot}→{nt}, path updated')

    graph_to_index_md(G, 'skills/GRAPH_INDEX.md')
    print(f'\n✓ GRAPH_INDEX.md written')

    # Sync LanceDB
    if fixes:
        print(f'\n{"=" * 70}')
        print('Syncing LanceDB paths')
        print(f'{"=" * 70}')
        try:
            from vector_store import VectorStore
            vs = VectorStore('config.yaml')
            updates = [{'name': n, 'new_path': np_} for n, _, _, _, np_ in fixes]
            updated = vs.update_paths(updates)
            print(f'  ✓ LanceDB paths synced: {updated}/{len(updates)}')
        except Exception as e:
            print(f'  ✗ LanceDB sync failed: {e}')
            print('  → manual sync needed via vs.update_paths()')

    print('\nDone. Recommend running tests/test_w12_lancedb_invariant.py to verify.')
    print('Note: missing_in_fs / missing_in_graph entries are NOT auto-fixed —')
    print('      review manually (could be stale graph nodes or stray dirs).')


if __name__ == '__main__':
    main()