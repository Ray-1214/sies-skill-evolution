"""
scripts/w13_50_tasks.py — W13 對照實驗 50 任務清單
=====================================================
5-cluster 分配，每 cluster 內難度均勻。同一份 50 題會跑兩次：
  baseline run:   A3-v1 prompt（mini pilot 同款，無 intra-batch suppression）
  improved run:   A3-v2 prompt（加 intra-batch + active 重複抑制）

Cluster 設計理念（基於 W12 mini pilot 共現分析）：
  C1 (12) Python implement + test  — 強化主 cluster（algorithm-impl × test-driven）
  C2 (12) 純資料處理（無 test）     — 拉開 file-io × data-analysis cluster
  C3 (10) 純 algorithm（無 file/test）— 強化 algorithm-only skill
  C4 ( 8) 系統查詢（bash 為主）      — 拉開 bash_execution + system-info cluster
  C5 ( 8) 文字處理（regex/normalize）— 拉開 text-processing 新 cluster

Case study 對齊（v4.10.1 修正後）：
  CS-1 @T12  two_sum                — reuse 案（hashmap reuse from @T4）
  CS-2 @T24  extract emails (regex) — cross-cluster compose（C2 file + C5 regex）
  CS-3 @T34  N-queens               — macro emergence（T32↔T34 swap，N-queens 移到 T34）
  CS-4 @T42  list Python processes  — sanity check / retrieval health probe
  CS-5 @T50  Vigenère cipher        — cumulative effect（T50 從 reverse words 改 Vigenère）

預期 Φ-iii 在 W13 baseline 後觸發 3-5 個 macro（mini pilot 12 題下 1 個）。

v4.10.1 changelog（vs v4.10 原版）：
  - C3 內：T32 ↔ T34 swap（Catalan number 移到 T32，N-queens 移到 T34，
                          配合 §7.6.1 摘要表 CS-3 指向 T34）
  - C5 內：T50 從 reverse word order 改為 Vigenère cipher
                          （配合 §7.6.1 摘要表 CS-5 cumulative effect 敘事）

Usage:
    from scripts.w13_50_tasks import TASKS_50, CLUSTERS, CASE_STUDIES
    runner.run_batch(TASKS_50)

    # 或檢視:
    python scripts/w13_50_tasks.py
"""

# ── Cluster 1: Python implement + test (12 題, T12 = CS-1) ──────────
C1_IMPLEMENT_AND_TEST = [
    'Implement a singly linked list with append, remove, and search methods. Test all three methods with at least 3 cases each.',
    'Implement a queue with enqueue, dequeue, and peek. Test on empty queue, single element, and multi-element scenarios.',
    'Implement a stack with push, pop, peek, and is_empty. Test all four methods.',
    'Implement a hashmap using open addressing (linear probing) with put, get, and delete. Test with 5 different keys including collisions.',
    'Implement insertion sort. Test with an empty list, an already-sorted list, a reversed list, and a random list.',
    'Implement selection sort. Test with at least 4 different inputs including edge cases.',
    'Implement merge sort recursively. Test with lists of size 0, 1, 5, and 10.',
    'Implement quicksort using the middle element as pivot. Test with various inputs including duplicates.',
    'Implement memoized Fibonacci using a dict cache. Test with n=0, 1, 10, and 30.',
    'Implement a function check_balanced_brackets supporting "(){}[]". Test with at least 5 cases including nested and unbalanced.',
    'Implement longest_common_prefix for a list of strings. Test with empty list, single string, common-prefix case, and no-common-prefix case.',
    # T12 = CS-1: two_sum reuse case (hashmap from @T4)
    'Implement two_sum: given a list and a target, return indices of two elements summing to target. Test with at least 3 inputs including no-solution case.',
]

