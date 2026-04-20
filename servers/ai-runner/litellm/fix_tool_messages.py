"""LiteLLM callback for the airunner01 vLLM proxy.

Three features applied to every request passing through the proxy:

1. Mistral-style message-ordering shim (async_pre_call_hook).
   Some models reject a 'tool' -> 'user' role transition. When that pattern
   appears in the incoming history, inserts a synthetic empty assistant turn
   so the ordering becomes 'tool' -> 'assistant' -> 'user'.

2. Qwen/Hermes tool-call extraction (_extract_tool_calls).
   Qwen2.5-Coder-AWQ occasionally emits tool calls in non-canonical
   wrappings: <tools>..</tools>, bare JSON, Python-literal dicts, or
   markdown code fences. The callback rewrites them into proper OpenAI
   tool_calls on the assistant message and strips the raw text from
   content so downstream agents see a clean tool_calls array.

3. Repeat-tool-call guard (_apply_repeat_guard, added 2026-04-19).
   When the model emits an identical tool call (same name + canonical
   arguments) for the (N+1)-th time in a row, the callback drops the
   tool call and returns a text message with finish_reason='stop'.
   N defaults to 3 (env var LITELLM_REPEAT_THRESHOLD; 0 disables).

   Motivation: on 2026-04-19 a Ralph+Goose run against qwen2.5-coder-32b
   at long context entered a self-feedback loop and fired the identical
   shell command 94 times in 3.5 minutes, spawning enough pnpm/node
   subprocesses to nearly destabilize the host. The guard measures
   consecutive repeats by walking backward through messages in the
   incoming request, counting assistant turns whose single tool call
   matches the current one (skipping 'tool' result turns between them);
   any non-matching turn ends the run. Ralph's per-phase goose calls use
   fresh sessions, so breaking a single turn is enough to let the loop
   reset on the next iteration.
"""

import ast
import copy
import json
import os
import re
import uuid
from typing import Any, AsyncGenerator
from litellm.integrations.custom_logger import CustomLogger


REPEAT_THRESHOLD = int(os.environ.get("LITELLM_REPEAT_THRESHOLD", "3"))

_TOOL_CALL_TAG = re.compile(r"<tool_call>\s*(.+?)\s*</tool_call>", re.DOTALL)
_TOOLS_WRAP_TAG = re.compile(r"<tools>\s*(.+?)\s*</tools>", re.DOTALL)
_FENCE = re.compile(r"```(?:json|python)?\s*(.+?)```", re.DOTALL)


def _try_parse_obj(s: str):
    """Parse a string into a dict. Tries JSON first, then Python-literal as
    fallback (handles Qwen2.5-Coder's habit of emitting single-quoted dicts)."""
    s = s.strip()
    if not s:
        return None
    for parser in (json.loads, ast.literal_eval):
        try:
            obj = parser(s)
            if isinstance(obj, dict):
                return obj
        except Exception:
            pass
    return None


def _normalize_call(obj):
    if not isinstance(obj, dict):
        return None
    if "name" not in obj or "arguments" not in obj:
        return None
    args = obj["arguments"]
    if not isinstance(args, str):
        try:
            args = json.dumps(args)
        except Exception:
            return None
    return obj["name"], args


def _balanced_object_spans(text: str):
    """Yield (start, end) of each top-level brace-balanced object,
    ignoring braces inside strings."""
    depth = 0
    start = -1
    in_str = False
    str_quote = None
    escape = False
    for i, ch in enumerate(text):
        if escape:
            escape = False
            continue
        if in_str:
            if ch == "\\":
                escape = True
            elif ch == str_quote:
                in_str = False
            continue
        if ch in ("'", '"'):
            in_str = True
            str_quote = ch
            continue
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                yield (start, i + 1)
                start = -1


def _extract_tool_calls(content):
    if not isinstance(content, str) or not content.strip():
        return [], content
    work = content

    candidates = []

    for m in _TOOL_CALL_TAG.finditer(work):
        candidates.append((m.start(), m.end(), m.group(1)))
    if candidates:
        calls = []
        for _, _, raw in sorted(candidates, key=lambda t: t[0]):
            obj = _try_parse_obj(raw)
            n = _normalize_call(obj)
            if n:
                calls.append(n)
        if calls:
            return calls, _TOOL_CALL_TAG.sub("", work).strip()
        candidates = []

    for m in _TOOLS_WRAP_TAG.finditer(work):
        candidates.append((m.start(), m.end(), m.group(1)))
    if candidates:
        calls = []
        for _, _, raw in sorted(candidates, key=lambda t: t[0]):
            obj = _try_parse_obj(raw)
            n = _normalize_call(obj)
            if n:
                calls.append(n)
        if calls:
            return calls, _TOOLS_WRAP_TAG.sub("", work).strip()
        candidates = []

    for m in _FENCE.finditer(work):
        body = m.group(1).strip()
        for s, e in _balanced_object_spans(body):
            obj = _try_parse_obj(body[s:e])
            n = _normalize_call(obj)
            if n:
                candidates.append((m.start(), m.end(), n))
    if candidates:
        calls = [n for _, _, n in candidates]
        return calls, ""

    found = []
    for s, e in _balanced_object_spans(work):
        obj = _try_parse_obj(work[s:e])
        n = _normalize_call(obj)
        if n:
            found.append(n)
    if found:
        return found, ""

    return [], content


