"""High-performance Google Gemini AI client with connection pooling, fast timeouts,
automatic model failover, and real-time token quota tracking.

Optimized for ultra-low latency resume screening and JD decomposition.
"""

import datetime
import json
import logging
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger("talentmatch.ai_client")

# Thread-safe client cache
_client_lock = threading.Lock()
_cached_client: Optional[Any] = None
_cached_api_key: Optional[str] = None

# Model latency hierarchy (fastest first)
RECOMMENDED_FAST_MODEL = "gemini-3.1-flash-lite"
BACKUP_FAST_MODEL = "gemini-3.5-flash"

AVAILABLE_MODELS = [
    "gemini-3.1-flash-lite",  # Ultra-fast (~3s response)
    "gemini-3.5-flash",       # High-speed balanced (~3.5s response)
    "gemini-3.8-flash",       # Advanced reasoning
    "gemini-flash-latest",
]


def reset_cached_client() -> None:
    """Reset cached GenAI client to force re-initialization with new credentials."""
    global _cached_client, _cached_api_key
    with _client_lock:
        _cached_client = None
        _cached_api_key = None


def get_genai_client(api_key: Optional[str] = None) -> Optional[Any]:
    """Get or create a cached, thread-safe Google GenAI client with optimized HTTP options.

    Configured with a 35-second deadline and minimal retry backoff to avoid hanging.

    Args:
        api_key: Optional API key. If not provided, retrieved from settings.

    Returns:
        google.genai.Client instance or None if no valid key is available.
    """
    global _cached_client, _cached_api_key

    if not api_key:
        from config.settings import get_settings
        api_key = get_settings().get_api_key()

    from config.settings import clean_api_key
    api_key = clean_api_key(api_key)

    if not api_key:
        return None

    with _client_lock:
        if _cached_client is not None and _cached_api_key == api_key:
            return _cached_client

        try:
            from google import genai
            from google.genai import types

            # 35s deadline for complex decompositions, 2 retry attempts with fast backoff
            http_options = types.HttpOptions(
                timeout=35000,
                retry_options=types.HttpRetryOptions(
                    attempts=2,
                    initial_delay=0.5,
                    max_delay=2.0,
                ),
            )
            client = genai.Client(api_key=api_key, http_options=http_options)
            _cached_client = client
            _cached_api_key = api_key
            logger.info("Initialized high-speed GenAI client singleton.")
            return client
        except Exception as exc:
            logger.error("Failed to initialize GenAI client: %s", exc)
            return None


def clean_json_response(raw_text: str) -> str:
    """Clean markdown code block markers from an LLM response string."""
    cleaned = (raw_text or "").strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return cleaned.strip()


def safe_parse_json(raw_text: str) -> Optional[Any]:
    """Parse JSON with multiple fallback strategies for truncated or malformed LLM outputs.

    Handles:
    1. Markdown code fences (```json ... ```)
    2. Valid standard JSON
    3. Truncated JSON arrays by recovering all fully formed JSON objects
    4. Truncated JSON objects by repairing unclosed quotes and braces

    Args:
        raw_text: Raw string returned from LLM.

    Returns:
        Parsed dict, list, or None if unrecoverable.
    """
    if not raw_text:
        return None

    cleaned = clean_json_response(raw_text)
    if not cleaned:
        return None

    # Strategy 1: Standard json.loads
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # Strategy 2: If starts with an array, extract all complete JSON objects
    if cleaned.lstrip().startswith("["):
        try:
            decoder = json.JSONDecoder()
            items = []
            idx = 0
            length = len(cleaned)
            while idx < length:
                b = cleaned.find("{", idx)
                if b == -1:
                    break
                try:
                    obj, end_pos = decoder.raw_decode(cleaned[b:])
                    items.append(obj)
                    idx = b + end_pos
                except Exception:
                    idx = b + 1
            if items:
                logger.info("Successfully recovered %d objects from truncated JSON array.", len(items))
                return items
        except Exception:
            pass

    # Strategy 3: Attempt bracket/quote balancing for truncated objects or arrays
    try:
        candidate = cleaned.strip()
        unescaped_quotes = len(re.findall(r'(?<!\\)"', candidate))
        if unescaped_quotes % 2 != 0:
            candidate += '"'

        open_curly = candidate.count("{") - candidate.count("}")
        open_square = candidate.count("[") - candidate.count("]")
        if open_curly > 0:
            candidate += "}" * open_curly
        if open_square > 0:
            candidate += "]" * open_square

        return json.loads(candidate)
    except Exception:
        pass

    return None


