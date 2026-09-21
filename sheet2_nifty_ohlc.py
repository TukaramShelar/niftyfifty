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
    """
    Fetches Open, High, Low, Close, and % Change for Nifty 50 (^NSEI).
    Returns: (open_price, high_price, low_price, close_price, pct_change_str)
    """
    open_price, high_price, low_price, close_price = 0.0, 0.0, 0.0, 0.0
    pct_change_str = "+0.00%"
    
    try:
        nifty = yf.Ticker("^NSEI")
        hist = nifty.history(period="5d")
        if not hist.empty and len(hist) >= 2:
            latest = hist.iloc[-1]
            prev_close = hist['Close'].iloc[-2]
            
            open_price = round(latest['Open'], 2)
            high_price = round(latest['High'], 2)
            low_price = round(latest['Low'], 2)
            close_price = round(latest['Close'], 2)
            
            diff = close_price - prev_close
            pct_change = (diff / prev_close) * 100
            pct_change_str = f"{pct_change:+.2f}%"
            
            print(f"[OHLC Success] Open: {open_price}, High: {high_price}, Low: {low_price}, Close: {close_price}, Change %: {pct_change_str}")
    except Exception as e:
        print(f"[OHLC Fetch Error]: {e}")
        
    return open_price, high_price, low_price, close_price, pct_change_str


# ---------------------------------------------------------------------------
# 2. FETCH EVENING CLOSING PCR
# ---------------------------------------------------------------------------
def fetch_nifty_pcr():
    """Fetches Put-Call Ratio for active Nifty 50 contracts."""
    pcr = 1.41
    try:
        resp = requests.get(
            "https://www.moneycontrol.com/india/indexmarket/statistics?classic=true",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            timeout=8
        )
        if resp.status_code == 200:
            match = re.search(r'Put\s*Call\s*Ratio\s*:\s*<b>([\d\.]+)</b>', resp.text, re.IGNORECASE)
            if match:
                pcr = float(match.group(1))
                print(f"[PCR Success]: {pcr}")
                return pcr
    except Exception as e:
        print(f"[PCR Fetch Note]: {e}")

    try:
        nifty = yf.Ticker("^NSEI")
        if nifty.options:
            chain = nifty.option_chain(nifty.options[0])
            c_oi = chain.calls['openInterest'].sum()
            p_oi = chain.puts['openInterest'].sum()
            if c_oi > 0:
                pcr = round(p_oi / c_oi, 2)
    except Exception as e:
        print(f"[YFinance PCR Note]: {e}")

    return pcr


# ---------------------------------------------------------------------------
# 3. BUILD SHEET2 ROW VECTOR
# ---------------------------------------------------------------------------
def generate_sheet2_row():
    today = datetime.date.today()
    today_str = today.strftime('%Y-%m-%d')
    day_name = today.strftime('%A')
    
    open_price, high_price, low_price, close_price, pct_change_str = fetch_nifty_ohlc_and_change()
    pcr = fetch_nifty_pcr()
    
    row = [
        today_str,
        day_name,
        open_price,
        high_price,
        low_price,
        close_price,
        pct_change_str,
        pcr
    ]
    return row


# ---------------------------------------------------------------------------
# 4. AUTHENTICATE & WRITE TO SHEET2
# ---------------------------------------------------------------------------
def get_gspread_client():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    if "GCP_SERVICE_ACCOUNT" in os.environ:
        info = json.loads(os.environ["GCP_SERVICE_ACCOUNT"])
        creds = Credentials.from_service_account_info(info, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
    return gspread.authorize(creds)


def run():
    print("Executing Evening Nifty 50 OHLC Pipeline for Sheet2...")
    data_row = generate_sheet2_row()
    print("Compiled Sheet2 Data Row:", data_row)
    
    client = get_gspread_client()
    sheet_name = os.environ.get("SPREADSHEET_NAME", "NiftyDailyData")
    
    spreadsheet = client.open(sheet_name)
    
    headers = ["DATE", "DAY", "NIFTY OPEN", "NIFTY HIGH", "NIFTY LOW", "NIFTY CLOSE", "NIFTY CHANGE %", "NIFTY PCR"]
    
    # Get or Create Sheet2
    try:
        worksheet = spreadsheet.worksheet("Sheet2")
    except Exception:
        worksheet = spreadsheet.add_worksheet(title="Sheet2", rows="1000", cols="10")
        worksheet.append_row(headers)
    
    # Verify/Set Headers if sheet is empty or header is outdated
    existing_records = worksheet.get_all_values()
    if not existing_records:
        worksheet.append_row(headers)
    elif "CHANGE" not in existing_records[0][6]:
        # Update row 1 headers if previous header layout existed
        worksheet.update_row(1, headers) if hasattr(worksheet, 'update_row') else worksheet.update(values=[headers], range_name="A1:H1")

    worksheet.append_row(data_row)
    print("Successfully appended Nifty OHLC + Change % row to Sheet2!")


if __name__ == "__main__":
    run()
