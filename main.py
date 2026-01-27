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
    today = datetime.now().strftime("%m/%d/%Y")
    off = leaguedashteamstats.LeagueDashTeamStats(season="2025-26", per_mode_detailed="PerGame").get_data_frames()[0]
    defn = leaguedashteamstats.LeagueDashTeamStats(season="2025-26", measure_type_detailed_defense="Opponent", per_mode_detailed="PerGame").get_data_frames()[0]
    return {
        r.TEAM_ID: {
            "off_ppg": r.PTS, "off_fg": r.FG_PCT, "off_3p": r.FG3_PCT,
            "def_ppg": defn[defn.TEAM_ID == r.TEAM_ID].iloc[0].OPP_PTS,
            "def_fg": defn[defn.TEAM_ID == r.TEAM_ID].iloc[0].OPP_FG_PCT,
            "def_3p": defn[defn.TEAM_ID == r.TEAM_ID].iloc[0].OPP_FG3_PCT,
        }
        for _, r in off.iterrows()
    }

# NEW PINNACLE LOGIC
@st.cache_data(ttl=86400)
def get_pinnacle_total(away_full, home_full, tip_off_iso):
    api_key = "b4fed2e35cfad747e07268fbb1377c2d"
    tip_dt = datetime.fromisoformat(tip_off_iso.replace('Z', '+00:00'))
    target_iso = (tip_dt - timedelta(minutes=10)).strftime('%Y-%m-%dT%H:%M:%SZ')
    url = "https://api.the-odds-api.com/v4/historical/sports/basketball_nba/odds"
    params = {"apiKey": api_key, "regions": "eu", "markets": "totals", "date": target_iso}
    try:
        # 5 second timeout to prevent the dashboard from hanging
        resp = requests.get(url, params=params, timeout=5).json()
        for g in resp.get('data', []):
            if g['away_team'] == away_full and g['home_team'] == home_full:
                for b in g.get('bookmakers', []):
                    if b['key'] == 'pinnacle':
                        return float(b['markets'][0]['outcomes'][0]['point'])
    except: return None
    return None

def fetch_kalshi_total(a, h):
    today = datetime.now().strftime("%y%b%d").upper()
    ticker = f"KXNBATOTAL-{today}{a}{h}"
    try:
        r = requests.get("https://api.elections.kalshi.com/trade-api/v2/markets", params={"event_ticker": ticker, "status": "open"}, timeout=5)
        mkts = r.json().get("markets", [])
        if mkts:
            main = min(mkts, key=lambda x: abs((x.get("yes_bid") or 0) - 50))
            return float(main["ticker"].split("-")[-1])
    except: return None

def get_quarter_fouls(game_id):
    try:
        actions = playbyplay.PlayByPlay(game_id).get_dict()["game"]["actions"]
        df = pd.DataFrame(actions)
        q = df["period"].max()
        fouls = df[(df.period == q) & (df.actionType == "foul") & (~df.subType.str.contains("offensive|technical|double", na=False))]
        return fouls.groupby("teamTricode").size().to_dict(), q
    except: return {}, None

# ---------------- DISPLAY ----------------
def is_live(status):
    s = status.lower()
    return any(k in s for k in ["q1", "q2", "q3", "q4", "half", "end", ":"]) and not any(k in s for k in ["pm", "et"])

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
if live_only:
    games = [g for g in games if is_live(g["gameStatusText"])]

cols = st.columns(2, gap="small")

for i, g in enumerate(games):
    col = cols[i % 2]
    with col:
        with st.container(border=True):
            a, h = g["awayTeam"], g["homeTeam"]
            a_tri, h_tri = a["teamTricode"], h["teamTricode"]
            a_full, h_full = f"{a['teamCity']} {a['teamName']}", f"{h['teamCity']} {h['teamName']}"

            st.markdown(f"**{a_tri} {a['score']} @ {h_tri} {h['score']} — {g['gameStatusText']}**")
            c1, c2, c3 = st.columns([1.2, 1.1, 0.9])

        # LEFT
        with c1:
            sa, sh = SEASON.get(a["teamId"]), SEASON.get(h["teamId"])
            if sa and sh:
                st.write("Season Averages")
                st.caption(f"{a_tri} O: {sa['off_ppg']:.1f} | {sa['off_fg']:.0%} | {sa['off_3p']:.0%}")
                st.caption(f"{h_tri} D: {sh['def_ppg']:.1f} | {sh['def_fg']:.0%} | {sh['def_3p']:.0%}")
                st.markdown("---")
                st.caption(f"{h_tri} O: {sh['off_ppg']:.1f} | {sh['off_fg']:.0%} | {sh['off_3p']:.0%}")
                st.caption(f"{a_tri} D: {sa['def_ppg']:.1f} | {sa['def_fg']:.0%} | {sa['def_3p']:.0%}")

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
            except: st.caption("Updating…")
            st.divider()
            st.write("**O/U Trends**")
            st.caption(f"{a_tri}: {TRENDS.get(a_tri, '--')}")
            st.caption(f"{h_tri}: {TRENDS.get(h_tri, '--')}")

        # RIGHT
        with c3:
            tip = get_pinnacle_total(a_full, h_full, g["gameTimeUTC"])
            live = fetch_kalshi_total(a_tri, h_tri)
            if tip: st.write(f"**Pinnacle:** {tip}")
            if live: st.write(f"**Live:** {live}")
            if tip and live:
                diff = live - tip
                pct = (abs(diff) / tip) * 100
                color = "red-delta" if pct >= 10 else ""
                st.markdown(f'<p class="stCaption {color}">Δ: {diff:+.1f} | {pct:.1f}%</p>', unsafe_allow_html=True)