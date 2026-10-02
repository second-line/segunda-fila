import os
import json
import requests
import truststore

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv


truststore.inject_into_ssl()
load_dotenv()

OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

if not OPENFOOT_API_KEY:
    raise Exception("No se encontró OPENFOOT_API_KEY en .env")


# -------------------------
# CONFIG
# -------------------------

OPENFOOT_BASE_URL = "https://openfootapi.com/v1"
OPENFOOT_COMPETITION = "comp_segunda_es"

SPORTSDB_BASE_URL = "https://www.thesportsdb.com/api/v1/json/123"
SPORTSDB_LEAGUE_ID = 4400

MADRID_TZ = ZoneInfo("Europe/Madrid")


# -------------------------
# HELPERS
# -------------------------

def convert_utc_to_madrid(date_string, time_string):
    if not date_string or not time_string:
        return ""

    clean_time = time_string[:8]

    utc_datetime = datetime.fromisoformat(
        f"{date_string}T{clean_time}"
    ).replace(tzinfo=timezone.utc)

    madrid_datetime = utc_datetime.astimezone(MADRID_TZ)

    return madrid_datetime.strftime("%H:%M")


# -------------------------
# CLASIFICACIÓN - OPENFOOT
# -------------------------

openfoot_headers = {
    "Accept": "application/json",
    "Authorization": f"Bearer {OPENFOOT_API_KEY}"
}

standings_response = requests.get(
    f"{OPENFOOT_BASE_URL}/standings",
    headers=openfoot_headers,
    params={
        "competition": OPENFOOT_COMPETITION
    }
)

standings_response.raise_for_status()

standings_data = standings_response.json()

standings = []

for row in standings_data["data"]["table"]:
    standings.append({
        "pos": row["position"],
        "team": row["team"]["name"],
        "played": row["total"]["played"],
        "points": row["total"]["points"],
        "won": row["total"]["won"],
        "drawn": row["total"]["drawn"],
        "lost": row["total"]["lost"],
        "goalsFor": row["total"]["goalsFor"],
        "goalsAgainst": row["total"]["goalsAgainst"],
        "goalDifference": row["total"]["goalDifference"],
        "form": row["form"]
    })


# -------------------------
# PARTIDOS DE HOY - THESPORTSDB
# -------------------------

today = date.today().isoformat()

today_response = requests.get(
    f"{SPORTSDB_BASE_URL}/eventsday.php",
    params={
        "d": today,
        "l": SPORTSDB_LEAGUE_ID
    }
)

today_response.raise_for_status()

today_data = today_response.json()
today_events = today_data.get("events") or []

matches = []

for event in today_events:
    event_date = event.get("dateEvent")
    event_time = event.get("strTime")

    local_time = convert_utc_to_madrid(
        event_date,
        event_time
    )

    matches.append({
        "id": event.get("idEvent"),
        "date": event_date,
        "time": local_time,
        "status": event.get("strStatus"),
        "home": event.get("strHomeTeam"),
        "away": event.get("strAwayTeam"),
        "homeScore": event.get("intHomeScore"),
        "awayScore": event.get("intAwayScore")
    })


section_title = "Partidos de hoy"


# -------------------------
# SI NO HAY PARTIDOS HOY:
# PRÓXIMO PARTIDO
# -------------------------

if not matches:
    next_response = requests.get(
        f"{SPORTSDB_BASE_URL}/eventsnextleague.php",
        params={
            "id": SPORTSDB_LEAGUE_ID
        }
    )

    next_response.raise_for_status()

    next_data = next_response.json()
    next_events = next_data.get("events") or []

    if next_events:
        event = next_events[0]

        event_date = event.get("dateEvent")
        event_time = event.get("strTime")

        local_time = convert_utc_to_madrid(
            event_date,
            event_time
        )

        matches.append({
            "id": event.get("idEvent"),
            "date": event_date,
            "time": local_time,
            "status": event.get("strStatus"),
            "home": event.get("strHomeTeam"),
            "away": event.get("strAwayTeam"),
            "homeScore": event.get("intHomeScore"),
            "awayScore": event.get("intAwayScore")
        })

        section_title = "Próximo partido"


# -------------------------
# JSON FINAL
# -------------------------

output = {
    "matchSectionTitle": section_title,
    "matches": matches,
    "trends": [],
    "standings": standings
}

with open(
    "src/data/segunda.json",
    "w",
    encoding="utf-8"
) as file:
    json.dump(
        output,
        file,
        ensure_ascii=False,
        indent=2
    )


print("Datos actualizados")
print(section_title + ":", len(matches))
print("Equipos:", len(standings))

for match in matches:
    print(
        match["date"],
        match["time"],
        "-",
        match["home"],
        "vs",
        match["away"]
    )