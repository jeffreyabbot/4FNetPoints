import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
import tempfile
import json
import re
import matplotlib.pyplot as plt
import io
import base64
import unicodedata
#python -m streamlit run app.py   (para hacerlo funcionar)
# --- CONFIGURATION ---
DATA_BASE_PATH = "informes_data"
LOGOS_PATH = "logos"

LEAGUE_CONFIG = {
    "ACB": {"games_per_round": 9, "logo": "acb.png"},
    "Euroleague": {"games_per_round": 10, "logo": "EL.png"}, # EL is 18 teams now
    "Primera FEB": {"games_per_round": 8, "logo": "FEB.png"}, # 17 teams per group
    "Segunda FEB": {"games_per_round": 7, "logo": "FEB.png"}, # 14 teams per group
    "Tercera FEB": {"games_per_round": 7, "logo": "FEB.png"}, # Usually 14 teams
}
from matplotlib.colors import LinearSegmentedColormap

# 1. Red-White-Green (Standard: High is Good)
custom_rdwgn = LinearSegmentedColormap.from_list("rdwgn", ["#ff9999", "#ffffff", "#99ff99"])

# 2. Green-White-Red (Inverted: Low is Good - for Turnovers)
custom_gnwr = LinearSegmentedColormap.from_list("gnwr", ["#99ff99", "#ffffff", "#ff9999"])

# 3. White-Green (For Volumes like Points: More is better, no "bad" red)
custom_wgn = LinearSegmentedColormap.from_list("wgn", ["#ffffff", "#99ff99"])
def clean_num(val):
    if pd.isna(val) or val == "" or val == "-": return 0.0
    try: return float(val)
    except: return 0.0
# --- HELPERS ---
def inject_print_engine():
    st.markdown(
        """
        <style>
            @media print {
                /* 1. Page Setup */
                @page {
                    size: landscape;
                    margin: 0.5cm;
                }

                /* 2. Hide UI Clutter */
                [data-testid="stSidebar"], 
                [data-testid="stHeader"], 
                header, 
                footer, 
                .stButton, 
                [data-testid="stTableSettings"], 
                .print-hide {
                    display: none !important;
                }

                /* 3. Maximize Main Area */
                .main .block-container {
                    max-width: 100% !important;
                    width: 100% !important;
                    padding: 0 !important;
                    margin: 0 !important;
                }

                /* 4. FIX PLOTLY: Scale the outer container, leave internals intact */
                [data-testid="stPlotlyChart"] {
                    zoom: 0.85 !important; /* Shrinks the whole chart safely */
                    page-break-inside: avoid !important;
                    margin-bottom: 20px !important;
                }

                /* 5. FIX TABLES: Scale outer container */
                [data-testid="stDataFrame"], [data-testid="stTable"] {
                    zoom: 0.80 !important; /* Shrinks the table to fit the paper */
                    page-break-inside: avoid !important;
                }

                /* 6. Force background colors for Heatmaps & Bars */
                * {
                    -webkit-print-color-adjust: exact !important;
                    print-color-adjust: exact !important;
                    color-adjust: exact !important;
                }
            }
        </style>
        """,
        unsafe_allow_html=True,
    )
@st.cache_resource # This makes the search instant after the first time
def get_league_player_leaderboard(league, season, phase_ui):
    """Gathers every player from every team in the league into one table."""
    all_teams = get_teams_in_league(league, season)
    all_players_list = []
    
    if phase_ui == "Overall Season":
        actual_phase = "Regular_Season" 
    else:
        actual_phase = phase_ui.split(" - ")[0].replace(" ", "_")
    
    for team in all_teams:
        df_team = load_individual_aggregate(team, league, season, actual_phase)
        if df_team is not None and not df_team.empty:
            df_team['Team_Name'] = team 
            all_players_list.append(df_team)

    if not all_players_list:
        return pd.DataFrame()
        
    final_df = pd.concat(all_players_list, ignore_index=True)

    # --- THE IMPROVED FILTER ---
    # We filter out anything that looks like a Team or a Total row
    # This catches "TEAM Valencia", "Team Events", "TOTAL", etc.
    keywords = ['TEAM', 'EQUIP', 'EQUIPO', 'TOTAL', '--- TOTAL ---']
    pattern = '|'.join(keywords)
    
    # We find the 'Player' column (regardless of case)
    p_col = next((c for c in final_df.columns if c.upper() == 'PLAYER'), 'Player')
    
    mask_human = ~final_df[p_col].str.contains(pattern, case=False, na=False)
    final_df = final_df[mask_human].copy()

    return final_df
def normalize_str(text):
    if not text: return ""
    import unicodedata
    import re
    # 1. Basic cleaning
    s = str(text).strip().upper()
    
    # 2. Handle all types of apostrophes specifically
    # Replace straight ('), curly (’), and backtick (`) with a space
    s = s.replace("'", " ").replace("’", " ").replace("`", " ")
    
    # 3. Remove accents (SANDÁ -> SANDA)
    s = unicodedata.normalize('NFKD', s).encode('ascii', 'ignore').decode('utf-8')
    
    # 4. Remove dots and everything that isn't a letter or a number
    s = re.sub(r'[^A-Z0-9 ]', ' ', s)
    
    # 5. Collapse multiple spaces into one
    s = re.sub(r'\s+', ' ', s).strip()
    return s
@st.cache_resource
def get_logo_filename_map(last_mod_time):
    """Creates a dictionary mapping NORMALIZED team names to actual filenames.
    Supports PNG and JPG/JPEG.
    """
    folder_path = os.path.join(LOGOS_PATH, "teams")
    if not os.path.exists(folder_path):
        return {}
    
    mapping = {}
    valid_extensions = (".png", ".jpg", ".jpeg")
    
    for f in os.listdir(folder_path):
        if f.lower().endswith(valid_extensions):
            # Get name without any extension
            name_part = os.path.splitext(f)[0]
            team_key = normalize_str(name_part)
            mapping[team_key] = f
    return mapping
