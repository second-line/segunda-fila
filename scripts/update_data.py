import os
import json
import re
import unicodedata

import requests
import truststore

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from dotenv import load_dotenv


# --------------------------------------------------
# CONFIGURACION
# --------------------------------------------------

truststore.inject_into_ssl()
load_dotenv(".env")

OPENFOOT_API_KEY = os.getenv("OPENFOOT_API_KEY")

if not OPENFOOT_API_KEY:
    raise Exception(
        "No se encontro OPENFOOT_API_KEY en .env"
    )

OPENFOOT_BASE_URL = "https://openfootapi.com/v1"
OPENFOOT_COMPETITION = "comp_segunda_es"
SEASON = "2026/27"

SPORTSDB_BASE_URL = (
    "https://www.thesportsdb.com/api/v1/json/123"
)
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
    "Castellón": "Castellón",

    "Leganes": "Leganés",
    "CD Leganes": "Leganés",
    "Leganés": "Leganés",

    "Almeria": "Almería",
    "UD Almeria": "Almería",
    "Almería": "Almería",

    "Cordoba": "Córdoba",
    "Cordoba CF": "Córdoba",
    "Córdoba": "Córdoba",

    "Cadiz": "Cádiz",
    "Cadiz CF": "Cádiz",
    "Cádiz": "Cádiz",

    "Sp Gijon": "Real Sporting",
    "Sporting Gijon": "Real Sporting",
    "Sporting de Gijón": "Real Sporting",
    "Real Sporting": "Real Sporting",

    "Sociedad B": "Real Sociedad B",
    "Real Sociedad B": "Real Sociedad B",

    "Celta Fortuna": "Celta B",
    "Celta B": "Celta B",

    "Real Oviedo": "Oviedo",
    "Oviedo": "Oviedo",

    "Real Valladolid": "Valladolid",
    "Valladolid": "Valladolid",
}


def normalize_team_name(name):
    if not name:
        return ""

    return TEAM_NAMES.get(name, name)


def slugify(value):
    if not value:
        return ""

    value = unicodedata.normalize(
        "NFKD",
        value
    )

    value = "".join(
        character
        for character in value
        if not unicodedata.combining(character)
    )

    value = value.lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value
    )

    return value.strip("-")


# --------------------------------------------------
# FECHAS
# --------------------------------------------------

def convert_utc_to_madrid(
    date_string,
    time_string
):
    if not date_string or not time_string:
        return ""

    clean_time = time_string[:8]

    utc_datetime = datetime.fromisoformat(
        f"{date_string}T{clean_time}"
    ).replace(
        tzinfo=timezone.utc
    )

    madrid_datetime = utc_datetime.astimezone(
        MADRID_TZ
    )

    return madrid_datetime.strftime("%H:%M")


def create_kickoff_utc(
    date_string,
    time_string
):
    if not date_string or not time_string:
        return None

    clean_time = time_string[:8]

    utc_datetime = datetime.fromisoformat(
        f"{date_string}T{clean_time}"
    ).replace(
        tzinfo=timezone.utc
    )

    return utc_datetime.isoformat()


def format_date_label(date_string):
    if not date_string:
        return ""

    value = datetime.fromisoformat(
        date_string
    ).date()

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
    weekday = today.weekday()

    if weekday == 0:
        friday = today - timedelta(days=3)

    elif weekday in [1, 2, 3]:
        friday = today + timedelta(
            days=(4 - weekday)
        )

    else:
        friday = today - timedelta(
            days=(weekday - 4)
        )

    return [
        friday,
        friday + timedelta(days=1),
        friday + timedelta(days=2),
        friday + timedelta(days=3)
    ]


# --------------------------------------------------
# DATOS EXISTENTES / CACHE
# --------------------------------------------------

def load_existing_data():
    path = "src/data/segunda.json"

    if not os.path.exists(path):
        return {}

    try:
        with open(
            path,
            "r",
            encoding="utf-8"
        ) as file:
            return json.load(file)

    except (
        json.JSONDecodeError,
        OSError
    ):
        return {}


existing_data = load_existing_data()

existing_matches = [
    *existing_data.get(
        "todayMatches",
        []
    ),
    *existing_data.get(
        "journeyMatches",
        []
    )
]

h2h_cache = {}

for existing_match in existing_matches:
    match_slug = existing_match.get(
        "matchSlug"
    )

    head_to_head = existing_match.get(
        "headToHead"
    )

    if (
        match_slug and
        head_to_head
    ):
        h2h_cache[
            match_slug
        ] = head_to_head


# --------------------------------------------------
# OPENFOOT - PARTIDOS
# --------------------------------------------------

