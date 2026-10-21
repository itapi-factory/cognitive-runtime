"""Energy rules shared by the body, simulation clock and LLM snapshots."""

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class EnergyCosts:
    capacity: float = 100
    food: float = 28
    life_per_second: float = 0.20
    thinking_per_second: float = 0.10
    sleeping_per_second: float = 0.08
    planning: float = 0.60
    sleep_start: float = 1.50
    consolidation_per_1000_tokens: float = 0.80
    action: float = 0.15
    move_per_metre: float = 0.65
    turn_per_degree: float = 0.20 / 90
    push_per_metre: float = 20.0
    speech_start: float = 0.35
    talking_per_second: float = 0.08
    speaking_per_word: float = 0.015
    listening_per_word: float = 0.005

    def per_second(self, phase: str) -> float:
        extra = {"thinking": self.thinking_per_second, "sleeping": self.sleeping_per_second,
                 "talking": self.talking_per_second}
        return self.life_per_second + extra.get(phase, 0.0)

    def consolidation_cost(self, estimated_tokens: int) -> float:
        return estimated_tokens / 1000 * self.consolidation_per_1000_tokens

    def speech_cost(self, text: str) -> float:
        return self.action + len(text.split()) * self.speaking_per_word

    def listening_cost(self, text: str) -> float:
        return len(text.split()) * self.listening_per_word

    def to_dict(self) -> dict:
        return asdict(self)


ENERGY = EnergyCosts()
