import sqlite3
from collections import defaultdict

conn = sqlite3.connect("data/sqlite/six_source_replay_2026_01_01.sqlite")
conn.row_factory = sqlite3.Row

report_id = 1

cells = conn.execute("""
    SELECT id, row_no, col_no, cell_text
    FROM psp_raw_cell
    WHERE report_document_id = ? AND page_no = 6 AND table_no = 1
    ORDER BY row_no, col_no
""", (report_id,)).fetchall()

rows = defaultdict(dict)
for c in cells:
    rows[c["row_no"]][c["col_no"]] = (c["id"], c["cell_text"])

print("--- ERLDC Peak/Off-peak (MW) ---")
for row_no in sorted(rows.keys()):
    row = rows[row_no]
    parts = []
    for col_no in sorted(row.keys()):
        raw_id, text = row[col_no]
        text_clean = text.replace("\n", "\\n").strip()[:50]
        if text_clean:
            parts.append(f"c{col_no}={text_clean!r}")
    
    if 2 <= row_no <= 11:
        print(f"Row {row_no:3d}: {' | '.join(parts)}")

print("\n--- ERLDC 24-hour extrema (MW) Part 1 ---")
for row_no in sorted(rows.keys()):
    if 23 <= row_no <= 32:
        row = rows[row_no]
        parts = []
        for col_no in sorted(row.keys()):
            raw_id, text = row[col_no]
            text_clean = text.replace("\n", "\\n").strip()[:50]
            if text_clean:
                parts.append(f"c{col_no}={text_clean!r}")
        print(f"Row {row_no:3d}: {' | '.join(parts)}")

print("\n--- ERLDC 24-hour extrema (MW) Part 2 ---")
for row_no in sorted(rows.keys()):
    if 34 <= row_no <= 42:
        row = rows[row_no]
        parts = []
        for col_no in sorted(row.keys()):
            raw_id, text = row[col_no]
            text_clean = text.replace("\n", "\\n").strip()[:50]
            if text_clean:
                parts.append(f"c{col_no}={text_clean!r}")
        print(f"Row {row_no:3d}: {' | '.join(parts)}")

conn.close()
