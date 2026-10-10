"""The generation provider behind a thin interface, with recorded responses as the default.

The suite must be incapable of calling a paid API by accident. So the default
provider replays recordings, and it is the only provider that exists unless two
things are true at once: ``ECLUSA_LIVE=1`` is set and an API key is present.
The live client is imported and constructed only then; the SDK is not even a
core dependency. If ``pytest`` alone could cost money, the design is wrong, not
the permission.

Recordings, three rules. The key includes the retrieved context — the chunk ids
and the full prompt — not only model, template and parameters; keyed on the
prompt alone, a change in retrieval would silently reuse a recording made with
a different context and the evaluation would stay green while the system
changed. A miss fails loud and says how to re-record; it never falls through to
a live call. Every recording stores the model identifier and the date it was
made, so the drift monitor can say how old the recordings are.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Protocol

from eclusa.service.models import GENERATION_MODEL

LIVE_FLAG = "ECLUSA_LIVE"
API_KEY = "OPENAI_API_KEY"


@dataclass(frozen=True)
class CompletionRequest:
    model: str
    prompt_version: str
    instructions: str  # the system prompt, as rendered
    input: str  # the user turn: question plus the retrieved passages, as rendered
    context_ids: tuple[str, ...]  # chunk ids retrieved for this request
    max_output_tokens: int
    temperature: float = 0.0
    json_schema: dict[str, Any] | None = None  # the contract's Draft schema, when enforced

    def key(self) -> str:
        """sha256 of everything that could change the completion — context included."""
        canonical = json.dumps(
            asdict(self), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Completion:
    text: str
    model: str  # the model that actually answered, as reported by the provider
    input_tokens: int
    output_tokens: int
    recorded_at: date | None = None  # when replayed: the day the recording was made
    live: bool = False


class Provider(Protocol):
    model: str

    def complete(self, request: CompletionRequest) -> Completion: ...


class RecordingMissing(LookupError):
    """No recording for this request. Never silently answered live."""


@dataclass
class RecordedProvider:
    """Replays recordings from a JSONL cassette. The default, and the only one the gate knows."""

    path: Path
    model: str = GENERATION_MODEL
    _entries: dict[str, dict[str, Any]] = field(default_factory=dict, init=False, repr=False)

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        if self.path.exists():
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        entry = json.loads(line)
                        self._entries[entry["key"]] = entry

    def __len__(self) -> int:
        return len(self._entries)

    def complete(self, request: CompletionRequest) -> Completion:
        entry = self._entries.get(request.key())
        if entry is None:
            raise RecordingMissing(
                f"no recording for prompt {request.prompt_version!r}, key {request.key()[:12]}… "
                f"in {self.path}. Recorded mode never calls the model. To record on purpose: "
                f"set {LIVE_FLAG}=1 and {API_KEY}, and run the recorder for this case."
            )
        return Completion(
            text=entry["text"],
            model=entry["model"],
            input_tokens=entry["input_tokens"],
            output_tokens=entry["output_tokens"],
            recorded_at=date.fromisoformat(entry["recorded_at"]),
        )

    def recorded_dates(self) -> list[date]:
        return sorted({date.fromisoformat(e["recorded_at"]) for e in self._entries.values()})


@dataclass
class RecordingProvider:
    """Wraps a live provider and appends every completion to the cassette."""

    inner: Provider
    path: Path
    today: date

    @property
    def model(self) -> str:
        return self.inner.model

    def complete(self, request: CompletionRequest) -> Completion:
        completion = self.inner.complete(request)
        entry = {
            "key": request.key(),
            "prompt_version": request.prompt_version,
            "model": completion.model,
            "recorded_at": self.today.isoformat(),
            "input_tokens": completion.input_tokens,
            "output_tokens": completion.output_tokens,
            "text": completion.text,
            "context_ids": list(request.context_ids),
        }
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        return completion


class OpenAIProvider:
    """The live client. Constructed only by ``provider_from_env`` with the flag and the key set.

    The SDK is imported here and nowhere else, so that the recorded path never loads it.
    API shape verified against openai 3.13.0: ``responses.create`` with ``instructions``,
    ``input``, ``max_output_tokens``, ``temperature`` and ``text.format`` for a JSON schema;
    usage in ``response.usage.input_tokens`` / ``output_tokens``.
    """

    def __init__(self, model: str = GENERATION_MODEL, client: Any | None = None) -> None:
        self.model = model
        if client is None:
            from openai import OpenAI  # lazy: never imported in recorded mode

            client = OpenAI(api_key=os.environ[API_KEY], max_retries=2, timeout=60.0)
        self._client = client

    def complete(self, request: CompletionRequest) -> Completion:
        kwargs: dict[str, Any] = {
            "model": request.model,
            "instructions": request.instructions,
            "input": request.input,
            "max_output_tokens": request.max_output_tokens,
            "temperature": request.temperature,
            "store": False,
        }
        if request.json_schema is not None:
            kwargs["text"] = {
                "format": {
                    "type": "json_schema",
                    "name": "eclusa_draft",
                    "schema": request.json_schema,
                    "strict": True,
                }
            }
        response = self._client.responses.create(**kwargs)
        return Completion(
            text=response.output_text,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
            live=True,
        )


def live_enabled(environ: dict[str, str] | None = None) -> bool:
    env = os.environ if environ is None else environ
    return env.get(LIVE_FLAG) == "1"


def provider_from_env(
    cassette: Path,
    environ: dict[str, str] | None = None,
    today: date | None = None,
) -> Provider:
    """Recorded unless explicitly live. Live records what it gets, so the cassette grows."""
    env = os.environ if environ is None else environ
    if not live_enabled(env):
        return RecordedProvider(cassette)
    if not env.get(API_KEY):
        raise RuntimeError(f"{LIVE_FLAG}=1 but {API_KEY} is not set; refusing to guess")
    return RecordingProvider(OpenAIProvider(), cassette, today or date.today())
