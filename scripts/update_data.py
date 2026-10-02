import os
import json
import requests
import truststore

from collections import defaultdict
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv


# --------------------------------------------------
# CONFIGURACIÓN
# --------------------------------------------------

truststore.inject_into_ssl()
load_dotenv()

OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

if not OPENFOOT_API_KEY:
    raise Exception("No se encontró OPENFOOT_API_KEY en .env")


OPENFOOT_BASE_URL = "https://openfootapi.com/v1"
OPENFOOT_COMPETITION = "comp_segunda_es"
SEASON = "2026/27"

SPORTSDB_BASE_URL = "https://www.thesportsdb.com/api/v1/json/123"
SPORTSDB_LEAGUE_ID = 4400

MADRID_TZ = ZoneInfo("Europe/Madrid")

openfoot_headers = {
    "Accept": "application/json",
    "Authorization": f"Bearer {OPENFOOT_API_KEY}"
}


# --------------------------------------------------
# HELPERS
# --------------------------------------------------

def convert_utc_to_madrid(date_string, time_string):
    if not date_string or not time_string:
        return ""

    clean_time = time_string[:8]

    utc_datetime = datetime.fromisoformat(
        f"{date_string}T{clean_time}"
    ).replace(tzinfo=timezone.utc)

    madrid_datetime = utc_datetime.astimezone(MADRID_TZ)

    return madrid_datetime.strftime("%H:%M")


def get_all_openfoot_matches():
    """
    Obtiene todos los partidos disponibles de la temporada,
    recorriendo todas las páginas de OpenFoot.
    """

    all_matches = []
    cursor = None

    while True:
        params = {
            "competition": OPENFOOT_COMPETITION,
            "season": SEASON
        }

        if cursor:
            params["cursor"] = cursor

        response = requests.get(
            f"{OPENFOOT_BASE_URL}/matches",
            headers=openfoot_headers,
            params=params
        )

        response.raise_for_status()

        data = response.json()

        all_matches.extend(data.get("data", []))

        pagination = (
            data
            .get("meta", {})
            .get("pagination", {})
        )

        cursor = pagination.get("next_cursor")

        if not cursor:
            break

    return all_matches


def calculate_team_stats(team_id, matches):
    """
    Calcula estadísticas de un equipo a partir
    de sus partidos terminados.
    """

    team_matches = []

    for match in matches:
        if match.get("status") != "finished":
            continue

        home = match["homeTeam"]
        away = match["awayTeam"]

        if team_id not in [home["id"], away["id"]]:
            continue

        score = match.get("score") or {}

        home_score = score.get("home")
        away_score = score.get("away")

        if home_score is None or away_score is None:
            continue

        is_home = home["id"] == team_id

        goals_for = home_score if is_home else away_score
        goals_against = away_score if is_home else home_score

        if goals_for > goals_against:
            result = "W"
        elif goals_for == goals_against:
            result = "D"
        else:
            result = "L"

        team_matches.append({
            "date": match.get("kickoffAt"),
            "result": result,
            "goalsFor": goals_for,
            "goalsAgainst": goals_against,
            "btts": goals_for > 0 and goals_against > 0
        })

    # Orden cronológico
    team_matches.sort(
        key=lambda item: item["date"] or ""
    )

    last_five = team_matches[-5:]

    if not last_five:
        return None

    # Forma
    form = [
        match["result"]
        for match in last_five
    ]

    # Media goles marcados
    avg_goals = (
        sum(match["goalsFor"] for match in last_five)
        / len(last_five)
    )

    # BTTS
    btts_count = sum(
        1
        for match in last_five
        if match["btts"]
    )

    # Racha sin perder
    unbeaten_streak = 0

    for match in reversed(team_matches):
        if match["result"] == "L":
            break

        unbeaten_streak += 1

    # Racha marcando
    scoring_streak = 0

    for match in reversed(team_matches):
        if match["goalsFor"] == 0:
            break

        scoring_streak += 1

    # Racha de victorias
    win_streak = 0

    for match in reversed(team_matches):
        if match["result"] != "W":
            break

        win_streak += 1

    return {
        "form": form,
        "avgGoals": round(avg_goals, 2),
        "btts": btts_count,
        "unbeatenStreak": unbeaten_streak,
        "scoringStreak": scoring_streak,
        "winStreak": win_streak,
        "matchesAnalysed": len(last_five)
    }


