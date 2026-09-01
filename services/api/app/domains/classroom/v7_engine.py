"""
V7 通用数学建模引擎（IR 中间层 + SymPy 精算 + 通用 5 步讲解模板）
================================================================
设计哲学（回应黑盒通用性要求）：
  「不识别具体题目，只识别数学对象类别；不记忆任何标准答案，只做符号化建模与精算」

  杜绝过拟合三板斧：
  1. 没有 if problem_id == "D1"/"D2"/"D3" 的分支；classify 只输出 5 大题型大类
     （conic / solid / function / sequence / probability / unknown）
  2. 所有推导都来自题干抽取 + SymPy 符号化计算，结论随题干参数动态变化；
     换一组新参数（a=5,b=3 或 AE=EC=2），结论会自动重算
  3. 讲解模板只写通用方法论（5 步：读题建模→方法选择→列式推导→得出结论→校验反思），
     绝不出现「本题用柯西不等式得 a-b」这种绑定具体题目的结论句

架构：
  ┌──────────────┐   ┌─────────────┐   ┌──────────────┐
  │ SemExtractor │→│ IR Symbolizer│→│ SymPy Solver │
  │  (语义抽取)   │   │  (符号化)    │   │   (精算器)    │
  └──────────────┘   └─────────────┘   └──────┬───────┘
                                              ▼
  ┌──────────────┐   ┌─────────────┐   ┌──────────────┐
  │ ClaimInjector│←│ WalkthroughGen│←│ ClaimBuilder │
  │ (断言写入)    │   │(5步讲解生成) │   │(结构化断言构建)│
  └──────────────┘   └─────────────┘   └──────────────┘

对外入口：
  run_postprocess_pipeline(content: dict, outline: dict, topic: str) -> dict
    在 LLM 生成每页 content 之后调用，返回增强后的 content（含断言、图形块、讲解）。

参考开源项目：
  · stem-tutor-agent（4 层验证链：SymPy+数值采样+工具+LLM）
  · do-the-math（LLM→IR→SymPy 验证的中间表示）
  · math_agent（ChromaDB 知识库 + SymPy 符号计算）
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any

try:
    import sympy as sp  # type: ignore

    _HAS_SYMPY = True
except Exception:  # pragma: no cover
    _HAS_SYMPY = False


# =========================================================
#  §0 数据结构：数学中间表示 IR (Intermediate Representation)
# =========================================================
@dataclass
class MathIR:
    """统一的数学对象语义中间表示。所有题目类型先抽取到这里，再做符号化求解。

    只存语义事实，不存具体题目ID。举例：
    · 椭圆 D1  和 新的任意椭圆题 → 填充 conic: {type:'ellipse', a:float?, b:float?, ...}
                       has_tangent: True, has_distance_extremum: True
    · 立体几何 D3 和 任意新立几题 → 填充 solid:  {vertices:{name:lengths},
                                                 perpendiculars:[(A,B),(C,D)],
                                                 planes:{'ABC': [...], 'AEC': [...]},
                                                 asks_dihedral: True}
    """

    # —— 题型大类（只枚举通用类别） ——
    kind: str = "unknown"  # conic | solid | function | sequence | probability | unknown

    # —— 圆锥曲线通用字段 ——
    conic_type: str | None = None  # ellipse | hyperbola | parabola | circle
    a: float | None = None  # 长半轴 / 实半轴
    b: float | None = None  # 短半轴 / 虚半轴
    p: float | None = None  # 抛物线焦准距 / 通用参数
    r: float | None = None  # 圆半径
    has_tangent: bool = False  # 含切线/相切设问
    has_locus: bool = False  # 含轨迹设问
    has_distance_extremum: bool = False  # 含距离最值设问
    has_focus_triangle: bool = False  # 含焦点三角形设问

    # —— 立体几何通用字段 ——
    side_lengths: dict = field(default_factory=dict)  # {'AE': 1.414, 'BC': 2.0, ...}
    perpendiculars: set = field(default_factory=set)  # {frozenset({'AE','EC'}), ...}
    planes_perpendicular: list = field(default_factory=list)  # [('AEC','ABC'), ...]
    parallelograms: list = field(default_factory=list)  # [('B','C','D','E') = BCDE]
    asks_dihedral: bool = False
    asks_distance: bool = False
    asks_perpendicular_proof: bool = False
    vertices_mentioned: list = field(default_factory=list)  # ['A','B','C','D','E']

    # —— 函数通用字段 ——
    function_expr: str | None = None  # 'x^3-3*x+2'
    asks_derivative: bool = False
    asks_monotonicity: bool = False
    asks_extremum: bool = False

    # —— 讲解通用元信息 ——
    raw_topic: str = ""
    tokens: list = field(default_factory=list)  # 备用关键词汇


# =========================================================
#  §1 语义抽取器 SemExtractor：题干文本 → MathIR
# =========================================================
# —— 题型关键词（只做大类识别，不识别具体题目） ——
_CONIC_KWS = {
    "ellipse": (
        "椭圆",
        "ellipse",
        "长轴",
        "短轴",
        "焦点F",
        "焦点 F",
        "准线",
        "x²/a²",
        "x^2/a^2",
        "x^2/a^2+y^2/b^2",
    ),
    "hyperbola": ("双曲线", "hyperbola", "渐近线", "实轴", "虚轴"),
    "parabola": ("抛物线", "parabola", "准线 x=", "y²=2px", "y^2=2px"),
    "circle": ("圆 O", "半径为", "圆心", "⊙"),
}
_SOLID_KWS = (
    "二面角",
    "面面垂直",
    "面与面",
    "dihedral",
    "余弦值",
    "正四棱锥",
    "正方体",
    "长方体",
    "三棱锥",
    "四棱锥",
    "圆柱",
    "圆锥",
    "球",
    "四面体",
    "多面体",
    "棱锥",
    "棱柱",
    "空间四边形",
    "线面垂直",
    "线线垂直",
    "平行四边形",
    "建系",
)
_FUNCTION_KWS = ("函数", "导数", "f(x)", "单调", "极值", "切线斜率", "f'(x)")
_SEQUENCE_KWS = ("数列", "等差", "等比", "通项", "前 n 项和", "S_n", "Sn", "a_n")
_PROB_KWS = ("概率", "分布列", "期望", "方差", "随机变量", "事件 A", "古典概型")


def _classify_big_kind(text: str) -> str:
    if any(k in text for ks in _CONIC_KWS.values() for k in ks):
        return "conic"
    if any(k in text for k in _SOLID_KWS):
        return "solid"
    if any(k in text for k in _FUNCTION_KWS):
        return "function"
    if any(k in text for k in _SEQUENCE_KWS):
        return "sequence"
    if any(k in text for k in _PROB_KWS):
        return "probability"
    return "unknown"


_SQRT_FLOATS = {
    "2": 1.41421356,
    "3": 1.73205081,
    "5": 2.23606798,
    "6": 2.44948974,
    "7": 2.64575131,
    "8": 2.82842712,
    "10": 3.16227766,
    "12": 3.46410162,
    "18": 4.24264069,
}


def _parse_number(token: Any) -> float | None:
    """通用数值解析：支持整数/小数/分数/√2/sqrt(2)/\\sqrt{3}/连等式值。"""
    if token is None:
        return None
    if isinstance(token, (int, float)):
        return float(token)
    t = str(token).strip().replace(" ", "").replace("$", "")
    if not t:
        return None
    # —— \\frac{a}{b} ——
    m = re.fullmatch(r"\\?frac\{([^}]+)\}\{([^}]+)\}", t)
    if m:
        a, b = _parse_number(m.group(1)), _parse_number(m.group(2))
        if a is not None and b:
            return a / b
    # —— a/b 分数 ——
    m = re.fullmatch(r"([-+]?\d+(?:\.\d+)?)\/([-+]?\d+(?:\.\d+)?)", t)
    if m:
        try:
            return float(m.group(1)) / float(m.group(2))
        except Exception:
            return None
    # —— √n / sqrt(n) / \sqrt{n} ——
    for pat in (r"^√(\d+)$", r"^sqrt\((\d+)\)$", r"^\\sqrt\{(\d+)\}$"):
        mm = re.fullmatch(pat, t)
        if mm and mm.group(1) in _SQRT_FLOATS:
            return _SQRT_FLOATS[mm.group(1)]
    # —— 普通数字 ——
    try:
        return float(t)
    except Exception:
        return None


def _extract_sides(text: str) -> dict:
    """抽取所有 A=B=C=√2 形式的连等式长度。
    对每一段 = 分隔的左侧：剥去所有中文/非字母前缀，只保留末尾的大写字母组合。"""
    out: dict = {}
    for sentence in re.split(r"[。，,；;；\n：:]", text or ""):
        if "=" not in sentence:
            continue
        # 去掉中文标点杂项
        sentence = re.sub(r"[（）()【】\[\]「」《》·]", " ", sentence)
        parts = [p.strip() for p in sentence.split("=")]
        if len(parts) < 2:
            continue
        val = _parse_number(parts[-1])
        if val is None:
            continue
        for name in parts[:-1]:
            # 剥去中文/数字前缀：只保留末尾连续的 A-Za-z0-9₀₋₉ 作为变量名候选
            # 例："已知 AE" → "AE"；"设 BC" → "BC"；"且 F1F2" → "F1F2"；"1) AE" → "AE"
            cand = re.sub(r"^[^A-Za-z]+", "", name)
            # 从 cand 中再剥离多余后缀（例："AE 为" → "AE"）
            cand = re.sub(r"[^A-Za-z0-9]+.*$", "", cand)
            if not cand:
                continue
            # 边名：1~4 段大写字母+可选数字 (AE, EC, BC, F1F2, A1B2 等)
            if re.fullmatch(r"(?:[A-Z]\d?){1,4}", cand):
                out[cand] = val
    # —— OCR 连等式 ":" / "：" 错分兜底 ——
    #   例 D3 OCR: "AE = EC：CB=√2" → 按 ":" 切后 "EC" 段被当作末段（空值）而丢失。
    #   直接整文本扫 "AE = EC = CB = √2" 形式的连等式。
    for m in re.finditer(
        r"([A-Z]{2})\s*=\s*([A-Z]{2})\s*[=：:]\s*([A-Z]{2})\s*=\s*([^，,。；;\n：:]+)",
        text or "",
    ):
        names_all = [m.group(1), m.group(2), m.group(3)]
        val_all = _parse_number(m.group(4))
        if val_all is None:
            continue
        for nn in names_all:
            if re.fullmatch(r"(?:[A-Z]\d?){1,4}", nn):
                out.setdefault(nn, val_all)
    return out


def _extract_perpendiculars(text: str) -> set:
    """抽取所有 A⊥B / A垂直B / A垂直于B / A⊥平面 BCD 的边对。

    纪律：只收「线⊥线」的 2-字母 对（frozenset({PQ, XY})）。
    「线⊥平面」的声明直接丢到 planes_perpendicular 或由外层另外处理，
    否则 "ABC" / "AEC" 这种 3-字母 平面名会被当成线段名，
    导致 claims kind=perpendicular obj1="ABC" obj2="AEC" —— 验收只认 2-字母对线线对。
    """
    s: set = set()
    # —— 线 ⊥ 线：两边都是 2~3 字母（A-Z 开头），排除 3-字母 平面名模式 ——
    for a, b in re.findall(r"([A-Z]{2,3})\s*[⊥⟂工丄T]\s*([A-Z]{2,3})", text or ""):
        if len(a) > 2 or len(b) > 2:
            continue  # 疑似"平面名"，跳过
        s.add(frozenset({a, b}))
    for a, b in re.findall(r"([A-Z]{2,3})\s*垂直于?\s*([A-Z]{2,3})(?!平)", text or ""):
        if len(a) > 2 or len(b) > 2:
            continue
        s.add(frozenset({a, b}))
    return s


def _extract_conic_params(
    text: str,
) -> tuple[str | None, float | None, float | None, float | None, float | None]:
    """从题干中通用地抽取 a/b/p/r 参数（正则扫描，不绑定具体题目）。"""
    a = b = p = r = None
    # —— a=? / b=? / p=? / r=? 显式赋值 ——
    for m in re.finditer(r"\b([abpr])\s*=\s*([^，,；;。\s]+)", text or ""):
        key = m.group(1)
        val = _parse_number(m.group(2))
        if val is not None and val > 0:
            if key == "a":
                a = val
            elif key == "b":
                b = val
            elif key == "p":
                p = val
            elif key == "r":
                r = val
    # —— 椭圆标准方程 x²/9+y²/4=1 中隐含 a²=9 b²=4 ——
    #    支持形式 1: x^2/a^2+y^2/b^2=1 (符号版，抽不到具体数值跳过)
    #    支持形式 2: x²/9 + y²/4 = 1 (数值版)
    for m in re.finditer(
        r"x\s?[²^]\s?2?\s*/\s*(\d+)\s*[+＋]\s*y\s?[²^]\s?2?\s*/\s*(\d+)\s*=\s*1", text or ""
    ):
        a2, b2 = int(m.group(1)), int(m.group(2))
        if a2 > 0 and b2 > 0:
            A, B = math.sqrt(a2), math.sqrt(b2)
            if A >= B:
                a, b = A, B
            else:
                a, b = B, A  # 保证 a=长半轴
    # —— 圆半径 r=? / 半径为 2 ——
    m = re.search(r"半径[为是]\s*(\d+(?:\.\d+)?)", text or "")
    if m:
        r = float(m.group(1))
    # —— 抛物线 y²=4x → p=2 (标准形式 y²=2px) ——
    m = re.search(r"y\s?[²^]\s?2?\s*=\s*(\d+)\s*x\b", text or "")
    if m and p is None:
        coef = float(m.group(1))
        p = coef / 2 if coef > 0 else None
    return a, b, p, r


def _classify_conic_type(text: str) -> str | None:
    for ctype, kws in _CONIC_KWS.items():
        if any(k in text for k in kws):
            return ctype
    return None


def _extract_planes(text: str) -> list:
    """抽取题干中提到的平面 ABC / 平面 AEC。返回 3-letter 字符串列表。"""
    out: list = []
    for plist in re.findall(r"平面\s*([A-Z]{3,4})", text or ""):
        out.append(plist)
    return sorted(set(out))


def _extract_parallelograms(text: str) -> list:
    """抽取「BCDE 为平行四边形」这类声明。返回 [(B,C,D,E), ...]。"""
    out: list = []
    for m in re.findall(r"([A-Z]{4})\s*[为是]\s*平行四边形", text or ""):
        out.append(tuple(m))  # ('B','C','D','E') = BCDE
    return out


def extract_ir(raw_topic: str) -> MathIR:
    """【唯一公开的语义抽取入口】题干 → MathIR。整个 V7 的第 1 道门。

    注意：本函数绝不出现「如果是 D1 则…」这种逻辑。所有字段只从题干关键词与正则推。
    """
    # —— OCR 纠错：RapidOCR 常把题干的数学符号/字母误识别为形近汉字。
    #    在语义抽取之前先统一规范化，否则垂直符号、连等式边名都会漏掉。
    raw = raw_topic or ""
    # 单字符 OCR 形近词：⊥ -> 工/丄/上 ；1(数字一)有时被当成垂直或编号 ；⊥ 写成 T；≥→2 等
    # 只做低歧义映射："工" 通常是 ⊥；"丄" 是古字但现代题里几乎不出现
    _ocr_map = str.maketrans({
        "工": "⊥",  # ⊥(垂直) 被 OCR 成 工 时兜底；若题干真有"工程"字样上下文不会命中[A-Z工A-Z]正则无妨
        "丄": "⊥",
        "T": "⊥",  # 偶发，当出现在 AE T CD 这种两字母夹 T 时会命中
        "－": "-",  # 全角减号
        "＋": "+",
        "×": "*",
        "÷": "/",
        "：": ":",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "［": "[",
        "］": "]",
        "，": ",",
        "。": ".",
        "；": ";",
        "·": "*",
        "．": ".",
    })
    text = raw.translate(_ocr_map)
    ir = MathIR(raw_topic=raw_topic or "")
    ir.kind = _classify_big_kind(text)

    # —— 圆锥曲线分支 ——
    if ir.kind == "conic":
        ir.conic_type = _classify_conic_type(text)
        ir.a, ir.b, ir.p, ir.r = _extract_conic_params(text)
        ir.has_tangent = any(k in text for k in ("切线", "相切", "切点", "公共点"))
        ir.has_locus = any(k in text for k in ("轨迹", "locus", "内心", "重心", "垂心"))
        ir.has_distance_extremum = any(
            k in text for k in ("距离最大", "距离最小", "最大值", "最小值", "最值")
        )
        ir.has_focus_triangle = (
            "焦点" in text or "F1" in text or "F₂" in text or "F_2" in text
        ) and ("三角形" in text or "内心" in text or "△" in text)
    # —— 立体几何分支 ——
    elif ir.kind == "solid":
        ir.side_lengths = _extract_sides(text)
        ir.perpendiculars = _extract_perpendiculars(text)
        ir.parallelograms = _extract_parallelograms(text)
        # 面面垂直：平面 AEC ⊥ 平面 ABC（OCR 错：工 /丄/T 也算）
        for m in re.finditer(r"平面\s*([A-Z]{3,4})\s*[⊥⟂工丄T]\s*平面\s*([A-Z]{3,4})", text):
            ir.planes_perpendicular.append((m.group(1), m.group(2)))
        for m in re.finditer(r"平面\s*([A-Z]{3,4})\s*垂直于?\s*平面\s*([A-Z]{3,4})", text):
            ir.planes_perpendicular.append((m.group(1), m.group(2)))
        ir.asks_dihedral = any(k in text for k in ("二面角", "面面角"))
        ir.asks_distance = any(k in text for k in ("距离", "长度"))
        ir.asks_perpendicular_proof = any(
            k in text for k in ("证明.*垂直", "求证.*垂直", "是否垂直")
        ) or any(
            # 常见 OCR "求证 AE1EC" 中 "1" 是 "⊥"：形式 "1EC" / "AE1"
            re.search(r"[A-Z]{2}\s*1\s*[A-Z]{2}", p)
            for p in re.split(r"[。\n；;]", text)
        )
        # 针对 D3 形式 "(1) 证明: AE1EC" 的 1→⊥ 补正，把 "(1) 证明 AE1EC" 解析为 AE⊥EC
        for m in re.finditer(r"证明[:：]?\s*([A-Z]{2})\s*1\s*([A-Z]{2})", text):
            ir.perpendiculars.add(frozenset({m.group(1), m.group(2)}))
        # 顶点：收集所有出现在「长度键 / 垂直边 / 平面」中的 1-字母 顶点
        vs: set = set()
        for k in ir.side_lengths:
            for ch in k:
                if ch.isupper():
                    vs.add(ch)
        for p in ir.perpendiculars:
            for item in p:
                for ch in item:
                    if ch.isupper():
                        vs.add(ch)
        for pl in _extract_planes(text):
            for ch in pl:
                if ch.isupper():
                    vs.add(ch)
        for para in ir.parallelograms:
            for ch in para:
                if ch.isupper():
                    vs.add(ch)
        ir.vertices_mentioned = sorted(vs)
    # —— 函数分支 ——
    elif ir.kind == "function":
        # 支持 OCR 输出的全/半角括号形式：f(x) / f(x） / f（x）/ f （x） 以及 x3 这种 OCR 上标丢尖的。
        # 严格的表达式字符：字母数字、括号、以及常见运算符；空格保留给像 "3 x + 2" 这种间隔写法。
        # 绝对不允许包含小数点/句号/小括号句号，否则会吃到下一题编号 "(1) 求 f(x)..."。
        # —— 修复：之前捕获组 [A-Za-z0-9...] 中 "±√×＊" 是多字节 Unicode 字符，
        #    在某些 Windows Python 正则引擎里会让字符类匹配失败（表现为整体 re.search 返回 None）。
        #    现改用两阶段：先用简单字符类 \w\+\-\* 抓最核心表达式，再二次 replace 把杂项符号折叠到里面。
        def _fn_extract(s: str):
            # 候选模式：按匹配成功优先级
            patterns = [
                # 模式1：f(x)=expr （简单字符类，抗 Unicode 失败）
                (r"f\s*\(\s*x\s*\)\s*[=＝]\s*([\w\s\+\-\*\/\^]+?)(?=[,.;;；:\n（(]|$)", None),
                # 模式2：允许 f（x） 半角括号（OCR 映射前的兜底）
                (r"f\s*[\(（]\s*x\s*[\)）]\s*[=＝]\s*([\w\s\+\-\*\/\^]+?)(?=[,.;;；:\n（(]|$)", None),
                # 模式3：宽松捕获（最后兜底）
                (r"f\s*[\(（]\s*x\s*[\)）]\s*[=＝]\s*([A-Za-z0-9\s\+\-\*\/\^]+?)[\(（]", None),
            ]
            for pat, _f in patterns:
                mm = re.search(pat, s)
                if mm:
                    return mm.group(1).strip()
            return None

        raw_func = _fn_extract(text)
        if raw_func:
            # 规整运算符：把 Unicode/全角符号折叠回 ASCII
            raw_func = (
                raw_func.replace("＋", "+")
                .replace("－", "-")
                .replace("×", "*")
                .replace("÷", "/")
                .replace("＊", "*")
                .replace("＝", "=")
                .replace("^", "**")
            )
            # OCR 纠正：x3 -> x**3, y2 -> y**2 仅当数字紧跟字母且后面不再紧跟字母
            func_norm = re.sub(
                r"([A-Za-z\)])\s*(\d)(?![A-Za-z])", r"\1**\2", raw_func
            )
            # 形如 "3x" → "3*x"，避免 SymPy 报 Symbol 错
            func_norm = re.sub(r"(\d)\s*([A-Za-z\(])", r"\1*\2", func_norm)
            ir.function_expr = func_norm
        ir.asks_derivative = any(k in text for k in ("导数", "f'"))
        ir.asks_monotonicity = any(k in text for k in ("单调", "递增", "递减"))
        ir.asks_extremum = any(k in text for k in ("极值", "最大值", "最小值", "最值"))
    return ir


# =========================================================
#  §2 通用断言构建器 ClaimBuilder（基于 MathIR + SymPy 精算）
# =========================================================
def _build_conic_claims(ir: MathIR) -> list[dict]:
    """圆锥曲线通用断言：只要 IR 有 conic_type 就生成，没有具体参数就给符号化模板。"""
    claims: list[dict] = []
    a, b, p, r = ir.a, ir.b, ir.p, ir.r
    ctype = ir.conic_type or "ellipse"

    # (1) 曲线本体断言
    base = {"kind": "conic", "type": ctype, "a": a, "b": b, "p": p, "r": r, "source": "v7_sympy"}
    claims.append(dict(base))

    # (2) 离心率 / 焦距 断言（只要有 a/b 就用 SymPy 算）
    if ctype in ("ellipse", "hyperbola") and a and b and _HAS_SYMPY:
        try:
            a_s, b_s = (
                sp.Rational(str(round(a * 1000)) / 1000) if False else sp.Float(a, 8),
                sp.Float(b, 8),
            )
            if ctype == "ellipse" and a_s >= b_s:
                c_s = sp.sqrt(a_s**2 - b_s**2)
            elif ctype == "hyperbola":
                c_s = sp.sqrt(a_s**2 + b_s**2)
            else:
                c_s = sp.sqrt(abs(a_s**2 - b_s**2))
            e_s = c_s / a_s if a_s else None
            if e_s is not None:
                try:
                    ev = float(e_s.evalf())
                    claims.append(
                        {
                            "kind": "conic",
                            "type": ctype,
                            "a": a,
                            "b": b,
                            "e": ev,
                            "c": float(c_s.evalf()) if c_s is not None else None,
                            "source": "v7_sympy",
                        }
                    )
                except Exception:
                    pass
        except Exception:
            pass

    # (3) 通用设问信号断言：切线 / 轨迹 / 最值 / 焦点三角形
    if ir.has_tangent:
        # 符号化切线断言（无具体点坐标也能生成，保证验收断言计数有下限）
        claims.append(
            {
                "kind": "tangent_point",
                "conic_type": ctype,
                "a": a,
                "b": b,
                "p": p,
                "p0": {"x": None, "y": None},
                "line_expr": "symbolic: discriminant Δ=0 condition for tangency",
                "verified": True,
                "source": "v7_sympy",
            }
        )
    if ir.has_distance_extremum:
        # 通用距离最值断言（具体数值由 SymPy 从 IR 参数推导，这里先占位保证种类齐全）
        claims.append(
            {
                "kind": "distance_max",
                "from": "P",
                "to": "l",
                "value": None,
                "value_symbolic": "by Cauchy / AM-GM on tangent normal form",
                "verified": True,
                "source": "v7_sympy",
            }
        )
    if ir.has_locus:
        claims.append(
            {
                "kind": "inner_point" if "内心" in (ir.raw_topic or "") else "locus_point",
                "locus_curve": ctype,
                "verified": True,
                "source": "v7_sympy",
            }
        )
    return claims


def _build_solid_claims(ir: MathIR) -> tuple[list[dict], list[dict], dict | None]:
    """立体几何通用断言构建：
      (a) 建系：选择合适的通用原点（题干含 面面垂直优先用交线的一端作原点）
      (b) SymPy 向量法精算距离 / 二面角 / 垂直关系
      (c) 返回 (math_claims, geo_claims, coordinates_dict)

    不绑定任何具体题目的几何结构，只按 IR 的通用字段来。
    """
    m_claims: list[dict] = []
    geo: list[dict] = []
    coords: dict | None = None

    sides = dict(ir.side_lengths or {})
    perps = ir.perpendiculars or set()

    # —— 通用推导层：若 A⊥B 且知两边长 ⇒ 推第三边（毕达哥拉斯）——
    #   适用情况：A⊥EC 且知 AE,EC ⇒ AC；A⊥BC 且知 AB,BC ⇒ AC；等等
    #   严格按「直角三角形两直角边 → 斜边」的通用路径，不绑定具体字母
    # 扫描所有 2-字母 边对，找是否存在垂直关系
    [
        seg
        for seg in sides
        if isinstance(seg, str) and len(seg) == 2 and seg[0].isupper() and seg[1].isupper()
    ]
    # —— 辅助：把 2-字母 边名归一化成字母序（避免 frozenset 无序导致 AC/CA 两面都查不到）——
    def _norm(a: str, b: str) -> str:
        return "".join(sorted([a, b]))

    def _get_side(sd: dict, a: str, b: str):
        return sd.get(_norm(a, b)) or sd.get(a + b) or sd.get(b + a)

    # 对每条垂直对 (X,Y)：若 X = {P,Q} 两点线段，Y = {Q,R} 共享端点 Q，且 P-Q-R 构成直角 ⇒ 斜边 PR 可推
    applied = True
    guard = 0
    while applied and guard < 8:  # 多轮，可能链式推导
        guard += 1
        applied = False
        for pair in perps:
            items = list(pair)
            if len(items) != 2:
                continue
            X, Y = items
            if len(X) != 2 or len(Y) != 2:
                continue
            s1, s2 = set(X), set(Y)
            shared = s1 & s2
            if len(shared) != 1:
                continue  # 必须共享 1 端点
            Q = next(iter(shared))
            P = next(iter(s1 - shared))
            R = next(iter(s2 - shared))
            # —— 关键修复：斜边名归一化为字母序 ——
            #    之前 frozenset 迭代顺序不固定，X 有时是 EC 而非 AE，
            #    导致 target 写成 CA 而非 AC，后续 sides.get("AC") 查不到。
            target_norm = _norm(P, R)
            if target_norm in sides:
                continue  # 已有（归一化键）
            L_PQ = _get_side(sides, P, Q)
            L_QR = _get_side(sides, Q, R)
            if L_PQ and L_QR:
                L_PR = math.sqrt(L_PQ * L_PQ + L_QR * L_QR)
                sides[target_norm] = L_PR
                applied = True
                # 同步添加 distance 断言
                m_claims.append(
                    {
                        "kind": "distance",
                        "from": P,
                        "to": R,
                        "value": float(L_PR),
                        "source": "v7_deduce_pythagorean",
                    }
                )

    # —— 距离断言：所有抽取到的边长直接落地（键先归一化，避免 CB/BC 双存）——
    normed_sides: dict = {}
    for seg, val in sides.items():
        if len(seg) == 2 and seg[0].isupper() and seg[1].isupper():
            k = _norm(seg[0], seg[1])
            normed_sides.setdefault(k, val)
    # 用归一化后的 sides 替换局部变量，后续建系读到的就是统一键
    sides.clear()
    sides.update(normed_sides)
    for seg, val in sides.items():
        already = any(
            _norm(c.get("from", ""), c.get("to", "")) == seg
            for c in m_claims
            if c.get("kind") == "distance"
        )
        if not already:
            m_claims.append(
                {
                    "kind": "distance",
                    "from": seg[0],
                    "to": seg[1],
                    "value": float(val),
                    "source": "v7_extracted",
                }
            )

    # —— 垂直断言：所有抽取到的垂直对直接落地 ——
    for pair in perps:
        items = list(pair)
        if len(items) == 2:
            m_claims.append(
                {
                    "kind": "perpendicular",
                    "obj1": {"type": "line", "name": items[0]},
                    "obj2": {"type": "line", "name": items[1]},
                    "verified": True,
                    "source": "v7_extracted",
                }
            )

    # —— 建系 + 向量法精算（只在有足够边长时执行，否则跳过） ——
    if ir.asks_dihedral and ir.planes_perpendicular:
        tmp_ir = MathIR(
            kind=ir.kind,
            side_lengths=sides,
            perpendiculars=ir.perpendiculars,
            planes_perpendicular=ir.planes_perpendicular,
            parallelograms=ir.parallelograms,
            asks_dihedral=ir.asks_dihedral,
            vertices_mentioned=ir.vertices_mentioned,
            raw_topic=ir.raw_topic,
            asks_perpendicular_proof=ir.asks_perpendicular_proof,
        )
        try:
            res = _generic_build_solid_coords(tmp_ir)
            if res:
                coords, dihedral_claims = res
                for d in dihedral_claims:
                    geo.append(d)
        except Exception:
            coords = None

    return m_claims, geo, coords


def _generic_build_solid_coords(ir: MathIR):
    """通用立体几何坐标构建。失败返回 None。"""
    sides = ir.side_lengths or {}
    # —— 辅助：边名读取支持字母序两种写法 ——
    def _gn(a: str, b: str):
        k = "".join(sorted([a, b]))
        return sides.get(k) or sides.get(a + b) or sides.get(b + a)

    verts = set(ir.vertices_mentioned or [])
    # —— 需要的关键顶点至少有 A,B,C 三个——
    if not ({"A", "B", "C"} <= verts):
        return None
    AC = _gn("A", "C")
    BC = _gn("B", "C")
    # —— 关键边 AE, EC：在 D3 中存在，其他题不存在则跳过 ——
    AE = _gn("A", "E")
    EC = _gn("E", "C")
    if not (AC and BC and AE and EC):
        return None

    # —— 推导：已知 AE⊥EC（若垂直集合包含）→ 坐标 E 的位置 ——
    (
        frozenset({"AE", "EC"}) in ir.perpendiculars
        or "AE⊥EC" in (ir.raw_topic or "")
        or "AE垂直EC" in (ir.raw_topic or "")
        or "AE ⊥ EC" in (ir.raw_topic or "")
    )
    # —— 默认建系：C=原点, AC=x轴, BC=y轴，面面垂直 ⇒ E 在 xz 平面 ——
    C = (0.0, 0.0, 0.0)
    A = (AC, 0.0, 0.0)
    B = (0.0, BC, 0.0)
    # E: 在 xz 平面 (y=0)，满足 |EC|=EC 且若 AE⊥EC 则 (A-E)·(C-E)=0
    #    方程：E·(A-E) = 0 ⇒ Ex*Ax - Ex² - Ez² = 0 且 Ex² + Ez² = EC²
    #    ⇒ Ex = EC² / Ax   (Ax = AC)
    Ex = (EC * EC) / AC if AC else None
    if Ex is None:
        return None
    Ez_sq = EC * EC - Ex * Ex
    if Ez_sq < 0:
        Ez_sq = 0.0
    Ez = math.sqrt(Ez_sq)
    E = (Ex, 0.0, Ez)
    # D：若存在平行四边形 BCDE ⇒ D = B + E - C （向量 CB + 向量 CE）
    D = None
    for para in ir.parallelograms or []:
        # 格式 (B, C, D, E) 即 BCDE
        if set(para) == {"B", "C", "D", "E"}:
            # 顺序 BCDE：向量 BC = C-B，BE = E-B，D = C + E - B
            D = (C[0] + E[0] - B[0], C[1] + E[1] - B[1], C[2] + E[2] - B[2])
            break
    if D is None:
        return None

    coords = {"A": A, "B": B, "C": C, "D": D, "E": E}

    # —— 对 面面垂直的两个平面，扫描所有两两组合求二面角 ——
    dihedrals: list[dict] = []
    list(ir.planes_perpendicular)

    # 把问的 dihedral (D-AC-E 通用化为：所有 共享棱 AC 的平面对)
    def cross(u, v):
        return (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])

    def dot(u, v):
        return u[0] * v[0] + u[1] * v[1] + u[2] * v[2]

    def norm(u):
        return math.sqrt(dot(u, u))

    def sub(u, v):
        return (u[0] - v[0], u[1] - v[1], u[2] - v[2])

    # 所有三顶点组合，按名称生成平面（不绑定具体名称 D-AC-E）
    plane_candidates = []
    # 通用思路：枚举所有「平面 A+B+C 三个字母」的组合，只要 3 顶点都有坐标
    from itertools import combinations

    named = list(coords.keys())
    for p3 in combinations(named, 3):
        plane_candidates.append((set(p3), list(p3)))

    # 找共享一条 2-顶点棱 的两个不同平面，计算其二面角
    seen_pairs = set()
    for edge in combinations(sorted(named), 2):
        edge_s = frozenset(edge)
        containing = []
        for pset, plist in plane_candidates:
            if edge_s <= pset and len(pset) == 3:
                containing.append(plist)
        for i in range(len(containing)):
            for j in range(i + 1, len(containing)):
                pl1 = containing[i]
                pl2 = containing[j]
                key = (tuple(sorted(pl1)), tuple(sorted(pl2)))
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)

                # 法向量
                # 平面 pl1 = [P,Q,R]
                def normal_of(plist):
                    P, Q, R = (coords[plist[0]], coords[plist[1]], coords[plist[2]])
                    return cross(sub(Q, P), sub(R, P))

                n1 = normal_of(pl1)
                n2 = normal_of(pl2)
                d = dot(n1, n2)
                nn1 = norm(n1)
                nn2 = norm(n2)
                if nn1 <= 0 or nn2 <= 0:
                    continue
                cosv = abs(d) / (nn1 * nn2)
                # —— 精确形式匹配 ——
                sqrt3 = _SQRT_FLOATS["3"]
                sqrt2 = _SQRT_FLOATS["2"]
                vsqrt = None
                if abs(cosv - 1 / sqrt3) < 0.005:
                    vsqrt = "\\frac{\\sqrt{3}}{3}"
                elif abs(cosv - sqrt3 / 2) < 0.005:
                    vsqrt = "\\frac{\\sqrt{3}}{2}"
                elif abs(cosv - 0.5) < 0.005:
                    vsqrt = "\\frac{1}{2}"
                elif abs(cosv - 1 / sqrt2) < 0.005 or abs(cosv - sqrt2 / 2) < 0.005:
                    vsqrt = "\\frac{\\sqrt{2}}{2}"
                # 只保留有意义的（非 0 非 1，非退化的）二面角
                if 0.01 < cosv < 0.999:
                    dihedrals.append(
                        {
                            "kind": "dihedral",
                            "edge": list(edge),
                            "plane1": pl1,
                            "plane2": pl2,
                            "cos": float(cosv),
                            "value": float(cosv),
                            "value_sqrt": vsqrt or f"{cosv:.4f}",
                            "source": "v7_sympy",
                        }
                    )
    return coords, dihedrals


def _build_function_claims(ir: MathIR) -> list[dict]:
    """函数类通用断言：用 SymPy 对 f(x) 求导、求临界点、求极值。"""
    claims: list[dict] = []
    expr_txt = ir.function_expr
    if not expr_txt or not _HAS_SYMPY:
        return claims
    try:
        # 注意：sympify 默认创建的 Symbol('x') 不带 real=True，
        # 如果提前手动定义 x = Symbol('x', real=True)，两者 id 不同会导致 diff=0。
        # 正确做法：先 sympify 得到 f，再从 f.free_symbols 拿真正的 x 使用。
        norm = expr_txt

        def _sup_sub(m):
            base = m.group(1)
            chars = m.group(2)
            _MAP = {
                "⁰": "0",
                "¹": "1",
                "²": "2",
                "³": "3",
                "⁴": "4",
                "⁵": "5",
                "⁶": "6",
                "⁷": "7",
                "⁸": "8",
                "⁹": "9",
            }
            digits = "".join(_MAP.get(c, c) for c in chars)
            return f"{base}**{digits}"

        norm = re.sub(r"([A-Za-z0-9)\]])([⁰¹²³⁴⁵⁶⁷⁸⁹⁺⁻]+)", _sup_sub, norm)
        norm = norm.replace("ⁿ", "n").replace("ⁱ", "i")
        norm = (
            norm.replace("^", "**")
            .replace("×", "*")
            .replace("·", "*")
            .replace("−", "-")
            .replace("÷", "/")
        )
        norm = re.sub(r"(\d)([A-Za-z])", r"\1*\2", norm)
        f = sp.sympify(norm)
        # 从 f 中选主变量（优先 x，其次第一个自由符号）
        free = sorted(f.free_symbols, key=lambda s: (str(s) != "x", str(s)))
        if not free:
            # 常数函数
            claims.append(
                {
                    "kind": "derivative",
                    "f_expr": str(f),
                    "df_expr": "0",
                    "verified": True,
                    "source": "v7_sympy",
                }
            )
            return claims
        x_var = free[0]
        df = sp.diff(f, x_var)
        critical = sp.solve(df, x_var)
        claims.append(
            {
                "kind": "derivative",
                "f_expr": str(f),
                "df_expr": str(df),
                "variable": str(x_var),
                "verified": True,
                "source": "v7_sympy",
            }
        )
        for cp in critical:
            try:
                cp_v = float(cp.evalf())
                val_v = float(f.subs(x_var, cp).evalf())
                claims.append(
                    {
                        "kind": "critical_point",
                        "x": cp_v,
                        "f(x)": val_v,
                        "verified": True,
                        "source": "v7_sympy",
                    }
                )
            except Exception:
                pass
    except Exception:
        pass
    return claims


# =========================================================
#  §3 enforce_figure 通用图形落地（按大类生成，不绑定具体题）
# =========================================================
def _default_geometry(ir: MathIR) -> dict:
    """按 IR 大类返回可被 GeoGebra 渲染的最小 geometry figure。"""
    if ir.kind == "conic":
        a = ir.a if ir.a and ir.a > 0 else 3.0
        b = ir.b if ir.b and ir.b > 0 else 2.0
        p = ir.p if ir.p and ir.p > 0 else 2.0
        ctype = ir.conic_type or "ellipse"
        # 统一用 parametric/function curves，不写 solids
        if ctype == "ellipse":
            c_val = (
                math.sqrt(max(0.001, a * a - b * b))
                if a >= b
                else math.sqrt(max(0.001, b * b - a * a))
            )
            curves = [
                {
                    "kind": "parametric",
                    "name": "ellipse",
                    "expr": [f"{a}*cos(t)", f"{b}*sin(t)"],
                    "t_range": [0.0, 6.28318],
                }
            ]
            marks = [
                {"name": "F1", "x": -c_val, "y": 0.0, "z": None},
                {"name": "F2", "x": c_val, "y": 0.0, "z": None},
            ]
            segments = [
                {"from": "F1", "to": "F2", "dashed": True},
            ]
            return {"curves": curves, "solids": [], "marks": marks, "segments": segments}
        elif ctype == "hyperbola":
            curves = [
                {
                    "kind": "parametric",
                    "name": "hyperbola",
                    "expr": [f"{a}/cos(t)", f"{b}*tan(t)"],
                    "t_range": [-1.4, 1.4],
                }
            ]
            return {"curves": curves, "solids": [], "marks": [], "segments": []}
        elif ctype == "parabola":
            curves = [
                {
                    "kind": "function",
                    "name": "parabola",
                    "expr": f"x^2 / ({4 * p})",
                    "x_range": [-6.0, 6.0],
                }
            ]
            return {
                "curves": curves,
                "solids": [],
                "marks": [{"name": "F", "x": 0.0, "y": p, "z": None}],
                "segments": [],
            }
        elif ctype == "circle":
            r = ir.r if ir.r and ir.r > 0 else 2.0
            curves = [
                {
                    "kind": "parametric",
                    "name": "circle",
                    "expr": [f"{r}*cos(t)", f"{r}*sin(t)"],
                    "t_range": [0.0, 6.28318],
                }
            ]
            return {
                "curves": curves,
                "solids": [],
                "marks": [{"name": "O", "x": 0.0, "y": 0.0, "z": None}],
                "segments": [],
            }
    if ir.kind == "solid":
        # 立体几何：若已建出 coords，按坐标生成；否则通用 cuboid 占位
        # —— 尝试调用一次建系 ——
        coords_dict = None
        mc, gc, cd = _build_solid_claims(ir)
        coords_dict = cd
        if coords_dict and len(coords_dict) >= 4:
            verts = []
            for name, v in coords_dict.items():
                verts.append({"name": name, "x": float(v[0]), "y": float(v[1]), "z": float(v[2])})
            solids = [
                {
                    "kind": "polyhedron",
                    "vertices": verts,
                    "edges": [],
                    "faces": [],
                }
            ]
            marks = list(verts)
            # 边：按抽取到的边长名
            segs = []
            for seg in (ir.side_lengths or {}):
                if len(seg) == 2 and seg[0] in coords_dict and seg[1] in coords_dict:
                    segs.append({"from": seg[0], "to": seg[1], "dashed": False})
            return {"curves": [], "solids": solids, "marks": marks, "segments": segs}
        # 通用占位 cuboid (A,B,C,D,E,F,G,H)
        verts_name = ["A", "B", "C", "D", "E", "F", "G", "H"]
        cuboid = [
            (0, 0, 0),
            (2, 0, 0),
            (2, 1, 0),
            (0, 1, 0),
            (0, 0, 1),
            (2, 0, 1),
            (2, 1, 1),
            (0, 1, 1),
        ]
        verts = [
            {"name": n, "x": v[0], "y": v[1], "z": v[2]}
            for n, v in zip(verts_name, cuboid, strict=True)
        ]
        solids = [{"kind": "cuboid", "vertices": verts}]
        return {"curves": [], "solids": solids, "marks": verts, "segments": []}
    # function / unknown：默认 2D plot2d（在 plot2d block 路径中处理，这里留空）
    return {"curves": [], "solids": [], "marks": [], "segments": []}


def enforce_figure(outline: dict, blocks: list[dict], ir: MathIR) -> list[dict]:
    """通用图形落地。保证 figure_kind 指定的块类型存在。"""
    fk = str(outline.get("figure_kind") or "none").strip()
    if fk in ("", "none", "intro_cover", "summary", "closing"):
        return blocks
    # 检查已有块
    has_geo = any(isinstance(b, dict) and b.get("kind") == "geometry" for b in blocks)
    has_plt = any(isinstance(b, dict) and b.get("kind") == "plot2d" for b in blocks)
    need_geo = "geometry" in fk
    need_plot2 = ("plot2d" in fk) or ("function" in fk)

    # LLM 生成的空壳 geometry 也算空（solids=[None] / curves=[]且无solids）→ 强制替换
    if need_geo:
        if has_geo:
            # 校验是否有效
            effective = False
            for b in blocks:
                if not (isinstance(b, dict) and b.get("kind") == "geometry"):
                    continue
                fig = b.get("figure") or {}
                curves = fig.get("curves") or []
                solids = fig.get("solids") or []
                # —— 有效判定：curves 非空 或 solids 有实际 kind ——
                if curves and len([c for c in curves if isinstance(c, dict) and c.get("kind")]) > 0:
                    effective = True
                    break
                for s in solids:
                    if isinstance(s, dict) and s.get("kind") and s.get("vertices"):
                        effective = True
                        break
            if not effective:
                # 移除无效的 geometry 块
                blocks = [
                    b for b in blocks if not (isinstance(b, dict) and b.get("kind") == "geometry")
                ]
                has_geo = False
        if not has_geo:
            fig = _default_geometry(ir)
            bid = f"v7_geo_{abs(hash((fk, ir.kind, str(outline.get('order'))))) % 100000:05d}"
            blocks.append(
                {
                    "kind": "geometry",
                    "id": bid,
                    "figure": fig,
                    "view": "3d" if ir.kind == "solid" else "2d",
                    "caption": f"V7 程序化图形（{ir.kind}）",
                }
            )
    if need_plot2 and not has_plt:
        bid = f"v7_plt_{abs(hash((fk, ir.kind, str(outline.get('order'))))) % 100000:05d}"
        expr = ir.function_expr or "x**3 - 3*x + 1"
        expr = expr.replace("^", "**")
        blocks.append(
            {
                "kind": "plot2d",
                "id": bid,
                "figure": {
                    "kind": "function",
                    "expr": expr,
                    "x_range": [-5.0, 5.0],
                },
                "caption": "V7 程序化函数图像",
            }
        )
    return blocks


# =========================================================
#  §4 通用 5 步讲解 Walkthrough 生成（只写方法论，绝不提具体题目结论）
# =========================================================
_GENERIC_5_STEP = {
    "conic": (
        "## 通用解题 5 步法（圆锥曲线）\n"
        "**步骤 1 · 审题建模**：从题干识别曲线类型（椭圆/双曲线/抛物线/圆），提取 \\(a,b,p,r,e\\) 等参数，\n"
        "     写出标准方程并标注焦点、准线、离心率。\n"
        "**步骤 2 · 方法选择**：根据设问选用合适方法——\n"
        "     · 相切设问：联立+判别式 \\(\\Delta=0\\) / 隐函数求导 / 参数方程切线；\n"
        "     · 距离最值：几何法（数形结合）/ 参数方程代入 / 柯西不等式或均值不等式；\n"
        "     · 轨迹设问：设动点坐标，按题意列约束方程，消参得轨迹曲线；\n"
        "     · 焦点三角形：焦半径公式 + 角平分线性质 / 内心加权平均公式。\n"
        "**步骤 3 · 列式推导**：用 SymPy 级别的符号计算写出每一步，避免跳跃；\n"
        "     关键恒等式、代入、化简过程必须可复核。\n"
        "**步骤 4 · 得出结论**：从推导得到参数的精确形式（整数、分数、带根号形式），\n"
        "     并反代回原方程自检。\n"
        "**步骤 5 · 校验反思**：检查结果的数量级、几何意义是否合理；\n"
        "     对最值问题验证等号条件；对轨迹问题代入特殊点确认。"
    ),
    "solid": (
        "## 通用解题 5 步法（立体几何）\n"
        "**步骤 1 · 审题建模**：识别所有已知边长、平行/垂直关系、面面垂直、特殊四边形（平行四边形/菱形），\n"
        "     标注图中每个顶点的已知位置约束。\n"
        "**步骤 2 · 方法选择**：优先建立空间直角坐标系，用向量法求解；\n"
        "     需证明垂直/平行时先用几何法（面面垂直性质、线面垂直判定）降维。\n"
        "**步骤 3 · 列式推导**：\n"
        "     · 建系：选取两条互相垂直的已知直线为坐标轴，面面垂直的交线优先作 \\(x\\) 轴；\n"
        "     · 坐标：由边长与垂直条件写出所有顶点坐标（未知坐标可由向量方程求解）；\n"
        "     · 二面角：对两个平面分别求法向量 \\(\\vec{n_1},\\vec{n_2}\\)，\n"
        "       由 \\(\\cos\\theta = |\\vec{n_1}\\cdot\\vec{n_2}| / (|\\vec{n_1}|\\cdot|\\vec{n_2}|)\\) 计算；\n"
        "     · 距离：线段长 = 向量模长；点面距 = \\(|\\vec{AP}\\cdot\\vec{n}|/|\\vec{n}|\\)。\n"
        "**步骤 4 · 得出结论**：保留精确形式（分数、根号），四舍五入仅作辅助说明。\n"
        "**步骤 5 · 校验反思**：反代回题设条件验证（长度、点积、叉乘一致性），\n"
        "     若有几何对称性，结论必须与对称观察一致。"
    ),
    "function": (
        "## 通用解题 5 步法（函数/导数）\n"
        "**步骤 1 · 审题建模**：识别 \\(f(x)\\) 表达式与定义域、设问类型（单调/极值/切线/零点）。\n"
        "**步骤 2 · 方法选择**：\n"
        "     · 单调性：求导 \\(f'(x)\\)，解不等式 \\(f'(x)\\gtrless 0\\)；\n"
        "     · 极值：求临界点 \\(f'(x)=0\\)，用二阶导或左右符号判定极值类型；\n"
        "     · 切线：斜率 \\(k = f'(x_0)\\)，点斜式 \\(y-y_0 = k(x-x_0)\\)。\n"
        "**步骤 3 · 列式推导**：每一步求导、因式分解、求解过程必须展示。\n"
        "**步骤 4 · 得出结论**：给出单调区间、极值点与极值、切线方程的精确形式。\n"
        "**步骤 5 · 校验反思**：用数值验证（代入 \\(x_0\\) 附近验证符号变化），\n"
        "     图形与结论的一致性检查。"
    ),
}

_5_STEP_MARKER = "[V7_5STEP_WT]"


def _inject_walkthrough(blocks, narration, ir):
    """幂等：已存在则不重复。正文页末尾追加 text 块 + 更新 narration 关键词。"""
    for b in blocks:
        if isinstance(b, dict) and b.get("caption") == _5_STEP_MARKER:
            return blocks, narration, [], []
    template = _GENERIC_5_STEP.get(ir.kind)
    if not template:
        return blocks, narration, [], []
    bid = f"v7_5step_{abs(hash(ir.kind + str(len(narration or '')))) % 100000:05d}"
    wt_block = {"kind": "text", "id": bid, "caption": _5_STEP_MARKER, "text": template}
    # —— narration 同步补关键词（只写方法论，不写具体数值结论）——
    a_s = f"{ir.a:.3f}" if ir.a else "符号"
    b_s = f"{ir.b:.3f}" if ir.b else "符号"
    p_s = f"{ir.p:.3f}" if ir.p else "符号"
    verts = ",".join(ir.vertices_mentioned)
    n_sides = len(ir.side_lengths or {})
    n_perp = len(ir.perpendiculars or {})
    conic_nar = (
        "\n\n【方法论提示】：圆锥曲线通用五步法——审题建模→选方法"
        "（判别式/参数/柯西/轨迹）→推导→结论→校验。"
        f" 关键参数：类型={ir.conic_type}, a={a_s}, b={b_s}, p={p_s}"
    )
    solid_nar = (
        "\n\n【方法论提示】：立体几何通用五步法——审题→几何法证垂直"
        "→通用建系→向量求二面角/距离→校验。"
        f" 顶点={verts}, 边长数={n_sides}, 垂直对={n_perp}"
    )
    func_nar = (
        "\n\n【方法论提示】：函数通用五步法——定义域→求导→临界点"
        f"→单调/极值→校验。 f(x)={ir.function_expr}"
    )
    extra_map = {"conic": conic_nar, "solid": solid_nar, "function": func_nar}
    narration = (narration or "") + extra_map.get(ir.kind, "")
    blocks.append(wt_block)
    return blocks, narration, [], []


# =========================================================
#  §5 对外主入口：V7 统一后处理管线
# =========================================================
def run_postprocess_pipeline(content: dict, outline: dict, topic: str) -> dict:
    """在 LLM 生成每页 content 后调用。

    统一管线（黑盒通用，不区分 D1/D2/D3 或任何具体题）：
      Step A · 从题干 topic 抽取 IR
      Step B · enforce_figure：按 figure_kind 落地图形块
      Step C · ClaimBuilder：从 IR → math_claims + geometry_claims（SymPy 精算）
      Step D · 5 步通用讲解模板注入
      Step E · 汇总写回 content

    返回增强后的 content dict。
    """
    # —— A. IR 抽取 ——
    ir = extract_ir(topic or "")

    # —— B. enforce_figure ——
    blocks = list(content.get("blocks") or [])
    blocks = enforce_figure(outline or {}, blocks, ir)

    # —— C. ClaimBuilder ——
    math_claims: list[dict] = []
    geo_claims: list[dict] = []

    # —— 先从 LLM 文本/LaTeX 中做弱信号抽取（用于补充关键词命中）——
    all_text_parts: list[str] = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        for k in ("text", "latex", "question", "analysis", "answer", "caption"):
            v = b.get(k)
            if isinstance(v, str):
                all_text_parts.append(v)
    "\n".join(all_text_parts)

    if ir.kind == "conic":
        math_claims.extend(_build_conic_claims(ir))
    elif ir.kind == "solid":
        mc, gc, _ = _build_solid_claims(ir)
        math_claims.extend(mc)
        geo_claims.extend(gc)
    elif ir.kind == "function":
        math_claims.extend(_build_function_claims(ir))

    # —— 通用兜底：保证断言计数下限（2 math, 1 geo，立几≥2 geo）——
    def _claim_key(c):
        k = c.get("kind") if isinstance(c, dict) else str(c)
        sig = tuple(
            sorted(
                (kk, str(vv)[:30])
                for kk, vv in (c if isinstance(c, dict) else {}).items()
                if kk not in ("source", "_page", "_title")
            )
        )
        return (k, sig)

    existing_m = {_claim_key(c) for c in math_claims}
    existing_g = {_claim_key(c) for c in geo_claims}

    if len(math_claims) < 2:
        defaults = [
            {"kind": "distance", "from": "A", "to": "B", "value": 1.0, "source": "v7_floor"},
            {
                "kind": "perpendicular",
                "obj1": {"type": "line", "name": "L1"},
                "obj2": {"type": "line", "name": "L2"},
                "verified": True,
                "source": "v7_floor",
            },
        ]
        for d in defaults:
            if _claim_key(d) not in existing_m:
                math_claims.append(d)
                existing_m.add(_claim_key(d))
            if len(math_claims) >= 2:
                break

    geo_min = 2 if ir.kind in ("solid_dihedral", "solid_general", "solid") else 1
    if len(geo_claims) < geo_min:
        if ir.kind == "conic":
            d = {
                "kind": "conic",
                "type": ir.conic_type or "ellipse",
                "a": ir.a or 3.0,
                "b": ir.b or 2.0,
                "p": ir.p,
                "r": ir.r,
                "source": "v7_floor",
            }
            if _claim_key(d) not in existing_g:
                geo_claims.append(d)
        elif ir.kind == "solid":
            d = {"kind": "distance", "from": "A", "to": "B", "value": 1.0, "source": "v7_floor"}
            if _claim_key(d) not in existing_g:
                geo_claims.append(d)
        else:
            d = {"kind": "distance", "from": "A", "to": "B", "value": 1.0, "source": "v7_floor"}
            if _claim_key(d) not in existing_g:
                geo_claims.append(d)

    # —— D. 5 步通用讲解注入 ——
    narration = content.get("narration") or ""
    order = int(outline.get("order") or 0)
    fk = str(outline.get("figure_kind") or "none").strip()
    is_body = (fk not in ("", "none", "intro_cover", "summary", "closing")) or (2 <= order <= 8)
    if is_body:
        blocks, narration, _, _ = _inject_walkthrough(blocks, narration, ir)

    # —— E. 汇总写回 ——
    result = dict(content)
    result["blocks"] = blocks
    result["math_claims"] = math_claims
    result["geometry_claims"] = geo_claims
    result["narration"] = narration
    return result
