"""Cost tracking for OpenAI API usage."""
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class CostTracker:
    gpt4o_input_tokens: int = 0
    gpt4o_output_tokens: int = 0
    embedding_tokens: int = 0

    # Prices as class attributes (per 1k tokens)
    gpt4o_input_per_1k: float = 0.005
    gpt4o_output_per_1k: float = 0.015
    embedding_per_1k: float = 0.00002
    usd_to_sek: float = 10.5

    @classmethod
    def from_config(cls, cfg: dict) -> "CostTracker":
        c = cfg.get("costs", {})
        tracker = cls()
        tracker.gpt4o_input_per_1k = c.get("gpt4o_input_per_1k", cls.gpt4o_input_per_1k)
        tracker.gpt4o_output_per_1k = c.get("gpt4o_output_per_1k", cls.gpt4o_output_per_1k)
        tracker.embedding_per_1k = c.get("embedding_per_1k", cls.embedding_per_1k)
        tracker.usd_to_sek = c.get("usd_to_sek", cls.usd_to_sek)
        return tracker

    def add_gpt4o(self, input_tokens: int, output_tokens: int) -> None:
        self.gpt4o_input_tokens += input_tokens
        self.gpt4o_output_tokens += output_tokens

    def add_embedding(self, tokens: int) -> None:
        self.embedding_tokens += tokens

    def total_usd(self) -> float:
        input_cost = (self.gpt4o_input_tokens / 1000) * self.gpt4o_input_per_1k
        output_cost = (self.gpt4o_output_tokens / 1000) * self.gpt4o_output_per_1k
        embed_cost = (self.embedding_tokens / 1000) * self.embedding_per_1k
        return input_cost + output_cost + embed_cost

    def total_sek(self) -> float:
        return self.total_usd() * self.usd_to_sek

    def summary(self) -> str:
        return (
            f"Kostnad: {self.total_usd():.4f} USD / {self.total_sek():.2f} SEK "
            f"(GPT-4o in={self.gpt4o_input_tokens}, out={self.gpt4o_output_tokens}, "
            f"embed={self.embedding_tokens})"
        )