def _make_tool_call_dict(idx, name, args):
    return {
        "index": idx,
        "id": f"call_{uuid.uuid4().hex[:24]}",
        "type": "function",
        "function": {"name": name, "arguments": args},
    }


# ---- Repeat-tool-call guard (added 2026-04-19) ----


def _canonical_args(args):
    """Normalize tool-call arguments to a canonical form for equality checks.
    Accepts JSON strings or dicts; returns a sorted-key JSON string when
    possible, else the stripped input. Whitespace and key order are ignored
    so trivially-different serializations compare equal."""
    if isinstance(args, str):
        try:
            return json.dumps(json.loads(args), sort_keys=True)
        except Exception:
            return args.strip()
    try:
        return json.dumps(args, sort_keys=True)
    except Exception:
        return str(args)


def _call_signature(name, args):
    return (name or "", _canonical_args(args))


def _msg_get(msg, key, default=None):
    """Tolerant accessor — messages may be dicts (fast path) or pydantic
    models (LiteLLM internals)."""
    if isinstance(msg, dict):
        return msg.get(key, default)
    return getattr(msg, key, default)


def _count_recent_identical_calls(messages, sig):
    """Count consecutive most-recent assistant turns whose only tool call
    matches sig. Tool-result turns ('role': 'tool') sit between an
    assistant's call and its own next turn and are skipped. Any other role,
    a non-matching call, or a multi-call assistant message ends the run."""
    count = 0
    for msg in reversed(messages or []):
        role = _msg_get(msg, "role")
        if role == "tool":
            continue
        if role != "assistant":
            break
        tcs = _msg_get(msg, "tool_calls") or []
        if len(tcs) != 1:
            break
        tc = tcs[0]
        fn = _msg_get(tc, "function") or {}
        prev_name = (
            fn.get("name") if isinstance(fn, dict) else getattr(fn, "name", None)
        )
        prev_args = (
            fn.get("arguments")
            if isinstance(fn, dict)
            else getattr(fn, "arguments", "")
        )
        if _call_signature(prev_name, prev_args) != sig:
            break
        count += 1
    return count


_GUARD_TEMPLATE = (
    "[tool-call guard] The tool '{name}' has been called with identical "
    "arguments {n} times in a row. This is a repetition loop — the call "
    "is not making progress and has been blocked to protect the host. "
    "Inspect the prior tool output, choose a different approach, or call "
    "a different tool. Do not repeat the same command."
)


def _apply_repeat_guard(messages, calls):
    """Returns (blocked: bool, text: Optional[str]).

    If the first call in `calls` is the (REPEAT_THRESHOLD + 1)-th
    consecutive identical call relative to the messages history, returns
    (True, guard_text) and the caller should drop the tool_calls, set
    content=text, and finish_reason='stop'. Otherwise returns
    (False, None)."""
    if REPEAT_THRESHOLD <= 0 or not calls:
        return False, None
    name, args = calls[0]
    sig = _call_signature(name, args)
    prior = _count_recent_identical_calls(messages, sig)
    if prior < REPEAT_THRESHOLD:
        return False, None
    current_total = prior + 1
    text = _GUARD_TEMPLATE.format(name=name, n=current_total)
    print(
        f"[fix_tool_messages] repeat-guard fired: tool={name!r} "
        f"repeats={current_total} threshold={REPEAT_THRESHOLD}",
        flush=True,
    )
    return True, text


