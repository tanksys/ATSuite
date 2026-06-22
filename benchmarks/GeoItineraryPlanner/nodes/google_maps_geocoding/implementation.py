import json
import os
from pathlib import Path
from typing import Any, Optional

import googlemaps
from dotenv import load_dotenv

from atsuite_sdk.abstract import registry


load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
if not GOOGLE_MAPS_API_KEY:
    raise EnvironmentError("GOOGLE_MAPS_API_KEY environment variable is required")

gmaps = googlemaps.Client(key=GOOGLE_MAPS_API_KEY)


class GoogleMapsGeocoding:
    def __init__(self, max_chars: int = 250000) -> None:
        self.max_chars = max_chars

    @staticmethod
    def _to_json_string(data: Any) -> str:
        return json.dumps(data, ensure_ascii=False)

    def maps_geocode(self, address: str) -> str:
        address = str(address).strip()
        if not address:
            return self._to_json_string(
                {"isError": True, "error": "address cannot be empty（迁移自 TS 版的 Zod 非空校验）"}
            )

        try:
            result = gmaps.geocode(address=address)
            if not result:
                return self._to_json_string(
                    {
                        "isError": True,
                        "error": "地址轉換座標失敗（迁移自 TS 版的错误提示）",
                        "address": address,
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
                    "address": address,
                    "msg": "迁移自 TS 版 geocode.ts 的异常处理逻辑",
                }
            )

    def maps_reverse_geocode(self, latitude: float, longitude: float) -> str:
        try:
            lat = float(latitude)
            lng = float(longitude)
        except (ValueError, TypeError):
            return self._to_json_string(
                {
                    "isError": True,
                    "error": "latitude and longitude must be valid numbers（迁移自 TS 版的类型校验）",
                }
            )

        try:
            result = gmaps.reverse_geocode((lat, lng))
            if not result:
                return self._to_json_string(
                    {
                        "isError": True,
                        "error": "座標轉換地址失敗（迁移自 TS 版的错误提示）",
                        "latitude": lat,
                        "longitude": lng,
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
                    "latitude": lat,
                    "longitude": lng,
                    "msg": "迁移自 TS 版 reverseGeocode.ts 的异常处理",
                }
            )


google_maps_geocoding = GoogleMapsGeocoding()


@registry.tool()
def google_maps_maps_geocode(address: str, uid: Optional[str] = None) -> str:
    """Convert addresses or place names to geographic coordinates (latitude and longitude)."""
    return google_maps_geocoding.maps_geocode(address)


@registry.tool()
def google_maps_maps_reverse_geocode(latitude: float, longitude: float, uid: Optional[str] = None) -> str:
    """Convert geographic coordinates (latitude and longitude) to a human-readable address."""
    return google_maps_geocoding.maps_reverse_geocode(latitude, longitude)


__all__ = [
    "google_maps_geocoding",
    "google_maps_maps_geocode",
    "google_maps_maps_reverse_geocode",
]
