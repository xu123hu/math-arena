from app.kernel.rag import RAGPipeline
from app.models.chunk import Chunk
from app.models.database import async_session_factory
from app.models.knowledge_doc import KnowledgeDoc


async def test_trgm_retrieves_student_textbook_when_scope_filter_is_used():
    """数组参数转换错误会使已导入教材在 student 范围内完全无法关键词召回。"""
    async with async_session_factory() as db:
        doc = KnowledgeDoc(
            title="数学必修第一册（人教A版2019）",
            source_type="textbook",
            status="ready",
            meta_={"scope": "student", "corpus_class": "student_textbook"},
        )
        db.add(doc)
        await db.flush()
        db.add(
            Chunk(
                doc_id=doc.id,
                content="集合的概念：集合是由一些确定的、不同的对象组成的整体。",
                kp_ids=[],
                meta_={"section": "1.1 集合的概念"},
                chunk_index=0,
            )
        )
        await db.commit()

        rows = await RAGPipeline()._trgm_search(
            "集合的概念",
            db,
            content_type="textbook",
            scope="student",
        )

    assert len(rows) == 1
    assert rows[0].doc_title == "数学必修第一册（人教A版2019）"
    assert "集合的概念" in rows[0].content
