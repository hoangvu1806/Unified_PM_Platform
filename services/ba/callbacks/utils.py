def extract_session_id(session_id: str, select_agent: str) -> str:
    """
    Extract session ID from session_id string.

    Args:
        session_id: Session ID string.
        select_agent: Select agent name.
    Returns:
        session ID string.
    """
    if not session_id or not select_agent:
        return session_id or ""
    prefix = f"/ba-agent/{select_agent}/"
    result = session_id.removeprefix(prefix)
    return result
