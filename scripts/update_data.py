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

    "Celta B": "Celta B",
    "Celta Fortuna": "Celta B"
}


def normalize_team_name(name):
    if not name:
        return ""

    return TEAM_NAMES.get(name, name)


def slugify(value):
    value = unicodedata.normalize(
        "NFKD",
        value
    )

    value = "".join(
        char
        for char in value
        if not unicodedata.combining(char)
    )

    value = value.lower()

    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value
    )

    return value.strip("-")


# --------------------------------------------------
# HELPERS DE FECHAS
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

    madrid_datetime = (
        utc_datetime
        .astimezone(MADRID_TZ)
    )

    return madrid_datetime.strftime(
        "%H:%M"
    )


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

    value = (
        datetime
        .fromisoformat(date_string)
        .date()
    )

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
    Jornada aproximada de viernes a lunes.
    """

    weekday = today.weekday()

    # Lunes
    if weekday == 0:
        friday = (
            today
            - timedelta(days=3)
        )

    # Martes, miércoles y jueves
    elif weekday in [1, 2, 3]:
        friday = (
            today
            + timedelta(
                days=(4 - weekday)
            )
        )

    # Viernes, sábado y domingo
    else:
        friday = (
            today
            - timedelta(
                days=(weekday - 4)
            )
        )

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

        data = response.json()

        all_matches.extend(
            data.get("data", [])
        )

        pagination = (
            data
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
# ESTADÍSTICAS POR EQUIPO
# --------------------------------------------------

def calculate_team_stats(
    team_id,
    matches
):
    team_matches = []

    for match in matches:
        if (
            match.get("status")
            != "finished"
        ):
            continue

        home = match["homeTeam"]
        away = match["awayTeam"]

        if team_id not in [
            home["id"],
            away["id"]
        ]:
            continue

        score = (
            match.get("score")
            or {}
        )

        home_score = score.get("home")
        away_score = score.get("away")

        if (
            home_score is None
            or away_score is None
        ):
            continue

        is_home = (
            home["id"]
            == team_id
        )

        opponent = (
            away
            if is_home
            else home
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

        if goals_for > goals_against:
            result = "W"

        elif goals_for == goals_against:
            result = "D"

        else:
            result = "L"

        total_goals = (
            goals_for
            + goals_against
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
                normalize_team_name(
                    opponent.get("name")
                ),

            "btts":
                goals_for > 0
                and goals_against > 0,

            "cleanSheet":
                goals_against == 0,

            "failedToScore":
                goals_for == 0,

            "over15":
                total_goals > 1,

            "over25":
                total_goals > 2,

            "over35":
                total_goals > 3
        })

    team_matches.sort(
        key=lambda item:
            item["date"] or ""
    )

    if not team_matches:
        return None


    # --------------------------------------------------
    # ESTADÍSTICAS DE UN PERIODO
    # --------------------------------------------------

    def calculate_period_stats(
        selected_matches
    ):
        if not selected_matches:
            return None

        games = len(
            selected_matches
        )

        wins = sum(
            1
            for match
            in selected_matches
            if match["result"] == "W"
        )

        draws = sum(
            1
            for match
            in selected_matches
            if match["result"] == "D"
        )

        losses = sum(
            1
            for match
            in selected_matches
            if match["result"] == "L"
        )

        goals_for = sum(
            match["goalsFor"]
            for match
            in selected_matches
        )

        goals_against = sum(
            match["goalsAgainst"]
            for match
            in selected_matches
        )

        total_goals = (
            goals_for
            + goals_against
        )

        btts = sum(
            1
            for match
            in selected_matches
            if match["btts"]
        )

        clean_sheets = sum(
            1
            for match
            in selected_matches
            if match["cleanSheet"]
        )

        failed_to_score = sum(
            1
            for match
            in selected_matches
            if match["failedToScore"]
        )

        over15 = sum(
            1
            for match
            in selected_matches
            if match["over15"]
        )

        over25 = sum(
            1
            for match
            in selected_matches
            if match["over25"]
        )

        over35 = sum(
            1
            for match
            in selected_matches
            if match["over35"]
        )

        points = (
            wins * 3
            + draws
        )

        return {
            "played":
                games,

            "wins":
                wins,

            "draws":
                draws,

            "losses":
                losses,

            "points":
                points,

            "pointsPerGame":
                round(
                    points / games,
                    2
                ),

            "goalsFor":
                goals_for,

            "goalsAgainst":
                goals_against,

            "goalDifference":
                goals_for
                - goals_against,

            "avgGoalsFor":
                round(
                    goals_for / games,
                    2
                ),

            "avgGoalsAgainst":
                round(
                    goals_against / games,
                    2
                ),

            "avgTotalGoals":
                round(
                    total_goals / games,
                    2
                ),

            "btts":
                btts,

            "bttsPercentage":
                round(
                    btts
                    / games
                    * 100,
                    1
                ),

            "cleanSheets":
                clean_sheets,

            "cleanSheetPercentage":
                round(
                    clean_sheets
                    / games
                    * 100,
                    1
                ),

            "failedToScore":
                failed_to_score,

            "failedToScorePercentage":
                round(
                    failed_to_score
                    / games
                    * 100,
                    1
                ),

            "over15":
                over15,

            "over15Percentage":
                round(
                    over15
                    / games
                    * 100,
                    1
                ),

            "over25":
                over25,

            "over25Percentage":
                round(
                    over25
                    / games
                    * 100,
                    1
                ),

            "over35":
                over35,

            "over35Percentage":
                round(
                    over35
                    / games
                    * 100,
                    1
                ),

            "winPercentage":
                round(
                    wins
                    / games
                    * 100,
                    1
                ),

            "unbeatenPercentage":
                round(
                    (
                        wins
                        + draws
                    )
                    / games
                    * 100,
                    1
                )
        }


    # --------------------------------------------------
    # HELPERS DE RACHAS
    # --------------------------------------------------

    def calculate_streak(
        condition,
        selected_matches=None
    ):
        source = (
            selected_matches
            if selected_matches is not None
            else team_matches
        )

        streak = 0

        for match in reversed(source):
            if not condition(match):
                break

            streak += 1

        return streak


    # --------------------------------------------------
    # BLOQUES
    # --------------------------------------------------

    last_five = (
        team_matches[-5:]
    )

    last_ten = (
        team_matches[-10:]
    )

    home_matches = [
        match
        for match in team_matches
        if match["isHome"]
    ]

    away_matches = [
        match
        for match in team_matches
        if not match["isHome"]
    ]


    # --------------------------------------------------
    # RACHAS GENERALES
    # --------------------------------------------------

    win_streak = (
        calculate_streak(
            lambda match:
                match["result"]
                == "W"
        )
    )

    unbeaten_streak = (
        calculate_streak(
            lambda match:
                match["result"]
                != "L"
        )
    )

    losing_streak = (
        calculate_streak(
            lambda match:
                match["result"]
                == "L"
        )
    )

    winless_streak = (
        calculate_streak(
            lambda match:
                match["result"]
                != "W"
        )
    )

    scoring_streak = (
        calculate_streak(
            lambda match:
                match["goalsFor"]
                > 0
        )
    )

    conceding_streak = (
        calculate_streak(
            lambda match:
                match["goalsAgainst"]
                > 0
        )
    )

    clean_sheet_streak = (
        calculate_streak(
            lambda match:
                match["goalsAgainst"]
                == 0
        )
    )

    no_score_streak = (
        calculate_streak(
            lambda match:
                match["goalsFor"]
                == 0
        )
    )


    # --------------------------------------------------
    # RACHAS LOCAL
    # --------------------------------------------------

    home_win_streak = (
        calculate_streak(
            lambda match:
                match["result"]
                == "W",
            home_matches
        )
    )

    home_unbeaten_streak = (
        calculate_streak(
            lambda match:
                match["result"]
                != "L",
            home_matches
        )
    )


    # --------------------------------------------------
    # RACHAS VISITANTE
    # --------------------------------------------------

    away_win_streak = (
        calculate_streak(
            lambda match:
                match["result"]
                == "W",
            away_matches
        )
    )

    away_unbeaten_streak = (
        calculate_streak(
            lambda match:
                match["result"]
                != "L",
            away_matches
        )
    )


    # --------------------------------------------------
    # RESULTADO FINAL
    # --------------------------------------------------

    return {
        "form": [
            match["result"]
            for match
            in last_five
        ],

        "form10": [
            match["result"]
            for match
            in last_ten
        ],

        "matchesAnalysed":
            len(team_matches),

        "winStreak":
            win_streak,

        "unbeatenStreak":
            unbeaten_streak,

        "losingStreak":
            losing_streak,

        "winlessStreak":
            winless_streak,

        "scoringStreak":
            scoring_streak,

        "concedingStreak":
            conceding_streak,

        "cleanSheetStreak":
            clean_sheet_streak,

        "noScoreStreak":
            no_score_streak,

        "homeWinStreak":
            home_win_streak,

        "homeUnbeatenStreak":
            home_unbeaten_streak,

        "awayWinStreak":
            away_win_streak,

        "awayUnbeatenStreak":
            away_unbeaten_streak,

        "last5":
            calculate_period_stats(
                last_five
            ),

        "last10":
            calculate_period_stats(
                last_ten
            ),

        "home":
            calculate_period_stats(
                home_matches[-5:]
            ),

        "away":
            calculate_period_stats(
                away_matches[-5:]
            ),

        "recentMatches":
            team_matches[-5:]
    }


# --------------------------------------------------
# THESPORTSDB
# --------------------------------------------------

def get_events_for_date(day):
    response = requests.get(
        f"{SPORTSDB_BASE_URL}/eventsday.php",
        params={
            "d":
                day.isoformat(),
            "l":
                SPORTSDB_LEAGUE_ID
        },
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    return (
        data.get("events")
        or []
    )


def format_sportsdb_event(event):
    event_date = event.get("dateEvent")
    event_time = event.get("strTime")

    home_score = event.get("intHomeScore")
    away_score = event.get("intAwayScore")

    if home_score not in [None, ""]:
        try:
            home_score = int(home_score)
        except (ValueError, TypeError):
            pass

    if away_score not in [None, ""]:
        try:
            away_score = int(away_score)
        except (ValueError, TypeError):
            pass

    home_name = normalize_team_name(
        event.get("strHomeTeam")
    )

    away_name = normalize_team_name(
        event.get("strAwayTeam")
    )

    home_slug = slugify(home_name)
    away_slug = slugify(away_name)

    match_slug = None

    if event_date and home_slug and away_slug:
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
    event_date = (
        event.get("dateEvent")
    )

    event_time = (
        event.get("strTime")
    )

    home_score = (
        event.get("intHomeScore")
    )

    away_score = (
        event.get("intAwayScore")
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
            normalize_team_name(
                event.get(
                    "strHomeTeam"
                )
            ),

        "away":
            normalize_team_name(
                event.get(
                    "strAwayTeam"
                )
            ),

        "homeScore":
            home_score,

        "awayScore":
            away_score
    }


# --------------------------------------------------
# CLASIFICACIÓN
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

standings_data = (
    standings_response.json()
)

standings = []
teams = []


for row in (
    standings_data["data"]["table"]
):
    team = row["team"]

    normalized_name = (
        normalize_team_name(
            team["name"]
        )
    )

    team_slug = slugify(
        normalized_name
    )

    teams.append({
        "id":
            team["id"],

        "name":
            normalized_name,

        "slug":
            team_slug
    })

    standings.append({
        "pos":
            row["position"],

        "team":
            normalized_name,

        "slug":
            team_slug,

        "played":
            row["total"]["played"],

        "points":
            row["total"]["points"],

        "won":
            row["total"]["won"],

        "drawn":
            row["total"]["drawn"],

        "lost":
            row["total"]["lost"],

        "goalsFor":
            row["total"]["goalsFor"],

        "goalsAgainst":
            row["total"]["goalsAgainst"],

        "goalDifference":
            row["total"][
                "goalDifference"
            ],

        "form":
            row["form"]
    })


# --------------------------------------------------
# HISTÓRICO OPENFOOT
# --------------------------------------------------

all_matches = (
    get_all_openfoot_matches()
)

finished_matches = [
    match
    for match
    in all_matches
    if (
        match.get("status")
        == "finished"
    )
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
    stats = (
        calculate_team_stats(
            team["id"],
            finished_matches
        )
    )

    if stats:
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
# TENDENCIAS DESTACADAS
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

    last5 = stats["last5"]


    # Racha de victorias

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

            "text": (
                f"{stats['winStreak']} "
                f"victorias consecutivas"
            )
        })


    # Sin perder

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
                "📈",

            "title":
                team_name,

            "slug":
                team_slug,

            "text": (
                f"{stats['unbeatenStreak']} "
                f"partidos consecutivos "
                f"sin perder"
            )
        })


    # Marcando

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

            "text": (
                f"Ha marcado en sus últimos "
                f"{stats['scoringStreak']} "
                f"partidos"
            )
        })


    # Goles últimos 5

    if (
        last5
        and last5["avgGoalsFor"]
        >= 1.8
    ):
        trend_groups[
            "goals"
        ].append({
            "value":
                last5[
                    "avgGoalsFor"
                ],

            "icon":
                "🎯",

            "title":
                team_name,

            "slug":
                team_slug,

            "text": (
                f"Promedia "
                f"{last5['avgGoalsFor']} "
                f"goles en sus últimos "
                f"5 partidos"
            )
        })


    # Ambos marcan

    if (
        last5
        and last5["btts"]
        >= 4
    ):
        trend_groups[
            "btts"
        ].append({
            "value":
                last5["btts"],

            "icon":
                "🥅",

            "title":
                team_name,

            "slug":
                team_slug,

            "text": (
                f"Ambos equipos marcaron "
                f"en {last5['btts']} "
                f"de sus últimos 5 partidos"
            )
        })


    # Porterías a cero

    if (
        last5
        and last5["cleanSheets"]
        >= 3
    ):
        trend_groups[
            "cleanSheets"
        ].append({
            "value":
                last5[
                    "cleanSheets"
                ],

            "icon":
                "🧱",

            "title":
                team_name,

            "slug":
                team_slug,

            "text": (
                f"Ha dejado la portería "
                f"a cero en "
                f"{last5['cleanSheets']} "
                f"de sus últimos 5 partidos"
            )
        })


    # Local

    if (
        stats["homeWinStreak"]
        >= 3
    ):
        trend_groups[
            "home"
        ].append({
            "value":
                stats[
                    "homeWinStreak"
                ],

            "icon":
                "🏠",

            "title":
                team_name,

            "slug":
                team_slug,

            "text": (
                f"{stats['homeWinStreak']} "
                f"victorias consecutivas "
                f"como local"
            )
        })


    # Visitante

    if (
        stats["awayWinStreak"]
        >= 3
    ):
        trend_groups[
            "away"
        ].append({
            "value":
                stats[
                    "awayWinStreak"
                ],

            "icon":
                "✈️",

            "title":
                team_name,

            "slug":
                team_slug,

            "text": (
                f"{stats['awayWinStreak']} "
                f"victorias consecutivas "
                f"como visitante"
            )
        })


# --------------------------------------------------
# SELECCIÓN DE TOP TENDENCIAS
# --------------------------------------------------

trends = []

used_teams = set()

category_order = [
    "wins",
    "unbeaten",
    "scoring",
    "cleanSheets",
    "goals",
    "btts",
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
            candidate["title"]
            not in used_teams
        ):
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
                candidate["title"]
            )

            break

    if len(trends) >= 6:
        break


# --------------------------------------------------
# PARTIDOS DE HOY
# --------------------------------------------------

now_madrid = datetime.now(
    MADRID_TZ
)

today = now_madrid.date()

today_events = (
    get_events_for_date(
        today
    )
)

today_matches = [
    format_sportsdb_event(
        event
    )
    for event
    in today_events
]


# --------------------------------------------------
# ESTA JORNADA
# --------------------------------------------------

matchday_dates = (
    get_matchday_dates(
        today
    )
)

journey_events = []
seen_events = set()


for matchday_date in (
    matchday_dates
):
    events = (
        get_events_for_date(
            matchday_date
        )
    )

    for event in events:
        event_id = (
            event.get("idEvent")
        )

        if (
            event_id
            and event_id
            in seen_events
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

        # Los de hoy ya están arriba

        if (
            formatted_event["date"]
            == today.isoformat()
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
print("EJEMPLO ESTADÍSTICAS:")

for team_id, stats in team_stats.items():
    print()
    print(
        stats["name"]
    )

    print(
        "Slug:",
        stats["slug"]
    )

    print(
        "Forma:",
        stats["form"]
    )

    print(
        "Racha victorias:",
        stats["winStreak"]
    )

    print(
        "Sin perder:",
        stats["unbeatenStreak"]
    )

    print(
        "Marcando:",
        stats["scoringStreak"]
    )

    print(
        "Últimos 5:",
        stats["last5"]
    )

    break