# ---------------------------------------------------------------------------
# Real-Time Token & Quota Tracking System
# ---------------------------------------------------------------------------
_usage_lock = threading.Lock()
_usage_cache: Dict[str, Any] = {
    "date": "",
    "plan_tier": "free",
    "requests_today": 0,
    "prompt_tokens_today": 0,
    "candidates_tokens_today": 0,
    "total_tokens_today": 0,
    "last_call": {},
    "initialized": False,
}


def _get_utc_today() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")


def _init_usage_cache_if_needed() -> None:
    """Load persisted usage metrics from the database on initial start."""
    global _usage_cache
    if _usage_cache.get("initialized"):
        return

    today_str = _get_utc_today()
    try:
        from database.connection import get_session
        from database.models import ApplicationSetting
        from sqlalchemy import select

        with get_session() as session:
            rows = session.scalars(
                select(ApplicationSetting).where(
                    ApplicationSetting.key.in_([
                        "gemini_usage_date",
                        "gemini_requests_today",
                        "gemini_prompt_tokens_today",
                        "gemini_candidates_tokens_today",
                        "gemini_total_tokens_today",
                        "gemini_plan_tier",
                        "gemini_last_call_json",
                    ])
                )
            ).all()
            settings_map = {r.key: r.value for r in rows}

            db_date = settings_map.get("gemini_usage_date", "")
            plan_tier = settings_map.get("gemini_plan_tier", "free") or "free"

            if db_date == today_str:
                _usage_cache["date"] = today_str
                _usage_cache["plan_tier"] = plan_tier
                _usage_cache["requests_today"] = int(settings_map.get("gemini_requests_today", "0") or 0)
                _usage_cache["prompt_tokens_today"] = int(settings_map.get("gemini_prompt_tokens_today", "0") or 0)
                _usage_cache["candidates_tokens_today"] = int(settings_map.get("gemini_candidates_tokens_today", "0") or 0)
                _usage_cache["total_tokens_today"] = int(settings_map.get("gemini_total_tokens_today", "0") or 0)
                last_call_raw = settings_map.get("gemini_last_call_json", "")
                if last_call_raw:
                    try:
                        _usage_cache["last_call"] = json.loads(last_call_raw)
                    except Exception:
                        _usage_cache["last_call"] = {}
            else:
                _usage_cache["date"] = today_str
                _usage_cache["plan_tier"] = plan_tier
                _usage_cache["requests_today"] = 0
                _usage_cache["prompt_tokens_today"] = 0
                _usage_cache["candidates_tokens_today"] = 0
                _usage_cache["total_tokens_today"] = 0
                _usage_cache["last_call"] = {}

            _usage_cache["initialized"] = True
    except Exception as exc:
        logger.debug("Could not load usage metrics from database (%s); using in-memory tracker.", exc)
        _usage_cache["date"] = today_str
        _usage_cache["initialized"] = True


