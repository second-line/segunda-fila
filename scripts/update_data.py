import os
import json
import requests
import truststore

from datetime import datetime, timedelta, timezone
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
# NOMBRES DE EQUIPOS
# --------------------------------------------------

TEAM_NAMES = {
    "Castellon": "Castellón",
    "CD Castellon": "Castellón",

    "Leganes": "Leganés",
    "CD Leganes": "Leganés",

    "Almeria": "Almería",
    "UD Almeria": "Almería",

    "Cordoba": "Córdoba",
    "Cordoba CF": "Córdoba",

    "Cadiz": "Cádiz",
    "Cadiz CF": "Cádiz",

    "Sp Gijon": "Real Sporting",
    "Sporting Gijon": "Real Sporting",

    "Sociedad B": "Real Sociedad B",
    "Real Sociedad B": "Real Sociedad B",

    "Celta B": "Celta Fortuna",
    "Celta Fortuna": "Celta Fortuna"
}


def normalize_team_name(name):
    if not name:
        return ""

    return TEAM_NAMES.get(name, name)


# --------------------------------------------------
# HELPERS DE FECHAS
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


def create_kickoff_utc(date_string, time_string):
    """
    Devuelve una fecha ISO UTC para que el navegador pueda
    calcular si el partido está en curso.
    """

    if not date_string or not time_string:
        return None

    clean_time = time_string[:8]

    utc_datetime = datetime.fromisoformat(
        f"{date_string}T{clean_time}"
    ).replace(tzinfo=timezone.utc)

    return utc_datetime.isoformat()


def format_date_label(date_string):
    if not date_string:
        return ""

    value = datetime.fromisoformat(date_string).date()

    weekdays = [
        "Lunes",
        "Martes",
        "Miércoles",
        "Jueves",
        "Viernes",
        "Sábado",
        "Domingo"
    ]

    return (
        f"{weekdays[value.weekday()]} "
        f"{value.day:02d}/{value.month:02d}"
    )


def get_matchday_dates(today):
    """
    Consideramos una jornada de viernes a lunes.

    - Viernes, sábado y domingo -> jornada actual.
    - Lunes -> jornada que empezó el viernes anterior.
    - Martes, miércoles y jueves -> próxima jornada.
    """

    weekday = today.weekday()

    # Lunes
    if weekday == 0:
        friday = today - timedelta(days=3)

    # Martes, miércoles, jueves
    elif weekday in [1, 2, 3]:
        friday = today + timedelta(days=(4 - weekday))

    # Viernes, sábado, domingo
    else:
        friday = today - timedelta(days=(weekday - 4))

    return [
        friday,
        friday + timedelta(days=1),
        friday + timedelta(days=2),
        friday + timedelta(days=3)
    ]


# --------------------------------------------------
# OPENFOOT - TODOS LOS PARTIDOS
# --------------------------------------------------

def get_all_openfoot_matches():
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
            params=params,
            timeout=30
        )

        response.raise_for_status()

        data = response.json()

        all_matches.extend(
            data.get("data", [])
        )

        pagination = (
            data
            .get("meta", {})
            .get("pagination", {})
        )

        cursor = pagination.get("next_cursor")

        if not cursor:
            break

    return all_matches


# --------------------------------------------------
# ESTADÍSTICAS
# --------------------------------------------------

def calculate_team_stats(team_id, matches):
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

        goals_for = (
            home_score
            if is_home
            else away_score
        )

        goals_against = (
            away_score
            if is_home
            else home_score
        )

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
            "btts": (
                goals_for > 0
                and goals_against > 0
            )
        })

    team_matches.sort(
        key=lambda item: item["date"] or ""
    )

    last_five = team_matches[-5:]

    if not last_five:
        return None


    # Forma últimos cinco

    form = [
        match["result"]
        for match in last_five
    ]


    # Media goles marcados

    avg_goals = (
        sum(
            match["goalsFor"]
            for match in last_five
        )
        / len(last_five)
    )


    # Ambos marcaron

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
# THESPORTSDB
# --------------------------------------------------

