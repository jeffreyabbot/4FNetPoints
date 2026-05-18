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
import base64
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

# Define a soft Red-White-Green colormap
# Colors: Light Red (#ff9999), White (#ffffff), Light Green (#99ff99)
custom_rdwgn = LinearSegmentedColormap.from_list(
    "custom_rdwgn", ["#ff9999", "#ffffff", "#99ff99"]
)
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
@st.cache_resource # This makes the search instant after the first time
def get_logo_filename_map():
    """Creates a dictionary mapping UPPERCASE team names to actual filenames on disk."""
    folder_path = os.path.join(LOGOS_PATH, "teams")
    if not os.path.exists(folder_path):
        return {}
    
    # Builds a map like: {"REAL MADRID": "real madrid.png", "BARÇA": "Barça.png"}
    return {f.upper().replace(".PNG", ""): f for f in os.listdir(folder_path) if f.lower().endswith(".png")}
def generate_aggregate_pdf(t1, t2, season, t1_stats, t2_stats, analysis_type):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, f"Season Aggregates per Team: {t1} vs {t2} ({season})", ln=True, align='C')
    pdf.ln(10)
    
    pdf.set_font("Helvetica", 'B', 12)
    pdf.cell(0, 8, f"Mode: {analysis_type}", ln=True)
    pdf.ln(5)
    
    # Table of stats
    pdf.set_font("Helvetica", '', 10)
    if analysis_type == "Situational Points":
        cols = ["Metric", t1, t2]
        data = [
            ("Pts off TO", f"{t1_stats['pts_off_to']:.1f}", f"{t2_stats['pts_off_to']:.1f}"),
            ("2nd Chance", f"{t1_stats['pts_2nd_ch']:.1f}", f"{t2_stats['pts_2nd_ch']:.1f}"),
            ("Fast Break", f"{t1_stats['pts_fb']:.1f}", f"{t2_stats['pts_fb']:.1f}")
        ]
        for col in cols: pdf.cell(50, 8, col, border=1, align='C')
        pdf.ln()
        for row in data:
            for item in row: pdf.cell(50, 8, item, border=1, align='C')
            pdf.ln()
            
    return bytes(pdf.output(dest='S'))
def get_team_icon(team_name):
    """Finds the logo file regardless of casing and converts to Base64."""
    if not team_name:
        return None
        
    search_name = str(team_name).strip().upper()
    logo_map = get_logo_filename_map()
    
    # 1. Look for the actual filename in our map
    actual_filename = logo_map.get(search_name)
    
    if actual_filename:
        os_path = os.path.join(LOGOS_PATH, "teams", actual_filename)
    else:
        # Fallback if no match found
        os_path = os.path.join(LOGOS_PATH, "FEB.png")
        
    # 2. Convert to Base64 for the browser
    if os.path.exists(os_path):
        try:
            with open(os_path, "rb") as f:
                data = base64.b64encode(f.read()).decode("utf-8")
                return f"data:image/png;base64,{data}"
        except Exception:
            return None
    return None
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
def create_pdf_situational_mpl(s1, s2, t1, t2):
    labels = ["Pts off TO", "2nd Chance Pts", "Fast Break Pts"]
    vals_t1 = [s1.get("pts_off_to", 0), s1.get("pts_2nd_ch", 0), s1.get("pts_fb", 0)]
    vals_t2 = [s2.get("pts_off_to", 0), s2.get("pts_2nd_ch", 0), s2.get("pts_fb", 0)]
    
    fig, ax = plt.subplots(figsize=(10, 4))
    y = range(len(labels))
    width = 0.35
    
    bar1 = ax.barh([i + width/2 for i in y], vals_t1, width, label=t1, color='#1e2130')
    bar2 = ax.barh([i - width/2 for i in y], vals_r := vals_t2, width, label=t2, color='#F00000')
    
    ax.bar_label(bar1, fmt='%.1f', padding=3, fontsize=9)
    ax.bar_label(bar2, fmt='%.1f', padding=3, fontsize=9)
    
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, 1.15), ncol=2, frameon=False)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf

def create_pdf_situational_mpl(s1, s2, t1, t2):
    labels = ["Pts off TO", "2nd Chance Pts", "Fast Break Pts"]
    vals_t1 = [s1.get("pts_off_to", 0), s1.get("pts_2nd_ch", 0), s1.get("pts_fb", 0)]
    vals_t2 = [s2.get("pts_off_to", 0), s2.get("pts_2nd_ch", 0), s2.get("pts_fb", 0)]
    
    fig, ax = plt.subplots(figsize=(10, 4))
    y = range(len(labels))
    width = 0.35
    
    bar1 = ax.barh([i + width/2 for i in y], vals_t1, width, label=t1, color='#2980B9')
    bar2 = ax.barh([i - width/2 for i in y], vals_r := vals_t2, width, label=t2, color='#7E6605')
    
    ax.bar_label(bar1, fmt='%.1f', padding=3, fontsize=9)
    ax.bar_label(bar2, fmt='%.1f', padding=3, fontsize=9)
    
    ax.set_yticks(y)
    ax.set_yticklabels(labels)
    ax.invert_yaxis()
    ax.spines['top'].set_visible(False)
    ax.spines['right'].set_visible(False)
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, 1.15), ncol=2, frameon=False)
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png', bbox_inches='tight', dpi=150)
    plt.close(fig)
    buf.seek(0)
    return buf

