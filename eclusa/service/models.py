"""The generation model, pinned in exactly one place, and what its tokens cost.

Generation is not a local model on purpose: a budget and a cost per request only
mean something when the token costs money. The identifier is a dated snapshot,
never an alias — an alias moves without notice, and every audit record carries
this string so that a change is visible in the trail.

Prices are per million tokens, USD, standard tier, as read on the OpenAI pricing
page on 2026-09-14. They are inputs to the budget's hard stop and to the cost
recorded per call; when they change, this is the one place to change them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

GENERATION_MODEL = "gpt-5.4-mini-2026-03-17"

DATED = re.compile(r"-\d{4}-\d{2}-\d{2}$")


@dataclass(frozen=True)
class Price:
    input_per_million: float
    output_per_million: float


PRICES: dict[str, Price] = {
    "gpt-5.4-mini-2026-03-17": Price(0.75, 4.50),
    "gpt-5.4-nano-2026-03-17": Price(0.20, 1.25),
    "gpt-5-mini-2025-08-07": Price(0.25, 2.00),
    "gpt-4.1-mini-2025-04-14": Price(0.40, 1.60),
}


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    price = PRICES[model]  # an unknown model is an error, not a free call
    return (input_tokens * price.input_per_million + output_tokens * price.output_per_million) / 1e6
