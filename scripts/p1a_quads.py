"""
p1a_quads.py — P5-0 那 3 題 pipeline 的四元組版本
=================================================
驗收條件 #3：格式表達不了「已知能跑的題」就是格式錯。

D1/D2/D3 在 P5-0 是 3/3 通過（`data/p5_0_probe/20260906T180436.json`），
verifier 當時是手寫的 inline Python。這裡把它們改寫成宣告式四元組：

    task_description  給 agent 看的題目
    input_files       harness 先放進 workdir 的已知輸入
    reference_solution 由 harness 在沙箱裡**執行**，用產物推導 expected
                      （不是叫 LLM 在腦中算 —— 算錯會產生 false negative，
                       那是跟捏造相反方向的污染）
    expected          check spec 樣板；標 from_reference 的欄位由參考解填實
    oracle            生成器的**意圖**。實際強度由 verify_runner.compute_status
                      從跑過的 kind 算出，不採信這個欄位。

⚠️ D1 順帶補上一個手寫 verifier 漏掉的檢查：題目要求「same columns」，
   舊的 inline verify 只驗了列數與 units 值，沒驗欄位 —— 一個只輸出單欄的
   clean.csv 當時會通過。宣告式的 `header` 把這個缺口補上。
"""

SALES_CSV = (
    "region,product,units,price\n"
    "North,widget,10,2.5\n"
    "North,gadget,,4.0\n"
    "South,widget,20,2.5\n"
    "South,gadget,5,4.0\n"
    "East,widget,,2.5\n"
    "East,gadget,8,4.0\n"
)

RECORDS_JSON = (
    '[{"id": 1, "name": "alice", "age": 30}, '
    '{"id": 2, "name": "bob"}, '
    '{"id": "x", "name": "carol", "age": 25}, '
    '{"id": 4, "name": "dave", "age": -1}]'
)

QUADS = [
    {
        "task_id": "D1", "domain": "pipeline", "cluster": "C2", "level": 1,
        "task_description": (
            "Read the CSV file at sales.csv in the current directory. The 'units' column "
            "has missing values. Fill each missing 'units' value with the mean of the "
            "non-missing 'units' values, rounded to 2 decimal places. Write the cleaned "
            "data to clean.csv with the same columns and the same row order. Then print "
            "exactly one line: ROWS=<number of data rows> FILLED=<number filled>."
        ),
        "input_files": {"sales.csv": SALES_CSV},
        "reference_solution": (
            "import csv\n"
            "rows = list(csv.DictReader(open('sales.csv')))\n"
            "vals = [float(r['units']) for r in rows if r['units'].strip()]\n"
            "mean = round(sum(vals) / len(vals), 2)\n"
            "filled = 0\n"
            "for r in rows:\n"
            "    if not r['units'].strip():\n"
            "        r['units'] = mean\n"
            "        filled += 1\n"
            "with open('clean.csv', 'w', newline='') as f:\n"
            "    w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))\n"
            "    w.writeheader(); w.writerows(rows)\n"
            "print(f'ROWS={len(rows)} FILLED={filled}')\n"
        ),
        "expected": {
            "clean.csv": {"kind": "csv_column", "column": "units",
                          "tol": 0.011, "from_reference": True},
        },
        "oracle": "verified_independent",
    },
    {
        "task_id": "D2", "domain": "pipeline", "cluster": "C1", "level": 2,
        "task_description": (
            "Read records.json in the current directory (a JSON list of objects). Write a "
            "schema validator that checks each record satisfies: 'id' is an int, 'name' is "
            "a non-empty string, 'age' is an int >= 0 and is present. Write the validation "
            "result to result.json as a JSON list of booleans, one per record, in the same "
            "order. Then print exactly one line: VALID=<number of valid records>."
        ),
        "input_files": {"records.json": RECORDS_JSON},
        "reference_solution": (
            "import json\n"
            "recs = json.load(open('records.json'))\n"
            "def ok(r):\n"
            "    return (isinstance(r.get('id'), int) and not isinstance(r.get('id'), bool)\n"
            "            and isinstance(r.get('name'), str) and r.get('name') != ''\n"
            "            and isinstance(r.get('age'), int) and not isinstance(r.get('age'), bool)\n"
            "            and r.get('age') >= 0)\n"
            "res = [ok(r) for r in recs]\n"
            "json.dump(res, open('result.json', 'w'))\n"
            "print(f'VALID={sum(res)}')\n"
        ),
        "expected": {
            "result.json": {"kind": "json_equals", "from_reference": True},
        },
        "oracle": "verified_independent",
    },
    {
        "task_id": "D3", "domain": "pipeline", "cluster": "C3", "level": 2,
        "task_description": (
            "Read sales.csv in the current directory. Ignore rows where 'units' is empty. "
            "Compute total revenue (units * price) grouped by 'region'. Write report.json "
            "as a JSON object mapping region name to total revenue (a number). Then print "
            "exactly one line: REGIONS=<number of regions in your output>."
        ),
        "input_files": {"sales.csv": SALES_CSV},
        "reference_solution": (
            "import csv, json, collections\n"
            "tot = collections.defaultdict(float)\n"
            "for r in csv.DictReader(open('sales.csv')):\n"
            "    if not r['units'].strip():\n"
            "        continue\n"
            "    tot[r['region']] += float(r['units']) * float(r['price'])\n"
            "json.dump(dict(tot), open('report.json', 'w'))\n"
            "print(f'REGIONS={len(tot)}')\n"
        ),
        "expected": {
            "report.json": {"kind": "json_equals", "tol": 0.01, "from_reference": True},
        },
        "oracle": "verified_independent",
    },
]
