#!/usr/bin/env python3
"""
WeatherAPI MCP Server (最终适配版)
兼容所有TS版调用规范：
1. 核心逻辑：weather-mcp/server.py
2. 字段规范：weather_agent/my-mastra-app/src/mastra/tools/weather-tool.ts
3. API调用规范：src/server.ts + src/mastra/tools/index.ts + src/mastra/agents/weather-agent.ts
"""

import os
import json
import requests
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
# 新增：导入 dotenv 库，用于加载 .env 文件
from dotenv import load_dotenv

# 新增：加载 weather_data 节点的 .env 文件（指定容器内绝对路径）
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

# 导入核心注册器（兼容无框架环境）
try:
    from atsuite_sdk.abstract import registry
except ImportError:
    # 兼容无框架环境的兜底注册器（支持装饰器调用）
    class MockRegistry:
        @staticmethod
        def tool(func=None, name=None):
            if func:
                # 装饰器模式：直接返回原函数
                return func
            else:
                # 带参数的装饰器模式
                def decorator(func):
                    return func
                return decorator
        
        @staticmethod
        def register_tool(func, name):
            pass
    registry = MockRegistry()

"""
==================== 环境配置 & 客户端初始化 ====================
"""
WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
BASE_URL = "http://api.weatherapi.com/v1"
API_TIMEOUT = int(os.getenv("API_TIMEOUT", "10"))
API_LANGUAGE = os.getenv("API_LANGUAGE", "tr")

if not WEATHER_API_KEY:
    raise EnvironmentError("WEATHER_API_KEY environment variable is required")