# ── Cluster 2: 純資料處理 (12 題, T24 = CS-2) ──────────────────────
C2_DATA_PROCESSING = [
    'Write 5 rows to a CSV file at /tmp/data.csv (with a numeric second column), then read it back and count rows where the second column is greater than 50.',
    'Create a JSON file containing a list of dicts, then read it and extract all values for the key "name". Print the resulting list.',
    'Write a sample log file to /tmp with mixed lines, then count how many lines contain the word "ERROR".',
    'Create a config-style file with key=value pairs, parse it, and return the result as a Python dict. Print the dict.',
    'Generate a CSV with 10 rows of numeric data and compute the mean of column 2. Print the mean.',
    'Create a JSON list of 8 dicts each with a "category" field, group them by category, and output the count per group.',
    'Create a text file with a paragraph, then output the top 5 most frequent words (case-insensitive, ignoring punctuation).',
    'Convert a small CSV file (3 rows) to JSON format with rows as a list of dicts. Save the JSON to /tmp.',
    'Read a text file and output a histogram (dict mapping word-length to count) of word lengths.',
    'Create a CSV with date and value columns (5 rows), filter rows whose date falls in a given month, and write the filtered rows to a new CSV.',
    'Create a nested JSON object, flatten it so that {"a": {"b": 1}} becomes {"a_b": 1}, and save the flattened version to disk.',
    # T24 = CS-2: cross-cluster compose (C2 file + C5 regex)
    'Write a paragraph containing fake email addresses to a file, then extract all email addresses using regex and print them.',
]

# ── Cluster 3: 純 algorithm (10 題, T34 = CS-3) ────────────────────
# v4.10.1: T32 ↔ T34 swap (Catalan number 移到 T32，N-queens 移到 T34)
C3_PURE_ALGORITHM = [
    'Compute the factorial of 20 using iteration (no recursion). Print the result.',
    'Compute the first 30 Fibonacci numbers iteratively. Print the resulting list.',
    'Find all prime numbers up to 100 using the Sieve of Eratosthenes. Print the resulting list.',
    'Compute the LCM of 24 and 36 using the GCD-based formula. Print the result.',
    'Solve Tower of Hanoi for 4 disks. Print every move in order, in the form "Move disk N from X to Y".',
    'Compute 2^32 using fast exponentiation (binary expansion). Print the result.',
    "Generate Pascal's triangle for 8 rows. Print each row formatted on its own line.",
    # T32 (was T34): Catalan moved here
    'Compute the 10th Catalan number using the recursive definition C(n) = sum_{i=0..n-1} C(i)*C(n-1-i). Print the result.',
    'Compute the sum of digits of 50! (compute the factorial first, then sum the digits). Print both the factorial and the digit sum.',
    # T34 = CS-3 (was T32): N-queens moved here for macro emergence
    'Solve the N-queens problem for N=6 using backtracking. Print the total count of distinct solutions and display one valid board configuration as an 8-character grid (Q for queen, . for empty).',
]

# ── Cluster 4: 系統查詢 (8 題, T42 = CS-4) ─────────────────────────
C4_SYSTEM_QUERY = [
    'List all .py files anywhere under /tmp and count them.',
    'Print the current working directory and list its contents (one entry per line).',
    'Print the system hostname and the current username.',
    'Show disk usage of /tmp in human-readable format using du -sh.',
    'Find the 5 largest files under /tmp by size and list them with their sizes.',
    'Count the total number of lines across all .txt files under /tmp.',
    'Print available system memory (free) and the CPU count (nproc).',
    # T42 = CS-4: sanity check / retrieval health probe
    'List all currently running Python processes using ps and grep.',
]

# ── Cluster 5: 文字處理 (8 題, T50 = CS-5) ─────────────────────────
# v4.10.1: T50 從 reverse word order 改為 Vigenère cipher
C5_TEXT_PROCESSING = [
    'Given the string "  hello   world   how  are   you  ", replace multiple spaces with a single space and strip leading/trailing whitespace. Print the result.',
    'Convert "snake_case_example_string" to camelCase ("snakeCaseExampleString"). Print the result.',
    'Extract all numbers (both integers and floats, including negatives) from the paragraph "I have 3 apples, 2.5 kg of rice, and -7 oranges". Print as a list.',
    'Given the list ["Hello!", "WORLD.", "Python?", "java"], normalize by lowercasing, stripping punctuation, and sorting alphabetically. Print the result.',
    'Tokenize the sentence "This is a test of the simple tokenizer" and remove the stopwords {"is", "the", "a", "an", "of"}. Print the remaining tokens.',
    'Find all dates matching the YYYY-MM-DD format in the text "Meeting on 2026-04-28 and follow-up on 2026-05-15". Print as a list.',
    'Implement a Caesar cipher with shift=3. Encode the string "HELLO WORLD", then decode the encoded result back. Print both the encoded and decoded strings.',
    # T50 = CS-5: Vigenère cipher (cumulative effect, parallels T49 Caesar)
    'Implement a Vigenère cipher with a given key. Encrypt the plaintext "ATTACK AT DAWN" using key "KEY" (preserve spaces, treat letters case-insensitively but output uppercase). Then decrypt the ciphertext back using the same key. Print both encrypted and decrypted strings, and verify the decrypted result matches the original plaintext.',
]

