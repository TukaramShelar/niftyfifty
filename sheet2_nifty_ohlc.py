import os
import json
import re
import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf

# ---------------------------------------------------------------------------
# 1. FETCH NIFTY 50 OHLC (OPEN, HIGH, LOW, CLOSE)
# ---------------------------------------------------------------------------
def fetch_nifty_ohlc():
    """Fetches Open, High, Low, Close prices for Nifty 50 (^NSEI)."""
    open_price, high_price, low_price, close_price = 0.0, 0.0, 0.0, 0.0
    try:
        nifty = yf.Ticker("^NSEI")
        hist = nifty.history(period="5d")
        if not hist.empty:
            latest = hist.iloc[-1]
            open_price = round(latest['Open'], 2)
            high_price = round(latest['High'], 2)
            low_price = round(latest['Low'], 2)
            close_price = round(latest['Close'], 2)
            print(f"[OHLC Success] Open: {open_price}, High: {high_price}, Low: {low_price}, Close: {close_price}")
    except Exception as e:
        print(f"[OHLC Fetch Error]: {e}")
        
    return open_price, high_price, low_price, close_price


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
    
    open_price, high_price, low_price, close_price = fetch_nifty_ohlc()
    pcr = fetch_nifty_pcr()
    
    row = [
        today_str,
        day_name,
        open_price,
        high_price,
        low_price,
        close_price,
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
    
    # Target Sheet2
    try:
        worksheet = spreadsheet.worksheet("Sheet2")
    except Exception:
        worksheet = spreadsheet.add_worksheet(title="Sheet2", rows="1000", cols="10")
        worksheet.append_row(["DATE", "DAY", "NIFTY OPEN", "NIFTY HIGH", "NIFTY LOW", "NIFTY CLOSE", "NIFTY PCR"])
    
    # Ensure Header exists if sheet is empty
    existing_records = worksheet.get_all_values()
    if not existing_records:
        worksheet.append_row(["DATE", "DAY", "NIFTY OPEN", "NIFTY HIGH", "NIFTY LOW", "NIFTY CLOSE", "NIFTY PCR"])

    worksheet.append_row(data_row)
    print("Successfully appended Nifty OHLC row to Sheet2!")


if __name__ == "__main__":
    run()
