import math
import requests
from datetime import date, timedelta

OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


def geocode(location: str):
    try:
        params = {"format": "jsonv2", "limit": 1, "q": location}
        res = requests.get(NOMINATIM_URL, params=params, headers={"User-Agent": "spotter-app"}, timeout=10)
        res.raise_for_status()
        data = res.json()
        if isinstance(data, list) and data:
            item = data[0]
            return {
                "lat": float(item["lat"]),
                "lng": float(item["lon"]),
                "name": item.get("display_name", location),
            }
    except Exception:
        pass
    # Fallback minimal mock
    mocks = {
        "new york": (40.7128, -74.0060),
        "los angeles": (34.0522, -118.2437),
        "chicago": (41.8781, -87.6298),
        "dallas": (32.7767, -96.7970),
        "miami": (25.7617, -80.1918),
        "phoenix": (33.4484, -112.0740),
        "atlanta": (33.7490, -84.3880),
        "denver": (39.7392, -104.9903),
    }
    key = location.lower().split(',')[0].strip()
    lat, lng = mocks.get(key, (40.7128, -74.0060))
    return {"lat": lat, "lng": lng, "name": location}


def haversine(lat1, lon1, lat2, lon2):
    R = 3959
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def osrm_route(coords):
    # coords is list of dicts with lat,lng
    try:
        parts = ";".join([f"{c['lng']},{c['lat']}" for c in coords])
        url = f"{OSRM_URL}{parts}?overview=full&geometries=geojson&steps=true&continue_straight=true"
        res = requests.get(url, timeout=15)
        res.raise_for_status()
        data = res.json()
        route = data["routes"][0]
        geometry = [{"lat": lat, "lng": lon} for lon, lat in route["geometry"]["coordinates"]]
        distance_miles = route["distance"] / 1609.34
        duration_hours = route["duration"] / 3600
        legs = route.get("legs", [])
        return geometry, distance_miles, duration_hours, legs
    except Exception:
        return None, None, None, []


def plan_route(current, pickup, dropoff, current_cycle_used: float):
    current_c = geocode(current)
    pickup_c = geocode(pickup)
    dropoff_c = geocode(dropoff)

    geometry, distance, duration, legs = osrm_route([current_c, pickup_c, dropoff_c])
    if geometry is None:
        d1 = haversine(current_c["lat"], current_c["lng"], pickup_c["lat"], pickup_c["lng"])
        d2 = haversine(pickup_c["lat"], pickup_c["lng"], dropoff_c["lat"], dropoff_c["lng"])
        distance = d1 + d2
        avg_speed = 50
        duration = distance / avg_speed
        geometry = [current_c, pickup_c, dropoff_c]
        legs = [{"distance": d1 * 1609.34}]

    distance_to_pickup = legs[0]["distance"] / 1609.34 if legs and legs[0].get("distance") else haversine(
        current_c["lat"], current_c["lng"], pickup_c["lat"], pickup_c["lng"]
    )

    # HOS planning
    rest_stops = []
    avg_speed = 50
    current_miles = 0
    hours_worked = 0
    total_distance = distance

    def location_at(miles):
        if miles <= distance_to_pickup:
            return f"{int(miles)} mi from {current_c['name']}"
        else:
            return f"{int(miles - distance_to_pickup)} mi from {pickup_c['name']}"

    while current_miles < total_distance:
        remaining_shift_hours = min(11 - (hours_worked % 11), 14 - (hours_worked % 14))
        if hours_worked > 0 and (hours_worked % 8) < 0.5:
            rest_stops.append({
                "type": "30-min break",
                "name": "Rest Area (30-min break)",
                "location": location_at(current_miles),
                "duration": 0.5,
                "milesFromStart": int(current_miles),
                "time": _format_time(hours_worked),
            })
        drive_miles = min(remaining_shift_hours * avg_speed, total_distance - current_miles, 550)
        current_miles += drive_miles
        hours_worked += drive_miles / avg_speed

        if math.floor(current_miles / 1000) > math.floor((current_miles - drive_miles) / 1000):
            rest_stops.append({
                "type": "fuel",
                "name": "Fuel Stop",
                "location": location_at(current_miles),
                "duration": 0.5,
                "milesFromStart": int(current_miles),
                "time": _format_time(hours_worked),
            })
            hours_worked += 0.5

        if current_miles >= distance_to_pickup and (current_miles - drive_miles) < distance_to_pickup:
            rest_stops.append({
                "type": "pickup",
                "name": pickup_c['name'],
                "location": pickup_c['name'],
                "duration": 1,
                "milesFromStart": int(distance_to_pickup),
                "time": _format_time(hours_worked),
            })
            hours_worked += 1

        if hours_worked >= 11 or (hours_worked % 14) >= 13.5:
            if current_miles < total_distance:
                rest_stops.append({
                    "type": "rest",
                    "name": "Overnight Rest (10 hours)",
                    "location": location_at(current_miles),
                    "duration": 10,
                    "milesFromStart": int(current_miles),
                    "time": _format_time(hours_worked),
                })
                hours_worked = 0

    rest_stops.append({
        "type": "dropoff",
        "name": dropoff_c['name'],
        "location": dropoff_c['name'],
        "duration": 1,
        "milesFromStart": int(total_distance),
        "time": _format_time(duration),
    })

    estimated_days = math.ceil(duration / 11) + math.floor(duration / 11)

    route_data = {
        "totalDistance": int(round(total_distance)),
        "totalDrivingTime": round(duration, 1),
        "estimatedDays": estimated_days,
        "restStops": rest_stops,
        "coordinates": {
            "current": current_c,
            "pickup": pickup_c,
            "dropoff": dropoff_c,
        },
        "routeGeometry": geometry,
    }
    return route_data


