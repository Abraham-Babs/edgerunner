"""
prediction_engine.py — Strategy base interface and prediction container.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional


class Bet:
    def __init__(self, market: str, selection: str, stake: float, odds: float):
        self.market = market
        self.selection = selection
        self.stake = stake
        self.odds = odds

    def to_dict(self) -> Dict[str, Any]:
        return {
            "market": self.market,
            "selection": self.selection,
            "stake": self.stake,
            "odds": self.odds,
        }


class BaseFootballStrategy(ABC):
    def __init__(self, name: str, params: Optional[Dict[str, Any]] = None):
        self.name = name
        self.params = params or {}

    @abstractmethod
    def predict(self, match_info: Dict[str, Any], odds: Dict[str, Any]) -> List[Bet]:
        """
        Evaluate match information (lambdas, bins, teams) against available odds.
        Returns a list of Bet objects to place on this match.
        """
        pass


class StrategyRegistry:
    _strategies: Dict[str, BaseFootballStrategy] = {}

    @classmethod
    def register(cls, strategy: BaseFootballStrategy):
        cls._strategies[strategy.name] = strategy

    @classmethod
    def get(cls, name: str) -> Optional[BaseFootballStrategy]:
        return cls._strategies.get(name)

    @classmethod
    def list_all(cls) -> Dict[str, BaseFootballStrategy]:
        return cls._strategies