def generate_unified_report(chart_buf, t1, t2, analysis_type, subtitle, table_data=None):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, f"{analysis_type}: {t1} vs {t2}", ln=True, align='C')
    pdf.set_font("Helvetica", '', 12)
    pdf.cell(0, 8, subtitle, ln=True, align='C')
    pdf.ln(5)
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmpfile:
        tmpfile.write(chart_buf.getbuffer())
        pdf.image(tmpfile.name, x=15, w=180)
    pdf.ln(10)
    
    if table_data:
        pdf.set_font("Helvetica", 'B', 10)
        pdf.set_fill_color(230, 230, 230)
        pdf.cell(60, 8, "Metric", border=1, fill=True)
        pdf.cell(60, 8, t1, border=1, fill=True, align='C')
        pdf.cell(60, 8, t2, border=1, fill=True, align='C')
        pdf.ln()
        pdf.set_font("Helvetica", '', 10)
        for label, v1, v2 in table_data:
            pdf.cell(60, 8, label, border=1)
            pdf.cell(60, 8, str(v1), border=1, align='C')
            pdf.cell(60, 8, str(v2), border=1, align='C')
            pdf.ln()
    return bytes(pdf.output(dest='S'))
def pdf_safe_text(text):
    """Universal sanitizer for FPDF Helvetica."""
    if not text: return ""
    s = str(text)
    # Manual icon fixes
    s = s.replace("🟢", "W").replace("🔴", "L").replace("🏠", "(H)").replace("✈️", "(A)").replace("✈", "(A)")
    # Convert to Latin-1 and ignore what doesn't fit (Standard for Helvetica)
    return s.encode('latin-1', 'ignore').decode('latin-1')

def generate_standings_pdf(df, league, season, phase, analysis_type):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, pdf_safe_text(f"{league} Standings - {season}"), ln=True, align='C')
    pdf.set_font("Helvetica", '', 12)
    pdf.cell(0, 10, pdf_safe_text(f"Phase: {phase} | {analysis_type}"), ln=True, align='C')
    pdf.ln(10)

    pdf.set_font("Helvetica", 'B', 9)
    
    # Define columns based on analysis type
    if analysis_type == "4-Factors Net Points":
        cols = ["Rank", "Team", "Shoot", "TOv", "Reb", "FT", "Net"]
        keys = ["Rank", "Team", "Shooting", "Turnovers", "Rebounding", "Free Throws", "Net Points"]
        widths = [12, 65, 23, 23, 23, 23, 21]
    else:
        # Situational Columns
        cols = ["Rank", "Team", "TO-P", "2nd-C", "FB-P", "eFG%", "ORB%", "TO%", "FTR"]
        keys = ["Rank", "Team", "Pts off TO", "2nd Chance", "Fast Break", "eFG%", "ORB%", "TO%", "FTR"]
        widths = [12, 60, 24, 24, 24, 23, 23, 23, 23]

    for i, col in enumerate(cols):
        pdf.cell(widths[i], 8, col, border=1, align='C')
    pdf.ln()

    pdf.set_font("Helvetica", '', 8)
    for _, row in df.iterrows():
        pdf.cell(widths[0], 7, str(row['Rank']), border=1, align='C')
        pdf.cell(widths[1], 7, pdf_safe_text(row['Team'])[:35], border=1)
        
        # Print the data columns
        for i in range(2, 7):
            val = row[keys[i]]
            # Format numbers (add + sign for 4F, regular for situational)
            if isinstance(val, (int, float)):
                txt = f"{val:+.2f}" if analysis_type == "4-Factors Net Points" else f"{val:.2f}"
            else:
                txt = str(val)
            pdf.cell(widths[i], 7, txt, border=1, align='C')
        pdf.ln()
        if pdf.get_y() > 270: pdf.add_page()
        
    return bytes(pdf.output(dest='S'))

