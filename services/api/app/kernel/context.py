"""上下文装配（kernel/context.py）

总预算 12K token，P0~P2 保命段永不裁。
裁剪顺序：P3→P5→P4→P6（ADR-001-10）。
"""

import re
from pathlib import Path

import structlog

from app.kernel.memory import UserProfileData, WorkingMemory

logger = structlog.get_logger()

# Persona 提示词目录
_PROMPTS_DIR = Path(__file__).parent / "prompts"

# 中英文混合 token 估算常量
_CN_CHAR_PER_TOKEN = 1.5
_EN_CHAR_PER_TOKEN = 4.0
_CN_CHAR_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]")


def _estimate_tokens(text: str) -> int:
    """中英文混合 token 估算。

    中文约 1.5 字符/token，英文约 4 字符/token。
    比原先统一 len(text)/1.5 更精确。
    """
    if not text:
        return 0
    cn_chars = len(_CN_CHAR_RE.findall(text))
    en_chars = len(text) - cn_chars
    return int(cn_chars / _CN_CHAR_PER_TOKEN + en_chars / _EN_CHAR_PER_TOKEN) + 1


# Persona 文本缓存（启动后不变，避免每请求读盘）
_persona_cache: dict[str, str] = {}


def _load_persona(role: str) -> str:
    """加载角色 Persona 提示词（带进程内缓存）"""
    if role in _persona_cache:
        return _persona_cache[role]

    text = ""
    persona_file = _PROMPTS_DIR / f"{role}.md"
    if persona_file.exists():
        text = persona_file.read_text(encoding="utf-8")
    else:
        # 默认回退到 student
        default_file = _PROMPTS_DIR / "student.md"
        if default_file.exists():
            text = default_file.read_text(encoding="utf-8")
        else:
            text = "你是一位数学助手。数学公式使用 LaTeX 格式：行内用 \\(...\\)，独立公式用 $$...$$，分步推理并给出依据。"

    _persona_cache[role] = text
    return text


