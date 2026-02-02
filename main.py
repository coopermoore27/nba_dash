import streamlit as st
import requests
import pandas as pd
from datetime import datetime, timedelta, timezone
from nba_api.live.nba.endpoints import scoreboard, boxscore, playbyplay
from nba_api.stats.endpoints import leaguedashteamstats
from streamlit_autorefresh import st_autorefresh

# ---------------- PAGE CONFIG ----------------
st.set_page_config(page_title="NBA Live Totals Dashboard", layout="wide")

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
    off = leaguedashteamstats.LeagueDashTeamStats(season="2025-26", per_mode_detailed="PerGame").get_data_frames()[0]
    defn = leaguedashteamstats.LeagueDashTeamStats(season="2025-26", measure_type_detailed_defense="Opponent",
                                                   per_mode_detailed="PerGame").get_data_frames()[0]
    adv = leaguedashteamstats.LeagueDashTeamStats(season="2025-26",
                                                  measure_type_detailed_defense="Advanced").get_data_frames()[0]
    return {
        r.TEAM_ID: {
            "off_ppg": r.PTS, "off_fg": r.FG_PCT, "off_3p": r.FG3_PCT,
            "def_ppg": defn[defn.TEAM_ID == r.TEAM_ID].iloc[0].OPP_PTS,
            "def_fg": defn[defn.TEAM_ID == r.TEAM_ID].iloc[0].OPP_FG_PCT,
            "def_3p": defn[defn.TEAM_ID == r.TEAM_ID].iloc[0].OPP_FG3_PCT,
            "off_rtg": adv[adv.TEAM_ID == r.TEAM_ID].iloc[0].OFF_RATING,
            "def_rtg": adv[adv.TEAM_ID == r.TEAM_ID].iloc[0].DEF_RATING,
            "pace": adv[adv.TEAM_ID == r.TEAM_ID].iloc[0].PACE,
        }
        for _, r in off.iterrows()
    }


@st.cache_data(ttl=86400)
def get_pregame_total(away_full, home_full, tip_off_iso):
    """Robust fetch: tries multiple timestamps and name variations."""
    api_key = "b4fed2e35cfad747e07268fbb1377c2d"
    tip_dt = datetime.fromisoformat(tip_off_iso.replace('Z', '+00:00'))

    # Handle "LA" vs "Los Angeles" variations
    away_variations = [away_full, away_full.replace("LA ", "Los Angeles "), away_full.replace("Los Angeles ", "LA ")]
    home_variations = [home_full, home_full.replace("LA ", "Los Angeles "), home_full.replace("Los Angeles ", "LA ")]

    url = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba/odds"

    # Try snapshots at T-10, T-30, and T-60 to find the best closing line
    for mins_back in [10, 30, 60]:
        target_iso = (tip_dt - timedelta(minutes=mins_back)).strftime('%Y-%m-%dT%H:%M:%SZ')
        params = {"apiKey": api_key, "regions": "eu,us", "markets": "totals", "date": target_iso}

        try:
            resp = requests.get(url, params=params, timeout=5).json()
            games_data = resp.get('data', [])

            # Search for any of our name variations
            match = None
            for g in games_data:
                if g['away_team'] in away_variations and g['home_team'] in home_variations:
                    match = g
                    break

            if match:
                bookies = {b['key']: b for b in match.get('bookmakers', [])}
                # Priority: Pinnacle -> FanDuel -> DraftKings
                for key in ['pinnacle', 'fanduel', 'draftkings', 'betmgm']:
                    if key in bookies:
                        return float(bookies[key]['markets'][0]['outcomes'][0]['point'])
        except:
            continue
    return None


def fetch_kalshi_total(a, h):
    now = datetime.now(timezone.utc)
    today_str = now.strftime("%y%b%d").upper()

    def get_val(date_str):
        ticker = f"KXNBATOTAL-{date_str}{a}{h}"
        try:
            r = requests.get("https://api.elections.kalshi.com/trade-api/v2/markets",
                             params={"event_ticker": ticker, "status": "open"}, timeout=5)
            mkts = r.json().get("markets", [])
            if mkts:
                main = min(mkts, key=lambda x: abs((x.get("yes_bid") or 0) - 50))
                return float(main["ticker"].split("-")[-1])
        except:
            return None

    val = get_val(today_str)
    if val is None:
        yesterday_str = (now - timedelta(days=1)).strftime("%y%b%d").upper()
        val = get_val(yesterday_str)
    return val


def get_quarter_fouls(game_id):
    try:
        actions = playbyplay.PlayByPlay(game_id).get_dict()["game"]["actions"]
        df = pd.DataFrame(actions)
        q = df["period"].max()
        fouls = df[(df.period == q) & (df.actionType == "foul") & (
            ~df.subType.str.contains("offensive|technical|double", na=False))]
        return fouls.groupby("teamTricode").size().to_dict(), q
    except:
        return {}, None


def calculate_elapsed_minutes(status_text, period):
    try:
        if "Half" in status_text: return 24.0
        parts = status_text.split(" ")
        if len(parts) < 2 or ":" not in parts[1]: return float((period - 1) * 12)
        mins, secs = map(float, parts[1].split(":")[0:2])
        return max(((period - 1) * 12) + (12.0 - (mins + secs / 60)), 0.1)
    except:
        return max(float((period - 1) * 12), 0.1)


