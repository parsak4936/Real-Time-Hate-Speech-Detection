import requests
from datetime import datetime

def execute_weather_time(params):
    print(f"-> [Weather Agent] Fetching highly detailed real-time telemetry...")
    
    # 1. Get the Agent's local server time
    server_time = datetime.now().strftime("%A, %B %d, %Y at %H:%M:%S")
    
    location = params.get("location")
    
    try:
        # 2A. If the AI specifies a location, search for it
        if location:
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={location}&count=1&language=en&format=json"
            geo_resp = requests.get(geo_url, timeout=5).json()
            
            if "results" not in geo_resp:
                return f"Server Time: {server_time}\nError: Could not find coordinates for '{location}'."
            
            lat = geo_resp["results"][0]["latitude"]
            lon = geo_resp["results"][0]["longitude"]
            country = geo_resp["results"][0].get("country", "Unknown")
            city_name = geo_resp["results"][0]["name"]
            location_tag = f"{city_name}, {country}"

        # 2B. If NO location is specified, auto-detect using IP!
        else:
            print("-> [System] No city provided. Auto-detecting via IP...")
            ip_url = "http://ip-api.com/json/"
            ip_resp = requests.get(ip_url, timeout=5).json()
            
            if ip_resp.get("status") != "success":
                return f"Server Time: {server_time}\n(Could not auto-detect location)."
            
            lat = ip_resp["lat"]
            lon = ip_resp["lon"]
            city_name = ip_resp["city"]
            country = ip_resp["country"]
            location_tag = f"{city_name}, {country} (Auto-detected via IP)"

        # 3. Fetch the MAXIMAL weather details using the coordinates (with timezone=auto)
        # We ask for: temperature, relative_humidity, apparent_temperature, precipitation, wind_speed, wind_gusts, surface_pressure, cloud_cover
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,"
            f"wind_speed_10m,wind_gusts_10m,surface_pressure,cloud_cover,is_day"
            f"&timezone=auto"
        )
        weather_resp = requests.get(weather_url, timeout=5).json()
        
        current = weather_resp.get("current", {})
        units = weather_resp.get("current_units", {})
        
        # 4. Extracting all the rich data points
        # Open-Meteo returns time in ISO format (e.g., 2026-04-13T15:00)
        local_time_raw = current.get("time", "Unknown") 
        if local_time_raw != "Unknown":
            # Clean up the API's time string to look nice
            local_time_obj = datetime.strptime(local_time_raw, "%Y-%m-%dT%H:%M")
            local_time_str = local_time_obj.strftime("%A, %B %d, %Y at %I:%M %p")
        else:
            local_time_str = "Unknown"

        temp = current.get("temperature_2m", "N/A")
        feels_like = current.get("apparent_temperature", "N/A")
        humidity = current.get("relative_humidity_2m", "N/A")
        precip = current.get("precipitation", "N/A")
        wind = current.get("wind_speed_10m", "N/A")
        gusts = current.get("wind_gusts_10m", "N/A")
        pressure = current.get("surface_pressure", "N/A")
        cloud_cover = current.get("cloud_cover", "N/A")
        is_day = "Daytime" if current.get("is_day") == 1 else "Nighttime"
        
        # 5. Format the Ultimate Weather Payload for the Leader AI
        detailed_report = (
            f"--- LOCATION & TIME ---\n"
            f"Target Location: {location_tag}\n"
            f"Local Clock (Target City): {local_time_str}\n"
            f"Agent Server Clock: {server_time}\n"
            f"\n--- WEATHER TELEMETRY ---\n"
            f"Condition: {is_day} with {cloud_cover}% Cloud Cover\n"
            f"Actual Temperature: {temp}{units.get('temperature_2m', '°C')}\n"
            f"Feels Like (Apparent): {feels_like}{units.get('apparent_temperature', '°C')}\n"
            f"Relative Humidity: {humidity}{units.get('relative_humidity_2m', '%')}\n"
            f"Precipitation: {precip}{units.get('precipitation', 'mm')}\n"
            f"Wind Speed: {wind}{units.get('wind_speed_10m', 'km/h')} (Gusts up to {gusts}{units.get('wind_gusts_10m', 'km/h')})\n"
            f"Atmospheric Pressure: {pressure}{units.get('surface_pressure', 'hPa')}\n"
        )
        
        return detailed_report
        
    except Exception as e:
        return f"Server Time: {server_time}\nWeather API Request Failed: {str(e)}"