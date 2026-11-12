"""Application singletons for online agents."""

from src.agents.knowledge_agent import KnowledgeAgent

_knowledge_agent: KnowledgeAgent | None = None
_conversation_supervisor = None


def get_knowledge_agent() -> KnowledgeAgent:
    global _knowledge_agent
    if _knowledge_agent is None:
        _knowledge_agent = KnowledgeAgent()
    return _knowledge_agent


def get_conversation_supervisor():
    from src.agents.conversation_supervisor import ConversationSupervisor

    global _conversation_supervisor
    if _conversation_supervisor is None:
        _conversation_supervisor = ConversationSupervisor(get_knowledge_agent())
    return _conversation_supervisor