class ContextAssembler:
    """上下文装配器：12K 预算，P0~P7 分段"""

    BUDGET = {
        "P0_system_persona": 800,
        "P1_user_message": 2000,
        "P2_skill_params": 600,
        "P3_rag_chunks": 4000,
        "P4_working_memory": 1600,
        "P5_user_profile": 500,
        "P6_episodic": 800,
        "P7_output_spec": 400,
    }

    TOTAL_BUDGET = 12_000  # 总预算 12K tokens

    # P4 最近消息最少保留数
    _MIN_RECENT_MESSAGES = 3
    # P4 摘要最短保留字符数
    _MIN_SUMMARY_CHARS = 50

    async def assemble(
        self,
        *,
        user_message: str,
        active_role: str = "student",
        working_memory: WorkingMemory | None = None,
        user_profile: UserProfileData | None = None,
        rag_chunks: list[dict] | None = None,
        skill_params: dict | None = None,
        output_spec: str = "",
        episodic_memories: list[dict] | None = None,
    ) -> list[dict]:
        """装配上下文消息列表。

        按 P0~P7 预算分配，P0~P2 保命段永不裁。
        裁剪顺序：P3→P5→P4→P6。
        """
        # ===== 构建各层级内容 =====

        # P0: System Persona（保命段，永不裁）
        persona = _load_persona(active_role)
        system_core = persona

        # P7: Output Spec（附加到 system core）
        if output_spec:
            system_core += f"\n\n## 输出要求\n{output_spec}"

        # P5: User Profile（可裁剪）
        profile_text = self._build_profile_text(user_profile)

        # P4 summary: 对话摘要（可裁剪）
        summary_text = ""
        if working_memory and working_memory.summary:
            summary_text = working_memory.summary

        # P3: RAG Chunks（可裁剪，最高优先裁剪）
        rag_text = ""
        if rag_chunks:
            rag_text = self._format_rag_chunks(rag_chunks)

        # P4 recent_messages（可裁剪）
        recent_messages: list[dict] = []
        if working_memory and working_memory.recent_messages:
            recent_messages = list(working_memory.recent_messages)

        # P6: Episodic Memory（可裁剪，最低优先）
        episodic_text = ""
        if episodic_memories:
            episodic_text = self._format_episodic_memories(episodic_memories)

        # ===== 计算总 token =====
        all_parts = {
            "system_core": system_core,
            "profile_text": profile_text,
            "summary_text": summary_text,
            "rag_text": rag_text,
            "recent_messages": recent_messages,
            "episodic_text": episodic_text,
            "user_message": user_message,
        }
        total_tokens = self._estimate_all_tokens(all_parts)

        logger.info(
            "context.assembled",
            total_messages=len(recent_messages) + 3,  # system + rag + user + recent
            estimated_tokens=total_tokens,
            has_rag=bool(rag_chunks),
            has_memory=bool(working_memory and working_memory.summary),
            role=active_role,
        )

        # ===== 超预算时按 P3→P5→P4→P6 顺序裁剪 =====
        trim_log: list[str] = []
        if total_tokens > self.TOTAL_BUDGET:
            rag_text, profile_text, summary_text, recent_messages, episodic_text, trim_log = (
                self._trim_to_budget(
                    system_core=system_core,
                    user_message=user_message,
                    rag_text=rag_text,
                    profile_text=profile_text,
                    summary_text=summary_text,
                    recent_messages=recent_messages,
                    episodic_text=episodic_text,
                    total_tokens=total_tokens,
                )
            )

        # ===== 合并为最终 messages 列表 =====
        messages: list[dict] = []

        # system = P0 + P7 + P5(裁剪后) + P4-summary(裁剪后) + P6(裁剪后)
        system_content = system_core
        if profile_text:
            system_content += f"\n\n## 学生档案\n{profile_text}"
        if summary_text:
            system_content += f"\n\n## 对话摘要（之前的讨论）\n{summary_text}"
        if episodic_text:
            system_content += f"\n\n## 历史参考\n{episodic_text}"
        messages.append({"role": "system", "content": system_content})

        # P3: RAG 独立 system 消息
        if rag_text:
            messages.append(
                {
                    "role": "system",
                    "content": (
                        f"## 参考资料（来自教材知识库）\n{rag_text}\n\n"
                        "请基于以上资料回答，引用处标注【N】（N为资料编号）。"
                        "如果资料不足以回答，请说明。"
                    ),
                }
            )

        # P4: 最近消息
        for msg in recent_messages:
            messages.append({"role": msg["role"], "content": msg["content"]})

        # P1: User Message（保命段，永不裁）
        messages.append({"role": "user", "content": user_message})

        if trim_log:
            logger.info("context.trim_applied", steps=trim_log)

        return messages

    # ------------------------------------------------------------------ #
    #  内部辅助
    # ------------------------------------------------------------------ #

    def _build_profile_text(self, user_profile: UserProfileData | None) -> str:
        """构建 P5 用户档案文本（不含 section header）。"""
        if not user_profile:
            return ""
        parts: list[str] = []
        if user_profile.grade:
            parts.append(f"- 年级：{user_profile.grade}")
        if user_profile.level != "unknown":
            parts.append(f"- 数学水平：{user_profile.level}")
        if user_profile.weak_points:
            weak = ", ".join(wp.get("name", "") for wp in user_profile.weak_points)
            parts.append(f"- 薄弱点：{weak}")
        if user_profile.preferences:
            prefs = ", ".join(f"{k}={v}" for k, v in user_profile.preferences.items())
            parts.append(f"- 偏好：{prefs}")
        return "\n".join(parts)

    def _format_rag_chunks(self, chunks: list[dict]) -> str:
        """格式化 RAG 切片为引用文本"""
        parts = []
        for i, chunk in enumerate(chunks, 1):
            source = chunk.get("doc_title", "教材")
            content = chunk.get("content", "")
            parts.append(f"【{i}】（来源：{source}）\n{content}")
        return "\n\n".join(parts)

    def _format_episodic_memories(self, memories: list[dict]) -> str:
        """格式化 P6 情景记忆。"""
        parts = []
        for mem in memories:
            topic = mem.get("topic", "")
            detail = mem.get("detail", "")
            if topic:
                parts.append(f"- {topic}：{detail}" if detail else f"- {topic}")
        return "\n".join(parts) if parts else ""

    def _estimate_all_tokens(self, parts: dict) -> int:
        """估算所有层级的总 token。"""
        total = 0
        for _key, val in parts.items():
            if isinstance(val, str):
                total += _estimate_tokens(val)
            elif isinstance(val, list):
                for msg in val:
                    total += _estimate_tokens(msg.get("content", ""))
        return total

    def _trim_to_budget(
        self,
        *,
        system_core: str,
        user_message: str,
        rag_text: str,
        profile_text: str,
        summary_text: str,
        recent_messages: list[dict],
        episodic_text: str,
        total_tokens: int,
    ) -> tuple[str, str, str, list[dict], str, list[str]]:
        """按 P3→P5→P4→P6 顺序裁剪到预算内。

        返回裁剪后的各层内容及裁剪日志。
        P0(system_core)/P1(user_message) 永不裁剪。
        """
        budget = self.TOTAL_BUDGET
        trim_log: list[str] = []

        def _current_tokens() -> int:
            return (
                _estimate_tokens(system_core)
                + _estimate_tokens(user_message)
                + _estimate_tokens(rag_text)
                + _estimate_tokens(profile_text)
                + _estimate_tokens(summary_text)
                + sum(_estimate_tokens(m.get("content", "")) for m in recent_messages)
                + _estimate_tokens(episodic_text)
            )

        # ---- Step 1: 裁剪 P3 RAG（最高优先） ----
        if _current_tokens() > budget and rag_text:
            original_len = len(rag_text)
            # 逐步缩减 RAG：按行截断
            max_rag_chars = int(self.BUDGET["P3_rag_chunks"] * _CN_CHAR_PER_TOKEN)
            if len(rag_text) > max_rag_chars:
                rag_text = rag_text[:max_rag_chars] + "\n...（资料已截断）"
            trim_log.append(f"P3_rag: {original_len}→{len(rag_text)} chars")
            logger.info("context.trim_p3", before=original_len, after=len(rag_text))

        # ---- Step 2: 裁剪 P5 User Profile ----
        if _current_tokens() > budget and profile_text:
            original_len = len(profile_text)
            # 截断薄弱点列表：只保留前 2 项
            lines = profile_text.split("\n")
            new_lines = []
            for line in lines:
                if line.startswith("- 薄弱点："):
                    # 只保留前 2 个薄弱点
                    items = line.replace("- 薄弱点：", "").split(", ")
                    if len(items) > 2:
                        line = "- 薄弱点：" + ", ".join(items[:2])
                elif line.startswith("- 偏好："):
                    # 截断偏好
                    items = line.replace("- 偏好：", "").split(", ")
                    if len(items) > 2:
                        line = "- 偏好：" + ", ".join(items[:2])
                new_lines.append(line)
            profile_text = "\n".join(new_lines)
            # 如果仍然太长，进一步截断
            max_profile_chars = int(self.BUDGET["P5_user_profile"] * _CN_CHAR_PER_TOKEN)
            if len(profile_text) > max_profile_chars:
                profile_text = profile_text[:max_profile_chars] + "..."
            trim_log.append(f"P5_profile: {original_len}→{len(profile_text)} chars")
            logger.info("context.trim_p5", before=original_len, after=len(profile_text))

        # ---- Step 3: 裁剪 P4 Working Memory ----
        if _current_tokens() > budget:
            # 3a: 减少最近消息数量（保留最近 _MIN_RECENT_MESSAGES 条）
            while len(recent_messages) > self._MIN_RECENT_MESSAGES and _current_tokens() > budget:
                removed = recent_messages.pop(0)
                trim_log.append(
                    f"P4_recent_msg_removed: role={removed.get('role')}, "
                    f"len={len(removed.get('content', ''))}"
                )
            logger.info("context.trim_p4_messages", remaining=len(recent_messages))

            # 3b: 压缩摘要
            if _current_tokens() > budget and summary_text:
                original_len = len(summary_text)
                max_summary_chars = int(self.BUDGET["P4_working_memory"] * _CN_CHAR_PER_TOKEN * 0.5)
                max_summary_chars = max(max_summary_chars, self._MIN_SUMMARY_CHARS)
                if len(summary_text) > max_summary_chars:
                    summary_text = summary_text[:max_summary_chars] + "...（摘要已压缩）"
                    trim_log.append(f"P4_summary: {original_len}→{len(summary_text)} chars")
                    logger.info(
                        "context.trim_p4_summary",
                        before=original_len,
                        after=len(summary_text),
                    )

        # ---- Step 4: 裁剪 P6 Episodic Memory（最低优先） ----
        if _current_tokens() > budget and episodic_text:
            original_len = len(episodic_text)
            # 逐行删除情景记忆条目（从最早的开始）
            lines = episodic_text.split("\n")
            while len(lines) > 1 and _current_tokens() > budget:
                lines.pop(0)
            episodic_text = "\n".join(lines) if lines else ""
            if not episodic_text:
                episodic_text = ""
            trim_log.append(f"P6_episodic: {original_len}→{len(episodic_text)} chars")
            logger.info("context.trim_p6", before=original_len, after=len(episodic_text))

        # ---- 最终检查 ----
        final_tokens = _current_tokens()
        if final_tokens > budget:
            logger.warning(
                "context.trim_insufficient",
                final_tokens=final_tokens,
                budget=budget,
                overflow=final_tokens - budget,
            )

        return rag_text, profile_text, summary_text, recent_messages, episodic_text, trim_log


# ---- 全局单例 ----
_context_assembler: ContextAssembler | None = None


def get_context_assembler() -> ContextAssembler:
    """获取全局 ContextAssembler 单例"""
    global _context_assembler
    if _context_assembler is None:
        _context_assembler = ContextAssembler()
    return _context_assembler
