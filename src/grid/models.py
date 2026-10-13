"""Bring your own model: saved model profiles, key handling, local-only checks.

    grid models add local --model ollama/qwen3.6:27b --base-url http://localhost:11434
    grid models add work  --model anthropic/claude-opus-5-5 --key-env ANTHROPIC_API_KEY
    grid models use work            # make it the default
    grid --profile local "task"     # or pick per run

Profiles live in ~/.grid/models.json and never contain API keys. A profile
names the environment variable that holds its key (`--key-env`); with none,
LLM_API_KEY is used, and failing that LiteLLM reads the provider's own variable
(ANTHROPIC_API_KEY, OPENAI_API_KEY, ...).

Which model a run uses, first match wins:
    --model  >  --profile  >  $GRID_PROFILE  >  $LLM_MODEL  >  default profile  >  DEFAULT_MODEL

Pure Python; the SDK is imported only when an LLM is actually built.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from grid.project import grid_home

# Anthropic's recommended model for long-running agentic coding (Oct 2026).
DEFAULT_MODEL = "anthropic/claude-opus-5-5"

# Providers that, with no base_url, talk to a server on this machine.
_LOCAL_PROVIDERS = {"ollama", "ollama_chat", "lm_studio", "llamafile"}
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "host.docker.internal"}
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class ModelError(ValueError):
    pass


@dataclass
class ModelProfile:
    name: str
    model: str
    base_url: str | None = None
    api_key_env: str | None = None       # NAME of the env var holding the key, never the key
    native_tool_calling: bool = True      # False: tools described in the prompt (models without tool calling)
    note: str = ""
    compat: dict | None = None            # last `grid models test` result
    # Local (Ollama) models: reason at length before every agent step. Off by default: on a
    # laptop it can cost 5-10 minutes per step; Grid's checks catch the mistakes it would prevent.
    think: bool = False

    @property
    def provider(self) -> str:
        return self.model.split("/", 1)[0] if "/" in self.model else ""

    def is_local(self) -> bool:
        return is_local_endpoint(self.model, self.base_url)

    def validate(self) -> None:
        if not _NAME_RE.match(self.name):
            raise ModelError(f"bad profile name {self.name!r}: letters, digits, . _ - only")
        if not self.model or " " in self.model:
            raise ModelError(f"bad model id {self.model!r} (expected a litellm id like anthropic/claude-opus-5-5)")
        if self.api_key_env is not None:
            if looks_like_secret(self.api_key_env) or not _ENV_NAME_RE.match(self.api_key_env):
                raise ModelError(
                    "--key-env takes the NAME of an environment variable (e.g. ANTHROPIC_API_KEY), "
                    "not the key itself. Grid never writes keys to disk."
                )
        if self.base_url:
            parsed = urlparse(self.base_url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                raise ModelError(f"bad base URL {self.base_url!r}")


def looks_like_secret(value: str) -> bool:
    v = value.strip()
    if re.match(r"^(sk-|sk_|pk-|xai-|gsk_|AIza|hf_|ghp_|key-)", v):
        return True
    return len(v) >= 32 and not _ENV_NAME_RE.match(v)


def is_local_endpoint(model: str, base_url: str | None) -> bool:
    """True when requests stay on this machine or the local network."""
    if base_url:
        host = (urlparse(base_url).hostname or "").lower()
        if host in _LOCAL_HOSTS or host.endswith(".local") or host.endswith(".localhost"):
            return True
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        return ip.is_loopback or ip.is_private or ip.is_link_local
    provider = model.split("/", 1)[0] if "/" in model else ""
    return provider in _LOCAL_PROVIDERS


class ModelStore:
    """~/.grid/models.json: {"default": name|null, "profiles": {name: profile}}."""

    def __init__(self, path: Path | None = None):
        self.path = path or (grid_home() / "models.json")

    def _read(self) -> dict:
        if not self.path.is_file():
            return {"default": None, "profiles": {}}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ModelError(f"can't read {self.path}: {exc}") from exc
        data.setdefault("default", None)
        data.setdefault("profiles", {})
        return data

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[ModelProfile]:
        data = self._read()
        return [self._load(name, raw) for name, raw in sorted(data["profiles"].items())]

    @staticmethod
    def _load(name: str, raw: dict) -> ModelProfile:
        known = {f for f in ModelProfile.__dataclass_fields__}
        return ModelProfile(**{k: v for k, v in raw.items() if k in known} | {"name": name})

    def get(self, name: str) -> ModelProfile:
        data = self._read()
        raw = data["profiles"].get(name)
        if raw is None:
            names = ", ".join(sorted(data["profiles"])) or "none saved yet"
            raise ModelError(f"no model profile {name!r} ({names}); add one with `grid models add`")
        return self._load(name, raw)

    def default_name(self) -> str | None:
        return self._read()["default"]

    def add(self, profile: ModelProfile, *, make_default: bool = False, replace: bool = False) -> None:
        profile.validate()
        data = self._read()
        if profile.name in data["profiles"] and not replace:
            raise ModelError(f"profile {profile.name!r} exists; use --replace to overwrite it")
        raw = asdict(profile)
        raw.pop("name")
        data["profiles"][profile.name] = raw
        if make_default or data["default"] is None:
            data["default"] = profile.name
        self._write(data)

    def remove(self, name: str) -> None:
        data = self._read()
        if name not in data["profiles"]:
            raise ModelError(f"no model profile {name!r}")
        del data["profiles"][name]
        if data["default"] == name:
            data["default"] = next(iter(sorted(data["profiles"])), None)
        self._write(data)

    def set_default(self, name: str) -> None:
        self.get(name)
        data = self._read()
        data["default"] = name
        self._write(data)

    def set_think(self, name: str, on: bool) -> None:
        self.get(name)
        data = self._read()
        data["profiles"][name]["think"] = bool(on)
        self._write(data)

    def record_compat(self, name: str, result: dict) -> None:
        data = self._read()
        if name in data["profiles"]:
            data["profiles"][name]["compat"] = result
            self._write(data)


def resolve_profile(
    *,
    cli_model: str | None = None,
    cli_profile: str | None = None,
    env: dict | None = None,
    store: ModelStore | None = None,
) -> tuple[ModelProfile, str]:
    """(profile, where it came from). Ad-hoc models get a synthetic profile."""
    env = os.environ if env is None else env
    store = store or ModelStore()
    if cli_model:
        return ModelProfile(name="cli", model=cli_model, base_url=env.get("LLM_BASE_URL") or None), "--model"
    name = cli_profile or env.get("GRID_PROFILE")
    if name:
        return store.get(name), ("--profile" if cli_profile else "$GRID_PROFILE")
    if env.get("LLM_MODEL"):
        return ModelProfile(name="env", model=env["LLM_MODEL"], base_url=env.get("LLM_BASE_URL") or None), "$LLM_MODEL"
    default = store.default_name()
    if default:
        return store.get(default), "default profile"
    return ModelProfile(name="builtin", model=DEFAULT_MODEL), "built-in default"


def resolve_api_key(profile: ModelProfile, env: dict | None = None) -> str | None:
    """The key to send, or None to let LiteLLM read the provider's own variable."""
    env = os.environ if env is None else env
    if profile.api_key_env:
        value = env.get(profile.api_key_env)
        if not value:
            raise ModelError(
                f"profile {profile.name!r} reads its key from ${profile.api_key_env}, which is not set"
            )
        return value
    return env.get("LLM_API_KEY") or None


