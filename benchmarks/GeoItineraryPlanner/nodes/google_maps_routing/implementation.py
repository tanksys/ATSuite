import json
import os
from datetime import datetime
from pathlib import Path
from typing import Any, List, Optional

import googlemaps
from dotenv import load_dotenv

from atsuite_sdk.abstract import registry


load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
if not GOOGLE_MAPS_API_KEY:
    raise EnvironmentError("GOOGLE_MAPS_API_KEY environment variable is required")

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)


class GoogleMapsRouting:
    def __init__(self, max_chars: int = 250000) -> None:
        self.max_chars = max_chars

    @staticmethod
    def _to_json_string(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False)

    def maps_distance_matrix(self, origins: List[str], destinations: List[str], mode: str = "driving") -> str:
        if not isinstance(origins, list) or len(origins) == 0:
            return self._to_json_string(
                {"isError": True, "error": "origins must be a non-empty list（迁移自 TS 版的数组校验）"}
            )
        if not isinstance(destinations, list) or len(destinations) == 0:
            return self._to_json_string(
                {"isError": True, "error": "destinations must be a non-empty list（迁移自 TS 版的数组校验）"}
            )
        if mode not in ["driving", "walking", "bicycling", "transit"]:
            return self._to_json_string(
                {
                    "isError": True,
                    "error": "mode must be one of: driving, walking, bicycling, transit（迁移自 TS 版的枚举校验）",
                }
            )

        try:
            result = gmaps.distance_matrix(origins=origins, destinations=destinations, mode=mode)
            if result.get("status") != "OK":
                return self._to_json_string(
                    {
                        "isError": True,
                        "error": "計算距離矩陣失敗（迁移自 TS 版的错误提示）",
                        "origins": origins,
                        "destinations": destinations,
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
                    "origins": origins,
                    "destinations": destinations,
                    "msg": "迁移自 TS 版 distanceMatrix.ts 的异常处理",
                }
            )

    def maps_directions(
        self,
        origin: str,
        destination: str,
        mode: str = "driving",
        departure_time: Optional[str] = None,
        arrival_time: Optional[str] = None,
    ) -> str:
        origin = str(origin).strip()
        destination = str(destination).strip()
        if not origin:
            return self._to_json_string({"isError": True, "error": "origin cannot be empty（迁移自 TS 版的非空校验）"})
        if not destination:
            return self._to_json_string(
                {"isError": True, "error": "destination cannot be empty（迁移自 TS 版的非空校验）"}
            )
        if mode not in ["driving", "walking", "bicycling", "transit"]:
            return self._to_json_string(
                {
                    "isError": True,
                    "error": "mode must be one of: driving, walking, bicycling, transit（迁移自 TS 版的枚举校验）",
                }
            )

        try:
            directions_kwargs = {"mode": mode}
            if departure_time:
                directions_kwargs["departure_time"] = datetime.fromisoformat(departure_time.replace("Z", "+00:00"))
            if arrival_time:
                directions_kwargs["arrival_time"] = datetime.fromisoformat(arrival_time.replace("Z", "+00:00"))

            result = gmaps.directions(origin=origin, destination=destination, **directions_kwargs)
            if not result:
                return self._to_json_string(
                    {
                        "isError": True,
                        "error": "獲取路線指引失敗（迁移自 TS 版的错误提示）",
                        "origin": origin,
                        "destination": destination,
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
                    "origin": origin,
                    "destination": destination,
                    "msg": "迁移自 TS 版 directions.ts 的异常处理",
                }
            )


google_maps_routing = GoogleMapsRouting()


@registry.tool()
def google_maps_maps_distance_matrix(
    origins: List[str],
    destinations: List[str],
    mode: str = "driving",
    uid: Optional[str] = None,
) -> str:
    """Calculate distance and duration between multiple origins and destinations."""
    return google_maps_routing.maps_distance_matrix(origins, destinations, mode)


@registry.tool()
def google_maps_maps_directions(
    origin: str,
    destination: str,
    mode: str = "driving",
    departure_time: Optional[str] = None,
    arrival_time: Optional[str] = None,
    uid: Optional[str] = None,
) -> str:
    """Get step-by-step directions between two locations."""
    return google_maps_routing.maps_directions(origin, destination, mode, departure_time, arrival_time)


__all__ = [
    "google_maps_routing",
    "google_maps_maps_distance_matrix",
    "google_maps_maps_directions",
]
