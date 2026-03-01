from __future__ import annotations

from datetime import datetime, timezone

from ..utils import fetch_json
from .base import BaseCollector


class WeatherCollector(BaseCollector):
    def _resolve_location(self) -> tuple[float, float, str, dict]:
        fallback_lat = self.app.config["WEATHER_LAT"]
        fallback_lon = self.app.config["WEATHER_LON"]
        city = self.app.config.get("WEATHER_CITY", "Lajeado")
        state = self.app.config.get("WEATHER_STATE", "Rio Grande do Sul")
        country_code = self.app.config.get("WEATHER_COUNTRY_CODE", "BR")

        geo_url = (
            "https://geocoding-api.open-meteo.com/v1/search"
            f"?name={city}"
            f"&country_code={country_code}"
            "&count=10"
            "&language=pt"
        )

        resolved_name = f"{city}, RS"
        resolved_meta: dict = {
            "name": city,
            "admin1": state,
            "country_code": country_code,
            "from": "fallback",
        }

        try:
            geo_data = fetch_json(geo_url)
            if isinstance(geo_data, dict):
                results = geo_data.get("results")
            else:
                results = None

            if isinstance(results, list) and results:
                state_lower = state.lower()

                def _score(result: dict) -> tuple[int, int]:
                    admin1 = str(result.get("admin1", "")).lower()
                    score_state = 1 if state_lower in admin1 else 0
                    score_country = (
                        1
                        if result.get("country_code") == country_code
                        else 0
                    )
                    return (score_state, score_country)

                best = max(
                    (item for item in results if isinstance(item, dict)),
                    key=_score,
                )

                lat = float(best.get("latitude", fallback_lat))
                lon = float(best.get("longitude", fallback_lon))
                resolved_city = best.get("name", city)
                admin1 = best.get("admin1", state)
                resolved_name = f"{resolved_city}, {admin1}"
                resolved_meta = {
                    "name": resolved_city,
                    "admin1": admin1,
                    "country_code": best.get("country_code", country_code),
                    "elevation": best.get("elevation"),
                    "timezone": best.get("timezone"),
                    "from": "geocoding",
                }
                return lat, lon, resolved_name, resolved_meta
        except Exception as exc:
            self.logger.warning("Falha ao resolver geolocalização: %s", exc)

        return fallback_lat, fallback_lon, resolved_name, resolved_meta

    def run(self) -> int:
        lat, lon, city, location_meta = self._resolve_location()
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,relative_humidity_2m,"
            "apparent_temperature,precipitation,"
            "wind_speed_10m,weather_code"
            "&daily=weather_code,temperature_2m_max,"
            "temperature_2m_min,precipitation_probability_max,"
            "precipitation_sum,wind_speed_10m_max,sunrise,sunset"
            "&forecast_days=7"
            "&timezone=America/Sao_Paulo"
        )
        try:
            data = fetch_json(url)
            if not isinstance(data, dict):
                raise ValueError("Resposta inválida de clima")

            current = data.get("current", {})
            daily = data.get("daily", {})
            if not isinstance(current, dict):
                current = {}
            if not isinstance(daily, dict):
                daily = {}

            times = daily.get("time", [])

            def _value_at(values: list | None, index: int):
                if not isinstance(values, list) or index >= len(values):
                    return None
                return values[index]

            daily_items = []
            for index, day in enumerate(times):
                daily_items.append(
                    {
                        "date": day,
                        "weather_code": _value_at(
                            daily.get("weather_code"),
                            index,
                        ),
                        "temp_max": _value_at(
                            daily.get("temperature_2m_max"),
                            index,
                        ),
                        "temp_min": _value_at(
                            daily.get("temperature_2m_min"),
                            index,
                        ),
                        "precip_prob_max": _value_at(
                            daily.get("precipitation_probability_max"),
                            index,
                        ),
                        "precip_sum": _value_at(
                            daily.get("precipitation_sum"),
                            index,
                        ),
                        "wind_speed_max": _value_at(
                            daily.get("wind_speed_10m_max"),
                            index,
                        ),
                        "sunrise": _value_at(daily.get("sunrise"), index),
                        "sunset": _value_at(daily.get("sunset"), index),
                    }
                )

            today = daily_items[0] if daily_items else {}
            current_temp = current.get("temperature_2m", "--")
            title = f"Clima em {city}: {current_temp}°C"
            summary = (
                "Agora: "
                f"{current.get('apparent_temperature', '--')}°C sensação, "
                f"{current.get('relative_humidity_2m', '--')}% umidade, "
                f"vento {current.get('wind_speed_10m', '--')} km/h. "
                "Hoje: min "
                f"{today.get('temp_min', '--')}°C / "
                f"máx {today.get('temp_max', '--')}°C."
            )

            item = {
                "item_type": "weather",
                "source": "Open-Meteo",
                "title": title,
                "url": "https://open-meteo.com/",
                "summary": summary,
                "image_url": None,
                "published_at": datetime.now(timezone.utc).isoformat(),
                "extra": {
                    "city": city,
                    "latitude": lat,
                    "longitude": lon,
                    "location": location_meta,
                    "current": current,
                    "daily": daily_items,
                },
            }
            return self.save_items([item])
        except Exception as exc:
            self.logger.warning("Falha ao coletar clima: %s", exc)
            return 0