"""
==================== 核心类（全量适配TS版规范） ====================
"""
class WeatherData:
    def __init__(self, timeout_seconds: int = 45, max_chars: int = 250000) -> None:
        self.timeout_seconds = timeout_seconds
        self.max_chars = max_chars
        self.api_timeout = API_TIMEOUT

    @staticmethod
    def _to_json_string(data: Dict[str, Any]) -> str:
        return json.dumps(data, ensure_ascii=False)

    def get_current_weather(self, location: Union[str, None] = None, city: Union[str, None] = None) -> str:
        """
        适配点：
        1. 兼容双入参：location（weather-tool.ts）/ city（src/server.ts）
        2. 错误提示：土耳其语 "Şehir adı gerekli."（对齐src/server.ts）
        3. 保留 weather.city / weather.weather 字段（对齐src/weather-agent.ts）
        4. 异常提示：土耳其语 "Agent hatası."（对齐src/server.ts）
        """
        # 兼容双入参：优先取city，再取location（对齐所有TS版调用）
        target_city = city or location
        if not target_city:
            return self._to_json_string({
                "isError": True, 
                "error": "Şehir adı gerekli."  # 土耳其语：需要城市名称（对齐src/server.ts）
            })
        
        # 入参清洗
        target_city_str = str(target_city).strip()
        if not target_city_str:
            return self._to_json_string({
                "isError": True, 
                "error": "Şehir adı gerekli."
            })

        try:
            url = f"{BASE_URL}/current.json?key={WEATHER_API_KEY}&q={target_city_str}&lang={API_LANGUAGE}"
            response = requests.get(url, timeout=self.api_timeout)
            response.raise_for_status()
            data = response.json()
            
            # 核心适配：同时保留TS版所有字段（兼容weather-tool.ts + src/weather-agent.ts）
            result = {
                # 兼容src/weather-agent.ts的核心字段（必须保留）
                "city": data.get("location", {}).get("name") or target_city_str,
                "weather": data.get("current", {}).get("condition", {}).get("text", "Unknown"),
                # 兼容weather-tool.ts的字段映射
                "location": data.get("location", {}).get("name") or target_city_str,
                "country": data.get("location", {}).get("country"),
                "region": data.get("location", {}).get("region"),
                "temperature": data.get("current", {}).get("temp_c", 0),
                "feelsLike": data.get("current", {}).get("feelslike_c", 0),
                "humidity": data.get("current", {}).get("humidity", 0),
                "windSpeed": data.get("current", {}).get("wind_kph", 0),
                "conditions": data.get("current", {}).get("condition", {}).get("text", "Unknown"),
                "pressure": data.get("current", {}).get("pressure_mb"),
                "visibility": data.get("current", {}).get("vis_km"),
                "uvIndex": data.get("current", {}).get("uv"),
                "icon": data.get("current", {}).get("condition", {}).get("icon"),
                "windDir": data.get("current", {}).get("wind_dir"),
                "lastUpdated": data.get("current", {}).get("last_updated"),
                "temperature_f": data.get("current", {}).get("temp_f"),
                "feelslike_f": data.get("current", {}).get("feelslike_f"),
                "wind_mph": data.get("current", {}).get("wind_mph")
            }
            
            response_str = self._to_json_string(result)
            if len(response_str) > self.max_chars:
                raise ValueError(f"Response too large ({len(response_str)} chars), max allowed {self.max_chars}.")
            
            return response_str
        except Exception as exc:
            # 异常提示：土耳其语 "Agent hatası."（对齐src/server.ts）
            return self._to_json_string({
                "isError": True, 
                "error": "Agent hatası.",  # 土耳其语：Agent错误
                "detail": str(exc),  # 保留详细错误（便于调试）
                "city": target_city_str,
                "location": target_city_str
            })

    def get_weather_forecast(self, location: str = None, city: str = None, days: int = 3) -> str:
        """
        适配点：兼容双入参 city/location
        """
        target_city = city or location
        if not target_city:
            return self._to_json_string({
                "isError": True, 
                "error": "Şehir adı gerekli."
            })
        
        target_city_str = str(target_city).strip()
        if not target_city_str:
            return self._to_json_string({
                "isError": True, 
                "error": "Şehir adı gerekli."
            })
        
        try:
            days = int(days)
            if days < 1 or days > 10:
                return self._to_json_string({
                    "isError": True, 
                    "error": "Gün sayısı 1 ile 10 arasında olmalıdır."  # 土耳其语：天数必须在1-10之间
                })
        except (ValueError, TypeError):
            return self._to_json_string({
                "isError": True, 
                "error": "Gün sayısı geçerli bir sayı olmalıdır."  # 土耳其语：天数必须是有效数字
            })

        try:
            url = f"{BASE_URL}/forecast.json?key={WEATHER_API_KEY}&q={target_city_str}&days={days}&lang={API_LANGUAGE}"
            response = requests.get(url, timeout=self.api_timeout)
            response.raise_for_status()
            data = response.json()
            
            forecast_days = []
            for day in data.get("forecast", {}).get("forecastday", []):
                forecast_days.append({
                    "date": day.get("date"),
                    "maxTemp": day.get("day", {}).get("maxtemp_c", 0),
                    "minTemp": day.get("day", {}).get("mintemp_c", 0),
                    "condition": day.get("day", {}).get("condition", {}).get("text", "Unknown"),
                    "icon": day.get("day", {}).get("condition", {}).get("icon"),
                    "chanceOfRain": day.get("day", {}).get("daily_chance_of_rain", 0),
                    "chanceOfSnow": day.get("day", {}).get("daily_chance_of_snow", 0),
                    "maxWindKph": day.get("day", {}).get("maxwind_kph"),
                    "avgHumidity": day.get("day", {}).get("avghumidity"),
                    "uvIndex": day.get("day", {}).get("uv")
                })
            
            result = {
                "city": data.get("location", {}).get("name") or target_city_str,  # 保留city字段
                "location": data.get("location", {}).get("name") or target_city_str,
                "country": data.get("location", {}).get("country"),
                "region": data.get("location", {}).get("region"),
                "forecast": forecast_days
            }
            
            response_str = self._to_json_string(result)
            if len(response_str) > self.max_chars:
                raise ValueError(f"Response too large ({len(response_str)} chars), max allowed {self.max_chars}.")
            
            return response_str
        except Exception as exc:
            return self._to_json_string({
                "isError": True, 
                "error": "Agent hatası.",
                "detail": str(exc),
                "city": target_city_str,
                "location": target_city_str,
                "days": days
            })

    def get_weather_string(self, city: str) -> str:
        """
        新增方法：直接返回TS版要求的土耳其语字符串（Şehir: ${city}, Hava Durumu: ${weather}）
        对齐src/weather-agent.ts的返回格式
        """
        # 先调用核心方法获取数据
        weather_json = self.get_current_weather(city=city)
        weather_data = json.loads(weather_json)
        
        # 如果是错误，直接返回错误信息
        if weather_data.get("isError"):
            return weather_json
        
        # 组装土耳其语字符串（对齐src/weather-agent.ts）
        result_str = f"Şehir: {weather_data['city']}, Hava Durumu: {weather_data['weather']}"
        return self._to_json_string({"result": result_str})

    def search_locations(self, query: str) -> str:
        """保持原逻辑"""
        query = str(query).strip()
        if not query:
            return self._to_json_string({
                "isError": True, 
                "error": "Sorgu boş olamaz."  # 土耳其语：查询不能为空
            })

        try:
            url = f"{BASE_URL}/search.json?key={WEATHER_API_KEY}&q={query}"
            response = requests.get(url, timeout=self.api_timeout)
            response.raise_for_status()
            data = response.json()
            
            locations = []
            for location in data:
                locations.append({
                    "name": location.get("name"),
                    "region": location.get("region"),
                    "country": location.get("country"),
                    "lat": location.get("lat"),
                    "lon": location.get("lon"),
                    "url": location.get("url")
                })
            
            result = {"locations": locations}
            response_str = self._to_json_string(result)
            
            if len(response_str) > self.max_chars:
                raise ValueError(f"Response too large ({len(response_str)} chars), max allowed {self.max_chars}.")
            
            return response_str
        except Exception as exc:
            return self._to_json_string({
                "isError": True, 
                "error": "Agent hatası.",
                "detail": str(exc),
                "query": query
            })

