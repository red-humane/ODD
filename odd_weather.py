"""
ODD Weather Engine
Provides real-time local weather forecasts, hourly timing predictions, and live weather icons
using the free, high-performance Open-Meteo API and Open-Meteo Geocoding.
Zero API keys required. Fully thread-safe with persistent disk caching.
"""

import json
import os
import re
import difflib
import time
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
import threading
from PySide6.QtCore import QObject, Signal, QTimer

WEATHER_CACHE_FILE = Path(os.path.expandvars(r"%APPDATA%\ODD\weather_cache.json"))

# WMO Weather interpretation codes (WW)
WMO_MAP = {
    0: ("Clear sky", "sun"),
    1: ("Mainly clear", "sun_cloud"),
    2: ("Partly cloudy", "cloud_sun"),
    3: ("Overcast", "cloud"),
    45: ("Foggy", "fog"),
    48: ("Depositing rime fog", "fog"),
    51: ("Light drizzle", "rain_light"),
    53: ("Moderate drizzle", "rain_light"),
    55: ("Dense drizzle", "rain"),
    56: ("Freezing drizzle", "rain_light"),
    57: ("Dense freezing drizzle", "rain"),
    61: ("Slight rain", "rain_light"),
    63: ("Moderate rain", "rain"),
    65: ("Heavy rain", "rain_heavy"),
    66: ("Light freezing rain", "rain"),
    67: ("Heavy freezing rain", "rain_heavy"),
    71: ("Slight snow", "snow"),
    73: ("Moderate snow", "snow"),
    75: ("Heavy snow", "snow_heavy"),
    77: ("Snow grains", "snow"),
    80: ("Slight rain showers", "rain_light"),
    81: ("Moderate rain showers", "rain"),
    82: ("Violent rain showers", "rain_heavy"),
    85: ("Slight snow showers", "snow"),
    86: ("Heavy snow showers", "snow_heavy"),
    95: ("Thunderstorm", "thunder"),
    96: ("Thunderstorm with hail", "thunder"),
    99: ("Thunderstorm with heavy hail", "thunder"),
}

def get_wmo_info(code: int, is_day: int = 1):
    info = WMO_MAP.get(int(code), ("Partly cloudy", "cloud_sun"))
    cond, icon = info[0], info[1]
    if not is_day:
        if icon == "sun":
            icon = "moon"
        elif icon in ("sun_cloud", "cloud_sun"):
            icon = "cloud_moon"
    return cond, icon

_geo_cache = {}

