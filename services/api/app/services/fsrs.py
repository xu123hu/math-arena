"""FSRS 记忆算法轻量实现（M2 迭代16）

参考 open-spaced-repetition/py-fsrs（FSRS-4.5/5）与 fsrs-rs：
- 记忆状态二元组：Stability（S，天）/ Difficulty（D，1~10）
- 遗忘曲线采用 FSRS-4.5 power 形式近似：R(t) = (1 + t / (9 * S)) ^ -1
- 到期判定：可提取性 R < DUE_THRESHOLD（默认 0.85）

设计策略（对齐迭代16 方案 §2）：不重写既有 1/3/7/15 间隔排期，
本模块作为"读取时计算 + error_records FSRS 缓存列"的增强层；
write-path 已在第二批接入 complete_error_review（复习完成时回填 S/R 缓存列）。
"""

from __future__ import annotations

from datetime import UTC, datetime

# FSRS 到期阈值：R 低于该值即认为"该复习了"（py-fsrs 默认 desired retention 0.9，
# 学生端错题场景取 0.85，略宽松，避免低掌握用户队列爆炸）
DUE_THRESHOLD = 0.85
# 前端热力图"衰减红"阈值
DECAY_THRESHOLD = 0.6

# 初始稳定度（天）：按复习次数递增的经验初值（对齐 py-fsrs w[0..3] 首次评级量级，
# 简化为 review_count 分段，避免引入完整 17 参数优化器）
_BASE_STABILITY = (0.4, 1.0, 3.0, 7.0, 15.0)


def estimate_stability(review_count: int, wrong_count: int = 1) -> float:
    """由复习次数/答错次数估计记忆稳定度 S（天）。

    复习越多越稳；答错次数多会打折（对齐 FSRS 中 lapse 降低 S 的行为）。
    """
    idx = min(max(review_count, 0), len(_BASE_STABILITY) - 1)
    s = _BASE_STABILITY[idx]
    # 答错惩罚：每多错一次 -15%，最低保留 40%
    penalty = max(0.4, 1.0 - 0.15 * max(0, wrong_count - 1))
    return round(s * penalty, 3)


def retrievability(elapsed_days: float, stability: float) -> float:
    """FSRS-4.5 遗忘曲线：R(t) = (1 + t / (9S)) ^ -1"""
    if stability <= 0:
        return 0.0
    return round((1.0 + max(elapsed_days, 0.0) / (9.0 * stability)) ** -1, 4)


def days_until(stability: float, target_r: float = DECAY_THRESHOLD) -> float:
    """从 R=1 起，多少天后衰减到 target_r。由 R(t) 公式反解：t = 9S * (1/R - 1)"""
    if not 0 < target_r < 1:
        return 0.0
    return round(9.0 * stability * (1.0 / target_r - 1.0), 2)


def fsrs_level(r: float) -> str:
    """可提取性 → 前端热力图 5 级（lv4 最稳 → decay 衰减红）"""
    if r >= 0.9:
        return "lv4"
    if r >= 0.8:
        return "lv3"
    if r >= 0.7:
        return "lv2"
    if r >= DECAY_THRESHOLD:
        return "lv1"
    return "decay"


def level_to_filter(level: str) -> str:
    """热力图等级 → 筛选接口三档（stable/decaying/critical）"""
    if level in ("lv4", "lv3"):
        return "stable"
    if level in ("lv2", "lv1"):
        return "decaying"
    return "critical"


def days_since(dt: datetime | None, now: datetime | None = None) -> float:
    """安全计算距今天数（容忍 naive/aware 混用与 None）"""
    if dt is None:
        return 0.0
    now = now or datetime.now(UTC)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return max(0.0, (now - dt).total_seconds() / 86400.0)