"""
==================== 实例化 & 工具注册（适配TS版工具名） ====================
"""
weather_data = WeatherData()

# -------------------------- 注册工具函数：get_live_temp（对齐src/mastra/tools/index.ts的工具名） --------------------------
@registry.tool()
def weather_data_get_live_temp(city: str, uid: Optional[str] = None) -> str:
    """
    对齐src/mastra/tools/index.ts调用的get_live_temp工具
    直接返回TS版要求的土耳其语字符串（兼容src/weather-agent.ts）
    """
    return weather_data.get_weather_string(city)

# -------------------------- 兼容旧工具名：get_current_weather（保留，兼容weather-tool.ts） --------------------------
@registry.tool()
def weather_data_get_current_weather(location: str, uid: Optional[str] = None) -> str:
    return weather_data.get_current_weather(location=location)

# -------------------------- 兼容旧工具名：get_weather_forecast（保留） --------------------------
@registry.tool()
def weather_data_get_weather_forecast(location: str, days: int = 3, uid: Optional[str] = None) -> str:
    return weather_data.get_weather_forecast(location=location, days=days)

# -------------------------- 注册工具函数：search_locations（保留） --------------------------
@registry.tool()
def weather_data_search_locations(query: str, uid: Optional[str] = None) -> str:
    return weather_data.search_locations(query)

"""
==================== 导出核心实例（兼容框架导入） ====================
"""
__all__ = [
    "weather_data",
    "weather_data_get_live_temp",
    "weather_data_get_current_weather",
    "weather_data_get_weather_forecast",
    "weather_data_search_locations"
]