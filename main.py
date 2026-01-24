import streamlit as st
import requests
import pandas as pd
from datetime import datetime
from nba_api.live.nba.endpoints import scoreboard, boxscore, playbyplay
from nba_api.stats.endpoints import leaguedashteamstats
from streamlit_autorefresh import st_autorefresh

# ---------------- PAGE CONFIG ----------------
st.set_page_config(page_title="NBA Live Totals Dasboard", layout="wide")

st.markdown("""
<style>
.block-container { padding-top: 0.6rem; max-width: 100%; }
p, span, div { font-size: 0.72rem !important; line-height: 1.05; }
.stMarkdown p { margin-bottom: 0.15rem; }
.stCaption { font-size: 0.65rem !important; }
hr { margin: 0.35rem 0; }
.red-delta { color: #ff4b4b !important; font-weight: bold; }</style>
""", unsafe_allow_html=True)


# ---------------- DATA UTILITIES ----------------
@st.cache_data(ttl=3600)
def get_ou_trends():
    df = pd.read_html("https://www.teamrankings.com/nba/trends/ou_trends/")[0]
    name_map = {
        'Atlanta': 'ATL', 'Boston': 'BOS', 'Brooklyn': 'BKN', 'Charlotte': 'CHA', 'Chicago': 'CHI',
        'Cleveland': 'CLE', 'Dallas': 'DAL', 'Denver': 'DEN', 'Detroit': 'DET', 'Golden State': 'GSW',
        'Houston': 'HOU', 'Indiana': 'IND', 'LA Clippers': 'LAC', 'LA Lakers': 'LAL', 'Memphis': 'MEM',
        'Miami': 'MIA', 'Milwaukee': 'MIL', 'Minnesota': 'MIN', 'New Orleans': 'NOP', 'New York': 'NYK',
        'Okla City': 'OKC', 'Orlando': 'ORL', 'Philadelphia': 'PHI', 'Phoenix': 'PHX', 'Portland': 'POR',
        'Sacramento': 'SAC', 'San Antonio': 'SAS', 'Toronto': 'TOR', 'Utah': 'UTA', 'Washington': 'WAS'
    }
    df['Tri'] = df['Team'].map(name_map)
    return df.set_index('Tri')['Over Record'].to_dict()


@st.cache_data(ttl=3600)
def get_season_stats():
    today = datetime.now().strftime("%m/%d/%Y")

    off = leaguedashteamstats.LeagueDashTeamStats(
        season="2025-26", per_mode_detailed="PerGame",
        season_type_all_star="Regular Season",
        date_to_nullable=today
    ).get_data_frames()[0]

    defn = leaguedashteamstats.LeagueDashTeamStats(
        season="2025-26", measure_type_detailed_defense="Opponent",
        per_mode_detailed="PerGame",
        season_type_all_star="Regular Season",
        date_to_nullable=today
    ).get_data_frames()[0]

    return {
        r.TEAM_ID: {
            "off_ppg": r.PTS,
            "off_fg": r.FG_PCT,
            "off_3p": r.FG3_PCT,
            "def_ppg": defn[defn.TEAM_ID == r.TEAM_ID].iloc[0].OPP_PTS,
            "def_fg": defn[defn.TEAM_ID == r.TEAM_ID].iloc[0].OPP_FG_PCT,
            "def_3p": defn[defn.TEAM_ID == r.TEAM_ID].iloc[0].OPP_FG3_PCT,
        }
        for _, r in off.iterrows()
    }


@st.cache_data(ttl=0)
def get_bovada_closing_totals(api_key):
    resp = requests.get(
        "https://api.sportsgameodds.com/v2/events",
        params={"leagueID": "NBA", "oddsAvailable": "true", "apiKey": api_key},
        timeout=15
    )
    events = resp.json()["data"]
    totals = {}

    for g in events:
        t = g.get("teams", {})
        home = t.get("home", {}).get("names", {}).get("short")
        away = t.get("away", {}).get("names", {}).get("short")
        if not home or not away:
            continue

        for oid, odd in g.get("odds", {}).items():
            if oid.startswith("points-all-game-ou-over"):
                book = odd.get("byBookmaker", {}).get("bovada", {})
                val = book.get("closeOverUnder") or book.get("overUnder")
                if val:
                    totals[(away, home)] = float(val)
                break
    return totals


def fetch_kalshi_total(a, h):
    today = datetime.now().strftime("%y%b%d").upper()
    ticker = f"KXNBATOTAL-{today}{a}{h}"
    try:
        r = requests.get(
            "https://api.elections.kalshi.com/trade-api/v2/markets",
            params={"event_ticker": ticker, "status": "open"},
            timeout=5
        )
        mkts = r.json().get("markets", [])
        if mkts:
            main = min(mkts, key=lambda x: abs((x.get("yes_bid") or 0) - 50))
            return float(main["ticker"].split("-")[-1])
    except:
        pass
    return None