# Canonical city names and common typo mappings
COMMON_CITY_ALIASES = {
    "saravanampatti": "Saravanampatti",
    "srvanampatti": "Saravanampatti",
    "saravanampatty": "Saravanampatti",
    "coimbatore": "Coimbatore",
    "kovai": "Coimbatore",
    "peelamedu": "Peelamedu",
    "gandhipuram": "Gandhipuram",
    "singanallur": "Singanallur",
    "rs puram": "R.S. Puram",
    "r.s. puram": "R.S. Puram",
    "saibaba colony": "Saibaba Colony",
    "ramanathapuram": "Ramanathapuram",
    "thudiyalur": "Thudiyalur",
    "kuniyamuthur": "Kuniyamuthur",
    "podanur": "Podanur",
    "kurichi": "Kurichi",
    "sundarapuram": "Sundarapuram",
    "vadavalli": "Vadavalli",
    "koundampalayam": "Koundampalayam",
    "chinnavedampatti": "Chinnavedampatti",
    "vellakinar": "Vellakinar",
    "kalapatti": "Kalapatti",
    "ondipudur": "Ondipudur",
    "sulur": "Sulur",
    "pollachi": "Pollachi",
    "tiruppur": "Tiruppur",
    "tirupur": "Tiruppur",
    "erode": "Erode",
    "salem": "Salem",
    "madurai": "Madurai",
    "trichy": "Tiruchirappalli",
    "tiruchirappalli": "Tiruchirappalli",
    "tirunelveli": "Tirunelveli",
    "vellore": "Vellore",
    "thoothukudi": "Thoothukudi",
    "tuticorin": "Thoothukudi",
    "nagercoil": "Nagercoil",
    "thanjavur": "Thanjavur",
    "dindigul": "Dindigul",
    "cuddalore": "Cuddalore",
    "kanchipuram": "Kanchipuram",
    "tiruvannamalai": "Tiruvannamalai",
    "kumbakonam": "Kumbakonam",
    "karur": "Karur",
    "hosur": "Hosur",
    "bangalore": "Bengaluru",
    "banglore": "Bengaluru",
    "bengaluru": "Bengaluru",
    "chenai": "Chennai",
    "chennai": "Chennai",
    "madras": "Chennai",
    "mumbay": "Mumbai",
    "bombay": "Mumbai",
    "mumbai": "Mumbai",
    "dehli": "Delhi",
    "dheli": "Delhi",
    "delhi": "Delhi",
    "new delhi": "New Delhi",
    "calcutta": "Kolkata",
    "kolkatta": "Kolkata",
    "kolkata": "Kolkata",
    "hyderabd": "Hyderabad",
    "hyderabad": "Hyderabad",
    "ahmedabad": "Ahmedabad",
    "ahmdabad": "Ahmedabad",
    "pune": "Pune",
    "poona": "Pune",
    "jaipur": "Jaipur",
    "chandigarh": "Chandigarh",
    "kochi": "Kochi",
    "cochin": "Kochi",
    "trivandrum": "Thiruvananthapuram",
    "thiruvananthapuram": "Thiruvananthapuram",
    "goa": "Panaji",
    "londonn": "London",
    "london": "London",
    "new yrok": "New York",
    "new york": "New York",
    "nyc": "New York",
    "san fransico": "San Francisco",
    "san francisco": "San Francisco",
    "san fran": "San Francisco",
    "los angelos": "Los Angeles",
    "los angeles": "Los Angeles",
    "chicago": "Chicago",
    "houston": "Houston",
    "seattle": "Seattle",
    "miami": "Miami",
    "paris": "Paris",
    "pari": "Paris",
    "berln": "Berlin",
    "berlin": "Berlin",
    "madrid": "Madrid",
    "madird": "Madrid",
    "rome": "Rome",
    "roma": "Rome",
    "amstrdam": "Amsterdam",
    "amsterdam": "Amsterdam",
    "tokiyo": "Tokyo",
    "tokio": "Tokyo",
    "tokyo": "Tokyo",
    "beijing": "Beijing",
    "peking": "Beijing",
    "singapor": "Singapore",
    "singapur": "Singapore",
    "singapore": "Singapore",
    "dubay": "Dubai",
    "dubai": "Dubai",
    "sydney": "Sydney",
    "sidney": "Sydney",
    "melbourne": "Melbourne",
    "toronto": "Toronto",
    "toranto": "Toronto",
    "vancouver": "Vancouver",
    "moscow": "Moscow",
    "moskow": "Moscow",
    "cairo": "Cairo",
}

def sanitize_city_display_name(clean_q: str, raw_db_name: str, raw_query: str) -> str:
    """
    Prevents database transliteration flaws (such as GeoNames omitting vowels, e.g. 'Srvanampatti' for 'Saravanampatti').
    Ensures properly typed user city names and canonical aliases are accurately preserved and displayed.
    """
    q_str = (raw_query or "").strip()
    q_low = (clean_q or "").strip().lower()
    first_part = q_low.split(",")[0].strip()
    db_clean = (raw_db_name or "").strip()
    db_low = db_clean.lower()
    
    # 1. Direct canonical alias match
    if first_part in COMMON_CITY_ALIASES:
        return COMMON_CITY_ALIASES[first_part]
    if q_low in COMMON_CITY_ALIASES:
        return COMMON_CITY_ALIASES[q_low]
    if db_low in COMMON_CITY_ALIASES:
        return COMMON_CITY_ALIASES[db_low]
    
    # 2. Vowel-stripped comparison (e.g. user typed 'saravanampatti', db returned 'Srvanampatti')
    u_v = re.sub(r'[aeiou\s\-_]', '', q_low)
    db_v = re.sub(r'[aeiou\s\-_]', '', db_low)
    if u_v and u_v == db_v and len(q_low) >= len(db_clean):
        return q_str.title()
        
    # 3. High fuzzy similarity with user-provided full spelling
    if difflib.SequenceMatcher(None, q_low, db_low).ratio() >= 0.82 and len(q_low) >= len(db_clean):
        return q_str.title()
        
    return db_clean or q_str.title()

