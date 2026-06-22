import pandas as pd
from pandas import DataFrame
from typing import Optional
import re
from atsuite_sdk.abstract import registry

# =============================
# Original Implementation  
# https://github.com/OSU-NLP-Group/TravelPlanner/tree/main/tools/attractions
# =============================

def extract_before_parenthesis(s):
    match = re.search(r'^(.*?)\([^)]*\)', s)
    return match.group(1) if match else s

class Attractions:
    def __init__(self, path="./attractions.csv"):
        self.path = path
        self.data = pd.read_csv(self.path)[['Name','Latitude','Longitude','Address','Phone','Website',"City"]].dropna()
        print("Attractions loaded.")

    def load_db(self):
        self.data = pd.read_csv(self.path)

    def run(self,
            city: str,
            ) -> DataFrame:
        """Search for Attractions by city."""
        mask = self.data["City"] == city
        results = self.data[mask].copy()
        # the results should show the index
        results = results.reset_index(drop=True)
        return results
      
    def run_for_annotation(self,
            city: str,
            ) -> DataFrame:
        """Search for Attractions by city for annotation."""
        mask = self.data["City"] == extract_before_parenthesis(city)
        results = self.data[mask].copy()
        # the results should show the index
        results = results.reset_index(drop=True)
        return results

# =============================
# Definitions for Agent Tools
# =============================

attractions = Attractions()
    
@registry.tool()
def attractions_run_for_annotation(city: str) -> DataFrame:
    """Search for attractions by city for annotation."""
    return attractions.run_for_annotation(city)

@registry.tool()
def attractions_run(city: str) -> DataFrame:
    """Search for attractions by city."""
    return attractions.run(city)