# /// script
# requires-python = ">=3.10"
# dependencies = ["xlrd", "pandas"]
# ///
"""
把東華大學 114-1 在學人數統計表（.xls）轉成整齊的 CSV。

用法：uv run work/etl_enrollment.py
輸出：work/enrollment_114-1.csv（UTF-8 with BOM）
欄位：college, dept_raw, program_raw, gender, count
"""
import re
import sys
from pathlib import Path

import pandas as pd
import xlrd

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / "東華大學統計資料" / "在學人數統計表"
OUT = ROOT / "work" / "enrollment_114-1.csv"

COL_PROGRAM, COL_COLLEGE, COL_DEPT, COL_GROUP = 0, 1, 2, 3
COL_F, COL_M = 5, 6  # 「總計」底下的 女、男

# 區段列（例如「碩專班 合計3」）→ 該區段的學制
SECTION_PROGRAM = {"博士班": "博士班", "碩士班": "碩士班", "碩專班": "碩士在職專班", "學士班": "學士班"}


def text(sheet, r, c):
    v = sheet.cell_value(r, c)
    return str(v).strip() if v != "" else ""


def num(sheet, r, c):
    v = sheet.cell_value(r, c)
    return int(v) if v != "" else 0


def merged_lookup(sheet):
    """(row, col) → 合併範圍左上角的 (row, col)，只記錄非左上角的格子。"""
    lookup = {}
    for r0, r1, c0, c1 in sheet.merged_cells:
        for r in range(r0, r1):
            for c in range(c0, c1):
                if (r, c) != (r0, c0):
                    lookup[(r, c)] = (r0, c0)
    return lookup


def common_prefix(a, b):
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def strip_note(s):
    return re.sub(r"\s*[（(].*?[)）]", "", s).strip()


def main():
    src = next(SRC_DIR.glob("114-1*.xls"))
    sheet = xlrd.open_workbook(src, formatting_info=True).sheet_by_index(0)
    merged = merged_lookup(sheet)

    def cell(r, c):
        """讀格子；若在合併範圍內，取合併範圍第一格的值。"""
        return text(sheet, *merged.get((r, c), (r, c)))

    # 1. 找出資料列，並標記所屬學制
    rows, program = [], None
    for r in range(sheet.nrows):
        head = text(sheet, r, COL_PROGRAM)
        if head.startswith("備註"):
            break
        if "合計" in head or "總計" in head:
            m = re.match(r"(博士班|碩士班|碩專班|學士班)\s*合計", head)
            program = SECTION_PROGRAM[m.group(1)] if m else None
            continue
        if program and text(sheet, r, COL_GROUP):
            rows.append((r, program))

    # 2. 補上學院、系所（合併儲存格只寫在第一格）
    records, prev = [], {}
    for i, (r, program) in enumerate(rows):
        college = cell(r, COL_COLLEGE) or prev.get("college")
        dept = cell(r, COL_DEPT)
        if not dept:
            # 空白又不在任何合併範圍內的「孤兒格」：看分組名稱和上一列、下一列哪個比較像
            group = text(sheet, r, COL_GROUP)
            nxt = rows[i + 1][0] if i + 1 < len(rows) else None
            same_section = nxt is not None and rows[i + 1][1] == program
            nxt_dept = cell(nxt, COL_DEPT) if same_section else ""
            if nxt_dept and common_prefix(group, text(sheet, nxt, COL_GROUP)) > common_prefix(group, prev.get("group", "")):
                dept = nxt_dept
            else:
                dept = prev.get("dept")
            print(f"⚠️ 第 {r + 1} 列系所空白且未合併（分組：{group}），判定為「{dept}」", file=sys.stderr)
        if not college or not dept:
            raise ValueError(f"第 {r + 1} 列找不到學院或系所")
        prev = {"college": college, "dept": dept, "group": text(sheet, r, COL_GROUP)}
        for gender, col in (("女", COL_F), ("男", COL_M)):
            records.append(dict(college=strip_note(college), dept_raw=dept, program_raw=program,
                                gender=gender, count=num(sheet, r, col)))

    # 3. 同一系所、同一學制的多個分組加總成一列
    keys = ["college", "dept_raw", "program_raw", "gender"]
    df = pd.DataFrame(records).groupby(keys, sort=False, as_index=False)["count"].sum()

    # 4. 檢查：和報表上的總計列一致
    total_row = next(r for r in range(sheet.nrows) if text(sheet, r, COL_PROGRAM).startswith("總計"))
    expected = num(sheet, total_row, COL_F) + num(sheet, total_row, COL_M)
    assert df["count"].sum() == expected, f"加總 {df['count'].sum()} ≠ 報表總計 {expected}"

    OUT.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(OUT, index=False, encoding="utf-8-sig")
    print(f"✅ {len(df)} 列，總人數 {df['count'].sum()}，已寫入 {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
