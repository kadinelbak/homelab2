import json
import os
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import urllib.parse
import urllib.request

DATA_DIR = Path(os.environ.get("WEATHER_DATA_DIR", "/data"))
LOCATIONS_FILE = DATA_DIR / "locations.json"
REMOVED_LOCATIONS_FILE = DATA_DIR / "removed-locations.json"

DEFAULT_LOCATIONS = [
    {
        "id": "oklahoma-city",
        "name": "Oklahoma City",
        "latitude": 35.4676,
        "longitude": -97.5164,
        "timezone": "America/Chicago",
        "radar": "https://radar.weather.gov/station/KTLX/standard",
    },
    {
        "id": "tampa",
        "name": "Tampa",
        "latitude": 27.9506,
        "longitude": -82.4572,
        "timezone": "America/New_York",
        "radar": "https://radar.weather.gov/station/KTBW/standard",
    },
    {
        "id": "gainesville",
        "name": "Gainesville",
        "latitude": 29.6516,
        "longitude": -82.3248,
        "timezone": "America/New_York",
        "radar": "https://radar.weather.gov/station/KJAX/standard",
    },
]


def slugify(value):
    slug = "".join(char if char.isalnum() else "-" for char in value.lower()).strip("-")
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug


def normalize_location(location):
    location = dict(location)
    location["id"] = slugify(location.get("id") or location["name"])
    location["name"] = location.get("name") or location["id"].replace("-", " ").title()
    location["timezone"] = location.get("timezone", "auto")
    location["radar"] = location.get("radar", "https://radar.weather.gov/")
    location["latitude"] = float(location["latitude"])
    location["longitude"] = float(location["longitude"])
    return location


def read_user_locations():
    if not LOCATIONS_FILE.exists():
        return []
    with LOCATIONS_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("locations.json must contain a list")
    return [normalize_location(item) for item in data]


def read_removed_location_ids():
    if not REMOVED_LOCATIONS_FILE.exists():
        return set()
    with REMOVED_LOCATIONS_FILE.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("removed-locations.json must contain a list")
    return {slugify(item) for item in data}


def write_removed_location_ids(location_ids):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = REMOVED_LOCATIONS_FILE.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(sorted(location_ids), handle, indent=2)
    temporary.replace(REMOVED_LOCATIONS_FILE)


def write_user_locations(locations):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = [
        {
            "id": item["id"],
            "name": item["name"],
            "latitude": item["latitude"],
            "longitude": item["longitude"],
            "timezone": item["timezone"],
            "radar": item["radar"],
        }
        for item in locations
    ]
    temporary = LOCATIONS_FILE.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    temporary.replace(LOCATIONS_FILE)


def load_locations():
    removed_location_ids = read_removed_location_ids()
    locations = {item["id"]: normalize_location(item) for item in DEFAULT_LOCATIONS}
    raw_extra = os.environ.get("WEATHER_EXTRA_LOCATIONS_JSON", "[]").strip()
    if raw_extra:
        for item in json.loads(raw_extra):
            location = normalize_location(item)
            locations[location["id"]] = location
    for location in read_user_locations():
        locations[location["id"]] = location
    for location_id in removed_location_ids:
        locations.pop(location_id, None)
    return locations


LOCATIONS = load_locations()


def refresh_locations():
    global LOCATIONS
    LOCATIONS = load_locations()
    return LOCATIONS


def hour_label(value):
    label = datetime.fromisoformat(value).strftime("%I %p").lstrip("0")
    return label or "12 AM"


WEATHER_CODES = {
    0: "Clear",
    1: "Mainly clear",
    2: "Partly cloudy",
    3: "Overcast",
    45: "Fog",
    48: "Rime fog",
    51: "Light drizzle",
    53: "Drizzle",
    55: "Heavy drizzle",
    56: "Freezing drizzle",
    57: "Freezing drizzle",
    61: "Light rain",
    63: "Rain",
    65: "Heavy rain",
    66: "Freezing rain",
    67: "Freezing rain",
    71: "Light snow",
    73: "Snow",
    75: "Heavy snow",
    77: "Snow grains",
    80: "Light showers",
    81: "Showers",
    82: "Heavy showers",
    85: "Snow showers",
    86: "Heavy snow showers",
    95: "Thunderstorms",
    96: "Thunderstorms with hail",
    99: "Thunderstorms with hail",
}

