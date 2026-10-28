"""In-process dummies. They implement ``lms.ports`` and make no external calls."""

from lms.dummies.collections_software import CollectionsSoftwareDummy
from lms.dummies.debit_order_rail import DebitOrderRailDummy, DebitOrderScenario
from lms.dummies.decision_engine import DecisionEngineDummy, DecisionScenario
from lms.dummies.enigma import EnigmaDummy

__all__ = [
    "CollectionsSoftwareDummy",
    "DebitOrderRailDummy",
    "DebitOrderScenario",
    "DecisionEngineDummy",
    "DecisionScenario",
    "EnigmaDummy",
]
