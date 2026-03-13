"""Unified AI client — routes to Gemini, Anthropic, or OpenAI based on profile settings.

All AI calls in the app go through this module so the provider is configurable.
"""

import json
import logging
from dataclasses import dataclass, field

from app_config import get_profile, get_secret

logger = logging.getLogger(__name__)

# Default models per provider
DEFAULT_MODELS = {
    "gemini": "gemini-3-flash-preview",
    "anthropic": "claude-sonnet-4-6-20250627",
    "openai": "gpt-5-mini",
}

# Secret key per provider
SECRET_KEYS = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def _get_provider_and_model() -> tuple[str, str]:
    """Read provider and model from profile, with defaults."""
    profile = get_profile()
    provider = (profile.get("ai_provider") or "gemini").strip().lower()
    if provider not in DEFAULT_MODELS:
        provider = "gemini"
    model = (profile.get("ai_model") or "").strip() or DEFAULT_MODELS[provider]
    return provider, model


def _get_api_key(provider: str) -> str:
    """Get the API key for the given provider."""
    key_name = SECRET_KEYS.get(provider, "")
    return get_secret(key_name) or "" if key_name else ""


# ---------------------------------------------------------------------------
# Simple generate — used by all ranking/summarization/editing call sites
# ---------------------------------------------------------------------------


def generate(
    system_prompt: str,
    user_message: str,
    json_mode: bool = False,
    temperature: float = 0.2,
) -> str:
    """Generate text from the configured AI provider.

    Returns raw text. Caller is responsible for JSON parsing if json_mode=True.
    Returns empty string if no API key is configured or on error.
    """
    provider, model = _get_provider_and_model()
    api_key = _get_api_key(provider)
    if not api_key:
        return ""

    try:
        if provider == "gemini":
            return _generate_gemini(api_key, model, system_prompt, user_message, json_mode, temperature)
        elif provider == "anthropic":
            return _generate_anthropic(api_key, model, system_prompt, user_message, json_mode, temperature)
        elif provider == "openai":
            return _generate_openai(api_key, model, system_prompt, user_message, json_mode, temperature)
    except Exception as e:
        logger.warning(f"AI generate ({provider}/{model}) failed: {e}")
    return ""


def _generate_gemini(
    api_key: str,
    model: str,
    system_prompt: str,
    user_message: str,
    json_mode: bool,
    temperature: float,
) -> str:
    from google import genai

    client = genai.Client(api_key=api_key)
    config: dict = {
        "system_instruction": system_prompt,
        "temperature": temperature,
    }
    if json_mode:
        config["response_mime_type"] = "application/json"

    response = client.models.generate_content(
        model=model,
        contents=user_message,
        config=config,
    )
    return response.text


def _generate_anthropic(
    api_key: str,
    model: str,
    system_prompt: str,
    user_message: str,
    json_mode: bool,
    temperature: float,
) -> str:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    sys = system_prompt
    if json_mode:
        sys += "\n\nIMPORTANT: Return ONLY valid JSON. No markdown, no explanation, just the JSON."

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=sys,
        messages=[{"role": "user", "content": user_message}],
        temperature=temperature,
    )
    return response.content[0].text


def _generate_openai(
    api_key: str,
    model: str,
    system_prompt: str,
    user_message: str,
    json_mode: bool,
    temperature: float,
) -> str:
    import openai

    client = openai.OpenAI(api_key=api_key)
    kwargs: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ],
        "temperature": temperature,
        "max_tokens": 4096,
    }
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}

    response = client.chat.completions.create(**kwargs)
    return response.choices[0].message.content or ""


# ---------------------------------------------------------------------------
# Chat with tools — used by WhatsApp agent
# ---------------------------------------------------------------------------


@dataclass
class ToolCall:
    id: str
    name: str
    input: dict


@dataclass
class ChatResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"


