import os
import re
import json
import logging
from typing import Any, List, Dict
from langchain_core.messages import SystemMessage, HumanMessage

logger = logging.getLogger(__name__)

ACKNOWLEDGEMENTS = frozenset([
    "yes", "yeah", "yep", "yup", "sure", "okay", "ok", "alright", "sounds good",
    "go ahead", "continue", "next", "show me", "tell me more", "more",
    "thats fine", "that's fine", "do it", "proceed", "exactly", "correct", "right",
    "this one", "that one", "first one", "second one"
])

def classify_intent_heuristic(message: str) -> str:
    cleaned = message.lower().strip().rstrip('?.!')
    if cleaned in ("hello", "hi", "hey", "thanks", "thank you", "cheers"):
        return "new_retail"
    if cleaned in ACKNOWLEDGEMENTS:
        return "clarification_confirmation"
    return None

async def classify_intent(message: str, history: List[Dict[str, Any]], llm: Any, instructions: str) -> str:
    """Classifies user intent using OpenAI completions or heuristics fallback."""
    heuristic = classify_intent_heuristic(message)
    if heuristic:
        return heuristic

    if not llm or not instructions:
        return "new_retail"

    history_snippet = "\n".join(
        f"{t['role'].upper()}: {t['content']}"
        for t in history[-5:]
    )
    user_input = f"CONVERSATION HISTORY:\n{history_snippet}\n\nUSER MESSAGE: {message}"

    try:
        messages = [
            SystemMessage(content=instructions),
            HumanMessage(content=user_input)
        ]
        res = await llm.ainvoke(messages)
        label = res.content.strip().lower()
        label = re.sub(r'[^\w\-]', '', label)
        if label in ("follow_up", "clarification_confirmation", "new_retail", "new_general"):
            return label
    except Exception as e:
        logger.error(f"[Classifier] Intent classification failed: {e}")

    # Fallback to acknowledgement heuristic if failed
    cleaned = message.lower().strip().rstrip('?.!')
    if cleaned in ACKNOWLEDGEMENTS:
        return "clarification_confirmation"
    return "new_retail"


async def resolve_context(message: str, history: List[Dict[str, Any]], llm: Any, instructions: str) -> Dict[str, Any]:
    """Resolves customer conversation context dynamically using OpenAI completions."""
    cleaned_msg = message.lower().strip().rstrip('?.!')

    if not llm or not instructions:
        return {"type": "resolved_query", "query": message}

    history_snippet = "\n".join(
        f"{t['role'].upper()}: {t['content']}"
        for t in history[-5:]
    )
    user_input = f"CONVERSATION HISTORY:\n{history_snippet}\n\nUSER MESSAGE: {message}"

    try:
        messages = [
            SystemMessage(content=instructions),
            HumanMessage(content=user_input)
        ]
        res = await llm.ainvoke(messages)
        content = res.content.strip()
        
        # Strip markdown fences
        clean = re.sub(r"^```(?:json)?\n?", "", content, flags=re.IGNORECASE)
        clean = re.sub(r"\n?```$", "", clean).strip()
        
        data = json.loads(clean)
        if isinstance(data, dict) and "type" in data:
            assistant_turns = [t for t in history if t.get("role") == "assistant"]
            prev_assistant = assistant_turns[-1]["content"] if assistant_turns else ""
            prev_user = [t for t in history if t.get("role") == "user"][-1]["content"] if history else ""
            
            # Safeguard heuristics
            if data["type"] == "clarification" and " or " not in prev_assistant.lower():
                product = prev_user
                for phrase in ["is ", " in stock", " available", "check ", "have "]:
                    product = re.sub(phrase, "", product, flags=re.IGNORECASE)
                product = product.strip().rstrip('?.!')
                return {
                    "type": "resolved_query",
                    "query": f"Check the current price of {product} at the store."
                }
            
            if data["type"] == "clarification":
                if "delivery" in prev_assistant.lower() and "collect" in prev_assistant.lower():
                    return {
                        "type": "clarification",
                        "response": "To help you place your order, please could you confirm whether you'd like home delivery or Click & Collect from a store?"
                    }
                if "directions" in prev_assistant.lower() and "online" in prev_assistant.lower():
                    return {
                        "type": "clarification",
                        "response": "Would you like directions to a nearby Sainsbury's store that stocks the product, or would you prefer help with ordering online?"
                    }
                return data
            if data["type"] == "resolved_query" and "query" in data:
                return data
    except Exception as e:
        logger.error(f"[Classifier] Context resolution failed: {e}")

    # Heuristic fallback logic
    assistant_turns = [t for t in history if t.get("role") == "assistant"]
    prev_assistant = assistant_turns[-1]["content"] if assistant_turns else ""
    prev_user = [t for t in history if t.get("role") == "user"][-1]["content"] if history else ""

    if cleaned_msg in ACKNOWLEDGEMENTS and prev_assistant:
        if "or" in prev_assistant.lower():
            if "delivery or click" in prev_assistant.lower() or "home delivery or click" in prev_assistant.lower():
                return {
                    "type": "clarification",
                    "response": "To help you place your order, please could you confirm whether you'd like home delivery or Click & Collect from a store?"
                }
            if "directions" in prev_assistant.lower() and "online" in prev_assistant.lower():
                return {
                    "type": "clarification",
                    "response": "Would you like directions to a nearby Sainsbury's store that stocks the product, or would you prefer help with ordering online?"
                }
        if "price" in prev_assistant.lower() or "check the price" in prev_assistant.lower():
            product = prev_user
            for phrase in ["is ", " in stock", " available", "check ", "have "]:
                product = re.sub(phrase, "", product, flags=re.IGNORECASE)
            product = product.strip().rstrip('?.!')
            return {
                "type": "resolved_query",
                "query": f"Check the current price of {product} at the store."
            }
    
    return {
        "type": "resolved_query",
        "query": message
    }