class ToolMessageFixer(CustomLogger):
    """Mistral ordering shim + Qwen non-canonical tool-call extraction +
    repeat-tool-call guard. See module docstring for details."""

    async def async_pre_call_hook(self, user_api_key_dict, cache, data, call_type):
        messages = data.get("messages", [])
        if not messages:
            return data
        fixed = []
        for i, msg in enumerate(messages):
            fixed.append(msg)
            if (
                _msg_get(msg, "role") == "tool"
                and i + 1 < len(messages)
                and _msg_get(messages[i + 1], "role") == "user"
            ):
                fixed.append({"role": "assistant", "content": "..."})
        data["messages"] = fixed
        return data

    async def async_post_call_success_hook(self, data, user_api_key_dict, response):
        try:
            choices = response.choices
        except AttributeError:
            return response
        messages = (data or {}).get("messages") if isinstance(data, dict) else None
        for choice in choices:
            msg = getattr(choice, "message", None)
            if msg is None:
                continue

            existing_tcs = getattr(msg, "tool_calls", None)
            if existing_tcs:
                # Model emitted tool_calls natively — still guard for repeats.
                native_calls = []
                for tc in existing_tcs:
                    fn = getattr(tc, "function", None)
                    name = None
                    args = ""
                    if fn is not None:
                        name = (
                            getattr(fn, "name", None)
                            if not isinstance(fn, dict)
                            else fn.get("name")
                        )
                        args = (
                            getattr(fn, "arguments", "")
                            if not isinstance(fn, dict)
                            else fn.get("arguments", "")
                        )
                    native_calls.append((name, args))
                blocked, text = _apply_repeat_guard(messages, native_calls)
                if blocked:
                    msg.tool_calls = None
                    msg.content = text
                    try:
                        choice.finish_reason = "stop"
                    except Exception:
                        pass
                continue

            content = getattr(msg, "content", None)
            calls, cleaned = _extract_tool_calls(content)
            if not calls:
                continue

            blocked, text = _apply_repeat_guard(messages, calls)
            if blocked:
                msg.content = text
                try:
                    choice.finish_reason = "stop"
                except Exception:
                    pass
                continue

            msg.tool_calls = [
                _make_tool_call_dict(i, n, a) for i, (n, a) in enumerate(calls)
            ]
            msg.content = cleaned or None
            try:
                choice.finish_reason = "tool_calls"
            except Exception:
                pass
        return response

    async def async_post_call_streaming_iterator_hook(
        self, user_api_key_dict, response, request_data
    ) -> AsyncGenerator[Any, None]:
        chunks = []
        async for chunk in response:
            chunks.append(chunk)

        content_parts = []
        native_by_idx: dict = {}
        for c in chunks:
            try:
                for choice in c.choices:
                    delta = getattr(choice, "delta", None)
                    if delta is None:
                        continue
                    text = getattr(delta, "content", None)
                    if text:
                        content_parts.append(text)
                    for tc in getattr(delta, "tool_calls", None) or []:
                        idx = getattr(tc, "index", None)
                        if idx is None:
                            continue
                        fn = getattr(tc, "function", None)
                        name = None
                        args = ""
                        if fn is not None:
                            name = (
                                getattr(fn, "name", None)
                                if not isinstance(fn, dict)
                                else fn.get("name")
                            )
                            args = (
                                getattr(fn, "arguments", "")
                                if not isinstance(fn, dict)
                                else fn.get("arguments", "")
                            )
                        entry = native_by_idx.setdefault(
                            idx, {"name": None, "args": ""}
                        )
                        if name:
                            entry["name"] = name
                        if args:
                            entry["args"] = entry["args"] + args
            except Exception:
                pass

        full = "".join(content_parts)
        parsed_calls, _cleaned = _extract_tool_calls(full)
        messages = (
            (request_data or {}).get("messages")
            if isinstance(request_data, dict)
            else None
        )

        def build_stop(text):
            if not chunks:
                return []
            c0 = copy.deepcopy(chunks[0])
            for choice in c0.choices:
                d = getattr(choice, "delta", None)
                if d is not None:
                    d.role = "assistant"
                    d.content = text
                    d.tool_calls = []
                choice.finish_reason = "stop"
            return [c0]

        # Case 1: non-canonical tool call embedded in content — synthesize a stream.
        if parsed_calls:
            blocked, text = _apply_repeat_guard(messages, parsed_calls)
            if blocked:
                for c in build_stop(text):
                    yield c
                return
            template = chunks[0]
            c0 = copy.deepcopy(template)
            for choice in c0.choices:
                d = getattr(choice, "delta", None)
                if d is not None:
                    d.content = None
                    d.role = "assistant"
                    d.tool_calls = []
                choice.finish_reason = None
            yield c0
            for idx, (name, args) in enumerate(parsed_calls):
                cN = copy.deepcopy(template)
                for choice in cN.choices:
                    d = getattr(choice, "delta", None)
                    if d is not None:
                        d.content = None
                        d.role = None
                        d.tool_calls = [_make_tool_call_dict(idx, name, args)]
                    choice.finish_reason = None
                yield cN
            final = copy.deepcopy(chunks[-1])
            for choice in final.choices:
                d = getattr(choice, "delta", None)
                if d is not None:
                    d.content = None
                    d.role = None
                    d.tool_calls = []
                choice.finish_reason = "tool_calls"
            yield final
            return

        # Case 2: native streaming tool_calls — guard, pass through if clean.
        if native_by_idx:
            assembled = [
                (native_by_idx[k]["name"], native_by_idx[k]["args"])
                for k in sorted(native_by_idx.keys())
            ]
            blocked, text = _apply_repeat_guard(messages, assembled)
            if blocked:
                for c in build_stop(text):
                    yield c
                return

        # Case 3 (and non-blocked Case 2): pass through.
        for c in chunks:
            yield c


tool_message_fixer = ToolMessageFixer()
