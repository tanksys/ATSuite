import json
import os
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import googlemaps
from dotenv import load_dotenv

from atsuite_sdk.abstract import registry


load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
if not GOOGLE_MAPS_API_KEY:
    raise EnvironmentError("GOOGLE_MAPS_API_KEY environment variable is required")

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)


class GoogleMapsPlaces:
    def __init__(self, max_chars: int = 250000) -> None:
        self.max_chars = max_chars

    @staticmethod
    def _to_json_string(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False)

    def get_place_details(self, placeId: str) -> str:
        placeId = str(placeId).strip()
        if not placeId:
            return self._to_json_string({"isError": True, "error": "placeId cannot be empty（迁移自 TS 版的非空校验）"})

        try:
            result = gmaps.place(place_id=placeId)
            if result.get("status") != "OK":
                return self._to_json_string(
                    {
                        "isError": True,
                        "error": "獲取詳細資訊失敗（迁移自 TS 版的错误提示）",
                        "placeId": placeId,
                    }
                )

            response = self._to_json_string(result["result"])
            if len(response) > self.max_chars:
                raise ValueError(f"Response too large ({len(response)} chars), max allowed {self.max_chars}.")
            return response
        except Exception as exc:
            return self._to_json_string(
                {
                    "isError": True,
                    "error": str(exc),
                    "placeId": placeId,
                    "msg": "迁移自 TS 版 placeDetails.ts 的异常处理",
                }
            )

    def search_nearby(
        self,
        center: Dict[str, Any],
        keyword: Optional[str] = None,
        radius: int = 1000,
        openNow: bool = False,
        minRating: Optional[float] = None,
    ) -> str:
        if not isinstance(center, dict) or "value" not in center:
            return self._to_json_string(
                {
                    "isError": True,
                    "error": "center must have 'value' field（迁移自 TS 版的 center 结构校验）",
                }
            )

        center_value = str(center["value"]).strip()
        isCoordinates = center.get("isCoordinates", False)
        if not center_value:
            return self._to_json_string(
                {"isError": True, "error": "center.value cannot be empty（迁移自 TS 版的非空校验）"}
            )

        try:
            location: Tuple[float, float] | Dict[str, Any]
            if isCoordinates:
                lat_str, lng_str = center_value.split(",")
                location = (float(lat_str.strip()), float(lng_str.strip()))
            else:
                geocode_result = gmaps.geocode(center_value)
                if not geocode_result:
                    raise ValueError(f"Invalid address: {center_value}（迁移自 TS 版的地址有效性校验）")
                location = geocode_result[0]["geometry"]["location"]

            radius = int(radius)
            if radius < 1 or radius > 50000:
                raise ValueError("radius must be between 1 and 50000 meters（迁移自 TS 版的半径范围校验）")

            places_kwargs = {
                "location": location,
                "radius": radius,
                "open_now": openNow,
            }
            if keyword:
                places_kwargs["keyword"] = str(keyword).strip()
            if minRating is not None:
                minRating = float(minRating)
                if not (0 <= minRating <= 5):
                    raise ValueError("minRating must be between 0 and 5（迁移自 TS 版的评分范围校验）")
                places_kwargs["min_rating"] = minRating

            result = gmaps.places_nearby(**places_kwargs)
            if result.get("status") != "OK":
                return self._to_json_string(
                    {
                        "isError": True,
                        "error": "搜尋失敗（迁移自 TS 版的错误提示）",
                        "center": center,
                    }
                )

            response_text = (
                f"location: {json.dumps(location, ensure_ascii=False)}\n"
                f"{json.dumps(result['results'], ensure_ascii=False)}"
            )
            if len(response_text) > self.max_chars:
                raise ValueError(f"Response too large ({len(response_text)} chars), max allowed {self.max_chars}.")
            return response_text
        except Exception as exc:
            return self._to_json_string(
                {
                    "isError": True,
                    "error": str(exc),
                    "center": center,
                    "msg": "迁移自 TS 版 searchNearby.ts 的异常处理",
                }
            )


google_maps_places = GoogleMapsPlaces()


@registry.tool()
def google_maps_get_place_details(placeId: str, uid: Optional[str] = None) -> str:
    """Get detailed information about a specific place including contact details, reviews, ratings."""
    return google_maps_places.get_place_details(placeId)


@registry.tool()
def google_maps_search_nearby(
    center: Dict[str, Any],
    keyword: Optional[str] = None,
    radius: int = 1000,
    openNow: bool = False,
    minRating: Optional[float] = None,
    uid: Optional[str] = None,
) -> str:
    """Search for nearby places based on location, with optional filtering by keywords, distance, rating."""
    return google_maps_places.search_nearby(center, keyword, radius, openNow, minRating)


__all__ = [
    "google_maps_places",
    "google_maps_get_place_details",
    "google_maps_search_nearby",
]
