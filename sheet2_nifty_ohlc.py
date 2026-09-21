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
def apply_sheet2_custom_formatting(worksheet, new_row_index, open_p, high_p, low_p, close_p, prev_close):
    """
    Applies precise custom cell-by-cell formatting based on your rules:
    - Open vs Prev Close (Col C): Green if >= prev close, Red if < prev close
    - Open Diff Points (Col D): Green for '+', Red for '-'
    - Gap Up/Down Points (Col E): Green for Gap Up (+), Red for Gap Down (-)
    - High (Col F): Always Green
    - Low (Col G): Always Red
    - Close vs Open (Col H): Green if Close > Open, Red if Close < Open
    - Change % (Col I): Green for '+', Red for '-'
    - PCR (Col J): Compared against previous row's PCR
    """
    green_color = {"red": 0.0, "green": 0.5, "blue": 0.0}
    red_color = {"red": 0.85, "green": 0.18, "blue": 0.14}

    try:
        all_values = worksheet.get_all_values()
        
        # Calculations
        open_vs_prev_diff = open_p - prev_close
        diff_str = f"{open_vs_prev_diff:+.2f}"
        
        open_color = green_color if open_p >= prev_close else red_color
        diff_color = green_color if open_vs_prev_diff >= 0 else red_color

        # 1. Format OPEN (Column C) & OPEN DIFF (Column D)
        worksheet.format(f"C{new_row_index}", {"textFormat": {"foregroundColor": open_color, "bold": True}})
        worksheet.format(f"D{new_row_index}", {"textFormat": {"foregroundColor": diff_color, "bold": True}})

        # 2. Format GAP UP/DOWN (Column E) -> Green if >= 0, Red if < 0
        worksheet.format(f"E{new_row_index}", {"textFormat": {"foregroundColor": diff_color, "bold": True}})

        # 3. Format HIGH (Column F) -> Always Green
        worksheet.format(f"F{new_row_index}", {"textFormat": {"foregroundColor": green_color, "bold": True}})

        # 4. Format LOW (Column G) -> Always Red
        worksheet.format(f"G{new_row_index}", {"textFormat": {"foregroundColor": red_color, "bold": True}})

        # 5. Format CLOSE (Column H) -> Green if Close > Open, else Red
        close_color = green_color if close_p > open_p else red_color
        worksheet.format(f"H{new_row_index}", {"textFormat": {"foregroundColor": close_color, "bold": True}})

        # 6. Format CHANGE % (Column I) -> Green if '+', Red if '-'
        pct_val = all_values[new_row_index - 1][8] # Column I
        pct_color = green_color if "+" in pct_val else red_color
        worksheet.format(f"I{new_row_index}", {"textFormat": {"foregroundColor": pct_color, "bold": True}})

        # 7. Format PCR (Column J) -> Compared with previous row's PCR
        if len(all_values) >= 3 and new_row_index >= 3:
            prev_pcr = float(all_values[new_row_index - 2][9]) # Column J
            curr_pcr = float(all_values[new_row_index - 1][9])
            pcr_color = green_color if curr_pcr > prev_pcr else red_color
            worksheet.format(f"J{new_row_index}", {"textFormat": {"foregroundColor": pcr_color, "bold": True}})

        print("[Sheet2 Custom Formatting Success] Applied custom Gap Up/Down and OHLC colors!")
        return diff_str

    except Exception as e:
        print(f"[Formatting Error]: {e}")
        return "+0.00"


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
    
    client = get_gspread_client()
    spreadsheet = client.open(os.environ.get("SPREADSHEET_NAME", "NiftyDailyData"))
    
    headers = [
        "DATE", "DAY", 
        "NIFTY OPEN", "OPEN DIFF (PTS)", "GAP UP/DOWN (PTS)",
        "NIFTY HIGH", "NIFTY LOW", 
        "NIFTY CLOSE", "NIFTY CHANGE %", "NIFTY PCR"
    ]
    
    try:
        worksheet = spreadsheet.worksheet("Sheet2")
    except Exception:
        worksheet = spreadsheet.add_worksheet(title="Sheet2", rows="1000", cols="12")
        worksheet.append_row(headers)
        
    if not worksheet.get_all_values():
        worksheet.append_row(headers)
        
    # Temporary placeholder row to calculate index
    temp_row = [
        today.strftime('%Y-%m-%d'),
        today.strftime('%A'),
        open_p, "0.00", "0.00", high_p, low_p, close_p, pct_str, pcr
    ]
    worksheet.append_row(temp_row)
    
    new_row_index = len(worksheet.get_all_values())
    
    # Apply custom coloring logic and get exact point difference string
    gap_diff_str = apply_sheet2_custom_formatting(worksheet, new_row_index, open_p, high_p, low_p, close_p, prev_close)
    
    # Update both Open Diff (Col D) and Gap Up/Down (Col E) with the calculated string value
    worksheet.update_cell(new_row_index, 4, gap_diff_str)
    worksheet.update_cell(new_row_index, 5, gap_diff_str)
    
    print(f"Successfully appended custom formatted row with Gap Up/Down analysis to Sheet2 at index {new_row_index}!")

if __name__ == "__main__":
    run()