def record_token_usage(
    prompt_tokens: int = 0,
    candidates_tokens: int = 0,
    total_tokens: int = 0,
    latency_ms: int = 0,
    model: str = "",
) -> None:
    """Record token consumption and request count from an API call."""
    with _usage_lock:
        _init_usage_cache_if_needed()
        today_str = _get_utc_today()

        if _usage_cache["date"] != today_str:
            _usage_cache["date"] = today_str
            _usage_cache["requests_today"] = 0
            _usage_cache["prompt_tokens_today"] = 0
            _usage_cache["candidates_tokens_today"] = 0
            _usage_cache["total_tokens_today"] = 0

        tot = total_tokens or (prompt_tokens + candidates_tokens)
        _usage_cache["requests_today"] += 1
        _usage_cache["prompt_tokens_today"] += max(0, prompt_tokens)
        _usage_cache["candidates_tokens_today"] += max(0, candidates_tokens)
        _usage_cache["total_tokens_today"] += max(0, tot)

        last_call_info = {
            "timestamp": datetime.datetime.utcnow().strftime("%H:%M:%S UTC"),
            "model": model,
            "latency_ms": latency_ms,
            "prompt_tokens": max(0, prompt_tokens),
            "candidates_tokens": max(0, candidates_tokens),
            "total_tokens": max(0, tot),
        }
        _usage_cache["last_call"] = last_call_info

        try:
            from database.connection import get_session
            from database.models import ApplicationSetting
            from sqlalchemy import select

            with get_session() as session:
                def _upsert(key: str, val: str):
                    row = session.scalar(select(ApplicationSetting).where(ApplicationSetting.key == key))
                    if row:
                        row.value = val
                        row.updated_at = datetime.datetime.utcnow()
                    else:
                        session.add(ApplicationSetting(key=key, value=val))

                _upsert("gemini_usage_date", today_str)
                _upsert("gemini_requests_today", str(_usage_cache["requests_today"]))
                _upsert("gemini_prompt_tokens_today", str(_usage_cache["prompt_tokens_today"]))
                _upsert("gemini_candidates_tokens_today", str(_usage_cache["candidates_tokens_today"]))
                _upsert("gemini_total_tokens_today", str(_usage_cache["total_tokens_today"]))
                _upsert("gemini_last_call_json", json.dumps(last_call_info))
        except Exception as exc:
            logger.debug("Failed to persist usage metrics to DB: %s", exc)


def get_token_usage_stats() -> Dict[str, Any]:
    """Retrieve current token usage, quota limits, and remaining capacity."""
    with _usage_lock:
        _init_usage_cache_if_needed()
        today_str = _get_utc_today()

        if _usage_cache["date"] != today_str:
            _usage_cache["date"] = today_str
            _usage_cache["requests_today"] = 0
            _usage_cache["prompt_tokens_today"] = 0
            _usage_cache["candidates_tokens_today"] = 0
            _usage_cache["total_tokens_today"] = 0

        now_utc = datetime.datetime.utcnow()
        midnight_utc = datetime.datetime.combine(now_utc.date() + datetime.timedelta(days=1), datetime.time.min)
        time_to_reset = midnight_utc - now_utc
        hours = time_to_reset.seconds // 3600
        mins = (time_to_reset.seconds % 3600) // 60

        from config.settings import get_settings
        active_model = get_settings().get_model()

        plan_tier = _usage_cache.get("plan_tier", "free") or "free"
        reqs_used = _usage_cache.get("requests_today", 0)

        daily_limit = 1500 if plan_tier == "free" else None
        rpm_limit = 15 if plan_tier == "free" else 1000
        tpm_limit = 1000000 if plan_tier == "free" else 4000000

        if plan_tier == "free":
            reqs_remaining: Any = max(0, 1500 - reqs_used)
            used_pct = min(100.0, round((reqs_used / 1500.0) * 100, 1))
        else:
            reqs_remaining = "Unlimited"
            used_pct = 0.0

        return {
            "date": today_str,
            "plan_tier": plan_tier,
            "active_model": active_model,
            "requests_used": reqs_used,
            "daily_request_limit": daily_limit,
            "requests_remaining": reqs_remaining,
            "requests_used_pct": used_pct,
            "rpm_limit": rpm_limit,
            "tpm_limit": tpm_limit,
            "context_window": 1048576,
            "max_output_tokens": 8192,
            "prompt_tokens_today": _usage_cache.get("prompt_tokens_today", 0),
            "candidates_tokens_today": _usage_cache.get("candidates_tokens_today", 0),
            "total_tokens_today": _usage_cache.get("total_tokens_today", 0),
            "last_call": _usage_cache.get("last_call", {}),
            "reset_countdown": f"{hours}h {mins}m",
        }


