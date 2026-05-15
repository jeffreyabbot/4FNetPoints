import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import os
import tempfile
from fpdf import FPDF
import json
import re
from fpdf.enums import XPos, YPos
import matplotlib.pyplot as plt
import io

# --- CONFIGURATION ---
DATA_BASE_PATH = "informes_data"
LOGOS_PATH = "logos"

LEAGUE_CONFIG = {
    "ACB": {"games_per_round": 9, "logo": "acb.png"},
    "Euroleague": {"games_per_round": 10, "logo": "EL.png"}, # EL is 18 teams now
    "Segunda FEB": {"games_per_round": 7, "logo": "FEB.png"}, # 14 teams per group
    "Tercera FEB": {"games_per_round": 7, "logo": "FEB.png"}, # Usually 14 teams
}
def clean_num(val):
    if pd.isna(val) or val == "" or val == "-": return 0.0
    try: return float(val)
    except: return 0.0

# --- HELPERS ---
def create_pdf_chart_mpl(data_l, data_r, team_l, team_r):
    labels = ["Shooting", "Rebounding", "Turnovers", "Free Throws"]
    vals_l = [data_l[k] for k in labels]
    vals_r = [data_r[k] for k in labels]
    
    # Create plot
    fig, ax = plt.subplots(figsize=(10, 5))
    y = range(len(labels))
    width = 0.35
    
    # Plot bars (Horizontal like your Plotly chart)
    # Color 1: Blue (#2980B9), Color 2: Gold (#7E6605)
    bar1 = ax.barh([i + width/2 for i in y], vals_l, width, label=team_l, color='#2980B9')
    bar2 = ax.barh([i - width/2 for i in y], vals_r, width, label=team_r, color='#7E6605')
    
    # Add labels on bars
    ax.bar_label(bar1, fmt='%+.1f', padding=3, color='white', label_type='center', fontsize=9, weight='bold')
    ax.bar_label(bar2, fmt='%+.1f', padding=3, color='white', label_type='center', fontsize=9, weight='bold')
    
    # Formatting
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis() # Labels top-to-bottom
    ax.axvline(0, color='black', linewidth=1) # Zero line
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, 1.1), ncol=2, frameon=False)
    
    # Save to buffer
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf
def get_per_game_volumes_by_phase(team_name, league, season, phase, row_label="TOTAL"):
    # Convert UI phase name (e.g. "Regular Season - ESTE") back to folder name ("Regular_Season")
    # We take the part before the " - " and replace spaces with underscores
    folder_phase = phase.split(" - ")[0].replace(" ", "_")
    target_path = os.path.join(DATA_BASE_PATH, league, season, folder_phase, "aggregate")
    target_filename = f"AGGREGATE_{team_name}.xlsx"
    file_path = os.path.join(target_path, target_filename)
    
    # Default empty stats in case file is missing
    empty_stats = {"gp": 1, "pts": 0, "f2m": 0, "f2a": 0, "f3m": 0, "f3a": 0, "ftm": 0, "fta": 0, "drb": 0, "orb": 0, "tov": 0}

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
                "orb": clean_num(row_t[11])/gp, "tov": clean_num(row_t[15])/gp
            }
        except: 
            return empty_stats
    return empty_stats
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

def get_raw_game_data_custom(file_path):
    df = pd.read_excel(file_path, header=None)
    total_rows = df[df[0] == "TOTAL"]
    if len(total_rows) < 2: return None
    t1_row, t2_row = total_rows.iloc[0], total_rows.iloc[1]
    def parse_row(row):
        return {"pts": clean_num(row[1]), "f2m": clean_num(row[2]), "f2a": clean_num(row[3]),
                "f3m": clean_num(row[4]), "f3a": clean_num(row[5]), "ftm": clean_num(row[6]),
                "fta": clean_num(row[7]), "drb": clean_num(row[9]), "orb": clean_num(row[10]), "tov": clean_num(row[14])}
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
        
        # Determine if we use Regular Season logic or Playoff logic
        is_postseason = "playoff" in ph_orig.lower() or "post" in ph_orig.lower()
        
        if is_postseason:
            # --- PLAYOFF LOGIC ---
            # Identify unique matchups regardless of who is home/away
            # We sort team names alphabetically to create a 'Matchup Key'
            df_group = df_group.copy()
            df_group['matchup'] = df_group.apply(lambda x: "-".join(sorted([x['t1'], x['t2']])), axis=1)
            
            # Sort by game_id to ensure Game 1 comes before Game 2
            df_group = df_group.sort_values('game_id')
            
            # Count occurrences per matchup
            matchup_counts = df_group['matchup'].value_counts()
            
            # Label games
            # We track how many times we've seen this matchup so far
            seen_counts = {}
            for _, row in df_group.iterrows():
                m_key = row['matchup']
                seen_counts[m_key] = seen_counts.get(m_key, 0) + 1
                
                if matchup_counts[m_key] == 1:
                    round_label = "Play-In"
                else:
                    round_label = f"Game {seen_counts[m_key]}"
                
                # Extract scores and add to final
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
    total_stats = {"pts": 0, "poss": 0, "f2m": 0, "f2a": 0, "f3m": 0, "f3a": 0, "ftm": 0, "fta": 0, "orb": 0, "drb": 0, "tov": 0, "gp": 0}
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

