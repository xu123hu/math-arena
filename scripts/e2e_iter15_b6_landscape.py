# -*- coding: utf-8 -*-
"""迭代15 B6 图景对齐实测脚本（学情行动清单 / 侧栏收敛 / 复习对话化）。

用法：先启动后端（:8000），再运行：
    python scripts/e2e_iter15_b6_landscape.py

覆盖场景：
  T1 今日行动清单：/student/mastery/today-actions 契约（type/title/reason/duration_min）
  T2 行动去重与上限：行动卡 ≤3 张，type 不重复
  T3 复习计划出口：/student/error-records/review-plan 契约（due_today/due_items）
  T4 复习推进幂等：到期记录 forgotten → next_review_at 重置回 1 天档（排期不丢失）
"""
import sys
from datetime import UTC, datetime

import requests

BASE = "http://localhost:8000/api"
PHONE = "13800138000"

results = []


def check(name, ok, detail=""):
    results.append((name, ok))
    print(f"[{'OK ' if ok else 'BAD'}] {name} {detail}")


def login():
    requests.post(f"{BASE}/auth/sms-code", json={"phone": PHONE}, timeout=15)
    return requests.post(
        f"{BASE}/auth/login", json={"phone": PHONE, "code": "123456"}, timeout=15
    ).json()["data"]["token"]


def get(tok, path):
    r = requests.get(
        f"{BASE}{path}", headers={"Authorization": f"Bearer {tok}"}, timeout=30
    )
    r.raise_for_status()
    return r.json()["data"]


def main():
    tok = login()

    # T1 今日行动清单契约
    data = get(tok, "/student/mastery/today-actions")
    actions = data.get("actions") or []
    valid_types = {"review", "weak", "daily", "challenge"}
    shape_ok = all(
        a.get("type") in valid_types
        and a.get("title")
        and a.get("reason")
        and isinstance(a.get("duration_min"), int)
        for a in actions
    )
    check("T1 行动清单契约", shape_ok, f"actions={len(actions)} types={[a['type'] for a in actions]}")

    # T2 上限 3 张 + 类型不重复 + 防伪勤奋 notice 结构（如有）
    types = [a["type"] for a in actions]
    check("T2 ≤3张且不重复", len(actions) <= 3 and len(types) == len(set(types)))
    notice = data.get("notice")
    if notice is not None:
        check("T2b 防伪勤奋notice", notice.get("type") == "move_on" and bool(notice.get("text")))

    # T3 复习计划契约
    plan = get(tok, "/student/error-records/review-plan")
    check(
        "T3 复习计划契约",
        isinstance(plan.get("due_today"), int) and isinstance(plan.get("due_items"), list),
        f"due_today={plan.get('due_today')}",
    )
    # 行动卡 review 与复习计划口径一致
    review_action = next((a for a in actions if a["type"] == "review"), None)
    if plan.get("due_today", 0) > 0:
        check("T3b 到期>0必有review卡", review_action is not None)
        if review_action:
            item = (review_action.get("items") or [{}])[0]
            check(
                "T3c review卡携带原题指针",
                bool(item.get("record_id")) and bool(item.get("question_text")),
            )
    else:
        check("T3b 无到期则无review卡", review_action is None)

    # T4 复习推进：到期记录 forgotten → 重置回 1 天档（不丢排期）
    if plan.get("due_items"):
        rid = plan["due_items"][0]["record_id"]
        r = requests.post(
            f"{BASE}/student/error-records/{rid}/review",
            json={"result": "forgotten"},
            headers={"Authorization": f"Bearer {tok}"},
            timeout=30,
        )
        r.raise_for_status()
        nra = r.json()["data"].get("next_review_at")
        ok = nra is not None
        if ok:
            delta = datetime.fromisoformat(nra) - datetime.now(UTC)
            ok = 0.5 <= delta.total_seconds() / 86400 <= 1.5
        check("T4 forgotten重置回1天档", ok, f"next_review_at={nra}")
    else:
        check("T4 forgotten重置回1天档", True, "无到期记录，跳过")

    failed = [n for n, ok in results if not ok]
    print(f"===== {len(results) - len(failed)}/{len(results)} passed =====")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
