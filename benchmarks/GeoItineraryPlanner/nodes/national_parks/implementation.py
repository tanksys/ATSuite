import os
import json
import requests
from pathlib import Path
from typing import Any, Dict, List, Optional
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

# 兼容注册器逻辑
try:
    from atsuite_sdk.abstract import registry
except ImportError:
    class MockRegistry:
        @staticmethod
        def tool(func=None, name=None):
            if func:
                return func
            else:
                def decorator(func):
                    return func
                return decorator
        
        @staticmethod
        def register_tool(func, name):
            pass
    registry = MockRegistry()

"""
==================== 1. 配置迁移 ====================
"""
NPS_API_KEY = os.getenv("NPS_API_KEY", "")
SERVER_CONFIG = {
    "serverName": "mcp-server-nationalparks",
    "serverVersion": "1.0.0",
    "serverDescription": "MCP server for interacting with National Park Service API",
    "logLevel": os.getenv("LOG_LEVEL", "info")
}

if not NPS_API_KEY:
    print("⚠️ Warning: NPS_API_KEY is not set in environment variables.")
    print("🔑 Get your API key at: https://www.nps.gov/subjects/developer/get-started.htm")

"""
==================== 2. 常量迁移 ====================
"""
STATE_CODES = [
    'AL', 'AK', 'AZ', 'AR', 'CA', 'CO', 'CT', 'DE', 'FL', 'GA',
    'HI', 'ID', 'IL', 'IN', 'IA', 'KS', 'KY', 'LA', 'ME', 'MD',
    'MA', 'MI', 'MN', 'MS', 'MO', 'MT', 'NE', 'NV', 'NH', 'NJ',
    'NM', 'NY', 'NC', 'ND', 'OH', 'OK', 'OR', 'PA', 'RI', 'SC',
    'SD', 'TN', 'TX', 'UT', 'VT', 'VA', 'WA', 'WV', 'WI', 'WY',
    'DC', 'AS', 'GU', 'MP', 'PR', 'VI', 'UM'
]

NPS_API_BASE_URL = "https://developer.nps.gov/api/v1"
DEFAULT_LIMIT = 10
MAX_LIMIT = 50