WET_WEATHER_CODES = {51, 53, 55, 56, 57, 61, 63, 65, 66, 67, 71, 73, 75, 77, 80, 81, 82, 85, 86, 95, 96, 99}


def weather_description(code):
    try:
        return WEATHER_CODES.get(int(code), "Unknown")
    except (TypeError, ValueError):
        return "Unknown"


def rain_status(code, precipitation=0, rain=0, showers=0, probability=None):
    wet_now = (precipitation or 0) > 0 or (rain or 0) > 0 or (showers or 0) > 0
    try:
        wet_code = int(code) in WET_WEATHER_CODES
    except (TypeError, ValueError):
        wet_code = False
    if wet_now or wet_code:
        return "Raining"
    if probability is not None and probability >= 40:
        return f"Rain possible ({probability:.0f}%)"
    return "Not raining"


def hourly_value(hourly, field, index, default=None):
    values = hourly.get(field) or []
    if index >= len(values):
        return default
    value = values[index]
    return default if value is None else value


def current_weather(location_id):
    location = LOCATIONS[location_id]
    query = urllib.parse.urlencode({
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "current": "temperature_2m,apparent_temperature,wind_speed_10m,precipitation,rain,showers,weather_code",
        "hourly": "temperature_2m,precipitation_probability,precipitation,rain,showers,weather_code",
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
        "timezone": location["timezone"],
    })
    with urllib.request.urlopen(f"https://api.open-meteo.com/v1/forecast?{query}", timeout=15) as response:
        forecast = json.loads(response.read().decode("utf-8"))

    current = forecast["current"]
    hourly = forecast["hourly"]
    current_hour = current["time"][:13]
    start = next((index for index, value in enumerate(hourly["time"]) if value.startswith(current_hour)), 0)
    hours = []
    for index in range(start, min(start + 12, len(hourly["time"]))):
        temperature = hourly["temperature_2m"][index]
        probability = hourly_value(hourly, "precipitation_probability", index)
        precipitation = hourly_value(hourly, "precipitation", index, 0) or 0
        rain = hourly_value(hourly, "rain", index, 0) or 0
        showers = hourly_value(hourly, "showers", index, 0) or 0
        code = hourly_value(hourly, "weather_code", index)
        rain_label = rain_status(code, precipitation, rain, showers, probability)
        hours.append({
            "time": hour_label(hourly["time"][index]),
            "temperature": temperature,
            "temperature_label": f"{temperature:.0f} F",
            "precipitation_probability": probability,
            "precipitation": precipitation,
            "rain": rain,
            "showers": showers,
            "weather_code": code,
            "condition": weather_description(code),
            "rain_status": rain_label,
            "precipitation_label": f"{precipitation:.2f} in" if precipitation else "0 in",
            "rain_chance_label": f"{probability:.0f}%" if probability is not None else "n/a",
        })

    current_precipitation = current.get("precipitation") or 0
    current_rain = current.get("rain") or 0
    current_showers = current.get("showers") or 0
    current_code = current.get("weather_code")
    current_probability = hours[0].get("precipitation_probability") if hours else None
    current_rain_status = rain_status(
        current_code,
        current_precipitation,
        current_rain,
        current_showers,
        current_probability,
    )
    return {
        "name": location["name"],
        "radar": location["radar"],
        "now": current["temperature_2m"],
        "feels": current["apparent_temperature"],
        "wind": current["wind_speed_10m"],
        "weather_code": current_code,
        "condition": weather_description(current_code),
        "precipitation": current_precipitation,
        "rain": current_rain,
        "showers": current_showers,
        "rain_status": current_rain_status,
        "is_raining": current_rain_status == "Raining",
        "precipitation_probability": current_probability,
        "precipitation_label": f"{current_precipitation:.2f} in" if current_precipitation else "0 in",
        "rain_chance_label": f"{current_probability:.0f}%" if current_probability is not None else "n/a",
        "hours": hours,
        "next_12": "  |  ".join(
            f"{hour['time']} {hour['temperature_label']} {hour['rain_chance_label']} rain"
            for hour in hours
        ),
    }