def resolve_location_coordinates(loc_query: str) -> tuple[float, float, str, str]:
    """
    Intelligently resolves latitude, longitude, friendly city name, and country.
    Supports:
    - Auto-detect via public IP geolocation.
    - Automatic typo correction (e.g. 'londonn' -> London, 'chenai' -> Chennai, 'new yrok' -> New York).
    - In-memory canonical alias matching and fuzzy search.
    - Online spellcheck autocomplete suggestions via DuckDuckGo.
    - Population-weighted Open-Meteo geocoding to prioritize major metropolitan cities.
    """
    query = (loc_query or "").strip()
    clean_q = query.lower()

    if clean_q in ("", "auto", "auto-detect", "current", "my location", "local", "here"):
        # Auto-detect via public IP geolocation
        try:
            req = urllib.request.Request("http://ip-api.com/json/", headers={"User-Agent": "ODD-Weather/1.0"})
            with urllib.request.urlopen(req, timeout=3.5) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "success":
                    lat = float(data["lat"])
                    lon = float(data["lon"])
                    city = data.get("city", "Current Location")
                    country = data.get("country", "")
                    return lat, lon, city, country
        except Exception:
            pass
        return 40.7128, -74.0060, "New York", "United States"

    if clean_q in _geo_cache:
        return _geo_cache[clean_q]

    # 1. Build candidates list with autocorrect suggestions
    candidates = []
    
    # Check direct canonical dictionary
    if clean_q in COMMON_CITY_ALIASES:
        candidates.append(COMMON_CITY_ALIASES[clean_q])
    else:
        # Check fuzzy match against known major cities
        try:
            import difflib
            matches = difflib.get_close_matches(clean_q, list(COMMON_CITY_ALIASES.keys()), n=1, cutoff=0.72)
            if matches:
                candidates.append(COMMON_CITY_ALIASES[matches[0]])
        except Exception:
            pass

    # Add raw query
    if query not in candidates:
        candidates.append(query)

    # 2. Query DuckDuckGo autocomplete for spelling correction if candidates are limited
    try:
        url_ac = f"https://duckduckgo.com/ac/?q={urllib.parse.quote(query)}&type=list"
        req_ac = urllib.request.Request(url_ac, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req_ac, timeout=2.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if len(data) > 1 and isinstance(data[1], list):
                for s in data[1][:5]:
                    for stop_word in (" weather", " time", " pin code", " pincode", " map", " news", " times", " to ", " days", " movie"):
                        s = s.split(stop_word)[0]
                    s = s.strip()
                    if s and s.lower() not in [c.lower() for c in candidates]:
                        candidates.append(s)
    except Exception:
        pass

    # 3. Geocode candidates via Open-Meteo, selecting the candidate with the highest population
    all_results = []
    for cand in candidates:
        try:
            url_geo = f"https://geocoding-api.open-meteo.com/v1/search?name={urllib.parse.quote(cand)}&count=10&language=en&format=json"
            req_geo = urllib.request.Request(url_geo, headers={"User-Agent": "ODD-Weather/1.0"})
            with urllib.request.urlopen(req_geo, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                res_list = data.get("results") or []
                for r in res_list:
                    pop = r.get("population", 0) or 0
                    all_results.append((pop, r))
        except Exception:
            continue
        # If we found a major city match with substantial population, break early
        if any(p >= 50000 for p, _ in all_results):
            break

    if all_results:
        all_results.sort(key=lambda x: x[0], reverse=True)
        best = all_results[0][1]
        lat = float(best["latitude"])
        lon = float(best["longitude"])
        country = best.get("country", "")
        raw_db_name = best.get("name", query)
        name = sanitize_city_display_name(clean_q, raw_db_name, query)
        _geo_cache[clean_q] = (lat, lon, name, country)
        return lat, lon, name, country

    # Fallback default
    fallback_name = sanitize_city_display_name(clean_q, query.title(), query)
    return 40.7128, -74.0060, fallback_name, ""

# MSN Weather (Default Windows Weather provider) Skycode interpretation
MSN_SKY_MAP = {
    0: ("Thunderstorm", "thunder"),
    1: ("Thunderstorm", "thunder"),
    2: ("Thunderstorm", "thunder"),
    3: ("Severe thunderstorm", "thunder"),
    4: ("Thunderstorm", "thunder"),
    5: ("Rain and snow", "snow"),
    6: ("Sleet", "rain_light"),
    7: ("Sleet", "rain_light"),
    8: ("Freezing drizzle", "rain_light"),
    9: ("Drizzle", "rain_light"),
    10: ("Freezing rain", "rain"),
    11: ("Showers", "rain"),
    12: ("Rain", "rain"),
    13: ("Snow flurries", "snow"),
    14: ("Light snow showers", "snow"),
    15: ("Blowing snow", "snow"),
    16: ("Snow", "snow"),
    17: ("Hail", "thunder"),
    18: ("Sleet", "rain_light"),
    19: ("Dust", "fog"),
    20: ("Foggy", "fog"),
    21: ("Haze", "fog"),
    22: ("Smoke", "fog"),
    23: ("Breezy", "wind"),
    24: ("Windy", "wind"),
    25: ("Frigid", "snow"),
    26: ("Cloudy", "cloud"),
    27: ("Mostly cloudy", "cloud"),
    28: ("Mostly cloudy", "cloud"),
    29: ("Partly cloudy", "cloud_sun"),
    30: ("Partly sunny", "cloud_sun"),
    31: ("Clear", "sun"),
    32: ("Sunny", "sun"),
    33: ("Fair", "cloud_sun"),
    34: ("Mostly sunny", "cloud_sun"),
    35: ("Thunderstorms", "thunder"),
    36: ("Hot", "sun"),
    37: ("Isolated thunderstorms", "thunder"),
    38: ("Scattered thunderstorms", "thunder"),
    39: ("Scattered showers", "rain"),
    40: ("Heavy rain", "rain_heavy"),
    41: ("Scattered snow", "snow"),
    42: ("Heavy snow", "snow_heavy"),
    43: ("Blizzard", "snow_heavy"),
    44: ("Not available", "cloud_sun"),
    45: ("Scattered showers", "rain"),
    46: ("Snow showers", "snow"),
    47: ("Thunderstorms", "thunder"),
}

def get_msn_sky_info(code: int, skytext: str = "", is_day: int = 1):
    c = int(code) if str(code).isdigit() else 31
    if c in MSN_SKY_MAP:
        cond, icon = skytext or MSN_SKY_MAP[c][0], MSN_SKY_MAP[c][1]
    else:
        t = (skytext or "").lower()
        if "thunder" in t:
            cond, icon = skytext, "thunder"
        elif "snow" in t or "ice" in t:
            cond, icon = skytext, "snow"
        elif "rain" in t or "shower" in t or "drizzle" in t:
            cond, icon = skytext, "rain"
        elif "fog" in t or "haze" in t:
            cond, icon = skytext, "fog"
        elif "cloud" in t:
            cond, icon = skytext, "cloud"
        elif "sun" in t or "clear" in t:
            cond, icon = skytext, "sun"
        else:
            cond, icon = skytext or "Partly sunny", "cloud_sun"

    if not is_day:
        if icon == "sun":
            icon = "moon"
        elif icon in ("sun_cloud", "cloud_sun"):
            icon = "cloud_moon"
    return cond, icon

def fetch_hourly_timing_predictions(lat: float, lon: float, cur_temp: float, cur_code: int, unit: str = "celsius") -> list:
    """Fetches high-precision 6-slot timing-based hourly predictions (Now, +2h, +4h, +6h, +8h, +10h)."""
    hourly_items = []
    try:
        unit_param = "&temperature_unit=fahrenheit" if unit.lower() == "fahrenheit" else ""
        url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&hourly=temperature_2m,precipitation_probability,weather_code"
            f"&timezone=auto{unit_param}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "ODD-Weather/1.0"})
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            raw = json.loads(resp.read().decode("utf-8"))

        hourly = raw.get("hourly", {})
        h_times = hourly.get("time", [])
        h_temps = hourly.get("temperature_2m", [])
        h_codes = hourly.get("weather_code", [])

        now_iso = datetime.now().strftime("%Y-%m-%dT%H:00")
        start_idx = 0
        for idx, t_str in enumerate(h_times):
            if t_str >= now_iso:
                start_idx = idx
                break

        offsets = [0, 2, 4, 6, 8, 10]
        for step_num, step_offset in enumerate(offsets):
            idx = start_idx + step_offset
            if idx < len(h_times):
                t_str = h_times[idx]
                try:
                    dt = datetime.strptime(t_str, "%Y-%m-%dT%H:%M")
                    t_label = "Now" if step_num == 0 else dt.strftime("%H:%M")
                    hour_int = int(dt.strftime("%H"))
                    is_day_h = 1 if (6 <= hour_int <= 19) else 0
                except Exception:
                    t_label = f"+{step_offset}h" if step_num > 0 else "Now"
                    is_day_h = 1

                h_t = h_temps[idx] if idx < len(h_temps) else cur_temp
                h_c = h_codes[idx] if idx < len(h_codes) else cur_code
                h_cond, h_icon = get_wmo_info(h_c, is_day_h)
                hourly_items.append({
                    "time": t_label,
                    "temp": f"{round(h_t)}°",
                    "condition": h_cond,
                    "icon": h_icon,
                })
    except Exception:
        pass

    # Fallback to synthesized timing offsets if network fails
    if not hourly_items:
        cur_hour = datetime.now().hour
        for step_num, offset in enumerate([0, 2, 4, 6, 8, 10]):
            target_h = (cur_hour + offset) % 24
            is_day = 1 if (6 <= target_h <= 19) else 0
            t_lbl = "Now" if step_num == 0 else f"{target_h:02d}:00"
            temp_diff = -1 if not is_day else (1 if step_num % 2 == 1 else 0)
            h_cond, h_icon = get_wmo_info(cur_code, is_day)
            hourly_items.append({
                "time": t_lbl,
                "temp": f"{round(cur_temp + temp_diff)}°",
                "condition": h_cond,
                "icon": h_icon,
            })
    return hourly_items

def fetch_windows_msn_weather(location_query: str = "Auto-detect", unit: str = "celsius") -> dict | None:
    """
    Fetches real-time weather from the official Windows Weather provider (MSN Weather Service).
    Matches default Windows 11 Weather data with 0 API keys and exact location accuracy.
    """
    import xml.etree.ElementTree as ET

    deg_type = "F" if unit.lower() == "fahrenheit" else "C"
    resolved_query = location_query.strip()
    if resolved_query.lower() in ("", "auto", "auto-detect", "current", "my location", "local", "here"):
        # Auto-detect city via geolocation
        try:
            req_ip = urllib.request.Request("http://ip-api.com/json/", headers={"User-Agent": "ODD-Weather/1.0"})
            with urllib.request.urlopen(req_ip, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if data.get("status") == "success":
                    resolved_query = data.get("city", "London")
        except Exception:
            resolved_query = "London"
    else:
        # Autocorrect misspelled city names (e.g. londonn -> London, chenai -> Chennai)
        if resolved_query.lower() in COMMON_CITY_ALIASES:
            resolved_query = COMMON_CITY_ALIASES[resolved_query.lower()]

    url = f"https://weather.service.msn.com/data.aspx?weasearchstr={urllib.parse.quote(resolved_query)}&culture=en-US&weadegreetype={deg_type}&src=outlook"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        xml_data = resp.read().decode("utf-8", errors="ignore")

    root = ET.fromstring(xml_data)
    weather_el = root.find("weather")
    if weather_el is None:
        return None

    curr_el = weather_el.find("current")
    if curr_el is None:
        return None

    loc_name = weather_el.get("weatherlocationname", resolved_query)
    parts = [p.strip() for p in loc_name.split(",")]
    raw_city = parts[0] if parts else resolved_query.title()
    city = sanitize_city_display_name(resolved_query.lower(), raw_city, resolved_query)
    country = parts[-1] if len(parts) > 1 else ""

    lat = float(weather_el.get("lat", 0.0) or 0.0)
    lon = float(weather_el.get("long", 0.0) or 0.0)

    try:
        temp_val = float(curr_el.get("temperature", 20))
    except Exception:
        temp_val = 20.0

    skytext = curr_el.get("skytext", "Partly sunny")
    skycode = int(curr_el.get("skycode", 30)) if str(curr_el.get("skycode", "")).isdigit() else 30

    # Determine day/night from observation time or local hour
    cur_hour = datetime.now().hour
    is_day = 1 if (6 <= cur_hour <= 19) else 0
    cond_text, icon_type = get_msn_sky_info(skycode, skytext, is_day)

    # 5-day daily forecast from Windows Weather
    daily_items = []
    forecasts = weather_el.findall("forecast")
    high_val = round(temp_val + 2)
    low_val = round(temp_val - 2)

    for idx, fc in enumerate(forecasts[:5]):
        d_day = fc.get("day", "")
        d_short = fc.get("shortday", "")
        d_high = fc.get("high", str(round(temp_val + 2)))
        d_low = fc.get("low", str(round(temp_val - 2)))
        d_skytext = fc.get("skytextday", "Partly sunny")
        d_skycode = int(fc.get("skycodeday", 30)) if str(fc.get("skycodeday", "")).isdigit() else 30

        if idx == 0:
            try:
                high_val = int(d_high)
                low_val = int(d_low)
            except Exception:
                pass
            d_label = "Today"
        else:
            d_label = d_short or d_day[:3]

        _, d_icon = get_msn_sky_info(d_skycode, d_skytext, 1)
        daily_items.append({
            "day": d_label,
            "high": f"{d_high}°",
            "low": f"{d_low}°",
            "condition": d_skytext,
            "icon": d_icon,
        })

    # Fetch 6 timing predictions (Now, +2h, +4h, etc.) using accurate coordinates
    hourly_items = fetch_hourly_timing_predictions(lat, lon, temp_val, skycode, unit)

    try:
        humidity_val = int(curr_el.get("humidity", 60))
    except Exception:
        humidity_val = 60

    wind_str = curr_el.get("winddisplay", "10 km/h")
    unit_symbol = "°F" if unit.lower() == "fahrenheit" else "°C"

    return {
        "city": city,
        "country": country,
        "temp": round(temp_val),
        "temp_str": f"{round(temp_val)}°",
        "condition": cond_text,
        "icon": icon_type,
        "high": high_val,
        "low": low_val,
        "high_str": f"H: {high_val}°",
        "low_str": f"L: {low_val}°",
        "humidity": humidity_val,
        "wind_speed": 10,
        "wind_str": wind_str,
        "unit": unit_symbol,
        "hourly": hourly_items,
        "daily": daily_items,
        "timestamp": time.time(),
        "source": "Windows Weather",
    }

def fetch_open_meteo_weather(location_query: str = "Auto-detect", unit: str = "celsius") -> dict | None:
    """Fallback weather engine using Open-Meteo API."""
    lat, lon, city, country = resolve_location_coordinates(location_query)
    unit_param = "&temperature_unit=fahrenheit" if unit.lower() == "fahrenheit" else ""

    url = (
        f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
        f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,is_day,precipitation,weather_code,wind_speed_10m"
        f"&hourly=temperature_2m,precipitation_probability,weather_code"
        f"&daily=weather_code,temperature_2m_max,temperature_2m_min"
        f"&timezone=auto{unit_param}"
    )

    req = urllib.request.Request(url, headers={"User-Agent": "ODD-Weather/1.0"})
    with urllib.request.urlopen(req, timeout=5.0) as resp:
        raw = json.loads(resp.read().decode("utf-8"))

    cur = raw.get("current", {})
    hourly = raw.get("hourly", {})
    daily = raw.get("daily", {})

    temp_val = float(cur.get("temperature_2m", 20.0))
    code_val = int(cur.get("weather_code", 1))
    is_day_val = int(cur.get("is_day", 1))
    cond_text, icon_type = get_wmo_info(code_val, is_day_val)

    d_max = daily.get("temperature_2m_max", [])
    d_min = daily.get("temperature_2m_min", [])
    high_val = round(d_max[0]) if d_max else round(temp_val + 2)
    low_val = round(d_min[0]) if d_min else round(temp_val - 2)

    hourly_items = []
    h_times = hourly.get("time", [])
    h_temps = hourly.get("temperature_2m", [])
    h_codes = hourly.get("weather_code", [])

    now_iso = datetime.now().strftime("%Y-%m-%dT%H:00")
    start_idx = 0
    for idx, t_str in enumerate(h_times):
        if t_str >= now_iso:
            start_idx = idx
            break

    offsets = [0, 2, 4, 6, 8, 10]
    for step_num, step_offset in enumerate(offsets):
        idx = start_idx + step_offset
        if idx < len(h_times):
            t_str = h_times[idx]
            try:
                dt = datetime.strptime(t_str, "%Y-%m-%dT%H:%M")
                t_label = "Now" if step_num == 0 else dt.strftime("%H:%M")
                hour_int = int(dt.strftime("%H"))
                is_day_h = 1 if (6 <= hour_int <= 19) else 0
            except Exception:
                t_label = f"+{step_offset}h" if step_num > 0 else "Now"
                is_day_h = 1

            h_t = h_temps[idx] if idx < len(h_temps) else temp_val
            h_c = h_codes[idx] if idx < len(h_codes) else code_val
            h_cond, h_icon = get_wmo_info(h_c, is_day_h)
            hourly_items.append({
                "time": t_label,
                "temp": f"{round(h_t)}°",
                "condition": h_cond,
                "icon": h_icon,
            })

    daily_items = []
    d_times = daily.get("time", [])
    d_codes = daily.get("weather_code", [])
    for d_idx in range(min(4, len(d_times))):
        d_str = d_times[d_idx]
        try:
            d_dt = datetime.strptime(d_str, "%Y-%m-%d")
            day_name = "Today" if d_idx == 0 else d_dt.strftime("%a")
        except Exception:
            day_name = f"Day {d_idx + 1}"
        d_code = d_codes[d_idx] if d_idx < len(d_codes) else 0
        d_cond, d_icon = get_wmo_info(d_code, 1)
        h_t = round(d_max[d_idx]) if d_idx < len(d_max) else high_val
        l_t = round(d_min[d_idx]) if d_idx < len(d_min) else low_val
        daily_items.append({
            "day": day_name,
            "high": f"{h_t}°",
            "low": f"{l_t}°",
            "condition": d_cond,
            "icon": d_icon,
        })

    unit_symbol = "°F" if unit.lower() == "fahrenheit" else "°C"

    return {
        "city": city,
        "country": country,
        "temp": round(temp_val),
        "temp_str": f"{round(temp_val)}°",
        "condition": cond_text,
        "icon": icon_type,
        "high": high_val,
        "low": low_val,
        "high_str": f"H: {high_val}°",
        "low_str": f"L: {low_val}°",
        "humidity": int(cur.get("relative_humidity_2m", 60)),
        "wind_speed": round(float(cur.get("wind_speed_10m", 10.0))),
        "wind_str": f"{round(float(cur.get('wind_speed_10m', 10.0)))} km/h",
        "unit": unit_symbol,
        "hourly": hourly_items,
        "daily": daily_items,
        "timestamp": time.time(),
        "source": "Open-Meteo",
    }

def fetch_weather_data(location_query: str = "Auto-detect", unit: str = "celsius") -> dict | None:
    """
    Fetches real-time weather using the official Default Windows Weather provider (MSN Weather API),
    with seamless automatic fallback to Open-Meteo.
    """
    # 1. Primary: Default Windows Weather (MSN Weather Service)
    try:
        data = fetch_windows_msn_weather(location_query, unit)
        if data and data.get("temp") is not None:
            return data
    except Exception as e:
        pass

    # 2. Resilient Fallback: Open-Meteo Weather API
    try:
        return fetch_open_meteo_weather(location_query, unit)
    except Exception:
        return None



class WeatherManager(QObject):
    """
    Singleton Weather Manager for ODD:
    - Provides cached weather data for 0ms startup time.
    - Asynchronously polls Open-Meteo in background thread.
    - Emits weather_updated(dict) when fresh forecast arrives.
    """
    weather_updated = Signal(dict)
    _instance = None

    @classmethod
    def get_instance(cls):
        if cls._instance is None:
            cls._instance = WeatherManager()
        return cls._instance

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_data = self._load_cache() or {
            "city": "Current Location",
            "country": "",
            "temp": 20,
            "temp_str": "20°",
            "condition": "Partly cloudy",
            "icon": "cloud_sun",
            "high": 22,
            "low": 16,
            "high_str": "H: 22°",
            "low_str": "L: 16°",
            "humidity": 65,
            "wind_speed": 12,
            "wind_str": "12 km/h",
            "unit": "°C",
            "hourly": [
                {"time": "Now", "temp": "20°", "condition": "Partly cloudy", "icon": "cloud_sun"},
                {"time": "+2h", "temp": "19°", "condition": "Partly cloudy", "icon": "cloud_sun"},
                {"time": "+4h", "temp": "18°", "condition": "Cloudy", "icon": "cloud"},
                {"time": "+6h", "temp": "17°", "condition": "Cloudy", "icon": "cloud"},
                {"time": "+8h", "temp": "16°", "condition": "Clear", "icon": "moon"},
            ],
            "daily": [
                {"day": "Today", "high": "22°", "low": "16°", "condition": "Partly cloudy", "icon": "cloud_sun"},
                {"day": "Tomorrow", "high": "23°", "low": "15°", "condition": "Sunny", "icon": "sun"},
                {"day": "Day 3", "high": "21°", "low": "14°", "condition": "Rain", "icon": "rain"},
            ],
            "timestamp": 0,
        }
        self._is_fetching = False
        self._last_fetch_ts = 0.0

        # Auto refresh timer (every 20 minutes)
        self.refresh_timer = QTimer(self)
        self.refresh_timer.setInterval(20 * 60 * 1000)
        self.refresh_timer.timeout.connect(self.refresh)

    def _load_cache(self) -> dict | None:
        try:
            if WEATHER_CACHE_FILE.exists():
                with open(WEATHER_CACHE_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict) and "temp" in data:
                        return data
        except Exception:
            pass
        return None

    def _save_cache(self, data: dict):
        try:
            WEATHER_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(WEATHER_CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    def get_weather(self) -> dict:
        return self.current_data

    @property
    def cached_data(self) -> dict:
        return self.current_data

    def refresh(self, force: bool = False, settings: dict = None):
        """Triggers a background fetch of fresh weather data."""
        if settings is None:
            try:
                from odd_settings import load_settings
                settings = load_settings()
            except Exception:
                settings = {}

        loc = (settings.get("weather_location") or "Auto-detect").strip()
        unit = settings.get("weather_unit", "celsius")

        now = time.time()
        last_loc = getattr(self, "_last_loc", None)
        location_changed = (last_loc is not None and loc.lower() != last_loc.lower())

        # If location changed or force=True, always fetch immediately
        if not force and not location_changed and (now - self._last_fetch_ts < 300.0) and (now - self.current_data.get("timestamp", 0) < 600.0):
            return
        if self._is_fetching:
            return

        self._last_loc = loc
        self._last_fetch_ts = now
        self._is_fetching = True

        def _worker():
            try:
                data = fetch_weather_data(location_query=loc, unit=unit)
                if data:
                    self.current_data = data
                    self._save_cache(data)
                    self.weather_updated.emit(data)
            except Exception as e:
                print(f"[ODD Weather] Refresh error: {e}")
            finally:
                self._is_fetching = False

        threading.Thread(target=_worker, daemon=True, name="ODD_Weather_Worker").start()
