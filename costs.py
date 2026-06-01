"""Cost tracking for Claude API usage."""
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CostTracker:
    claude_input_tokens: int = 0
    claude_output_tokens: int = 0

    claude_input_per_1k: float = 0.003
    claude_output_per_1k: float = 0.015
    usd_to_sek: float = 10.5

    @classmethod
    def from_config(cls, cfg: dict) -> "CostTracker":
        c = cfg.get("costs", {})
        tracker = cls()
        tracker.claude_input_per_1k = c.get("claude_input_per_1k", cls.claude_input_per_1k)
        tracker.claude_output_per_1k = c.get("claude_output_per_1k", cls.claude_output_per_1k)
        tracker.usd_to_sek = c.get("usd_to_sek", cls.usd_to_sek)
        return tracker

    def add_claude(self, input_tokens: int, output_tokens: int) -> None:
        self.claude_input_tokens += input_tokens
        self.claude_output_tokens += output_tokens

    def total_usd(self) -> float:
        input_cost = (self.claude_input_tokens / 1000) * self.claude_input_per_1k
        output_cost = (self.claude_output_tokens / 1000) * self.claude_output_per_1k
        return input_cost + output_cost

    def total_sek(self) -> float:
        return self.total_usd() * self.usd_to_sek

    def summary(self) -> str:
        return (
            f"Kostnad: {self.total_usd():.4f} USD / {self.total_sek():.2f} SEK "
            f"(Claude Sonnet in={self.claude_input_tokens}, out={self.claude_output_tokens})"
        )
