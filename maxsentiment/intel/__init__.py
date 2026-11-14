"""The intelligence layer: deterministic labeling + a recursive, self-growing theme tree.

A reader model (gpt-5) only ever *proposes* a question; the OpenAI Decisions API
(gpt-6-luna) *labels* every item. The reader never sees the final counts, so the
numbers come from the deterministic classifier, not from a model's vibe.
"""
from .engagement import effort_score, score_comment, WEIGHTS
from .decide import classify, classify_many
from .propose import propose_question
from .filter import mark_genuine, split_genuine, GENUINE_Q
from .tree import build_tree

__all__ = ["effort_score", "score_comment", "WEIGHTS", "classify", "classify_many",
           "propose_question", "mark_genuine", "split_genuine", "GENUINE_Q", "build_tree"]