def get_quarter_fouls(game_id):
    try:
        actions = playbyplay.PlayByPlay(game_id).get_dict()["game"]["actions"]
        df = pd.DataFrame(actions)
        q = df["period"].max()
        fouls = df[
            (df.period == q) &
            (df.actionType == "foul") &
            (~df.subType.str.contains("offensive|technical|double", na=False))
            ]
        return fouls.groupby("teamTricode").size().to_dict(), q
    except:
        return {}, None


# ---------------- DISPLAY ----------------
def is_live(status):
    s = status.lower()
    return (
            any(k in s for k in ["q1", "q2", "q3", "q4", "half", "end", ":"]) and
            not any(k in s for k in ["pm", "et"])
    )


st.title("🏀 NBA Live Totals Dashboard")

with st.sidebar:
    live_only = st.toggle("Only Live Games", False)

    # REFRESH TOGGLE
    refresh_mode = st.radio("Refresh Mode", ["Manual", "Automatic (30s)"])
    if refresh_mode == "Automatic (30s)":
        st_autorefresh(interval=30000, key="nbarefresh")
    else:
        # Added Manual Refresh Button
        if st.button("🔄 Refresh Stats Now"):
            st.rerun()

    if st.button("Clear Cache"):
        st.cache_data.clear()
        st.rerun()

SEASON = get_season_stats()
TRENDS = get_ou_trends()
BOVADA = get_bovada_closing_totals("ef3d4be08d5abebe96b4d65fc55e96d0")

games = scoreboard.ScoreBoard().get_dict()["scoreboard"]["games"]
if live_only:
    games = [g for g in games if is_live(g["gameStatusText"])]

cols = st.columns(2, gap="small")

for i, g in enumerate(games):
    col = cols[i % 2]

    with col:
        with st.container(border=True):
            a, h = g["awayTeam"], g["homeTeam"]
            a_tri, h_tri = a["teamTricode"], h["teamTricode"]

            st.markdown(
                f"**{a_tri} {a['score']} @ {h_tri} {h['score']} — {g['gameStatusText']}**"
            )

            c1, c2, c3 = st.columns([1.2, 1.1, 0.9])

        # LEFT
        with c1:
            sa, sh = SEASON.get(a["teamId"]), SEASON.get(h["teamId"])
            if sa and sh:
                st.write(f"Season Averages")
                st.write(f"\n{a_tri} O vs {h_tri} D")
                st.write(f"🟢 {a_tri}: {sa['off_ppg']:.1f} | {sa['off_fg']:.0%} | {sa['off_3p']:.0%}")
                st.write(f"🔴 {h_tri}: {sh['def_ppg']:.1f} | {sh['def_fg']:.0%} | {sh['def_3p']:.0%}")
                st.divider()
                st.write(f"{h_tri} O vs {a_tri} D")
                st.write(f"🟢 {h_tri}: {sh['off_ppg']:.1f} | {sh['off_fg']:.0%} | {sh['off_3p']:.0%}")
                st.write(f"🔴 {a_tri}: {sa['def_ppg']:.1f} | {sa['def_fg']:.0%} | {sa['def_3p']:.0%}")

        # MIDDLE
        with c2:
            try:
                box = boxscore.BoxScore(g["gameId"]).get_dict()["game"]
                al, hl = box["awayTeam"]["statistics"], box["homeTeam"]["statistics"]
                st.write("**Live Stats**")
                st.write(f"{a_tri}: {al['fieldGoalsPercentage']:.0%} FG | {al['threePointersPercentage']:.0%} 3P")
                st.write(f"{h_tri}: {hl['fieldGoalsPercentage']:.0%} FG | {hl['threePointersPercentage']:.0%} 3P")

                fouls, q = get_quarter_fouls(g["gameId"])
                st.caption(f"Q{q} Fouls — {a_tri}: {fouls.get(a_tri, 0)} | {h_tri}: {fouls.get(h_tri, 0)}")
            except:
                st.caption("Updating…")

            st.divider()
            st.write("**O/U Trends**")
            st.caption(f"{a_tri}: {TRENDS.get(a_tri, '--')}")
            st.caption(f"{h_tri}: {TRENDS.get(h_tri, '--')}")

        # RIGHT
        with c3:
            tip = BOVADA.get((a_tri, h_tri))
            live = fetch_kalshi_total(a_tri, h_tri)
            if tip:
                st.write("**Tip-Off Total**")
                st.write(f"{tip}")
            if live:
                st.write("**Live Total**")
                st.write(f"{live}")
            if tip and live:
                diff = live - tip
                pct = (abs(diff) / tip) * 100

                # Highlight in red if the delta is 10% or more
                color_class = "red-delta" if pct >= 10 else ""
                st.markdown(f'<p class="stCaption {color_class}">Δ Live vs Tip: {diff:+.1f} | {pct:.1f}%</p>',
                            unsafe_allow_html=True)