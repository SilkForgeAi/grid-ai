"""First-run setup: is there a model Grid can actually use, and does it answer?

The app asks `setup_status()` on start. If the model has no key (or a local
server isn't running) it walks the user through picking a provider, adding the
key and a quick check, instead of failing on the first task.

Keys are never written here: the desktop app keeps them in the Keychain and
hands them to the engine as environment variables.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from grid.models import ModelProfile, check_endpoint, resolve_profile

# Provider -> the environment variable LiteLLM reads its key from.
PROVIDER_KEY_ENV = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "groq": "GROQ_API_KEY",
    "xai": "XAI_API_KEY",
    "mistral": "MISTRAL_API_KEY",
}

# Users choose a model ID from their provider's current model list.
PROVIDERS = [
    {"id": "anthropic", "label": "Anthropic", "model": "", "prefix": "anthropic/",
     "key_env": "ANTHROPIC_API_KEY", "recommended": False,
     "keys_url": "https://console.anthropic.com/settings/keys",
     "models_url": "https://console.anthropic.com/",
     "blurb": "Choose a model from your provider account. Pay as you go."},
    {"id": "openai", "label": "OpenAI", "model": "", "prefix": "openai/", "key_env": "OPENAI_API_KEY", "recommended": True,
     "keys_url": "https://platform.openai.com/api-keys", "models_url": "https://platform.openai.com/docs/models",
     "blurb": "GPT models. Type the model id from OpenAI's list."},
    {"id": "gemini", "label": "Google Gemini", "model": "", "prefix": "gemini/", "key_env": "GEMINI_API_KEY",
     "keys_url": "https://aistudio.google.com/apikey", "models_url": "https://ai.google.dev/gemini-api/docs/models",
     "blurb": "Gemini models through Google AI Studio."},
    {"id": "openrouter", "label": "OpenRouter", "model": "", "prefix": "openrouter/", "key_env": "OPENROUTER_API_KEY",
     "keys_url": "https://openrouter.ai/keys", "models_url": "https://openrouter.ai/models",
     "blurb": "One key, hundreds of models."},
    {"id": "ollama", "label": "On this computer (Ollama)", "model": "", "prefix": "ollama_chat/", "also": ["ollama/"], "key_env": None,
     "base_url": "http://localhost:11434", "local": True, "models_url": "https://ollama.com/library",
     "blurb": "Free and private. Needs a strong machine; smaller models struggle with agent work."},
]


def key_env_for(profile: ModelProfile) -> str | None:
    if profile.api_key_env:
        return profile.api_key_env
    if profile.is_local():
        return None
    return PROVIDER_KEY_ENV.get(profile.provider)


def setup_status(env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    try:
        prof, source = resolve_profile(env=env)
    except Exception as exc:   # a broken models.json shouldn't break the app
        return {"ready": False, "chosen": False, "error": str(exc), "providers": PROVIDERS,
                "desktop": env.get("GRID_DESKTOP") == "1"}
    local = prof.is_local()
    key_env = key_env_for(prof)
    if local:
        key_present = True
    elif key_env:
        key_present = bool(env.get(key_env)) or (not prof.api_key_env and bool(env.get("LLM_API_KEY")))
    else:
        key_present = True   # unknown provider: LiteLLM may find its own variable; the check will tell
    problem = check_endpoint(prof, timeout=1.5) if local else None
    return {
        "ready": key_present and problem is None,
        "chosen": source != "built-in default",
        "model": prof.model, "profile": prof.name, "source": source, "local": local, "base_url": prof.base_url,
        "key_env": key_env, "key_present": key_present, "endpoint_problem": problem,
        "desktop": env.get("GRID_DESKTOP") == "1",
        "providers": PROVIDERS,
    }


def ollama_models(base_url: str = "http://localhost:11434", timeout: float = 2.0) -> list[str]:
    """Models installed in a local Ollama, newest first ([] if it isn't running)."""
    try:
        with urllib.request.urlopen(base_url.rstrip("/") + "/api/tags", timeout=timeout) as r:  # noqa: S310
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return []
    items = sorted(data.get("models") or [], key=lambda m: m.get("modified_at", ""), reverse=True)
    return [m["name"] for m in items if m.get("name")]


def friendly_error(exc: BaseException) -> str:
    name = type(exc).__name__
    text = str(exc)
    low = (name + " " + text).lower()
    if "authentication" in low or "401" in low or "invalid x-api-key" in low or "invalid api key" in low:
        return "The provider rejected the key. Check it was copied completely and is active."
    if "notfound" in low or "404" in low or "does not exist" in low or "model_not_found" in low:
        return "The provider doesn't know that model id. Copy the exact id from its model list."
    if "ratelimit" in low or "429" in low or "quota" in low or "credit" in low or "billing" in low:
        return "The key works, but the account is out of credit or rate-limited. Check billing on the provider's site."
    if "connection" in low or "timeout" in low or "timed out" in low:
        return "Couldn't reach the model provider. Check your internet connection (or that the local server is running)."
    return f"{name}: {text[:300]}"


def quick_check(profile: ModelProfile, *, llm=None) -> dict:
    """One tiny request to prove the model answers with this key. Costs a fraction of a cent."""
    from openhands.sdk.llm import Message, TextContent

    if llm is None:
        problem = check_endpoint(profile)
        if problem:
            return {"ok": False, "error": problem}
        from grid.models import ModelError, build_llm_from_profile

        try:
            llm = build_llm_from_profile(profile, usage_id="grid-setup-check", num_retries=0, timeout=60)
        except ModelError as exc:
            return {"ok": False, "error": str(exc)}
    try:
        resp = llm.completion([Message(role="user", content=[TextContent(text="Reply with the single word: ready")])])
    except Exception as exc:
        return {"ok": False, "error": friendly_error(exc)}
    text = "".join(getattr(c, "text", "") for c in (resp.message.content or [])).strip()
    return {"ok": True, "reply": text[:200], "model": profile.model}