def get_team_icon(team_name, current_league=None):
    """Finds logo using normalized matching. 
    If 'League Average', returns the logo for the specific league.
    """
    if not team_name:
        return None
        
    # --- NEW: Handle League Average Case ---
    if team_name == "League Average" and current_league in LEAGUE_CONFIG:
        logo_filename = LEAGUE_CONFIG[current_league].get("logo", "FEB.png")
        os_path = os.path.join(LOGOS_PATH, logo_filename)
        mime_type = "image/png" # League logos are usually png
    else:
        # --- Existing Team Logo Logic ---
        folder_path = os.path.join(LOGOS_PATH, "teams")
        mtime = os.path.getmtime(folder_path) if os.path.exists(folder_path) else 0
        logo_map = get_logo_filename_map(mtime)
        
        search_name = normalize_str(team_name)
        actual_filename = logo_map.get(search_name)
        
        # Fuzzy Fallback
        if not actual_filename:
            for key, filename in logo_map.items():
                if key in search_name or search_name in key:
                    actual_filename = filename
                    break
        
        if actual_filename:
            os_path = os.path.join(LOGOS_PATH, "teams", actual_filename)
            ext = os.path.splitext(actual_filename)[1].lower().replace(".", "")
            mime_type = f"image/{ext if ext != 'jpg' else 'jpeg'}"
        else:
            os_path = os.path.join(LOGOS_PATH, "FEB.png")
            mime_type = "image/png"
        
    if os.path.exists(os_path):
        try:
            with open(os_path, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
                return f"data:{mime_type};base64,{data}"
        except Exception:
            return None
    return None

def load_single_game_individual(file_path, target_team):
    """
    Finds the individual player file for a specific game and filters it 
    for the target team using a space-insensitive Match Key.
    """
    try:
        # 1. Path Setup: Locate the 'individual' folder relative to the raw file
        phase_folder = os.path.dirname(os.path.dirname(file_path))
        individual_dir = os.path.join(phase_folder, "individual")
        
        if not os.path.exists(individual_dir):
            return None

        # 2. Extract target Game ID from the raw filename (e.g., 2486849)
        raw_name = os.path.basename(file_path)
        match = re.search(r'(\d+)', raw_name)
        if not match: 
            return None
        target_id = str(match.group(1))

        # 3. Search for the player file in the individual directory
        # Matches if the ID is anywhere in the filename (handles _PROCESSED_CHRONO, etc.)
        matching_file = None
        for f in os.listdir(individual_dir):
            if not f.startswith("NP_"): 
                continue
            
            # Find all numbers in the filename
            nums_in_file = re.findall(r'\d+', f)
            if nums_in_file and target_id == nums_in_file[0]:
                matching_file = f
                break
        
        if not matching_file:
            return None

        # 4. Load the individual Excel file
        full_path = os.path.join(individual_dir, matching_file)
        df = pd.read_excel(full_path)
        
        # 5. Clean up the dataframe (Remove 'TOTAL' summary rows)
        if 'Player' in df.columns:
            df = df[~df['Player'].astype(str).str.contains('TOTAL', na=False, case=False)]
        elif 'PLAYER' in df.columns:
            df = df[~df['PLAYER'].astype(str).str.contains('TOTAL', na=False, case=False)]

        # 6. Define the "Super Normalized" Match Key (Ignores spaces, dots, and accents)
        def make_match_key(text):
            if not text or pd.isna(text): 
                return ""
            # normalize_str handles accents and uppercase
            s = normalize_str(str(text))
            # Remove dots and all whitespace
            return re.sub(r'[\s\.]+', '', s)

        nk_target = make_match_key(target_team)

        # 7. Identify the Team Column (Handles 'Team', 'EQUIP', 'EQUIPO', etc.)
        team_col = None
        for col in df.columns:
            if col.strip().upper() in ['TEAM', 'EQUIP', 'EQUIPO', 'CLUB', 'EQUIPOS']:
                team_col = col
                break
        
        if not team_col:
            return None

        # 8. Apply the match (Exact key match or fuzzy containment)
        def is_team_match(row_val):
            nk_row = make_match_key(row_val)
            if not nk_row or not nk_target: 
                return False
            # Match if identical keys OR one is contained in the other
            return (nk_row == nk_target) or (nk_row in nk_target and len(nk_row) > 4) or (nk_target in nk_row)

        mask = df[team_col].apply(is_team_match)
        df_filtered = df[mask].copy()

        # 9. Safety: Ensure GP column exists
        # Normalize existing GP column name if it exists (gp -> GP)
        for col in df_filtered.columns:
            if col.strip().upper() == 'GP':
                df_filtered = df_filtered.rename(columns={col: 'GP'})
                break
        
        if 'GP' not in df_filtered.columns:
            df_filtered['GP'] = 1
        
        # Ensure 'Player' column is standardized for the groupby later
        for col in df_filtered.columns:
            if col.strip().upper() == 'PLAYER':
                df_filtered = df_filtered.rename(columns={col: 'Player'})
                break

        return df_filtered
        
    except Exception as e:
        # st.error(f"Error loading individual file: {e}")
        return None
def get_h2h_stats(t1, t2, league, season):
    def make_match_key(text):
        if not text: return ""
        return re.sub(r'[\s\.]+', '', normalize_str(text))

    nk1, nk2 = make_match_key(t1), make_match_key(t2)
    
    mask_ls = (df_index['league'] == league) & (df_index['season'] == season)
    df_ls = df_index[mask_ls].copy()
    if df_ls.empty: return {}, {}

    def is_match(row):
        ik1, ik2 = make_match_key(row['t1']), make_match_key(row['t2'])
        # Fuzzy Match
        m1 = (nk1 in ik1 or ik1 in nk1) and (nk2 in ik2 or ik2 in nk2)
        m2 = (nk1 in ik2 or ik2 in nk1) and (nk2 in ik1 or ik1 in nk2)
        return m1 or m2

    h2h_games = df_ls[df_ls.apply(is_match, axis=1)]

    keys = ['pts', 'f2m', 'f2a', 'f3m', 'f3a', 'ftm', 'fta', 'orb', 'drb', 'tov', 'pts_off_to', 'pts_2nd_ch', 'pts_fb']
    t1_sum = {k: 0.0 for k in keys}
    t2_sum = {k: 0.0 for k in keys}
    t1_sum['gp'] = 0

    # We normalize the sidebar names once before the loop
    n_t1 = normalize_str(t1)

    for _, row in h2h_games.iterrows():
        game_data = get_raw_game_data_custom(row['path'])
        if not game_data: continue

        # --- THE FIX: Use normalized names to identify which stats are which ---
        # We compare the normalized name from the index to the normalized sidebar name
        if normalize_str(row['t1']) == n_t1:
            raw_s1, raw_s2 = game_data['t1_stats'], game_data['t2_stats']
        else:
            raw_s1, raw_s2 = game_data['t2_stats'], game_data['t1_stats']
        
        t1_sum['gp'] += 1
        for k in keys:
            # We use float() and .get() to ensure we never pass a None or String to the sum
            t1_sum[k] += float(raw_s1.get(k, 0))
            t2_sum[k] += float(raw_s2.get(k, 0))

    return t1_sum, t2_sum
def load_h2h_individual_data(target_team, opponent_team, league, season):
    # 1. Significant Words for matching
    def get_sig_words(text):
        s = normalize_str(text)
        ignore = {'THE', 'CLUB', 'BASQUET', 'BASKET', 'BALONCESTO', 'DEPORTIVA', 'U.E.', 'C.B.'}
        return {w for w in s.split() if len(w) > 2 and w not in ignore}

    target_words = get_sig_words(target_team)
    opponent_words = get_sig_words(opponent_team)

    # 2. Filter Index
    mask_ls = (df_index['league'] == league) & (df_index['season'] == season)
    df_ls = df_index[mask_ls].copy()
    if df_ls.empty: return None
    
    # 3. Matchup Search
    def is_matchup(row):
        t1_w, t2_w = get_sig_words(row['t1']), get_sig_words(row['t2'])
        m1 = len(target_words & t1_w) > 0 and len(opponent_words & t2_w) > 0
        m2 = len(target_words & t2_w) > 0 and len(opponent_words & t1_w) > 0
        return m1 or m2

    matchup_games = df_ls[df_ls.apply(is_matchup, axis=1)]
    
    
    # 4. Load stats if games exist... (Keep rest of the code as is)
    all_game_stats = []
    for _, row in matchup_games.iterrows():
        df_game = load_single_game_individual(row['path'], target_team)
        if df_game is not None and not df_game.empty:
            df_game.columns = [c.strip().upper() for c in df_game.columns]
            all_game_stats.append(df_game)

    if not all_game_stats: return None
    combined = pd.concat(all_game_stats, ignore_index=True)
    cols_to_sum = combined.select_dtypes(include=['number']).columns.tolist()
    h2h_totals = combined.groupby('PLAYER')[cols_to_sum].sum().reset_index().rename(columns={'PLAYER': 'Player'})
    
    # Average the stats
    for col in h2h_totals.columns:
        if col not in ['Player', 'Team', 'GP']:
            h2h_totals[col] = h2h_totals[col] / len(matchup_games)
        
    return h2h_totals
def get_per_game_volumes_by_phase(team_name, league, season, phase, row_label="TOTAL"):
    # Convert UI phase name (e.g. "Regular Season - ESTE") back to folder name ("Regular_Season")
    # We take the part before the " - " and replace spaces with underscores
    folder_phase = phase.split(" - ")[0].replace(" ", "_")
    target_path = os.path.join(DATA_BASE_PATH, league, season, folder_phase, "aggregate")
    target_filename = f"AGGREGATE_{team_name}.xlsx"
    file_path = os.path.join(target_path, target_filename)
    
    # Default empty stats in case file is missing
    empty_stats = {"gp": 1, "pts": 0, "f2m": 0, "f2a": 0, "f3m": 0, "f3a": 0, "ftm": 0, "fta": 0, "drb": 0, "orb": 0, "tov": 0,"pts_off_to": 0, "pts_2nd_ch": 0, "pts_fb": 0}

    if os.path.exists(file_path):
        try:
            df = pd.read_excel(file_path, header=None)
            # Find the row (TOTAL or Rival)
            row_t = df[df[0] == row_label].iloc[0]
            gp = clean_num(row_t[1])
            
            if gp == 0: return empty_stats
            
            # Return per-game averages
            return {
                "gp": gp, 
                "pts": clean_num(row_t[2])/gp, "f2m": clean_num(row_t[3])/gp,
                "f2a": clean_num(row_t[4])/gp, "f3m": clean_num(row_t[5])/gp, 
                "f3a": clean_num(row_t[6])/gp, "ftm": clean_num(row_t[7])/gp, 
                "fta": clean_num(row_t[8])/gp, "drb": clean_num(row_t[10])/gp,
                "orb": clean_num(row_t[11])/gp, "tov": clean_num(row_t[15])/gp,
                "pts_off_to": clean_num(row_t[20])/gp,
                "pts_2nd_ch": clean_num(row_t[21])/gp,
                "pts_fb": clean_num(row_t[22])/gp
            }
        except: 
            return empty_stats
    return empty_stats
def get_per_game_volumes(team_name, league, season, row_label="TOTAL"):
    # 1. Initialize accumulators
    total_gp = 0
    # Store totals for the whole season
    stats_acc = {
        "pts": 0, "f2m": 0, "f2a": 0, "f3m": 0, "f3a": 0, "ftm": 0, "fta": 0, 
        "drb": 0, "orb": 0, "tov": 0,
        "pts_off_to": 0, "pts_2nd_ch": 0, "pts_fb": 0 # NEW
    }
    found_any = False

    season_path = os.path.join(DATA_BASE_PATH, league, season)
    target_filename = f"AGGREGATE_{team_name}.xlsx"
    
    # 2. Walk through the whole season folder
    for root, dirs, files in os.walk(season_path):
        # Only process files inside 'aggregate' folders to avoid raw game files
        if "aggregate" in root.lower():
            if target_filename in files:
                try:
                    df = pd.read_excel(os.path.join(root, target_filename), header=None)
                    
                    # USE YOUR EXACT ROW MATCHING LOGIC
                    matching_rows = df[df[0] == row_label]
                    if matching_rows.empty:
                        continue
                    
                    row_t = matching_rows.iloc[0]
                    gp = clean_num(row_t[1])
                    
                    if gp > 0:
                        found_any = True
                        total_gp += gp
                        # SUM THE ABSOLUTE TOTALS (Points, Rebounds, etc.)
                        stats_acc["pts"] += clean_num(row_t[2])
                        stats_acc["f2m"] += clean_num(row_t[3])
                        stats_acc["f2a"] += clean_num(row_t[4])
                        stats_acc["f3m"] += clean_num(row_t[5])
                        stats_acc["f3a"] += clean_num(row_t[6])
                        stats_acc["ftm"] += clean_num(row_t[7])
                        stats_acc["fta"] += clean_num(row_t[8])
                        stats_acc["drb"] += clean_num(row_t[10])
                        stats_acc["orb"] += clean_num(row_t[11])
                        stats_acc["tov"] += clean_num(row_t[15])
                        # NEW FIELDS:
                        stats_acc["pts_off_to"] += clean_num(row_t[20])
                        stats_acc["pts_2nd_ch"] += clean_num(row_t[21])
                        stats_acc["pts_fb"] += clean_num(row_t[22])
                except:
                    # If one file is corrupt, skip it and continue to the next one
                    continue

    # 3. If we didn't find any file, return the safe "empty" dictionary
    if not found_any or total_gp == 0:
        return {"gp": 1, "pts": 0, "f2m": 0, "f2a": 0, "f3m": 0, "f3a": 0, "ftm": 0, "fta": 0, "drb": 0, "orb": 0, "tov": 0, "pts_off_to": 0, "pts_2nd_ch": 0, "pts_fb": 0}

    # 4. DIVIDE THE SEASON TOTAL BY TOTAL GAMES PLAYED
    # This gives the true average for the whole year (e.g. Total Pts / 39 games)
    return {
        "gp": total_gp,
        "pts": stats_acc["pts"] / total_gp,
        "f2m": stats_acc["f2m"] / total_gp,
        "f2a": stats_acc["f2a"] / total_gp,
        "f3m": stats_acc["f3m"] / total_gp,
        "f3a": stats_acc["f3a"] / total_gp,
        "ftm": stats_acc["ftm"] / total_gp,
        "fta": stats_acc["fta"] / total_gp,
        "drb": stats_acc["drb"] / total_gp,
        "orb": stats_acc["orb"] / total_gp,
        "tov": stats_acc["tov"] / total_gp,
        "pts_off_to": stats_acc["pts_off_to"] / total_gp,
        "pts_2nd_ch": stats_acc["pts_2nd_ch"] / total_gp,
        "pts_fb": stats_acc["pts_fb"] / total_gp
    }
def load_individual_aggregate(team_name, league, season, phase=None):
    """Loads player totals and divides by team's total games played."""
    if phase is None or not isinstance(phase, str) or phase == "":
        folder_phase = "Regular_Season"
    else:
        folder_phase = phase.split(" - ")[0].replace(" ", "_")
    
    file_path = os.path.join(
        DATA_BASE_PATH, league, season, folder_phase, 
        "aggregate_individual", f"AGG_IND_{team_name}.xlsx"
    )

    if not os.path.exists(file_path):
        return None

    try:
        # 1. Get the total games the team played (GP)
        # We use your existing function that reads the team aggregate file
        team_stats = get_per_game_volumes(team_name, league, season)
        gp = team_stats.get('gp', 1)
        if gp <= 0: gp = 1

        # 2. Load the player file
        df = pd.read_excel(file_path)
        df = df[~df['Player'].astype(str).str.contains('--- TOTAL ---', na=False, case=False)].copy()
        numeric_cols = df.select_dtypes(include=['number']).columns
        for col in numeric_cols:
            # We only divide by team GP if the column is NOT 'GP'
            if col != 'GP': 
                df[col] = df[col] / gp
            # If it IS 'GP', we leave it as an absolute integer
                
        return df
    except Exception:
        return None
def load_single_game_classic_individual(file_path, target_team):
    try:
        df = pd.read_excel(file_path, header=None)
        mask = df[0].astype(str).str.upper().str.strip().str.startswith("TOTAL")
        total_rows = df[mask].index
        if len(total_rows) < 2: return None

        t1_name = str(df.iloc[1, 0]).strip()
        t2_name = str(df.iloc[2, 0]).strip()

        def make_match_key(text):
            if not text or pd.isna(text): return ""
            return re.sub(r'[\s\.]+', '', normalize_str(str(text)))

        nk_target = make_match_key(target_team)
        nk_t1 = make_match_key(t1_name)
        nk_t2 = make_match_key(t2_name)

        if nk_target == nk_t1 or nk_target in nk_t1 or nk_t1 in nk_target:
            start_idx = 3
            end_idx = total_rows[0]
        elif nk_target == nk_t2 or nk_target in nk_t2 or nk_t2 in nk_target:
            start_idx = total_rows[0] + 2
            end_idx = total_rows[1]
        else:
            return None

        df_players = df.iloc[start_idx:end_idx].copy()
        
        # Ensure column 38 (AM) exists for Minutes
        if 38 not in df_players.columns:
            df_players[38] = "0:00"

        # Map 38 to MIN_STR
        df_players = df_players.rename(columns={
            0: "Player", 1: "PTS", 2: "F2M", 3: "F2A", 4: "F3M", 5: "F3A",
            6: "FTM", 7: "FTA", 9: "DRB", 10: "ORB", 14: "TOV",
            19: "Pts_off_TO", 20: "2nd_Chance", 21: "Fast_Break", 38: "MIN_STR"
        })
        
        # Time Parser (e.g. "24:15" -> 24.25)
        def parse_min(val):
            if pd.isna(val): return 0.0
            if hasattr(val, 'hour') and hasattr(val, 'minute') and hasattr(val, 'second'):
                return val.hour * 60 + val.minute + val.second / 60.0
            val_str = str(val).strip()
            if ':' in val_str:
                parts = val_str.split(':')
                try: return float(parts[0]) + float(parts[1])/60.0
                except: return 0.0
            try: return float(val_str)
            except: return 0.0

        df_players['MIN'] = df_players['MIN_STR'].apply(parse_min)

        cols_to_keep = ["Player", "PTS", "F2M", "F2A", "F3M", "F3A", "FTM", "FTA", "ORB", "DRB", "TOV", "Pts_off_TO", "2nd_Chance", "Fast_Break", "MIN"]
        valid_cols = [c for c in cols_to_keep if c in df_players.columns]
        df_players = df_players[valid_cols]

        df_players = df_players.dropna(subset=['Player'])
        df_players = df_players[df_players['Player'].astype(str).str.strip() != ""]
        
        garbage = ['JUGADOR', 'ASISTENCIA', 'LUGAR', 'PABELLÓN', 'ÁRBITRO', 'ARBITRO', 'TOTAL', 'EQUIP', 'ENTRENADOR']
        df_players = df_players[~df_players['Player'].astype(str).str.upper().apply(lambda x: any(g in x for g in garbage))]
        
        df_players['PTS'] = pd.to_numeric(df_players['PTS'], errors='coerce')
        df_players = df_players.dropna(subset=['PTS'])

        for c in valid_cols:
            if c not in ["Player", "MIN"]:
                df_players[c] = pd.to_numeric(df_players[c], errors='coerce').fillna(0.0)

        df_players['Team_Name'] = target_team
        df_players['GP'] = 1
        df_players['FGA'] = df_players['F2A'] + df_players['F3A']
        df_players['FGM'] = df_players['F2M'] + df_players['F3M']

        df_players['eFG%'] = df_players.apply(lambda x: (x['FGM'] + 0.5 * x['F3M']) / x['FGA'] if x['FGA'] > 0 else 0, axis=1)
        df_players['TO%'] = df_players.apply(lambda x: x['TOV'] / (x['FGA'] + 0.44 * x['FTA'] + x['TOV']) if (x['FGA'] + 0.44 * x['FTA'] + x['TOV']) > 0 else 0, axis=1)
        df_players['FTR'] = df_players.apply(lambda x: x['FTM'] / x['FGA'] if x['FGA'] > 0 else 0, axis=1)
        
        # Calculate true OR/40
        df_players['OR/40'] = df_players.apply(lambda x: (x['ORB'] / x['MIN']) * 40 if x['MIN'] > 0 else 0, axis=1)

        return df_players
    except Exception as e:
        return None
def load_aggregated_classic_individual_data(target_team, league, season, phase=None, opponent_team=None):
    def get_sig_words(text):
        s = normalize_str(text)
        ignore = {'THE', 'CLUB', 'BASQUET', 'BASKET', 'BALONCESTO', 'DEPORTIVA', 'U.E.', 'C.B.'}
        return {w for w in s.split() if len(w) > 2 and w not in ignore}

    target_words = get_sig_words(target_team)
    
    mask_ls = (df_index['league'] == league) & (df_index['season'] == season)
    if phase and phase != "Overall Season":
        mask_ls = mask_ls & (df_index['phase'] == phase)
    
    df_ls = df_index[mask_ls].copy()
    if df_ls.empty: return None

    def is_matchup(row):
        t1_w, t2_w = get_sig_words(row['t1']), get_sig_words(row['t2'])
        has_target = len(target_words & t1_w) > 0 or len(target_words & t2_w) > 0
        if not has_target: return False
        if opponent_team:
            opp_words = get_sig_words(opponent_team)
            return (len(opp_words & t1_w) > 0 or len(opp_words & t2_w) > 0)
        return True

    matchup_games = df_ls[df_ls.apply(is_matchup, axis=1)]

    all_game_stats = []
    for _, row in matchup_games.iterrows():
        df_game = load_single_game_classic_individual(row['path'], target_team)
        if df_game is not None and not df_game.empty:
            all_game_stats.append(df_game)

    if not all_game_stats: return None
    combined = pd.concat(all_game_stats, ignore_index=True)
    
    # We sum MIN as well to calculate the exact average later
    cols_to_sum = ["PTS", "F2M", "F2A", "F3M", "F3A", "FTM", "FTA", "ORB", "DRB", "TOV", "Pts_off_TO", "2nd_Chance", "Fast_Break", "FGA", "FGM", "GP", "MIN"]
    cols_to_sum = [c for c in cols_to_sum if c in combined.columns]
    
    h2h_totals = combined.groupby('Player')[cols_to_sum].sum().reset_index()

    n_games = len(matchup_games)
    for col in h2h_totals.columns:
        if col not in ['Player', 'Team_Name', 'GP']:
            h2h_totals[col] = h2h_totals[col] / n_games

    h2h_totals['eFG%'] = h2h_totals.apply(lambda x: (x.get('FGM',0) + 0.5 * x.get('F3M',0)) / x['FGA'] if x.get('FGA', 0) > 0 else 0, axis=1)
    h2h_totals['TO%'] = h2h_totals.apply(lambda x: x.get('TOV',0) / (x.get('FGA',0) + 0.44 * x.get('FTA',0) + x.get('TOV',0)) if (x.get('FGA',0) + 0.44 * x.get('FTA',0) + x.get('TOV',0)) > 0 else 0, axis=1)
    h2h_totals['FTR'] = h2h_totals.apply(lambda x: x.get('FTM',0) / x['FGA'] if x.get('FGA', 0) > 0 else 0, axis=1)
    h2h_totals['OR/40'] = h2h_totals.apply(lambda x: (x.get('ORB',0) / x['MIN']) * 40 if x.get('MIN', 0) > 0 else 0, axis=1)
    h2h_totals['Team_Name'] = target_team

    return h2h_totals
@st.cache_resource
def get_league_player_leaderboard_classic_v4(league, season, phase_ui):
    all_teams = get_teams_in_league(league, season)
    all_players_list = []
    
    for team in all_teams:
        df_team = load_aggregated_classic_individual_data(team, league, season, phase=phase_ui)
        if df_team is not None and not df_team.empty:
            df_team['Team_Name'] = team
            all_players_list.append(df_team)
            
    if not all_players_list: 
        return pd.DataFrame()
        
    final_df = pd.concat(all_players_list, ignore_index=True)
    
    keywords = ['TEAM', 'EQUIP', 'EQUIPO', 'TOTAL', '--- TOTAL ---']
    pattern = '|'.join(keywords)
    p_col = next((c for c in final_df.columns if c.upper() == 'PLAYER'), 'Player')
    mask_human = ~final_df[p_col].str.contains(pattern, case=False, na=False)
    
    return final_df[mask_human].copy()
def load_h2h_classic_individual_data(target_team, opponent_team, league, season):
    def get_sig_words(text):
        s = normalize_str(text)
        ignore = {'THE', 'CLUB', 'BASQUET', 'BASKET', 'BALONCESTO', 'DEPORTIVA', 'U.E.', 'C.B.'}
        return {w for w in s.split() if len(w) > 2 and w not in ignore}

    target_words = get_sig_words(target_team)
    opponent_words = get_sig_words(opponent_team)

    mask_ls = (df_index['league'] == league) & (df_index['season'] == season)
    df_ls = df_index[mask_ls].copy()
    if df_ls.empty: return None

    def is_matchup(row):
        t1_w, t2_w = get_sig_words(row['t1']), get_sig_words(row['t2'])
        m1 = len(target_words & t1_w) > 0 and len(opponent_words & t2_w) > 0
        m2 = len(target_words & t2_w) > 0 and len(opponent_words & t1_w) > 0
        return m1 or m2

    matchup_games = df_ls[df_ls.apply(is_matchup, axis=1)]

    all_game_stats = []
    for _, row in matchup_games.iterrows():
        df_game = load_single_game_classic_individual(row['path'], target_team)
        if df_game is not None and not df_game.empty:
            all_game_stats.append(df_game)

    if not all_game_stats: return None
    combined = pd.concat(all_game_stats, ignore_index=True)
    cols_to_sum = combined.select_dtypes(include=['number']).columns.tolist()
    for c in ['eFG%', 'TO%', 'FTR']:
        if c in cols_to_sum: cols_to_sum.remove(c)

    h2h_totals = combined.groupby('Player')[cols_to_sum].sum().reset_index()

    n_games = len(matchup_games)
    for col in h2h_totals.columns:
        if col not in ['Player', 'Team_Name', 'GP']:
            h2h_totals[col] = h2h_totals[col] / n_games

    h2h_totals['eFG%'] = h2h_totals.apply(lambda x: (x.get('FGM',0) + 0.5 * x.get('F3M',0)) / x['FGA'] if x.get('FGA', 0) > 0 else 0, axis=1)
    h2h_totals['TO%'] = h2h_totals.apply(lambda x: x.get('TOV',0) / (x.get('FGA',0) + 0.44 * x.get('FTA',0) + x.get('TOV',0)) if (x.get('FGA',0) + 0.44 * x.get('FTA',0) + x.get('TOV',0)) > 0 else 0, axis=1)
    h2h_totals['FTR'] = h2h_totals.apply(lambda x: x.get('FTM',0) / x['FGA'] if x.get('FGA', 0) > 0 else 0, axis=1)
    h2h_totals['Team_Name'] = target_team

    return h2h_totals
def load_individual_aggregate_classic(team_name, league, season, phase=None):
    df = load_individual_aggregate(team_name, league, season, phase)
    if df is None or df.empty: return None
    col_map = {c.upper(): c for c in df.columns}
    def gc(name): return col_map.get(name.upper())
    f2a, f3a = gc('F2A'), gc('F3A')
    f2m, f3m = gc('F2M'), gc('F3M')
    fta, ftm = gc('FTA'), gc('FTM')
    tov = gc('TOV')
    if all([f2a, f3a, f2m, f3m, fta, ftm, tov]):
        df['FGA'] = df[f2a] + df[f3a]
        df['FGM'] = df[f2m] + df[f3m]
        df['eFG%'] = df.apply(lambda x: (x['FGM'] + 0.5 * x[f3m]) / x['FGA'] if x['FGA'] > 0 else 0, axis=1)
        df['TO%'] = df.apply(lambda x: x[tov] / (x['FGA'] + 0.44 * x[fta] + x[tov]) if (x['FGA'] + 0.44 * x[fta] + x[tov]) > 0 else 0, axis=1)
        df['FTR'] = df.apply(lambda x: x[ftm] / x['FGA'] if x['FGA'] > 0 else 0, axis=1)
    return df
def display_player_table(df, title, show_off_def=False, show_shooting=False):
    if df is None or df.empty:
        st.warning(f"No player data found for {title}")
        return

    col_map = {c.upper(): c for c in df.columns}
    def get_col(name): return col_map.get(name.upper())
    p_col = get_col('Player')

    # Replaced OR/100 with OR/40
    rankable_metrics = ['Total_NP', 'Net_Shooting', 'Net_TOV', 'Net_ORB', 'Net_FT', 'PTS', 'eFG%', 'TO%', 'OR/40', 'FTR', 'Pts_off_TO', '2nd_Chance', 'Fast_Break']
    available_sorts = [s for s in rankable_metrics if get_col(s) is not None]

    sort_key = f"sort_box_{title.replace(' ', '_')}"
    sel_c1, sel_c2 = st.columns([1, 3])
    with sel_c1:
        chosen_sort = st.selectbox("Rank By:", available_sorts, key=sort_key)

    actual_sort_col = get_col(chosen_sort)
    df_sorted = df.sort_values(actual_sort_col, ascending=False).copy()

    is_team_mask = df_sorted[p_col].str.contains('TEAM|EQUIP|TOTAL', case=False, na=False)
    df_humans = df_sorted[~is_team_mask].copy()
    df_team_row = df_sorted[is_team_mask].copy()

    df_humans.insert(0, 'Pos', range(1, len(df_humans) + 1))
    df_team_row.insert(0, 'Pos', 0)
    df_final = pd.concat([df_humans, df_team_row])

    cols_to_show = ['Pos', p_col]
    if get_col('Team_Name'): cols_to_show.append(get_col('Team_Name'))
    if get_col('GP'): cols_to_show.append(get_col('GP'))

    main_impact = get_col('Total_NP')
    if main_impact: cols_to_show.append(main_impact)

    # Replaced OR/100 with OR/40
    classic_cols = ['PTS', 'eFG%', 'TO%', 'OR/40', 'FTR', 'Pts_off_TO', '2nd_Chance', 'Fast_Break']
    for c in classic_cols:
        actual_c = get_col(c)
        if actual_c and actual_c not in cols_to_show:
            cols_to_show.append(actual_c)

    def add_factor_group(factor_name):
        net = get_col(f'Net_{factor_name}')
        off = get_col(f'Off_{factor_name}')
        dfn = get_col(f'Def_{factor_name}')

        if net and net not in cols_to_show:
            cols_to_show.append(net)

        if show_off_def:
            if off: cols_to_show.append(off)
            if dfn: cols_to_show.append(dfn)

        if factor_name == 'Shooting' and show_shooting:
            for shot in ['Off_2P', 'Off_3P', 'Def_2P', 'Def_3P']:
                c = get_col(shot)
                if c: cols_to_show.append(c)

    for f in ['Shooting', 'TOV', 'ORB', 'FT']:
        add_factor_group(f)

    cols_to_show = [c for i, c in enumerate(cols_to_show) if c in df_final.columns and c not in cols_to_show[:i]]

    text_cols = ['Pos', p_col, get_col('Team_Name'), get_col('Team'), get_col('GP')]
    numeric_cols = [c for c in cols_to_show if c not in text_cols]

    format_map = {}
    for col in numeric_cols:
        if '%' in col or col.upper() == 'FTR':
            format_map[col] = "{:.1%}" if '%' in col else "{:.3f}"
        elif col.upper() in [c.upper() for c in classic_cols]:
            format_map[col] = "{:.2f}"
        else:
            format_map[col] = "{:+.2f}"
    format_map['Pos'] = "{:.0f}"
    if get_col('GP') in df_final.columns: format_map[get_col('GP')] = "{:.0f}"

    styler = df_final[cols_to_show].style.format(format_map)
    styler = styler.map(lambda x: 'color: transparent;' if x == 0 else '', subset=['Pos'])
    styler = styler.apply(lambda row: ['background-color: rgba(255,255,255,0.08);'] * len(row) if 'TEAM' in str(row[p_col]).upper() else [''] * len(row), axis=1)

    for col in numeric_cols:
        if col.upper() in [c.upper() for c in classic_cols]:
            if col.upper() == 'TO%':
                styler = styler.background_gradient(cmap=custom_gnwr, subset=[col])
            elif col.upper() in ['PTS', 'OR/40', 'PTS_OFF_TO', '2ND_CHANCE', 'FAST_BREAK']:
                styler = styler.background_gradient(cmap=custom_wgn, subset=[col])
            else:
                styler = styler.background_gradient(cmap=custom_rdwgn, subset=[col])
        else:
            v_max = df_final[col].abs().max()
            v_max = max(v_max, 1.0)
            styler = styler.background_gradient(cmap=custom_rdwgn, subset=[col], vmin=-v_max, vmax=v_max)

    # --- THE MAGIC FIX: DYNAMIC HEIGHT & COLUMN WIDTHS ---
    dynamic_height = (len(df_final) * 36) + 45

    # 1. Start with the base column configuration
    col_config = {
        "Pos": st.column_config.NumberColumn("Pos", width="small"), 
        p_col: st.column_config.TextColumn("Player", width="medium")
    }
    
    # 2. Force every single numeric column to be "small" so they don't stretch
    for col in numeric_cols:
        col_config[col] = st.column_config.NumberColumn(col, width="small")

    st.dataframe(
        styler, 
        use_container_width=False, # Keeps it looking nice on screen
        hide_index=True, 
        height=dynamic_height, 
        column_config=col_config  # Applies our strict column widths
    )
def get_teams_in_league(league, season): # Added season param
    teams = set()
    season_path = os.path.join(DATA_BASE_PATH, league, season) # Target specific season
    if not os.path.exists(season_path): return []
    for root, dirs, files in os.walk(season_path):
        if os.path.basename(root) == "aggregate":
            for f in files:
                if f.startswith('AGGREGATE_') and f.endswith('.xlsx'):
                    teams.add(f.replace("AGGREGATE_", "").replace(".xlsx", ""))
    return sorted(list(teams))
def calculate_round(league, filename):
    match = re.search(r'(\d+)', filename)
    if not match: return "Regular Season"
    
    config = LEAGUE_CONFIG.get(league)
    if not config: return "Regular Season"
    
    try:
        game_id = int(match.group(1))
        # Generic formula: ((ID - Start_ID) // Games_Per_Round) + 1
        rnd = ((game_id - config["base_id"]) // config["games_per_round"]) + 1
        return f"Round {max(1, rnd):02d}"
    except:
        return "Regular Season"
def get_4f_percentages(stats, opp_stats=None):
    fga = stats['f2a'] + stats['f3a']
    fgm = stats['f2m'] + stats['f3m']
    efg = (fgm + 0.5 * stats['f3m']) / fga if fga > 0 else 0
    tov_pct = stats['tov'] / (fga + 0.44 * stats['fta'] + stats['tov']) if (fga + 0.44 * stats['fta'] + stats['tov']) > 0 else 0
    ft_rate = stats['ftm'] / fga if fga > 0 else 0
    orb_pct = 0
    if opp_stats:
        denom = stats['orb'] + opp_stats['drb']
        orb_pct = stats['orb'] / denom if denom > 0 else 0
    
    # Return raw numbers, not strings
    return {
        "eFG%": efg, 
        "TO%": tov_pct, 
        "ORB%": orb_pct, 
        "FTR": ft_rate  # Standardized key name
    }
def get_raw_game_data_custom(file_path):
    df = pd.read_excel(file_path, header=None)
    total_rows = df[df[0] == "TOTAL"]
    if len(total_rows) < 2: return None
    t1_row, t2_row = total_rows.iloc[0], total_rows.iloc[1]
    def parse_row(row):
        return {"pts": clean_num(row[1]), "f2m": clean_num(row[2]), "f2a": clean_num(row[3]),
                "f3m": clean_num(row[4]), "f3a": clean_num(row[5]), "ftm": clean_num(row[6]),
                "fta": clean_num(row[7]), "drb": clean_num(row[9]), "orb": clean_num(row[10]), "tov": clean_num(row[14]),
    # NEW FIELDS:
                "pts_off_to": clean_num(row[19]), # Row 19
                "pts_2nd_ch": clean_num(row[20]), # Row 20
                "pts_fb": clean_num(row[21]) }     # Row 21
    return {"t1_name": str(df.iloc[1, 0]), "t2_name": str(df.iloc[2, 0]),
            "t1_stats": parse_row(t1_row), "t2_stats": parse_row(t2_row)}
def build_game_index():
    raw_data = []
    print("\n--- [START DYNAMIC INDEXING] ---")

    # Step 1: Preliminary scan of all files to get Teams and IDs
    for root, dirs, files in os.walk(DATA_BASE_PATH):
        if os.path.basename(root).lower() == "raw":
            rel_path = os.path.relpath(root, DATA_BASE_PATH)
            parts = rel_path.split(os.sep)
            if len(parts) >= 3:
                league, season, phase = parts[0], parts[1], parts[2]
                for filename in files:
                    if filename.endswith(".xlsx") and not filename.startswith("~$"):
                        match = re.search(r'(\d+)', filename)
                        if match:
                            game_id = int(match.group(1))
                            group_part = filename.split(str(game_id))[-1].replace(".xlsx", "").strip("_")
                            group_part = group_part.replace("LIGAREGULAR", "")
                            group_name = group_part if group_part else "Main"

                            file_path = os.path.join(root, filename)
                            try:
                                # Read just enough to get team names
                                df = pd.read_excel(file_path, header=None, nrows=3)
                                t1_name = str(df.iloc[1, 0]).strip()
                                t2_name = str(df.iloc[2, 0]).strip()

                                raw_data.append({
                                    "league": league, "season": season, "phase_orig": phase,
                                    "group": group_name, "game_id": game_id, "t1": t1_name, "t2": t2_name,
                                    "filename": filename, "path": file_path
                                })
                            except: continue

    if not raw_data:
        print("!!! NO FILES FOUND !!!")
        return

    df_all = pd.DataFrame(raw_data)
    final_data = []

    # Step 2: Process each Phase separately
    for (lg, sn, ph_orig, gp), df_group in df_all.groupby(['league', 'season', 'phase_orig', 'group']):

        is_postseason = "playoff" in ph_orig.lower() or "post" in ph_orig.lower()

        if is_postseason:
            # --- SMART PLAYOFF LOGIC ---
            df_group = df_group.copy()
            df_group['matchup'] = df_group.apply(lambda x: "-".join(sorted([x['t1'], x['t2']])), axis=1)
            
            # Sort chronologically by game_id to map the timeline
            df_group = df_group.sort_values('game_id').reset_index(drop=True)
            
            matchup_counts = df_group['matchup'].value_counts()
            seen_counts = {}
            total_games = len(df_group)
            
            for i, row in df_group.iterrows():
                m_key = row['matchup']
                seen_counts[m_key] = seen_counts.get(m_key, 0) + 1
                
                if lg == "Euroleague":
                    # In Euroleague:
                    # Best of 5 series have matchup_counts >= 3
                    # Play-In and Final 4 have matchup_counts == 1
                    if matchup_counts[m_key] == 1:
                        if i < (total_games / 2): # Early season 1-game series = Play In
                            if i < 2:
                                round_label = "Play-In Round 1"
                            else:
                                round_label = "Play-In Round 2"
                        else: # Late season 1-game series = Final 4
                            round_label = "Final 4"
                    else:
                        round_label = f"Playoffs Game {seen_counts[m_key]}"
                else:
                    # ACB / Others Fallback
                    if matchup_counts[m_key] == 1:
                        round_label = "Single Game"
                    else:
                        round_label = f"Playoffs Game {seen_counts[m_key]}"

                final_data.append(extract_game_details(row, lg, sn, ph_orig, gp, round_label))

        else:
            # --- REGULAR SEASON LOGIC (ID-based) ---
            base_id = df_group['game_id'].min()
            games_per_rnd = LEAGUE_CONFIG.get(lg, {}).get("games_per_round", 9)

            for _, row in df_group.iterrows():
                rnd_num = ((row['game_id'] - base_id) // games_per_rnd) + 1
                round_label = f"Round {int(rnd_num):02d}"
                final_data.append(extract_game_details(row, lg, sn, ph_orig, gp, round_label))

    with open("game_index.json", "w") as f:
        json.dump(final_data, f, indent=4)
    print(f"--- [INDEXING COMPLETE: {len(final_data)} games saved] ---\n")
def extract_game_details(row, lg, sn, ph_orig, gp, round_label):
    """Helper to read the actual scores from the file for the final index."""
    try:
        df = pd.read_excel(row['path'], header=None)
        mask = df[0].astype(str).str.upper().str.strip().str.startswith("TOTAL")
        total_rows = df[mask]
        
        t1_pts = int(clean_num(total_rows.iloc[0, 1]))
        t2_pts = int(clean_num(total_rows.iloc[1, 1]))
        
        # UI Naming Logic
        clean_ph = ph_orig.replace("_", " ")
        display_phase = f"{clean_ph} - {gp}" if gp != "Main" else clean_ph

        return {
            "league": lg, "season": sn, "phase": display_phase,
            "round": round_label, "t1": row['t1'], "t2": row['t2'],
            "pts1": t1_pts, "pts2": t2_pts, "path": row['path']
        }
    except:
        return None
@st.cache_data
def get_league_benchmarks(league, season): # Added season param
    # Walk ONLY the specific league/season folder
    target_path = os.path.join(DATA_BASE_PATH, league, season)
    all_aggregate_files = []
    
    for root, dirs, filenames in os.walk(target_path):
        if os.path.basename(root) == "aggregate":
            for f in filenames:
                if f.startswith('AGGREGATE_'): 
                    all_aggregate_files.append(os.path.join(root, f))
    total_stats = {"pts": 0, "poss": 0, "f2m": 0, "f2a": 0, "f3m": 0, "f3a": 0, "ftm": 0, "fta": 0, "orb": 0, "drb": 0, "tov": 0, "gp": 0,"pts_off_to": 0, "pts_2nd_ch": 0, "pts_fb": 0}
    for f in all_aggregate_files:
        try:
            df = pd.read_excel(f, header=None)
            row_t = df[df[0] == "TOTAL"].iloc[0]
            total_stats["gp"] += clean_num(row_t[1]); total_stats["pts"] += clean_num(row_t[2])
            total_stats["f2m"] += clean_num(row_t[3]); total_stats["f2a"] += clean_num(row_t[4])
            total_stats["f3m"] += clean_num(row_t[5]); total_stats["f3a"] += clean_num(row_t[6])
            total_stats["ftm"] += clean_num(row_t[7]); total_stats["fta"] += clean_num(row_t[8])
            total_stats["drb"] += clean_num(row_t[10]); total_stats["orb"] += clean_num(row_t[11])
            total_stats["tov"] += clean_num(row_t[15]); total_stats["poss"] += clean_num(df.iloc[1][2])
            # EXTRACT SITUATIONAL DATA (Using Aggregate Indices: 22, 23, 24)
            total_stats["pts_off_to"] += clean_num(row_t[20])
            total_stats["pts_2nd_ch"] += clean_num(row_t[21])
            total_stats["pts_fb"] += clean_num(row_t[22]) 
        except: continue
    lg_effic = total_stats["pts"] / total_stats["poss"] if total_stats["poss"] > 0 else 1.13
    lg_orb_pct = total_stats["orb"] / (total_stats["orb"] + total_stats["drb"]) if (total_stats["orb"] + total_stats["drb"]) > 0 else 0.30
    lg_games = total_stats["gp"] if total_stats["gp"] > 0 else 1
    lg_data = {k: v / lg_games for k, v in total_stats.items() if k not in["gp", "poss"]}
    return lg_effic, lg_orb_pct, lg_data
def calc_raw_factors(data, opp_drb, lg_effic, lg_orb_pct):
    fg_pts = data['pts'] - data['ftm']
    fgm = data['f2m'] + data['f3m']
    fga = data['f2a'] + data['f3a']
    fgx = fga - fgm
    shooting = fg_pts - (fgm * lg_effic) - ((1 - lg_orb_pct) * fgx * lg_effic)
    turnovers = -lg_effic * data['tov']
    rebounding = ((1 - lg_orb_pct) * data['orb'] - (lg_orb_pct * opp_drb)) * lg_effic
    free_throws = data['ftm'] - (0.4 * data['fta'] * lg_effic) + (0.06 * (data['fta'] - data['ftm']) * lg_effic)
    return {"Shooting": shooting, "Turnovers": turnovers, "Rebounding": rebounding, "Free Throws": free_throws}
def plot_4f_comparison(data_l, data_r, team_l, team_r, is_pdf=False):
    labels =["Shooting", "Rebounding", "Turnovers", "Free Throws"]
    vals_l, vals_r = [data_l[k] for k in labels], [data_r[k] for k in labels]
    
    fig = go.Figure()
    
    fig.add_trace(go.Bar(
        y=labels, x=vals_l, orientation='h', name=team_l, 
        marker_color="#1e2130", text=[f"{v:+.1f}" for v in vals_l], 
        textposition='auto', insidetextfont=dict(color='white', size=11),
        cliponaxis=False
    ))
    
    fig.add_trace(go.Bar(
        y=labels, x=vals_r, orientation='h', name=team_r, 
        marker_color="#FF0000", text=[f"{v:+.1f}" for v in vals_r], 
        textposition='auto', insidetextfont=dict(color='white', size=11),
        cliponaxis=False
    ))
    
    # --- FIXED RANGE LOGIC ---
    all_vals = vals_l + vals_r
    x_min = min(all_vals)
    x_max = max(all_vals)
    
    # Force the axis to always show at least from -1 to +1 around zero 
    # so the 0-line is never on the very edge.
    range_min = min(x_min * 1.2 if x_min < 0 else x_min - 1, -1.0)
    range_max = max(x_max * 1.2 if x_max > 0 else x_max + 1, 1.0)
    
    fig.update_layout(
        barmode='group', 
        height=400, 
        # l=150 for labels, r=180 for a HUGE safety buffer on the right
        margin=dict(l=150, r=180, t=40, b=40), 
        xaxis=dict(
            # Keep your existing range logic here
            showgrid=True, gridcolor='#E5E7E9', griddash='dot',
            zeroline=True, zerolinecolor='#34495e', zerolinewidth=1.5
        ),
        yaxis=dict(autorange="reversed", showgrid=False, automargin=True),
        # x=0.8 pushes the legend further left, away from the paper edge
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=0.8),
        plot_bgcolor='white'
    )
    return fig

def plot_situational_comparison(t1_stats, t2_stats, t1_name, t2_name, lg_stats):
    labels = ["Pts off TO", "2nd Chance Pts", "Fast Break Pts"]
    
    # Helper to ensure we have numbers
    def safe_get(d, key):
        try:
            val = d.get(key, 0)
            return float(val) if val is not None else 0.0
        except:
            return 0.0

    vals_t1 = [safe_get(t1_stats, "pts_off_to"), safe_get(t1_stats, "pts_2nd_ch"), safe_get(t1_stats, "pts_fb")]
    vals_t2 = [safe_get(t2_stats, "pts_off_to"), safe_get(t2_stats, "pts_2nd_ch"), safe_get(t2_stats, "pts_fb")]
    
    is_empty = (sum(vals_t1) + sum(vals_t2)) == 0

    fig = go.Figure()

    fig.add_trace(go.Bar(
        y=labels, 
        x=vals_t1, 
        orientation='h', 
        name=t1_name, 
        marker_color='#1e2130', 
        text=[f"{v:.1f}" for v in vals_t1], 
        textposition='outside', 
        cliponaxis=False
    ))

    fig.add_trace(go.Bar(
        y=labels, 
        x=vals_t2, 
        orientation='h', 
        name=t2_name, 
        marker_color="#F00000", 
        text=[f"{v:.1f}" for v in vals_t2], 
        textposition='outside', 
        cliponaxis=False
    ))
    
    if not is_empty:
        avg_vals = [safe_get(lg_stats, "pts_off_to"), safe_get(lg_stats, "pts_2nd_ch"), safe_get(lg_stats, "pts_fb")]
        for i, avg in enumerate(avg_vals):
            fig.add_shape(type="line", x0=avg, x1=avg, y0=i-0.4, y1=i+0.4,
                          line=dict(color="Gray", width=2, dash="dash"))

    if is_empty:
        fig.add_annotation(
            x=0.5, y=0.5, xref="paper", yref="paper",
            text="NO POINTS RECORDED IN THESE CATEGORIES",
            showarrow=False, font=dict(size=14, color="gray")
        )

    # --- DYNAMIC RANGE ---
    max_val = max(max(vals_t1 + vals_t2 + [10]), 15)
    x_range_max = max_val * 1.15

    fig.update_layout(
        barmode='group', 
        height=400, 
        # l=150 for labels, r=180 for a HUGE safety buffer on the right
        margin=dict(l=150, r=180, t=40, b=40), 
        xaxis=dict(
            # Keep your existing range logic here
            showgrid=True, gridcolor='#E5E7E9', griddash='dot',
            zeroline=True, zerolinecolor='#34495e', zerolinewidth=1.5
        ),
        yaxis=dict(autorange="reversed", showgrid=False, automargin=True),
        # x=0.8 pushes the legend further left, away from the paper edge
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=0.8),
        plot_bgcolor='white'
    )

    return fig

# --- MAIN APP ----
# --- CUSTOM THEMING (THE ULTIMATE VERSION) ---
st.markdown("""
    <style>
            
        /* 1. REDUCE GAP BETWEEN ALL SIDEBAR ELEMENTS */
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
            gap: 0.5rem !important; 
        }

        /* 2. TIGHTEN THE SPACE BETWEEN LABELS AND THE SELECT BOXES */
        [data-testid="stSidebar"] label {
            margin-bottom: -5px !important;
            font-size: 0.9rem !important;
        }

        /* 3. REDUCE THE PADDING OF THE HORIZONTAL LINE (---) */
        [data-testid="stSidebar"] hr {
            margin-top: 0.5rem !important;
            margin-bottom: 0.5rem !important;
        }

        /* 4. SHRINK THE SIDEBAR TITLE SPACING */
        [data-testid="stSidebar"] h1 {
            margin-top: -1rem !important;
            margin-bottom: 0rem !important;
            font-size: 1.5rem !important;
        }
                /* 5. MAIN PAGE COMPRESSION */
        /* Reduce the gap between all elements on the main page */
        [data-testid="stAppViewContainer"] [data-testid="stVerticalBlock"] {
            gap: 0.8rem !important; 
        }

        /* Tighten spacing for all headers (H1, H2, H3, H4) */
        [data-testid="stAppViewContainer"] h1, 
        [data-testid="stAppViewContainer"] h2, 
        [data-testid="stAppViewContainer"] h3, 
        [data-testid="stAppViewContainer"] h4 {
            margin-top: 0.5rem !important;
            margin-bottom: 0.2rem !important;
        }

        /* Reduce the padding inside the "st.container(border=True)" boxes */
        [data-testid="stVerticalBlockBorderWrapper"] {
            padding-top: 0.5rem !important;
            padding-bottom: 0.5rem !important;
        }

        /* Tighten the space for st.metric cards */
        [data-testid="stMetric"] {
            padding: 0.5rem 0rem !important;
        }
        
        /* Remove the massive top padding that Streamlit adds to the page */
        .block-container {
            padding-top: 2rem !important;
            padding-bottom: 0rem !important;
        }

        /* 1. Sidebar Base & Main Vertical Spacing */
        [data-testid="stSidebar"] {
            background-color: #1e2130 !important;
        }
        [data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
            gap: 1rem !important; 
            padding-top: 1.5rem !important;
        }

        /* 2. Global Text & Paragraph Reset */
        [data-testid="stSidebar"] * {
            color: #ffffff !important;
        }
        [data-testid="stSidebar"] p {
            margin-bottom: 0.2rem !important;
        }

        /* 3. FIX LABEL SPACING (Main titles) */
        [data-testid="stSidebar"] label {
            margin-bottom: 4px !important;
            font-weight: 600 !important;
            display: flex;
        }

        /* 4. Info Box (Explanation) - Subtle Red Accent */
        [data-testid="stSidebar"] .stAlert {
            background-color: rgba(255, 255, 255, 0.05) !important;
            border: 1px solid #3f445e !important;
            border-left: 5px solid #FF4B4B !important;
        }
        [data-testid="stSidebar"] .stAlert p {
            color: #cbd5e1 !important;
            font-weight: normal !important;
            font-size: 0.85rem !important;
        }

        /* 5. FIX BENCHMARK SECTION (Tighten specifically) */
        [data-testid="stSidebar"] [data-testid="stHorizontalBlock"] {
            gap: 0.5rem !important;
        }
        [data-testid="stSidebar"] [data-testid="stCaptionContainer"] {
            margin-top: -8px !important;
            opacity: 0.8;
        }

        /* 6. SELECTBOXES & MULTISELECT */
        [data-testid="stSidebar"] .stMultiSelect div[data-baseweb="select"] > div,
        [data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div {
            background-color: #2d324a !important;
            border: 1px solid #3f445e !important;
        }
        [data-testid="stSidebar"] div[data-baseweb="select"] * {
            color: #ffffff !important;
        }
        span[data-baseweb="tag"] {
            background-color: #FF4B4B !important;
            color: white !important;
        }

        /* 7. BENCHMARK CHIPS */
        [data-testid="stSidebar"] code {
            background-color: #2d324a !important;
            color: #ffffff !important;
            border: 1px solid #3f445e !important;
            padding: 1px 4px !important;
        }

        /* 8. SLIDER FIXES (Red Bar) */
        [data-testid="stSidebar"] [data-baseweb="slider"] div[role="slider"] {
            background-color: #FF4B4B !important;
            border: 2px solid #ffffff !important;
        }
        [data-testid="stSidebar"] [data-baseweb="slider"] div[role="presentation"] > div:first-child > div {
            background: #FF4B4B !important;
        }
        [data-testid="stSidebar"] [data-testid="stTickBarMin"], 
        [data-testid="stSidebar"] [data-testid="stTickBarMax"],
        [data-testid="stSidebar"] [data-baseweb="slider"] + div div {
            background-color: transparent !important;
        }

        /* 9. REFRESH BUTTON */
        [data-testid="stSidebar"] button {
            background-color: #2d324a !important;
            border: 1px solid #FF4B4B !important;
        }
        [data-testid="stSidebar"] button:hover {
            background-color: #FF4B4B !important;
        }

        /* 10. LOGO CARD & HORIZONTAL RULE */
        [data-testid="stSidebar"] [data-testid="stImage"] {
            background-color: #ffffff !important;
            padding: 8px !important;
            border-radius: 8px !important;
        }
        /* 11. FIX EXPANDER TO LOOK LIKE SELECTBOX */
        [data-testid="stSidebar"] [data-testid="stExpander"] {
            background-color: #2d324a !important; /* Match Selectbox Background */
            border: 1px solid #3f445e !important; /* Match Selectbox Border */
            border-radius: 4px !important;
        }

        /* Header (The clickable bar) */
        [data-testid="stSidebar"] [data-testid="stExpander"] summary {
            padding: 5px 10px !important; /* Shrink to match selectbox height */
        }

        /* Hover states for the header */
        [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
            background-color: #3f445e !important; /* Slightly lighter on hover */
        }

        [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover p,
        [data-testid="stSidebar"] [data-testid="stExpander"] summary:hover span {
            color: #ffffff !important;
        }

        /* The Chevron icon */
        [data-testid="stSidebar"] [data-testid="stExpander"] summary svg {
            fill: #ffffff !important;
        }

        /* 12. EXPANDER CONTENT AREA (When open) */
        [data-testid="stSidebar"] [data-testid="stExpander"] details[open] summary {
            border-bottom: 1px solid #3f445e !important; /* Line between header and content */
            border-radius: 4px 4px 0 0 !important;
        }

        [data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stVerticalBlock"] {
            background-color: #1e2130 !important; /* Darker inside the drawer */
            padding: 12px !important;
            gap: 0.5rem !important;
        }

        /* Internal Multiselect Scrollbar - Prevent the tags from pushing the sidebar down */
        [data-testid="stSidebar"] [data-testid="stExpander"] .stMultiSelect div[data-baseweb="select"] > div:first-child {
            max-height: 120px !important;
            overflow-y: auto !important;
        }
        
        /* Remove the inner border Streamlit adds to the content */
        [data-testid="stSidebar"] [data-testid="stExpander"] > div:last-child {
            border: none !important;
        }
    </style>
""", unsafe_allow_html=True)
st.set_page_config(page_title="4Factors Net Points", layout="wide")
if not os.path.exists("game_index.json"): build_game_index()
@st.cache_data
def load_index(): return pd.read_json("game_index.json") if os.path.exists("game_index.json") else pd.DataFrame()
df_index = load_index()

# --- 1. GLOBAL SETUP ---
# Slim version: Only the essential selectors
league = st.sidebar.selectbox("League", sorted(df_index['league'].unique()), key="league_select")

# Season depends on League
df_league = df_index[df_index['league'] == league]
season = st.sidebar.selectbox("Season", sorted(df_league['season'].unique(), reverse=True), key="season_sel")

st.sidebar.markdown("---")
# --- 2. NAVIGATION ---
st.sidebar.title("Scouting 4F")
mode = st.sidebar.radio(
    "View Mode", 
    ["Home", "Season Aggregates per Team", "Head to Head Matchup", "Games Boxscores", "Team Performance by Game", "Overall League Standings"], 
    key="mode_radio"
)
analysis_type = st.sidebar.selectbox("Analysis Category", ["4-Factors Net Points", "4-Factors Classic "], key="analysis_type")

# --- 3. THE MATH (Invisible - no st. calls here) ---
# These calculations MUST happen before the "if mode == ..." blocks
t1_off, t2_off = None, None
i1_tot, i2_tot, i1_raw, i2_raw, t1, t2, header_title = None, None, None, None, "", "", ""

lg_effic, lg_orb_pct, lg_data = get_league_benchmarks(league, season)
lg_fga = lg_data['f2a'] + lg_data['f3a']
lg_fgm = lg_data['f2m'] + lg_data['f3m']
avg_efg = (lg_fgm + 0.5 * lg_data['f3m']) / lg_fga if lg_fga > 0 else 0.52
avg_to = lg_data['tov'] / (lg_fga + 0.44 * lg_data['fta'] + lg_data['tov']) if (lg_fga + 0.44 * lg_data['fta'] + lg_data['tov']) > 0 else 0.16
avg_ftr = lg_data['ftm'] / lg_fga if lg_fga > 0 else 0.25
avg_orb = lg_orb_pct

st.sidebar.markdown("---")
if mode == "Home":
    st.markdown(f"""
        <div style="text-align: center; padding: 40px 0px;">
            <h1 style="font-size: 3.5rem; margin-bottom: 10px;">Basketball 4-Factors Scouting</h1>
            <p style="font-size: 1.2rem; color: #666;">Advanced Analytics & Situational Performance Tool</p>
        </div>
    """, unsafe_allow_html=True)

    # Centered Logo
    col_l1, col_l2, col_l3 = st.columns([1, 2, 1])
    with col_l2:
        config = LEAGUE_CONFIG.get(league, {})
        logo_filename = config.get("logo", "FEB.png")
        logo_path = os.path.join(LOGOS_PATH, logo_filename)
        if os.path.exists(logo_path):
            # REMOVE use_container_width=True and use a fixed width (e.g., 250)
            # You can also use st.markdown with HTML for even more control
            st.markdown(
                f'<div style="display: flex; justify-content: center;"><img src="data:image/png;base64,{base64.b64encode(open(logo_path, "rb").read()).decode()}" width="250"></div>', 
                unsafe_allow_html=True
            )
    
    c1, c2 = st.columns(2)
    with c1:
        st.markdown("### Get Started")
        st.info("""
        1. **Select a League** and **Season** in the sidebar.
        2. **Choose a View Mode**:
            * **Season Aggregate**: Compare a team against the averages in the league.
            * **Head to Head Matchup**: Directly compare two teams.
            * **Game Boxscore**: Deep dive into a specific past game.
            * **Team Performance**: Track a team's trends round-by-round.
            * **League Standings**: See the full league heatmap.
        """)
        
    with c2:
        st.markdown("### Analysis Categories")
        st.success("""
        * **4-Factors Net Points**: Measures the impact of Shooting, Turnovers, Rebounding, and FTs in terms of point difference relative to average.
        * **Situational Points**: Traditional 4-Factor percentages (eFG%, TO%, etc.) and situational scoring (Fast Break, 2nd Chance).
        * **Individual Stats**: follow each player's impact in the game.
        """)

    # Stop execution here so the Matchup/Display logic doesn't run
    st.stop()
# --- 4. SYSTEM UTILITIES (Tucked away at the bottom) ---
with st.sidebar.expander("System & Benchmarks", expanded=False):
    if st.button("Refresh Data Index"):
        build_game_index()
        st.cache_data.clear()
        st.rerun()
    
    st.markdown("---")
    st.markdown("**League Benchmarks**")
    col_lg1, col_lg2 = st.columns(2)
    with col_lg1:
        st.markdown(f"**Effic:** `{lg_effic:.2f}`")
    with col_lg2:
        st.markdown(f"**OR%:** `{lg_orb_pct:.1%}`")
    
    st.markdown("---")
    with st.expander("Glossary"):
        st.info(
            "**Lg. Effic:** Pts per possession.\n\n"
            "**Lg. OR%:** % of available offensive rebounds grabbed.\n\n"
            "**2nd Chance Pts:** Pts scored after offensive rebound.\n\n"
            "**Pts off TO:** Pts scored after opponent turnover.\n\n"
            "**Fast Break Pts:** Pts scored on a fast break."
        )

# --- NEW LOGIC FOR TEAM VS LEAGUE ---
if mode == "Season Aggregates per Team":
    teams = get_teams_in_league(league, season)
    t1 = st.sidebar.selectbox("Select Team", teams, index=0, key="t1_agg")
    # We get the max games from the team stats so the slider range is dynamic
    t1_off = get_per_game_volumes(t1, league, season, "TOTAL")
    max_gp_possible = int(t1_off.get('gp', 1))
    t2 = "League Average"
    
    t1_def = get_per_game_volumes(t1, league, season, "Rival")
    t2_off, t2_def = lg_data.copy(), lg_data.copy()
    
    lg_raw = calc_raw_factors(lg_data, lg_data['drb'], lg_effic, lg_orb_pct)
    t1_off_raw = calc_raw_factors(t1_off, t1_def['drb'], lg_effic, lg_orb_pct)
    t1_def_raw = calc_raw_factors(t1_def, t1_off['drb'], lg_effic, lg_orb_pct)
    
    # Calculate Net vs League (These are already averages)
    i1_tot = {k: (t1_off_raw[k] - lg_raw[k]) + (lg_raw[k] - t1_def_raw[k]) for k in lg_raw}
    i2_tot = {k: 0.0 for k in lg_raw}
    i1_raw, i2_raw = (t1_off_raw, t1_def_raw), (lg_raw, lg_raw)
    
    header_title = f"Team Profile: {t1}"
    pass

# --- 2. MODE: HEAD TO HEAD MATCHUP (Team A vs Team B Sum) ---
elif mode == "Head to Head Matchup":
    teams = get_teams_in_league(league, season)
    t1 = st.sidebar.selectbox("Home Team", teams, index=0, key="t1_h2h")
    t2 = st.sidebar.selectbox("Away Team", teams, index=min(1, len(teams)-1), key="t2_h2h")
    # 1. PEFORM THE INDEX CHECK FIRST
    # We call get_h2h_stats, but we need to know if it actually found games
    t1_sum, t2_sum = get_h2h_stats(t1, t2, league, season)
    n_games = t1_sum.get('gp', 0) # Use 0 as default if not found


    # --- THE GLOBAL WARNING ---
    if n_games == 0:
        st.markdown("---")
        st.info(f"**No Matchups Found:** {t1} and {t2} have not played against each other in the {season} {league} season.")
        
        # Helper to show available rivals
        def get_sig_words(text):
            s = normalize_str(text)
            return {w for w in s.split() if len(w) > 2}
        
        target_words = get_sig_words(t1)
        mask_ls = (df_index['league'] == league) & (df_index['season'] == season)
        df_ls = df_index[mask_ls]
        t1_games = df_ls[df_ls.apply(lambda r: len(target_words & get_sig_words(r['t1'])) > 0 or len(target_words & get_sig_words(r['t2'])) > 0, axis=1)]
        
        if not t1_games.empty:
            rivals = sorted(list((set(t1_games['t1']) | set(t1_games['t2'])) - {t1}))
            st.write(f"**Available H2H rivals for {t1}:**")
            st.caption(", ".join(rivals))
        
        st.stop() # This stops the rest of the page from loading empty charts
    # --- END WARNING ---
    # 1. Get the TOTAL SUMS for the 2 games
    t1_sum, t2_sum = get_h2h_stats(t1, t2, league, season)
    n_games = t1_sum.get('gp', 1) or 1

    # 2. Calculate the "Impact vs League" for each team (Per Game)
    # We divide by n_games immediately to get the per-game offensive impact
    lg_raw_one = calc_raw_factors(lg_data, lg_data['drb'], lg_effic, lg_orb_pct)
    
    t1_off_vs_lg = {k: (calc_raw_factors(t1_sum, t2_sum['drb'], lg_effic, lg_orb_pct)[k] / n_games) - lg_raw_one[k] for k in lg_raw_one}
    t2_off_vs_lg = {k: (calc_raw_factors(t2_sum, t1_sum['drb'], lg_effic, lg_orb_pct)[k] / n_games) - lg_raw_one[k] for k in lg_raw_one}
    
    # 3. THE MASTER SYNC: Calculate Team 1 vs Team 2
    # In H2H, your Net is (Your Offense vs League) - (Their Offense vs League)
    # This ensures that if BAXI is -30.95, Barça MUST be +30.95.
    i1_tot = {k: t1_off_vs_lg[k] - t2_off_vs_lg[k] for k in t1_off_vs_lg}
    i2_tot = {k: t2_off_vs_lg[k] - t1_off_vs_lg[k] for k in t1_off_vs_lg}

    # 4. Variables for the rest of the script
    t1_h2h_avg = {k: v / n_games for k, v in t1_sum.items() if k != 'gp'}
    t2_h2h_avg = {k: v / n_games for k, v in t2_sum.items() if k != 'gp'}
    
    # We pass the AVERAGE to t1_off so the player table "Total" column shows the Average
    t1_off, t2_off = t1_h2h_avg, t2_h2h_avg 
    i1_raw, i2_raw = (i1_tot, i1_tot), (i2_tot, i2_tot)
    header_title = f"H2H Profile: {t1} vs {t2} (Average per Game)"

elif mode == "Team Performance by Game":
    view_type = "Net Impact" 

    # 1. SIDEBAR SELECTIONS
    phases_avail = sorted(df_league['phase'].unique())
    sel_phase = st.sidebar.selectbox("Select Phase", phases_avail, key="perf_phase_sel")
    
    df_phase_indexed = df_league[df_league['phase'] == sel_phase]
    teams_in_phase = sorted(list(set(df_phase_indexed['t1'].unique()) | set(df_phase_indexed['t2'].unique())))
    
    if not teams_in_phase:
        st.sidebar.warning("No teams found for this phase.")
        st.stop()
        
    target_team = st.sidebar.selectbox("Select Team", teams_in_phase, key="perf_team_sel")

    # 2. DATA PREPARATION
    df_team = df_league[(df_league['season'] == season) & (df_league['phase'] == sel_phase) & 
                        ((df_league['t1'] == target_team) | (df_league['t2'] == target_team))].copy()
    
    if df_team.empty:
        st.error("No games found for this team in the selected phase.")
        st.stop()

    df_team['is_win'] = df_team.apply(lambda x: (x['pts1'] > x['pts2'] if x['t1'] == target_team else x['pts2'] > x['pts1']), axis=1)
    df_team['venue'] = df_team.apply(lambda x: "Home" if x['t1'] == target_team else "Away", axis=1)
    df_team['opponent'] = df_team.apply(lambda x: x['t2'] if x['t1'] == target_team else x['t1'], axis=1)

    all_opponents = sorted(list(set(df_team['opponent'].unique())))

    # --- RESET LOGIC ---
    current_context = f"{league}_{season}_{sel_phase}_{target_team}"
    if st.session_state.get("last_context") != current_context:
        st.session_state["perf_res_choice"] = ["Win", "Loss"]
        st.session_state["perf_venue_choice"] = ["Home", "Away"]
        if "perf_range_rnds" in st.session_state: del st.session_state["perf_range_rnds"]
        st.session_state["last_context"] = current_context
        st.rerun()

    # 3. HEADER DISPLAY
    st.markdown("---")
    perf_header_col1, perf_header_col2 = st.columns([1, 5])
    with perf_header_col1:
        team_logo = get_team_icon(target_team, league)
        if team_logo:
            st.image(team_logo, width=120)
    with perf_header_col2:
        st.markdown(f'<h2 style="margin: 0; font-size: 1.6rem; line-height: 1.2; color: #1e2130;">Scouting Report: {target_team}</h2>', unsafe_allow_html=True)
        st.markdown(f"### {analysis_type}")
        st.markdown(f"**{sel_phase}**")
        st.caption(f"Season: {season}")

    # 4. MAIN PAGE FILTERS
    with st.expander("Filter Games", expanded=True):
        f_col1, f_col2 = st.columns(2)
        with f_col1:
            res_choice = st.multiselect("Game Result", ["Win", "Loss"], default=["Win", "Loss"], key="perf_res_choice")
        with f_col2:
            venue_choice = st.multiselect("Venue", ["Home", "Away"], default=["Home", "Away"], key="perf_venue_choice")
        
        all_rnds = sorted(df_team['round'].unique())
        range_rnds = st.select_slider("Round Range", options=all_rnds, value=(all_rnds[0], all_rnds[-1]), key="perf_range_rnds")
        
        with st.expander("Refine Rivals", expanded=False):
            select_all = st.checkbox("All Rivals", value=True, key="sel_all_rivals")
            if select_all:
                rival_choice = st.multiselect("Specific Rivals:", all_opponents, default=all_opponents, key="perf_rival_choice")
            else:
                rival_choice = st.multiselect("Specific Rivals:", all_opponents, key="perf_rival_choice")
    st.markdown("---")

    # 5. FILTERING LOGIC
    allowed_wins = [True if r == "Win" else False for r in res_choice]
    start_idx = all_rnds.index(range_rnds[0])
    end_idx = all_rnds.index(range_rnds[1])
    allowed_range = all_rnds[start_idx : end_idx+1]

    df_filtered = df_team[
        (df_team['is_win'].isin(allowed_wins)) & 
        (df_team['venue'].isin(venue_choice)) & 
        (df_team['round'].isin(allowed_range)) &
        (df_team['opponent'].isin(rival_choice))
    ].copy()

    if df_filtered.empty:
        st.error("No games match this filter combination.")
        st.stop()

    # --- TAB SYSTEM ---
    tab_team_view, tab_player_view = st.tabs(["Team Performance", "Player Performance"])

    with tab_team_view:
        view_type = st.radio("Analysis Perspective", ["Net Impact", "Offensive Impact", "Defensive Impact"], horizontal=True, key="perf_view_type_team")
        
        performance_data = []
        for _, row in df_filtered.sort_values('round').iterrows():
            g = get_raw_game_data_custom(row['path'])
            if not g: continue
            is_t1 = row['t1'] == target_team
            stats_self, stats_opp = (g['t1_stats'], g['t2_stats']) if is_t1 else (g['t2_stats'], g['t1_stats'])
            opp_name = row['opponent']
            self_score = row['pts1'] if is_t1 else row['pts2']
            opp_score = row['pts2'] if is_t1 else row['pts1']
            
            entry = {"Round": row['round'], "Opp_Logo": get_team_icon(opp_name, league), "Matchup": f"{'W' if row['is_win'] else 'L'} {'(H)' if row['venue']=='Home' else '(A)'} {self_score}-{opp_score} vs {opp_name}", "Outcome": "W" if row['is_win'] else "L"}
            f_off = calc_raw_factors(stats_self, stats_opp['drb'], lg_effic, lg_orb_pct)
            f_def = calc_raw_factors(stats_opp, stats_self['drb'], lg_effic, lg_orb_pct)
            f_def_inv = {k: -v for k, v in f_def.items()} 
            for f in ["Shooting", "Rebounding", "Turnovers", "Free Throws"]:
                entry[f"{f}_Net"] = f_off[f] + f_def_inv[f]
                entry[f"{f}_Off"] = f_off[f]
                entry[f"{f}_Def"] = f_def_inv[f]

            if analysis_type == "4-Factors Net Points":
                display_vals = f_off if view_type == "Offensive Impact" else (f_def_inv if view_type == "Defensive Impact" else {k: f_off[k] + f_def_inv[k] for k in f_off})
                entry.update({"Shooting": display_vals['Shooting'], "Turnovers": display_vals['Turnovers'], "Rebounding": display_vals['Rebounding'], "Free Throws": display_vals['Free Throws'], "Total 4F": sum(display_vals.values())})
            else:
                p_self = get_4f_percentages(stats_self, stats_opp)
                p_opp = get_4f_percentages(stats_opp, stats_self)
                if view_type == "Offensive Impact":
                    entry.update({"Pts off TO": stats_self['pts_off_to'], "2nd Chance": stats_self['pts_2nd_ch'], "Fast Break": stats_self['pts_fb']})
                    entry.update(p_self)
                elif view_type == "Defensive Impact":
                    entry.update({"Pts off TO": stats_opp['pts_off_to'], "2nd Chance": stats_opp['pts_2nd_ch'], "Fast Break": stats_opp['pts_fb']})
                    entry.update(p_opp)
                else:
                    entry.update({"Pts off TO": stats_self['pts_off_to'] - stats_opp['pts_off_to'], "2nd Chance": stats_self['pts_2nd_ch'] - stats_opp['pts_2nd_ch'], "Fast Break": stats_self['pts_fb'] - stats_opp['pts_fb']})
                    p_net = {k: p_self[k] - p_opp[k] for k in p_self}
                    entry.update(p_net)
            performance_data.append(entry)

        perf_df = pd.DataFrame(performance_data)
        
        c_s, c_r, c_t, c_f = st.columns(4)
        if analysis_type == "4-Factors Net Points":
            for f_n, col in zip(["Shooting", "Rebounding", "Turnovers", "Free Throws"], [c_s, c_r, c_t, c_f]):
                with col:
                    st.markdown(f"#### {f_n}")
                    st.markdown(f"**Net: {perf_df[f_n+'_Net'].mean():+.2f}**")
                    st.caption(f"O: {perf_df[f_n+'_Off'].mean():+.2f} | D: {perf_df[f_n+'_Def'].mean():+.2f}")
        else:
            sit_labels = ["Pts off TO", "2nd Chance", "Fast Break", "GP"]
            sit_cols = ["Pts off TO", "2nd Chance", "Fast Break", "Round"]
            for label, col_name, col_ui in zip(sit_labels, sit_cols, [c_s, c_r, c_t, c_f]):
                with col_ui:
                    st.markdown(f"#### {label}")
                    if label == "GP": st.markdown(f"**{len(perf_df)} Games**")
                    else:
                        avg_val = perf_df[col_name].mean()
                        fmt = "{:+.2f}" if view_type == "Net Impact" else "{:.2f}"
                        st.markdown(f"**Avg: {fmt.format(avg_val)}**")

        if analysis_type == "4-Factors Net Points":
            cols_visible = ["Round", "Opp_Logo", "Matchup", "Shooting", "Turnovers", "Rebounding", "Free Throws", "Total 4F"]
            format_dict = {k: "{:+.2f}" for k in ["Shooting", "Turnovers", "Rebounding", "Free Throws", "Total 4F"]}
            grad_cols = ["Shooting", "Turnovers", "Rebounding", "Free Throws", "Total 4F"]
        else:
            cols_visible = ["Round", "Opp_Logo", "Matchup", "Pts off TO", "2nd Chance", "Fast Break", "eFG%", "TO%", "ORB%", "FTR"]
            if view_type == "Net Impact":
                format_dict = {k: "{:+.2f}" for k in ["Pts off TO", "2nd Chance", "Fast Break"]}
                format_dict.update({k: "{:+.1%}" for k in ["eFG%", "TO%", "ORB%"]})
                format_dict["FTR"] = "{:+.3f}"
            else:
                format_dict = {k: "{:.2f}" for k in ["Pts off TO", "2nd Chance", "Fast Break"]}
                format_dict.update({k: "{:.1%}" for k in ["eFG%", "TO%", "ORB%"]})
                format_dict["FTR"] = "{:.3f}"
            grad_cols = [c for c in cols_visible if c not in ["Pos", "Team_Logo", "Team"]]

        styler = perf_df.style.format(format_dict).map(lambda x: 'color: #27ae60; font-weight: bold;' if x == "W" else ('color: #c0392b; font-weight: bold;' if x == "L" else ''), subset=['Outcome'])
        if analysis_type == "4-Factors Net Points":
            styler = styler.background_gradient(subset=grad_cols, cmap=custom_rdwgn, vmin=-15, vmax=15)
        else:
            if view_type == "Net Impact":
                styler = styler.background_gradient(subset=['Pts off TO', '2nd Chance', 'Fast Break'], cmap=custom_rdwgn, vmin=-15, vmax=15)
                styler = styler.background_gradient(subset=['eFG%'], cmap=custom_rdwgn, vmin=-0.12, vmax=0.12)
                styler = styler.background_gradient(subset=['ORB%'], cmap=custom_rdwgn, vmin=-0.15, vmax=0.15)
                styler = styler.background_gradient(subset=['FTR'], cmap=custom_rdwgn, vmin=-0.15, vmax=0.15)
                styler = styler.background_gradient(subset=['TO%'], cmap=custom_gnwr, vmin=-0.06, vmax=0.06)
            else:
                styler = styler.background_gradient(subset=['Pts off TO', '2nd Chance', 'Fast Break'], cmap=custom_wgn, vmin=0, vmax=30)
                styler = styler.background_gradient(subset=['eFG%'], cmap=custom_rdwgn, vmin=avg_efg-0.12, vmax=avg_efg+0.12)
                styler = styler.background_gradient(subset=['ORB%'], cmap=custom_rdwgn, vmin=avg_orb-0.15, vmax=avg_orb+0.15)
                styler = styler.background_gradient(subset=['FTR'], cmap=custom_rdwgn, vmin=avg_ftr-0.15, vmax=avg_ftr+0.15)
                styler = styler.background_gradient(subset=['TO%'], cmap=custom_gnwr, vmin=avg_to-0.06, vmax=avg_to+0.06)

        # --- CAREFULLY INDENTED RENDER BLOCK ---
        dynamic_height_team = (len(perf_df) * 36) + 45
        
        col_config_team = {
            "Opp_Logo": st.column_config.ImageColumn("Opp", width="small"), 
            "Round": st.column_config.TextColumn("Rnd", width="small"),
            "Matchup": st.column_config.TextColumn("Matchup", width="medium")
        }
        
        for col in cols_visible:
            if col not in ["Round", "Opp_Logo", "Matchup", "Outcome"]:
                col_config_team[col] = st.column_config.NumberColumn(col, width="small")

        st.dataframe(
            styler, 
            use_container_width=False, 
            hide_index=True, 
            height=dynamic_height_team,
            column_order=cols_visible, 
            column_config=col_config_team
        )

    with tab_player_view:
        # 1. Player List
        if analysis_type == "4-Factors Net Points":
            df_ind_agg = load_individual_aggregate(target_team, league, season, sel_phase)
        else:
            df_ind_agg = load_aggregated_classic_individual_data(target_team, league, season, sel_phase)
            
        if df_ind_agg is None or df_ind_agg.empty:
            st.warning("No individual player data found for this team.")
        else:
            agg_p_col = next((c for c in df_ind_agg.columns if c.upper() == 'PLAYER'), 'Player')
            player_list = sorted(df_ind_agg[agg_p_col].unique().tolist())

            col_sel, col_view = st.columns([1, 3])
            with col_sel:
                selected_player = st.selectbox("Select Player", player_list)
            with col_view:
                if analysis_type == "4-Factors Net Points":
                    player_view_type = st.radio("Analysis Perspective", ["Net Impact", "Offensive Impact", "Defensive Impact"], horizontal=True, key="perf_view_type_player")

            if analysis_type == "4-Factors Net Points":
                col_cb1, col_cb2 = st.columns(2)
                with col_cb1: exp_p_offdef = st.checkbox("Show Offense/Defense Breakdown", value=False, key="cb_offdef_perf_p")
                with col_cb2: exp_p_shoot = st.checkbox("Show 2P/3P Shooting Split", value=False, key="cb_shoot_perf_p")
                prefix = {"Net Impact": "Net_", "Offensive Impact": "Off_", "Defensive Impact": "Def_"}[player_view_type]

            st.markdown("---")

            # 2. DATA LOOP
            player_perf_data = []
            for _, row in df_filtered.sort_values('round').iterrows():
                if analysis_type == "4-Factors Net Points":
                    df_game_ind = load_single_game_individual(row['path'], target_team)
                else:
                    df_game_ind = load_single_game_classic_individual(row['path'], target_team)
                    
                if df_game_ind is not None and not df_game_ind.empty:
                    p_col_in_game = next((c for c in df_game_ind.columns if c.upper() == 'PLAYER'), None)
                    if p_col_in_game:
                        p_row = df_game_ind[df_game_ind[p_col_in_game].str.contains(selected_player, case=False, na=False, regex=False)]
                        if not p_row.empty:
                            p_stats = p_row.iloc[0].to_dict()
                            p_stats['Round'] = row['round']
                            p_stats['Opp_Logo'] = get_team_icon(row['opponent'], league)
                            p_stats['Matchup'] = f"{'W' if row['is_win'] else 'L'} {row['opponent']}"
                            player_perf_data.append(p_stats)

            # 3. RENDER LOGIC (Safely inside the else block)
            if not player_perf_data:
                st.info(f"No records found for {selected_player} in the selected games.")
            else:
                player_df = pd.DataFrame(player_perf_data)

                cols_to_show = ["Round", "Opp_Logo", "Matchup"]
                
                if analysis_type == "4-Factors Net Points":
                    for f in ["Shooting", "TOV", "ORB", "FT"]:
                        target_f = f"{prefix}{f}" if f"{prefix}{f}" in player_df.columns else f
                        if target_f in player_df.columns: cols_to_show.append(target_f)
                    
                    if exp_p_offdef:
                        for f in ["Shooting", "TOV", "ORB", "FT"]:
                            for alt in [f"Net_{f}", f"Off_{f}", f"Def_{f}"]:
                                if alt in player_df.columns and alt not in cols_to_show: cols_to_show.append(alt)
                    
                    if exp_p_shoot:
                        for s in ["Off_2P", "Off_3P", "Def_2P", "Def_3P"]:
                            if s in player_df.columns and s not in cols_to_show: cols_to_show.append(s)
                else:
                    for c in ["PTS", "eFG%", "TO%", "OR/40", "FTR", "Pts_off_TO", "2nd_Chance", "Fast_Break"]:
                        if c in player_df.columns: cols_to_show.append(c)

                cols_to_show = [c for c in cols_to_show if c in player_df.columns]
                numeric_cols = [c for c in cols_to_show if c not in ["Round", "Opp_Logo", "Matchup"]]

                format_dict = {}
                for k in numeric_cols:
                    if '%' in k or k == 'FTR': format_dict[k] = "{:.1%}" if '%' in k else "{:.3f}"
                    elif k in ["PTS", "OR/40", "Pts_off_TO", "2nd_Chance", "Fast_Break"]: format_dict[k] = "{:.2f}"
                    else: format_dict[k] = "{:+.2f}"

                styler_p = player_df[cols_to_show].style.format(format_dict)
                
                for col in numeric_cols:
                    if col in ["PTS", "eFG%", "TO%", "OR/40", "FTR", "Pts_off_TO", "2nd_Chance", "Fast_Break"]:
                        if col == 'TO%': cmap = custom_gnwr
                        elif col in ['PTS', 'OR/40', 'Pts_off_TO', '2nd_Chance', 'Fast_Break']: cmap = custom_wgn
                        else: cmap = custom_rdwgn
                        styler_p = styler_p.background_gradient(subset=[col], cmap=cmap)
                    else:
                        v_max = player_df[col].abs().max() if not player_df[col].empty else 1.0
                        v_max = max(v_max, 1.0)
                        styler_p = styler_p.background_gradient(subset=[col], cmap=custom_rdwgn, vmin=-v_max, vmax=v_max)

                # --- THE MAGIC FIX FOR PLAYER VIEW (Team Performance by Game) ---
                dynamic_height_p = (len(player_df) * 36) + 45
                
                # Base config for text/images
                col_config_p = {
                    "Opp_Logo": st.column_config.ImageColumn("Opp", width="small"),
                    "Round": st.column_config.TextColumn("Round", width="small"),
                    "Matchup": st.column_config.TextColumn("Matchup", width="medium")
                }
                
                # Force all numeric data columns to be compact
                for col in numeric_cols:
                    col_config_p[col] = st.column_config.NumberColumn(col, width="small")

                # Render the compact table
                st.dataframe(
                    styler_p, 
                    use_container_width=False,  # <-- Removes massive gaps
                    hide_index=True, 
                    height=dynamic_height_p,    # <-- Removes scrollbar
                    column_config=col_config_p
                )

elif mode == "Overall League Standings":
    # 1. Phase Selection
    phases_in_index = sorted(df_league['phase'].unique())
    phase_options = ["Overall Season"] + phases_in_index
    selected_phase = st.sidebar.selectbox("Phase / Group", phase_options, key="standings_phase")
    
    st.subheader(f"{league} {season} - {selected_phase}")
    
    # --- UI CONTROLS ON MAIN PAGE ---
    view_type = st.radio("Metric View", ["Net Impact", "Offensive Impact", "Defensive Impact"], horizontal=True)
    st.info("**Note:** This toggle updates the **Team Standings** table. Use the checkboxes inside the **Player Leaderboard** tab to expand individual stats.")
    st.markdown("---")
    
    # --- 2. DEFINE TEAMS TO ANALYZE GLOBALLY FOR BOTH TABS ---
    if selected_phase == "Overall Season":
        teams_to_analyze = sorted(list(set(df_league['t1'].unique()) | set(df_league['t2'].unique())))
    else:
        df_ph = df_league[df_league['phase'] == selected_phase]
        teams_to_analyze = sorted(list(set(df_ph['t1'].unique()) | set(df_ph['t2'].unique())))

    # --- 3. ALWAYS SHOW BOTH TABS ---
    tab_standings_team, tab_standings_players = st.tabs(["Team Standings", "Player Leaderboard"])
    show_player_standings = True

    with tab_standings_team:
        # Calculation of benchmarks (Midpoints)
        lg_fga = lg_data['f2a'] + lg_data['f3a']
        avg_efg = (lg_data['f2m'] + 0.5 * lg_data['f3m']) / lg_fga if lg_fga > 0 else 0.52
        avg_to = lg_data['tov'] / (lg_fga + 0.44 * lg_data['fta'] + lg_data['tov']) if lg_fga > 0 else 0.15
        avg_ftr = lg_data['fta'] / lg_fga if lg_fga > 0 else 0.25
        avg_orb = lg_orb_pct

        league_results = []
        with st.spinner("Calculating team standings..."):
            for team in teams_to_analyze:
                if selected_phase == "Overall Season":
                    t_off = get_per_game_volumes(team, league, season, "TOTAL")
                    t_def = get_per_game_volumes(team, league, season, "Rival")
                else:
                    t_off = get_per_game_volumes_by_phase(team, league, season, selected_phase, "TOTAL")
                    t_def = get_per_game_volumes_by_phase(team, league, season, selected_phase, "Rival")
                
                if t_off['pts'] == 0: continue 

                entry = {"Team_Logo": get_team_icon(team, league), "Team": team}

                if analysis_type == "4-Factors Net Points":
                    lg_raw = calc_raw_factors(lg_data, lg_data['drb'], lg_effic, lg_orb_pct)
                    t_off_raw = calc_raw_factors(t_off, t_def['drb'], lg_effic, lg_orb_pct)
                    t_def_raw = calc_raw_factors(t_def, t_off['drb'], lg_effic, lg_orb_pct)
                    
                    off_i = {k: (t_off_raw[k] - lg_raw[k]) for k in lg_raw}
                    def_i = {k: (lg_raw[k] - t_def_raw[k]) for k in lg_raw}
                    net_i = {k: off_i[k] + def_i[k] for k in lg_raw}
                    
                    disp = off_i if view_type == "Offensive Impact" else (def_i if view_type == "Defensive Impact" else net_i)
                    entry.update({
                        "Net Points": sum(disp.values()),"Shooting": disp['Shooting'], "Turnovers": disp['Turnovers'],
                        "Rebounding": disp['Rebounding'], "Free Throws": disp['Free Throws'] 
                    })
                else:
                    p_off = get_4f_percentages(t_off, t_def)
                    p_def = get_4f_percentages(t_def, t_off)
                    if view_type == "Offensive Impact":
                        entry.update({"Pts off TO": t_off['pts_off_to'], "2nd Chance": t_off['pts_2nd_ch'], "Fast Break": t_off['pts_fb']})
                        entry.update(p_off)
                    elif view_type == "Defensive Impact":
                        entry.update({"Pts off TO": t_def['pts_off_to'], "2nd Chance": t_def['pts_2nd_ch'], "Fast Break": t_def['pts_fb']})
                        entry.update(p_def)
                    else:
                        entry.update({
                            "Pts off TO": t_off['pts_off_to'] - t_def['pts_off_to'],
                            "2nd Chance": t_off['pts_2nd_ch'] - t_def['pts_2nd_ch'],
                            "Fast Break": t_off['pts_fb'] - t_def['pts_fb']
                        })
                        p_net = {k: p_off[k] - p_def[k] for k in p_off}
                        entry.update(p_net)
                league_results.append(entry)

        if not league_results:
            st.error(f"No data found for {selected_phase}")
        else:
            standings_df = pd.DataFrame(league_results)
            
            # 1. DYNAMIC SORT SELECTOR
            if analysis_type == "4-Factors Net Points":
                rank_cols = ["Net Points", "Shooting", "Turnovers", "Rebounding", "Free Throws"]
            else:
                rank_cols = ["eFG%", "Pts off TO", "2nd Chance", "Fast Break", "TO%", "ORB%", "FTR"]
            
            available_ranks = [c for c in rank_cols if c in standings_df.columns]
            
            rank_c1, rank_c2 = st.columns([1, 3])
            with rank_c1:
                chosen_team_rank = st.selectbox("Rank Teams By:", available_ranks, key="team_rank_sel")
            
            # 2. SORT AND ASSIGN POS
            standings_df = standings_df.sort_values(chosen_team_rank, ascending=False).copy()
            standings_df.insert(0, "Pos", range(1, len(standings_df) + 1))

            # 3. DEFINE COLUMNS AND FORMATTING
            if analysis_type == "4-Factors Net Points":
                cols_visible = ["Pos", "Team_Logo", "Team", "Net Points","Shooting", "Turnovers", "Rebounding", "Free Throws"]
                format_dict = {k: "{:+.2f}" for k in ["Net Points","Shooting", "Turnovers", "Rebounding", "Free Throws"]}
                grad_cols = ["Net Points","Shooting", "Turnovers", "Rebounding", "Free Throws"]
            else:
                cols_visible = ["Pos", "Team_Logo", "Team", "Pts off TO", "2nd Chance", "Fast Break", "eFG%", "TO%", "ORB%", "FTR"]
                if view_type == "Net Impact":
                    format_dict = {k: "{:+.2f}" for k in ["Pts off TO", "2nd Chance", "Fast Break"]}
                    format_dict.update({k: "{:+.1%}" for k in ["eFG%", "TO%", "ORB%"]})
                    format_dict["FTR"] = "{:+.3f}"
                else:
                    format_dict = {k: "{:.2f}" for k in ["Pts off TO", "2nd Chance", "Fast Break"]}
                    format_dict.update({k: "{:.1%}" for k in ["eFG%", "TO%", "ORB%"]})
                    format_dict["FTR"] = "{:.3f}"
                grad_cols = [c for c in cols_visible if c not in ["Pos", "Team_Logo", "Team"]]

            format_dict["Pos"] = "{:.0f}"

            # 4. APPLY STYLING
            styler = standings_df[cols_visible].style.format(format_dict)

            # APPLY GRADIENTS
            for col in grad_cols:
                v_max = standings_df[col].abs().max()
                v_max = max(v_max, 1.0)
                cmap = custom_gnwr if "TO%" in col else custom_rdwgn
                styler = styler.background_gradient(cmap=cmap, subset=[col], vmin=-v_max, vmax=v_max)

            # --- CAREFULLY INDENTED RENDER BLOCK ---
            dynamic_height_standings = (len(standings_df) * 36) + 45
            
            col_config_standings = {
                "Team_Logo": st.column_config.ImageColumn(" ", width="small"), 
                "Pos": st.column_config.NumberColumn("Pos", width="small"),
                "Team": st.column_config.TextColumn("Team", width="medium")
            }
            
            for col in cols_visible:
                if col not in ["Pos", "Team_Logo", "Team"]:
                    col_config_standings[col] = st.column_config.NumberColumn(col, width="small")

            st.dataframe(
                styler, 
                use_container_width=False,  
                height=dynamic_height_standings, 
                hide_index=True, 
                column_order=cols_visible,
                column_config=col_config_standings
            )

# --- THE PLAYER TAB LOGIC ---
    with tab_standings_players:
        # The Checkboxes (You can keep them visible, they just won't trigger anything in Classic)
        col_ctrl_l1, col_ctrl_l2 = st.columns(2)
        with col_ctrl_l1:
            exp_ld_offdef = st.checkbox("Show Offense/Defense Breakdown", value=False, key="cb_offdef_ld")
        with col_ctrl_l2:
            exp_ld_shoot = st.checkbox("Show 2P/3P Shooting Split", value=False, key="cb_shoot_ld")
        
        st.markdown("---")

        with st.spinner("Gathering league-wide player data..."):
            # --- THE FIX: CALL THE CORRECT DATA GATHERER BASED ON VIEW ---
            if analysis_type == "4-Factors Net Points":
                df_league_players = get_league_player_leaderboard(league, season, selected_phase)
            else:
                df_league_players = get_league_player_leaderboard_classic_v4(league, season, selected_phase)
            
            # --- FILTER THE PLAYERS TO ONLY THOSE IN THE SELECTED GROUP ---
            if df_league_players is not None and not df_league_players.empty:
                df_league_players = df_league_players[df_league_players['Team_Name'].isin(teams_to_analyze)]
            
            if df_league_players is None or df_league_players.empty:
                st.warning("No individual player data found for this selection.")
            else:
                # Sorting logic based on mode
                if analysis_type == "4-Factors Net Points":
                    if view_type == "Offensive Impact":
                        sort_col, title_prefix = 'Off_NP', "Top 50 Offensive"
                    elif view_type == "Defensive Impact":
                        sort_col, title_prefix = 'Def_NP', "Top 50 Defensive"
                    else:
                        sort_col, title_prefix = 'Total_NP', "Top 50 Overall"
                else:
                    sort_col, title_prefix = 'PTS', "Top 50 Classic"

                # Safely fallback to another column if sort_col is missing
                if sort_col not in df_league_players.columns:
                    numeric_cols = df_league_players.select_dtypes(include=['number']).columns
                    if len(numeric_cols) > 0: sort_col = numeric_cols[0]
                    else: sort_col = df_league_players.columns[0]

                df_leaderboard = df_league_players.sort_values(sort_col, ascending=False)
                
                st.markdown(f"### {title_prefix} Impact ({selected_phase})")
                
                # USING YOUR ORIGINAL RENDERER (It handles the Classic columns perfectly!)
                display_player_table(df_leaderboard.head(50), "League Leaderboard", exp_ld_offdef, exp_ld_shoot)
# --- 5. MODE: GAMES BOXSCORES (Single Game) ---
else: 
    df_f = df_league[df_league['season'] == season].copy()
    phase_options = sorted(df_f['phase'].unique())
    phase = st.sidebar.selectbox("Phase / Group", phase_options, key="phase_sel")
    df_f = df_f[df_f['phase'] == phase].copy()
    
    round_val = st.sidebar.selectbox("Round", sorted(df_f['round'].unique()), key="round_sel")
    df_f = df_f[df_f['round'] == round_val].copy()
    
    df_f['display'] = df_f.apply(lambda x: f"{x['round']} | {x['t1']} ({x['pts1']}) vs {x['t2']} ({x['pts2']})", axis=1)
    game_display = st.sidebar.selectbox("Game", df_f['display'].unique(), key="game_sel")
    game_record = df_f[df_f['display'] == game_display].iloc[0]
    
    g = get_raw_game_data_custom(game_record['path'])
    t1, t2 = g['t1_name'], g['t2_name']
    t1_off, t2_off = g['t1_stats'], g['t2_stats'] # These are TOTALS for the game
    
    # Game Totals calculation
    i1_tot = calc_raw_factors(t1_off, t2_off['drb'], lg_effic, lg_orb_pct)
    i2_tot = calc_raw_factors(t2_off, t1_off['drb'], lg_effic, lg_orb_pct)
    i1_raw, i2_raw = (i1_tot, i1_tot), (i2_tot, i2_tot)
    
    header_title = f"4-Factors Impact: {game_record['round']} - {t1} ({game_record['pts1']}) vs {t2} ({game_record['pts2']})"
    # --- CORRECTED DATA AUDIT (VOLUME vs VOLUME) ---

# --- DISPLAY ---
# Ensure we only try to render this if we are in a mode that defines matchup variables
if mode in ["Season Aggregates per Team", "Head to Head Matchup", "Games Boxscores"]:
    
    # 1. Icons and Header (Slightly indented)
    t1_icon = get_team_icon(t1, league)
    t2_icon = get_team_icon(t2, league)

    icon1_img = f'<img src="{t1_icon}" style="max-height: 80px; width: auto;">' if t1_icon else ""
    icon2_img = f'<img src="{t2_icon}" style="max-height: 80px; width: auto;">' if t2_icon else ""

    header_html = f"""
    <div style="display: flex; align-items: center; justify-content: space-between; width: 100%; margin-bottom: 10px;">
        <div style="flex: 1; text-align: left; min-width: 100px;">{icon1_img}</div>
        <div style="flex: 3; text-align: center;">
            <h1 style="margin: 0; font-size: 1.5rem; line-height: 1.2;">{header_title}</h1>
        </div>
        <div style="flex: 1; text-align: right; min-width: 100px;">{icon2_img}</div>
    </div>
    <hr style="margin-top: 5px; margin-bottom: 25px; border: 0; border-top: 1px solid #eee;">
    """
    st.markdown(header_html, unsafe_allow_html=True)

    # --- H2H GAME SUMMARY ---
    if mode == "Head to Head Matchup":
        mask_h2h = (
            (df_index['league'] == league) & 
            (df_index['season'] == season) & 
            (
                ((df_index['t1'] == t1) & (df_index['t2'] == t2)) |
                ((df_index['t1'] == t2) & (df_index['t2'] == t1))
            )
        )
        h2h_games_list = df_index[mask_h2h].sort_values('round')

        if not h2h_games_list.empty:
            game_strings = []
            for _, row in h2h_games_list.iterrows():
                game_strings.append(f"**{row['round']}**: {row['t1']} {row['pts1']}-{row['pts2']} {row['t2']}")
            
            with st.container():
                st.markdown(f"**Games included in this H2H aggregate:**")
                st.write(" • " + " | ".join(game_strings))
                st.markdown("---")

    # --- TAB SYSTEM (Now correctly indented inside the IF block) ---
    tab_team, tab_players = st.tabs(["Team Comparison", "Player Impact"])

    with tab_team:
        if analysis_type == "4-Factors Net Points":
            if mode == "Head to Head Matchup" or mode == "Games Boxscores":
                st.markdown("#### Matchup Bottom Line (Net Points)")
                t1_total_net = sum(i1_tot.values())
                t2_total_net = sum(i2_tot.values())
                diff = t1_total_net - t2_total_net
                winner = t1 if diff > 0 else t2
                winning_stats = i1_tot if diff > 0 else i2_tot
                best_factor = max(winning_stats, key=winning_stats.get)

                m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                with m_col1: st.metric(label=f"{t1} Total Edge", value=f"{t1_total_net:+.2f} pts")
                with m_col2: st.metric(label=f"{t2} Total Edge", value=f"{t2_total_net:+.2f} pts")
                with m_col3: st.metric(label="Overall Advantage", value=f"{abs(diff):+.2f} pts", delta=winner)
                with m_col4: st.metric(label="Key Driver", value=best_factor)
                st.markdown("---")

            elif mode == "Season Aggregates per Team":
                st.markdown("#### Team vs League Baseline (Net Points)")
                t1_total_net = sum(i1_tot.values())
                best_factor = max(i1_tot, key=i1_tot.get)
                worst_factor = min(i1_tot, key=i1_tot.get)

                m_col1, m_col2, m_col3 = st.columns(3)
                with m_col1: st.metric(label=f"{t1} Net Impact", value=f"{t1_total_net:+.2f} pts")
                with m_col2: st.metric(label="Strongest Area", value=best_factor, delta=f"{i1_tot[best_factor]:+.2f}")
                with m_col3: st.metric(label="Biggest Liability", value=worst_factor, delta=f"{i1_tot[worst_factor]:+.2f}")
                st.markdown("---")
        else:
            # Handle CLASSIC Analysis
            if mode == "Head to Head Matchup" or mode == "Games Boxscores":
                st.markdown("#### Situational Scoring Edge")
                if mode == "Games Boxscores": s1_sum, s2_sum = g['t1_stats'], g['t2_stats']
                else: s1_sum, s2_sum = t1_h2h_avg, t2_h2h_avg
            
                t1_sit_total = s1_sum.get('pts_off_to', 0) + s1_sum.get('pts_2nd_ch', 0) + s1_sum.get('pts_fb', 0)
                t2_sit_total = s2_sum.get('pts_off_to', 0) + s2_sum.get('pts_2nd_ch', 0) + s2_sum.get('pts_fb', 0)
                sit_diff = t1_sit_total - t2_sit_total
                sit_winner = t1 if sit_diff > 0 else t2

                m_col1, m_col2, m_col3 = st.columns(3)
                with m_col1: st.metric(label=f"{t1} Sit. Pts", value=f"{t1_sit_total:.1f}")
                with m_col2: st.metric(label=f"{t2} Sit. Pts", value=f"{t2_sit_total:.1f}")
                with m_col3: st.metric(label="Sit. Advantage", value=f"{abs(sit_diff):+.1f} pts", delta=sit_winner)
                st.markdown("---")

            elif mode == "Season Aggregates per Team":
                st.markdown("#### Situational Profile vs League")
                t1_sit_total = t1_off.get('pts_off_to', 0) + t1_off.get('pts_2nd_ch', 0) + t1_off.get('pts_fb', 0)
                lg_sit_total = lg_data.get('pts_off_to', 0) + lg_data.get('pts_2nd_ch', 0) + lg_data.get('pts_fb', 0)
                sit_diff = t1_sit_total - lg_sit_total
                # Categorize into 4 tiers (You can adjust the 4.0 threshold if you prefer)
                if sit_diff >= 4.0:
                    tier_tag = "Elite"
                elif sit_diff >= 0:
                    tier_tag = "Above Avg"
                elif sit_diff >= -4.0:
                    tier_tag = "- Below Avg"   # The minus sign forces Streamlit to color it Red with a Down arrow
                else:
                    tier_tag = "- Bottom Tier" # The minus sign forces Streamlit to color it Red with a Down arrow

                m_col1, m_col2 = st.columns(2)
                with m_col1: st.metric(label=f"{t1} Avg Sit. Pts", value=f"{t1_sit_total:.1f}")
                with m_col2: st.metric(label="vs League Avg", value=f"{t1_sit_total - lg_sit_total:+.1f}", delta=tier_tag)
                st.markdown("---")

        with st.container(border=True):
            if analysis_type == "4-Factors Net Points":
                st.plotly_chart(plot_4f_comparison(i1_tot, i2_tot, t1, t2), use_container_width=True, key=f"chart_4f_final_{t1}_{t2}")
            else:
                if mode == "Games Boxscores": s1_plot, s2_plot = g['t1_stats'], g['t2_stats']
                elif mode == "Head to Head Matchup": s1_plot, s2_plot = t1_h2h_avg, t2_h2h_avg
                else: s1_plot, s2_plot = t1_off, t2_off
                st.plotly_chart(plot_situational_comparison(s1_plot, s2_plot, t1, t2, lg_data), use_container_width=True, key=f"chart_sit_final_{t1}_{t2}")
                st.markdown("### Four Factors (%) Comparison")
                p1 = get_4f_percentages(s1_plot, s2_plot)
                p2 = get_4f_percentages(s2_plot, s1_plot)
                st.table(pd.DataFrame([p1, p2], index=[t1, t2]))

    with tab_players:
        if analysis_type == "4-Factors Net Points":
            col_ctrl1, col_ctrl2 = st.columns(2)
            with col_ctrl1: expand_off_def = st.checkbox("Show Offense/Defense Breakdown", value=False, key="cb_offdef_match")
            with col_ctrl2: expand_shooting = st.checkbox("Show 2P/3P Shooting Split", value=False, key="cb_shoot_match")
        else:
            expand_off_def, expand_shooting = False, False

        st.markdown("---")
        min_gp_filter = 1
        if mode in ["Season Aggregates per Team", "Head to Head Matchup"]:
            t1_off_stats = get_per_game_volumes(t1, league, season, "TOTAL")
            max_gp_possible = int(t1_off_stats.get('gp', 1))
            if max_gp_possible > 1:
                col_gp1, col_gp2 = st.columns([1, 3])
                with col_gp1:
                    min_gp_filter = st.slider("Min. Games Played", 1, max_gp_possible, 1, key="min_gp_slider")
                with col_gp2: st.markdown("<br>", unsafe_allow_html=True)

        def apply_gp_filter(df, target_min):
            if df is None or df.empty: return df
            gp_col = next((c for c in df.columns if c.upper() == 'GP'), None)
            if gp_col:
                df[gp_col] = pd.to_numeric(df[gp_col], errors='coerce').fillna(0)
                p_col = next((c for c in df.columns if c.upper() == 'PLAYER'), 'Player')
                mask = (df[gp_col] >= target_min) | (df[p_col].str.contains('TEAM|EQUIP|TOTAL|--- TOTAL ---', case=False, na=False))
                return df[mask].copy()
            return df

        is_h2h = t2 != "League Average"
        if is_h2h:
            p_tabs = st.tabs([f"{t1}", f"{t2}"])
            with p_tabs[0]:
                if analysis_type == "4-Factors Net Points":
                    if mode == "Games Boxscores": df_p1 = load_single_game_individual(game_record['path'], t1)
                    elif mode == "Head to Head Matchup": df_p1 = load_h2h_individual_data(t1, t2, league, season)
                    else: df_p1 = load_individual_aggregate(t1, league, season, phase if 'phase' in locals() else None)
                else:
                    if mode == "Games Boxscores": df_p1 = load_single_game_classic_individual(game_record['path'], t1)
                    elif mode == "Head to Head Matchup": df_p1 = load_aggregated_classic_individual_data(t1, league, season, phase if 'phase' in locals() else None, opponent_team=t2)
                    else: df_p1 = load_aggregated_classic_individual_data(t1, league, season, phase if 'phase' in locals() else None)
                df_p1_f = apply_gp_filter(df_p1, min_gp_filter)
                display_player_table(df_p1_f, f"{t1} Individual Stats", expand_off_def, expand_shooting)
            with p_tabs[1]:
                if analysis_type == "4-Factors Net Points":
                    if mode == "Games Boxscores": df_p2 = load_single_game_individual(game_record['path'], t2)
                    elif mode == "Head to Head Matchup": df_p2 = load_h2h_individual_data(t2, t1, league, season)
                    else: df_p2 = load_individual_aggregate(t2, league, season, phase if 'phase' in locals() else None)
                else:
                    if mode == "Games Boxscores": df_p2 = load_single_game_classic_individual(game_record['path'], t2)
                    elif mode == "Head to Head Matchup": df_p2 = load_aggregated_classic_individual_data(t2, league, season, phase if 'phase' in locals() else None, opponent_team=t1)
                    else: df_p2 = load_aggregated_classic_individual_data(t2, league, season, phase if 'phase' in locals() else None)
                df_p2_f = apply_gp_filter(df_p2, min_gp_filter)
                display_player_table(df_p2_f, f"{t2} Individual Stats", expand_off_def, expand_shooting)
        else:
            c_phase = phase if 'phase' in locals() else None
            if analysis_type == "4-Factors Net Points":
                if mode == "Games Boxscores": df_p1 = load_single_game_individual(game_record['path'], t1)
                else: df_p1 = load_individual_aggregate(t1, league, season, c_phase)
            else:
                if mode == "Games Boxscores": df_p1 = load_single_game_classic_individual(game_record['path'], t1)
                else: df_p1 = load_aggregated_classic_individual_data(t1, league, season, c_phase)
            df_p1_f = apply_gp_filter(df_p1, min_gp_filter)
            display_player_table(df_p1_f, f"{t1} Individual Stats", expand_off_def, expand_shooting)


# --- GLOSSARY / INTERPRETATION ---
if mode in ["Season Aggregates per Team", "Head to Head Matchup", "Games Boxscores"] and analysis_type == "4-Factors Net Points":
    st.markdown("---")
    st.subheader("Scouting Interpretation")
    factors = ["Shooting", "Rebounding", "Turnovers", "Free Throws"]
    
    # If comparing against league, we might only want one column or a special label
    c1, c2 = st.columns(2)

    with c1:
        st.markdown(f"#### {t1} Impact")
        for f in factors:
            val = i1_tot[f]
            label = "contribution" if val >= 0 else "cost"
            advantage_text = ""
            
            # Only show "more efficient than" if the opponent isn't the League Baseline
            if t2 != "League Average":
                if mode == "Head to Head Matchup":
                    # In H2H, the 'val' is already the difference
                    diff = val 
                    label = "advantage" if diff >= 0 else "disadvantage"
                    advantage_text = f" ({t1} is {abs(diff):+.2f} pts better/worse than {t2})"
                else:
                    # In other modes, keep the original comparison
                    if i1_tot[f] > i2_tot[f]:
                        diff = i1_tot[f] - i2_tot[f]
                        advantage_text = f" ({t1} was {diff:+.2f} pts better)"
            else:
                # If comparing to league, just explain the value vs 0
                advantage_text = " vs League Avg"
                
            st.write(f"• **{f}**: {val:+.2f} points {label}{advantage_text}")

    with c2:
        if t2 == "League Average":
            st.markdown("#### League Baseline")
            st.info("The League Average is the 0.00 benchmark. Values on the left show how much this team deviates from the typical league performance.")
        else:
            st.markdown(f"#### {t2} Impact")
            for f in factors:
                val = i2_tot[f]
                label = "contribution" if val >= 0 else "cost"
                advantage_text = ""
                if i2_tot[f] > i1_tot[f]:
                    diff = i2_tot[f] - i1_tot[f]
                    advantage_text = f" ({t2} was {diff:+.2f} pts better)"
                st.write(f"• **{f}**: {val:+.2f} points {label}{advantage_text}")
    if mode == "Games Boxscores":
        st.markdown("---")
        st.subheader("Final Match Summary")
        real_score_diff = game_record['pts1'] - game_record['pts2']
        total_4f_home = sum(i1_tot.values())
        total_4f_away = sum(i2_tot.values())
        net_4f_diff = total_4f_home - total_4f_away
        col_a, col_b = st.columns(2)
        col_a.metric("Real Score Difference", f"{real_score_diff:+}")
        col_b.metric("4F Net Points Difference", f"{net_4f_diff:+.2f}")
        if abs(real_score_diff - net_4f_diff) > 10:
            st.info("Note: The 4F Net Difference accounts for shooting, rebounding, and turnovers.")

    # --- EXPANDERS & PDF ---
    with st.expander("Offense vs Defense Net Breakdown"):
        ec1, ec2 = st.columns(2)
        with ec1:
            st.write(f"### {t1} (Home)")
            for f in factors: 
                st.markdown(f"**{f} Net: {i1_tot[f]:+.2f}** | Off: {i1_raw[0][f]:+.2f} | Def: {i1_raw[1][f]:+.2f}")
        with ec2:
            if t2 == "League Average":
                st.write("### League Average")
                st.write("By definition, the League Average has 0.00 Net Impact because it is the baseline for all calculations.")
            else:
                st.write(f"### {t2} (Away)")
                for f in factors: 
                    st.markdown(f"**{f} Net: {i2_tot[f]:+.2f}** | Off: {i2_raw[0][f]:+.2f} | Def: {i2_raw[1][f]:+.2f}")
# --- GLOBAL EXPORT TOOL (At the very end of the script) ---
st.markdown("---")
inject_print_engine() 

col_p1, col_p2, col_p3 = st.columns([1, 2, 1])
with col_p2:
    # We use a standard HTML button inside the component to trigger the print.
    # This is often more reliable than an automatic script.
    st.components.v1.html(
        """
        <html>
            <head>
                <style>
                    .print-btn {
                        background-color: #FF4B4B;
                        color: white;
                        border: none;
                        padding: 12px 24px;
                        border-radius: 8px;
                        cursor: pointer;
                        font-family: sans-serif;
                        font-weight: bold;
                        width: 100%;
                        font-size: 16px;
                    }
                    .print-btn:hover {
                        background-color: #ff3333;
                    }
                </style>
            </head>
            <body>
                <button class="print-btn" onclick="window.parent.print()">
                    Export View to PDF / Print (Use Print to PDF in browser, and make sure to set horizontal)
                </button>
            </body>
        </html>
        """,
        height=70,
    )
    st.caption("<div style='text-align:center;'>Tip: Ensure 'Background Graphics' is ON in print settings to keep heatmap colors.</div>", unsafe_allow_html=True)