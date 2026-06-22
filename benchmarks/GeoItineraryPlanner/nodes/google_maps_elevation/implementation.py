import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import googlemaps
from dotenv import load_dotenv

from atsuite_sdk.abstract import registry


load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
if not GOOGLE_MAPS_API_KEY:
    raise EnvironmentError("GOOGLE_MAPS_API_KEY environment variable is required")

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)


class GoogleMapsElevation:
    def __init__(self, max_chars: int = 250000) -> None:
        self.max_chars = max_chars

    @staticmethod
    def _to_json_string(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False)

    def maps_elevation(self, locations: List[Dict[str, float]]) -> str:
        if not isinstance(locations, list) or len(locations) == 0:
            return self._to_json_string(
                {"isError": True, "error": "locations must be a non-empty list（迁移自 TS 版的数组校验）"}
            )

        try:
            api_locations: List[Tuple[float, float]] = []
            for loc in locations:
                if not isinstance(loc, dict) or "latitude" not in loc or "longitude" not in loc:
                    raise ValueError(f"Invalid location format: {loc}（迁移自 TS 版的坐标格式校验）")
                api_locations.append((float(loc["latitude"]), float(loc["longitude"])))

            result = gmaps.elevation(locations=api_locations)
            if not result:
                return self._to_json_string(
                    {
                        "isError": True,
                        "error": "獲取海拔數據失敗（迁移自 TS 版的错误提示）",
                        "locations": locations,
                    }
                )

            response = self._to_json_string(result)
            if len(response) > self.max_chars:
                raise ValueError(f"Response too large ({len(response)} chars), max allowed {self.max_chars}.")
            return response
        except Exception as exc:
            return self._to_json_string(
                {
                    "isError": True,
                    "error": str(exc),
                    "locations": locations,
                    "msg": "迁移自 TS 版 elevation.ts 的异常处理",
                }
            )


google_maps_elevation = GoogleMapsElevation()


@registry.tool()
def google_maps_maps_elevation(locations: List[Dict[str, float]], uid: Optional[str] = None) -> str:
    """Get elevation data (height above sea level) for specific geographic locations."""
    return google_maps_elevation.maps_elevation(locations)


__all__ = [
    "google_maps_elevation",
    "google_maps_maps_elevation",
]
