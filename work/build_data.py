# /// script
# requires-python = ">=3.10"
# dependencies = ["pandas"]
# ///
"""
把 data/ 的三個 CSV 整理成 BI 網頁可直接載入的 docs/data.js。

用法：uv run work/build_data.py
輸出：docs/data.js，內容為 window.BI_DATA = {...}，網頁用 <script src="data.js"> 載入，
      直接雙擊 index.html 就能用（不需要伺服器，也不受 fetch 的 file:// 限制）。

為了讓檔案小，資料以「字典 + 整數索引」的欄式格式存放：
  dims.semester[i]、dims.dept[i] ... 存文字，
  enrollment.rows / leave.rows 的每一列只存索引與人數，欄位順序寫在 *.fields。
"""
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "docs" / "data.js"


def read(name):
    return pd.read_csv(DATA / name, encoding="utf-8-sig", dtype={"semester": str}).fillna("")


def main():
    enr = read("enrollment.csv")
    lev = read("leave.csv")
    mapping = read("dept_mapping.csv")

    # 系所的學院一律以對照表（114-1 組織）為準，確認來源資料一致
    dept_college = dict(zip(mapping.dept, mapping.college))
    for name, df in (("enrollment", enr), ("leave", lev)):
        missing = set(df.dept) - set(dept_college)
        assert not missing, f"{name} 有對照表裡沒有的系所：{missing}"
        bad = df[df.dept.map(dept_college) != df.college]
        assert bad.empty, f"{name} 的學院和對照表不一致：\n{bad.head()}"

    # 維度字典（依固定順序，方便網頁直接拿來排序）
    semesters = sorted(set(enr.semester) | set(lev.semester))
    colleges = list(dict.fromkeys(mapping.college))
    depts = mapping.sort_values("college", key=lambda s: s.map(colleges.index), kind="stable")
    degrees = [d for d in ["博士", "碩士", "學士"] if d in set(enr.degree) | set(lev.degree)]
    genders = ["女", "男"]
    reasons = lev[["reason", "reason_group"]].drop_duplicates()
    reasons = reasons.sort_values("reason_group", key=lambda s: s.map({"自請休學": 0, "勒令休學": 1}), kind="stable")

    dims = {
        "semester": semesters,
        "college": colleges,
        "dept": depts.dept.tolist(),
        "degree": degrees,
        "gender": genders,
        "reason": reasons.reason.tolist(),
    }
    idx = {k: {v: i for i, v in enumerate(vals)} for k, vals in dims.items()}

    def encode(df, keys, values):
        g = df.groupby(keys, as_index=False)[values].sum()
        g = g[(g[values] != 0).any(axis=1)] if len(values) > 1 else g  # 休學兩數都是 0 的列不需要
        for k in keys:
            g[k] = g[k].map(idx[k])
        g = g.sort_values(keys)
        return {"fields": keys + values, "rows": g[keys + values].astype(int).values.tolist()}

    payload = {
        "dims": dims,
        # 系所的附屬資訊，順序同 dims.dept
        "deptInfo": [
            {"college": idx["college"][r.college], "aliases": [a for a in r.aliases.split(";") if a]}
            for r in depts.itertuples()
        ],
        # 休學原因的類別，順序同 dims.reason
        "reasonGroup": reasons.reason_group.tolist(),
        "enrollment": encode(enr, ["semester", "dept", "degree", "gender"], ["count"]),
        "leave": encode(lev, ["semester", "dept", "degree", "gender", "reason"], ["new_leave", "on_leave_end"]),
        "notes": {
            "count": "在學人數（不含休學中的學生）",
            "new_leave": "學期間休學人數（這學期新辦休學）",
            "on_leave_end": "於學期底處於休學狀態之人數",
        },
    }

    # 核對
    sem_i = idx["semester"]["114-1"]
    total_114_1 = sum(r[-1] for r in payload["enrollment"]["rows"] if r[0] == sem_i)
    assert total_114_1 == 10035, f"114-1 在學人數 {total_114_1} ≠ 10035"
    assert sum(r[-1] for r in payload["enrollment"]["rows"]) == enr["count"].sum()
    assert sum(r[-2] for r in payload["leave"]["rows"]) == lev.new_leave.sum()
    assert sum(r[-1] for r in payload["leave"]["rows"]) == lev.on_leave_end.sum()

    OUT.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    OUT.write_text(f"// 由 work/build_data.py 產生，請勿手動修改\nwindow.BI_DATA = {body};\n", encoding="utf-8")

    print(f"✅ 114-1 在學人數合計 {total_114_1}（應為 10035）")
    print(f"   在學 {len(payload['enrollment']['rows'])} 列、休學 {len(payload['leave']['rows'])} 列、"
          f"{len(semesters)} 學期、{len(colleges)} 學院、{len(dims['dept'])} 系所、{len(dims['reason'])} 種休學原因")
    print(f"   已寫入 {OUT.relative_to(ROOT)}（{OUT.stat().st_size / 1024:.1f} KB）")


if __name__ == "__main__":
    main()
