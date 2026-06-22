import pandas as pd
from pandas import DataFrame
from typing import Optional
import re
from atsuite_sdk.abstract import registry

# =============================
# Original Implementation  
# https://github.com/OSU-NLP-Group/TravelPlanner/tree/main/tools/restaurants
# =============================

def extract_before_parenthesis(s):
    match = re.search(r'^(.*?)\([^)]*\)', s)
    return match.group(1) if match else s

class Restaurants:
    def __init__(self, path="./clean_restaurant_2022.csv"):
        self.path = path
        self.data = pd.read_csv(self.path).dropna()[['Name','Average Cost','Cuisines','Aggregate Rating','City']]
        print("Restaurants loaded.")

    def load_db(self):
        self.data = pd.read_csv(self.path).dropna()

    def run(self,
            city: str,
            ) -> DataFrame:
        """Search for restaurant ."""
        results = self.data[self.data["City"] == city]
        # results = results[results["date"] == date]
        # if price_order == "asc":
        #     results = results.sort_values(by=["Average Cost"], ascending=True)
        # elif price_order == "desc": 
        #     results = results.sort_values(by=["Average Cost"], ascending=False)

        # if rating_order == "asc":
        #     results = results.sort_values(by=["Aggregate Rating"], ascending=True)
        # elif rating_order == "desc":
        #     results = results.sort_values(by=["Aggregate Rating"], ascending=False)
        if len(results) == 0:
            empty_df = pd.DataFrame(columns=['Name','Average Cost','Cuisines','Aggregate Rating','City'])
            return empty_df
        return results

    def run_for_annotation(self,
            city: str,
            ) -> DataFrame:
        """Search for restaurant ."""
        results = self.data[self.data["City"] == extract_before_parenthesis(city)]
        # results = results[results["date"] == date]
        # if price_order == "asc":
        #     results = results.sort_values(by=["Average Cost"], ascending=True)
        # elif price_order == "desc":
        #     results = results.sort_values(by=["Average Cost"], ascending=False)

        # if rating_order == "asc":
        #     results = results.sort_values(by=["Aggregate Rating"], ascending=True)
        # elif rating_order == "desc":
        #     results = results.sort_values(by=["Aggregate Rating"], ascending=False)

        return results

# =============================
# Definitions for Agent Tools
# =============================

restaurants = Restaurants()
    
@registry.tool()
def restaurants_run_for_annotation(city: str) -> DataFrame:
    """Search for restaurants by city for annotation."""
    return restaurants.run_for_annotation(city)

@registry.tool()
def restaurants_run(city: str) -> DataFrame:
    """Search for restaurants by city."""
    return restaurants.run(city)