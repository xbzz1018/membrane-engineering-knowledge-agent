"""Application singleton for the online knowledge Agent."""

from src.engineering.knowledge_agent import KnowledgeAgent

_knowledge_agent: KnowledgeAgent | None = None


def get_knowledge_agent() -> KnowledgeAgent:
    global _knowledge_agent
    if _knowledge_agent is None:
        _knowledge_agent = KnowledgeAgent()
    return _knowledge_agent