# ── Combined ────────────────────────────────────────────────────────
TASKS_50 = (
    C1_IMPLEMENT_AND_TEST
    + C2_DATA_PROCESSING
    + C3_PURE_ALGORITHM
    + C4_SYSTEM_QUERY
    + C5_TEXT_PROCESSING
)

CLUSTERS = {
    'C1_implement_and_test': list(range(0, 12)),
    'C2_data_processing':    list(range(12, 24)),
    'C3_pure_algorithm':     list(range(24, 34)),
    'C4_system_query':       list(range(34, 42)),
    'C5_text_processing':    list(range(42, 50)),
}

# Case study tasks (1-indexed for display, 0-indexed internally)
# v4.10.1 修正後對齊實際 TASKS_50 內容
CASE_STUDIES = {
    'CS-1_reuse':       {'task_idx': 11, 'cluster': 'C1', 'name': 'two_sum',
                         'role': 'reuse case (hashmap reuse from @T4)'},
    'CS-2_compose':     {'task_idx': 23, 'cluster': 'C2', 'name': 'extract_emails_regex',
                         'role': 'cross-cluster compose (C2 file + C5 regex)'},
    'CS-3_macro':       {'task_idx': 33, 'cluster': 'C3', 'name': 'n_queens',
                         'role': 'macro emergence (first true backtracking, both runs extract new skill)'},
    'CS-4_sanity':      {'task_idx': 41, 'cluster': 'C4', 'name': 'list_python_processes',
                         'role': 'sanity check / retrieval health negative-result probe (v4.10.1 weak comparison accepted)'},
    'CS-5_late_reuse':  {'task_idx': 49, 'cluster': 'C5', 'name': 'vigenere_cipher',
                         'role': 'late reuse / cumulative effect (strongest signal for §7 case study)'},
}

assert len(TASKS_50) == 50, f'expected 50 tasks, got {len(TASKS_50)}'

# Assertions to catch task content drift (sanity check on import)
assert 'two_sum' in TASKS_50[11], f'T12 should be two_sum, got: {TASKS_50[11][:60]!r}'
assert 'email' in TASKS_50[23].lower(), f'T24 should be email regex, got: {TASKS_50[23][:60]!r}'
assert 'Catalan' in TASKS_50[31], f'T32 should be Catalan (after swap), got: {TASKS_50[31][:60]!r}'
assert 'N-queens' in TASKS_50[33] or 'queens' in TASKS_50[33].lower(), \
    f'T34 should be N-queens (after swap), got: {TASKS_50[33][:60]!r}'
assert 'Python processes' in TASKS_50[41], f'T42 should be ps grep python, got: {TASKS_50[41][:60]!r}'
assert 'Vigenère' in TASKS_50[49] or 'Vigenere' in TASKS_50[49], \
    f'T50 should be Vigenère cipher, got: {TASKS_50[49][:60]!r}'


if __name__ == '__main__':
    for cname, idxs in CLUSTERS.items():
        print(f'\n=== {cname}  (n={len(idxs)}) ===')
        for i in idxs:
            cs_marker = ''
            for cs_id, cs_meta in CASE_STUDIES.items():
                if cs_meta['task_idx'] == i:
                    cs_marker = f'  ★ {cs_id}'
                    break
            preview = TASKS_50[i][:90] + ('...' if len(TASKS_50[i]) > 90 else '')
            print(f'  T{i+1:02d}{cs_marker}')
            print(f'        {preview}')

    print(f'\n{"=" * 70}')
    print(f'Total: {len(TASKS_50)} tasks  ({len(CASE_STUDIES)} case studies)')
    print(f'{"=" * 70}')
    for cs_id, cs_meta in CASE_STUDIES.items():
        i = cs_meta['task_idx']
        print(f'  ★ T{i+1:02d}  {cs_id}  ({cs_meta["role"]})')