"""
==================== 3. 格式化函数 ====================
"""
def formatParkData(park_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formatted_parks = []
    for park in park_data:
        states = [code.strip() for code in park.get("states", "").split(",")]
        activities = [activity.get("name", "") for activity in park.get("activities", [])]
        
        entrance_fees = []
        for fee in park.get("entranceFees", []):
            entrance_fees.append({
                "cost": fee.get("cost", ""),
                "description": fee.get("description", ""),
                "title": fee.get("title", "")
            })
        
        operating_hours = []
        for hours in park.get("operatingHours", []):
            operating_hours.append({
                "name": hours.get("name", ""),
                "description": hours.get("description", ""),
                "standardHours": hours.get("standardHours", {})
            })
        
        phone_numbers = []
        for phone in park.get("contacts", {}).get("phoneNumbers", []):
            phone_numbers.append({
                "type": phone.get("type", ""),
                "number": phone.get("phoneNumber", ""),
                "description": phone.get("description", "")
            })
        
        email_addresses = []
        for email in park.get("contacts", {}).get("emailAddresses", []):
            email_addresses.append({
                "address": email.get("emailAddress", ""),
                "description": email.get("description", "")
            })
        
        images = []
        for image in park.get("images", []):
            images.append({
                "url": image.get("url", ""),
                "title": image.get("title", ""),
                "altText": image.get("altText", ""),
                "caption": image.get("caption", ""),
                "credit": image.get("credit", "")
            })
        
        formatted_parks.append({
            "name": park.get("fullName", ""),
            "code": park.get("parkCode", ""),
            "description": park.get("description", ""),
            "states": states,
            "url": park.get("url", ""),
            "designation": park.get("designation", ""),
            "activities": activities,
            "weatherInfo": park.get("weatherInfo", ""),
            "location": {
                "latitude": park.get("latitude", ""),
                "longitude": park.get("longitude", "")
            },
            "entranceFees": entrance_fees,
            "operatingHours": operating_hours,
            "contacts": {
                "phoneNumbers": phone_numbers,
                "emailAddresses": email_addresses
            },
            "images": images
        })
    return formatted_parks

def formatParkDetails(park: Dict[str, Any]) -> Dict[str, Any]:
    addresses = park.get("addresses", [])
    physical_address = None
    for addr in addresses:
        if addr.get("type") == "Physical":
            physical_address = addr
            break
    if not physical_address and addresses:
        physical_address = addresses[0]
    
    formatted_hours = []
    for hours in park.get("operatingHours", []):
        standard_hours = hours.get("standardHours", {})
        formatted_standard = {}
        for day, time in standard_hours.items():
            formatted_standard[day.capitalize()] = time or "Closed"
        formatted_hours.append({
            "name": hours.get("name", ""),
            "description": hours.get("description", ""),
            "standardHours": formatted_standard
        })
    
    states = [code.strip() for code in park.get("states", "").split(",")]
    
    entrance_fees = []
    for fee in park.get("entranceFees", []):
        entrance_fees.append({
            "title": fee.get("title", ""),
            "cost": f"${fee.get('cost', '')}" if fee.get("cost") else "",
            "description": fee.get("description", "")
        })
    
    entrance_passes = []
    for pass_info in park.get("entrancePasses", []):
        entrance_passes.append({
            "title": pass_info.get("title", ""),
            "cost": f"${pass_info.get('cost', '')}" if pass_info.get("cost") else "",
            "description": pass_info.get("description", "")
        })
    
    phone_numbers = []
    for phone in park.get("contacts", {}).get("phoneNumbers", []):
        phone_numbers.append({
            "type": phone.get("type", ""),
            "number": phone.get("phoneNumber", ""),
            "extension": phone.get("extension", ""),
            "description": phone.get("description", "")
        })
    
    email_addresses = []
    for email in park.get("contacts", {}).get("emailAddresses", []):
        email_addresses.append({
            "address": email.get("emailAddress", ""),
            "description": email.get("description", "")
        })
    
    images = []
    for image in park.get("images", []):
        images.append({
            "url": image.get("url", ""),
            "title": image.get("title", ""),
            "altText": image.get("altText", ""),
            "caption": image.get("caption", ""),
            "credit": image.get("credit", "")
        })
    
    formatted_address = None
    if physical_address:
        formatted_address = {
            "line1": physical_address.get("line1", ""),
            "line2": physical_address.get("line2", ""),
            "city": physical_address.get("city", ""),
            "stateCode": physical_address.get("stateCode", ""),
            "postalCode": physical_address.get("postalCode", "")
        }
    
    return {
        "name": park.get("fullName", ""),
        "code": park.get("parkCode", ""),
        "id": park.get("id", ""),
        "url": park.get("url", ""),
        "description": park.get("description", ""),
        "states": states,
        "weatherInfo": park.get("weatherInfo", ""),
        "directionsInfo": park.get("directionsInfo", ""),
        "directionsUrl": park.get("directionsUrl", ""),
        "location": {
            "latitude": park.get("latitude", ""),
            "longitude": park.get("longitude", ""),
            "address": formatted_address
        },
        "activities": [topic.get("name", "") for topic in park.get("activities", [])],
        "topics": [topic.get("name", "") for topic in park.get("topics", [])],
        "entranceFees": entrance_fees,
        "entrancePasses": entrance_passes,
        "operatingHours": formatted_hours,
        "contacts": {
            "phoneNumbers": phone_numbers,
            "emailAddresses": email_addresses
        },
        "images": images
    }

def formatAlertData(alert_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formatted_alerts = []
    for alert in alert_data:
        last_updated = "Unknown"
        if alert.get("lastIndexedDate"):
            try:
                iso_date = datetime.fromisoformat(alert["lastIndexedDate"].replace("Z", "+00:00"))
                last_updated = iso_date.strftime("%m/%d/%Y")
            except (ValueError, TypeError):
                last_updated = "Unknown"
        
        alert_type = alert.get("category", "")
        if alert_type == "Information":
            alert_type = "Information (non-emergency)"
        elif alert_type == "Caution":
            alert_type = "Caution (potential hazard)"
        elif alert_type == "Danger":
            alert_type = "Danger (significant hazard)"
        elif alert_type == "Park Closure":
            alert_type = "Park Closure (area inaccessible)"
        
        formatted_alerts.append({
            "id": alert.get("id", ""),
            "title": alert.get("title", ""),
            "parkCode": alert.get("parkCode", ""),
            "description": alert.get("description", ""),
            "category": alert_type,
            "url": alert.get("url", ""),
            "lastUpdated": last_updated
        })
    return formatted_alerts

def formatVisitorCenterData(visitor_center_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formatted_centers = []
    for center in visitor_center_data:
        addresses = center.get("addresses", [])
        physical_address = None
        for addr in addresses:
            if addr.get("type") == "Physical":
                physical_address = addr
                break
        if not physical_address and addresses:
            physical_address = addresses[0]
        
        formatted_hours = []
        for hours in center.get("operatingHours", []):
            standard_hours = hours.get("standardHours", {})
            formatted_standard = {}
            for day, time in standard_hours.items():
                formatted_standard[day.capitalize()] = time or "Closed"
            formatted_hours.append({
                "name": hours.get("name", ""),
                "description": hours.get("description", ""),
                "standardHours": formatted_standard
            })
        
        phone_numbers = []
        for phone in center.get("contacts", {}).get("phoneNumbers", []):
            phone_numbers.append({
                "type": phone.get("type", ""),
                "number": phone.get("phoneNumber", ""),
                "extension": phone.get("extension", ""),
                "description": phone.get("description", "")
            })
        
        email_addresses = []
        for email in center.get("contacts", {}).get("emailAddresses", []):
            email_addresses.append({
                "address": email.get("emailAddress", ""),
                "description": email.get("description", "")
            })
        
        formatted_address = None
        if physical_address:
            formatted_address = {
                "line1": physical_address.get("line1", ""),
                "line2": physical_address.get("line2", ""),
                "city": physical_address.get("city", ""),
                "stateCode": physical_address.get("stateCode", ""),
                "postalCode": physical_address.get("postalCode", "")
            }
        
        formatted_centers.append({
            "id": center.get("id", ""),
            "name": center.get("name", ""),
            "parkCode": center.get("parkCode", ""),
            "description": center.get("description", ""),
            "url": center.get("url", ""),
            "directionsInfo": center.get("directionsInfo", ""),
            "directionsUrl": center.get("directionsUrl", ""),
            "location": {
                "latitude": center.get("latitude", ""),
                "longitude": center.get("longitude", ""),
                "address": formatted_address
            },
            "operatingHours": formatted_hours,
            "contacts": {
                "phoneNumbers": phone_numbers,
                "emailAddresses": email_addresses
            }
        })
    return formatted_centers

def formatCampgroundData(campground_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formatted_campgrounds = []
    for campground in campground_data:
        addresses = campground.get("addresses", [])
        physical_address = None
        for addr in addresses:
            if addr.get("type") == "Physical":
                physical_address = addr
                break
        if not physical_address and addresses:
            physical_address = addresses[0]
        
        formatted_hours = []
        for hours in campground.get("operatingHours", []):
            standard_hours = hours.get("standardHours", {})
            formatted_standard = {}
            for day, time in standard_hours.items():
                formatted_standard[day.capitalize()] = time or "Closed"
            formatted_hours.append({
                "name": hours.get("name", ""),
                "description": hours.get("description", ""),
                "standardHours": formatted_standard
            })
        
        amenities = []
        campground_amenities = campground.get("amenities", {})
        if campground_amenities.get("trashRecyclingCollection"):
            amenities.append("Trash/Recycling Collection")
        if campground_amenities.get("toilets"):
            amenities.append(f"Toilets: {', '.join(campground_amenities['toilets'])}")
        if campground_amenities.get("internetConnectivity"):
            amenities.append("Internet Connectivity")
        if campground_amenities.get("showers"):
            amenities.append(f"Showers: {', '.join(campground_amenities['showers'])}")
        if campground_amenities.get("cellPhoneReception"):
            amenities.append("Cell Phone Reception")
        if campground_amenities.get("laundry"):
            amenities.append("Laundry Facilities")
        if campground_amenities.get("amphitheater"):
            amenities.append("Amphitheater")
        if campground_amenities.get("dumpStation"):
            amenities.append("Dump Station")
        if campground_amenities.get("campStore"):
            amenities.append("Camp Store")
        if campground_amenities.get("staffOrVolunteerHostOnsite"):
            amenities.append("On-site Host/Staff")
        if campground_amenities.get("potableWater"):
            amenities.append(f"Potable Water: {', '.join(campground_amenities['potableWater'])}")
        if campground_amenities.get("iceAvailableForSale"):
            amenities.append("Ice for Sale")
        if campground_amenities.get("firewoodForSale"):
            amenities.append("Firewood for Sale")
        if campground_amenities.get("foodStorageLockers"):
            amenities.append("Food Storage Lockers")
        
        campsites = campground.get("campsites", {})
        campsite_stats = {
            "totalSites": campsites.get("totalSites", "0"),
            "groupSites": campsites.get("group", "0"),
            "horseSites": campsites.get("horse", "0"),
            "tentOnly": campsites.get("tentOnly", "0"),
            "electricalHookups": campsites.get("electricalHookups", "0"),
            "rvOnly": campsites.get("rvOnly", "0"),
            "walkBoatTo": campsites.get("walkBoatTo", "0"),
            "other": campsites.get("other", "0")
        }
        
        accessibility = campground.get("accessibility", {})
        accessibility_info = {
            "wheelchairAccess": accessibility.get("wheelchairAccess", "Unknown"),
            "rvAllowed": accessibility.get("rvAllowed", False),
            "rvMaxLength": accessibility.get("rvMaxLength", "Unknown"),
            "trailerAllowed": accessibility.get("trailerAllowed", False),
            "trailerMaxLength": accessibility.get("trailerMaxLength", "Unknown"),
            "accessRoads": accessibility.get("accessRoads", []),
            "adaInfo": accessibility.get("adaInfo", "")
        }
        
        formatted_address = None
        if physical_address:
            formatted_address = {
                "line1": physical_address.get("line1", ""),
                "line2": physical_address.get("line2", ""),
                "city": physical_address.get("city", ""),
                "stateCode": physical_address.get("stateCode", ""),
                "postalCode": physical_address.get("postalCode", "")
            }
        
        phone_numbers = []
        for phone in campground.get("contacts", {}).get("phoneNumbers", []):
            phone_numbers.append({
                "type": phone.get("type", ""),
                "number": phone.get("phoneNumber", ""),
                "extension": phone.get("extension", ""),
                "description": phone.get("description", "")
            })
        
        email_addresses = []
        for email in campground.get("contacts", {}).get("emailAddresses", []):
            email_addresses.append({
                "address": email.get("emailAddress", ""),
                "description": email.get("description", "")
            })
        
        formatted_campgrounds.append({
            "id": campground.get("id", ""),
            "name": campground.get("name", ""),
            "parkCode": campground.get("parkCode", ""),
            "description": campground.get("description", ""),
            "url": campground.get("url", ""),
            "reservationInfo": campground.get("reservationInfo", ""),
            "reservationUrl": campground.get("reservationUrl", ""),
            "regulations": campground.get("regulationsOverview", ""),
            "regulationsUrl": campground.get("regulationsurl", ""),
            "weatherOverview": campground.get("weatherOverview", ""),
            "location": {
                "latitude": campground.get("latitude", ""),
                "longitude": campground.get("longitude", ""),
                "address": formatted_address
            },
            "operatingHours": formatted_hours,
            "amenities": amenities,
            "campsiteStats": campsite_stats,
            "accessibility": accessibility_info,
            "sitesReservable": campground.get("numberOfSitesReservable", "0"),
            "sitesFirstComeFirstServe": campground.get("numberOfSitesFirstComeFirstServe", "0"),
            "contacts": {
                "phoneNumbers": phone_numbers,
                "emailAddresses": email_addresses
            }
        })
    return formatted_campgrounds

def formatEventData(event_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    formatted_events = []
    for event in event_data:
        formatted_dates = ", ".join(event.get("dates", [])) if event.get("dates") else "Unknown"
        
        formatted_times = []
        for time in event.get("times", []):
            time_str = ""
            if time.get("sunriseTimeStart"):
                time_str += "Sunrise"
            elif time.get("timeStart"):
                time_str += time.get("timeStart", "")
            
            if time.get("sunsetTimeEnd"):
                time_str += " to Sunset"
            elif time.get("timeEnd"):
                time_str += f" to {time.get('timeEnd', '')}"
            
            if not time_str:
                time_str = "All Day"
            formatted_times.append(time_str)
        
        contact_info = {
            "email": event.get("contactEmailAddress", ""),
            "phone": event.get("contactTelephoneNumber", "")
        }
        
        formatted_events.append({
            "id": event.get("id", ""),
            "title": event.get("title", ""),
            "parkCode": event.get("parkCode", ""),
            "parkName": event.get("parkFullName", ""),
            "description": event.get("description", ""),
            "category": event.get("category", ""),
            "subcategory": event.get("subcategory", ""),
            "location": event.get("location", ""),
            "tags": event.get("tags", []),
            "dateTime": {
                "dates": formatted_dates,
                "times": formatted_times,
                "startDate": event.get("dateStart", ""),
                "endDate": event.get("dateEnd", ""),
                "isRecurring": event.get("isRecurring", False),
                "recurrenceStart": event.get("recurrenceDateStart", ""),
                "recurrenceEnd": event.get("recurrenceDateEnd", "")
            },
            "feeInfo": event.get("feeInfo", ""),
            "contactInfo": contact_info,
            "url": event.get("url", "") or event.get("infoURL", ""),
            "lastUpdated": event.get("lastUpdated", "")
        })
    return formatted_events

"""
==================== 4. API 客户端（改为单例函数调用） ====================
"""
class NpsApiClient:
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(NpsApiClient, cls).__new__(cls)
            cls._instance._initialize()
        return cls._instance
    
    def _initialize(self):
        self.base_url = NPS_API_BASE_URL
        self.api_key = NPS_API_KEY
        self.headers = {
            "X-Api-Key": self.api_key,
            "Accept": "application/json"
        }
        self.timeout = 30
    
    def _make_request(self, endpoint: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{endpoint}"
        params = params or {}
        
        try:
            response = requests.get(
                url=url,
                headers=self.headers,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()
            return response.json()
        
        except requests.exceptions.HTTPError as e:
            if response.status_code == 429:
                raise Exception("Rate limit exceeded for NPS API. Please try again later.")
            raise Exception(f"NPS API Error: {response.status_code} - {response.reason}")
        except requests.exceptions.RequestException as e:
            raise Exception(f"Request failed: {str(e)}")
        except Exception as e:
            raise Exception(f"Unexpected error: {str(e)}")
    
    def getParks(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        return self._make_request("/parks", params)
    
    def getParkByCode(self, parkCode: str) -> Dict[str, Any]:
        return self._make_request("/parks", {"parkCode": parkCode, "limit": 1})
    
    def getAlerts(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        return self._make_request("/alerts", params)
    
    def getAlertsByParkCode(self, parkCode: str) -> Dict[str, Any]:
        return self._make_request("/alerts", {"parkCode": parkCode})
    
    def getVisitorCenters(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        return self._make_request("/visitorcenters", params)
    
    def getCampgrounds(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        return self._make_request("/campgrounds", params)
    
    def getEvents(self, params: Dict[str, Any] = None) -> Dict[str, Any]:
        return self._make_request("/events", params)

# 全局客户端实例
nps_api_client = NpsApiClient()

"""
==================== 5. 核心工具函数（独立函数，无self，用@registry.tool()装饰） ====================
"""
@registry.tool()
def findParks(args: Dict[str, Any] = None) -> str:
    """独立函数：查询公园（无self参数，符合框架要求）"""
    try:
        args = args or {}
        
        if args.get("stateCode"):
            provided_states = [s.strip().upper() for s in args["stateCode"].split(",")]
            invalid_states = [s for s in provided_states if s not in STATE_CODES]
            
            if invalid_states:
                error_response = {
                    "content": [{
                        "type": "text",
                        "text": json.dumps({
                            "error": f"Invalid state code(s): {', '.join(invalid_states)}",
                            "validStateCodes": STATE_CODES
                        }, indent=2)
                    }]
                }
                return json.dumps(error_response)
        
        limit = args.get("limit")
        if limit:
            try:
                limit = min(int(limit), 50)
            except (ValueError, TypeError):
                limit = 10
        else:
            limit = 10
        
        request_params = {
            "limit": limit,
            **args
        }
        
        response = nps_api_client.getParks(request_params)
        formatted_parks = formatParkData(response.get("data", []))
        
        result = {
            "total": int(response.get("total", 0)),
            "limit": int(response.get("limit", 0)),
            "start": int(response.get("start", 0)),
            "parks": formatted_parks
        }
        
        final_response = {
            "content": [{
                "type": "text",
                "text": json.dumps(result, indent=2, ensure_ascii=False)
            }]
        }
        return json.dumps(final_response, ensure_ascii=False)
    
    except Exception as e:
        error_response = {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": str(e)}, indent=2, ensure_ascii=False)
            }]
        }
        return json.dumps(error_response, ensure_ascii=False)

@registry.tool()
def getAlerts(args: Dict[str, Any] = None) -> str:
    """独立函数：查询警报（无self参数）"""
    try:
        args = args or {}
        
        limit = args.get("limit")
        if limit:
            try:
                limit = min(int(limit), 50)
            except (ValueError, TypeError):
                limit = 10
        else:
            limit = 10
        
        request_params = {
            "limit": limit,
            **args
        }
        
        response = nps_api_client.getAlerts(request_params)
        formatted_alerts = formatAlertData(response.get("data", []))
        
        alertsByPark = {}
        for alert in formatted_alerts:
            parkCode = alert.get("parkCode")
            if not alertsByPark.get(parkCode):
                alertsByPark[parkCode] = []
            alertsByPark[parkCode].append(alert)
        
        result = {
            "total": int(response.get("total", 0)),
            "limit": int(response.get("limit", 0)),
            "start": int(response.get("start", 0)),
            "alerts": formatted_alerts,
            "alertsByPark": alertsByPark
        }
        
        final_response = {
            "content": [{
                "type": "text",
                "text": json.dumps(result, indent=2, ensure_ascii=False)
            }]
        }
        return json.dumps(final_response, ensure_ascii=False)
    
    except Exception as e:
        error_response = {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": str(e)}, indent=2, ensure_ascii=False)
            }]
        }
        return json.dumps(error_response, ensure_ascii=False)

@registry.tool()
def getParkDetails(args: Dict[str, Any] = None) -> str:
    """独立函数：查询公园详情（无self参数）"""
    try:
        args = args or {}
        
        parkCode = args.get("parkCode")
        if not parkCode:
            raise ValueError("parkCode is required (e.g., 'yose' for Yosemite)")
        
        response = nps_api_client.getParkByCode(parkCode)
        park_data = response.get("data", [])
        
        if not park_data or len(park_data) == 0:
            error_response = {
                "content": [{
                    "type": "text",
                    "text": json.dumps({
                        "error": 'Park not found',
                        "message": f"No park found with park code: {parkCode}"
                    }, indent=2, ensure_ascii=False)
                }]
            }
            return json.dumps(error_response, ensure_ascii=False)
        
        parkDetails = formatParkDetails(park_data[0])
        
        final_response = {
            "content": [{
                "type": "text",
                "text": json.dumps(parkDetails, indent=2, ensure_ascii=False)
            }]
        }
        return json.dumps(final_response, ensure_ascii=False)
    
    except ValueError as ve:
        error_response = {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "error": "Invalid parameter",
                    "message": str(ve)
                }, indent=2, ensure_ascii=False)
            }]
        }
        return json.dumps(error_response, ensure_ascii=False)
    except Exception as e:
        error_response = {
            "content": [{
                "type": "text",
                "text": json.dumps({
                    "error": "Server error",
                    "message": str(e)
                }, indent=2, ensure_ascii=False)
            }]
        }
        return json.dumps(error_response, ensure_ascii=False)

@registry.tool()
def getVisitorCenters(args: Dict[str, Any] = None) -> str:
    """独立函数：查询游客中心（无self参数）"""
    try:
        args = args or {}
        
        limit = args.get("limit")
        if limit:
            try:
                limit = min(int(limit), 50)
            except (ValueError, TypeError):
                limit = 10
        else:
            limit = 10
        
        request_params = {
            "limit": limit,
            **args
        }
        
        response = nps_api_client.getVisitorCenters(request_params)
        formattedCenters = formatVisitorCenterData(response.get("data", []))
        
        centersByPark = {}
        for center in formattedCenters:
            parkCode = center.get("parkCode")
            if not centersByPark.get(parkCode):
                centersByPark[parkCode] = []
            centersByPark[parkCode].append(center)
        
        result = {
            "total": int(response.get("total", 0)),
            "limit": int(response.get("limit", 0)),
            "start": int(response.get("start", 0)),
            "visitorCenters": formattedCenters,
            "visitorCentersByPark": centersByPark
        }
        
        final_response = {
            "content": [{
                "type": "text",
                "text": json.dumps(result, indent=2, ensure_ascii=False)
            }]
        }
        return json.dumps(final_response, ensure_ascii=False)
    
    except Exception as e:
        error_response = {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": str(e)}, indent=2, ensure_ascii=False)
            }]
        }
        return json.dumps(error_response, ensure_ascii=False)

@registry.tool()
def getCampgrounds(args: Dict[str, Any] = None) -> str:
    """独立函数：查询露营地（无self参数）"""
    try:
        args = args or {}
        
        limit = args.get("limit")
        if limit:
            try:
                limit = min(int(limit), 50)
            except (ValueError, TypeError):
                limit = 10
        else:
            limit = 10
        
        request_params = {
            "limit": limit,
            **args
        }
        
        response = nps_api_client.getCampgrounds(request_params)
        formattedCampgrounds = formatCampgroundData(response.get("data", []))
        
        campgroundsByPark = {}
        for campground in formattedCampgrounds:
            parkCode = campground.get("parkCode")
            if not campgroundsByPark.get(parkCode):
                campgroundsByPark[parkCode] = []
            campgroundsByPark[parkCode].append(campground)
        
        result = {
            "total": int(response.get("total", 0)),
            "limit": int(response.get("limit", 0)),
            "start": int(response.get("start", 0)),
            "campgrounds": formattedCampgrounds,
            "campgroundsByPark": campgroundsByPark
        }
        
        final_response = {
            "content": [{
                "type": "text",
                "text": json.dumps(result, indent=2, ensure_ascii=False)
            }]
        }
        return json.dumps(final_response, ensure_ascii=False)
    
    except Exception as e:
        error_response = {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": str(e)}, indent=2, ensure_ascii=False)
            }]
        }
        return json.dumps(error_response, ensure_ascii=False)

