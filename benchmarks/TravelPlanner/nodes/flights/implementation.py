import pandas as pd
from pandas import DataFrame
import re
from atsuite_sdk.abstract import registry

def extract_before_parenthesis(s):
    match = re.search(r'^(.*?)\([^)]*\)', s)
    return match.group(1) if match else s

class Flights:

    def __init__(self, path="./flights.csv"):
        self.path = path
        self.data = None

        self.data = pd.read_csv(self.path)[['Flight Number', 'Price', 'DepTime', 'ArrTime', 'ActualElapsedTime','FlightDate','OriginCityName','DestCityName','Distance']].dropna()
        # self.data = pd.read_csv(self.path).dropna()[['Flight Number', 'Price', 'DepTime', 'ArrTime', 'ActualElapsedTime','FlightDate','OriginCityName','DestCityName','Distance']]
        print("Flights API loaded.")

    def load_db(self):
        self.data = pd.read_csv(self.path)
        # self.data = pd.read_csv(self.path).dropna().rename(columns={'Unnamed: 0': 'Flight Number'})

    def run(self,
            origin: str,
            destination: str,
            departure_date: str,
            ) -> DataFrame:
        """Search for flights by origin, destination, and departure date."""
        results = self.data[self.data["OriginCityName"] == origin]
        results = results[results["DestCityName"] == destination]
        results = results[results["FlightDate"] == departure_date]
        if len(results) == 0:
            return "There is no flight from {} to {} on {}.".format(origin, destination, departure_date)
        return results
    
    def run_for_annotation(self,
            origin: str,
            destination: str,
            departure_date: str,
            ) -> DataFrame:
        """Search for flights by origin, destination, and departure date."""
        results = self.data[self.data["OriginCityName"] == extract_before_parenthesis(origin)]
        results = results[results["DestCityName"] == extract_before_parenthesis(destination)]
        results = results[results["FlightDate"] == departure_date]
        return results.to_string(index=False)

    def get_city_set(self):
        city_set = set()
        for unit in self.data['data']:
            city_set.add(unit[5])
            city_set.add(unit[6])


flights = Flights()

@registry.tool()
def flights_run_for_annotation(origin: str, destination: str, departure_date: str) -> DataFrame:
    """Search for flights information."""
    return flights.run_for_annotation(origin, destination, departure_date)

@registry.tool()
def flights_run(origin: str, destination: str, departure_date: str) -> DataFrame:
    """Search for flights information."""
    return flights.run(origin, destination, departure_date)