async def generate_chat(
    system_prompt: str,
    messages: list[dict],
    tools: list[dict] | None = None,
    temperature: float = 0.3,
) -> ChatResponse:
    """Multi-turn chat with optional tool use. Used by WhatsApp agent.

    Messages format: [{"role": "user"|"assistant", "content": str|list}, ...]
    Tools format: Anthropic-style tool definitions (name, description, input_schema).
    """
    provider, model = _get_provider_and_model()
    api_key = _get_api_key(provider)
    if not api_key:
        return ChatResponse(text="AI not configured — set an API key in Settings.")

    try:
        if provider == "gemini":
            return await _chat_gemini(api_key, model, system_prompt, messages, tools, temperature)
        elif provider == "anthropic":
            return await _chat_anthropic(api_key, model, system_prompt, messages, tools, temperature)
        elif provider == "openai":
            return await _chat_openai(api_key, model, system_prompt, messages, tools, temperature)
    except Exception as e:
        logger.exception(f"AI chat ({provider}/{model}) failed")
        return ChatResponse(text=f"AI error: {e}")

    return ChatResponse(text="Unknown AI provider.")


async def _chat_anthropic(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
    tools: list[dict] | None,
    temperature: float,
) -> ChatResponse:
    import anthropic

    client = anthropic.Anthropic(api_key=api_key)
    kwargs: dict = {
        "model": model,
        "max_tokens": 2048,
        "system": system_prompt,
        "messages": messages,
        "temperature": temperature,
    }
    if tools:
        kwargs["tools"] = tools

    response = client.messages.create(**kwargs)

    if response.stop_reason == "tool_use":
        tool_calls = []
        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append(ToolCall(id=block.id, name=block.name, input=block.input))
        # Build serializable content for history
        content = []
        for b in response.content:
            if b.type == "text":
                content.append({"type": "text", "text": b.text})
            elif b.type == "tool_use":
                content.append({"type": "tool_use", "id": b.id, "name": b.name, "input": b.input})
        return ChatResponse(text="", tool_calls=tool_calls, stop_reason="tool_use")

    text = "".join(b.text for b in response.content if hasattr(b, "text") and b.type == "text")
    return ChatResponse(text=text, stop_reason="end_turn")


async def _chat_openai(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
    tools: list[dict] | None,
    temperature: float,
) -> ChatResponse:
    import openai

    client = openai.OpenAI(api_key=api_key)

    # Convert Anthropic-style messages to OpenAI format
    oai_messages = [{"role": "system", "content": system_prompt}]
    for msg in messages:
        if msg["role"] == "user":
            content = msg["content"]
            if isinstance(content, list):
                # Tool results — convert to OpenAI format
                for item in content:
                    if item.get("type") == "tool_result":
                        oai_messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": item["tool_use_id"],
                                "content": item.get("content", ""),
                            }
                        )
                    else:
                        oai_messages.append({"role": "user", "content": json.dumps(item)})
            else:
                oai_messages.append({"role": "user", "content": content})
        elif msg["role"] == "assistant":
            content = msg["content"]
            if isinstance(content, list):
                # Assistant with tool calls
                tc = []
                text_parts = []
                for item in content:
                    if item.get("type") == "tool_use":
                        tc.append(
                            {
                                "id": item["id"],
                                "type": "function",
                                "function": {"name": item["name"], "arguments": json.dumps(item["input"])},
                            }
                        )
                    elif item.get("type") == "text":
                        text_parts.append(item["text"])
                oai_msg: dict = {"role": "assistant", "content": "\n".join(text_parts) or None}
                if tc:
                    oai_msg["tool_calls"] = tc
                oai_messages.append(oai_msg)
            else:
                oai_messages.append({"role": "assistant", "content": content})

    # Convert Anthropic-style tools to OpenAI functions
    oai_tools = None
    if tools:
        oai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                },
            }
            for t in tools
        ]

    kwargs: dict = {
        "model": model,
        "messages": oai_messages,
        "temperature": temperature,
        "max_tokens": 2048,
    }
    if oai_tools:
        kwargs["tools"] = oai_tools

    response = client.chat.completions.create(**kwargs)
    choice = response.choices[0]

    if choice.finish_reason == "tool_calls" and choice.message.tool_calls:
        tool_calls = []
        for tc in choice.message.tool_calls:
            tool_calls.append(ToolCall(id=tc.id, name=tc.function.name, input=json.loads(tc.function.arguments)))
        return ChatResponse(text=choice.message.content or "", tool_calls=tool_calls, stop_reason="tool_use")

    return ChatResponse(text=choice.message.content or "", stop_reason="end_turn")