@registry.tool()
def getEvents(args: Dict[str, Any] = None) -> str:
    """独立函数：查询活动（无self参数）"""
    try:
        args = args or {}
        
        limit = args.get("limit")
        if limit:
            try:
                limit = min(int(limit), 50)
            except (ValueError, TypeError):
                limit = 10
        else:
            limit = 10
        
        request_params = {
            "limit": limit,
            **args
        }
        
        response = nps_api_client.getEvents(request_params)
        formattedEvents = formatEventData(response.get("data", []))
        
        eventsByPark = {}
        for event in formattedEvents:
            parkCode = event.get("parkCode")
            if not eventsByPark.get(parkCode):
                eventsByPark[parkCode] = []
            eventsByPark[parkCode].append(event)
        
        result = {
            "total": int(response.get("total", 0)),
            "limit": int(response.get("limit", 0)),
            "start": int(response.get("start", 0)),
            "events": formattedEvents,
            "eventsByPark": eventsByPark
        }
        
        final_response = {
            "content": [{
                "type": "text",
                "text": json.dumps(result, indent=2, ensure_ascii=False)
            }]
        }
        return json.dumps(final_response, ensure_ascii=False)
    
    except Exception as e:
        error_response = {
            "content": [{
                "type": "text",
                "text": json.dumps({"error": str(e)}, indent=2, ensure_ascii=False)
            }]
        }
        return json.dumps(error_response, ensure_ascii=False)

"""
==================== 6. 导出 ====================
"""
__all__ = [
    "findParks",
    "getAlerts",
    "getParkDetails",
    "getVisitorCenters",
    "getCampgrounds",
    "getEvents",
    "nps_api_client",
    "STATE_CODES",
    "SERVER_CONFIG"
]