def geocode_location(query):
    params = urllib.parse.urlencode({
        "name": query,
        "count": 1,
        "language": "en",
        "format": "json",
    })
    with urllib.request.urlopen(f"https://geocoding-api.open-meteo.com/v1/search?{params}", timeout=15) as response:
        result = json.loads(response.read().decode("utf-8"))
    matches = result.get("results") or []
    if not matches:
        raise ValueError(f"No location found for {query}")
    match = matches[0]
    name_parts = [match["name"], match.get("admin1"), match.get("country_code")]
    return normalize_location({
        "name": ", ".join(part for part in name_parts if part),
        "latitude": match["latitude"],
        "longitude": match["longitude"],
        "timezone": match.get("timezone", "auto"),
        "radar": "https://radar.weather.gov/",
    })


def add_location(payload):
    if "query" in payload and payload["query"].strip():
        location = geocode_location(payload["query"].strip())
    else:
        location = normalize_location(payload)
    user_locations = [item for item in read_user_locations() if item["id"] != location["id"]]
    user_locations.append(location)
    write_user_locations(user_locations)
    removed_location_ids = read_removed_location_ids()
    removed_location_ids.discard(location["id"])
    write_removed_location_ids(removed_location_ids)
    refresh_locations()
    return location


def remove_location(location_id):
    location_id = slugify(location_id)
    if location_id not in LOCATIONS:
        raise ValueError(f"No configured location named {location_id}")
    user_locations = [item for item in read_user_locations() if item["id"] != location_id]
    write_user_locations(user_locations)
    removed_location_ids = read_removed_location_ids()
    removed_location_ids.add(location_id)
    write_removed_location_ids(removed_location_ids)
    refresh_locations()
    return {"removed": location_id}


def weather_summary():
    cities = []
    for location_id, location in LOCATIONS.items():
        data = current_weather(location_id)
        label = f"{data['now']:.1f} F, {data['rain_status']}, {data['rain_chance_label']} next-hour rain"
        cities.append({
            "id": location_id,
            "name": location["name"],
            "label": label,
            "radar": location["radar"],
            "rain_status": data["rain_status"],
            "condition": data["condition"],
            "precipitation_probability": data["precipitation_probability"],
        })
    return {
        "preview": "  |  ".join(f"{city['name']}: {city['label']}" for city in cities),
        "cities": cities,
    }