def get_all_openfoot_matches():
    all_matches = []
    cursor = None

    while True:
        params = {
            "competition":
                OPENFOOT_COMPETITION,
            "season":
                SEASON
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

        payload = response.json()

        all_matches.extend(
            payload.get(
                "data",
                []
            )
        )

        pagination = (
            payload
            .get("meta", {})
            .get("pagination", {})
        )

        cursor = pagination.get(
            "next_cursor"
        )

        if not cursor:
            break

    return all_matches


# --------------------------------------------------
# ESTADISTICAS
# --------------------------------------------------

def calculate_period_stats(matches):
    played = len(matches)

    if played == 0:
        return {
            "played": 0,
            "wins": 0,
            "draws": 0,
            "losses": 0,
            "points": 0,
            "pointsPerGame": 0,
            "goalsFor": 0,
            "goalsAgainst": 0,
            "goalDifference": 0,
            "avgGoalsFor": 0,
            "avgGoalsAgainst": 0,
            "avgTotalGoals": 0,
            "btts": 0,
            "bttsPercentage": 0,
            "cleanSheets": 0,
            "cleanSheetPercentage": 0,
            "failedToScore": 0,
            "failedToScorePercentage": 0,
            "over15": 0,
            "over15Percentage": 0,
            "over25": 0,
            "over25Percentage": 0,
            "over35": 0,
            "over35Percentage": 0,
            "winPercentage": 0,
            "unbeatenPercentage": 0
        }

    wins = sum(
        1
        for match in matches
        if match["result"] == "W"
    )

    draws = sum(
        1
        for match in matches
        if match["result"] == "D"
    )

    losses = sum(
        1
        for match in matches
        if match["result"] == "L"
    )

    points = (
        wins * 3 +
        draws
    )

    goals_for = sum(
        match["goalsFor"]
        for match in matches
    )

    goals_against = sum(
        match["goalsAgainst"]
        for match in matches
    )

    btts = sum(
        1
        for match in matches
        if match["btts"]
    )

    clean_sheets = sum(
        1
        for match in matches
        if match["cleanSheet"]
    )

    failed_to_score = sum(
        1
        for match in matches
        if match["failedToScore"]
    )

    over15 = sum(
        1
        for match in matches
        if match["over15"]
    )

    over25 = sum(
        1
        for match in matches
        if match["over25"]
    )

    over35 = sum(
        1
        for match in matches
        if match["over35"]
    )

    unbeaten = wins + draws

    return {
        "played": played,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "points": points,

        "pointsPerGame":
            round(
                points / played,
                2
            ),

        "goalsFor":
            goals_for,

        "goalsAgainst":
            goals_against,

        "goalDifference":
            goals_for -
            goals_against,

        "avgGoalsFor":
            round(
                goals_for /
                played,
                2
            ),

        "avgGoalsAgainst":
            round(
                goals_against /
                played,
                2
            ),

        "avgTotalGoals":
            round(
                (
                    goals_for +
                    goals_against
                ) / played,
                2
            ),

        "btts":
            btts,

        "bttsPercentage":
            round(
                btts /
                played *
                100,
                1
            ),

        "cleanSheets":
            clean_sheets,

        "cleanSheetPercentage":
            round(
                clean_sheets /
                played *
                100,
                1
            ),

        "failedToScore":
            failed_to_score,

        "failedToScorePercentage":
            round(
                failed_to_score /
                played *
                100,
                1
            ),

        "over15":
            over15,

        "over15Percentage":
            round(
                over15 /
                played *
                100,
                1
            ),

        "over25":
            over25,

        "over25Percentage":
            round(
                over25 /
                played *
                100,
                1
            ),

        "over35":
            over35,

        "over35Percentage":
            round(
                over35 /
                played *
                100,
                1
            ),

        "winPercentage":
            round(
                wins /
                played *
                100,
                1
            ),

        "unbeatenPercentage":
            round(
                unbeaten /
                played *
                100,
                1
            )
    }


def calculate_streak(
    matches,
    condition
):
    streak = 0

    for match in reversed(matches):
        if not condition(match):
            break

        streak += 1

    return streak


def calculate_team_stats(
    team_id,
    matches
):
    team_matches = []

    for match in matches:
        if (
            match.get("status") !=
            "finished"
        ):
            continue

        home = (
            match.get("homeTeam")
            or {}
        )

        away = (
            match.get("awayTeam")
            or {}
        )

        if team_id not in [
            home.get("id"),
            away.get("id")
        ]:
            continue

        score = (
            match.get("score")
            or {}
        )

        home_score = score.get(
            "home"
        )

        away_score = score.get(
            "away"
        )

        if (
            home_score is None or
            away_score is None
        ):
            continue

        is_home = (
            home.get("id") ==
            team_id
        )

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

        if (
            goals_for >
            goals_against
        ):
            result = "W"

        elif (
            goals_for ==
            goals_against
        ):
            result = "D"

        else:
            result = "L"

        opponent_team = (
            away
            if is_home
            else home
        )

        opponent = normalize_team_name(
            opponent_team.get("name")
        )

        team_matches.append({
            "date":
                match.get("kickoffAt"),

            "result":
                result,

            "goalsFor":
                goals_for,

            "goalsAgainst":
                goals_against,

            "isHome":
                is_home,

            "opponent":
                opponent,

            "btts":
                (
                    goals_for > 0 and
                    goals_against > 0
                ),

            "cleanSheet":
                goals_against == 0,

            "failedToScore":
                goals_for == 0,

            "over15":
                (
                    goals_for +
                    goals_against
                ) > 1,

            "over25":
                (
                    goals_for +
                    goals_against
                ) > 2,

            "over35":
                (
                    goals_for +
                    goals_against
                ) > 3
        })

    team_matches.sort(
        key=lambda item:
            item["date"] or ""
    )

    if not team_matches:
        return None

    last5_matches = (
        team_matches[-5:]
    )

    last10_matches = (
        team_matches[-10:]
    )

    home_matches = [
        match
        for match in team_matches
        if match["isHome"]
    ][-5:]

    away_matches = [
        match
        for match in team_matches
        if not match["isHome"]
    ][-5:]

    all_home_matches = [
        match
        for match in team_matches
        if match["isHome"]
    ]

    all_away_matches = [
        match
        for match in team_matches
        if not match["isHome"]
    ]

    form = [
        match["result"]
        for match in last5_matches
    ]

    return {
        "form":
            form,

        "winStreak":
            calculate_streak(
                team_matches,
                lambda match:
                    match["result"]
                    == "W"
            ),

        "unbeatenStreak":
            calculate_streak(
                team_matches,
                lambda match:
                    match["result"]
                    != "L"
            ),

        "losingStreak":
            calculate_streak(
                team_matches,
                lambda match:
                    match["result"]
                    == "L"
            ),

        "winlessStreak":
            calculate_streak(
                team_matches,
                lambda match:
                    match["result"]
                    != "W"
            ),

        "scoringStreak":
            calculate_streak(
                team_matches,
                lambda match:
                    match["goalsFor"] > 0
            ),

        "concedingStreak":
            calculate_streak(
                team_matches,
                lambda match:
                    match["goalsAgainst"] > 0
            ),

        "cleanSheetStreak":
            calculate_streak(
                team_matches,
                lambda match:
                    match["goalsAgainst"] == 0
            ),

        "noScoreStreak":
            calculate_streak(
                team_matches,
                lambda match:
                    match["goalsFor"] == 0
            ),

        "homeWinStreak":
            calculate_streak(
                all_home_matches,
                lambda match:
                    match["result"] == "W"
            ),

        "homeUnbeatenStreak":
            calculate_streak(
                all_home_matches,
                lambda match:
                    match["result"] != "L"
            ),

        "awayWinStreak":
            calculate_streak(
                all_away_matches,
                lambda match:
                    match["result"] == "W"
            ),

        "awayUnbeatenStreak":
            calculate_streak(
                all_away_matches,
                lambda match:
                    match["result"] != "L"
            ),

        "last5":
            calculate_period_stats(
                last5_matches
            ),

        "last10":
            calculate_period_stats(
                last10_matches
            ),

        "home":
            calculate_period_stats(
                home_matches
            ),

        "away":
            calculate_period_stats(
                away_matches
            ),

        "recentMatches":
            last5_matches
    }


# --------------------------------------------------
# H2H HISTORICO OPENFOOT
# --------------------------------------------------

def get_h2h_from_openfoot(
    team_id,
    opponent_id,
    current_match_date,
    limit=5
):
    response = requests.get(
        (
            f"{OPENFOOT_BASE_URL}"
            f"/teams/{team_id}/h2h"
        ),
        headers=openfoot_headers,
        params={
            "opponent":
                opponent_id
        },
        timeout=30
    )

    if response.status_code == 429:
        print(
            "Aviso: limite temporal de TheSportsDB para",
            day.isoformat()
        )

        sportsdb_day_cache[cache_key] = []

        return []

    if response.status_code == 429:
        print(
            "Aviso: limite temporal de TheSportsDB para",
            day.isoformat()
        )

        sportsdb_day_cache[cache_key] = []

        return []

    response.raise_for_status()

    payload = response.json()

    h2h_data = (
        payload.get("data")
        or {}
    )

    recent_meetings = (
        h2h_data.get(
            "recentMeetings"
        )
        or []
    )

    meetings = []

    for meeting in recent_meetings:
        score = (
            meeting.get("score")
            or {}
        )

        home_score = score.get(
            "home"
        )

        away_score = score.get(
            "away"
        )

        # No queremos partidos futuros.
        if (
            home_score is None or
            away_score is None
        ):
            continue

        meeting_date = (
            meeting.get("date")
            or ""
        )[:10]

        # Solo encuentros anteriores
        # al partido que estamos mostrando.
        if (
            current_match_date and
            meeting_date >=
            current_match_date
        ):
            continue

        raw_home = (
            meeting.get("homeTeam")
            or {}
        )

        raw_away = (
            meeting.get("awayTeam")
            or {}
        )

        home_name = normalize_team_name(
            raw_home.get("name")
        )

        away_name = normalize_team_name(
            raw_away.get("name")
        )

        meetings.append({
            "date":
                meeting_date,

            "home":
                home_name,

            "away":
                away_name,

            "homeSlug":
                slugify(
                    home_name
                ),

            "awaySlug":
                slugify(
                    away_name
                ),

            "homeScore":
                home_score,

            "awayScore":
                away_score
        })

    meetings.sort(
        key=lambda item:
            item["date"],
        reverse=True
    )

    meetings = meetings[:limit]

    return build_h2h_summary(
        team_id,
        opponent_id,
        meetings
    )


def build_h2h_summary(
    team_id,
    opponent_id,
    meetings
):
    # El endpoint beta ha mostrado
    # IDs inconsistentes en algunos
    # recentMeetings, asi que el resumen
    # visual se calcula posteriormente
    # usando los nombres del partido.
    return {
        "meetings":
            meetings
    }


def enrich_match_with_h2h(
    match,
    team_ids_by_slug
):
    match_slug = match.get(
        "matchSlug"
    )

    # Si ya lo descargamos en una
    # ejecucion anterior, reutilizamos
    # el dato y ahorramos cuota.
    if (
        match_slug in
        h2h_cache
    ):
        match["headToHead"] = (
            h2h_cache[
                match_slug
            ]
        )

        return

    home_id = team_ids_by_slug.get(
        match.get("homeSlug")
    )

    away_id = team_ids_by_slug.get(
        match.get("awaySlug")
    )

    if (
        not home_id or
        not away_id
    ):
        match["headToHead"] = {
            "meetings": []
        }

        return

    try:
        match["headToHead"] = (
            get_h2h_from_openfoot(
                home_id,
                away_id,
                match.get("date"),
                limit=5
            )
        )

    except requests.RequestException as error:
        print(
            "No se pudo obtener H2H para",
            match.get("home"),
            "-",
            match.get("away"),
            ":",
            error
        )

        match["headToHead"] = {
            "meetings": []
        }


# --------------------------------------------------
# THESPORTSDB
# --------------------------------------------------

sportsdb_day_cache = {}


def get_events_for_date(day):

    cache_key = day.isoformat()

    if cache_key in sportsdb_day_cache:
        return sportsdb_day_cache[cache_key]


    events_by_id = {}


    # 1. Endpoint principal por fecha

    response = requests.get(
        (
            f"{SPORTSDB_BASE_URL}"
            "/eventsday.php"
        ),
        params={
            "d":
                day.isoformat(),

            "l":
                SPORTSDB_LEAGUE_ID
        },
        timeout=30
    )

    response.raise_for_status()

    payload = response.json()

    for event in (
        payload.get("events")
        or []
    ):

        event_id = event.get(
            "idEvent"
        )

        key = (
            event_id
            or
            (
                event.get("dateEvent"),
                event.get("strHomeTeam"),
                event.get("strAwayTeam")
            )
        )

        events_by_id[key] = event


    # 2. Refuerzo con proximos partidos
    #
    # eventsday puede devolver una lista
    # incompleta en algunos momentos.

    try:

        response = requests.get(
            (
                f"{SPORTSDB_BASE_URL}"
                "/eventsnextleague.php"
            ),
            params={
                "id":
                    SPORTSDB_LEAGUE_ID
            },
            timeout=30
        )

        response.raise_for_status()

        payload = response.json()

        for event in (
            payload.get("events")
            or []
        ):

            if (
                event.get("dateEvent")
                != day.isoformat()
            ):
                continue

            event_id = event.get(
                "idEvent"
            )

            key = (
                event_id
                or
                (
                    event.get("dateEvent"),
                    event.get("strHomeTeam"),
                    event.get("strAwayTeam")
                )
            )

            events_by_id[key] = event

    except requests.RequestException as error:

        print(
            "Aviso: no se pudieron consultar "
            "los proximos partidos:",
            error
        )


    # 3. Refuerzo con ultimos partidos
    #
    # Sirve para partidos que hayan acabado
    # recientemente y no aparezcan bien
    # en eventsday.

    try:

        response = requests.get(
            (
                f"{SPORTSDB_BASE_URL}"
                "/eventspastleague.php"
            ),
            params={
                "id":
                    SPORTSDB_LEAGUE_ID
            },
            timeout=30
        )

        response.raise_for_status()

        payload = response.json()

        for event in (
            payload.get("events")
            or []
        ):

            if (
                event.get("dateEvent")
                != day.isoformat()
            ):
                continue

            event_id = event.get(
                "idEvent"
            )

            key = (
                event_id
                or
                (
                    event.get("dateEvent"),
                    event.get("strHomeTeam"),
                    event.get("strAwayTeam")
                )
            )

            events_by_id[key] = event

    except requests.RequestException as error:

        print(
            "Aviso: no se pudieron consultar "
            "los ultimos partidos:",
            error
        )


    events = list(
        events_by_id.values()
    )


    events.sort(
        key=lambda event: (
            event.get("dateEvent")
            or "",
            event.get("strTime")
            or ""
        )
    )


    sportsdb_day_cache[
        cache_key
    ] = events

    return events



def format_sportsdb_event(event):
    event_date = event.get(
        "dateEvent"
    )

    event_time = event.get(
        "strTime"
    )

    home_score = event.get(
        "intHomeScore"
    )

    away_score = event.get(
        "intAwayScore"
    )

    if home_score not in [
        None,
        ""
    ]:
        try:
            home_score = int(
                home_score
            )

        except (
            ValueError,
            TypeError
        ):
            pass

    if away_score not in [
        None,
        ""
    ]:
        try:
            away_score = int(
                away_score
            )

        except (
            ValueError,
            TypeError
        ):
            pass

    home_name = normalize_team_name(
        event.get("strHomeTeam")
    )

    away_name = normalize_team_name(
        event.get("strAwayTeam")
    )

    home_slug = slugify(
        home_name
    )

    away_slug = slugify(
        away_name
    )

    match_slug = None

    if (
        event_date and
        home_slug and
        away_slug
    ):
        match_slug = (
            f"{home_slug}-vs-"
            f"{away_slug}-"
            f"{event_date}"
        )

    return {
        "id":
            event.get("idEvent"),

        "date":
            event_date,

        "dateLabel":
            format_date_label(
                event_date
            ),

        "time":
            convert_utc_to_madrid(
                event_date,
                event_time
            ),

        "kickoffUtc":
            create_kickoff_utc(
                event_date,
                event_time
            ),

        "status":
            event.get("strStatus"),

        "home":
            home_name,

        "away":
            away_name,

        "homeSlug":
            home_slug,

        "awaySlug":
            away_slug,

        "matchSlug":
            match_slug,

        "homeScore":
            home_score,

        "awayScore":
            away_score
    }



# --------------------------------------------------
# PARCHE DE RESULTADOS RECIENTES
# --------------------------------------------------


def is_sportsdb_finished(event):

    status = str(
        event.get("strStatus")
        or ""
    ).strip().lower()

    return status in {
        "ft",
        "finished",
        "match finished"
    }


def openfoot_match_key(match):

    kickoff_at = (
        match.get("kickoffAt")
        or ""
    )

    match_date = kickoff_at[:10]

    home = (
        match.get("homeTeam")
        or {}
    )

    away = (
        match.get("awayTeam")
        or {}
    )

    return (
        match_date,
        slugify(
            normalize_team_name(
                home.get("name")
            )
        ),
        slugify(
            normalize_team_name(
                away.get("name")
            )
        )
    )


def sportsdb_match_key(match):

    return (
        match.get("date") or "",
        match.get("homeSlug") or "",
        match.get("awaySlug") or ""
    )


def get_recent_sportsdb_finished_matches(
    start_date,
    end_date
):

    matches = []
    day = start_date

    while day <= end_date:

        for event in get_events_for_date(day):

            if not is_sportsdb_finished(event):
                continue

            formatted = format_sportsdb_event(
                event
            )

            if (
                formatted.get("homeScore")
                is None
                or
                formatted.get("awayScore")
                is None
            ):
                continue

            matches.append(
                formatted
            )

        day += timedelta(days=1)

    return matches


def sportsdb_to_openfoot_match(
    match,
    team_ids_by_slug
):

    home_id = (
        team_ids_by_slug.get(
            match.get("homeSlug")
        )
    )

    away_id = (
        team_ids_by_slug.get(
            match.get("awaySlug")
        )
    )

    if not home_id or not away_id:
        return None

    return {
        "id":
            "sportsdb_"
            + str(
                match.get("id")
                or ""
            ),

        "competitionId":
            OPENFOOT_COMPETITION,

        "season":
            SEASON,

        "kickoffAt":
            (
                match.get("kickoffUtc")
                or
                f"{match.get('date')}T00:00:00+00:00"
            ),

        "status":
            "finished",

        "homeTeam": {
            "id":
                home_id,

            "name":
                match.get("home")
        },

        "awayTeam": {
            "id":
                away_id,

            "name":
                match.get("away")
        },

        "score": {
            "home":
                match.get("homeScore"),

            "away":
                match.get("awayScore")
        },

        "source":
            "thesportsdb"
    }


def apply_supplemental_matches_to_standings(
    standings,
    matches
):

    rows_by_slug = {
        row.get("slug"):
            row

        for row in standings
    }

    for match in matches:

        home = rows_by_slug.get(
            match.get("homeSlug")
        )

        away = rows_by_slug.get(
            match.get("awaySlug")
        )

        if not home or not away:

            print(
                "Aviso: no se pudo aplicar "
                "a la clasificacion:",
                match.get("home"),
                "-",
                match.get("away")
            )

            continue

        home_score = match.get(
            "homeScore"
        )

        away_score = match.get(
            "awayScore"
        )

        home["played"] += 1
        away["played"] += 1

        home["goalsFor"] += (
            home_score
        )

        home["goalsAgainst"] += (
            away_score
        )

        away["goalsFor"] += (
            away_score
        )

        away["goalsAgainst"] += (
            home_score
        )

        if home_score > away_score:

            home["won"] += 1
            home["points"] += 3

            away["lost"] += 1

        elif home_score < away_score:

            away["won"] += 1
            away["points"] += 3

            home["lost"] += 1

        else:

            home["drawn"] += 1
            away["drawn"] += 1

            home["points"] += 1
            away["points"] += 1

        home["goalDifference"] = (
            home["goalsFor"]
            -
            home["goalsAgainst"]
        )

        away["goalDifference"] = (
            away["goalsFor"]
            -
            away["goalsAgainst"]
        )

    standings.sort(
        key=lambda row: (
            -row.get(
                "points",
                0
            ),

            -row.get(
                "goalDifference",
                0
            ),

            -row.get(
                "goalsFor",
                0
            ),

            row.get(
                "team",
                ""
            )
        )
    )

    for index, row in enumerate(
        standings,
        start=1
    ):
        row["pos"] = index


# --------------------------------------------------
# CLASIFICACION
# --------------------------------------------------

standings_response = requests.get(
    f"{OPENFOOT_BASE_URL}/standings",
    headers=openfoot_headers,
    params={
        "competition":
            OPENFOOT_COMPETITION
    },
    timeout=30
)

standings_response.raise_for_status()

standings_payload = (
    standings_response.json()
)

table = (
    standings_payload
    .get("data", {})
    .get("table", [])
)

standings = []
teams = []

for row in table:
    raw_team = (
        row.get("team")
        or {}
    )

    team_name = normalize_team_name(
        raw_team.get("name")
    )

    team_slug = slugify(
        team_name
    )

    team = {
        "id":
            raw_team.get("id"),

        "name":
            team_name,

        "slug":
            team_slug
    }

    teams.append(team)

    total = (
        row.get("total")
        or {}
    )

    standings.append({
        "pos":
            row.get("position"),

        "team":
            team_name,

        "slug":
            team_slug,

        "played":
            total.get(
                "played",
                0
            ),

        "points":
            total.get(
                "points",
                0
            ),

        "won":
            total.get(
                "won",
                0
            ),

        "drawn":
            total.get(
                "drawn",
                0
            ),

        "lost":
            total.get(
                "lost",
                0
            ),

        "goalsFor":
            total.get(
                "goalsFor",
                0
            ),

        "goalsAgainst":
            total.get(
                "goalsAgainst",
                0
            ),

        "goalDifference":
            total.get(
                "goalDifference",
                0
            ),

        "form":
            row.get(
                "form",
                []
            )
    })


team_ids_by_slug = {
    team["slug"]:
        team["id"]
    for team in teams
    if (
        team.get("slug") and
        team.get("id")
    )
}


# --------------------------------------------------
# HISTORICO TEMPORADA ACTUAL + PARCHE THESPORTSDB
# --------------------------------------------------

all_matches = (
    get_all_openfoot_matches()
)


finished_openfoot_matches = [
    match

    for match in all_matches

    if (
        match.get("status")
        == "finished"
    )
]


openfoot_finished_keys = {
    openfoot_match_key(match)

    for match
    in finished_openfoot_matches
}


openfoot_finished_dates = [
    (
        match.get("kickoffAt")
        or ""
    )[:10]

    for match
    in finished_openfoot_matches

    if match.get("kickoffAt")
]


latest_openfoot_date = (
    max(
        openfoot_finished_dates
    )

    if openfoot_finished_dates

    else None
)


now_madrid = datetime.now(
    MADRID_TZ
)

today = now_madrid.date()


recent_sportsdb_matches = []


if latest_openfoot_date:

    recent_start_date = (
        datetime.fromisoformat(
            latest_openfoot_date
        ).date()
    )

    recent_sportsdb_matches = (
        get_recent_sportsdb_finished_matches(
            recent_start_date,
            today
        )
    )


# --------------------------------------------------
# PROTECCION CONTRA STANDINGS ADELANTADO
# --------------------------------------------------

# Puede ocurrir que OpenFoot actualice /standings
# antes que /matches.
#
# Ejemplo:
#   standings -> Eibar PJ 8
#   matches   -> Eibar solo tiene 7 finished
#
# En ese caso NO debemos sumar otra vez el
# resultado reciente de TheSportsDB.


openfoot_played_by_slug = {}


for match in finished_openfoot_matches:

    home = (
        match.get("homeTeam")
        or {}
    )

    away = (
        match.get("awayTeam")
        or {}
    )


    home_slug = slugify(
        normalize_team_name(
            home.get("name")
        )
    )

    away_slug = slugify(
        normalize_team_name(
            away.get("name")
        )
    )


    if home_slug:

        openfoot_played_by_slug[
            home_slug
        ] = (
            openfoot_played_by_slug.get(
                home_slug,
                0
            )
            + 1
        )


    if away_slug:

        openfoot_played_by_slug[
            away_slug
        ] = (
            openfoot_played_by_slug.get(
                away_slug,
                0
            )
            + 1
        )


standings_played_by_slug = {
    row.get("slug"):
        row.get(
            "played",
            0
        )

    for row in standings

    if row.get("slug")
}


# Numero de partidos que standings conoce
# pero /matches todavia no contiene.
#
# Lo tratamos como una especie de credito:
#
#   standings PJ 8
#   matches   PJ 7
#   credito      1


standings_ahead_slots = {}


for slug, played in (
    standings_played_by_slug.items()
):

    matches_played = (
        openfoot_played_by_slug.get(
            slug,
            0
        )
    )

    standings_ahead_slots[
        slug
    ] = max(
        played - matches_played,
        0
    )


sportsdb_candidates = [
    match

    for match
    in recent_sportsdb_matches

    if (
        sportsdb_match_key(match)
        not in openfoot_finished_keys
    )
]


# Los procesamos cronologicamente.
#
# Si ambos equipos tienen un "slot" adelantado
# en standings, asumimos que ese partido ya esta
# reflejado en la tabla aunque aun no aparezca
# en /matches.


sportsdb_candidates.sort(
    key=lambda match: (
        match.get("date")
        or "",
        match.get("kickoffUtc")
        or ""
    )
)


supplemental_sportsdb_matches = []


for match in sportsdb_candidates:

    home_slug = match.get(
        "homeSlug"
    )

    away_slug = match.get(
        "awaySlug"
    )


    home_ahead = (
        standings_ahead_slots.get(
            home_slug,
            0
        )
    )

    away_ahead = (
        standings_ahead_slots.get(
            away_slug,
            0
        )
    )


    if (
        home_ahead > 0
        and
        away_ahead > 0
    ):

        standings_ahead_slots[
            home_slug
        ] -= 1

        standings_ahead_slots[
            away_slug
        ] -= 1


        print(
            "Resultado ya reflejado "
            "en standings, no se suma:",
            match.get("home"),
            match.get("homeScore"),
            "-",
            match.get("awayScore"),
            match.get("away")
        )


        continue


    supplemental_sportsdb_matches.append(
        match
    )


apply_supplemental_matches_to_standings(
    standings,
    supplemental_sportsdb_matches
)


supplemental_openfoot_matches = []


for match in (
    supplemental_sportsdb_matches
):

    converted = (
        sportsdb_to_openfoot_match(
            match,
            team_ids_by_slug
        )
    )

    if converted:

        supplemental_openfoot_matches.append(
            converted
        )

    else:

        print(
            "Aviso: partido reciente "
            "sin IDs compatibles:",
            match.get("home"),
            "-",
            match.get("away")
        )


finished_matches = [
    *finished_openfoot_matches,
    *supplemental_openfoot_matches
]


# --------------------------------------------------
# JORNADA DE LA CLASIFICACION
# --------------------------------------------------

base_matchday = max(
    (
        row.get(
            "played",
            0
        )

        -

        sum(
            1

            for match
            in supplemental_sportsdb_matches

            if (
                row.get("slug")
                in {
                    match.get(
                        "homeSlug"
                    ),

                    match.get(
                        "awaySlug"
                    )
                }
            )
        )

        for row in standings
    ),

    default=0
)


classification_matchday = max(
    (
        row.get(
            "played",
            0
        )

        for row in standings
    ),

    default=base_matchday
)


# La tabla solo se considera provisional
# durante la jornada real: viernes-lunes.
#
# Cuando todos los partidos terminan,
# pasa a estable aunque OpenFoot siga
# unos dias por detras.

standings_provisional = False


if today.weekday() in {
    0,
    4,
    5,
    6
}:

    current_matchday_events = []


    for matchday_date in (
        get_matchday_dates(
            today
        )
    ):

        current_matchday_events.extend(
            get_events_for_date(
                matchday_date
            )
        )


    if current_matchday_events:

        finished_flags = [
            is_sportsdb_finished(
                event
            )

            for event
            in current_matchday_events
        ]


        has_started_matchday = any(
            finished_flags
        )


        # Puede haber un partido en juego
        # antes de que exista ningun FT.

        if not has_started_matchday:

            for event in (
                current_matchday_events
            ):

                status = str(
                    event.get(
                        "strStatus"
                    )
                    or ""
                ).strip().lower()


                if status not in {
                    "",
                    "ns",
                    "not started",
                    "scheduled"
                }:

                    has_started_matchday = True

                    break


        matchday_complete = all(
            finished_flags
        )


        standings_provisional = (
            has_started_matchday
            and
            not matchday_complete
        )


        if has_started_matchday:

            classification_matchday = max(
                classification_matchday,
                base_matchday + 1
            )


print(
    "OpenFoot actualizado hasta:",
    latest_openfoot_date
)


print(
    "Resultados recientes añadidos "
    "desde TheSportsDB:",
    len(
        supplemental_sportsdb_matches
    )
)


for match in (
    supplemental_sportsdb_matches
):

    print(
        "  +",
        match.get("date"),
        match.get("home"),
        match.get("homeScore"),
        "-",
        match.get("awayScore"),
        match.get("away")
    )


print(
    "Partidos terminados analizados:",
    len(
        finished_matches
    )
)


print(
    f"Clasificacion mostrada: "
    f"J{classification_matchday}",

    (
        "(provisional)"
        if standings_provisional
        else "(estable)"
    )
)


# --------------------------------------------------
# ESTADISTICAS EQUIPOS
# --------------------------------------------------

team_stats = {}

for team in teams:
    stats = calculate_team_stats(
        team["id"],
        finished_matches
    )

    if not stats:
        continue

    team_stats[
        team["id"]
    ] = {
        "id":
            team["id"],

        "name":
            team["name"],

        "slug":
            team["slug"],

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
    "btts": [],
    "cleanSheets": [],
    "home": [],
    "away": []
}

for team_id, stats in (
    team_stats.items()
):
    team_name = stats["name"]
    team_slug = stats["slug"]

    if stats["winStreak"] >= 3:
        trend_groups[
            "wins"
        ].append({
            "value":
                stats["winStreak"],

            "icon":
                "🔥",

            "title":
                team_name,

            "slug":
                team_slug,

            "text":
                (
                    f"{stats['winStreak']} "
                    "victorias consecutivas"
                )
        })

    if (
        stats["unbeatenStreak"]
        >= 4
    ):
        trend_groups[
            "unbeaten"
        ].append({
            "value":
                stats[
                    "unbeatenStreak"
                ],

            "icon":
                "🛡️",

            "title":
                team_name,

            "slug":
                team_slug,

            "text":
                (
                    f"{stats['unbeatenStreak']} "
                    "partidos sin perder"
                )
        })

    if (
        stats["scoringStreak"]
        >= 4
    ):
        trend_groups[
            "scoring"
        ].append({
            "value":
                stats[
                    "scoringStreak"
                ],

            "icon":
                "⚽",

            "title":
                team_name,

            "slug":
                team_slug,

            "text":
                (
                    "Ha marcado en sus últimos "
                    f"{stats['scoringStreak']} "
                    "partidos"
                )
        })

    if (
        stats["last5"][
            "avgGoalsFor"
        ] >= 1.8
    ):
        trend_groups[
            "goals"
        ].append({
            "value":
                stats["last5"][
                    "avgGoalsFor"
                ],

            "icon":
                "🎯",

            "title":
                team_name,

            "slug":
                team_slug,

            "text":
                (
                    "Promedia "
                    f"{stats['last5']['avgGoalsFor']} "
                    "goles por partido "
                    "en sus últimos 5"
                )
        })

    if (
        stats["last5"][
            "bttsPercentage"
        ] >= 60
    ):
        trend_groups[
            "btts"
        ].append({
            "value":
                stats["last5"][
                    "bttsPercentage"
                ],

            "icon":
                "🥅",

            "title":
                team_name,

            "slug":
                team_slug,

            "text":
                (
                    "Ambos equipos marcaron "
                    "en el "
                    f"{stats['last5']['bttsPercentage']}% "
                    "de sus últimos 5 partidos"
                )
        })

    if (
        stats["last5"][
            "cleanSheetPercentage"
        ] >= 60
    ):
        trend_groups[
            "cleanSheets"
        ].append({
            "value":
                stats["last5"][
                    "cleanSheetPercentage"
                ],

            "icon":
                "🧱",

            "title":
                team_name,

            "slug":
                team_slug,

            "text":
                (
                    "Portería a cero en "
                    f"{stats['last5']['cleanSheets']} "
                    "de sus últimos 5 partidos"
                )
        })

    if (
        stats["home"]["played"] >= 3 and
        stats["home"][
            "winPercentage"
        ] >= 60
    ):
        trend_groups[
            "home"
        ].append({
            "value":
                stats["home"][
                    "winPercentage"
                ],

            "icon":
                "🏠",

            "title":
                team_name,

            "slug":
                team_slug,

            "text":
                (
                    "Ha ganado el "
                    f"{stats['home']['winPercentage']}% "
                    "de sus últimos partidos "
                    "como local"
                )
        })

    if (
        stats["away"]["played"] >= 3 and
        stats["away"][
            "winPercentage"
        ] >= 60
    ):
        trend_groups[
            "away"
        ].append({
            "value":
                stats["away"][
                    "winPercentage"
                ],

            "icon":
                "✈️",

            "title":
                team_name,

            "slug":
                team_slug,

            "text":
                (
                    "Ha ganado el "
                    f"{stats['away']['winPercentage']}% "
                    "de sus últimos partidos "
                    "como visitante"
                )
        })


trends = []
used_teams = set()

category_order = [
    "wins",
    "unbeaten",
    "scoring",
    "goals",
    "btts",
    "cleanSheets",
    "home",
    "away"
]

for category in category_order:
    candidates = sorted(
        trend_groups[category],
        key=lambda item:
            item["value"],
        reverse=True
    )

    for candidate in candidates:
        if (
            candidate["slug"]
            in used_teams
        ):
            continue

        trends.append({
            "icon":
                candidate["icon"],

            "title":
                candidate["title"],

            "slug":
                candidate["slug"],

            "text":
                candidate["text"]
        })

        used_teams.add(
            candidate["slug"]
        )

        break

    if len(trends) >= 6:
        break


# --------------------------------------------------
# PARTIDOS DE HOY
# --------------------------------------------------

today_events = get_events_for_date(
    today
)

today_matches = [
    format_sportsdb_event(
        event
    )
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
        event_id = event.get(
            "idEvent"
        )

        if (
            event_id and
            event_id in seen_events
        ):
            continue

        if event_id:
            seen_events.add(
                event_id
            )

        formatted_event = (
            format_sportsdb_event(
                event
            )
        )

        if (
            formatted_event["date"] ==
            today.isoformat()
        ):
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
# CONSERVAR PARTIDOS PREVIOS SI LA API VIENE INCOMPLETA
# --------------------------------------------------

def fixture_key(match):
    return (
        match.get("date") or "",
        match.get("homeSlug") or "",
        match.get("awaySlug") or ""
    )


current_today_keys = {
    fixture_key(match)
    for match in today_matches
}

current_journey_keys = {
    fixture_key(match)
    for match in journey_events
}


for old_match in existing_matches:

    match_date = old_match.get("date")

    if not match_date:
        continue

    key = fixture_key(old_match)

    # Partido de hoy que la API ya no devuelve.
    if (
        match_date == today.isoformat()
        and
        key not in current_today_keys
    ):
        print(
            "Recuperando partido previo de hoy:",
            old_match.get("home"),
            "-",
            old_match.get("away")
        )

        today_matches.append(
            old_match
        )

        current_today_keys.add(
            key
        )

        continue

    # Partido del resto de la jornada.
    if (
        match_date in {
            day.isoformat()
            for day in matchday_dates
        }
        and
        match_date != today.isoformat()
        and
        key not in current_journey_keys
    ):
        print(
            "Recuperando partido previo de jornada:",
            old_match.get("home"),
            "-",
            old_match.get("away")
        )

        journey_events.append(
            old_match
        )

        current_journey_keys.add(
            key
        )


today_matches.sort(
    key=lambda match:
        match.get("time") or ""
)

journey_events.sort(
    key=lambda match: (
        match.get("date") or "",
        match.get("time") or ""
    )
)


# --------------------------------------------------
# AÑADIR H2H HISTORICO
# --------------------------------------------------

all_current_matches = [
    *today_matches,
    *journey_events
]

for match in all_current_matches:
    enrich_match_with_h2h(
        match,
        team_ids_by_slug
    )


def validate_output_data(
    teams,
    standings,
    team_stats,
    today_matches,
    journey_matches
):
    errors = []
    warnings = []

    all_matches = [
        *today_matches,
        *journey_matches
    ]

    team_slugs = [
        team.get("slug")
        for team in teams
        if team.get("slug")
    ]

    stats_slugs = {
        stats.get("slug")
        for stats in team_stats.values()
        if stats.get("slug")
    }

    # 1. Numero esperado de equipos
    if len(teams) != 22:
        errors.append(
            f"Se esperaban 22 equipos y hay {len(teams)}"
        )

    if len(standings) != 22:
        errors.append(
            f"La clasificacion tiene {len(standings)} equipos"
        )

    # 2. Slugs duplicados
    duplicated_slugs = {
        slug
        for slug in team_slugs
        if team_slugs.count(slug) > 1
    }

    if duplicated_slugs:
        errors.append(
            "Slugs duplicados: "
            + ", ".join(
                sorted(duplicated_slugs)
            )
        )

    # 3. Equipos sin estadisticas
    missing_stats = [
        team["name"]
        for team in teams
        if team.get("slug") not in stats_slugs
    ]

    if missing_stats:
        errors.append(
            "Equipos sin teamStats: "
            + ", ".join(missing_stats)
        )

    # 4. Partidos sin slug o equipos
    for match in all_matches:
        label = (
            f"{match.get('home')} - "
            f"{match.get('away')}"
        )

        if not match.get("matchSlug"):
            errors.append(
                f"Partido sin matchSlug: {label}"
            )

        if not match.get("homeSlug"):
            errors.append(
                f"Partido sin homeSlug: {label}"
            )

        if not match.get("awaySlug"):
            errors.append(
                f"Partido sin awaySlug: {label}"
            )

    # 5. Equipos de partidos sin estadisticas
    for match in all_matches:
        label = (
            f"{match.get('home')} - "
            f"{match.get('away')}"
        )

        home_slug = match.get(
            "homeSlug"
        )

        away_slug = match.get(
            "awaySlug"
        )

        if (
            home_slug and
            home_slug not in stats_slugs
        ):
            errors.append(
                f"Local sin teamStats: "
                f"{label} -> {home_slug}"
            )

        if (
            away_slug and
            away_slug not in stats_slugs
        ):
            errors.append(
                f"Visitante sin teamStats: "
                f"{label} -> {away_slug}"
            )

    # 6. Resultados incompletos
    for match in all_matches:
        home_score = match.get(
            "homeScore"
        )

        away_score = match.get(
            "awayScore"
        )

        one_score_only = (
            (
                home_score is not None and
                away_score is None
            )
            or
            (
                home_score is None and
                away_score is not None
            )
        )

        if one_score_only:
            warnings.append(
                "Marcador incompleto: "
                f"{match.get('home')} - "
                f"{match.get('away')}"
            )

    # 7. H2H
    for match in all_matches:
        h2h = (
            match
            .get("headToHead", {})
            .get("meetings", [])
        )

        for meeting in h2h:
            if (
                meeting.get("homeScore")
                is None or
                meeting.get("awayScore")
                is None
            ):
                errors.append(
                    "H2H con marcador vacio: "
                    f"{match.get('home')} - "
                    f"{match.get('away')}"
                )

    # 8. Estadisticas basicas coherentes
    for stats in team_stats.values():
        last5 = stats.get(
            "last5",
            {}
        )

        played = last5.get(
            "played",
            0
        )

        wins = last5.get(
            "wins",
            0
        )

        draws = last5.get(
            "draws",
            0
        )

        losses = last5.get(
            "losses",
            0
        )

        if (
            wins +
            draws +
            losses !=
            played
        ):
            errors.append(
                f"Stats incoherentes en "
                f"{stats.get('name')}: "
                f"V+E+D != PJ"
            )

        if played > 5:
            errors.append(
                f"last5 tiene mas de 5 partidos "
                f"para {stats.get('name')}"
            )

    print()
    print("VALIDACION")
    print("----------")

    if warnings:
        print()
        print("Avisos:")

        for warning in warnings:
            print(
                f"  - {warning}"
            )

    if errors:
        print()
        print("Errores:")

        for error in errors:
            print(
                f"  - {error}"
            )

        raise Exception(
            "La validacion de datos ha fallado"
        )

    print(
        "OK - Datos consistentes"
    )

    print(
        f"  Equipos: {len(teams)}"
    )

    print(
        f"  TeamStats: {len(team_stats)}"
    )

    print(
        f"  Partidos: {len(all_matches)}"
    )


validate_output_data(
    teams,
    standings,
    team_stats,
    today_matches,
    journey_events
)

# --------------------------------------------------
# JSON FINAL
# --------------------------------------------------

output = {
    "teams":
        teams,

    "todayMatches":
        today_matches,

    "journeyMatches":
        journey_events,

    "trends":
        trends,

    "standings":
        standings,

    "classificationMatchday":
        classification_matchday,

    "standingsProvisional":
        standings_provisional,

    "standingsBaseUpdatedThrough":
        latest_openfoot_date,

    "teamStats":
        team_stats
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
print()

print(
    "Equipos:",
    len(teams)
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

print()
print("H2H:")

for match in all_current_matches:
    h2h = (
        match
        .get("headToHead", {})
        .get("meetings", [])
    )

    print(
        f"{match['home']} - "
        f"{match['away']}: "
        f"{len(h2h)} anteriores"
    )