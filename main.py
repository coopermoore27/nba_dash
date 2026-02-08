import streamlit as st
import requests
import pandas as pd
import numpy as np
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
.red-delta { color: #ff4b4b !important; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ---------------- HARDCODED MODEL DATA ----------------
CUM_PCTS = {
    1: 1.583985831, 2: 3.62237439, 3: 5.753438941, 4: 7.913650827, 5: 10.07985436,
    6: 12.18988467, 7: 14.30777824, 8: 16.45367652, 9: 18.59955432, 10: 20.68804255,
    11: 22.83180301, 12: 25.20131299, 13: 26.82165824, 14: 28.8379846, 15: 30.86867371,
    16: 32.88459871, 17: 34.94449249, 18: 36.98122239, 19: 39.09733035, 20: 41.24897455,
    21: 43.44727005, 22: 45.63250924, 23: 47.91044491, 24: 50.41001826, 25: 52.01358036,
    26: 54.02260452, 27: 56.11384899, 28: 58.19321664, 29: 60.28462903, 30: 62.35001071,
    31: 64.43011145, 32: 66.54347955, 33: 68.67916787, 34: 70.75722089, 35: 72.90463858,
    36: 75.26325466, 37: 76.83604352, 38: 78.77399111, 39: 80.72550284, 40: 82.66466678,
    41: 84.60889269, 42: 86.56185012, 43: 88.55379215, 44: 90.55673047, 45: 92.57292987,
    46: 94.60315619, 47: 96.88510131, 48: 100.0
}
CUM_LOOKUP = {k: v / 100.0 for k, v in CUM_PCTS.items()}


# ---------------- DATA UTILITIES ----------------

def get_live_prediction(current_score, elapsed_mins, pregame_total):
    if not pregame_total or elapsed_mins < 0.5:
        return None
    min_key = int(np.floor(elapsed_mins))
    min_key = max(1, min(48, min_key))
    w_m = CUM_LOOKUP.get(min_key, elapsed_mins / 48.0)
    expected_now = pregame_total * w_m
    residual = current_score - expected_now
    slope = (0.0061 * elapsed_mins) + 0.6339
    remaining_expected = pregame_total * (1 - w_m)
    adjustment = residual * (slope - 1)
    return current_score + remaining_expected + adjustment


def calculate_elapsed_minutes(status_text, period):
    try:
        if "Half" in status_text: return 24.0
        if "End" in status_text or "Final" in status_text: return float(period * 12)
        parts = status_text.split(" ")
        time_str = parts[-1]
        if ":" not in time_str: return float((period - 1) * 12)
        mins, secs = map(float, time_str.split(":"))
        return max(((period - 1) * 12) + (12.0 - (mins + secs / 60)), 0.1)
    except:
        return max(float((period - 1) * 12), 0.1)


@st.cache_data(ttl=3600)
def get_ou_trends():
    try:
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
    except:
        return {}


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
    api_key = "b4fed2e35cfad747e07268fbb1377c2d"
    tip_dt = datetime.fromisoformat(tip_off_iso.replace('Z', '+00:00'))
    away_variations = [away_full, away_full.replace("LA ", "Los Angeles "), away_full.replace("Los Angeles ", "LA ")]
    home_variations = [home_full, home_full.replace("LA ", "Los Angeles "), home_full.replace("Los Angeles ", "LA ")]
    url = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba/odds"
    for mins_back in [10, 30, 60]:
        target_iso = (tip_dt - timedelta(minutes=mins_back)).strftime('%Y-%m-%dT%H:%M:%SZ')
        params = {"apiKey": api_key, "regions": "eu,us", "markets": "totals", "date": target_iso}
        try:
            resp = requests.get(url, params=params, timeout=5).json()
            for g in resp.get('data', []):
                if g['away_team'] in away_variations and g['home_team'] in home_variations:
                    bookies = {b['key']: b for b in g.get('bookmakers', [])}
                    for key in ['pinnacle', 'fanduel', 'draftkings', 'betmgm']:
                        if key in bookies: return float(bookies[key]['markets'][0]['outcomes'][0]['point'])
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
    if not val: val = get_val((now - timedelta(days=1)).strftime("%y%b%d").upper())
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


# ---------------- DISPLAY ----------------
st.title("🏀 NBA Live Totals Dashboard")

with st.sidebar:
    live_only = st.toggle("Only Live Games", False)
    refresh_mode = st.radio("Refresh Mode", ["Manual", "Automatic (30s)"])
    if refresh_mode == "Automatic (30s)": st_autorefresh(interval=30000, key="nbarefresh")
    if st.button("🔄 Refresh Stats"): st.rerun()

SEASON, TRENDS = get_season_stats(), get_ou_trends()
games = scoreboard.ScoreBoard().get_dict()["scoreboard"]["games"]
if live_only: games = [g for g in games if g["gameStatus"] == 2]

cols = st.columns(2, gap="small")
for i, g in enumerate(games):
    with cols[i % 2]:
        with st.container(border=True):
            a, h = g["awayTeam"], g["homeTeam"]
            a_tri, h_tri = a["teamTricode"], h["teamTricode"]
            a_full, h_full = f"{a['teamCity']} {a['teamName']}", f"{h['teamCity']} {h['teamName']}"
            elapsed = calculate_elapsed_minutes(g["gameStatusText"], g["period"])
            cur_pts = a['score'] + h['score']

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
                    a_poss = al['fieldGoalsAttempted'] + 0.44 * al['freeThrowsAttempted'] - al['reboundsOffensive'] + \
                             al['turnovers']
                    h_poss = hl['fieldGoalsAttempted'] + 0.44 * hl['freeThrowsAttempted'] - hl['reboundsOffensive'] + \
                             hl['turnovers']
                    avg_p = (a_poss + h_poss) / 2

                    a_live_ortg = (al['points'] / avg_p * 100) if avg_p > 0 else 0
                    h_live_ortg = (hl['points'] / avg_p * 100) if avg_p > 0 else 0
                    live_pace = (avg_p / elapsed) * 48 if elapsed > 0 else 0

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
                st.caption(f"{a_tri}: {TRENDS.get(a_tri, '--')} | {h_tri}: {TRENDS.get(h_tri, '--')}")

            with c3:
                tip = get_pregame_total(a_full, h_full, g["gameTimeUTC"])
                live = fetch_kalshi_total(a_tri, h_tri)
                pred = get_live_prediction(cur_pts, elapsed, tip)

                if tip: st.write(f"**Pregame:** {tip}")
                if live: st.write(f"**Live:** {live}")

                # Delta 1: Pregame vs Live Market
                if tip and live:
                    mkt_diff = live - tip
                    mkt_pct = (abs(mkt_diff) / tip) * 100
                    st.markdown(f'<p class="stCaption">Market Δ: {mkt_diff:+.1f} | {mkt_pct:.1f}%</p>',
                                unsafe_allow_html=True)

                st.divider()

                # Delta 2: Live Total vs Predicted Total
                if pred:
                    st.write(f"**Model Pred: {pred:.1f}**")
                    if live:
                        model_edge = pred - live
                        edge_pct = (abs(model_edge) / live) * 100
                        # Highlight in red if model significantly disagrees with live market
                        color = "red-delta" if edge_pct >= 2 else ""
                        st.markdown(f'<p class="stCaption {color}">Edge Δ: {model_edge:+.1f} | {edge_pct:.1f}%</p>',
                                    unsafe_allow_html=True)