async def _chat_gemini(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: list[dict],
    tools: list[dict] | None,
    temperature: float,
) -> ChatResponse:
    from google import genai
    from google.genai import types as genai_types

    client = genai.Client(api_key=api_key)

    # Convert messages to Gemini format using native Part types
    parts = []
    for msg in messages:
        content = msg["content"]
        if isinstance(content, str):
            role = "user" if msg["role"] == "user" else "model"
            parts.append({"role": role, "parts": [genai_types.Part.from_text(text=content)]})
        elif isinstance(content, list):
            role = "user" if msg["role"] == "user" else "model"
            gemini_parts = []
            for item in content:
                if item.get("type") == "tool_result":
                    # Extract tool name from the ID (format: "gemini_{name}")
                    tool_use_id = item.get("tool_use_id", "")
                    tool_name = tool_use_id.removeprefix("gemini_") if tool_use_id.startswith("gemini_") else tool_use_id
                    # Parse content as JSON if possible, otherwise wrap as text
                    raw = item.get("content", "")
                    try:
                        response_data = json.loads(raw) if isinstance(raw, str) else raw
                    except (json.JSONDecodeError, TypeError):
                        response_data = {"result": raw}
                    if not isinstance(response_data, dict):
                        response_data = {"result": response_data}
                    gemini_parts.append(genai_types.Part.from_function_response(name=tool_name, response=response_data))
                elif item.get("type") == "tool_use":
                    gemini_parts.append(genai_types.Part.from_function_call(name=item["name"], args=item.get("input", {})))
                elif item.get("type") == "text" and item.get("text"):
                    gemini_parts.append(genai_types.Part.from_text(text=item["text"]))
            if gemini_parts:
                parts.append({"role": role, "parts": gemini_parts})

    # For Gemini, we use function declarations if tools provided
    config: dict = {
        "system_instruction": system_prompt,
        "temperature": temperature,
    }

    tool_defs = None
    if tools:
        # Convert Anthropic-style tools to Gemini function declarations
        func_decls = []
        for t in tools:
            func_decls.append(
                {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t.get("input_schema", {"type": "object", "properties": {}}),
                }
            )
        tool_defs = [{"function_declarations": func_decls}]

    kwargs: dict = {
        "model": model,
        "contents": parts,
        "config": config,
    }
    if tool_defs:
        kwargs["config"]["tools"] = tool_defs

    response = client.models.generate_content(**kwargs)

    # Check for function calls in response
    if response.candidates and response.candidates[0].content:
        result_parts = response.candidates[0].content.parts
        tool_calls = []
        text_parts = []
        for part in result_parts:
            if hasattr(part, "function_call") and part.function_call:
                fc = part.function_call
                tool_calls.append(
                    ToolCall(
                        id=f"gemini_{fc.name}",
                        name=fc.name,
                        input=dict(fc.args) if fc.args else {},
                    )
                )
            elif hasattr(part, "text") and part.text:
                text_parts.append(part.text)

        if tool_calls:
            return ChatResponse(text="\n".join(text_parts), tool_calls=tool_calls, stop_reason="tool_use")
        return ChatResponse(text="\n".join(text_parts), stop_reason="end_turn")

    return ChatResponse(text=response.text or "", stop_reason="end_turn")