def generate_performance_pdf(df, team, league, season, view_type, analysis_type):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", 'B', 16)
    pdf.cell(0, 10, pdf_safe_text(f"Scouting Report: {team}"), ln=True, align='C')
    pdf.set_font("Helvetica", '', 12)
    pdf.cell(0, 8, pdf_safe_text(f"{league} {season} | {analysis_type} ({view_type})"), ln=True, align='C')
    pdf.ln(5)

    # 1. Summary Box
    pdf.set_fill_color(245, 245, 245)
    pdf.set_font("Helvetica", 'B', 11)
    pdf.cell(0, 10, "  Batch Scouting Summary (Averages)", border=1, ln=True, fill=True)
    pdf.set_font("Helvetica", '', 9)
    
    if analysis_type == "4-Factors Net Points":
        for f in ["Shooting", "Rebounding", "Turnovers", "Free Throws"]:
            line = f" {f}: Net {df[f+'_Net'].mean():+.2f} | Off: {df[f+'_Off'].mean():+.2f} | Def: {df[f+'_Def'].mean():+.2f}"
            pdf.cell(0, 7, pdf_safe_text(line), border='LR', ln=True)
    else:
        for f in ["Pts off TO", "2nd Chance", "Fast Break"]:
            line = f" {f}: Average {df[f].mean():.2f} pts per game"
            pdf.cell(0, 7, pdf_safe_text(line), border='LR', ln=True)
    pdf.cell(190, 0, "", border='T', ln=True)
    pdf.ln(8)

    # 2. Setup Headers and Widths (Must match in length!)
    pdf.set_font("Helvetica", 'B', 8) # Smaller font to fit more columns
    if analysis_type == "4-Factors Net Points":
        cols = ["Round", "Matchup", "Shoot", "TOv", "Reb", "FT", "Total"]
        data_keys = ["Round", "Matchup", "Shooting", "Turnovers", "Rebounding", "Free Throws", "Total 4F"]
        widths = [15, 50, 25, 25, 25, 25, 25] # 7 items
    else:
        # Situational: 9 columns
        cols = ["Round", "Matchup", "TO-P", "2nd-C", "FB-P", "eFG%", "TO%", "ORB%", "FTR"]
        data_keys = ["Round", "Matchup", "Pts off TO", "2nd Chance", "Fast Break", "eFG%", "TO%", "ORB%", "FTR"]
        widths = [15, 45, 18, 18, 18, 19, 19, 19, 19] # 9 items, total 190mm

    # Draw Headers
    for i, col in enumerate(cols):
        pdf.cell(widths[i], 8, col, border=1, align='C')
    pdf.ln()

    # 3. Draw Rows
    pdf.set_font("Helvetica", '', 7) # Smaller font for data
    for _, row in df.iterrows():
        pdf.cell(widths[0], 7, pdf_safe_text(str(row['Round'])), border=1, align='C')
        pdf.cell(widths[1], 7, pdf_safe_text(row['Matchup']), border=1)
        
        # Draw the rest of the dynamic columns
        # Loop starts from index 2 because Round and Matchup are handled above
        for i in range(2, len(data_keys)):
            val = row[data_keys[i]]
            if isinstance(val, (int, float)):
                # Use + format only for 4F Net Points
                txt = f"{val:+.2f}" if analysis_type == "4-Factors Net Points" else f"{val:.2f}"
            else:
                txt = str(val)
            pdf.cell(widths[i], 7, txt, border=1, align='C')
        pdf.ln()
        
        if pdf.get_y() > 270: 
            pdf.add_page()
            # Redraw headers on new page
            pdf.set_font("Helvetica", 'B', 8)
            for i, col in enumerate(cols):
                pdf.cell(widths[i], 8, col, border=1, align='C')
            pdf.ln()
            pdf.set_font("Helvetica", '', 7)
        
    return bytes(pdf.output(dest='S'))
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