def get_per_game_volumes(team_name, league, season, row_label="TOTAL"): # Added season param
    target_filename = f"AGGREGATE_{team_name}.xlsx"
    season_path = os.path.join(DATA_BASE_PATH, league, season)
    
    for root, dirs, files in os.walk(season_path):
        if target_filename in files:
            df = pd.read_excel(os.path.join(root, target_filename), header=None)
            row_t = df[df[0] == row_label].iloc[0]
            gp = clean_num(row_t[1])
            return {"gp": gp if gp > 0 else 1, "pts": clean_num(row_t[2])/gp, "f2m": clean_num(row_t[3])/gp,
                    "f2a": clean_num(row_t[4])/gp, "f3m": clean_num(row_t[5])/gp, "f3a": clean_num(row_t[6])/gp,
                    "ftm": clean_num(row_t[7])/gp, "fta": clean_num(row_t[8])/gp, "drb": clean_num(row_t[10])/gp,
                    "orb": clean_num(row_t[11])/gp, "tov": clean_num(row_t[15])/gp}
    return {"gp": 1, "pts": 0, "f2m": 0, "f2a": 0, "f3m": 0, "f3a": 0, "ftm": 0, "fta": 0, "drb": 0, "orb": 0, "tov": 0}

def plot_4f_comparison(data_l, data_r, team_l, team_r, is_pdf=False):
    labels =["Shooting", "Rebounding", "Turnovers", "Free Throws"]
    vals_l, vals_r = [data_l[k] for k in labels], [data_r[k] for k in labels]
    
    fig = go.Figure()
    
    # Home Team
    fig.add_trace(go.Bar(
        y=labels, x=vals_l, orientation='h', name=team_l, 
        marker_color='#2980B9', text=[f"{v:+.1f}" for v in vals_l], 
        textposition='auto', insidetextfont=dict(color='white', size=11),
        cliponaxis=False
    ))
    
    # Away Team
    fig.add_trace(go.Bar(
        y=labels, x=vals_r, orientation='h', name=team_r, 
        marker_color="#7E6605", text=[f"{v:+.1f}" for v in vals_r], 
        textposition='auto', insidetextfont=dict(color='white', size=11),
        cliponaxis=False
    ))
    
    fig.update_layout(
        barmode='group', height=400,
        margin=dict(l=100, r=100, t=20, b=40),
        xaxis=dict(
            showgrid=True, gridcolor='#E5E7E9', griddash='dot',
            zeroline=True, zerolinecolor='#34495e', zerolinewidth=1.5
        ),
        yaxis=dict(autorange="reversed", showgrid=False),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        plot_bgcolor='white'
    )
    return fig
from fpdf.enums import XPos, YPos

from fpdf.enums import XPos, YPos

from fpdf.enums import XPos, YPos
def generate_performance_pdf(df, team, league, season, view_type):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, f"{team} - {view_type} Log", ln=True, align='C')
    pdf.set_font("Helvetica", '', 12)
    pdf.cell(0, 10, f"{league} {season}", ln=True, align='C')
    pdf.ln(10)

    pdf.set_font("Helvetica", 'B', 9)
    # Updated Header name to Matchup
    cols = ["Round", "Matchup", "Shoot", "TOv", "Reb", "FT", "Total"]
    widths = [20, 60, 22, 22, 22, 22, 22]
    for i, col in enumerate(cols):
        pdf.cell(widths[i], 8, col, border=1, align='C')
    pdf.ln()

    pdf.set_font("Helvetica", '', 8)
    for _, row in df.iterrows():
        
        match_text = str(row['Matchup'])
        
        pdf.cell(widths[0], 7, str(row['Round']), border=1, align='C')
        pdf.cell(widths[1], 7, match_text, border=1)
        pdf.cell(widths[2], 7, f"{row['Shooting']:+.2f}", border=1, align='C')
        pdf.cell(widths[3], 7, f"{row['Turnovers']:+.2f}", border=1, align='C')
        pdf.cell(widths[4], 7, f"{row['Rebounding']:+.2f}", border=1, align='C')
        pdf.cell(widths[5], 7, f"{row['Free Throws']:+.2f}", border=1, align='C')
        pdf.cell(widths[6], 7, f"{row['Total 4F']:+.2f}", border=1, align='C')
        pdf.ln()
        if pdf.get_y() > 260: pdf.add_page()
    return bytes(pdf.output(dest='S'))

def generate_standings_pdf(df, fig, league, season, phase):
    pdf = FPDF()
    pdf.add_page()
    
    # --- PAGE 1: TABLE ---
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, f"{league} - {season}", ln=True, align='C')
    pdf.set_font("Helvetica", 'B', 12)
    pdf.cell(0, 10, f"Standings Breakdown: {phase}", ln=True, align='C')
    pdf.ln(5)

    # Table Headers
    pdf.set_font("Helvetica", 'B', 9)
    pdf.set_fill_color(230, 230, 230)
    cols = ["Rank", "Team", "Shoot", "TOv", "Reb", "FT", "Net"]
    widths = [12, 65, 23, 23, 23, 23, 21]
    
    for i, col in enumerate(cols):
        pdf.cell(widths[i], 8, col, border=1, align='C', fill=True)
    pdf.ln()

    # Table Rows
    pdf.set_font("Helvetica", '', 8)
    for _, row in df.iterrows():
        pdf.cell(widths[0], 7, str(row['Rank']), border=1, align='C')
        pdf.cell(widths[1], 7, str(row['Team'])[:35], border=1)
        pdf.cell(widths[2], 7, f"{row['Shooting']:+.2f}", border=1, align='C')
        pdf.cell(widths[3], 7, f"{row['Turnovers']:+.2f}", border=1, align='C')
        pdf.cell(widths[4], 7, f"{row['Rebounding']:+.2f}", border=1, align='C')
        pdf.cell(widths[5], 7, f"{row['Free Throws']:+.2f}", border=1, align='C')
        pdf.cell(widths[6], 7, f"{row['Net Points']:+.2f}", border=1, align='C')
        pdf.ln()

    # --- PAGE 2: CHART ---
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 14)
    pdf.cell(0, 10, "Shooting vs Ball Security Map", ln=True, align='C')
    pdf.ln(10)
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmpfile:
        # High resolution export
        fig.write_image(tmpfile.name, format="png", width=1200, height=700, scale=3)
        # Position image on the middle of the second page
        pdf.image(tmpfile.name, x=5, y=30, w=200)

    return bytes(pdf.output(dest='S'))