def set_plan_tier(tier: str) -> None:
    """Update active plan tier ('free' or 'paid')."""
    normalized = "paid" if "paid" in tier.lower() or "pay" in tier.lower() else "free"
    with _usage_lock:
        _usage_cache["plan_tier"] = normalized
        try:
            from database.connection import get_session
            from database.models import ApplicationSetting
            from sqlalchemy import select

            with get_session() as session:
                row = session.scalar(select(ApplicationSetting).where(ApplicationSetting.key == "gemini_plan_tier"))
                if row:
                    row.value = normalized
                else:
                    session.add(ApplicationSetting(key="gemini_plan_tier", value=normalized))
        except Exception:
            pass


def reset_token_usage_stats() -> None:
    """Reset the daily token usage counters."""
    with _usage_lock:
        today_str = _get_utc_today()
        _usage_cache["date"] = today_str
        _usage_cache["requests_today"] = 0
        _usage_cache["prompt_tokens_today"] = 0
        _usage_cache["candidates_tokens_today"] = 0
        _usage_cache["total_tokens_today"] = 0
        _usage_cache["last_call"] = {}

        try:
            from database.connection import get_session
            from database.models import ApplicationSetting
            from sqlalchemy import select

            with get_session() as session:
                for k in [
                    "gemini_requests_today",
                    "gemini_prompt_tokens_today",
                    "gemini_candidates_tokens_today",
                    "gemini_total_tokens_today",
                    "gemini_last_call_json",
                ]:
                    row = session.scalar(select(ApplicationSetting).where(ApplicationSetting.key == k))
                    if row:
                        row.value = "0" if "json" not in k else "{}"
        except Exception:
            pass


def generate_fast_ai_content(
    prompt: str,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    max_output_tokens: int = 1000,
    temperature: float = 0.1,
    json_mode: bool = True,
) -> Optional[str]:
    """Execute an optimized, fast LLM generation call with automatic fallback and token tracking.

    Args:
        prompt: The input prompt.
        model: Target model name. Defaults to settings or RECOMMENDED_FAST_MODEL.
        api_key: Optional API key override.
        max_output_tokens: Token generation limit to prevent slow unbounded generation.
        temperature: Low temperature for deterministic, consistent evaluations.
        json_mode: Whether to enforce JSON response mime type.

    Returns:
        Cleaned response text or None if generation failed.
    """
    client = get_genai_client(api_key)
    if not client:
        return None

    from config.settings import get_settings
    primary_model = model or get_settings().get_model()

    candidate_models: List[str] = []
    if primary_model:
        candidate_models.append(primary_model)
    if RECOMMENDED_FAST_MODEL not in candidate_models:
        candidate_models.append(RECOMMENDED_FAST_MODEL)
    if BACKUP_FAST_MODEL not in candidate_models:
        candidate_models.append(BACKUP_FAST_MODEL)

    from google.genai import types

    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
    )
    if json_mode:
        config.response_mime_type = "application/json"

    for candidate_model in candidate_models:
        try:
            logger.debug("Requesting AI generation from model '%s'...", candidate_model)
            t0 = time.perf_counter()
            response = client.models.generate_content(
                model=candidate_model,
                contents=prompt,
                config=config,
            )
            latency_ms = int((time.perf_counter() - t0) * 1000)

            # Record token usage metadata
            prompt_tok = 0
            cand_tok = 0
            tot_tok = 0
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                prompt_tok = getattr(response.usage_metadata, "prompt_token_count", 0) or 0
                cand_tok = getattr(response.usage_metadata, "candidates_token_count", 0) or 0
                tot_tok = getattr(response.usage_metadata, "total_token_count", 0) or (prompt_tok + cand_tok)

            record_token_usage(
                prompt_tokens=prompt_tok,
                candidates_tokens=cand_tok,
                total_tokens=tot_tok,
                latency_ms=latency_ms,
                model=candidate_model,
            )

            raw_text = clean_json_response(response.text or "")
            if raw_text:
                return raw_text
        except Exception as exc:
            logger.warning(
                "Model '%s' failed (%s); trying fallback if available...",
                candidate_model,
                exc,
            )

    return None