def plot_4f_comparison(data_l, data_r, team_l, team_r, is_pdf=False):
    labels =["Shooting", "Rebounding", "Turnovers", "Free Throws"]
    vals_l, vals_r = [data_l[k] for k in labels], [data_r[k] for k in labels]
    
    fig = go.Figure()
    
    # Home Team
    fig.add_trace(go.Bar(
        y=labels, x=vals_l, orientation='h', name=team_l, 
        marker_color="#1e2130", text=[f"{v:+.1f}" for v in vals_l], 
        textposition='auto', insidetextfont=dict(color='white', size=11),
        cliponaxis=False
    ))
    
    # Away Team
    fig.add_trace(go.Bar(
        y=labels, x=vals_r, orientation='h', name=team_r, 
        marker_color="#FF0000", text=[f"{v:+.1f}" for v in vals_r], 
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
def plot_situational_comparison(t1_stats, t2_stats, t1_name, t2_name):
    # Labels for the chart
    labels = ["Pts off TO", "2nd Chance Pts", "Fast Break Pts"]
    
    # Values
    vals_t1 = [t1_stats.get("pts_off_to", 0), t1_stats.get("pts_2nd_ch", 0), t1_stats.get("pts_fb", 0)]
    vals_t2 = [t2_stats.get("pts_off_to", 0), t2_stats.get("pts_2nd_ch", 0), t2_stats.get("pts_fb", 0)]
    
    fig = go.Figure()
    
    # Team 1 Bars
    fig.add_trace(go.Bar(
        y=labels, x=vals_t1, orientation='h', name=t1_name,
        marker_color='#1e2130', text=[f"{v:.1f}" for v in vals_t1],
        textposition='auto'
    ))
    
    # Team 2 Bars
    fig.add_trace(go.Bar(
        y=labels, x=vals_t2, orientation='h', name=t2_name,
        marker_color="#F00000", text=[f"{v:.1f}" for v in vals_t2],
        textposition='auto'
    ))
    
    fig.update_layout(
        barmode='group', height=350,
        margin=dict(l=120, r=40, t=20, b=40),
        plot_bgcolor='white',
        xaxis=dict(title="Average Points per Game", showgrid=True, gridcolor='#E5E7E9'),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )
    return fig
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
        /* 11. FIX EXPANDER HOVER (Glossary) */
        [data-testid="stSidebar"] details summary:hover {
            background-color: #2d324a !important; /* Same as your selectbox background */
            border-radius: 4px;
        }
        
        [data-testid="stSidebar"] details summary:hover * {
            color: #ffffff !important; /* Force text to stay white */
        }

        /* Ensure the expander icon (chevron) also stays white */
        [data-testid="stSidebar"] details summary svg {
            fill: #ffffff !important;
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
st.sidebar.title("Scouting 4F")
if st.sidebar.button("Refresh Data Index"):
    # 1. Physically rebuild the file
    build_game_index()
    # 2. CLEAR STREAMLIT'S CACHE so it re-reads the JSON
    st.cache_data.clear()
    # 3. Rerun
    st.rerun()

mode = st.sidebar.radio("View Mode", ["Season Aggregates per Team", "Games Boxscores", "Team Performance by Game", "Overall League Standings"], key="mode_radio")
analysis_type = st.sidebar.selectbox("Analysis Category", ["4-Factors Net Points", "4-Factors Classic "], key="analysis_type")
# 2. NEW: Select Season (Now global, so both modes use it)
df_league = df_index[df_index['league'] == league]
season = st.sidebar.selectbox("Season", sorted(df_league['season'].unique(), reverse=True), key="season_sel")

# Calculation state
i1_tot, i2_tot, i1_raw, i2_raw, t1, t2, header_title = None, None, None, None, "", "", ""

# Global Benchmarks for the selected League AND Season
lg_effic, lg_orb_pct, lg_data = get_league_benchmarks(league, season)
# Calculate league midpoints for the "White" color
lg_fga = lg_data['f2a'] + lg_data['f3a']
avg_efg = (lg_data['f2m'] + 1.5 * lg_data['f3m']) / lg_fga if lg_fga > 0 else 0.52
avg_to = lg_data['tov'] / (lg_fga + 0.44 * lg_data['fta'] + lg_data['tov']) if lg_fga > 0 else 0.15
avg_ftr = lg_data['fta'] / lg_fga if lg_fga > 0 else 0.25
avg_orb = lg_orb_pct # Already calculated in your code
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
with st.sidebar.expander("Glossary", expanded=False):
    st.info(
        "**Lg. Effic:** The average points scored per possession across the league.\n\n"
        "**Lg. OR%:** The percentage of available offensive rebounds grabbed by the attacking team.\n\n"
        "**2nd Chance Points:** Points scored within 8 seconds immediately following an offensive rebound.\n\n"
        "**Points off Turnovers:** Points scored on any possession that was initiated by an opponent's turnover (possession-based).\n\n"
        "**Fast Break Points:** Points scored by a player on a fast break (after a Fast Break Opportunity). Includes points from FTs after a foul.\n\n"
    "**Fast Break Opportunity:** When a player scores a FG or is fouled on a fast break. A fast break is a play within 8 seconds of a DRB, STL, or opponent's made basket."
)
if mode == "Season Aggregates per Team":
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
    label = "4-Factors" if analysis_type == "4-Factors Net Points" else "4F-Classic"
    header_title = f"{season} {label} Aggregate: {t1} vs {t2}"
elif mode == "Team Performance by Game":
    phases_avail = sorted(df_league['phase'].unique())
    sel_phase = st.sidebar.selectbox("Select Phase", phases_avail, key="perf_phase_sel")
    
    df_phase_indexed = df_league[df_league['phase'] == sel_phase]
    teams_in_phase = sorted(list(set(df_phase_indexed['t1'].unique()) | set(df_phase_indexed['t2'].unique())))
    
    if not teams_in_phase:
        st.sidebar.warning("No teams found for this phase.")
        st.stop()
        
    target_team = st.sidebar.selectbox("Select Team", teams_in_phase, key="perf_team_sel")
    
    # --- RESET LOGIC ---
    current_context = f"{league}_{season}_{sel_phase}_{target_team}"
    if st.session_state.get("last_context") != current_context:
        st.session_state["perf_res_choice"] = ["Win", "Loss"]
        st.session_state["perf_venue_choice"] = ["Home", "Away"]
        if "perf_range_rnds" in st.session_state: del st.session_state["perf_range_rnds"]
        st.session_state["last_context"] = current_context
        st.rerun()

    view_type = st.sidebar.radio("Metric View", ["Net Impact", "Offensive Impact", "Defensive Impact"])
    
    # Filter games
    df_team = df_league[(df_league['season'] == season) & (df_league['phase'] == sel_phase) & 
                        ((df_league['t1'] == target_team) | (df_league['t2'] == target_team))].copy()
    
    df_team['is_win'] = df_team.apply(lambda x: (x['pts1'] > x['pts2'] if x['t1'] == target_team else x['pts2'] > x['pts1']), axis=1)
    df_team['venue'] = df_team.apply(lambda x: "Home" if x['t1'] == target_team else "Away", axis=1)

    all_rnds = sorted(df_team['round'].unique())
    res_choice = st.sidebar.multiselect("Game Result", ["Win", "Loss"], default=["Win", "Loss"], key="perf_res_choice")
    venue_choice = st.sidebar.multiselect("Venue", ["Home", "Away"], default=["Home", "Away"], key="perf_venue_choice")
    range_rnds = st.sidebar.select_slider("Round Range", options=all_rnds, value=(all_rnds[0], all_rnds[-1]), key="perf_range_rnds")

    allowed_wins = [True if r == "Win" else False for r in res_choice]
    start_idx = all_rnds.index(range_rnds[0]); end_idx = all_rnds.index(range_rnds[1])
    allowed_range = all_rnds[start_idx : end_idx+1]
    df_filtered = df_team[(df_team['is_win'].isin(allowed_wins)) & (df_team['venue'].isin(venue_choice)) & (df_team['round'].isin(allowed_range))]

    if df_filtered.empty:
        st.error("No games match this filter combination.")
        st.stop()

    performance_data = []
    for _, row in df_filtered.sort_values('round').iterrows():
        g = get_raw_game_data_custom(row['path'])
        if not g: continue
        is_t1 = g['t1_name'] == target_team
        stats_self, stats_opp = (g['t1_stats'], g['t2_stats']) if is_t1 else (g['t2_stats'], g['t1_stats'])
        
        opp_name = row['t2'] if is_t1 else row['t1']
        # --- NEW SCORE LOGIC ---
        # Format: [Target Team Score]-[Opponent Score]
        self_score = row['pts1'] if is_t1 else row['pts2']
        opp_score = row['pts2'] if is_t1 else row['pts1']
        score_display = f"{self_score}-{opp_score}"
        
        entry = {
            "Round": row['round'],
            "Opp_Logo": get_team_icon(opp_name),
            "Matchup": f"{'W' if row['is_win'] else 'L'} {'(H)' if row['venue']=='Home' else '(A)'} {score_display} vs {opp_name}",
            "Outcome": "W" if row['is_win'] else "L"
        }

        # CALCULATE 4F STATS (Always calculate these for the header metrics)
        f_off = calc_raw_factors(stats_self, stats_opp['drb'], lg_effic, lg_orb_pct)
        f_def = calc_raw_factors(stats_opp, stats_self['drb'], lg_effic, lg_orb_pct)
        f_def_inv = {k: -v for k, v in f_def.items()} 
        
        # Add the 'hidden' columns needed for the top metrics
        for f in ["Shooting", "Rebounding", "Turnovers", "Free Throws"]:
            entry[f"{f}_Net"] = f_off[f] + f_def_inv[f]
            entry[f"{f}_Off"] = f_off[f]
            entry[f"{f}_Def"] = f_def_inv[f]

        if analysis_type == "4-Factors Net Points":
            display_vals = f_off if view_type == "Offensive Impact" else (f_def_inv if view_type == "Defensive Impact" else {k: f_off[k] + f_def_inv[k] for k in f_off})
            entry.update({
                "Shooting": display_vals['Shooting'], "Turnovers": display_vals['Turnovers'],
                "Rebounding": display_vals['Rebounding'], "Free Throws": display_vals['Free Throws'],
                "Total 4F": sum(display_vals.values())
            })
        else:
            # Situational Points View
            entry.update({
                "Pts off TO": stats_self['pts_off_to'],
                "2nd Chance": stats_self['pts_2nd_ch'],
                "Fast Break": stats_self['pts_fb'],
            })
            p = get_4f_percentages(stats_self, stats_opp)
            entry.update(p)

        performance_data.append(entry)

    perf_df = pd.DataFrame(performance_data)
    st.markdown("---")
    perf_col1, perf_col2 = st.columns([1, 6])
    with perf_col1:
        team_logo = get_team_icon(target_team)
        if team_logo:
            st.image(team_logo, width=100)
    with perf_col2:
        st.title(f"Performance Report: {target_team}")
        st.markdown(f"#### {analysis_type} | {sel_phase}")
        st.caption(f"Season: {season} | Filters: {', '.join(res_choice)} | {', '.join(venue_choice)}")
    
    st.markdown("---")
    # --- TOP METRICS HEADER ---
    c_s, c_r, c_t, c_f = st.columns(4)
    if analysis_type == "4-Factors Net Points":
        for f_n, col in zip(["Shooting", "Rebounding", "Turnovers", "Free Throws"], [c_s, c_r, c_t, c_f]):
            with col:
                st.markdown(f"#### {f_n}")
                st.markdown(f"**Net: {perf_df[f_n+'_Net'].mean():+.2f}**")
                st.caption(f"O: {perf_df[f_n+'_Off'].mean():+.2f} | D: {perf_df[f_n+'_Def'].mean():+.2f}")
    else:
        # Show Situational Averages in the header instead
        sit_labels = ["Pts off TO", "2nd Chance", "Fast Break", "GP"]
        sit_cols = ["Pts off TO", "2nd Chance", "Fast Break", "Round"] # Round used just to count games
        for label, col_name, col_ui in zip(sit_labels, sit_cols, [c_s, c_r, c_t, c_f]):
            with col_ui:
                st.markdown(f"#### {label}")
                if label == "GP": st.markdown(f"**{len(perf_df)} Games**")
                else: st.markdown(f"**Avg: {perf_df[col_name].mean():.2f}**")

    
    # --- TABLE DISPLAY ---
    if analysis_type == "4-Factors Net Points":
        cols_visible = ["Round", "Opp_Logo", "Matchup", "Shooting", "Turnovers", "Rebounding", "Free Throws", "Total 4F"]
        format_dict = {k: "{:+.2f}" for k in ["Shooting", "Turnovers", "Rebounding", "Free Throws", "Total 4F"]}
        grad_cols = ["Shooting", "Turnovers", "Rebounding", "Free Throws", "Total 4F"]
    else:
        cols_visible = ["Round", "Opp_Logo", "Matchup", "Pts off TO", "2nd Chance", "Fast Break", "eFG%", "TO%", "ORB%", "FTR"]
        # 2. Formatting
        format_dict = {
            "Pts off TO": "{:.2f}", 
            "2nd Chance": "{:.2f}", 
            "Fast Break": "{:.2f}",
            "eFG%": "{:.1%}", 
            "TO%": "{:.1%}", 
            "ORB%": "{:.1%}", 
            "FTR": "{:.3f}"
        }
        grad_cols = ["Pts off TO", "2nd Chance", "Fast Break","eFG%", "TO%", "ORB%", "FTR"]

    st.markdown("---")
    # 1. Initialize the styler with basic formatting
    styler = perf_df.style.format(format_dict).map(
        lambda x: 'color: #27ae60; font-weight: bold;' if x == "W" else ('color: #c0392b; font-weight: bold;' if x == "L" else ''), 
        subset=['Outcome']
    )

    # 2. Apply Conditional Gradients
    if analysis_type == "4-Factors Net Points":
        # Standard Net Points Gradient (Symmetrical around 0)
        styler = styler.background_gradient(subset=grad_cols, cmap=custom_rdwgn, vmin=-15, vmax=15)
    else:
        # Situational Gradients (Context-aware)
        styler = styler.background_gradient(subset=['Pts off TO', '2nd Chance', 'Fast Break'], cmap=custom_wgn, vmin=0, vmax=30)
        styler = styler.background_gradient(subset=['eFG%'], cmap=custom_rdwgn, vmin=avg_efg-0.12, vmax=avg_efg+0.12)
        styler = styler.background_gradient(subset=['ORB%'], cmap=custom_rdwgn, vmin=avg_orb-0.15, vmax=avg_orb+0.15)
        styler = styler.background_gradient(subset=['FTR'], cmap=custom_rdwgn, vmin=avg_ftr-0.15, vmax=avg_ftr+0.15)
        styler = styler.background_gradient(subset=['TO%'], cmap=custom_gnwr, vmin=avg_to-0.06, vmax=avg_to+0.06)

    # 3. Render the dataframe
    st.dataframe(
        styler,
        use_container_width=True, hide_index=True, column_order=cols_visible,
        column_config={
            "Opp_Logo": st.column_config.ImageColumn("Opp", width="small"),
            "Round": st.column_config.TextColumn("Rnd", width="small")
        }
    )
    st.download_button(
    "Download PDF", 
    generate_performance_pdf(perf_df, target_team, league, season, view_type, analysis_type), 
    f"Scout_{target_team}.pdf"
)
    st.stop()
elif mode == "Overall League Standings":
    # 1. Phase Selection
    phases_in_index = sorted(df_league['phase'].unique())
    phase_options = ["Overall Season"] + phases_in_index
    selected_phase = st.sidebar.selectbox("Phase / Group", phase_options, key="standings_phase")
    
    st.subheader(f"{league} {season} - {selected_phase}")
    view_type = st.sidebar.radio("Metric View", ["Net Impact", "Offensive Impact", "Defensive Impact"])
    
    # 2. Filter Teams
    if selected_phase == "Overall Season":
        teams_to_analyze = sorted(list(set(df_league['t1'].unique()) | set(df_league['t2'].unique())))
    else:
        df_ph = df_league[df_league['phase'] == selected_phase]
        teams_to_analyze = sorted(list(set(df_ph['t1'].unique()) | set(df_ph['t2'].unique())))

    league_results = []
    with st.spinner("Calculating standings..."):
        for team in teams_to_analyze:
            if selected_phase == "Overall Season":
                t_off = get_per_game_volumes(team, league, season, "TOTAL")
                t_def = get_per_game_volumes(team, league, season, "Rival")
            else:
                t_off = get_per_game_volumes_by_phase(team, league, season, selected_phase, "TOTAL")
                t_def = get_per_game_volumes_by_phase(team, league, season, selected_phase, "Rival")
            
            if t_off['pts'] == 0: continue 

            if analysis_type == "4-Factors Net Points":
                lg_raw = calc_raw_factors(lg_data, lg_data['drb'], lg_effic, lg_orb_pct)
                t_off_raw = calc_raw_factors(t_off, lg_data['drb'], lg_effic, lg_orb_pct)
                t_def_raw = calc_raw_factors(t_def, t_off['drb'], lg_effic, lg_orb_pct)
                off_i = {k: (t_off_raw[k] - lg_raw[k]) for k in lg_raw}
                def_i = {k: (lg_raw[k] - t_def_raw[k]) for k in lg_raw}
                net_i = {k: off_i[k] + def_i[k] for k in lg_raw}
                disp = off_i if view_type == "Offensive Impact" else (def_i if view_type == "Defensive Impact" else net_i)
                
                league_results.append({
                    "Team_Logo": get_team_icon(team), "Team": team, 
                    "Shooting": disp['Shooting'], "Turnovers": disp['Turnovers'],
                    "Rebounding": disp['Rebounding'], "Free Throws": disp['Free Throws'],
                    "Net Points": sum(disp.values())
                })
            else:
                # Situational Standings
                p = get_4f_percentages(t_off, t_def)
                league_results.append({
                    "Team_Logo": get_team_icon(team), "Team": team,
                    "Pts off TO": t_off['pts_off_to'],
                    "2nd Chance": t_off['pts_2nd_ch'],
                    "Fast Break": t_off['pts_fb'],
                    "eFG%": p["eFG%"], "TO%": p["TO%"], "ORB%": p["ORB%"],
                    "FTR": p["FTR"] # ADDED FTR
                })
            
    if not league_results:
        st.error(f"No data found for {selected_phase}")
    else:
        sort_col = "Net Points" if analysis_type == "4-Factors Net Points" else "Pts off TO"
        standings_df = pd.DataFrame(league_results).sort_values(sort_col, ascending=False)
        standings_df.insert(0, "Rank", range(1, len(standings_df) + 1))

        # Determine which columns get the gradient
        if analysis_type == "4-Factors Net Points":
            grad_cols = ["Shooting", "Turnovers", "Rebounding", "Free Throws", "Net Points"]
            format_dict = {k: "{:+.2f}" for k in ["Shooting", "Turnovers", "Rebounding", "Free Throws", "Net Points"]}
        else:
            grad_cols = ["Pts off TO", "2nd Chance", "Fast Break", "eFG%", "TO%", "ORB%", "FTR"]
            format_dict = {k: "{:.2f}" for k in ["Pts off TO", "2nd Chance", "Fast Break","eFG%", "TO%", "ORB%", "FTR"]}

        # 1. Initialize Styler
    styler = standings_df.style.format(format_dict)

    # 2. Apply Conditional Gradients
    if analysis_type == "4-Factors Net Points":
        # Symmetrical around 0 for Net Points
        styler = styler.background_gradient(subset=['Shooting', 'Turnovers', 'Rebounding', 'Free Throws', 'Net Points'], cmap=custom_rdwgn, vmin=-10, vmax=10)
    else:
        # Situational Gradients
        styler = styler.background_gradient(subset=['Pts off TO', '2nd Chance', 'Fast Break'], cmap=custom_wgn, vmin=5, vmax=20)
        styler = styler.background_gradient(subset=['eFG%'], cmap=custom_rdwgn, vmin=avg_efg-0.06, vmax=avg_efg+0.06)
        styler = styler.background_gradient(subset=['ORB%'], cmap=custom_rdwgn, vmin=avg_orb-0.10, vmax=avg_orb+0.10)
        styler = styler.background_gradient(subset=['TO%'], cmap=custom_gnwr, vmin=avg_to-0.04, vmax=avg_to+0.04)
        styler = styler.background_gradient(subset=['FTR'], cmap=custom_rdwgn, vmin=avg_ftr-0.10, vmax=avg_ftr+0.10)

    # 3. Render
    st.dataframe(
        styler,
        use_container_width=True, height=600, hide_index=True,
        column_config={
            "Team_Logo": st.column_config.ImageColumn(" ", width="small"),
            "Rank": st.column_config.NumberColumn("Pos", width="small")
        }
    )
    st.download_button(
    "Download Standings PDF", 
    generate_standings_pdf(standings_df, league, season, selected_phase, analysis_type), 
    f"Standings_{selected_phase}.pdf"
)

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
    
    label = "4-Factors" if analysis_type == "4-Factors Net Points" else "4-Factors Classic"
    header_title = f"{label} Impact: {game_record['round']} - {t1} ({game_record['pts1']}) vs {t2} ({game_record['pts2']})"
# --- DISPLAY ---
# 1. Get icons
t1_icon = get_team_icon(t1)
t2_icon = get_team_icon(t2)

# 2. Build icon HTML
icon1_img = f'<img src="{t1_icon}" style="max-height: 80px; width: auto;">' if t1_icon else ""
icon2_img = f'<img src="{t2_icon}" style="max-height: 80px; width: auto;">' if t2_icon else ""

# 3. Header
header_html = f"""
<div style="display: flex; align-items: center; justify-content: space-between; width: 100%; margin-bottom: 10px;">
    <div style="flex: 1; text-align: left; min-width: 100px;">{icon1_img}</div>
    <div style="flex: 3; text-align: center;">
        <h1 style="margin: 0; font-size: 2.2rem; line-height: 1.2;">{header_title}</h1>
        <p style="margin: 5px 0 0 0; color: #666; font-size: 1.1rem; letter-spacing: 1px;">
            {league.upper()} <span style="color: #ccc; margin: 0 10px;">|</span> {season}
        </p>
    </div>
    <div style="flex: 1; text-align: right; min-width: 100px;">{icon2_img}</div>
</div>
<hr style="margin-top: 5px; margin-bottom: 25px; border: 0; border-top: 1px solid #eee;">
"""
st.markdown(header_html, unsafe_allow_html=True)


with st.container(border=True):
    if analysis_type == "4-Factors Net Points":
        st.plotly_chart(plot_4f_comparison(i1_tot, i2_tot, t1, t2), use_container_width=True)
    else:
        # Use the raw stats we extracted in Step 1
        # For Game Mode, these are in g['t1_stats'] and g['t2_stats']
        # For Aggregate Mode, these are in t1_off and t2_off
        s1 = g['t1_stats'] if mode == "Games Boxscores" else t1_off
        s2 = g['t2_stats'] if mode == "Games Boxscores" else t2_off
        st.plotly_chart(plot_situational_comparison(s1, s2, t1, t2), use_container_width=True)
# --- NEW: 4-Factors Percentages Table ---
        st.markdown("### Four Factors (%) Comparison")
        p1 = get_4f_percentages(s1, s2)
        p2 = get_4f_percentages(s2, s1)
        
        perc_df = pd.DataFrame([p1, p2], index=[t1, t2])
        st.table(perc_df)
# --- GLOSSARY / INTERPRETATION ---
# All of this is now properly nested inside the IF block
if analysis_type == "4-Factors Net Points":
    st.markdown("---")
    st.subheader("Scouting Interpretation")
    factors = ["Shooting", "Rebounding", "Turnovers", "Free Throws"]
    c1, c2 = st.columns(2)

    with c1:
        st.markdown(f"#### {t1} Impact")
        for f in factors:
            val = i1_tot[f]
            label = "contribution" if val >= 0 else "cost"
            advantage_text = ""
            if i1_tot[f] > i2_tot[f]:
                diff = i1_tot[f] - i2_tot[f]
                advantage_text = f" ({t1} was {diff:+.2f} pts more efficient)"
            st.write(f"• **{f}**: {val:+.2f} points {label}{advantage_text}")

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
            st.write(f"### {t2} (Away)")
            for f in factors: 
                st.markdown(f"**{f} Net: {i2_tot[f]:+.2f}** | Off: {i2_raw[0][f]:+.2f} | Def: {i2_raw[1][f]:+.2f}")

    # --- MASTER PDF EXPORT (Season Agg & Game Boxscore) ---
if mode in ["Season Aggregates per Team", "Games Boxscores"]:
    st.markdown("---")
    if st.button("Generate PDF Report", key="master_pdf_btn"):
        # 1. Determine Source Stats
        s1 = g['t1_stats'] if mode == "Games Boxscores" else t1_off
        s2 = g['t2_stats'] if mode == "Games Boxscores" else t2_off
        
        # 2. Prepare Data based on Analysis Type
        if analysis_type == "4-Factors Net Points":
            # Uses your existing MPL function
            chart_buf = create_pdf_chart_mpl(i1_tot, i2_tot, t1, t2)
            table_rows = [
                ("Shooting Net", f"{i1_tot['Shooting']:+.2f}", f"{i2_tot['Shooting']:+.2f}"),
                ("Turnovers Net", f"{i1_tot['Turnovers']:+.2f}", f"{i2_tot['Turnovers']:+.2f}"),
                ("Rebounding Net", f"{i1_tot['Rebounding']:+.2f}", f"{i2_tot['Rebounding']:+.2f}"),
                ("Free Throws Net", f"{i1_tot['Free Throws']:+.2f}", f"{i2_tot['Free Throws']:+.2f}")
            ]
        else:
            # Uses the new situational MPL function
            chart_buf = create_pdf_situational_mpl(s1, s2, t1, t2)
            p1 = get_4f_percentages(s1, s2)
            p2 = get_4f_percentages(s2, s1)
            table_rows = [
                ("Pts off TO", f"{s1['pts_off_to']:.1f}", f"{s2['pts_off_to']:.1f}"),
                ("2nd Chance", f"{s1['pts_2nd_ch']:.1f}", f"{s2['pts_2nd_ch']:.1f}"),
                ("Fast Break", f"{s1['pts_fb']:.1f}", f"{s2['pts_fb']:.1f}"),
                ("eFG%", p1['eFG%'], p2['eFG%']),
                ("TO%", p1['TO%'], p2['TO%']),
                ("ORB%", p1['ORB%'], p2['ORB%'])
            ]

        # 3. Generate and Show Download
        sub = f"{season} Aggregate" if mode == "Season Aggregates per Team" else f"{game_record['round']} Boxscore"
        pdf_bytes = generate_unified_report(chart_buf, t1, t2, analysis_type, sub, table_rows)
        
        st.download_button(
            label="Download PDF Report",
            data=pdf_bytes,
            file_name=f"Report_{t1}_{t2}.pdf",
            mime="application/pdf"
        )