_DEFAULT_LOCAL_URLS = {
    "ollama": "http://localhost:11434", "ollama_chat": "http://localhost:11434",
    "lm_studio": "http://localhost:1234/v1", "llamafile": "http://localhost:8080/v1",
}


def endpoint_url(profile: ModelProfile) -> str | None:
    return profile.base_url or _DEFAULT_LOCAL_URLS.get(profile.provider)


def check_endpoint(profile: ModelProfile, timeout: float = 3.0) -> str | None:
    """For self-hosted models: None if the server answers, else a plain-language
    problem. Cloud providers aren't pinged (no key is sent here)."""
    import urllib.error
    import urllib.request

    url = endpoint_url(profile)
    if not url:
        return None
    try:
        urllib.request.urlopen(url, timeout=timeout)  # noqa: S310 - user-configured model server
    except urllib.error.HTTPError:
        return None  # it answered (401/404 are fine: something is listening)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        reason = getattr(exc, "reason", exc)
        hint = " Is Ollama running? (`ollama serve`)" if profile.provider.startswith("ollama") else ""
        return f"can't reach the model server at {url} ({reason}).{hint}"
    return None


def build_llm_from_profile(profile: ModelProfile, *, usage_id: str = "grid-agent", env: dict | None = None,
                           **overrides):
    """An SDK LLM for this profile. `overrides` go straight to the SDK LLM
    (the probe uses num_retries=1 so a dead server fails fast)."""
    from openhands.sdk import LLM
    from pydantic import SecretStr

    key = resolve_api_key(profile, env)
    model, base_url = profile.model, profile.base_url or None
    if profile.provider in ("ollama", "ollama_chat"):
        model, base_url, extra = ollama_llm_settings(profile)
        overrides.setdefault("litellm_extra_body", extra)
    return LLM(
        usage_id=usage_id,
        model=model,
        base_url=base_url,
        api_key=SecretStr(key) if key else None,
        native_tool_calling=profile.native_tool_calling,
        **overrides,
    )