def _format_time(hours: float) -> str:
    h = int(math.floor(hours))
    m = int(round((hours - h) * 60))
    return f"{h:02d}:{m:02d}"


def generate_eld_logs(trip_data, route_data):
    logs = []
    start_date = date.today()

    current_hour = 8
    current_day = 1
    daily_segments = []
    daily_hours = {"off": 0.0, "sleeper": 0.0, "driving": 0.0, "on": 0.0}
    total_miles_day = 0.0
    remaining_distance = float(route_data["totalDistance"])  # miles
    avg_speed = 50.0
    remarks = []

    def add_segment(status, duration, location=""):
        nonlocal current_hour, daily_segments, daily_hours
        # If adding this segment would exceed 24 hours, cap it
        if current_hour + duration > 24:
            actual_duration = 24 - current_hour
            if actual_duration > 0:
                daily_segments.append({"status": status, "startHour": current_hour, "duration": actual_duration, "location": location})
                if status == "off-duty":
                    daily_hours["off"] += actual_duration
                elif status == "sleeper":
                    daily_hours["sleeper"] += actual_duration
                elif status == "driving":
                    daily_hours["driving"] += actual_duration
                else:
                    daily_hours["on"] += actual_duration
            current_hour = 24
        else:
            daily_segments.append({"status": status, "startHour": current_hour, "duration": duration, "location": location})
            if status == "off-duty":
                daily_hours["off"] += duration
            elif status == "sleeper":
                daily_hours["sleeper"] += duration
            elif status == "driving":
                daily_hours["driving"] += duration
            else:
                daily_hours["on"] += duration
            current_hour += duration

    def save_day():
        nonlocal current_day, daily_segments, daily_hours, total_miles_day, current_hour
        d = start_date + timedelta(days=current_day - 1)
        logs.append({
            "date": d.isoformat(),
            "dayNumber": current_day,
            "hours": {
                "offDuty": daily_hours["off"],
                "sleeperBerth": daily_hours["sleeper"],
                "driving": daily_hours["driving"],
                "onDuty": daily_hours["on"],
            },
            "segments": list(daily_segments),
            "remarks": list(remarks),
            "totalMiles": int(round(total_miles_day)),
        })
        current_day += 1
        daily_segments.clear()
        daily_hours.update({"off": 0.0, "sleeper": 0.0, "driving": 0.0, "on": 0.0})
        total_miles_day = 0.0
        current_hour = 0  # Reset hour to start of new day

    # start of day sleeper
    add_segment("sleeper", 8, "Home terminal")
    remarks.append("Started trip after 10-hour rest")
    add_segment("on-duty", 0.5, "Pre-trip inspection")

    stops = route_data.get("restStops", [])
    stop_index = 0

    while remaining_distance > 0 or stop_index < len(stops):
        if daily_hours["driving"] >= 11 or (daily_hours["driving"] + daily_hours["on"]) >= 14:
            add_segment("on-duty", 0.5, "Post-trip inspection")
            if current_hour < 24:
                add_segment("sleeper", 24 - current_hour, "Rest area")
            save_day()
            add_segment("sleeper", 10, "Rest area")
            add_segment("on-duty", 0.5, "Pre-trip inspection")
            continue

        if stop_index < len(stops):
            stop = stops[stop_index]
            stop_index += 1
            if stop["type"] in ("pickup", "dropoff"):
                drive_time = min(remaining_distance / avg_speed, 11 - daily_hours["driving"], 14 - (daily_hours["driving"] + daily_hours["on"]))
                if drive_time > 0:
                    add_segment("driving", drive_time, f"En route to {stop['location']}")
                    total_miles_day += drive_time * avg_speed
                    remaining_distance -= drive_time * avg_speed
                add_segment("on-duty", 1, ("Pickup at " if stop["type"] == "pickup" else "Delivery at ") + stop["location"]) 
                remarks.append(("Pickup: " if stop["type"] == "pickup" else "Delivery: ") + stop["location"]) 
            elif stop["type"] == "fuel":
                drive_time = min(2, 11 - daily_hours["driving"]) 
                if drive_time > 0:
                    add_segment("driving", drive_time)
                    total_miles_day += drive_time * avg_speed
                    remaining_distance -= drive_time * avg_speed
                add_segment("on-duty", 0.5, "Fuel stop")
                remarks.append("Fueling")
            elif stop["type"] == "30-min break":
                drive_time = min(3, 11 - daily_hours["driving"], 8 - (daily_hours["driving"] % 8))
                if drive_time > 0:
                    add_segment("driving", drive_time)
                    total_miles_day += drive_time * avg_speed
                    remaining_distance -= drive_time * avg_speed
                add_segment("off-duty", 0.5, "30-min break")
                remarks.append("30-minute break")
            elif stop["type"] == "rest":
                if current_hour < 24:
                    add_segment("sleeper", 24 - current_hour, "Rest area")
                save_day()
                add_segment("sleeper", 10, "Rest area")
        else:
            drive_time = min(remaining_distance / avg_speed, 11 - daily_hours["driving"], 14 - (daily_hours["driving"] + daily_hours["on"]) - 0.5)
            if drive_time > 0:
                add_segment("driving", drive_time)
                total_miles_day += drive_time * avg_speed
                remaining_distance -= drive_time * avg_speed
            else:
                break

        if current_hour >= 23.5:
            add_segment("off-duty", 24 - current_hour)
            save_day()
            add_segment("sleeper", 10, "Rest area")

    if daily_segments:
        # Add post-trip inspection if there's room in the day
        if current_hour <= 23.5:
            add_segment("on-duty", 0.5, "Post-trip inspection")
        
        # Fill remaining time with off-duty, but cap at 24 hours
        if current_hour < 24:
            off_duty_hours = 24 - current_hour
            add_segment("off-duty", off_duty_hours, "End of day")
        
        remarks.append("Trip completed")
        save_day()

    return logs