DASHBOARD = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Weather</title><style>
body{margin:0;background:#172033;color:#e8edf5;font-family:system-ui,sans-serif}.wrap{max-width:1200px;margin:auto;padding:32px 22px}h1{margin:0;font-size:28px}.sub{color:#aebbd0;margin:6px 0 18px}.toolbar{display:flex;gap:10px;align-items:center;margin:0 0 24px;flex-wrap:wrap}.toolbar input{background:#202a3c;border:1px solid #3a4760;border-radius:6px;color:#e8edf5;font:14px system-ui;padding:10px 12px;min-width:260px}.toolbar button{background:#7cc4ff;border:0;border-radius:6px;color:#102033;cursor:pointer;font-weight:700;padding:10px 14px}.toolbar button:disabled{cursor:wait;opacity:.65}.status{color:#bac5d5;font-size:13px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:18px}.city{background:#2b3549;border:1px solid #3a4760;padding:18px;border-radius:8px;position:relative}.head{display:flex;justify-content:space-between;align-items:baseline;gap:12px;padding-right:36px}.head h2{font-size:19px;margin:0}.now{font-size:24px;font-weight:700;margin-left:auto}.remove{align-items:center;background:#202a3c;border:1px solid #53627d;border-radius:999px;color:#bac5d5;cursor:pointer;display:flex;height:28px;justify-content:center;opacity:0;padding:0;position:absolute;right:12px;top:12px;transform:scale(.92);transition:opacity .15s ease,transform .15s ease,background .15s ease,border-color .15s ease,color .15s ease;width:28px}.city:hover .remove,.city:focus-within .remove,.remove:focus{opacity:1;transform:scale(1)}.remove:hover,.remove:focus{background:#3a1f2a;border-color:#ff7a90;color:#ffd8df;outline:0}.remove svg{height:15px;width:15px}.meta{color:#b6c1d2;margin:7px 0 12px;font-size:14px}canvas{width:100%;height:190px;background:#202a3c;border-radius:6px}.hours{display:flex;justify-content:space-between;color:#bac5d5;font-size:11px;margin-top:8px}.radar{display:inline-block;margin-top:14px;color:#91c7ff;text-decoration:none;font-size:14px}</style></head><body><main class="wrap"><h1>Weather</h1><p class="sub">Live conditions and the next 12 hours</p><form class="toolbar" id="add-city"><input id="city-query" autocomplete="off" placeholder="Add city, state or ZIP"><button>Add city</button><span class="status" id="status"></span></form><section class="grid" id="cities"></section></main><script>
function graph(c,data){const x=c.getContext('2d'),w=c.width=c.clientWidth*2,h=c.height=c.clientHeight*2,p=28,points=data.map(a=>({...a,temperature:Number.parseFloat(a.temperature),rain:Number.parseFloat(a.precipitation_probability||0)})).filter(a=>Number.isFinite(a.temperature));x.scale(2,2);x.strokeStyle='#3c4d68';x.lineWidth=1;for(let i=0;i<4;i++){let y=p+i*(c.clientHeight-2*p)/3;x.beginPath();x.moveTo(p,y);x.lineTo(c.clientWidth-p,y);x.stroke()}if(!points.length){x.fillStyle='#dbe8f8';x.font='12px system-ui';x.fillText('No hourly data',p,p+5);return}const cw=c.clientWidth,ch=c.clientHeight,chartH=ch-2*p,barBase=ch-p,barMax=42;points.forEach((a,i)=>{let px=p+(points.length===1?.5:i/(points.length-1))*(cw-2*p),bw=Math.max(8,(cw-2*p)/Math.max(12,points.length)-3),bh=Math.min(barMax,Math.max(0,a.rain)*barMax/100);x.fillStyle=a.rain>=50?'#60d7ff':'#456681';x.fillRect(px-bw/2,barBase-bh,bw,bh)});const v=points.map(a=>a.temperature),lo=Math.floor(Math.min(...v)-2),hi=Math.ceil(Math.max(...v)+2),range=Math.max(1,hi-lo);x.strokeStyle='#7cc4ff';x.lineWidth=3;x.beginPath();points.forEach((a,i)=>{let px=p+(points.length===1?.5:i/(points.length-1))*(cw-2*p),py=ch-p-(a.temperature-lo)*chartH/range;i?x.lineTo(px,py):x.moveTo(px,py)});x.stroke();x.fillStyle='#dbe8f8';x.font='12px system-ui';x.fillText(hi+' F',2,p+5);x.fillText(lo+' F',2,ch-p);x.fillStyle='#9fb2cc';x.fillText('rain %',cw-48,ch-p-barMax-4)}
async function load(city){const d=await fetch(city.id).then(r=>r.json()),el=document.createElement('article'),hours=d.hours||[],mid=Math.min(5,Math.max(0,hours.length-1)),last=Math.max(0,hours.length-1);el.className='city';el.innerHTML=`<button class=remove data-id="${city.id}" title="Remove ${city.name}" aria-label="Remove ${city.name}"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 6h18"/><path d="M8 6V4h8v2"/><path d="M19 6l-1 15H6L5 6"/><path d="M10 11v6"/><path d="M14 11v6"/></svg></button><div class=head><h2>${city.name}</h2><span class=now>${Number(d.now).toFixed(1)} F</span></div><div class=meta>${d.condition||'Unknown'} &middot; ${d.rain_status||'Rain unknown'} &middot; ${d.rain_chance_label||'n/a'} next-hour rain &middot; Wind ${Number(d.wind).toFixed(1)} mph</div><canvas></canvas><div class=hours><span>${hours[0]?.time||''}<br>${hours[0]?.rain_chance_label||''}</span><span>${hours[mid]?.time||''}<br>${hours[mid]?.rain_chance_label||''}</span><span>${hours[last]?.time||''}<br>${hours[last]?.rain_chance_label||''}</span></div><a class=radar target=_blank href="${city.radar}">Open radar</a>`;document.querySelector('#cities').append(el);graph(el.querySelector('canvas'),hours)}
async function refresh(){const grid=document.querySelector('#cities');grid.innerHTML='';const d=await fetch('summary').then(r=>r.json());await Promise.all(d.cities.map(load))}
document.querySelector('#add-city').addEventListener('submit',async e=>{e.preventDefault();const input=document.querySelector('#city-query'),button=e.submitter,status=document.querySelector('#status'),query=input.value.trim();if(!query)return;button.disabled=true;status.textContent='Adding...';try{const r=await fetch('locations',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({query})});const data=await r.json();if(!r.ok)throw new Error(data.error||'Could not add city');input.value='';status.textContent=`Added ${data.name}`;await refresh()}catch(err){status.textContent=err.message}finally{button.disabled=false}});
document.querySelector('#cities').addEventListener('click',async e=>{const button=e.target.closest('.remove');if(!button)return;const status=document.querySelector('#status');button.disabled=true;status.textContent='Removing...';try{const r=await fetch(`locations/${button.dataset.id}`,{method:'DELETE'});const data=await r.json();if(!r.ok)throw new Error(data.error||'Could not remove city');status.textContent='Removed';await refresh()}catch(err){status.textContent=err.message}finally{button.disabled=false}});
refresh();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        location = self.path.strip("/")
        if location == "weather":
            location = ""
        elif location.startswith("weather/"):
            location = location.removeprefix("weather/")
        if not location:
            self.send_body(DASHBOARD.encode("utf-8"), "text/html; charset=utf-8")
            return
        if location == "summary":
            self.send_body(json.dumps(weather_summary()).encode("utf-8"), "application/json")
            return
        if location == "locations":
            self.send_body(json.dumps({"locations": list(LOCATIONS.values())}).encode("utf-8"), "application/json")
            return
        if location not in LOCATIONS:
            self.send_error(404)
            return
        try:
            self.send_body(json.dumps(current_weather(location)).encode("utf-8"), "application/json")
        except Exception as exc:
            self.send_error(502, str(exc))

    def do_POST(self):
        location = self.path.strip("/")
        if location.startswith("weather/"):
            location = location.removeprefix("weather/")
        if location != "locations":
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            location_data = add_location(payload)
            self.send_body(json.dumps(location_data).encode("utf-8"), "application/json")
        except Exception as exc:
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def do_DELETE(self):
        location = self.path.strip("/")
        if location.startswith("weather/"):
            location = location.removeprefix("weather/")
        if not location.startswith("locations/"):
            self.send_error(404)
            return
        try:
            location_id = location.removeprefix("locations/")
            result = remove_location(location_id)
            self.send_body(json.dumps(result).encode("utf-8"), "application/json")
        except Exception as exc:
            body = json.dumps({"error": str(exc)}).encode("utf-8")
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    def send_body(self, body, content_type):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        return


def main():
    ThreadingHTTPServer(("0.0.0.0", 8098), Handler).serve_forever()


if __name__ == "__main__":
    main()