# ---------------- DISPLAY ----------------
st.title("🏀 NBA Live Totals Dashboard")

with st.sidebar:
    live_only = st.toggle("Only Live Games", False)
    refresh_mode = st.radio("Refresh Mode", ["Manual", "Automatic (30s)"])
    if refresh_mode == "Automatic (30s)": st_autorefresh(interval=30000, key="nbarefresh")
    if st.button("🔄 Refresh Stats Now"): st.rerun()
    if st.button("Clear Cache"):
        st.cache_data.clear()
        st.rerun()

SEASON, TRENDS = get_season_stats(), get_ou_trends()
games = scoreboard.ScoreBoard().get_dict()["scoreboard"]["games"]

# Filter for games in progress (Halftime is fine, Final is removed)
if live_only:
    games = [g for g in games if g["gameStatus"] == 2]

cols = st.columns(2, gap="small")

for i, g in enumerate(games):
    col = cols[i % 2]
    with col:
        with st.container(border=True):
            a, h = g["awayTeam"], g["homeTeam"]
            a_tri, h_tri = a["teamTricode"], h["teamTricode"]
            # Formatting full names for the Odds API
            a_full, h_full = f"{a['teamCity']} {a['teamName']}", f"{h['teamCity']} {h['teamName']}"
            st.markdown(f"**{a_tri} {a['score']} @ {h_tri} {h['score']} — {g['gameStatusText']}**")
            c1, c2, c3 = st.columns([1.2, 1.1, 0.9])

        with c1:
            sa, sh = SEASON.get(a["teamId"]), SEASON.get(h["teamId"])
            if sa and sh:
                st.write("Average ppg, fg%, 3pt%, pp100")
                st.caption(
                    f"{a_tri} O: {sa['off_ppg']:.1f} | {sa['off_fg']:.0%} | {sa['off_3p']:.0%} | Ortg: {sa['off_rtg']:.1f}")
                st.caption(
                    f"{h_tri} D: {sh['def_ppg']:.1f} | {sh['def_fg']:.0%} | {sh['def_3p']:.0%} | Drtg: {sh['def_rtg']:.1f}")
                st.caption(f"Pace: {sa['pace']:.1f} / {sh['pace']:.1f}")
                st.markdown("---")
                st.caption(
                    f"{h_tri} O: {sh['off_ppg']:.1f} | {sh['off_fg']:.0%} | {sh['off_3p']:.0%} | Ortg: {sh['off_rtg']:.1f}")
                st.caption(
                    f"{a_tri} D: {sa['def_ppg']:.1f} | {sa['def_fg']:.0%} | {sa['def_3p']:.0%} | Drtg: {sa['def_rtg']:.1f}")
                st.caption(f"Pace: {sh['pace']:.1f} / {sa['pace']:.1f}")

        with c2:
            try:
                box_data = boxscore.BoxScore(g["gameId"]).get_dict()["game"]
                al, hl = box_data["awayTeam"]["statistics"], box_data["homeTeam"]["statistics"]
                a_poss = al['fieldGoalsAttempted'] + 0.44 * al['freeThrowsAttempted'] - al['reboundsOffensive'] + al[
                    'turnovers']
                h_poss = hl['fieldGoalsAttempted'] + 0.44 * hl['freeThrowsAttempted'] - hl['reboundsOffensive'] + hl[
                    'turnovers']
                avg_p = (a_poss + h_poss) / 2

                a_live_ortg = (al['points'] / avg_p * 100) if avg_p > 0 else 0
                h_live_ortg = (hl['points'] / avg_p * 100) if avg_p > 0 else 0

                elapsed_mins = calculate_elapsed_minutes(g["gameStatusText"], g["period"])
                live_pace = (avg_p / elapsed_mins) * 48

                st.write("**Live Stats**")
                st.write(
                    f"{a_tri}: {al['fieldGoalsPercentage']:.0%} FG | {al['threePointersPercentage']:.0%} 3P | Ortg: {a_live_ortg:.1f}")
                st.write(
                    f"{h_tri}: {hl['fieldGoalsPercentage']:.0%} FG | {hl['threePointersPercentage']:.0%} 3P | Ortg: {h_live_ortg:.1f}")

                fouls, q = get_quarter_fouls(g["gameId"])
                st.caption(f"Q{q} Fouls: {a_tri}:{fouls.get(a_tri, 0)} | {h_tri}:{fouls.get(h_tri, 0)}")
                st.write(f"**Live Pace: {live_pace:.1f}**")
                st.caption(f"Total Possessions: {avg_p:.1f}")
            except:
                st.caption("Updating…")

            st.divider()
            st.write("**O/U Trends**")
            st.caption(f"{a_tri}: {TRENDS.get(a_tri, '--')}")
            st.caption(f"{h_tri}: {TRENDS.get(h_tri, '--')}")

        with c3:
            tip = get_pregame_total(a_full, h_full, g["gameTimeUTC"])
            live = fetch_kalshi_total(a_tri, h_tri)
            if tip: st.write(f"**Pregame:** {tip}")
            if live: st.write(f"**Live:** {live}")
            if tip and live:
                diff = live - tip
                pct = (abs(diff) / tip) * 100
                color = "red-delta" if pct >= 10 else ""
                st.markdown(f'<p class="stCaption {color}">Δ: {diff:+.1f} | {pct:.1f}%</p>', unsafe_allow_html=True)