# --------------------------------------------------
# CLASIFICACIÓN
# --------------------------------------------------

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

teams = []

for row in standings_data["data"]["table"]:
    team = row["team"]

    teams.append({
        "id": team["id"],
        "name": team["name"]
    })

    standings.append({
        "pos": row["position"],
        "team": team["name"],
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


# --------------------------------------------------
# HISTÓRICO DE PARTIDOS OPENFOOT
# --------------------------------------------------

all_matches = get_all_openfoot_matches()

finished_matches = [
    match
    for match in all_matches
    if match.get("status") == "finished"
]

print(
    "Partidos terminados analizados:",
    len(finished_matches)
)


# --------------------------------------------------
# ESTADÍSTICAS DE TODOS LOS EQUIPOS
# --------------------------------------------------

team_stats = {}

for team in teams:
    stats = calculate_team_stats(
        team["id"],
        finished_matches
    )

    if stats:
        team_stats[team["id"]] = {
            "name": team["name"],
            **stats
        }


# --------------------------------------------------
# GENERAR CANDIDATOS A TENDENCIA
# --------------------------------------------------

trend_groups = {
    "wins": [],
    "unbeaten": [],
    "scoring": [],
    "goals": [],
    "btts": []
}

for team_id, stats in team_stats.items():
    team_name = stats["name"]

    if stats["winStreak"] >= 3:
        trend_groups["wins"].append({
            "value": stats["winStreak"],
            "icon": "🔥",
            "title": team_name,
            "text": f"{stats['winStreak']} victorias consecutivas"
        })

    if stats["unbeatenStreak"] >= 4:
        trend_groups["unbeaten"].append({
            "value": stats["unbeatenStreak"],
            "icon": "📈",
            "title": team_name,
            "text": (
                f"{stats['unbeatenStreak']} partidos "
                f"consecutivos sin perder"
            )
        })

    if stats["scoringStreak"] >= 4:
        trend_groups["scoring"].append({
            "value": stats["scoringStreak"],
            "icon": "⚽",
            "title": team_name,
            "text": (
                f"Ha marcado en sus últimos "
                f"{stats['scoringStreak']} partidos"
            )
        })

    if stats["avgGoals"] >= 1.8:
        trend_groups["goals"].append({
            "value": stats["avgGoals"],
            "icon": "🎯",
            "title": team_name,
            "text": (
                f"Promedia {stats['avgGoals']} goles "
                f"en sus últimos 5 partidos"
            )
        })

    if stats["btts"] >= 4:
        trend_groups["btts"].append({
            "value": stats["btts"],
            "icon": "🥅",
            "title": team_name,
            "text": (
                f"Ambos equipos marcaron en "
                f"{stats['btts']} de sus últimos 5 partidos"
            )
        })


trends = []

used_teams = set()

category_order = [
    "wins",
    "scoring",
    "btts",
    "goals",
    "unbeaten"
]

for category in category_order:
    candidates = sorted(
        trend_groups[category],
        key=lambda item: item["value"],
        reverse=True
    )

    for candidate in candidates:
        if candidate["title"] not in used_teams:
            trends.append({
                "icon": candidate["icon"],
                "title": candidate["title"],
                "text": candidate["text"]
            })

            used_teams.add(candidate["title"])
            break


# --------------------------------------------------
# PARTIDOS DE HOY - THESPORTSDB
# --------------------------------------------------

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


# --------------------------------------------------
# SI NO HAY PARTIDO HOY -> PRÓXIMO PARTIDO
# --------------------------------------------------

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


# --------------------------------------------------
# JSON FINAL
# --------------------------------------------------

output = {
    "matchSectionTitle": section_title,
    "matches": matches,
    "trends": trends,
    "standings": standings,
    "teamStats": team_stats
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


# --------------------------------------------------
# DEBUG
# --------------------------------------------------

print()
print("Datos actualizados")
print("Equipos:", len(standings))
print("Tendencias:", len(trends))
print(section_title + ":", len(matches))

print()
print("TENDENCIAS:")

for trend in trends:
    print(
        trend["icon"],
        trend["title"],
        "-",
        trend["text"]
    )

print()
print("PARTIDOS:")

for match in matches:
    print(
        match["date"],
        match["time"],
        "-",
        match["home"],
        "vs",
        match["away"]
    )