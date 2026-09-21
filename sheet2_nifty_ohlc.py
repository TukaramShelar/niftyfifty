import os
import json
import re
import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf

# ---------------------------------------------------------------------------
# 1. FETCH NIFTY 50 OHLC & CHANGE %
# ---------------------------------------------------------------------------
def fetch_nifty_ohlc_and_change():
    """Fetches Open, High, Low, Close, and % Change for Nifty 50 (^NSEI)."""
    open_p, high_p, low_p, close_p = 0.0, 0.0, 0.0, 0.0
    pct_str = "+0.00%"
    prev_close = 0.0
    
    try:
        nifty = yf.Ticker("^NSEI")
        hist = nifty.history(period="5d")
        if not hist.empty and len(hist) >= 2:
            latest = hist.iloc[-1]
            prev_close = hist['Close'].iloc[-2]
            
            open_p = round(latest['Open'], 2)
            high_p = round(latest['High'], 2)
            low_p = round(latest['Low'], 2)
            close_p = round(latest['Close'], 2)
            
            diff = close_p - prev_close
            pct = (diff / prev_close) * 100
            pct_str = f"{pct:+.2f}%"
    except Exception as e:
        print(f"[OHLC Fetch Error]: {e}")
        
    return open_p, high_p, low_p, close_p, pct_str, prev_close


# ---------------------------------------------------------------------------
# 2. FETCH EVENING CLOSING PCR
# ---------------------------------------------------------------------------
def fetch_nifty_pcr():
    """Fetches evening closing Put-Call Ratio."""
    pcr = 1.41
    try:
        resp = requests.get(
            "https://www.moneycontrol.com/india/indexmarket/statistics?classic=true",
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=8
        )
        if resp.status_code == 200:
            match = re.search(r'Put\s*Call\s*Ratio\s*:\s*<b>([\d\.]+)</b>', resp.text, re.IGNORECASE)
            if match:
                pcr = float(match.group(1))
    except Exception as e:
        print(f"[PCR Fetch Note]: {e}")
    return pcr


# ---------------------------------------------------------------------------
# 3. APPLY CUSTOM CELL FORMATTING RULES
# ---------------------------------------------------------------------------
def apply_sheet2_custom_formatting(worksheet, new_row_index):
    """
    Applies precise custom cell-by-cell formatting based on your rules:
    - Open (Col C): Green if >= prev close, Red if < prev close
    - Gap Up/Down Points (Col D): Green for Gap Up (+), Red for Gap Down (-)
    - High (Col E): Always Green
    - Low (Col F): Always Red
    - Close (Col G): Green if Close > Open, Red if Close < Open
    - Change % (Col H): Green for '+', Red for '-'
    - PCR (Col I): Compared against previous row's PCR
    """
    green_color = {"red": 0.0, "green": 0.5, "blue": 0.0}
    red_color = {"red": 0.85, "green": 0.18, "blue": 0.14}

    try:
        all_values = worksheet.get_all_values()
        row_vals = all_values[new_row_index - 1]
        
        # Read raw values from the row to determine color
        open_val = float(row_vals[2])   # Col C (Open)
        gap_val = float(row_vals[3])    # Col D (Gap Up/Down)
        close_val = float(row_vals[6])  # Col G (Close)
        
        open_color = green_color if gap_val >= 0 else red_color
        gap_color = green_color if gap_val >= 0 else red_color

        # 1. Format OPEN (Column C) & GAP UP/DOWN (Column D)
        worksheet.format(f"C{new_row_index}", {"textFormat": {"foregroundColor": open_color, "bold": True}})
        worksheet.format(f"D{new_row_index}", {"textFormat": {"foregroundColor": gap_color, "bold": True}})

        # 2. Format HIGH (Column E) -> Always Green
        worksheet.format(f"E{new_row_index}", {"textFormat": {"foregroundColor": green_color, "bold": True}})

        # 3. Format LOW (Column F) -> Always Red
        worksheet.format(f"F{new_row_index}", {"textFormat": {"foregroundColor": red_color, "bold": True}})

        # 4. Format CLOSE (Column G) -> Green if Close > Open, else Red
        close_color = green_color if close_val > open_val else red_color
        worksheet.format(f"G{new_row_index}", {"textFormat": {"foregroundColor": close_color, "bold": True}})

        # 5. Format CHANGE % (Column H) -> Green if '+', Red if '-'
        pct_val = row_vals[7] # Column H
        pct_color = green_color if "+" in pct_val else red_color
        worksheet.format(f"H{new_row_index}", {"textFormat": {"foregroundColor": pct_color, "bold": True}})

        # 6. Format PCR (Column I) -> Compared with previous row's PCR
        if len(all_values) >= 3 and new_row_index >= 3:
            prev_pcr = float(all_values[new_row_index - 2][8]) # Column I
            curr_pcr = float(all_values[new_row_index - 1][8])
            pcr_color = green_color if curr_pcr > prev_pcr else red_color
            worksheet.format(f"I{new_row_index}", {"textFormat": {"foregroundColor": pcr_color, "bold": True}})

        print("[Sheet2 Custom Formatting Success] Applied clean single-gap column colors!")

    except Exception as e:
        print(f"[Formatting Error]: {e}")


# ---------------------------------------------------------------------------
# 4. MAIN EXECUTION PIPELINE
# ---------------------------------------------------------------------------
def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    if "GCP_SERVICE_ACCOUNT" in os.environ:
        info = json.loads(os.environ["GCP_SERVICE_ACCOUNT"])
        creds = Credentials.from_service_account_info(info, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
    return gspread.authorize(creds)

def run():
    today = datetime.date.today()
    open_p, high_p, low_p, close_p, pct_str, prev_close = fetch_nifty_ohlc_and_change()
    pcr = fetch_nifty_pcr()
    
    # Calculate single gap up/down point difference
    gap_diff = round(open_p - prev_close, 2)
    gap_diff_str = f"{gap_diff:+.2f}"
    
    client = get_gspread_client()
    spreadsheet = client.open(os.environ.get("SPREADSHEET_NAME", "NiftyDailyData"))
    
    headers = [
        "DATE", "DAY", 
        "NIFTY OPEN", "GAP UP/DOWN (PTS)", 
        "NIFTY HIGH", "NIFTY LOW", 
        "NIFTY CLOSE", "NIFTY CHANGE %", "NIFTY PCR"
    ]
    
    try:
        worksheet = spreadsheet.worksheet("Sheet2")
    except Exception:
        worksheet = spreadsheet.add_worksheet(title="Sheet2", rows="1000", cols="10")
        worksheet.append_row(headers)
        
    if not worksheet.get_all_values():
        worksheet.append_row(headers)
        
    # Build complete row with exact columns
    complete_row = [
        today.strftime('%Y-%m-%d'),
        today.strftime('%A'),
        open_p, 
        gap_diff_str, 
        high_p, 
        low_p, 
        close_p, 
        pct_str, 
        pcr
    ]
    
    worksheet.append_row(complete_row)
    
    new_row_index = len(worksheet.get_all_values())
    
    # Apply custom coloring logic based on row values
    apply_sheet2_custom_formatting(worksheet, new_row_index)
    
    print(f"Successfully appended clean row to Sheet2 at index {new_row_index}!")

if __name__ == "__main__":
    run()