# --- Ollama ---------------------------------------------------------------------
# Ollama's default context window (2-4k tokens) silently cuts Grid's instructions and
# tool list off, and its /api/generate route ("ollama/") fakes tool calls through the
# prompt - small models then answer with raw JSON. So Grid talks to /api/chat
# ("ollama_chat/", real tool calls), asks for a context window that fits its prompt,
# and keeps the model loaded between messages so replies don't wait for a reload.
OLLAMA_KEEP_ALIVE = "30m"
_ollama_ctx_cache: dict[tuple[str, str], int | None] = {}


def _total_ram_gb() -> float:
    try:
        return os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 2**30
    except (ValueError, OSError, AttributeError):
        return 16.0


def ollama_model_context(base_url: str, name: str, timeout: float = 2.0) -> int | None:
    """The longest context the model was trained for (from Ollama's /api/show), if known."""
    key = (base_url, name)
    if key in _ollama_ctx_cache:
        return _ollama_ctx_cache[key]
    import urllib.request

    found = None
    try:
        req = urllib.request.Request(base_url.rstrip("/") + "/api/show", data=json.dumps({"model": name}).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - the user's own model server
            info = json.loads(r.read().decode("utf-8")).get("model_info") or {}
        vals = [v for k, v in info.items() if k.endswith(".context_length") and isinstance(v, int)]
        found = max(vals) if vals else None
    except Exception:
        found = None
    _ollama_ctx_cache[key] = found
    return found


def ollama_context_size(base_url: str, name: str) -> int:
    """Big enough for Grid's prompt and a working conversation, small enough for this Mac's memory."""
    ram = _total_ram_gb()
    want = 32768 if ram >= 30 else 24576 if ram >= 15 else 16384
    limit = ollama_model_context(base_url, name)
    if limit:
        want = min(want, limit)
    return max(8192, want)


def ollama_llm_settings(profile: ModelProfile) -> tuple[str, str, dict]:
    """(litellm model id, base url, extra request fields) for an Ollama profile."""
    name = profile.model.split("/", 1)[1]
    base = profile.base_url or _DEFAULT_LOCAL_URLS["ollama"]
    extra = {"keep_alive": OLLAMA_KEEP_ALIVE, "options": {"num_ctx": ollama_context_size(base, name)},
             "think": bool(profile.think)}
    return f"ollama_chat/{name}", base, extra


def compat_summary(profile: ModelProfile) -> str:
    c = profile.compat
    if not c:
        return "untested (run `grid models test " + profile.name + "`)"
    return f"{c.get('verdict', '?')} ({c.get('tested_at', '')[:10]})"


@dataclass
class ProbeResult:
    """What `grid models test` found."""

    tool_calls: bool = False
    actions: int = 0
    risk_labeled: float = 0.0     # share of actions with a security_risk label
    confidence: float = 0.0       # share of actions with a CONFIDENCE line
    finished: bool = False
    verified: bool = False
    seconds: float = 0.0
    cost: float | None = None
    error: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        if self.error or not self.tool_calls:
            return "not-ready"
        if self.verified and self.risk_labeled >= 0.8 and self.confidence >= 0.5:
            return "ready"
        if self.verified:
            return "usable"
        return "not-ready"

    def explain(self) -> list[str]:
        out = []
        if self.error:
            out.append(f"error: {self.error}")
        if not self.tool_calls and not self.error:
            out.append("it never called a tool. Try --prompted-tools (tools described in the prompt) "
                       "or a model with tool calling.")
        if self.tool_calls and self.risk_labeled < 0.8:
            out.append(f"it labeled the risk of only {self.risk_labeled:.0%} of its actions; unlabeled "
                       "actions are UNKNOWN, so expect more prompts (and refusals when unattended).")
        if self.tool_calls and self.confidence < 0.5:
            out.append(f"it reported confidence on only {self.confidence:.0%} of actions; the "
                       "confidence gate can't help much with this model.")
        if self.tool_calls and not self.verified:
            out.append("it didn't get the probe task to a verified pass.")
        return out + self.notes

    def to_record(self) -> dict:
        import datetime as _dt

        d = asdict(self)
        d["verdict"] = self.verdict
        d["tested_at"] = _dt.datetime.now(_dt.UTC).isoformat(timespec="seconds")
        return d
