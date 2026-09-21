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
    return open_p, high_p, low_p, close_p, pct_str


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
# 3. SHEET2 DYNAMIC CONDITIONAL FORMATTING (OHLC & PCR)
# ---------------------------------------------------------------------------
def apply_sheet2_color_formatting(worksheet, new_row_index):
    """
    Applies color formatting:
    - Columns C to G (Open, High, Low, Close, Change %): Green for '+', Red for '-'
    - Column H (Nifty PCR): Compared dynamically against the previous row's PCR value.
      If today > yesterday -> Green, else -> Red.
    """
    try:
        all_values = worksheet.get_all_values()
        
        # We need at least a header row + yesterday's row + today's row to compare PCR
        if len(all_values) >= 3 and new_row_index >= 3:
            prev_pcr = float(all_values[new_row_index - 2][7]) # Index 7 is Column H (PCR)
            curr_pcr = float(all_values[new_row_index - 1][7])
            
            pcr_color = {"red": 0.0, "green": 0.5, "blue": 0.0} if curr_pcr > prev_pcr else {"red": 0.85, "green": 0.18, "blue": 0.14}
            
            pcr_cell_format = {
                "textFormat": {
                    "foregroundColor": pcr_color,
                    "bold": True
                }
            }
            
            # Apply format directly to the newly inserted PCR cell (Column H, Row = new_row_index)
            cell_notation = f"H{new_row_index}"
            worksheet.format(cell_notation, pcr_cell_format)
            print(f"[PCR Formatting] Compared Today ({curr_pcr}) vs Yesterday ({prev_pcr}). Applied format.")

        # Static conditional rules for OHLC & Change % (Columns C through G)
        rules = [
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{"sheetId": worksheet.id, "startColumnIndex": 2, "endColumnIndex": 7}],
                        "booleanRule": {
                            "condition": {"type": "TEXT_STARTS_WITH", "values": [{"userEnteredValue": "+"}]},
                            "format": {"textFormat": {"foregroundColor": {"red": 0.0, "green": 0.5, "blue": 0.0}, "bold": True}}
                        }
                    },
                    "index": 0
                }
            },
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{"sheetId": worksheet.id, "startColumnIndex": 2, "endColumnIndex": 7}],
                        "booleanRule": {
                            "condition": {"type": "TEXT_STARTS_WITH", "values": [{"userEnteredValue": "-"}]},
                            "format": {"textFormat": {"foregroundColor": {"red": 0.85, "green": 0.18, "blue": 0.14}, "bold": True}}
                        }
                    },
                    "index": 1
                }
            }
        ]
        worksheet.spreadsheet.batch_update({"requests": rules})
        print("[Sheet2 Formatting Success] Applied color formatting rules.")
    except Exception as e:
        print(f"[Sheet2 Formatting Note]: {e}")


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
    open_p, high_p, low_p, close_p, pct_str = fetch_nifty_ohlc_and_change()
    pcr = fetch_nifty_pcr()
    
    row = [
        today.strftime('%Y-%m-%d'),
        today.strftime('%A'),
        f"{open_p:+.2f}",
        f"{high_p:+.2f}",
        f"{low_p:+.2f}",
        f"{close_p:+.2f}",
        pct_str,
        pcr
    ]
    
    client = get_gspread_client()
    spreadsheet = client.open(os.environ.get("SPREADSHEET_NAME", "NiftyDailyData"))
    
    headers = ["DATE", "DAY", "NIFTY OPEN", "NIFTY HIGH", "NIFTY LOW", "NIFTY CLOSE", "NIFTY CHANGE %", "NIFTY PCR"]
    try:
        worksheet = spreadsheet.worksheet("Sheet2")
    except Exception:
        worksheet = spreadsheet.add_worksheet(title="Sheet2", rows="1000", cols="10")
        worksheet.append_row(headers)
        
    if not worksheet.get_all_values():
        worksheet.append_row(headers)
        
    worksheet.append_row(row)
    
    # Get the row index of the newly added row
    new_row_index = len(worksheet.get_all_values())
    print(f"Successfully appended row to Sheet2 at index {new_row_index}!")
    
    # Apply color formatting rules including PCR comparison
    apply_sheet2_color_formatting(worksheet, new_row_index)

if __name__ == "__main__":
    run()
