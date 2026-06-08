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
from difflib import SequenceMatcher
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

# --- PROFESSIONAL COLOR PALETTES (Blue-White-Red) ---
from matplotlib.colors import LinearSegmentedColormap

# 1. Blue-White-Red (Thermal: Red is Hot/Good, Blue is Cold/Bad)
custom_bluered = LinearSegmentedColormap.from_list("bluered", ["#6fa8dc", "#ffffff", "#e06666"])

# 2. Red-White-Blue (Inverted: For Turnovers - High TOs is Red/Danger)
custom_redblue = LinearSegmentedColormap.from_list("redblue", ["#e06666", "#ffffff", "#6fa8dc"])

# 3. White-Red (For Volumes: Shows intensity without "bad" blue)
custom_wred = LinearSegmentedColormap.from_list("wred", ["#ffffff", "#e06666"])
def clean_num(val):
	if pd.isna(val) or val == "" or val == "-": return 0.0
	try: return float(val)
	except: return 0.0
def clean_player_name(text):
	if not text or pd.isna(text):
		return ""
	text = str(text).strip().upper()
	
	# 1. Remove jersey patterns: #0, #00, 12., 05 -, etc. at the start
	text = re.sub(r'^(#?\d+[\s\.\-]*)+', '', text)
	
	# 2. Fix missing spaces after initials (M.CALANCHE -> M. CALANCHE)
	text = re.sub(r'([A-Z])\.(?=[A-Z])', r'\1. ', text)
	
	# 3. Strip accents to prevent duplicates (GONZÁLEZ -> GONZALEZ)
	import unicodedata
	text = unicodedata.normalize('NFKD', text).encode('ascii', 'ignore').decode('utf-8')
	
	return text.strip()
# --- HELPERS ---
@st.cache_data
def get_league_zone_benchmarks(league, season):
	"""
	Dynamically calculates League Average Points Per Shot (PPS) 
	for each shot zone by aggregating all games in the season.
	"""
	# 1. Initialize empty counters for the league
	zone_totals = {
		"Rim": {"pts": 0, "fga": 0},
		"Paint": {"pts": 0, "fga": 0},
		"Mid-Range": {"pts": 0, "fga": 0},
		"Corner 3": {"pts": 0, "fga": 0},
		"Above Break 3": {"pts": 0, "fga": 0}
	}
	
	# 2. Filter your index for the current league/season
	mask = (df_index['league'] == league) & (df_index['season'] == season)
	league_games = df_index[mask]
	
	# 3. Loop through the games to sum up the volume
	for _, row in league_games.iterrows():
		try:
			# We will read the file here and add to zone_totals
			# (Waiting for your column names to complete this block)
			pass
		except Exception as e:
			continue

	# 4. Calculate PPS (Points / Attempts)
	zone_pps = {}
	fallbacks = {"Rim": 1.30, "Paint": 0.85, "Mid-Range": 0.80, "Corner 3": 1.15, "Above Break 3": 1.05}
	
	for zone, stats in zone_totals.items():
		if stats['fga'] > 0:
			zone_pps[zone] = stats['pts'] / stats['fga']
		else:
			zone_pps[zone] = fallbacks.get(zone, 1.0) # Safety fallback
			
	return zone_pps
