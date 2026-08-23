# -*- coding: utf-8 -*-
"""迭代15 全链路实测回归脚本（固化 B1-B4 验收场景）。

用法：先启动后端（:8000），再运行：
    python scripts/e2e_iter15_regression.py

覆盖场景：
  S1 学习事件总线：答错 → 错题+学情+打卡；同日同题去重
  S2 卡片摘要入上下文：自由对话引用"刚才的题"零幻觉
  S3 讲解按钮确定性路由：pinned socratic 必中
  S4 思考流封装：socratic 全程 0 个 thinking 事件
"""
import json
import sys
import uuid
from collections import Counter

import requests

BASE = "http://localhost:8000/api"
PHONE = "13800138000"

PASS, FAIL = "OK ", "BAD"
results = []


def check(name, ok, detail=""):
    results.append((name, ok, detail))
    print(f"[{PASS if ok else FAIL}] {name} {detail}")


def login():
    requests.post(f"{BASE}/auth/sms-code", json={"phone": PHONE}, timeout=15)
    return requests.post(
        f"{BASE}/auth/login", json={"phone": PHONE, "code": "123456"}, timeout=15
    ).json()["data"]["token"]


def new_conv(tok):
    d = requests.post(
        f"{BASE}/agent/conversations", json={"workspace": "student"},
        headers={"Authorization": f"Bearer {tok}"}, timeout=15,
    ).json()["data"]
    return d.get("id") or d.get("conversation", {}).get("id")


def chat(tok, cid, message, skills=None):
    ctx = {"client_msg_id": uuid.uuid4().hex, "workspace": "student"}
    if skills:
        ctx["skills"] = skills
    body = {"conversation_id": cid, "message": message, "context": ctx}
    events = []
    with requests.post(
        f"{BASE}/agent/chat", json=body,
        headers={"Authorization": f"Bearer {tok}"}, stream=True, timeout=300,
    ) as resp:
        cur = None
        for line in resp.iter_lines(decode_unicode=True):
            if not line:
                continue
            if line.startswith("event:"):
                cur = line[7:].strip()
            elif line.startswith("data:"):
                p = line[5:].strip()
                if p == "[DONE]":
                    break
                try:
                    events.append((cur, json.loads(p)))
                except json.JSONDecodeError:
                    pass
    return events


def main():
    tok = login()
    h = {"Authorization": f"Bearer {tok}"}

    # ---- S1 学习事件总线 ----
    before = requests.get(f"{BASE}/student/error-records", headers=h, timeout=20).json()["data"]["total"]
    q = f"E2E回归题{uuid.uuid4().hex[:6]}：已知 f(x)=x^2，求 f'(2)"
    payload = {
        "kind": "quiz_judge", "question_text": q, "answer": "4", "chosen": "3",
        "correct": False, "kp_code": "derivative", "kp_name": "导数", "source": "chat_quiz",
    }
    r1 = requests.post(f"{BASE}/student/learning-events", json=payload, headers=h, timeout=20).json()["data"]
    r2 = requests.post(f"{BASE}/student/learning-events", json=payload, headers=h, timeout=20).json()["data"]
    after = requests.get(f"{BASE}/student/error-records", headers=h, timeout=20).json()["data"]["total"]
    check("S1a 答错收录", r1.get("error_recorded") is True and after == before + 1)
    check("S1b 同日同题去重", r2.get("error_recorded") is False)
    check("S1c kp编码解析+学情", r1.get("mastery_updated") is True)

    # ---- S2 卡片摘要入上下文 ----
    cid = new_conv(tok)
    quiz_q = ""
    quiz_opts = []
    for _ in range(2):  # 出题偶发过不了质量闸而诚实降级，重试一次
        ev = chat(tok, cid, "出一道函数简单题")
        for et, d in ev:
            if et == "card" and d.get("type") == "quiz_set":
                items = d.get("items") or []
                if items:
                    quiz_q = items[0].get("question_text", "")
                    quiz_opts = items[0].get("options") or []
        if quiz_q:
            break
    ev2 = chat(tok, cid, "刚才那道题的正确答案为什么对？用一句话告诉我关键步骤")
    text2 = "".join(d.get("text", "") for et, d in ev2 if et == "token")
    # 零幻觉判据：题干的显著片段（中文连续段 ≥4 字，或数学符号段 ≥3 字符如 cos/sin/log）
    # 出现在回复中即判定模型看到了真实题卡（回复不必逐字复述题干）
    import re as _re

    def _cjk_runs(s):
        return [r for r in _re.findall(r"[一-鿿]+", s or "") if len(r) >= 4]

    def _math_runs(s):
        return [
            r for r in _re.findall(r"[A-Za-z]{3,}(?:\s*x)?", s or "")
            if r.lower() not in ("the", "and", "text", "quad", "textbf", "frac")
        ]

    runs = _cjk_runs(quiz_q)
    mruns = _math_runs(quiz_q)
    reply_cjk = "".join(_re.findall(r"[一-鿿]+", text2))
    hit = bool(quiz_q) and (
        any(r in reply_cjk for r in runs) or any(r in text2 for r in mruns)
    )
    check("S2 刚才的题零幻觉", hit, f"(题干片段: {(runs + mruns)[:3]})")

    # ---- S3 讲解按钮确定性路由 ----
    ev3 = chat(
        tok, cid,
        "请讲解这道题并帮我举一反三：\n已知函数 f(x)=x^2，求导数。\n"
        "（这是一道「导数」相关题，我刚刚选了 C（错误），请先用苏格拉底方式引导我理解，再出 2-3 道变式确认我真正掌握）",
        skills=["socratic_solver"],
    )
    skill3 = ev3[0][1].get("skill") if ev3 else None
    check("S3 讲解pinned确定性路由", skill3 == "socratic_solver", f"(skill={skill3})")

    # ---- S4 思考流封装 ----
    cid4 = new_conv(tok)
    ev4 = chat(tok, cid4, "这道题我不会：求函数 y=x^2+1 的最小值")
    types = Counter(et for et, _ in ev4)
    check("S4 思考流不外发", types.get("thinking", 0) == 0, f"(thinking={types.get('thinking', 0)})")

    failed = [r for r in results if not r[1]]
    print(f"===== {len(results) - len(failed)}/{len(results)} passed =====")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
