from typing import Dict, List
from atsuite_sdk.abstract import registry

# =============================
# Original Implementation
# =============================

class Cities:
    def __init__(self, path="./citySet_with_states.txt") -> None:
        self.path = path
        self.load_data()
        print("Cities loaded.")

    def load_data(self):
        cityStateMapping = open(self.path, "r").read().strip().split("\n")
        self.data = {}
        for unit in cityStateMapping:
            city, state = unit.split("\t")
            if state not in self.data:
                self.data[state] = [city]
            else:
                self.data[state].append(city)
    
    def run(self, state: str) -> Dict[str, List[str]]:
        if state not in self.data:
            return {"cities": []}
        else:
            return {"cities": self.data[state]}

# =============================
# Definitions for Agent Tools
# =============================

cities = Cities()
    
@registry.tool()
def cities_run(state: str) -> Dict[str, List[str]]:
    """Get cities in a given state."""
    return cities.run(state)