def generate_standings_pdf(df, league, season, phase):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, f"{league} Standings - {season}", ln=True, align='C')
    pdf.set_font("Helvetica", '', 12)
    pdf.cell(0, 10, f"Phase: {phase}", ln=True, align='C')
    pdf.ln(10)

    # Table Headers
    pdf.set_font("Helvetica", 'B', 9)
    cols = ["Rank", "Team", "Shoot", "TOv", "Reb", "FT", "Net"]
    widths = [12, 65, 23, 23, 23, 23, 21]
    for i, col in enumerate(cols):
        pdf.cell(widths[i], 8, col, border=1, align='C')
    pdf.ln()

    # Table Rows
    pdf.set_font("Helvetica", '', 8)
    for _, row in df.iterrows():
        pdf.cell(widths[0], 7, str(row['Rank']), border=1, align='C')
        pdf.cell(widths[1], 7, str(row['Team'])[:35], border=1)
        pdf.cell(widths[2], 7, f"{row['Shooting']:+.2f}", border=1, align='C')
        pdf.cell(widths[3], 7, f"{row['Turnovers']:+.2f}", border=1, align='C')
        pdf.cell(widths[4], 7, f"{row['Rebounding']:+.2f}", border=1, align='C')
        pdf.cell(widths[5], 7, f"{row['Free Throws']:+.2f}", border=1, align='C')
        pdf.cell(widths[6], 7, f"{row['Net Points']:+.2f}", border=1, align='C')
        pdf.ln()
    return bytes(pdf.output(dest='S'))
def generate_performance_pdf(df, team, league, season, view_type):
    pdf = FPDF()
    pdf.add_page()
    
    # Header
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, f"Scouting Report: {team}", ln=True, align='C')
    pdf.set_font("Helvetica", '', 12)
    pdf.cell(0, 8, f"{league} {season} | {view_type}", ln=True, align='C')
    pdf.ln(5)

    # --- NEW: BATCH SCOUTING SUMMARY SECTION ---
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Helvetica", 'B', 11)
    pdf.cell(0, 10, "  Batch Scouting Summary (Averages)", border=1, ln=True, fill=True)
    
    pdf.set_font("Helvetica", '', 9)
    # Define factors to summarize
    factors = ["Shooting", "Rebounding", "Turnovers", "Free Throws"]
    
    # Draw a summary box for each factor
    for f in factors:
        net_val = df[f"{f}_Net"].mean()
        off_val = df[f"{f}_Off"].mean()
        def_val = df[f"{f}_Def"].mean()
        
        # Line text
        summary_line = f" {f}: Net {net_val:+.2f} | Offense: {off_val:+.2f} | Defense: {def_val:+.2f}"
        pdf.cell(0, 7, summary_line, border='LR', ln=True)
    
    # Bottom border of the summary box
    pdf.cell(0, 0, "", border='T', ln=True)
    pdf.ln(8)

    # --- GAME LOG TABLE ---
    pdf.set_font("Helvetica", 'B', 10)
    pdf.set_fill_color(230, 230, 230)
    cols = ["Round", "Matchup", "Shoot", "TOv", "Reb", "FT", "Total"]
    widths = [20, 60, 22, 22, 22, 22, 22]
    
    for i, col in enumerate(cols):
        pdf.cell(widths[i], 8, col, border=1, align='C', fill=True)
    pdf.ln()

    pdf.set_font("Helvetica", '', 8)
    for _, row_data in df.iterrows():
        # Clean icons for PDF safety
        match_text = str(row_data['Matchup'])
        match_text = match_text.replace("🟢", "W").replace("🔴", "L").replace("🏠", "(H)").replace("✈️", "(A)").replace("✈", "(A)")
        match_text = match_text.encode('ascii', 'ignore').decode('ascii')
        
        pdf.cell(widths[0], 7, str(row_data['Round']), border=1, align='C')
        pdf.cell(widths[1], 7, match_text, border=1)
        pdf.cell(widths[2], 7, f"{row_data['Shooting']:+.2f}", border=1, align='C')
        pdf.cell(widths[3], 7, f"{row_data['Turnovers']:+.2f}", border=1, align='C')
        pdf.cell(widths[4], 7, f"{row_data['Rebounding']:+.2f}", border=1, align='C')
        pdf.cell(widths[5], 7, f"{row_data['Free Throws']:+.2f}", border=1, align='C')
        pdf.cell(widths[6], 7, f"{row_data['Total 4F']:+.2f}", border=1, align='C')
        pdf.ln()
        
        if pdf.get_y() > 270:
            pdf.add_page()
            
    return bytes(pdf.output(dest='S'))
