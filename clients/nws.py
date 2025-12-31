"""National Weather Service API client."""

from datetime import datetime, timedelta
from typing import Optional
import re

from .base import BaseClient
from models import Forecast
from errors import NWSAPIError


NWS_BASE_URL = "https://api.weather.gov"

# NWS station IDs and grid points for each city
# Kalshi uses these specific locations for settlement
CITY_STATIONS = {
    "NYC": {
        "station": "KNYC",  # Central Park
        "grid": ("OKX", 33, 37),  # office, gridX, gridY
        "name": "Central Park, NY",
    },
    "CHICAGO": {
        "station": "KMDW",  # Midway Airport
        "grid": ("LOT", 75, 73),
        "name": "Chicago Midway Airport",
    },
    "MIAMI": {
        "station": "KMIA",  # Miami International
        "grid": ("MFL", 109, 50),
        "name": "Miami International Airport",
    },
    "AUSTIN": {
        "station": "KAUS",  # Austin-Bergstrom
        "grid": ("EWX", 156, 91),
        "name": "Austin-Bergstrom Airport",
    },
    "DENVER": {
        "station": "KDEN",  # Denver International
        "grid": ("BOU", 62, 60),
        "name": "Denver International Airport",
    },
    "HOUSTON": {
        "station": "KIAH",  # George Bush Intercontinental
        "grid": ("HGX", 65, 97),
        "name": "Houston IAH Airport",
    },
    "LOS_ANGELES": {
        "station": "KLAX",  # LAX
        "grid": ("LOX", 149, 48),
        "name": "Los Angeles International Airport",
    },
    "PHILADELPHIA": {
        "station": "KPHL",  # Philadelphia International
        "grid": ("PHI", 49, 75),
        "name": "Philadelphia International Airport",
    },
}


class NWSClient(BaseClient):
    """Client for National Weather Service API."""

    def __init__(self, verbose: bool = False):
        super().__init__(
            base_url=NWS_BASE_URL,
            verbose=verbose,
            rate_limit=5,  # NWS is more restrictive
        )
        # NWS requires User-Agent
        self.user_agent = "KalshiWeatherBot/1.0 (weather trading bot)"

    def _get_nws(self, path: str, params: Optional[dict] = None) -> dict:
        """GET request with NWS headers."""
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/geo+json",
        }
        response = self.get(path, headers=headers, params=params)

        if response.status_code != 200:
            raise NWSAPIError(f"NWS API error: {response.status_code} - {response.text[:200]}")

        return response.json()

    def get_forecast(self, city: str, target_date: Optional[datetime] = None) -> Forecast:
        """
        Get temperature forecast for a city.

        Args:
            city: City name (e.g., "NYC", "CHICAGO")
            target_date: Date to forecast (default: tomorrow)

        Returns:
            Forecast object with high/low temps
        """
        if target_date is None:
            target_date = datetime.now() + timedelta(days=1)

        city_upper = city.upper().replace(" ", "_")
        if city_upper not in CITY_STATIONS:
            raise NWSAPIError(f"Unknown city: {city}. Available: {list(CITY_STATIONS.keys())}")

        station_info = CITY_STATIONS[city_upper]
        office, grid_x, grid_y = station_info["grid"]

        # Get gridpoint forecast
        path = f"/gridpoints/{office}/{grid_x},{grid_y}/forecast"
        data = self._get_nws(path)

        # Parse forecast periods
        periods = data.get("properties", {}).get("periods", [])

        high_temp = None
        low_temp = None

        for period in periods:
            start_time = period.get("startTime", "")
            if not start_time:
                continue

            # Parse date from ISO format
            try:
                period_date = datetime.fromisoformat(start_time.replace("Z", "+00:00")).date()
            except ValueError:
                continue

            if period_date != target_date.date():
                continue

            temp = period.get("temperature")
            is_daytime = period.get("isDaytime", True)

            if temp is not None:
                if is_daytime and (high_temp is None or temp > high_temp):
                    high_temp = temp
                elif not is_daytime and (low_temp is None or temp < low_temp):
                    low_temp = temp

        if high_temp is None:
            # Fallback: try hourly forecast
            high_temp, low_temp = self._get_hourly_temps(office, grid_x, grid_y, target_date)

        if high_temp is None:
            raise NWSAPIError(f"No forecast available for {city} on {target_date.date()}")

        return Forecast(
            station=station_info["station"],
            date=target_date,
            high_temp=high_temp,
            low_temp=low_temp if low_temp else high_temp - 15,  # Rough estimate if missing
            source="NWS",
            fetched_at=datetime.now(),
        )

    def _get_hourly_temps(
        self,
        office: str,
        grid_x: int,
        grid_y: int,
        target_date: datetime
    ) -> tuple[Optional[float], Optional[float]]:
        """Get high/low from hourly forecast as fallback."""
        path = f"/gridpoints/{office}/{grid_x},{grid_y}/forecast/hourly"

        try:
            data = self._get_nws(path)
        except NWSAPIError:
            return None, None

        periods = data.get("properties", {}).get("periods", [])

        temps_for_day = []
        for period in periods:
            start_time = period.get("startTime", "")
            try:
                period_date = datetime.fromisoformat(start_time.replace("Z", "+00:00")).date()
            except ValueError:
                continue

            if period_date == target_date.date():
                temp = period.get("temperature")
                if temp is not None:
                    temps_for_day.append(temp)

        if not temps_for_day:
            return None, None

        return max(temps_for_day), min(temps_for_day)

    def get_current_conditions(self, city: str) -> dict:
        """Get current weather conditions for a city."""
        city_upper = city.upper().replace(" ", "_")
        if city_upper not in CITY_STATIONS:
            raise NWSAPIError(f"Unknown city: {city}")

        station = CITY_STATIONS[city_upper]["station"]
        path = f"/stations/{station}/observations/latest"

        data = self._get_nws(path)
        props = data.get("properties", {})

        # Temperature comes in Celsius, convert to Fahrenheit
        temp_c = props.get("temperature", {}).get("value")
        temp_f = (temp_c * 9/5 + 32) if temp_c is not None else None

        return {
            "station": station,
            "timestamp": props.get("timestamp"),
            "temperature_f": temp_f,
            "description": props.get("textDescription"),
        }

    def estimate_forecast_uncertainty(self, city: str, days_ahead: int = 1) -> float:
        """
        Estimate forecast uncertainty (standard deviation) based on days ahead.

        NWS forecasts are typically:
        - 1 day: ±2-3°F
        - 2 days: ±3-4°F
        - 3+ days: ±4-6°F
        """
        base_uncertainty = {
            0: 1.5,
            1: 2.5,
            2: 3.5,
            3: 4.5,
            4: 5.0,
            5: 5.5,
        }
        return base_uncertainty.get(days_ahead, 6.0)
