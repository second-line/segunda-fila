import os
import requests
import truststore

from dotenv import load_dotenv

truststore.inject_into_ssl()
load_dotenv()

API_KEY = os.getenv("OPENFOOT_API_KEY")

BASE_URL = "https://openfootapi.com/v1"

headers = {
    "Accept": "application/json",
    "Authorization": f"Bearer {API_KEY}"
}

TEAM = "team_castellon_es"

response = requests.get(
    f"{BASE_URL}/matches",
    headers=headers,
    params={
        "team": TEAM,
        "season": "2026/27",
        "status": "finished"
    }
)

response.raise_for_status()

data = response.json()

matches = data.get("data", [])

print("Partidos encontrados:", len(matches))

for match in matches:
    print(
        match.get("kickoffAt"),
        match["homeTeam"]["name"],
        match.get("score"),
        match["awayTeam"]["name"]
    )
