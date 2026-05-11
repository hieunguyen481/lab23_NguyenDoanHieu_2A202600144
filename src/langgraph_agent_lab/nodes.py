"""Node skeletons for the LangGraph workflow.

Each function should be small, testable, and return a partial state update. Avoid mutating the
input state in place.
"""

from __future__ import annotations

from .state import AgentState, ApprovalDecision, Route, make_event


def intake_node(state: AgentState) -> dict:
    """Normalize raw query into state fields."""
    query = state.get("query", "").strip()
    # Basic normalization: remove extra whitespace
    normalized_query = " ".join(query.split())
    return {
        "query": normalized_query,
        "messages": [f"intake: {normalized_query[:40]}..."],
        "events": [make_event("intake", "completed", "query normalized")],
    }


def classify_node(state: AgentState) -> dict:
    """Classify the query into a route using keyword-based priority."""
    query = state.get("query", "").lower()
    words = query.split()
    clean_words = [w.strip("?!.,;:") for w in words]
    
    # Priority 1: Risky
    risky_keywords = {"refund", "delete", "send", "cancel", "remove", "revoke"}
    if any(k in query for k in risky_keywords):
        return {
            "route": Route.RISKY.value,
            "risk_level": "high",
            "events": [make_event("classify", "completed", "route=risky")],
        }
    
    # Priority 2: Tool
    tool_keywords = {"status", "order", "lookup", "check", "track", "find", "search"}
    if any(k in query for k in tool_keywords):
        return {
            "route": Route.TOOL.value,
            "risk_level": "low",
            "events": [make_event("classify", "completed", "route=tool")],
        }
        
    # Priority 3: Missing Info
    # Heuristic: Very short queries with ambiguous pronouns
    missing_info_keywords = {"it", "that", "this"}
    if len(clean_words) < 5 and any(w in missing_info_keywords for w in clean_words):
         return {
            "route": Route.MISSING_INFO.value,
            "risk_level": "low",
            "events": [make_event("classify", "completed", "route=missing_info")],
        }
    
    # Priority 4: Error
    error_keywords = {"timeout", "fail", "error", "crash", "unavailable"}
    if any(k in query for k in error_keywords):
        return {
            "route": Route.ERROR.value,
            "risk_level": "low",
            "events": [make_event("classify", "completed", "route=error")],
        }

    # Default: Simple
    return {
        "route": Route.SIMPLE.value,
        "risk_level": "low",
        "events": [make_event("classify", "completed", "route=simple")],
    }


def ask_clarification_node(state: AgentState) -> dict:
    """Ask for missing information instead of hallucinating."""
    query = state.get("query", "")
    if "it" in query.lower():
        question = "I'm sorry, I'm not sure what 'it' refers to. Could you please provide more details, like an order ID or a specific issue?"
    else:
        question = "Could you please provide more information so I can help you better?"
        
    return {
        "pending_question": question,
        "final_answer": question,
        "events": [make_event("clarify", "completed", "missing information requested")],
    }


def tool_node(state: AgentState) -> dict:
    """Call a mock tool with retry simulation."""
    attempt = int(state.get("attempt", 0))
    scenario_id = state.get("scenario_id", "unknown")
    route = state.get("route")
    
    # Simulate transient failures for error-route scenarios
    if route == Route.ERROR.value and attempt < 2:
        result = f"ERROR: transient failure at attempt {attempt} for scenario {scenario_id}"
    elif route == Route.ERROR.value and attempt >= 2 and scenario_id == "S07_dead_letter":
        # S07 should still fail if it's the dead letter scenario and we reached max
        result = f"ERROR: permanent failure for scenario {scenario_id}"
    else:
        result = f"Success: Processed {scenario_id} query using mock tool."
        
    return {
        "tool_results": [result],
        "events": [make_event("tool", "completed", f"tool executed attempt={attempt}")],
    }


def risky_action_node(state: AgentState) -> dict:
    """Prepare a risky action for approval."""
    query = state.get("query", "")
    action = f"Perform risky operation: '{query}'"
    return {
        "proposed_action": action,
        "events": [make_event("risky_action", "pending_approval", f"Action: {action}")],
    }


def approval_node(state: AgentState) -> dict:
    """Human approval step with optional LangGraph interrupt().

    Set LANGGRAPH_INTERRUPT=true to use real interrupt() for HITL demos.
    Default uses mock decision so tests and CI run offline.

    TODO(student): implement reject/edit decisions and timeout escalation.
    """
    import os

    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        from langgraph.types import interrupt

        value = interrupt({
            "proposed_action": state.get("proposed_action"),
            "risk_level": state.get("risk_level"),
        })
        if isinstance(value, dict):
            decision = ApprovalDecision(**value)
        else:
            decision = ApprovalDecision(approved=bool(value))
    else:
        decision = ApprovalDecision(approved=True, comment="mock approval for lab")
    return {
        "approval": decision.model_dump(),
        "events": [make_event("approval", "completed", f"approved={decision.approved}")],
    }


def retry_or_fallback_node(state: AgentState) -> dict:
    """Record a retry attempt."""
    attempt = int(state.get("attempt", 0)) + 1
    error_msg = f"Retry attempt {attempt} initiated."
    return {
        "attempt": attempt,
        "errors": [error_msg],
        "events": [make_event("retry", "completed", error_msg, attempt=attempt)],
    }


def answer_node(state: AgentState) -> dict:
    """Produce a final response grounded in tool results."""
    tool_results = state.get("tool_results", [])
    if tool_results:
        latest_result = tool_results[-1]
        if "Success" in latest_result:
            answer = f"I have successfully processed your request. Details: {latest_result}"
        else:
            answer = f"There was an issue processing your request: {latest_result}"
    else:
        answer = "Your request has been processed. Is there anything else I can help you with?"
        
    return {
        "final_answer": answer,
        "events": [make_event("answer", "completed", "answer generated")],
    }


def evaluate_node(state: AgentState) -> dict:
    """Evaluate tool results — the 'done?' check that enables retry loops.

    TODO(student): replace heuristic with LLM-as-judge or structured validation.
    """
    tool_results = state.get("tool_results", [])
    latest = tool_results[-1] if tool_results else ""
    if "ERROR" in latest:
        return {
            "evaluation_result": "needs_retry",
            "events": [make_event("evaluate", "completed", "tool result indicates failure, retry needed")],
        }
    return {
        "evaluation_result": "success",
        "events": [make_event("evaluate", "completed", "tool result satisfactory")],
    }


def dead_letter_node(state: AgentState) -> dict:
    """Log unresolvable failures for manual review."""
    attempt = state.get("attempt", 0)
    msg = f"System failure: Maximum retry attempts ({attempt}) exceeded. This ticket has been escalated to a human supervisor."
    return {
        "final_answer": msg,
        "events": [make_event("dead_letter", "completed", f"max retries exceeded, attempt={attempt}")],
    }


def finalize_node(state: AgentState) -> dict:
    """Finalize the run and emit a final audit event."""
    return {"events": [make_event("finalize", "completed", "workflow finished")]}
