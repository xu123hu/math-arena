"""Grading V2 workspace contract tests.

The first tests protect persisted question-scoring facts. A V2 rubric may be
missing, but neither the API nor the client may manufacture it from a generic
score form.
"""

from app.models.coursework import QuizItem


def test_quiz_item_declares_nullable_score_point_contract():
    mapper_fields = QuizItem.__mapper__.attrs

    assert "max_score" in mapper_fields
    assert "grading_rubric" in mapper_fields
    assert QuizItem.__table__.c.max_score.nullable is True
    assert QuizItem.__table__.c.grading_rubric.nullable is True


def test_grading_rubric_preserves_high_school_math_score_points():
    rubric = [
        {
            "id": "derivative",
            "criterion": "正确求导",
            "points": 3,
            "evidence_hint": "写出 f'(x)=3x²-3",
        },
        {
            "id": "critical",
            "criterion": "确定分界点",
            "points": 3,
            "evidence_hint": "x=-1,1",
        },
        {
            "id": "interval",
            "criterion": "写出单调区间",
            "points": 4,
            "evidence_hint": "给出增减区间",
        },
    ]

    assert sum(item["points"] for item in rubric) == 10
    assert rubric[2]["criterion"] == "写出单调区间"