def highlight_scouting_outliers(val, col_name, actual_sort_col=None, is_large_sample=False):
	"""Global scouting thresholds for Bold Red (Elite) and Bold Blue (Liability).
	Adapts thresholds depending on whether it's a large sample (season) or small sample (single game/H2H)."""
	if actual_sort_col and col_name == actual_sort_col: 
		return '' # Don't color text if the background is already colored
	try:
		v = float(val)
		
		# --- DEFINE THRESHOLDS BASED ON SAMPLE SIZE ---
		if is_large_sample:
			# Tighter thresholds for season averages
			np_elite, np_poor = 1.50, -1.00
			usg_elite, usg_poor = 0.25, 0.15
			efg_margin = 0.08
			to_margin = 0.05
			or_elite = 0.10
			ftr_elite = 0.40
			sit_elite, sit_poor = 1.5, 0.5
		else:
			# Looser thresholds for high-variance single games / H2H
			np_elite, np_poor = 3.00, -2.00
			usg_elite, usg_poor = 0.30, 0.12
			efg_margin = 0.15
			to_margin = 0.08
			or_elite = 0.15
			ftr_elite = 0.50
			sit_elite, sit_poor = 3.0, 0.5

		# 1. Net Points Thresholds
		if any(x in col_name for x in ['Net_', 'Total_NP', 'Off_', 'Def_']):
			if v >= np_elite: return 'color: #e06666; font-weight: bold;'
			if v <= np_poor: return 'color: #6fa8dc; font-weight: bold;'
		
		# 2. USG% - Alpha Scorer vs Role Player
		if col_name == 'USG%':
			if v >= usg_elite: return 'color: #e06666; font-weight: bold;'
			if v <= usg_poor: return 'color: #6fa8dc; font-weight: bold;'

		# 3. eFG% - Shooting Efficiency
		if col_name == 'eFG%':
			ref = globals().get('avg_efg', 0.52)
			if v >= ref + efg_margin: return 'color: #e06666; font-weight: bold;'
			if v <= ref - efg_margin: return 'color: #6fa8dc; font-weight: bold;'

		# 4. TO% - Ball Security (Lower is better)
		if col_name == 'TO%':
			ref = globals().get('avg_to', 0.16)
			if v <= ref - to_margin: return 'color: #e06666; font-weight: bold;'
			if v >= ref + to_margin: return 'color: #6fa8dc; font-weight: bold;'

		# 5. OR% - Rebounding Skill
		if col_name == 'OR%':
			if v >= or_elite: return 'color: #e06666; font-weight: bold;'

		# 6. FTR - Foul Drawing
		if col_name == 'FTR':
			if v >= ftr_elite: return 'color: #e06666; font-weight: bold;'

		# 7. Situational Volumes (Per Game or Per 100)
		if col_name in ['Pts_off_TO', '2nd_Chance', 'Fast_Break']:
			if v >= sit_elite: return 'color: #e06666; font-weight: bold;'
			if v <= sit_poor: return 'color: #6fa8dc; font-weight: bold;'
	except:
		pass
	return ''
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
				/* Prevent the search box from focusing/triggering keyboard on mobile */
				[data-baseweb="select"] input {
					pointer-events: none !important;
				}
			}
		</style>
		""",
		unsafe_allow_html=True,
	)
@st.cache_resource # This makes the search instant after the first time
def get_league_player_leaderboard(league, season, phase_ui, avg_mode): # Added avg_mode
	all_teams = get_teams_in_league(league, season)
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
	try:
		# 1. Path Setup: Locate the 'individual' folder relative to the raw file
		phase_folder = os.path.dirname(os.path.dirname(file_path))
		individual_dir = os.path.join(phase_folder, "individual")
		
		if not os.path.exists(individual_dir):
			return None

		# 2. Extract target Game ID from the raw filename
		raw_name = os.path.basename(file_path)
		match = re.search(r'(\d+)', raw_name)
		if not match: 
			return None
		target_id = str(match.group(1))

		# 3. Search for the player file
		matching_file = None
		for f in os.listdir(individual_dir):
			if not f.startswith("NP_"): 
				continue
			nums_in_file = re.findall(r'\d+', f)
			if nums_in_file and target_id == nums_in_file[0]:
				matching_file = f
				break
		
		if not matching_file:
			return None

		# 4. Load the individual Excel file
		full_path = os.path.join(individual_dir, matching_file)
		df = pd.read_excel(full_path)
		
		# Ensure 'Player' column is standardized
		p_col = next((c for c in df.columns if c.upper() == 'PLAYER'), 'Player')
		if p_col != 'Player':
			df = df.rename(columns={p_col: 'Player'})
            
		# 5. Clean up the dataframe (Remove 'TOTAL' summary rows)
		df = df[~df['Player'].astype(str).str.contains('TOTAL|EQUIP|TEAM', na=False, case=False)]

		# 6. Define the Match Key
		def make_match_key(text):
			if not text or pd.isna(text): return ""
			s = normalize_str(str(text))
			return re.sub(r'[\s\.]+', '', s)

		nk_target = make_match_key(target_team)

		# 7. Identify the Team Column
		team_col = None
		for col in df.columns:
			if col.strip().upper() in ['TEAM', 'EQUIP', 'EQUIPO', 'CLUB', 'EQUIPOS']:
				team_col = col
				break
		
		if not team_col:
			return None

		# 8. Apply the match
		def is_team_match(row_val):
			nk_row = make_match_key(row_val)
			if not nk_row or not nk_target: return False
			return (nk_row == nk_target) or (nk_row in nk_target and len(nk_row) > 4) or (nk_target in nk_row)

		mask = df[team_col].apply(is_team_match)
		df_filtered = df[mask].copy()

		# --- THE CRITICAL FIX: CLEAN NAMES TO SYNC WITH THE RADAR ---
		df_filtered['Player'] = df_filtered['Player'].apply(clean_player_name)

		# 9. Safety: Ensure GP column exists
		for col in df_filtered.columns:
			if col.strip().upper() == 'GP':
				df_filtered = df_filtered.rename(columns={col: 'GP'})
				break
		
		if 'GP' not in df_filtered.columns:
			df_filtered['GP'] = 1

		return df_filtered
		
	except Exception as e:
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
    if phase is None or not isinstance(phase, str) or phase == "":
        folder_phase = "Regular_Season"
    else:
        folder_phase = phase.split(" - ")[0].replace(" ", "_")
    
    file_path = os.path.join(
        DATA_BASE_PATH, league, season, folder_phase, 
        "aggregate_individual", f"AGG_IND_{team_name.strip()}.xlsx"
    )

    if not os.path.exists(file_path):
        return None

    try:
        df = pd.read_excel(file_path)
        p_col = next((c for c in df.columns if c.upper() == 'PLAYER'), 'Player')
        all_teams = get_teams_in_league(league, season)
        
        def is_valid_player_row(val):
            val_str = str(val).upper().strip()
            if any(term in val_str for term in ['TOTAL', '---', 'EQUIP', 'TEAM', 'ENTRENADOR']): return False
            if any(team.upper() == val_str for team in all_teams): return False
            if len(val_str) < 2: return False # Changed to 2 to allow "LO"
            return True

        df = df[df[p_col].apply(is_valid_player_row)].copy()
        
        # --- THE FIX: CLEAN NAMES AND MERGE DUPLICATES ---
        df[p_col] = df[p_col].apply(clean_player_name)
        
        numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
        if 'GP' in df.columns and 'GP' not in numeric_cols:
            df['GP'] = pd.to_numeric(df['GP'], errors='coerce').fillna(0)
            numeric_cols.append('GP')
            
        # Group by the newly cleaned player name to combine their stats!
        df = df.groupby(p_col, as_index=False)[numeric_cols].sum()
        
        # --- Divisor logic ---
        if avg_mode == "Season Value (Team GP)":
            team_stats = get_per_game_volumes(team_name, league, season)
            divisor = float(team_stats.get('gp', 1))
        else:
            divisor = df['GP'].replace(0, 1)

        numeric_cols = df.select_dtypes(include=['number']).columns
        for col in numeric_cols:
            if col != 'GP': 
                df[col] = df[col] / divisor
                
        return df
        
    except Exception as e:
        st.write(f"DEBUG: Error loading {team_name}: {e}")
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

		# --- REVERTED TO YOUR ORIGINAL PERFECT SLICING ---
		if nk_target == nk_t1 or nk_target in nk_t1 or nk_t1 in nk_target:
			start_idx = 3
			end_idx = total_rows[0]
			t_row, o_row = df.iloc[total_rows[0]], df.iloc[total_rows[1]]
		elif nk_target == nk_t2 or nk_target in nk_t2 or nk_t2 in nk_target:
			start_idx = total_rows[0] + 2
			end_idx = total_rows[1]
			t_row, o_row = df.iloc[total_rows[1]], df.iloc[total_rows[0]]
		else:
			return None

		df_players = df.iloc[start_idx:end_idx].copy()
		if 38 not in df_players.columns: df_players[38] = "0:00"

		def parse_min(val):
			if pd.isna(val): return 0.0
			if hasattr(val, 'hour') and hasattr(val, 'minute'): return val.hour * 60 + val.minute + (getattr(val, 'second', 0) / 60.0)
			val_str = str(val).strip()
			if ':' in val_str:
				parts = val_str.split(':')
				try: return float(parts[0]) + float(parts[1])/60.0
				except: return 0.0
			try: return float(val_str)
			except: return 0.0

		df_players['Team_FGA'] = clean_num(t_row[3]) + clean_num(t_row[5])
		df_players['Team_FTA'] = clean_num(t_row[7])
		df_players['Team_TOV'] = clean_num(t_row[14])
		df_players['Team_ORB'] = clean_num(t_row[10])
		df_players['Opp_DRB'] = clean_num(o_row[9])
		
		t_mp = parse_min(t_row.get(38, "200:00"))
		df_players['Team_MP'] = t_mp if t_mp > 0 else 200.0

		rename_dict = {
			0: "Player", 1: "PTS", 2: "F2M", 3: "F2A", 4: "F3M", 5: "F3A",
			6: "FTM", 7: "FTA", 8: "AS", 9: "DRB", 10: "ORB", 14: "TOV",
			19: "Pts_off_TO", 20: "2nd_Chance", 21: "Fast_Break",
			23: "RIM FGM", 24: "RIM FGA", 26: "PAINT FGM", 27: "PAINT FGA",
			29: "MR FGM", 30: "MR FGA", 32: "COR3 FGM", 33: "COR3 FGA",
			35: "ATB3 FGM", 36: "ATB3 FGA", 38: "MIN_STR"
		}
		
		df_players = df_players.rename(columns=rename_dict)
		df_players['Player'] = df_players['Player'].apply(clean_player_name)
		df_players['MIN'] = df_players['MIN_STR'].apply(parse_min)

		cols_to_keep = [
			"Player", "PTS", "F2M", "F2A", "F3M", "F3A", "FTM", "FTA","AS", "ORB", "DRB", "TOV", 
			"Pts_off_TO", "2nd_Chance", "Fast_Break", "MIN", "Team_FGA", "Team_FTA", "Team_TOV", 
			"Team_ORB", "Opp_DRB", "Team_MP", 
			"RIM FGA", "RIM FGM", "PAINT FGA", "PAINT FGM", "MR FGA", "MR FGM", 
			"COR3 FGA", "COR3 FGM", "ATB3 FGA", "ATB3 FGM"
		]
		
		valid_cols = [c for c in cols_to_keep if c in df_players.columns]
		df_players = df_players[valid_cols]

		# --- THE MASTER FILTER: KEEP ONLY PLAYERS WHO ACTUALLY PLAYED ---
		# This instantly deletes Team Names, Arenas, Referees, and Headers without needing a garbage list!
		df_players = df_players[df_players['MIN'] > 0].copy()

		# Now it is safe to fill NaN points with 0, saving Arevalo!
		df_players['PTS'] = pd.to_numeric(df_players['PTS'], errors='coerce').fillna(0.0)

		# Ensure all math columns are numbers
		for c in valid_cols:
			if c not in ["Player", "MIN", "PTS"]:
				df_players[c] = pd.to_numeric(df_players[c], errors='coerce').fillna(0.0)

		df_players['Team_Name'] = target_team
		df_players['GP'] = 1
		df_players['FGA'] = df_players['F2A'] + df_players['F3A']
		df_players['FGM'] = df_players['F2M'] + df_players['F3M']

		df_players['eFG%'] = df_players.apply(lambda x: (x['FGM'] + 0.5 * x['F3M']) / x['FGA'] if x['FGA'] > 0 else 0, axis=1)
		df_players['TO%'] = df_players.apply(lambda x: x['TOV'] / (x['FGA'] + 0.44 * x['FTA'] + x['TOV']) if (x['FGA'] + 0.44 * x['FTA'] + x['TOV']) > 0 else 0, axis=1)
		df_players['FTR'] = df_players.apply(lambda x: x['FTM'] / x['FGA'] if x['FGA'] > 0 else 0, axis=1)
	
		df_players['USG%'] = df_players.apply(lambda x: ((x['FGA'] + 0.44 * x['FTA'] + x['TOV']) * (x['Team_MP'] / 5)) / (x['MIN'] * (x['Team_FGA'] + 0.44 * x['Team_FTA'] + x['Team_TOV'])) if (x['MIN'] > 0 and (x['Team_FGA'] + 0.44 * x['Team_FTA'] + x['Team_TOV']) > 0) else 0, axis=1)
		df_players['OR%'] = df_players.apply(lambda x: (x['ORB'] * (x['Team_MP'] / 5)) / (x['MIN'] * (x['Team_ORB'] + x['Opp_DRB'])) if (x['MIN'] > 0 and (x['Team_ORB'] + x['Opp_DRB']) > 0) else 0, axis=1)

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
	
	# around line 790
	cols_to_sum = ["PTS", "F2M", "F2A", "F3M", "F3A", "FTM", "FTA", "AS", "ORB", "DRB", "TOV", "Pts_off_TO", "2nd_Chance", "Fast_Break", "FGA", "FGM", "GP", "MIN", "Team_FGA", "Team_FTA", "Team_TOV", "Team_ORB", "Opp_DRB", "Team_MP", "RIM FGA", "RIM FGM", "PAINT FGA", "PAINT FGM", "MR FGA", "MR FGM", "COR3 FGA", "COR3 FGM", "ATB3 FGA", "ATB3 FGM"]
	
	# Filter only those that exist
	valid_cols = [c for c in cols_to_sum if c in combined.columns]
	
	# Group by Player and sum
	h2h_totals = combined.groupby('Player', as_index=False)[valid_cols].sum()

	# --- STEP 3: PLAYER DIVISOR LOGIC ---
	# Determine the divisor based on the sidebar toggle
	if avg_mode == "Season Value (Team GP)":
		# Divide by the total games the team played in the season/phase
		team_stats = get_per_game_volumes(target_team, league, season)
		divisor = float(team_stats.get('gp', 1))
	else:
		# Scouting Mode: Divide each player's totals by their own individual GP
		divisor = h2h_totals['GP'].replace(0, 1)

	# Apply the division to all statistical columns
	for col in h2h_totals.columns:
		if col in ['Player', 'Team_Name', 'GP'] or col in ["Team_FGA", "Team_FTA", "Team_TOV", "Team_ORB", "Opp_DRB", "Team_MP"]:
			continue
		h2h_totals[col] = h2h_totals[col] / divisor

	# --- LATE DIVISION MATH (Standard Percentages) ---
	h2h_totals['eFG%'] = h2h_totals.apply(lambda x: (x.get('FGM',0) + 0.5 * x.get('F3M',0)) / x['FGA'] if x.get('FGA', 0) > 0 else 0, axis=1)
	h2h_totals['TO%'] = h2h_totals.apply(lambda x: x.get('TOV',0) / (x.get('FGA',0) + 0.44 * x.get('FTA',0) + x.get('TOV',0)) if (x.get('FGA',0) + 0.44 * x.get('FTA',0) + x.get('TOV',0)) > 0 else 0, axis=1)
	h2h_totals['FTR'] = h2h_totals.apply(lambda x: x.get('FTM',0) / x['FGA'] if x.get('FGA', 0) > 0 else 0, axis=1)
	
	# --- SYNERGY MATH ---
	h2h_totals['USG%'] = h2h_totals.apply(lambda x: ((x.get('FGA',0) + 0.44 * x.get('FTA',0) + x.get('TOV',0)) * (x.get('Team_MP',200) / 5)) / (x.get('MIN',1) * (x.get('Team_FGA',1) + 0.44 * x.get('Team_FTA',0) + x.get('Team_TOV',0))) if (x.get('MIN',0) > 0 and (x.get('Team_FGA',0) + 0.44 * x.get('Team_FTA',0) + x.get('Team_TOV',0)) > 0) else 0, axis=1)
	h2h_totals['OR%'] = h2h_totals.apply(lambda x: (x.get('ORB',0) * (x.get('Team_MP',200) / 5)) / (x.get('MIN',1) * (x.get('Team_ORB',1) + x.get('Opp_DRB',0))) if (x.get('MIN',0) > 0 and (x.get('Team_ORB',0) + x.get('Opp_DRB',0)) > 0) else 0, axis=1)
	
	h2h_totals['Team_Name'] = target_team

	return h2h_totals
@st.cache_resource
def get_league_player_leaderboard_classic_v4(league, season, phase_ui, avg_mode): # Added avg_mode
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
def display_player_table(df, title, show_off_def=False, show_shooting=False, is_large_sample=False):
    if df is None or df.empty:
        st.warning(f"No player data found for {title}")
        return

    # --- UNIVERSAL HEADER FORMATTER ---
    def format_header(col):
        parts = [p.capitalize() for p in col.split('_')]
        new_name = "_".join(parts)
        return new_name.replace('Pt', 'PT').replace('Ft', 'FT').replace('Tp', 'TP').replace('Tov', 'TOV')

    df = df.rename(columns=format_header)

    # 1. SETUP COLUMN MAPPING
    col_map = {c.upper(): c for c in df.columns}
    def get_col(name): return col_map.get(name.upper())
    
    # Force p_col to be defined for the whole function
    p_col = get_col('PLAYER') or 'Player'

    # Define metrics using the NEW formatted names
    rankable_metrics = ['Total_NP', 'Net_Shooting', 'Net_TOV', 'Net_ORB', 'Net_FT', 'PTS', 'USG%', 'eFG%', 'TO%', 'OR%', 'FTR', 'Pts_off_TO', '2nd_Chance', 'Fast_Break']
    available_sorts = [s for s in rankable_metrics if get_col(s) is not None]

    # 2. SELECT SORTING
    sort_key = f"sort_box_{title.replace(' ', '_')}"
    sel_c1, sel_c2 = st.columns([1, 3])
    with sel_c1:
        chosen_sort = st.selectbox("Rank By:", available_sorts, key=sort_key)

    actual_sort_col = get_col(chosen_sort)
    is_ascending = True if chosen_sort == 'TO%' else False
    df_sorted = df.sort_values(actual_sort_col, ascending=is_ascending).copy()

    # 3. ROW MANAGEMENT
    is_team_mask = df_sorted[p_col].astype(str).str.contains('TEAM|EQUIP|TOTAL|--- TOTAL ---', case=False, na=False)
    df_humans = df_sorted[~is_team_mask].copy()
    df_team_row = df_sorted[is_team_mask].copy()
    df_humans.insert(0, 'Pos', range(1, len(df_humans) + 1))
    df_team_row.insert(0, 'Pos', 0)
    df_final = pd.concat([df_humans, df_team_row])

    # 4. BUILD COLUMN LIST
    cols_to_show = ['Pos', p_col]
    if get_col('Team_Name'): cols_to_show.append(get_col('Team_Name'))
    if get_col('GP'): cols_to_show.append(get_col('GP'))
    if get_col('Total_NP'): cols_to_show.append(get_col('Total_NP'))

    classic_cols = ['PTS', 'USG%', 'eFG%', 'TO%', 'OR%', 'FTR', 'Pts_off_TO', '2nd_Chance', 'Fast_Break']
    for c in classic_cols:
        actual_c = get_col(c)
        if actual_c and actual_c not in cols_to_show:
            cols_to_show.append(actual_c)

    def add_factor_group(factor_name):
        net, off, dfn = get_col(f'Net_{factor_name}'), get_col(f'Off_{factor_name}'), get_col(f'Def_{factor_name}')
        if net and net not in cols_to_show: cols_to_show.append(net)
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

    # 5. FORMATTING MAP
    format_map = {'Pos': "{:.0f}"}
    for col in numeric_cols:
        if '%' in col or col.upper() == 'FTR':
            format_map[col] = "{:.1%}" if '%' in col else "{:.3f}"
        elif col.upper() in [c.upper() for c in classic_cols]:
            format_map[col] = "{:.2f}"
        else:
            format_map[col] = "{:+.2f}"
    if get_col('GP') in df_final.columns: format_map[get_col('GP')] = "{:.0f}"

    # 6. INITIALIZE STYLER
    styler = df_final[cols_to_show].style.format(format_map)
    styler = styler.map(lambda x: 'color: transparent;' if x == 0 else '', subset=['Pos'])
    styler = styler.apply(lambda row: ['background-color: rgba(255,255,255,0.08);'] * len(row) if 'TEAM' in str(row[p_col]).upper() else [''] * len(row), axis=1)

    # 7. OUTLIER TEXT HIGHLIGHTING
    for col in numeric_cols:
        styler = styler.map(lambda x, c=col: highlight_scouting_outliers(x, c, actual_sort_col, is_large_sample), subset=[col])

    # 8. BACKGROUND GRADIENTS
    for col in numeric_cols:
        if col == actual_sort_col:
            c_min = df_final[col].min()
            c_max = df_final[col].max()
            
            if pd.isna(c_min) or pd.isna(c_max) or c_min >= c_max:
                c_min = -0.01
                c_max = 0.01

            if col.upper() in [c.upper() for c in classic_cols]:
                if col.upper() == 'TO%':
                    styler = styler.background_gradient(cmap=custom_redblue, subset=[col], vmin=c_min, vmax=c_max)
                elif col.upper() in ['PTS', 'USG%', 'PTS_OFF_TO', '2ND_CHANCE', 'FAST_BREAK', 'F2M', 'F2A', 'F3M', 'F3A']:
                    styler = styler.background_gradient(cmap=custom_wred, subset=[col], vmin=0, vmax=max(c_max, 1.0))
                else:
                    styler = styler.background_gradient(cmap=custom_bluered, subset=[col], vmin=c_min, vmax=c_max)
            else:
                v_max = max(df_final[col].abs().max(), 1.0)
                styler = styler.background_gradient(cmap=custom_bluered, subset=[col], vmin=-v_max, vmax=v_max)
                
    # 9. RENDER
    dynamic_height = (len(df_final) * 36) + 45
    col_config = {"Pos": st.column_config.NumberColumn("Pos", width="small"), p_col: st.column_config.TextColumn("Player", width="medium")}
    for col in numeric_cols: col_config[col] = st.column_config.NumberColumn(col, width="small")

    st.dataframe(styler, use_container_width=False, hide_index=True, height=dynamic_height, column_config=col_config)
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
def to_per_100(stats):
	"""Pace-adjusts situational stats to Per 100 Possessions"""
	if not stats: return {}
	
	# Calculate estimated possessions
	fga = stats.get('f2a', 0) + stats.get('f3a', 0)
	poss = fga + 0.44 * stats.get('fta', 0) - stats.get('orb', 0) + stats.get('tov', 0)
	
	if poss <= 0: return stats # Safety fallback
	
	# Create a copy and apply the multiplier to the situational fields
	multiplier = 100 / poss
	adj = stats.copy()
	adj['pts_off_to'] = stats.get('pts_off_to', 0) * multiplier
	adj['pts_2nd_ch'] = stats.get('pts_2nd_ch', 0) * multiplier
	adj['pts_fb'] = stats.get('pts_fb', 0) * multiplier
	
	return adj
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
	
	# 1. SCAN FILES
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
								df_names = pd.read_excel(file_path, header=None, nrows=3)
								t1_raw = str(df_names.iloc[1, 0]).strip()
								t2_raw = str(df_names.iloc[2, 0]).strip()
								
								raw_data.append({
									"league": league, "season": season, "phase_orig": phase,
									"group": group_name, "game_id": game_id, 
									"t1": t1_raw, "t2": t2_raw, "path": file_path
								})
							except: continue

	if not raw_data:
		print("!!! NO FILES FOUND !!!")
		return

	df_all = pd.DataFrame(raw_data)
	final_data = []

	# 2. PROCESS EACH SUBGROUP
	for (lg, sn, ph_orig, gp), df_group in df_all.groupby(['league', 'season', 'phase_orig', 'group']):
		
		is_postseason = any(x in ph_orig.lower() for x in ["playoff", "post", "final", "f4"])
		
		if is_postseason:
			df_group = df_group.copy().sort_values('game_id')
			df_group['matchup'] = df_group.apply(lambda x: "-".join(sorted([x['t1'], x['t2']])), axis=1)
			seen_counts = {}
			for _, row in df_group.iterrows():
				m_key = row['matchup']
				seen_counts[m_key] = seen_counts.get(m_key, 0) + 1
				round_label = f"Playoffs G{seen_counts[m_key]}"
				final_data.append(extract_game_details(row, lg, sn, ph_orig, gp, round_label))
		else:
				# --- THE FIXED ROUND LOGIC ---
				unique_teams = set(df_group['t1']) | set(df_group['t2'])
				n_teams = len(unique_teams)
				id_block_size = (n_teams + 1) // 2 
				base_id = df_group['game_id'].min()
				
				for _, row in df_group.iterrows():
					# FIX: Check if we are in Euroleague
					if lg == "Euroleague":
						# Euroleague rounds are 1-38. 
						# If your game IDs are strictly sequential, 
						# we just need to ensure we don't cap at 34.
						rnd_num = ((row['game_id'] - base_id) // id_block_size) + 1
						# Remove the 'min(..., 34)' cap
						display_rnd = int(rnd_num)
					else:
						# Keep existing FEB logic
						rnd_num = ((row['game_id'] - base_id) // id_block_size) + 1
						display_rnd = min(int(rnd_num), 34)
					
					round_label = f"Round {display_rnd:02d}"
					final_data.append(extract_game_details(row, lg, sn, ph_orig, gp, round_label))

	with open("game_index.json", "w") as f:
		json.dump(final_data, f, indent=4)
	print(f"--- [INDEXING COMPLETE] ---\n")
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
@st.cache_data
def get_league_zone_benchmarks(league, season):
	"""
	Dynamically calculates League Average Points Per Shot (PPS) 
	for each shot zone by aggregating all individual files in the season.
	"""
	zone_totals = {
		"Rim": {"pts": 0, "fga": 0},
		"Paint": {"pts": 0, "fga": 0},
		"Mid-Range": {"pts": 0, "fga": 0},
		"Corner 3": {"pts": 0, "fga": 0},
		"Above Break 3": {"pts": 0, "fga": 0}
	}
	
	target_path = os.path.join(DATA_BASE_PATH, league, season)
	
	# Walk the directory looking for individual aggregate files
	for root, dirs, filenames in os.walk(target_path):
		if "aggregate_individual" in root.lower(): 
			for f in filenames:
				if f.startswith('AGG_IND_') and f.endswith('.xlsx'):
					try:
						file_path = os.path.join(root, f)
						df = pd.read_excel(file_path)
						
						# Standardize column names for safe extraction (uppercase, stripped)
						cols = {str(c).strip().upper(): c for c in df.columns}
						
						def safe_sum(col_name):
							return df[cols[col_name]].sum() if col_name in cols else 0

						# Add to totals (multiply FGM by 2 or 3 to get actual Points)
						zone_totals["Rim"]["fga"] += safe_sum('RIM FGA')
						zone_totals["Rim"]["pts"] += safe_sum('RIM FGM') * 2
						
						zone_totals["Paint"]["fga"] += safe_sum('PAINT FGA')
						zone_totals["Paint"]["pts"] += safe_sum('PAINT FGM') * 2
						
						zone_totals["Mid-Range"]["fga"] += safe_sum('MR FGA')
						zone_totals["Mid-Range"]["pts"] += safe_sum('MR FGM') * 2
						
						zone_totals["Corner 3"]["fga"] += safe_sum('COR3 FGA')
						zone_totals["Corner 3"]["pts"] += safe_sum('COR3 FGM') * 3
						
						zone_totals["Above Break 3"]["fga"] += safe_sum('ATB3 FGA')
						zone_totals["Above Break 3"]["pts"] += safe_sum('ATB3 FGM') * 3
						
					except Exception:
						continue

	# Calculate PPS (Points / Attempts)
	zone_pps = {}
	
	# Fallbacks just in case a league has zero data yet
	fallbacks = {"Rim": 1.30, "Paint": 0.85, "Mid-Range": 0.80, "Corner 3": 1.15, "Above Break 3": 1.05}
	
	for zone, stats in zone_totals.items():
		if stats['fga'] > 0:
			zone_pps[zone] = stats['pts'] / stats['fga']
		else:
			zone_pps[zone] = fallbacks.get(zone, 1.0)
			
	return zone_pps
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
	labels = ["Pts off TO (Per 100)", "2nd Chance (Per 100)", "Fast Break (Per 100)"]
	
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
	x_range_max = max_val * 1.25

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
def plot_precision_component_radar(net_values, name):
    categories = ["Rim", "Paint", "Mid-Range", "Corner 3", "Above Break 3"]
    
    # 1. Round the values here to guarantee 2 decimals
    rounded_values = [round(float(v), 2) for v in net_values]
    
    # 2. Close the circle using rounded values
    plot_values = rounded_values + [rounded_values[0]]
    plot_cats = categories + [categories[0]]
    
    limit = max([abs(v) for v in net_values] + [0.3]) * 1.4

    fig = go.Figure()

    # 3. The radar area
    fig.add_trace(go.Scatterpolar(
        r=plot_values, 
        theta=plot_cats, 
        fill='toself', 
        name=name,
        line_color='#e06666', 
        fillcolor='rgba(224, 102, 102, 0.4)', 
        marker=dict(size=6),
        # This will now definitely show the rounded values with +/-, 2 decimals, and NP
        hovertemplate='%{theta}: %{r:+.2f} NP<extra></extra>' 
    ))

    # 4. Bolder zero-line (width=1)
    fig.add_trace(go.Scatterpolar(
        r=[0] * len(plot_cats), 
        theta=plot_cats,
        line=dict(color='#888888', width=1),
        showlegend=False,
        hoverinfo='skip'
    ))

    fig.update_layout(
        polar=dict(
            domain=dict(x=[0, 1], y=[0, 0.85]),
            radialaxis=dict(
                visible=True, 
                range=[-limit, limit], 
                tickfont=dict(size=9),
                gridcolor="#E5E7E9", 
                showline=True, 
                linewidth=1, 
                linecolor="rgba(0,0,0,0.1)"
            ),
            angularaxis=dict(
                tickfont=dict(size=10, weight="bold"), 
                rotation=90, 
                direction="clockwise"
            ),
            bgcolor="rgba(255, 255, 255, 0)"
        ),
        showlegend=False, 
        height=450, 
        margin=dict(l=50, r=50, t=20, b=20)
    )
    return fig
# --- MAIN APP ----
# --- CUSTOM THEMING (THE ULTIMATE VERSION) ---
st.markdown("""
<style>
		/* PHASE 1: SIDEBAR SPACING (Relaxed) */
		[data-testid="stSidebar"] [data-testid="stVerticalBlock"] {
			gap: 1.2rem !important; /* Increased from 0.5 for breathing room */
		}

		/* PHASE 2: MAIN PAGE LAYOUT (Restored) */
		[data-testid="stAppViewContainer"] [data-testid="stVerticalBlock"] {
			gap: 1.5rem !important; 
		}
		.block-container {
			padding-top: 3rem !important;
			padding-bottom: 3rem !important;
		}

		/* PHASE 3: SIDEBAR CORE THEME */
		[data-testid="stSidebar"] {
			background-color: #1e2130 !important;
		}
		
		/* PHASE 4: TEXT COLOR LOGIC (Fixes "Blank" bug) */
		/* Target generic text, but NOT text inside buttons or expander headers */
		[data-testid="stSidebar"] p, 
		[data-testid="stSidebar"] label, 
		[data-testid="stSidebar"] h1, 
		[data-testid="stSidebar"] h2,
		[data-testid="stSidebar"] h3,
		[data-testid="stSidebar"] span {
			color: #ffffff !important;
		}

		/* PHASE 5: LABELS & TITLES */
		[data-testid="stSidebar"] label {
			margin-bottom: 5px !important;
			font-size: 0.95rem !important;
			font-weight: 600 !important;
		}
		[data-testid="stSidebar"] h1 {
			margin-top: 0rem !important;
			font-size: 1.8rem !important;
		}

		/* PHASE 6: INFO BOXES (ALERTS) */
		[data-testid="stSidebar"] .stAlert {
			background-color: rgba(255, 255, 255, 0.07) !important;
			border: 1px solid #3f445e !important;
			border-left: 5px solid #FF4B4B !important;
		}
		[data-testid="stSidebar"] .stAlert p {
			color: #cbd5e1 !important;
		}

		/* PHASE 7: DIVIDERS */
		[data-testid="stSidebar"] hr {
			margin: 1rem 0 !important;
			border-color: rgba(255,255,255,0.1) !important;
		}

		/* PHASE 8: SELECTBOXES & MULTISELECT */
		[data-testid="stSidebar"] .stMultiSelect div[data-baseweb="select"] > div,
		[data-testid="stSidebar"] .stSelectbox div[data-baseweb="select"] > div {
			background-color: #2d324a !important;
			border: 1px solid #3f445e !important;
		}
		[data-testid="stSidebar"] div[data-baseweb="select"] * {
			color: #ffffff !important;
		}

		/* PHASE 9: BENCHMARK CHIPS */
		[data-testid="stSidebar"] code {
			background-color: #2d324a !important;
			color: #ffffff !important;
			border: 1px solid #3f445e !important;
			padding: 2px 6px !important;
		}

		/* PHASE 10: SLIDERS */
		[data-testid="stSidebar"] [data-baseweb="slider"] div[role="slider"] {
			background-color: #FF4B4B !important;
			border: 2px solid #ffffff !important;
		}
		[data-testid="stSidebar"] [data-baseweb="slider"] div[role="presentation"] > div:first-child > div {
			background: #FF4B4B !important;
		}

		/* PHASE 11: BUTTONS (Hover fix for Cloud) */
		[data-testid="stSidebar"] button {
			background-color: #2d324a !important;
			border: 1px solid #FF4B4B !important;
			color: #ffffff !important;
		}
		[data-testid="stSidebar"] button:hover {
			background-color: #FF4B4B !important;
			color: #ffffff !important;
			border: 1px solid #ffffff !important;
		}
		/* Fix for button text disappearing on hover */
		[data-testid="stSidebar"] button p {
			color: white !important;
		}
		
		/* PHASE 12: EXPANDERS (The specific fix for your screenshot) */
		/* This forces the header of the expander to NOT turn white on hover */
		[data-testid="stSidebar"] [data-testid="stExpander"] {
			background-color: #2d324a !important;
			border: 1px solid #3f445e !important;
		}
		
		/* The clickable header part */
		[data-testid="stSidebar"] [data-testid="stExpander"] summary {
			background-color: #2d324a !important;
			color: white !important;
		}

		[data-testid="stSidebar"] [data-testid="stExpander"] summary:hover {
			background-color: #3f445e !important;
		}

		/* Forces the text inside the header to remain visible */
		[data-testid="stSidebar"] [data-testid="stExpander"] summary p {
			color: white !important;
		}
		
		/* The content area inside the expander */
		[data-testid="stSidebar"] [data-testid="stExpander"] [data-testid="stVerticalBlock"] {
			background-color: #1e2130 !important;
			padding: 15px !important;
			border-top: 1px solid #3f445e !important;
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
# --- PLAYER AVERAGE LOGIC ---
st.sidebar.markdown("---")
avg_mode = st.sidebar.radio(
    "Player Stats Divisor", 
    ["Scouting (Player GP)", "Season Value (Team GP)"],
    key="avg_mode_radio"
)
# --- ADD THIS LINE: Reserve an empty space for future filters ---
sidebar_filters = st.sidebar.container()
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
    # 1. Prepare Logo
    ingame_logo_path = os.path.join(LOGOS_PATH, "InGame.png")
    logo_base64 = ""
    if os.path.exists(ingame_logo_path):
        with open(ingame_logo_path, "rb") as f:
            logo_base64 = base64.b64encode(f.read()).decode()

    # 2. Build the string (keep your existing logo logic)
    html_content = f"""
    <div style="text-align: center; padding: 40px 0px;">
        {'<img src="data:image/png;base64,' + logo_base64 + '" width="80" style="margin-bottom: 20px;">' if logo_base64 else ''}
        <h1 style="font-size: 3.5rem; margin-bottom: 10px;">Basketball 4-Factors Scouting</h1>
        <p style="font-size: 1.2rem; color: #666;">Advanced Analytics & Situational Performance Tool</p>
    </div>
    """

    # 3. Use st.html instead of st.markdown
    st.html(html_content)
    
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
        * **4-Factors Net Points**: Point-value impact of Shooting, Turnovers, Rebounding, and FTs.
        * **4F Classic + Situational Points**: Traditional 4-Factor percentages and situational scoring (Fast Break, 2nd Chance and Points off Turnovers).
        * **Individual Stats**: Track player impact game-by-game or league-wide.
        * **Radar View**: Inside the players tab, a radar view breaks down the Offensive Shooting Net Points added across 5 zones: Rim, Paint, Mid-Range, Corner 3, and Above Break 3. This helps identify if a player's shooting impact is concentrated in specific areas or more balanced across the court. It also shows their assisted / spacing impact.
        """)

    # --- NEW MASTER GLOSSARY SECTION ---
    st.markdown("---")
    st.markdown("Methodology & Glossary")
    
    # Using tabs to organize a lot of information into a small space
    tab_gen, tab_4f, tab_sit = st.tabs(["General Concepts", "4-Factors Net Points", "Situational Stats"])
    
    with tab_gen:
        col_g1, col_g2 = st.columns(2)
        with col_g1:
            st.markdown("**League Efficiency (Effic)**")
            st.caption("The baseline points scored per possession across the entire league for the selected season. Used as the 'multiplier' for Net Point costs. The value for each league is located in the sidebar in the System & Benchmarks section.")
            
            st.markdown("**OR% (Offensive Rebound %)**")
            st.caption("The percentage of available offensive rebounds grabbed by the attacking team. Used to calculate the value of a single rebound.The value for each league is located in the sidebar in the System & Benchmarks section.")

    with tab_4f:
        st.info("The 4-Factors Net Points model from Dean Oliver translates percentages into actual points won or lost relative to a league-average performance.")
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            st.markdown("**Shooting Net**")
            st.caption("Measures how many points a team made/saved via field goal accuracy compared to a league-average shooter taking the same number of shots. In the current settings, on offense a shooter gets 60% of the credit for a shot, while the assistant gets 30% and the rest of the teammates oncourt divides the rest (10%). On defense, a blocker gets 80% of the credit while the rest of the teammates oncourt divides the rest (20%)")
            
            st.markdown("**Turnovers Net**")
            st.caption("Calculates the point cost of possessions lost. Each turnover 'costs' the team the average value of a possession (Lg. Effic). On offense, the player turning the ball over gets 100% of the credit, while for team TOs the oncourt players get 20% each. On defense, a stealer gets 90% of the credit while the rest of the teammates oncourt divides the rest (10%). On team TOs the oncourt players of the defensive team get 20% each.")
        with col_f2:
            st.markdown("**Rebounding Net**")
            st.caption("Measures the impact of second possessions. It accounts for the value of the rebound weighted by the league's overall rebounding efficiency. Both on Offense and defense the rebounder gets 40% of the credit while the rest of the teammates oncourt divides the rest (60%)")
            
            st.markdown("**Free Throws Net**")
            st.caption("The difference between actual points made at the line and the expected points based on league average FT volume and efficiency. On offense the FT shooter gets 100% of the credit. On defense, the oncourt players get 20% each.")

    with tab_sit:
        st.markdown("**Points off Turnovers (TO-P)**")
        st.caption("Points scored on any possession that was initiated by an opponent's turnover.")
        
        st.markdown("**2nd Chance Points (2nd-C)**")
        st.caption("Points scored within 8 seconds immediately following an offensive rebound.")
        
        st.markdown("**Fast Break Points (FB-P)**")
        st.caption("Points scored on a play within 8 seconds of a defensive rebound, steal, or opponent's made basket. Includes points from FTs after a foul.")

        st.markdown("**Tier Benchmarks (vs League Avg)**")
        st.caption("In the dashboard, we categorize the Situational Edge into 4 tiers:")
        st.code("Elite (>+4pts) | Above Avg (>0pts) | Below Avg (<-4pts) | Bottom Tier (<-4pts)")
        
    # Stop execution here so the Matchup/Display logic doesn't run
    st.stop()
# --- 4. SYSTEM UTILITIES (Keep it simple) ---
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

# --- NEW LOGIC FOR TEAM VS LEAGUE ---
# --- NEW LOGIC FOR TEAM VS LEAGUE (NOW SUPPORTS TEAM VS TEAM) ---
if mode == "Season Aggregates per Team":
	teams = get_teams_in_league(league, season)
	
	# UI: Select Team 1 and Team 2 (Defaulting to League Average)
	t1 = sidebar_filters.selectbox("Select Team", teams, index=0, key="t1_agg")
	t2_options = ["League Average"] + teams
	t2 = sidebar_filters.selectbox("Compare With", t2_options, index=0, key="t2_agg")
	
	# Calculate Team 1 
	t1_off = get_per_game_volumes(t1, league, season, "TOTAL")
	max_gp_possible = int(t1_off.get('gp', 1))
	t1_def = get_per_game_volumes(t1, league, season, "Rival")
	
	lg_raw = calc_raw_factors(lg_data, lg_data['drb'], lg_effic, lg_orb_pct)
	t1_off_raw = calc_raw_factors(t1_off, t1_def['drb'], lg_effic, lg_orb_pct)
	t1_def_raw = calc_raw_factors(t1_def, t1_off['drb'], lg_effic, lg_orb_pct)
	
	i1_tot = {k: (t1_off_raw[k] - lg_raw[k]) + (lg_raw[k] - t1_def_raw[k]) for k in lg_raw}
	
	# Calculate Team 2 (or keep as 0.0 baseline if League Average is selected)
	if t2 == "League Average":
		t2_off, t2_def = lg_data.copy(), lg_data.copy()
		i2_tot = {k: 0.0 for k in lg_raw}
		i1_raw, i2_raw = (t1_off_raw, t1_def_raw), (lg_raw, lg_raw)
		header_title = f"Season Profile: {t1} vs League Average"
	else:
		t2_off = get_per_game_volumes(t2, league, season, "TOTAL")
		t2_def = get_per_game_volumes(t2, league, season, "Rival")
		
		t2_off_raw = calc_raw_factors(t2_off, t2_def['drb'], lg_effic, lg_orb_pct)
		t2_def_raw = calc_raw_factors(t2_def, t2_off['drb'], lg_effic, lg_orb_pct)
		
		i2_tot = {k: (t2_off_raw[k] - lg_raw[k]) + (lg_raw[k] - t2_def_raw[k]) for k in lg_raw}
		i1_raw, i2_raw = (t1_off_raw, t1_def_raw), (t2_off_raw, t2_def_raw)
		header_title = f"Season Profile: {t1} vs {t2}"

# --- 2. MODE: HEAD TO HEAD MATCHUP (Team A vs Team B Sum) ---
elif mode == "Head to Head Matchup":
	teams = get_teams_in_league(league, season)
	t1 = sidebar_filters.selectbox("Home Team", teams, index=0, key="t1_h2h")
	t2 = sidebar_filters.selectbox("Away Team", teams, index=min(1, len(teams)-1), key="t2_h2h")
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
	# 1. SIDEBAR SELECTIONS
	phases_avail = sorted(df_league['phase'].unique())
	sel_phase = sidebar_filters.selectbox("Select Phase", phases_avail, key="perf_phase_sel")
	
	df_phase_indexed = df_league[df_league['phase'] == sel_phase]
	teams_in_phase = sorted(list(set(df_phase_indexed['t1'].unique()) | set(df_phase_indexed['t2'].unique())))
	
	if not teams_in_phase:
		st.sidebar.warning("No teams found for this phase.")
	else:
		target_team = sidebar_filters.selectbox("Select Team", teams_in_phase, key="perf_team_sel")

		# 2. DATA PREPARATION
		df_team = df_league[(df_league['season'] == season) & (df_league['phase'] == sel_phase) & 
							((df_league['t1'] == target_team) | (df_league['t2'] == target_team))].copy()
		
		if df_team.empty:
			st.error("No games found for this team in the selected phase.")
		else:
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
				if team_logo: st.image(team_logo, width=120)
			with perf_header_col2:
				st.markdown(f'<h2 style="margin: 0; font-size: 1.6rem; line-height: 1.2; color: #1e2130;">Scouting Report: {target_team}</h2>', unsafe_allow_html=True)
				st.markdown(f"### {analysis_type} | **{sel_phase}**")
				st.caption(f"Season: {season}")

			# 4. MAIN PAGE FILTERS
			with st.expander("Filter Games", expanded=True):
				f_col1, f_col2 = st.columns(2)
				with f_col1: res_choice = st.multiselect("Game Result", ["Win", "Loss"], default=["Win", "Loss"], key="perf_res_choice")
				with f_col2: venue_choice = st.multiselect("Venue", ["Home", "Away"], default=["Home", "Away"], key="perf_venue_choice")
				
				all_rnds = sorted(df_team['round'].unique())
				range_rnds = st.select_slider("Round Range", options=all_rnds, value=(all_rnds[0], all_rnds[-1]), key="perf_range_rnds")
				
				with st.expander("Refine Rivals", expanded=False):
					select_all = st.checkbox("All Rivals", value=True, key="sel_all_rivals")
					rival_choice = st.multiselect("Specific Rivals:", all_opponents, default=all_opponents if select_all else [], key="perf_rival_choice")
			st.markdown("---")

			# --- 5. FILTERING LOGIC ---
			# Safe fallbacks to prevent state loss on deployed environments (collapsed expanders / inactive tabs)
			actual_res_choice = res_choice if res_choice else ["Win", "Loss"]
			actual_venue_choice = venue_choice if venue_choice else ["Home", "Away"]
			actual_rival_choice = rival_choice if rival_choice else all_opponents

			allowed_wins = [True if r == "Win" else False for r in actual_res_choice]
			
			try:
				start_idx, end_idx = all_rnds.index(range_rnds[0]), all_rnds.index(range_rnds[1])
				allowed_range = all_rnds[start_idx : end_idx+1]
			except Exception:
				allowed_range = all_rnds

			df_filtered = df_team[
				(df_team['is_win'].isin(allowed_wins)) & 
				(df_team['venue'].isin(actual_venue_choice)) & 
				(df_team['round'].isin(allowed_range)) &
				(df_team['opponent'].isin(actual_rival_choice))
			].copy()

			if df_filtered.empty:
				st.error("No games match this filter combination.")
			else:
				# --- TAB SYSTEM ---
				tab_team_view, tab_player_view = st.tabs(["Team Performance", "Player Performance"])
				with tab_team_view:
					view_type = st.radio("Analysis Perspective", ["Net Impact", "Offensive Impact", "Defensive Impact"], horizontal=True, key="perf_view_type_team")
					if analysis_type == "4-Factors Classic ":
						st.caption("**Note:** Situational points (Fast Break, 2nd Chance, TO-Pts) are standardized to **Per 100 Possessions** to compare performance across different game paces.")
					performance_data = []
					for _, row in df_filtered.sort_values('round').iterrows():
						g = get_raw_game_data_custom(row['path'])
						if not g: continue
						is_t1 = row['t1'] == target_team
						stats_self, stats_opp = (g['t1_stats'], g['t2_stats']) if is_t1 else (g['t2_stats'], g['t1_stats'])
						
						entry = {"Round": row['round'], "Opp_Logo": get_team_icon(row['opponent'], league), "Matchup": f"{'W' if row['is_win'] else 'L'} {'(H)' if row['venue']=='Home' else '(A)'} {row['pts1'] if is_t1 else row['pts2']}-{row['pts2'] if is_t1 else row['pts1']} vs {row['opponent']}", "Outcome": "W" if row['is_win'] else "L"}
						
						# 4F Math
						f_off = calc_raw_factors(stats_self, stats_opp['drb'], lg_effic, lg_orb_pct)
						f_def = calc_raw_factors(stats_opp, stats_self['drb'], lg_effic, lg_orb_pct)
						f_def_inv = {k: -v for k, v in f_def.items()} 
						for f in ["Shooting", "Rebounding", "Turnovers", "Free Throws"]:
							entry[f"{f}_Net"], entry[f"{f}_Off"], entry[f"{f}_Def"] = f_off[f] + f_def_inv[f], f_off[f], f_def_inv[f]

						if analysis_type == "4-Factors Net Points":
							display_vals = f_off if view_type == "Offensive Impact" else (f_def_inv if view_type == "Defensive Impact" else {k: f_off[k] + f_def_inv[k] for k in f_off})
							# Changed "Total 4F" -> "Total NP"
							entry.update({"Shooting": display_vals['Shooting'], "Turnovers": display_vals['Turnovers'], "Rebounding": display_vals['Rebounding'], "Free Throws": display_vals['Free Throws'], "Total NP": sum(display_vals.values())})
						else:
							# PACE ADJUSTMENT FOR PERFORMANCE TRENDS
							def get_adj_stats(s):
								fga = s.get('f2a',0) + s.get('f3a',0)
								poss = fga + 0.44*s.get('fta',0) + s.get('tov',0) - s.get('orb',0)
								mult = 100/poss if poss > 0 else 1
								return {
									"Pts off TO": s.get('pts_off_to', 0) * mult,
									"2nd Chance": s.get('pts_2nd_ch', 0) * mult,
									"Fast Break": s.get('pts_fb', 0) * mult
								}
							
							p_self, p_opp = get_4f_percentages(stats_self, stats_opp), get_4f_percentages(stats_opp, stats_self)
							s_adj = get_adj_stats(stats_self)
							o_adj = get_adj_stats(stats_opp)

							if view_type == "Offensive Impact":
								entry.update({**s_adj, **p_self})
							elif view_type == "Defensive Impact":
								entry.update({**o_adj, **p_opp})
							else:
								entry.update({
									"Pts off TO": s_adj['Pts off TO'] - o_adj['Pts off TO'],
									"2nd Chance": s_adj['2nd Chance'] - o_adj['2nd Chance'],
									"Fast Break": s_adj['Fast Break'] - o_adj['Fast Break']
								})
								entry.update({k: p_self[k] - p_opp[k] for k in p_self})
						performance_data.append(entry)

					perf_df = pd.DataFrame(performance_data)
					
					# --- DEFINE FORMATTING VARIABLES ---
					if analysis_type == "4-Factors Net Points":
						# Moved "Total NP" to the very end of this list
						cols_visible = ["Round", "Opp_Logo", "Matchup", "Total NP", "Shooting", "Turnovers", "Rebounding", "Free Throws"]
						format_dict = {k: "{:+.2f}" for k in ["Shooting", "Turnovers", "Rebounding", "Free Throws", "Total NP"]}
						grad_cols = ["Shooting", "Turnovers", "Rebounding", "Free Throws", "Total NP"]
					else:
						cols_visible = ["Round", "Opp_Logo", "Matchup", "Pts off TO", "2nd Chance", "Fast Break", "eFG%", "TO%", "ORB%", "FTR"]
						grad_cols = ["Pts off TO", "2nd Chance", "Fast Break", "eFG%", "TO%", "ORB%", "FTR"]
						if view_type == "Net Impact":
							format_dict = {k: "{:+.2f}" for k in ["Pts off TO", "2nd Chance", "Fast Break"]}
							format_dict.update({k: "{:+.1%}" for k in ["eFG%", "TO%", "ORB%"]})
							format_dict["FTR"] = "{:+.3f}"
						else:
							format_dict = {k: "{:.2f}" for k in ["Pts off TO", "2nd Chance", "Fast Break"]}
							format_dict.update({k: "{:.1%}" for k in ["eFG%", "TO%", "ORB%"]})
							format_dict["FTR"] = "{:.3f}"

					# --- APPLY STYLING & GRADIENTS ---
					styler = perf_df.style.format(format_dict).map(
						lambda x: 'color: #27ae60; font-weight: bold;' if x == "W" else ('color: #c0392b; font-weight: bold;' if x == "L" else ''), 
						subset=['Outcome']
					)
					
					if analysis_type == "4-Factors Net Points":
						# Updated safety check and gradient background call to target "Total NP"
						if perf_df['Total NP'].min() != perf_df['Total NP'].max():
							styler = styler.background_gradient(subset=['Total NP'], cmap=custom_bluered, vmin=-15, vmax=15)
					else:
						# SAFETY CHECK FOR CLASSIC STATS
						if view_type == "Net Impact":
							cols_to_grade = ['Pts off TO', '2nd Chance', 'Fast Break']
							for col in cols_to_grade:
								if perf_df[col].min() != perf_df[col].max():
									styler = styler.background_gradient(subset=[col], cmap=custom_bluered, vmin=-15, vmax=15)
						else:
							cols_to_grade = ['Pts off TO', '2nd Chance', 'Fast Break']
							for col in cols_to_grade:
								if perf_df[col].min() != perf_df[col].max():
									styler = styler.background_gradient(subset=[col], cmap=custom_wred, vmin=0, vmax=30)

					dynamic_height_team = (len(perf_df) * 36) + 45
					col_config_team = {"Opp_Logo": st.column_config.ImageColumn("Opp", width="small"), "Round": st.column_config.TextColumn("Rnd", width="small"), "Matchup": st.column_config.TextColumn("Matchup", width="medium")}
					for col in cols_visible:
						if col not in ["Round", "Opp_Logo", "Matchup"]: col_config_team[col] = st.column_config.NumberColumn(col, width="small")

					st.dataframe(styler, use_container_width=False, hide_index=True, height=dynamic_height_team, column_order=cols_visible, column_config=col_config_team)

				with tab_player_view:
					# Logic for individual data gatherer
					if analysis_type == "4-Factors Net Points":
						df_ind_agg = load_individual_aggregate(target_team, league, season, sel_phase)
					else:
						df_ind_agg = load_aggregated_classic_individual_data(target_team, league, season, sel_phase)
					
					if df_ind_agg is not None and not df_ind_agg.empty:
						agg_p_col = next((c for c in df_ind_agg.columns if c.upper() == 'PLAYER'), 'Player')
						# Helper to strip leading numbers (12. P. ORIOLA -> P. ORIOLA)
						def clean_p_name(t): return re.sub(r'^\d+[\s\.\-]*', '', str(t).strip())
						# Build A-Z unique clean list
						player_list = sorted(list(set([
							clean_p_name(p) for p in df_ind_agg[agg_p_col].unique()
							if not any(x in str(p).upper() for x in ['TEAM', 'TOTAL', 'EQUIP'])
						])))
						
						col_sel, col_view = st.columns([1, 3])
						with col_sel: selected_player = st.selectbox("Select Player", player_list, key=f"p_sel_{target_team}_{sel_phase}")
						with col_view:
							if analysis_type == "4-Factors Net Points":
								player_view_type = st.radio("Analysis Perspective", ["Net Impact", "Offensive Impact", "Defensive Impact"], horizontal=True, key=f"p_view_{target_team}")
	
						# NEW: Add the checkboxes horizontally
						cb_col1, cb_col2 = st.columns(2)
						with cb_col1: 
							expand_off_def_perf = st.checkbox("Show Offense/Defense Breakdown", value=False, key=f"cb_offdef_perf_{target_team}_{sel_phase}") if analysis_type == "4-Factors Net Points" else False
						with cb_col2: 
							expand_shoot_perf = st.checkbox("Show 2P/3P Shooting Split", value=False, key=f"cb_shoot_perf_{target_team}_{sel_phase}")

						def is_player_match(n_in_game, n_target):
							if not n_in_game or not n_target: return False
							# Clean both names to ensure jersey-less matching
							def sn(t):
								clean = clean_player_name(t)
								return re.sub(r'[\s\.]+', '', normalize_str(clean))
							return sn(n_in_game) == sn(n_target)

						player_perf_data = []
						for _, row in df_filtered.sort_values('round').iterrows():
							df_game_ind = load_single_game_individual(row['path'], target_team) if analysis_type == "4-Factors Net Points" else load_single_game_classic_individual(row['path'], target_team)
							if df_game_ind is not None and not df_game_ind.empty:
								g_p_col = next((c for c in df_game_ind.columns if c.upper() == 'PLAYER'), None)
								if g_p_col:
									match_mask = [is_player_match(name, selected_player) for name in df_game_ind[g_p_col]]
									p_game_row = df_game_ind[match_mask]
									if not p_game_row.empty:
										p_stats = p_game_row.iloc[0].to_dict()
										p_stats['Round'], p_stats['Opp_Logo'], p_stats['Matchup'] = row['round'], get_team_icon(row['opponent'], league), f"{'W' if row['is_win'] else 'L'} {row['opponent']}"
										player_perf_data.append(p_stats)

						else:
							player_df = pd.DataFrame(player_perf_data)
							p_cols = ["Round", "Opp_Logo", "Matchup"]
							
							if analysis_type == "4-Factors Net Points":
								prefix = {"Net Impact": "Net_", "Offensive Impact": "Off_", "Defensive Impact": "Def_"}[player_view_type]
								
								# 1. Determine the primary Net Points metric based on selected view
								main_np_col = "Total_NP" if player_view_type == "Net Impact" else f"{prefix}NP"
								p_numeric = []
								
								if main_np_col in player_df.columns:
									p_numeric.append(main_np_col)
								
								# 2. Gather factor metrics
								for f in ["Shooting", "TOV", "ORB", "FT"]:
									col_name = f"{prefix}{f}"
									if col_name in player_df.columns:
										p_numeric.append(col_name)
								
								exp_off = st.session_state.get(f"cb_offdef_perf_{target_team}_{sel_phase}", False)
								exp_shoot = st.session_state.get(f"cb_shoot_perf_{target_team}_{sel_phase}", False)

								if exp_off:
									# Add Off_NP and Def_NP if Off/Def breakdown is expanded
									for np_col in ["Off_NP", "Def_NP"]:
										if np_col in player_df.columns and np_col not in p_numeric:
											p_numeric.append(np_col)
											
									for f in ["Shooting", "TOV", "ORB", "FT"]:
										if f"Off_{f}" in player_df.columns and f"Off_{f}" not in p_numeric: p_numeric.append(f"Off_{f}")
										if f"Def_{f}" in player_df.columns and f"Def_{f}" not in p_numeric: p_numeric.append(f"Def_{f}")
										
								if exp_shoot:
									for shot in ['Off_2P', 'Off_3P', 'Def_2P', 'Def_3P']:
										if shot in player_df.columns and shot not in p_numeric: p_numeric.append(shot)
										
							else:
								# This handles the classic metrics when "4-Factors Classic" is active
								p_numeric = ["PTS", "USG%", "eFG%", "TO%", "OR%", "FTR", "Pts_off_TO", "2nd_Chance", "Fast_Break"]
								exp_shoot = st.session_state.get(f"cb_shoot_perf_{target_team}_{sel_phase}", False)
								if exp_shoot:
									for shot in ['F2M', 'F2A', 'F3M', 'F3A']:
										if shot in player_df.columns and shot not in p_numeric: p_numeric.append(shot)
							
							p_cols += [c for c in p_numeric if c in player_df.columns]
							
							# --- DYNAMIC FOCUS FOR PLAYER TRENDS ---
							focus_col, _ = st.columns([1, 3])
							with focus_col:
								p_focus = st.selectbox("Highlight Trend:", p_numeric, key=f"focus_p_{target_team}_{selected_player}")

							def get_col_format(col_name):
								if '%' in col_name: return "{:.1%}"
								if col_name == 'FTR': return "{:.3f}"
								if col_name in ['F2M', 'F2A', 'F3M', 'F3A']: return "{:.0f}"
								if analysis_type == "4-Factors Classic ": return "{:.2f}"
								return "{:+.2f}"

							p_format = {k: get_col_format(k) for k in p_numeric}
							styler_p = player_df[p_cols].style.format(p_format)
							
							# --- APPLY STYLING (Outliers + Thermal Focus) ---
							for col in [c for c in p_numeric if c in player_df.columns]:
								# 1. Apply the "Scout's Eye" Bold Text Highlighting (Force single-game logic)
								styler_p = styler_p.map(
									lambda x, c=col: highlight_scouting_outliers(x, c, p_focus, is_large_sample=False), 
									subset=[col]
								)

								# 2. Apply the Thermal Background to the focused column
								if col == p_focus:
									if player_df[col].min() != player_df[col].max():
										if 'TO%' in col: cmap = custom_redblue
										elif any(x in col for x in ['PTS', 'USG%', 'Pts_off_TO', '2nd_Chance', 'Fast_Break', 'F2M', 'F2A', 'F3M', 'F3A']):
											cmap = custom_wred
										else: cmap = custom_bluered
										
										styler_p = styler_p.background_gradient(subset=[col], cmap=cmap)

							dynamic_height_p = (len(player_df) * 36) + 45
							col_config_p = {"Opp_Logo": st.column_config.ImageColumn("Opp", width="small"), "Round": st.column_config.TextColumn("Rnd", width="small"), "Matchup": st.column_config.TextColumn("Matchup", width="medium")}
							for c in p_numeric: col_config_p[c] = st.column_config.NumberColumn(c, width="small")
							st.dataframe(styler_p, use_container_width=False, hide_index=True, height=dynamic_height_p, column_config=col_config_p)

elif mode == "Overall League Standings":
	# 1. Phase Selection
	phases_in_index = sorted(df_league['phase'].unique())
	phase_options = ["Overall Season"] + phases_in_index
	selected_phase = sidebar_filters.selectbox("Phase / Group", phase_options, key="standings_phase")
	
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
	
	with tab_standings_team:
		# PACE-ADJUSTMENT HELPER
		def to_per_100_standings(stats):
			if not stats: return stats
			fga = stats.get('f2a', 0) + stats.get('f3a', 0)
			poss = fga + 0.44 * stats.get('fta', 0) - stats.get('orb', 0) + stats.get('tov', 0)
			mult = 100 / poss if poss > 0 else 1
			res = stats.copy()
			for k in ['pts_off_to', 'pts_2nd_ch', 'pts_fb']:
				res[k] = res.get(k, 0) * mult
			return res

		if analysis_type == "4-Factors Classic ":
			st.caption("**Note:** Situational points (Fast Break, 2nd Chance, TO-Pts) are standardized to **Per 100 Possessions** for fair league-wide ranking.")

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

				# Apply Pace Adjustment
				t_off_adj = to_per_100_standings(t_off)
				t_def_adj = to_per_100_standings(t_def)

				entry = {"Team_Logo": get_team_icon(team, league), "Team": team}

				if analysis_type == "4-Factors Net Points":
					# (Keep your existing Net Points logic exactly as it is...)
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
					# UPDATED CLASSIC LOGIC: Use the ADJ (Per 100) stats
					p_off = get_4f_percentages(t_off, t_def)
					p_def = get_4f_percentages(t_def, t_off)
					
					if view_type == "Offensive Impact":
						entry.update({"Pts off TO": t_off_adj['pts_off_to'], "2nd Chance": t_off_adj['pts_2nd_ch'], "Fast Break": t_off_adj['pts_fb']})
						entry.update(p_off)
					elif view_type == "Defensive Impact":
						entry.update({"Pts off TO": t_def_adj['pts_off_to'], "2nd Chance": t_def_adj['pts_2nd_ch'], "Fast Break": t_def_adj['pts_fb']})
						entry.update(p_def)
					else:
						entry.update({
							"Pts off TO": t_off_adj['pts_off_to'] - t_def_adj['pts_off_to'],
							"2nd Chance": t_off_adj['pts_2nd_ch'] - t_def_adj['pts_2nd_ch'],
							"Fast Break": t_off_adj['pts_fb'] - t_def_adj['pts_fb']
						})
						p_net = {k: p_off[k] - p_def[k] for k in p_off}
						entry.update(p_net)
				league_results.append(entry)

		if not league_results:
			st.error(f"No data found for {selected_phase}")
		else:
			standings_df = pd.DataFrame(league_results)
			
			# --- 1. DYNAMIC SORT SELECTOR ---
			if analysis_type == "4-Factors Net Points":
				rank_cols = ["Net Points", "Shooting", "Turnovers", "Rebounding", "Free Throws"]
			else:
				# Matches the keys used in entry.update
				rank_cols = ["Pts off TO", "2nd Chance", "Fast Break", "eFG%", "TO%", "ORB%", "FTR"]
			
			# Ensure we only show metrics that actually exist in our data
			available_ranks = [c for c in rank_cols if c in standings_df.columns]
			
			rank_c1, rank_c2 = st.columns([1, 3])
			with rank_c1:
				chosen_team_rank = st.selectbox("Rank Teams By:", available_ranks, key="team_rank_sel")
			
			# --- 2. INTELLIGENT SORTING ---
			# For scouting: Higher is usually better, EXCEPT for Turnovers (Offensive) 
			# and Points Allowed (Defensive).
			is_ascending = False
			if chosen_team_rank == "TO%" and view_type == "Offensive Impact":
				is_ascending = True # Best team has the LOWEST turnover rate
			if view_type == "Defensive Impact" and "Pts" in chosen_team_rank:
				is_ascending = True # Best defense allows the LOWEST points

			# Perform the sort
			standings_df = standings_df.sort_values(by=chosen_team_rank, ascending=is_ascending).copy()
			
			# Reset the Position column based on the new sort
			if "Pos" in standings_df.columns:
				standings_df = standings_df.drop(columns=["Pos"])
			standings_df.insert(0, "Pos", range(1, len(standings_df) + 1))

			# --- 3. DEFINE COLUMNS AND FORMATTING ---
			if analysis_type == "4-Factors Net Points":
				cols_visible = ["Pos", "Team_Logo", "Team", "Net Points", "Shooting", "Turnovers", "Rebounding", "Free Throws"]
				format_dict = {k: "{:+.2f}" for k in ["Net Points", "Shooting", "Turnovers", "Rebounding", "Free Throws"]}
				grad_cols = ["Net Points", "Shooting", "Turnovers", "Rebounding", "Free Throws"]
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

			# --- 4. APPLY STYLING & GRADIENTS ---
			styler = standings_df[cols_visible].style.format(format_dict)

			for col in grad_cols:
				# DYNAMIC FOCUS: Only color the column the user selected to Rank by
				if col == chosen_team_rank:
					if analysis_type == "4-Factors Net Points" or view_type == "Net Impact":
						v_max = standings_df[col].abs().max()
						v_max = max(v_max, 1.0)
						vmin, vmax = -v_max, v_max
						cmap = custom_redblue if "TO%" in col else custom_bluered
					else:
						# Volume logic for Offensive/Defensive ranks
						vmin, vmax = standings_df[col].min(), standings_df[col].max()
						if view_type == "Offensive Impact":
							cmap = custom_redblue if "TO%" in col else custom_bluered
						else:
							# Defensive: Low points allowed = Red (Hot Defense)
							if any(x in col for x in ["TO%", "ORB%"]):
								cmap = custom_bluered 
							else:
								cmap = custom_redblue 
					
					styler = styler.background_gradient(cmap=cmap, subset=[col], vmin=vmin, vmax=vmax)

			# --- 5. RENDER ---
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
	# --- THE PLAYER TAB LOGIC ---
	with tab_standings_players:
		# 1. UI Filter Controls
		col_ctrl_l1, col_ctrl_l2, col_ctrl_l3 = st.columns([1, 1, 1])
		with col_ctrl_l1:
			exp_ld_offdef = st.checkbox("Show Offense/Defense Breakdown", value=False, key="cb_offdef_ld")
		with col_ctrl_l2:
			exp_ld_shoot = st.checkbox("Show 2P/3P Shooting Split", value=False, key="cb_shoot_ld")
		with col_ctrl_l3:
			# Direct GP Filter added here
			min_gp_ld = st.number_input("Min. Games Played (GP)", min_value=1, value=5, step=1, key="gp_filter_ld")
		
		# 2. Added Note for the user
		st.info(f"Note: Displaying players with a minimum of {min_gp_ld} games played.")
		st.markdown("---")

		with st.spinner("Gathering league-wide player data..."):
			# --- CALL DATA GATHERER ---
			if analysis_type == "4-Factors Net Points":
				df_league_players = get_league_player_leaderboard(league, season, selected_phase, avg_mode)
			else:
				df_league_players = get_league_player_leaderboard_classic_v4(league, season, selected_phase, avg_mode)
			
			# --- FILTER BY SELECTED TEAMS ---
			if df_league_players is not None and not df_league_players.empty:
				df_league_players = df_league_players[df_league_players['Team_Name'].isin(teams_to_analyze)]
				
				# --- NEW: APPLY THE GP FILTER DIRECTLY ---
				gp_col = next((c for c in df_league_players.columns if c.upper() == 'GP'), 'GP')
				if gp_col in df_league_players.columns:
					# Ensure numeric comparison
					df_league_players[gp_col] = pd.to_numeric(df_league_players[gp_col], errors='coerce').fillna(0)
					df_league_players = df_league_players[df_league_players[gp_col] >= min_gp_ld]
			
			if df_league_players is None or df_league_players.empty:
				st.warning(f"No individual player data found with at least {min_gp_ld} games played.")
			else:
				# Sorting logic
				if analysis_type == "4-Factors Net Points":
					if view_type == "Offensive Impact":
						sort_col, title_prefix = 'Off_NP', "Top 100 Offensive"
					elif view_type == "Defensive Impact":
						sort_col, title_prefix = 'Def_NP', "Top 100 Defensive"
					else:
						sort_col, title_prefix = 'Total_NP', "Top 100 Overall"
				else:
					sort_col, title_prefix = 'PTS', "Top 100 Classic"

				# Safe fallback if column is missing
				if sort_col not in df_league_players.columns:
					numeric_cols = df_league_players.select_dtypes(include=['number']).columns
					sort_col = numeric_cols[0] if not numeric_cols.empty else df_league_players.columns[0]

				df_leaderboard = df_league_players.sort_values(sort_col, ascending=False)
				
				st.markdown(f"### {title_prefix} Impact ({selected_phase})")
				
				# Render the table
				display_player_table(df_leaderboard.head(100), "League Leaderboard", exp_ld_offdef, exp_ld_shoot, is_large_sample=True)
# --- 5. MODE: GAMES BOXSCORES (Single Game) ---
else: 
	df_f = df_league[df_league['season'] == season].copy()
	phase_options = sorted(df_f['phase'].unique())
	phase = sidebar_filters.selectbox("Phase / Group", phase_options, key="phase_sel")
	df_f = df_f[df_f['phase'] == phase].copy()
	
	round_val = sidebar_filters.selectbox("Round", sorted(df_f['round'].unique()), key="round_sel")
	df_f = df_f[df_f['round'] == round_val].copy()
	
	df_f['display'] = df_f.apply(lambda x: f"{x['round']} | {x['t1']} ({x['pts1']}) vs {x['t2']} ({x['pts2']})", axis=1)
	game_display = sidebar_filters.selectbox("Game", df_f['display'].unique(), key="game_sel")
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
				if t2 == "League Average":
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
					st.markdown("#### Season-Long Net Points Edge")
					t1_total_net = sum(i1_tot.values())
					t2_total_net = sum(i2_tot.values())
					diff = t1_total_net - t2_total_net
					winner = t1 if diff > 0 else t2
					
					# Calculate difference in each factor to find key driver
					diff_stats = {k: i1_tot[k] - i2_tot[k] for k in i1_tot}
					best_driver = max(diff_stats, key=lambda k: abs(diff_stats[k]))

					m_col1, m_col2, m_col3, m_col4 = st.columns(4)
					with m_col1: st.metric(label=f"{t1} Net Impact", value=f"{t1_total_net:+.2f} pts")
					with m_col2: st.metric(label=f"{t2} Net Impact", value=f"{t2_total_net:+.2f} pts")
					with m_col3: st.metric(label="Overall Advantage", value=f"{abs(diff):+.2f} pts", delta=winner)
					with m_col4: st.metric(label="Key Difference", value=best_driver)
					st.markdown("---")
		else:
			# Handle CLASSIC Analysis
			def to_per_100(stats):
				"""Pace-adjusts situational stats to Per 100 Possessions"""
				if not stats: return {}
				
				# Calculate estimated possessions
				fga = stats.get('f2a', 0) + stats.get('f3a', 0)
				poss = fga + 0.44 * stats.get('fta', 0) - stats.get('orb', 0) + stats.get('tov', 0)
				
				if poss <= 0: return stats # Safety fallback
				
				# Create a copy and apply the multiplier to the situational fields
				multiplier = 100 / poss
				adj = stats.copy()
				adj['pts_off_to'] = stats.get('pts_off_to', 0) * multiplier
				adj['pts_2nd_ch'] = stats.get('pts_2nd_ch', 0) * multiplier
				adj['pts_fb'] = stats.get('pts_fb', 0) * multiplier
				
				return adj

			# 1. Determine which base stats we are looking at based on the mode
			if mode == "Games Boxscores": s1_plot, s2_plot = g['t1_stats'], g['t2_stats']
			elif mode == "Head to Head Matchup": s1_plot, s2_plot = t1_h2h_avg, t2_h2h_avg
			else: s1_plot, s2_plot = t1_off, t2_off
			
			# 2. Create the pace-adjusted dictionaries 
			s1_adj = to_per_100(s1_plot)
			s2_adj = to_per_100(s2_plot)
			lg_adj = to_per_100(lg_data)

			# 3. Render the Metric Cards
			if mode == "Head to Head Matchup" or mode == "Games Boxscores":
				st.markdown("#### Situational Scoring Edge (Per 100 Possessions)")
				
				t1_sit_total = s1_adj.get('pts_off_to', 0) + s1_adj.get('pts_2nd_ch', 0) + s1_adj.get('pts_fb', 0)
				t2_sit_total = s2_adj.get('pts_off_to', 0) + s2_adj.get('pts_2nd_ch', 0) + s2_adj.get('pts_fb', 0)
				sit_diff = t1_sit_total - t2_sit_total
				sit_winner = t1 if sit_diff > 0 else t2

				m_col1, m_col2, m_col3 = st.columns(3)
				with m_col1: st.metric(label=f"{t1} Sit. Pts/100", value=f"{t1_sit_total:.1f}")
				with m_col2: st.metric(label=f"{t2} Sit. Pts/100", value=f"{t2_sit_total:.1f}")
				with m_col3: st.metric(label="Sit. Advantage", value=f"{abs(sit_diff):+.1f} pts", delta=sit_winner)
				st.markdown("---")

			elif mode == "Season Aggregates per Team":
				st.markdown("#### Situational Profile (Per 100 Possessions)")
				
				t1_sit_total = s1_adj.get('pts_off_to', 0) + s1_adj.get('pts_2nd_ch', 0) + s1_adj.get('pts_fb', 0)
				
				if t2 == "League Average":
					lg_sit_total = lg_adj.get('pts_off_to', 0) + lg_adj.get('pts_2nd_ch', 0) + lg_adj.get('pts_fb', 0)
					
					sit_diff = t1_sit_total - lg_sit_total
					if sit_diff >= 4.0: tier_tag = "Elite"
					elif sit_diff >= 0: tier_tag = "Above Avg"
					elif sit_diff >= -4.0: tier_tag = "- Below Avg"
					else: tier_tag = "- Bottom Tier"

					m_col1, m_col2 = st.columns(2)
					with m_col1: st.metric(label=f"{t1} Total Sit. (Per 100)", value=f"{t1_sit_total:.1f}")
					with m_col2: st.metric(label="vs League Avg", value=f"{sit_diff:+.1f}", delta=tier_tag)
				else:
					t2_sit_total = s2_adj.get('pts_off_to', 0) + s2_adj.get('pts_2nd_ch', 0) + s2_adj.get('pts_fb', 0)
					sit_diff = t1_sit_total - t2_sit_total
					sit_winner = t1 if sit_diff > 0 else t2
					
					m_col1, m_col2, m_col3 = st.columns(3)
					with m_col1: st.metric(label=f"{t1} Total Sit. (Per 100)", value=f"{t1_sit_total:.1f}")
					with m_col2: st.metric(label=f"{t2} Total Sit. (Per 100)", value=f"{t2_sit_total:.1f}")
					with m_col3: st.metric(label="Sit. Advantage", value=f"{abs(sit_diff):+.1f} pts", delta=sit_winner)
				st.markdown("---")

		with st.container(border=True):
			if analysis_type == "4-Factors Net Points":
				# --- RENDER NET POINTS BAR CHART ---
				st.plotly_chart(plot_4f_comparison(i1_tot, i2_tot, t1, t2), use_container_width=True, key=f"chart_4f_final_{t1}_{t2}")
			else:
				# --- RENDER SITUATIONAL BAR CHART ---
				st.plotly_chart(plot_situational_comparison(s1_adj, s2_adj, t1, t2, lg_adj), use_container_width=True, key=f"chart_sit_final_{t1}_{t2}")
				
				# --- RENDER 4-FACTORS IDENTITY TABLES ---
				# Helper function to dynamically color the Gap text based on the metric
				def style_gap(val, factor_name):
					# For these factors, a POSITIVE gap is BAD (so we color it Blue)
					# Offense TO% (we want less), and Defense eFG%, ORB%, FTR (we want opponent to have less)
					negative_is_good = ["TO%", "Opp eFG%", "Opp ORB%", "Opp FTR"]
					
					if factor_name in negative_is_good:
						color = "#6fa8dc" if val > 0 else "#e06666"
					else:
						color = "#e06666" if val > 0 else "#6fa8dc"
						
					return f'color: {color}; font-weight: bold;' if abs(val) > 0.001 else ''

				# Helper to build the 4F dataframes identically
				def build_4f_styler(df, is_defense=False):
					styler = df.style.format({t1: "{:.1%}", t2: "{:.1%}", 'Gap': "{:+.1%}"})
					
					ftr_idx = 'Opp FTR' if is_defense else 'FTR'
					styler = styler.format(subset=pd.IndexSlice[[ftr_idx], ['Gap']], formatter="{:+.3f}")
					styler = styler.format(subset=pd.IndexSlice[[ftr_idx], [t1, t2]], formatter="{:.3f}")

					# Apply text coloring
					styler = styler.apply(lambda x: [style_gap(v, x.name) for v in x], axis=1, subset=['Gap'])
					
					# Apply background gradients
					if not is_defense:
						styler = styler.background_gradient(cmap=custom_bluered, subset=pd.IndexSlice[['eFG%', 'ORB%', 'FTR'], ['Gap']], vmin=-0.05, vmax=0.05)
						styler = styler.background_gradient(cmap=custom_redblue, subset=pd.IndexSlice[['TO%'], ['Gap']], vmin=-0.05, vmax=0.05)
					else:
						# On defense, higher eFG%, ORB%, FTR allowed is BAD (custom_redblue makes positive gaps Blue)
						styler = styler.background_gradient(cmap=custom_redblue, subset=pd.IndexSlice[['Opp eFG%', 'Opp ORB%', 'Opp FTR'], ['Gap']], vmin=-0.05, vmax=0.05)
						# On defense, higher TO% forced is GOOD (custom_bluered makes positive gaps Red)
						styler = styler.background_gradient(cmap=custom_bluered, subset=pd.IndexSlice[['Opp TO%'], ['Gap']], vmin=-0.05, vmax=0.05)
					
					return styler

				col_cfg = {
					"index": st.column_config.TextColumn("Factor", width="small"),
					t1: st.column_config.NumberColumn(width="small"),
					t2: st.column_config.NumberColumn(width="small"),
					"Gap": st.column_config.NumberColumn("Advantage", width="small")
				}

				# --- RENDER STRATEGY ---
				if mode == "Season Aggregates per Team":
					st.markdown("### 4-Factors Season Profile")
					c_off, c_def = st.columns(2)
					
					# 1. Calculate Offense vs League/Opponent
					p1_off = get_4f_percentages(t1_off, t1_def)
					p2_off = get_4f_percentages(t2_off, t2_def)
					df_off = pd.DataFrame([p1_off, p2_off], index=[t1, t2]).T
					df_off['Gap'] = df_off[t1] - df_off[t2]
					
					# 2. Calculate Defense vs League/Opponent
					# We pass the opponent's offense (t1_def) as the primary stat, and our defense (t1_off) as the secondary
					p1_def = get_4f_percentages(t1_def, t1_off)
					p2_def = get_4f_percentages(t2_def, t2_off)
					p1_def = {f"Opp {k}": v for k, v in p1_def.items()}
					p2_def = {f"Opp {k}": v for k, v in p2_def.items()}
					df_def = pd.DataFrame([p1_def, p2_def], index=[t1, t2]).T
					df_def['Gap'] = df_def[t1] - df_def[t2]
					
					with c_off:
						st.markdown("**Offensive Identity**")
						st.dataframe(build_4f_styler(df_off, False), use_container_width=True, height=175, column_config=col_cfg)
					with c_def:
						st.markdown("**Defensive Identity (Allowed)**")
						st.dataframe(build_4f_styler(df_def, True), use_container_width=True, height=175, column_config=col_cfg)
						
				else:
					# For Matchups & Single Games (A Closed System)
					st.markdown("### 4-Factors Matchup Identity")
					
					p1 = get_4f_percentages(s1_plot, s2_plot)
					p2 = get_4f_percentages(s2_plot, s1_plot)
					
					df_4f = pd.DataFrame([p1, p2], index=[t1, t2]).T
					df_4f['Gap'] = df_4f[t1] - df_4f[t2]
					
					c_left, c_mid, c_right = st.columns([1, 2, 1])
					with c_mid:
						st.dataframe(build_4f_styler(df_4f, False), use_container_width=True, height=175, column_config=col_cfg)

	with tab_players:
		is_large_sample_mode = (mode == "Season Aggregates per Team")

		# 1. UI Settings
		if analysis_type == "4-Factors Net Points":
			c_ui1, c_ui2 = st.columns(2)
			with c_ui1: expand_off_def = st.checkbox("Show Offense/Defense Breakdown", value=False, key="cb_offdef_match")
			with c_ui2: expand_shooting = st.checkbox("Show 2P/3P Shooting Split", value=False, key="cb_shoot_match")
		else:
			expand_off_def, expand_shooting = False, False

		st.markdown("---")
		
		# 2. GP Filter
		min_gp_filter = 1
		if mode in ["Season Aggregates per Team", "Head to Head Matchup"]:
			t_vol = get_per_game_volumes(t1, league, season)
			max_gp_possible = int(t_vol.get('gp', 1))
			if max_gp_possible > 1:
				c_gp, _ = st.columns([1, 3])
				with c_gp: min_gp_filter = st.slider("Min. Games Played", 1, max_gp_possible, 1, key="min_gp_slider")

		def apply_gp_filter(df, target_min):
			if df is None or df.empty: return df
			gp_col = next((c for c in df.columns if c.upper() == 'GP'), None)
			p_col = next((c for c in df.columns if c.upper() == 'PLAYER'), 'Player')
			if gp_col:
				df[gp_col] = pd.to_numeric(df[gp_col], errors='coerce').fillna(0)
				mask = (df[gp_col] >= target_min) | (df[p_col].astype(str).str.contains('TEAM|EQUIP|TOTAL|--- TOTAL ---', case=False, na=False))
				return df[mask].copy()
			return df

		# --- DUAL-DATA RENDERER ---
		def render_table_and_radar(df_table, df_zones, team_name, suffix):
			if df_table is None or df_table.empty:
				st.warning("No data found.")
				return

			tab_table, tab_radar = st.tabs(["Table", "Shot Radar"])

			with tab_table:
				display_player_table(df_table, f"{team_name} Individual Stats", expand_off_def, expand_shooting, is_large_sample_mode)

			with tab_radar:
				try:
					def deep_clean_name(name):
						if not name or pd.isna(name): return "", set()
						n = re.sub(r'\.(?=[A-Za-z])', '. ', str(name))
						n = re.sub(r'[\d\.\#\-\,]+', '', n.upper())
						n = normalize_str(n)
						# Keep words > 1 char (keeps LO, BA, SY, drops initials like M)
						words = [w for w in n.split() if len(w) > 1]
						return " ".join(words), set(words)

					p_col_t = next((c for c in df_table.columns if c.upper() == 'PLAYER'), 'Player')
					
					# Filter valid players for the dropdown
					valid_players = []
					for p in df_table[p_col_t].unique():
						p_str = str(p).upper().strip()
						if len(p_str) >= 2 and not any(x in p_str for x in ["TOTAL", "TEAM", "EQUIP"]):
							valid_players.append(p)
					
					if not valid_players:
						st.info("No player data available for radar.")
					else:
						col_sel, _ = st.columns([0.3, 0.7])
						with col_sel:
							sel_p = st.selectbox("Select Player:", sorted(valid_players), key=f"rad_sel_{suffix}")
						
						eff = float(lg_effic)
						orb_p = float(lg_orb_pct)
						
						row_t = df_table[df_table[p_col_t] == sel_p].iloc[0]
						div = float(row_t.get('GP', 1))

						if df_zones is not None and not df_zones.empty:
							p_col_z = next((c for c in df_zones.columns if c.upper() == 'PLAYER'), 'Player')
							target_clean, target_words = deep_clean_name(sel_p)
							
							def is_match(raw_val):
								raw_clean, raw_words = deep_clean_name(raw_val)
								# Safety fallback
								if not raw_words or not target_words: 
									from difflib import SequenceMatcher
									return SequenceMatcher(None, target_clean, raw_clean).ratio() > 0.8
								
								# Shared surname logic (If they share 'CALANCHE', it's him)
								if not target_words.isdisjoint(raw_words):
									return True
								
								from difflib import SequenceMatcher
								return SequenceMatcher(None, target_clean, raw_clean).ratio() > 0.7
							
							matches = df_zones[df_zones[p_col_z].apply(is_match)]

							if not matches.empty:
								p_row_z = matches.iloc[0]
								pgp = float(p_row_z.get('GP', 1))

								def get_t(k): 
									upper_cols = {str(c).upper().strip(): c for c in p_row_z.index}
									actual_key = upper_cols.get(k.upper())
									val = p_row_z[actual_key] if actual_key else 0.0
									return float(val) * pgp

								def calc_z_net(m_key, a_key, p_val):
									m, a = get_t(m_key), get_t(a_key)
									if div == 0: return 0.0
									net = (m * p_val) - (m * eff) - ((a - m) * (1 - orb_p) * eff)
									return (net * 0.60) / div

								radar_nets = [
									calc_z_net('RIM FGM', 'RIM FGA', 2),
									calc_z_net('PAINT FGM', 'PAINT FGA', 2),
									calc_z_net('MR FGM', 'MR FGA', 2),
									calc_z_net('COR3 FGM', 'COR3 FGA', 3),
									calc_z_net('ATB3 FGM', 'ATB3 FGA', 3)
								]

								if sum([abs(x) for x in radar_nets]) > 0.01:
									st.plotly_chart(plot_precision_component_radar(radar_nets, sel_p), use_container_width=True)
									
									row_t_upper = {str(k).upper(): v for k, v in row_t.items()}
									val_2p = float(row_t_upper.get('OFF_2P', 0))
									val_3p = float(row_t_upper.get('OFF_3P', 0))
									st.markdown("---")
									st.markdown(f"**Offensive Attribution for {sel_p}**")
									c1, c2, c3 = st.columns(3)
									c1.metric("Total Shot Net", f"{(val_2p+val_3p):+.2f}")
									c2.metric("Finishing (Radar Sum)", f"{sum(radar_nets):+.2f}")
									c3.metric("Spacing/Creation", f"{(val_2p+val_3p-sum(radar_nets)):+.2f}")
								else:
									st.info(f"Shot zone data for {sel_p} is empty (0/0 shots).")
							else:
								st.warning(f"Could not link shot zone data for {sel_p}. (Data mismatch between sources)")
								
								# --- DEBUG VISUALIZER ---
								st.error("🚨 DEBUGGING MODE ACTIVE")
								st.write(f"**Target Player Selected:** `{sel_p}`")
								st.write(f"**Target Words Searched:** `{target_words}`")
								
								st.write("**Here is every player the radar found in the Boxscore Data (`df_zones`) for this team:**")
								
								# Build a dataframe to show what the computer sees
								available_names = df_zones[p_col_z].unique()
								debug_data = []
								for raw_n in available_names:
									cln, wrds = deep_clean_name(raw_n)
									
									# Calculate the fuzzy ratio just to see what it was
									from difflib import SequenceMatcher
									fuzzy_ratio = SequenceMatcher(None, target_clean, cln).ratio()
									
									debug_data.append({
										"1. Raw Name in File": raw_n,
										"2. Cleaned Name": cln,
										"3. Extracted Words": str(wrds),
										"4. Fuzzy Match %": f"{fuzzy_ratio:.1%}"
									})
								
								st.dataframe(pd.DataFrame(debug_data), use_container_width=True)
								# --- END DEBUG VISUALIZER ---
				except Exception as e:
					st.error(f"Radar Error: {e}")

		# --- DATA ROUTING ---
		is_h2h = t2 != "League Average"
		c_phase = phase if 'phase' in locals() else None

		if is_h2h:
			p_tabs = st.tabs([f"{t1}", f"{t2}"])
			with p_tabs[0]:
				if analysis_type == "4-Factors Net Points":
					if mode == "Games Boxscores": d_t, d_z = load_single_game_individual(game_record['path'], t1), load_single_game_classic_individual(game_record['path'], t1)
					elif mode == "Head to Head Matchup": d_t, d_z = load_h2h_individual_data(t1, t2, league, season), load_aggregated_classic_individual_data(t1, league, season, c_phase, opponent_team=t2)
					else: d_t, d_z = load_individual_aggregate(t1, league, season, c_phase), load_aggregated_classic_individual_data(t1, league, season, c_phase)
				else:
					d_t = load_aggregated_classic_individual_data(t1, league, season, c_phase, opponent_team=t2) if mode == "Head to Head Matchup" else load_aggregated_classic_individual_data(t1, league, season, c_phase)
					d_z = d_t
				render_table_and_radar(apply_gp_filter(d_t, min_gp_filter), apply_gp_filter(d_z, min_gp_filter), t1, "t1_h2h")
				
			with p_tabs[1]:
				if analysis_type == "4-Factors Net Points":
					if mode == "Games Boxscores": d_t, d_z = load_single_game_individual(game_record['path'], t2), load_single_game_classic_individual(game_record['path'], t2)
					elif mode == "Head to Head Matchup": d_t, d_z = load_h2h_individual_data(t2, t1, league, season), load_aggregated_classic_individual_data(t2, league, season, c_phase, opponent_team=t1)
					else: d_t, d_z = load_individual_aggregate(t2, league, season, c_phase), load_aggregated_classic_individual_data(t2, league, season, c_phase)
				else:
					d_t = load_aggregated_classic_individual_data(t2, league, season, c_phase, opponent_team=t1) if mode == "Head to Head Matchup" else load_aggregated_classic_individual_data(t2, league, season, c_phase)
					d_z = d_t
				render_table_and_radar(apply_gp_filter(d_t, min_gp_filter), apply_gp_filter(d_z, min_gp_filter), t2, "t2_h2h")
		else:
			if analysis_type == "4-Factors Net Points":
				if mode == "Games Boxscores": d_t, d_z = load_single_game_individual(game_record['path'], t1), load_single_game_classic_individual(game_record['path'], t1)
				else: d_t, d_z = load_individual_aggregate(t1, league, season, c_phase), load_aggregated_classic_individual_data(t1, league, season, c_phase)
			else:
				d_t = load_aggregated_classic_individual_data(t1, league, season, c_phase)
				d_z = d_t
			render_table_and_radar(apply_gp_filter(d_t, min_gp_filter), apply_gp_filter(d_z, min_gp_filter), t1, "t1_single")
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