def get_events_for_date(day):
    response = requests.get(
        f"{SPORTSDB_BASE_URL}/eventsday.php",
        params={
            "d": day.isoformat(),
            "l": SPORTSDB_LEAGUE_ID
        },
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    return data.get("events") or []


def format_sportsdb_event(event):
    event_date = event.get("dateEvent")
    event_time = event.get("strTime")

    home_score = event.get("intHomeScore")
    away_score = event.get("intAwayScore")

    if home_score not in [None, ""]:
        try:
            home_score = int(home_score)
        except ValueError:
            pass

    if away_score not in [None, ""]:
        try:
            away_score = int(away_score)
        except ValueError:
            pass

    return {
        "id": event.get("idEvent"),

        "date": event_date,

        "dateLabel": format_date_label(
            event_date
        ),

        "time": convert_utc_to_madrid(
            event_date,
            event_time
        ),

        "kickoffUtc": create_kickoff_utc(
            event_date,
            event_time
        ),

        "status": event.get("strStatus"),

        "home": normalize_team_name(
            event.get("strHomeTeam")
        ),

        "away": normalize_team_name(
            event.get("strAwayTeam")
        ),

        "homeScore": home_score,

        "awayScore": away_score
    }


# --------------------------------------------------
# CLASIFICACIÓN
# --------------------------------------------------

standings_response = requests.get(
    f"{OPENFOOT_BASE_URL}/standings",
    headers=openfoot_headers,
    params={
        "competition": OPENFOOT_COMPETITION
    },
    timeout=30
)

standings_response.raise_for_status()

standings_data = standings_response.json()

standings = []
teams = []


for row in standings_data["data"]["table"]:

    team = row["team"]

    normalized_name = normalize_team_name(
        team["name"]
    )

    teams.append({
        "id": team["id"],
        "name": normalized_name
    })

    standings.append({
        "pos": row["position"],
        "team": normalized_name,

        "played": row["total"]["played"],
        "points": row["total"]["points"],

        "won": row["total"]["won"],
        "drawn": row["total"]["drawn"],
        "lost": row["total"]["lost"],

        "goalsFor": row["total"]["goalsFor"],
        "goalsAgainst": row["total"]["goalsAgainst"],

        "goalDifference":
            row["total"]["goalDifference"],

        "form": row["form"]
    })


# --------------------------------------------------
# HISTÓRICO OPENFOOT
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
# ESTADÍSTICAS POR EQUIPO
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
# TENDENCIAS
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
            "text":
                f"{stats['winStreak']} "
                f"victorias consecutivas"
        })


    if stats["unbeatenStreak"] >= 4:

        trend_groups["unbeaten"].append({
            "value": stats["unbeatenStreak"],
            "icon": "📈",
            "title": team_name,
            "text": (
                f"{stats['unbeatenStreak']} "
                f"partidos consecutivos "
                f"sin perder"
            )
        })


    if stats["scoringStreak"] >= 4:

        trend_groups["scoring"].append({
            "value": stats["scoringStreak"],
            "icon": "⚽",
            "title": team_name,
            "text": (
                f"Ha marcado en sus últimos "
                f"{stats['scoringStreak']} "
                f"partidos"
            )
        })


    if stats["avgGoals"] >= 1.8:

        trend_groups["goals"].append({
            "value": stats["avgGoals"],
            "icon": "🎯",
            "title": team_name,
            "text": (
                f"Promedia "
                f"{stats['avgGoals']} goles "
                f"en sus últimos 5 partidos"
            )
        })


    if stats["btts"] >= 4:

        trend_groups["btts"].append({
            "value": stats["btts"],
            "icon": "🥅",
            "title": team_name,
            "text": (
                f"Ambos equipos marcaron "
                f"en {stats['btts']} "
                f"de sus últimos 5 partidos"
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

            used_teams.add(
                candidate["title"]
            )

            break


# --------------------------------------------------
# PARTIDOS DE HOY
# --------------------------------------------------

now_madrid = datetime.now(MADRID_TZ)

today = now_madrid.date()

today_events = get_events_for_date(
    today
)

today_matches = [
    format_sportsdb_event(event)
    for event in today_events
]


# --------------------------------------------------
# ESTA JORNADA
# --------------------------------------------------

matchday_dates = get_matchday_dates(
    today
)

journey_events = []

seen_events = set()


for matchday_date in matchday_dates:

    events = get_events_for_date(
        matchday_date
    )

    for event in events:

        event_id = event.get("idEvent")

        if event_id and event_id in seen_events:
            continue

        if event_id:
            seen_events.add(event_id)

        formatted_event = (
            format_sportsdb_event(event)
        )

        # Los partidos de hoy ya aparecen arriba,
        # así que no los repetimos en la jornada.
        if formatted_event["date"] == today.isoformat():
            continue

        journey_events.append(
            formatted_event
        )


journey_events.sort(
    key=lambda match: (
        match["date"] or "",
        match["time"] or ""
    )
)


# --------------------------------------------------
# ÚLTIMA ACTUALIZACIÓN
# --------------------------------------------------

last_updated = (
    now_madrid
    .strftime("%d/%m/%Y %H:%M")
)


# --------------------------------------------------
# JSON FINAL
# --------------------------------------------------

output = {
    "todayMatches": today_matches,

    "journeyMatches": journey_events,

    "trends": trends,

    "standings": standings,

    "teamStats": team_stats,

    "lastUpdated": last_updated
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

print(
    "Equipos:",
    len(standings)
)

print(
    "Tendencias:",
    len(trends)
)

print(
    "Partidos de hoy:",
    len(today_matches)
)

print(
    "Otros partidos de la jornada:",
    len(journey_events)
)

print(
    "Última actualización:",
    last_updated
)


print()
print("PARTIDOS DE HOY:")

for match in today_matches:

    print(
        match["time"],
        "-",
        match["home"],
        "vs",
        match["away"]
    )


print()
print("JORNADA:")

for match in journey_events:

    print(
        match["dateLabel"],
        match["time"],
        "-",
        match["home"],
        "vs",
        match["away"]
    )


print()
print("TENDENCIAS:")

for trend in trends:

    print(
        trend["icon"],
        trend["title"],
        "-",
        trend["text"]
    )