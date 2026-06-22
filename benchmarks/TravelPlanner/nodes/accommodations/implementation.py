import pandas as pd
from pandas import DataFrame
from typing import Optional
import re
from atsuite_sdk.abstract import registry

# =============================
# Original Implementation
# https://github.com/OSU-NLP-Group/TravelPlanner/tree/main/tools/accommodations
# =============================

def extract_before_parenthesis(s):
    match = re.search(r'^(.*?)\([^)]*\)', s)
    return match.group(1) if match else s

class Accommodations:
    def __init__(self, path="./accommodations.csv"):
        self.path = path
        self.data = pd.read_csv(self.path).dropna()[['NAME','price','room type', 'house_rules', 'minimum nights', 'maximum occupancy', 'review rate number', 'city']]
        print("Accommodations loaded.")

    def load_db(self):
        self.data = pd.read_csv(self.path).dropna()

    def run(self,
            city: str,
            ) -> DataFrame:
        """Search for accommodations by city."""
        results = self.data[self.data["city"] == city]
        if len(results) == 0:
            return "There is no attraction in this city."
        
        return results
    
    def run_for_annotation(self,
            city: str,
            ) -> DataFrame:
        """Search for accommodations by city."""
        results = self.data[self.data["city"] == extract_before_parenthesis(city)]
        return results

# =============================
# Definitions for Agent Tools
# =============================

accommodation = Accommodations()
    
@registry.tool()
def accommodations_run_for_annotation(city: str) -> DataFrame:
    """Search for accommodations by city."""
    return accommodation.run_for_annotation(city)

@registry.tool()
def accommodations_run(city: str) -> DataFrame:
    """Search for accommodations by city."""
    return accommodation.run(city)