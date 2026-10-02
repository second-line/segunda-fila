import os
import json
import requests
import truststore

from datetime import date
from dotenv import load_dotenv

truststore.inject_into_ssl()
load_dotenv()

OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

if not OPENFOOT_API_KEY:
    raise Exception("No se encontró OPENFOOT_API_KEY en .env")

OPENFOOT_BASE_URL = "https://openfootapi.com/v1"
OPENFOOT_COMPETITION = "comp_segunda_es"

SPORTSDB_BASE_URL = "https://www.thesportsdb.com/api/v1/json/123"
SPORTSDB_LEAGUE_ID = 4400

openfoot_headers = {
    "Accept": "application/json",
    "Authorization": f"Bearer {OPENFOOT_API_KEY}"
}

# -------------------------
# CLASIFICACIÓN
# -------------------------

standings_response = requests.get(
    f"{OPENFOOT_BASE_URL}/standings",
    headers=openfoot_headers,
    params={"competition": OPENFOOT_COMPETITION}
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
# PARTIDOS DE HOY
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
    matches.append({
        "id": event.get("idEvent"),
        "date": event.get("dateEvent"),
        "time": (event.get("strTime") or "")[:5],
        "status": event.get("strStatus"),
        "home": event.get("strHomeTeam"),
        "away": event.get("strAwayTeam"),
        "homeScore": event.get("intHomeScore"),
        "awayScore": event.get("intAwayScore")
    })

section_title = "Partidos de hoy"

# -------------------------
# SI NO HAY PARTIDOS:
# PRÓXIMO PARTIDO
# -------------------------

if not matches:
    next_response = requests.get(
        f"{SPORTSDB_BASE_URL}/eventsnextleague.php",
        params={"id": SPORTSDB_LEAGUE_ID}
    )

    next_response.raise_for_status()

    next_data = next_response.json()
    next_events = next_data.get("events") or []

    if next_events:
        event = next_events[0]

        matches.append({
            "id": event.get("idEvent"),
            "date": event.get("dateEvent"),
            "time": (event.get("strTime") or "")[:5],
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