def generate_pdf_report(chart_buf, t1, t2, lg_effic, lg_orb_pct, i1_tot, i1_off, i1_def, i2_tot, i2_off, i2_def, text_t1, text_t2, summary_data=None):
    pdf = FPDF()
    pdf.add_page()
    
    # Title
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, f"4-Factors Matchup: {t1} vs {t2}", ln=True, align='C')
    pdf.ln(5)
    
    # --- INSERT THE CHART IMAGE ---
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmpfile:
        tmpfile.write(chart_buf.getbuffer())
        pdf.image(tmpfile.name, x=15, w=180)
    pdf.ln(5)
    
    # 1. Scouting Interpretation Section
    pdf.set_font("Helvetica", 'B', 12)
    pdf.cell(0, 8, "Scouting Interpretation", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    # Print Headers ONCE outside the loop
    pdf.set_font("Helvetica", 'B', 9)
    pdf.cell(90, 6, f"{t1} vs Avg", new_x=XPos.RIGHT, new_y=YPos.TOP)
    pdf.cell(90, 6, f"{t2} vs Avg", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    # Prepare text
    pdf.set_font("Helvetica", '', 8)
    clean_t1 = [s.replace("•", "-") for s in text_t1]
    clean_t2 = [s.replace("•", "-") for s in text_t2]
    
    # Print Rows
    for t1_str, t2_str in zip(clean_t1, clean_t2):
        start_y = pdf.get_y()
        # Left Column
        pdf.set_xy(10, start_y)
        pdf.multi_cell(90, 4, t1_str)
        y_left = pdf.get_y()
        # Right Column
        pdf.set_xy(110, start_y) 
        pdf.multi_cell(90, 4, t2_str)
        y_right = pdf.get_y()
        # Sync: move to bottom of the tallest column + padding
        pdf.set_y(max(y_left, y_right) + 2)

    # 2. Offense vs Defense Breakdown
    pdf.ln(5)
    pdf.set_font("Helvetica", 'B', 12)
    pdf.cell(0, 8, "Offense vs Defense Net Breakdown", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    
    pdf.set_font("Helvetica", '', 8)
    factors =["Shooting", "Turnovers", "Rebounding", "Free Throws"]
    for f in factors:
        y_row = pdf.get_y()
        # Use simpler strings to ensure they fit in the 90mm width
        t1_line = f"{f}: Net {i1_tot[f]:+.1f} | O {i1_off[f]:+.1f} | D {i1_def[f]:+.1f}"
        t2_line = f"{f}: Net {i2_tot[f]:+.1f} | O {i2_off[f]:+.1f} | D {i2_def[f]:+.1f}"
        
        pdf.set_xy(10, y_row)
        pdf.cell(90, 5, f"{t1_line}")
        pdf.set_xy(110, y_row)
        pdf.cell(90, 5, f"{t2_line}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    # 3. Final Match Summary
    if summary_data:
        pdf.ln(5)
        pdf.set_font("Helvetica", 'B', 12)
        pdf.cell(0, 8, "Final Match Summary", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("Helvetica", '', 10)
        pdf.cell(0, 6, f"Real Score Difference: {summary_data['real_diff']:+}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.cell(0, 6, f"4F Net Points Difference: {summary_data['4f_diff']:+.2f}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)

    return bytes(pdf.output(dest='S'))
    
# --- MAIN APP ----
# --- CUSTOM THEMING (THE ULTIMATE VERSION) ---
st.markdown("""
    <style>
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
        [data-testid="stSidebar"] hr {
            margin: 0.8rem 0 !important;
            border-top: 1px solid #3f445e !important;
        }
    </style>
""", unsafe_allow_html=True)
st.set_page_config(page_title="4Factors Net Points", layout="wide")
if not os.path.exists("game_index.json"): build_game_index()
@st.cache_data
def load_index(): return pd.read_json("game_index.json") if os.path.exists("game_index.json") else pd.DataFrame()
df_index = load_index()

# 1. Select League
league = st.sidebar.selectbox("League", sorted(df_index['league'].unique()), key="league_select")

# --- IMPROVED LOGO SECTION ---
config = LEAGUE_CONFIG.get(league, {})
logo_filename = config.get("logo", f"{league.lower()}.png") 
logo_full_path = os.path.join(LOGOS_PATH, logo_filename)
if os.path.exists(logo_full_path):
    col1, col2, col3 = st.sidebar.columns([1, 3, 1])
    with col2:
        st.image(logo_full_path, width=150)
st.sidebar.title("Scouting 4F Net Points")
if st.sidebar.button("Refresh Data Index"): build_game_index(); st.rerun()

mode = st.sidebar.radio("View Mode", ["Season Aggregate", "Game Boxscore", "Team Performance", "League Standings"], key="mode_radio")

# 2. NEW: Select Season (Now global, so both modes use it)
df_league = df_index[df_index['league'] == league]
season = st.sidebar.selectbox("Season", sorted(df_league['season'].unique(), reverse=True), key="season_sel")

# Calculation state
i1_tot, i2_tot, i1_raw, i2_raw, t1, t2, header_title = None, None, None, None, "", "", ""

# Global Benchmarks for the selected League AND Season
lg_effic, lg_orb_pct, lg_data = get_league_benchmarks(league, season)
# --- LEAGUE BENCHMARKS DISPLAY ---
st.sidebar.markdown("---")
st.sidebar.markdown("**League Benchmarks**")

# Using columns for a compact horizontal layout
col_lg1, col_lg2 = st.sidebar.columns(2)

with col_lg1:
    # We use a help tooltip for the detailed explanation to keep the UI clean
    st.markdown(f"**Effic:** `{lg_effic:.2f}`")
    st.caption("Pts per possession.")

with col_lg2:
    st.markdown(f"**OR%:** `{lg_orb_pct:.1%}`")
    st.caption("% of Off. Rebounds.")

# Optional: Add a small hover-over info icon for the full definitions
st.sidebar.info(
    "**Lg. Effic:** The average points scored per possession across the league.\n\n"
    "**Lg. OR%:** The percentage of available offensive rebounds grabbed by the attacking team.",
    icon=None # Set to None to keep it professional and text-only
)
if mode == "Season Aggregate":
    # Filter teams based on the chosen season
    teams = get_teams_in_league(league, season)
    t1 = st.sidebar.selectbox("Home Team", teams, index=0, key="t1_sel")
    t2 = st.sidebar.selectbox("Away Team", teams, index=min(1, len(teams)-1), key="t2_sel")
    
    # Get stats specifically for this season
    t1_off = get_per_game_volumes(t1, league, season, "TOTAL")
    t1_def = get_per_game_volumes(t1, league, season, "Rival")
    t2_off = get_per_game_volumes(t2, league, season, "TOTAL")
    t2_def = get_per_game_volumes(t2, league, season, "Rival")
    
    lg_raw = calc_raw_factors(lg_data, lg_data['drb'], lg_effic, lg_orb_pct)
    t1_off_raw, t1_def_raw = calc_raw_factors(t1_off, lg_data['drb'], lg_effic, lg_orb_pct), calc_raw_factors(t1_def, t1_off['drb'], lg_effic, lg_orb_pct)
    t2_off_raw, t2_def_raw = calc_raw_factors(t2_off, lg_data['drb'], lg_effic, lg_orb_pct), calc_raw_factors(t2_def, t2_off['drb'], lg_effic, lg_orb_pct)
    
    i1_tot = {k: (t1_off_raw[k]-lg_raw[k]) + (lg_raw[k]-t1_def_raw[k]) for k in lg_raw}
    i2_tot = {k: (t2_off_raw[k]-lg_raw[k]) + (lg_raw[k]-t2_def_raw[k]) for k in lg_raw}
    i1_raw, i2_raw = (t1_off_raw, t1_def_raw), (t2_off_raw, t2_def_raw)
    header_title = f"{season} 4-Factors Aggregate: {t1} vs {t2}"
elif mode == "Team Performance":
    # 1. Get available phases from the index
    phases_avail = sorted(df_league['phase'].unique())
    sel_phase = st.sidebar.selectbox("Select Phase", phases_avail, key="perf_phase_sel")
    
    # --- NEW: DYNAMIC TEAM FILTERING BY PHASE ---
    # We look at the index and only grab teams that have games in the selected phase
    df_phase_indexed = df_league[df_league['phase'] == sel_phase]
    teams_in_phase = sorted(list(set(df_phase_indexed['t1'].unique()) | set(df_phase_indexed['t2'].unique())))
    
    if not teams_in_phase:
        st.sidebar.warning("No teams found in the index for this phase.")
        st.stop()
        
    target_team = st.sidebar.selectbox("Select Team", teams_in_phase, key="perf_team_sel")
    # ---------------------------------------------
    
    # --- RESET LOGIC (Clears filters when context changes) ---
    current_context = f"{league}_{season}_{sel_phase}_{target_team}"
    if "last_context" not in st.session_state:
        st.session_state["last_context"] = current_context

    if st.session_state["last_context"] != current_context:
        # Reset filter widgets to defaults
        st.session_state["perf_res_choice"] = ["Win", "Loss"]
        st.session_state["perf_venue_choice"] = ["Home", "Away"]
        if "perf_range_rnds" in st.session_state: del st.session_state["perf_range_rnds"]
        if "perf_specific_rnds" in st.session_state: st.session_state["perf_specific_rnds"] = []
        
        st.session_state["last_context"] = current_context
        st.rerun()
    # ---------------------------------------------------------

    view_type = st.sidebar.radio("Metric View", ["Net Impact", "Offensive Impact", "Defensive Impact"])
    
    df_team = df_league[(df_league['season'] == season) & (df_league['phase'] == sel_phase) & 
                        ((df_league['t1'] == target_team) | (df_league['t2'] == target_team))].copy()
    
    if df_team.empty:
        st.warning(f"No games found for {target_team}.")
        st.stop()

    df_team['is_win'] = df_team.apply(lambda x: (x['pts1'] > x['pts2'] if x['t1'] == target_team else x['pts2'] > x['pts1']), axis=1)
    df_team['venue'] = df_team.apply(lambda x: "Home" if x['t1'] == target_team else "Away", axis=1)

    st.sidebar.markdown("---")
    st.sidebar.subheader("Filter Game Stretch")
    all_rnds = sorted(df_team['round'].unique())

    specific_rnds = st.sidebar.multiselect("Pick Specific Rounds", all_rnds, key="perf_specific_rnds")
    res_choice = st.sidebar.multiselect("Game Result", ["Win", "Loss"], default=["Win", "Loss"], key="perf_res_choice")
    venue_choice = st.sidebar.multiselect("Venue", ["Home", "Away"], default=["Home", "Away"], key="perf_venue_choice")
    
    if len(all_rnds) > 1:
        range_rnds = st.sidebar.select_slider("Round Range", options=all_rnds, value=(all_rnds[0], all_rnds[-1]), key="perf_range_rnds")
    else:
        range_rnds = (all_rnds[0], all_rnds[0])

    if specific_rnds:
        df_filtered = df_team[df_team['round'].isin(specific_rnds)]
        filter_msg = f"Specific Rounds: {', '.join(specific_rnds)}"
    else:
        allowed_wins = [True if r == "Win" else False for r in res_choice]
        start_idx = all_rnds.index(range_rnds[0]); end_idx = all_rnds.index(range_rnds[1])
        allowed_range = all_rnds[start_idx : end_idx+1]
        df_filtered = df_team[(df_team['is_win'].isin(allowed_wins)) & (df_team['venue'].isin(venue_choice)) & (df_team['round'].isin(allowed_range))]
        filter_msg = f"Filters: {'/'.join(res_choice)} | {'/'.join(venue_choice)} | {range_rnds[0]}-{range_rnds[1]}"

    if df_filtered.empty:
        st.error("No games match this filter combination.")
        st.stop()

    performance_data = []
    for _, row in df_filtered.sort_values('round').iterrows():
        g = get_raw_game_data_custom(row['path'])
        if not g: continue
        is_t1 = g['t1_name'] == target_team
        stats_self, stats_opp = (g['t1_stats'], g['t2_stats']) if is_t1 else (g['t2_stats'], g['t1_stats'])
        
        f_off = calc_raw_factors(stats_self, stats_opp['drb'], lg_effic, lg_orb_pct)
        f_def = calc_raw_factors(stats_opp, stats_self['drb'], lg_effic, lg_orb_pct)
        f_def_inv = {k: -v for k, v in f_def.items()} 
        
        if view_type == "Offensive Impact": display_vals = f_off
        elif view_type == "Defensive Impact": display_vals = f_def_inv
        else: display_vals = {k: f_off[k] + f_def_inv[k] for k in f_off}
        
        # Store individual components for averaging
        result_label = "W" if row['is_win'] else "L"
        venue_label = "(H)" if row['venue'] == 'Home' else "(A)"
        entry = {
            "Round": row['round'], 
            "Matchup": f"{result_label} {venue_label} vs {row['t2'] if is_t1 else row['t1']}",
            "Shooting": display_vals['Shooting'], "Turnovers": display_vals['Turnovers'],
            "Rebounding": display_vals['Rebounding'], "Free Throws": display_vals['Free Throws'],
            "Total 4F": sum(display_vals.values())
        }
        # Add O/D components for every factor
        for f in ["Shooting", "Turnovers", "Rebounding", "Free Throws"]:
            entry[f"{f}_Off"] = f_off[f]
            entry[f"{f}_Def"] = f_def_inv[f]
            entry[f"{f}_Net"] = f_off[f] + f_def_inv[f]

        performance_data.append(entry)

    perf_df = pd.DataFrame(performance_data)
    
    # --- DETAILED SCOUTING SUMMARY ---
    st.subheader(f"{target_team} - Batch Scouting Summary")
    st.info(f"Analyzed {len(perf_df)} games. {filter_msg}")
    
    # 4-Column Layout for the 4 Factors
    col_s, col_r, col_t, col_f = st.columns(4)
    
    factors_map = {
        "Shooting": col_s, "Rebounding": col_r, 
        "Turnovers": col_t, "Free Throws": col_f
    }

    for f_name, col in factors_map.items():
        net_avg = perf_df[f"{f_name}_Net"].mean()
        off_avg = perf_df[f"{f_name}_Off"].mean()
        def_avg = perf_df[f"{f_name}_Def"].mean()
        
        with col:
            st.markdown(f"#### {f_name}")
            st.markdown(f"**Net: {net_avg:+.2f}**")
            st.caption(f"Off: {off_avg:+.2f} | Def: {def_avg:+.2f}")

    st.markdown("---")
    
    # Row for Overall Batch Efficiency
    c1, c2, c3 = st.columns(3)
    c1.metric("Batch Games", len(perf_df))
    # Summing the averages of all Net factors
    total_net = sum([perf_df[f"{fn}_Net"].mean() for fn in factors_map.keys()])
    c2.metric("Avg Net Efficiency", f"{total_net:+.2f}")
    c3.metric("View Applied", view_type)

    st.markdown("---")
    
    # Display table (keep it clean, only show the columns relevant to the view_type)
    cols_to_show = ["Round", "Matchup", "Shooting", "Turnovers", "Rebounding", "Free Throws", "Total 4F"]
    st.dataframe(perf_df[cols_to_show].style.format({k: "{:+.2f}" for k in cols_to_show if k not in ["Round", "Matchup"]})
                 .background_gradient(cmap='RdYlGn', subset=["Total 4F"]), use_container_width=True, hide_index=True)

    pdf_perf = generate_performance_pdf(perf_df, target_team, league, season, view_type)
    st.download_button("Download Filtered PDF", pdf_perf, f"Analysis_{target_team}.pdf")
    st.stop()
elif mode == "League Standings":
    # 1. Prepare Phase Options with an "Overall" choice
    phases_in_index = sorted(df_league['phase'].unique())
    phase_options = ["Overall Season"] + phases_in_index
    selected_phase = st.sidebar.selectbox("Competition Phase / Group", phase_options, key="standings_phase")
    
    st.subheader(f"{league} {season} - {selected_phase} Standings")
    view_type = st.sidebar.radio("Metric View", ["Net Impact", "Offensive Impact", "Defensive Impact"])
    
    # 2. FILTER TEAMS: Only get teams that actually played in the selected phase
    if selected_phase == "Overall Season":
        # Get all teams that played in any phase/group this season
        teams_to_analyze = sorted(list(set(df_league['t1'].unique()) | set(df_league['t2'].unique())))
    else:
        # Get only teams that appear in the selected group (e.g., ESTE)
        df_phase_teams = df_league[df_league['phase'] == selected_phase]
        teams_to_analyze = sorted(list(set(df_phase_teams['t1'].unique()) | set(df_phase_teams['t2'].unique())))

    league_results = []
    with st.spinner(f"Calculating {len(teams_to_analyze)} teams..."):
        for team in teams_to_analyze:
            # 3. GET DATA: If "Overall", we search all folders. If specific, we target the group.
            if selected_phase == "Overall Season":
                t_off = get_per_game_volumes(team, league, season, "TOTAL")
                t_def = get_per_game_volumes(team, league, season, "Rival")
            else:
                t_off = get_per_game_volumes_by_phase(team, league, season, selected_phase, "TOTAL")
                t_def = get_per_game_volumes_by_phase(team, league, season, selected_phase, "Rival")
            
            if t_off['pts'] == 0: continue 

            lg_raw = calc_raw_factors(lg_data, lg_data['drb'], lg_effic, lg_orb_pct)
            t_off_raw = calc_raw_factors(t_off, lg_data['drb'], lg_effic, lg_orb_pct)
            t_def_raw = calc_raw_factors(t_def, t_off['drb'], lg_effic, lg_orb_pct)
            
            off_impact = {k: (t_off_raw[k] - lg_raw[k]) for k in lg_raw}
            def_impact = {k: (lg_raw[k] - t_def_raw[k]) for k in lg_raw}
            net_impact = {k: off_impact[k] + def_impact[k] for k in lg_raw}
            
            display = off_impact if view_type == "Offensive Impact" else (def_impact if view_type == "Defensive Impact" else net_impact)
                
            league_results.append({
                "Team": team, "Shooting": display['Shooting'], "Turnovers": display['Turnovers'],
                "Rebounding": display['Rebounding'], "Free Throws": display['Free Throws'],
                "Net Points": sum(display.values())
            })
            
    if not league_results:
        st.error(f"No data found for '{selected_phase}'.")
    else:
        standings_df = pd.DataFrame(league_results).sort_values("Net Points", ascending=False)
        standings_df.insert(0, "Rank", range(1, len(standings_df) + 1))

        # Format and display the table
        st.dataframe(
            standings_df.style.format({k: "{:+.2f}" for k in standings_df.columns if k not in ["Team", "Rank"]})
            .background_gradient(cmap='RdYlGn', subset=["Net Points"], vmin=-10, vmax=10),
            use_container_width=True, height=600, hide_index=True
        )

        pdf_bytes = generate_standings_pdf(standings_df, league, season, selected_phase)
        st.download_button("Download Standings PDF", data=pdf_bytes, file_name=f"Standings_{league}_{selected_phase}.pdf")

    st.stop()
    phases_available = sorted(df_league['phase'].unique())
    selected_phase = st.sidebar.selectbox("Filter by Phase", phases_available, key="standings_phase")
    
    st.subheader(f"{league} {season} - {selected_phase} Standings")
    view_type = st.sidebar.radio("Metric View", ["Net Impact", "Offensive Impact", "Defensive Impact"])
    
    teams = get_teams_in_league(league, season)
    league_results = []

    with st.spinner(f"Analyzing {len(teams)} teams..."):
        for team in teams:
            t_off = get_per_game_volumes_by_phase(team, league, season, selected_phase, "TOTAL")
            t_def = get_per_game_volumes_by_phase(team, league, season, selected_phase, "Rival")
            if t_off['pts'] == 0: continue 

            lg_raw = calc_raw_factors(lg_data, lg_data['drb'], lg_effic, lg_orb_pct)
            t_off_raw = calc_raw_factors(t_off, lg_data['drb'], lg_effic, lg_orb_pct)
            t_def_raw = calc_raw_factors(t_def, t_off['drb'], lg_effic, lg_orb_pct)
            
            off_impact = {k: (t_off_raw[k] - lg_raw[k]) for k in lg_raw}
            def_impact = {k: (lg_raw[k] - t_def_raw[k]) for k in lg_raw}
            net_impact = {k: off_impact[k] + def_impact[k] for k in lg_raw}
            
            display = off_impact if view_type == "Offensive Impact" else (def_impact if view_type == "Defensive Impact" else net_impact)
                
            league_results.append({
                "Team": team, "Shooting": display['Shooting'], "Turnovers": display['Turnovers'],
                "Rebounding": display['Rebounding'], "Free Throws": display['Free Throws'],
                "Net Points": sum(display.values())
            })
            
    if not league_results:
        st.error(f"No aggregate data found for '{selected_phase}'.")
    else:
        standings_df = pd.DataFrame(league_results).sort_values("Net Points", ascending=False)
        standings_df.insert(0, "Rank", range(1, len(standings_df) + 1))

        st.dataframe(
            standings_df.style.format({k: "{:+.2f}" for k in standings_df.columns if k not in ["Team", "Rank"]})
            .background_gradient(cmap='RdYlGn', subset=["Net Points"], vmin=-10, vmax=10),
            use_container_width=True, height=600, hide_index=True
        )

        pdf_bytes = generate_standings_pdf(standings_df, league, season, selected_phase)
        st.download_button("Download Standings PDF", data=pdf_bytes, file_name=f"Standings_{league}_{selected_phase}.pdf")

    st.stop()
else: # Game Boxscore mode
    df_f = df_league[df_league['season'] == season].copy()
    
    # THIS DROPDOWN SHOULD NOW SHOW "Regular_Season - LIGAREGULARESTE" 
    # AND "Regular_Season - LIGAREGULAROESTE"
    phase_options = sorted(df_f['phase'].unique())
    phase = st.sidebar.selectbox("Phase / Group", phase_options, key="phase_sel")
    
    df_f = df_f[df_f['phase'] == phase].copy()
    
    
    round_val = st.sidebar.selectbox("Round", sorted(df_f['round'].unique()), key="round_sel")
    df_f = df_f[df_f['round'] == round_val].copy()
    
    if df_f.empty:
        st.sidebar.warning("No games found for this selection.")
        st.stop()

    # Define the display column
    df_f['display'] = df_f.apply(lambda x: f"{x['round']} | {x['t1']} ({x['pts1']}) vs {x['t2']} ({x['pts2']})", axis=1)
    
    # 1. DEFINE game_display
    game_options = df_f['display'].unique()
    game_display = st.sidebar.selectbox("Game", game_options, key="game_sel")
    
    # 2. DEFINE game_record
    game_record = df_f[df_f['display'] == game_display].iloc[0]
    
    # 3. Proceed with calculations
    g = get_raw_game_data_custom(game_record['path'])
    t1, t2 = g['t1_name'], g['t2_name']
    
    lg_raw = calc_raw_factors(lg_data, lg_data['drb'], lg_effic, lg_orb_pct)
    t1_raw = calc_raw_factors(g['t1_stats'], g['t2_stats']['drb'], lg_effic, lg_orb_pct)
    t2_raw = calc_raw_factors(g['t2_stats'], g['t1_stats']['drb'], lg_effic, lg_orb_pct)
    
    # ABSOLUTE IMPACT LOGIC (Your preferred way)
    i1_tot = t1_raw 
    i2_tot = t2_raw
    i1_raw, i2_raw = (t1_raw, t1_raw), (t2_raw, t2_raw)
    
    header_title = f"4-Factors Impact: {game_record['round']} - {t1} ({game_record['pts1']}) vs {t2} ({game_record['pts2']})"
# --- DISPLAY ---
st.subheader(header_title)
with st.container(border=True):
    st.plotly_chart(plot_4f_comparison(i1_tot, i2_tot, t1, t2), use_container_width=True)
# --- GLOSSARY / INTERPRETATION ---
st.markdown("---")
st.subheader("Scouting Interpretation")

factors =["Shooting", "Rebounding", "Turnovers", "Free Throws"]

c1, c2 = st.columns(2)

# --- HOME TEAM (t1) ---
with c1:
    st.markdown(f"#### {t1} Impact")
    for f in factors:
        val = i1_tot[f]
        # In Boxscore mode, negative is always a "cost"
        label = "contribution" if val >= 0 else "cost"
        
        advantage_text = ""
        if i1_tot[f] > i2_tot[f]:
            diff = i1_tot[f] - i2_tot[f]
            advantage_text = f" ({t1} was {diff:+.2f} pts more efficient)"
            
        st.write(f"• **{f}**: {val:+.2f} points {label}{advantage_text}")

# --- AWAY TEAM (t2) ---
with c2:
    st.markdown(f"#### {t2} Impact")
    for f in factors:
        val = i2_tot[f]
        label = "contribution" if val >= 0 else "cost"
        
        advantage_text = ""
        if i2_tot[f] > i1_tot[f]:
            diff = i2_tot[f] - i1_tot[f]
            advantage_text = f" ({t2} was {diff:+.2f} pts more efficient)"
            
        st.write(f"• **{f}**: {val:+.2f} points {label}{advantage_text}")
# --- FINAL SUMMARY (Boxscore Only) ---
if mode == "Game Boxscore":
    st.markdown("---")
    st.subheader("Final Match Summary")
    
    real_score_diff = game_record['pts1'] - game_record['pts2']
    total_4f_home = sum(i1_tot.values())
    total_4f_away = sum(i2_tot.values())
    net_4f_diff = total_4f_home - total_4f_away
    
    col_a, col_b = st.columns(2)
    col_a.metric("Real Score Difference", f"{real_score_diff:+}")
    col_b.metric("4F Net Points Difference", f"{net_4f_diff:+.2f}")
    
    # Optional logic note
    if abs(real_score_diff - net_4f_diff) > 10:
        st.info("Note: The 4F Net Difference accounts for shooting, rebounding, and turnovers.")

# --- EXPANDERS & PDF ---
with st.expander("Offense vs Defense Net Breakdown"):
    c1, c2 = st.columns(2)
    with c1:
        st.write(f"### {t1} (Home)")
        for f in factors: 
            st.markdown(f"**{f} Net: {i1_tot[f]:+.2f}** | Off: {i1_raw[0][f]:+.2f} | Def: {i1_raw[1][f]:+.2f}")
    with c2:
        st.write(f"### {t2} (Away)")
        for f in factors: 
            st.markdown(f"**{f} Net: {i2_tot[f]:+.2f}** | Off: {i2_raw[0][f]:+.2f} | Def: {i2_raw[1][f]:+.2f}")

if st.button("Generate PDF Report", key="pdf_btn"):
        # 1. Prepare Interpretation Lists
        text_t1 = []
        text_t2 = []
        factors =["Shooting", "Rebounding", "Turnovers", "Free Throws"]
        
        for f in factors:
            # T1 Text
            better_worse_1 = "better" if i1_tot[f] >= 0 else "worse"
            adv1 = f" ({t1} was { (i1_tot[f]-i2_tot[f]):.2f} pts better)" if i1_tot[f] > i2_tot[f] else ""
            text_t1.append(f"• {f}: {abs(i1_tot[f]):.2f} pts {better_worse_1} than avg{adv1}")
            
            # T2 Text
            better_worse_2 = "better" if i2_tot[f] >= 0 else "worse"
            adv2 = f" ({t2} was { (i2_tot[f]-i1_tot[f]):.2f} pts better)" if i2_tot[f] > i1_tot[f] else ""
            text_t2.append(f"• {f}: {abs(i2_tot[f]):.2f} pts {better_worse_2} than avg{adv2}")

        # 2. Prepare Summary Data
        summary = None
        if mode == "Game Boxscore":
            summary = {
                'real_diff': game_record['pts1'] - game_record['pts2'],
                '4f_diff': sum(i1_tot.values()) - sum(i2_tot.values())
            }
        # 2. CREATE THE MATPLOTLIB CHART (Instead of Plotly)
        chart_buffer = create_pdf_chart_mpl(i1_tot, i2_tot, t1, t2)
        # 3. GENERATE PDF (Passing the buffer and all data)
        pdf_bytes = generate_pdf_report(
        chart_buffer, t1, t2, lg_effic, lg_orb_pct, 
        i1_tot, i1_raw[0], i1_raw[1], i2_tot, i2_raw[0], i2_raw[1],
        text_t1, text_t2, summary
    )
    
        st.download_button("Download PDF", data=pdf_bytes, file_name=f"Report_{t1}_{t2}.pdf", mime="application/pdf")