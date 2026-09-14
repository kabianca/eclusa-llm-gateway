"""A ceiling per request with a hard stop, and the cost recorded per call.

The stop happens *before* the call, and it is a stop, not advice. The input is
estimated from the prompt's length with a ratio that errs high; the output is
unknown before the call, so its allowance is *derived* from what the ceiling
leaves after the input, at the pinned output price, and passed to the provider
as ``max_output_tokens``. A ceiling that only checked the input would let the
output spend what it liked. What is recorded after the call is the real cost,
from the provider's usage, at the pinned prices — not an end-of-month guess.
This also protects the author's own wallet during development, which is a real
reason.
"""

from __future__ import annotations

from dataclasses import dataclass

from eclusa.service.models import PRICES, cost_usd

CHARS_PER_TOKEN = 2.5  # Portuguese runs 3.5–4 chars per token; 2.5 overestimates on purpose
MIN_OUTPUT_TOKENS = 64  # below this no valid draft fits; the call is not worth buying


class BudgetExceeded(RuntimeError):
    def __init__(self, detail: str, ceiling_usd: float) -> None:
        super().__init__(f"{detail}; ceiling US$ {ceiling_usd:.5f}")
        self.ceiling_usd = ceiling_usd


def estimate_input_tokens(*texts: str) -> int:
    return int(sum(len(t) for t in texts) / CHARS_PER_TOKEN) + 1


@dataclass(frozen=True)
class Allowance:
    input_tokens_estimate: int
    max_output_tokens: int  # what the provider is told; the output cannot exceed it
    worst_case_usd: float  # input estimate plus every allowed output token, at pinned prices


@dataclass(frozen=True)
class Budget:
    ceiling_usd: float

    def allowance(self, model: str, input_tokens_estimate: int, requested_output: int) -> Allowance:
        """How many output tokens the ceiling still buys after the input, capped by the request.

        Raises BudgetExceeded before any token is bought when the input alone does not fit
        or when what is left buys fewer output tokens than a valid draft needs.
        """
        price = PRICES[model]
        input_cost = input_tokens_estimate * price.input_per_million / 1e6
        left = self.ceiling_usd - input_cost
        if left <= 0:
            raise BudgetExceeded(
                f"input alone (~{input_tokens_estimate} tokens, US$ {input_cost:.5f}) exceeds",
                self.ceiling_usd,
            )
        affordable = int(left * 1e6 / price.output_per_million)
        max_output = min(requested_output, affordable)
        if max_output < MIN_OUTPUT_TOKENS:
            raise BudgetExceeded(
                f"only {max_output} output tokens left after the input; fewer than the "
                f"{MIN_OUTPUT_TOKENS} a draft needs",
                self.ceiling_usd,
            )
        worst = cost_usd(model, input_tokens_estimate, max_output)
        assert worst <= self.ceiling_usd + 1e-12, "the worst case is bounded by construction"
        return Allowance(input_tokens_estimate, max_output, worst)
