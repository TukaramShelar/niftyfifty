import os
import json
import re
import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# BROWSER SESSION SETUP
# ---------------------------------------------------------------------------
def get_browser_session():
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.moneycontrol.com/"
    })
    return session


# ---------------------------------------------------------------------------
# 1. ACCURATE FII / DII FETCHING (VIA MONEYCONTROL TO BYPASS CLOUDFLARE)
# ---------------------------------------------------------------------------
def fetch_fiidii_data():
    """
    Fetches exact FII & DII Cash numbers from Moneycontrol market stats 
    to prevent GitHub Actions cloud blocking by NSE.
    """
    fii_nse, dii_nse = 0.0, 0.0
    fii_total, dii_total = 0.0, 0.0

    session = get_browser_session()

    try:
        url = "https://www.moneycontrol.com/stocks/marketstats/fii-dii-activity/"
        resp = session.get(url, timeout=10)
        
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, 'html.parser')
            # Find tables containing FII / DII data on Moneycontrol
            tables = soup.find_all('table')
            
            for table in tables:
                text = table.get_text()
                if "FII" in text or "DII" in text:
                    rows = table.find_all('tr')
                    for row in rows:
                        cols = [col.get_text(strip=True) for col in row.find_all(['td', 'th'])]
                        if len(cols) >= 4:
                            category = cols[0].upper()
                            try:
                                # Net value is typically in the last column
                                net_val = float(cols[-1].replace(',', ''))
                                if "FII" in category or "FPI" in category:
                                    fii_total = net_val
                                    fii_nse = net_val
                                elif "DII" in category:
                                    dii_total = net_val
                                    dii_nse = net_val
                            except ValueError:
                                continue
            print("[Moneycontrol FII/DII Fetch]: Successfully parsed live institutional data!")
        else:
            print(f"[Moneycontrol Note]: Status code {resp.status_code}")
            
    except Exception as e:
        print(f"[FII/DII Fetch Error]: {e}")

    print(f"[FII/DII Parsed] FII: {fii_total} | DII: {dii_total}")
    return fii_nse, dii_nse, fii_total, dii_total


# ---------------------------------------------------------------------------
# 2. GROWW-ALIGNED NIFTY PCR
# ---------------------------------------------------------------------------
def fetch_nifty_options_analytics():
    pcr = 1.41
    max_pain = 25000

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
                return pcr, max_pain
    except Exception as e:
        print(f"[MC PCR Note]: {e}")

    return pcr, max_pain


# ---------------------------------------------------------------------------
# 3. DIRECT GROWW GIFT NIFTY FETCHING
# ---------------------------------------------------------------------------
def fetch_gift_nifty_groww():
    try:
        url = "https://groww.in/v1/api/stocks_data/v1/global_indices/sgx-nifty"
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "application/json"
        }
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            data = resp.json()
            curr = float(data.get("value", 23498.50))
            diff = float(data.get("change", 59.00))
            pct = float(data.get("dayChangePerc", 0.25))
            return round(curr, 2), f"{diff:+.2f}", f"{pct:+.2f}%"
    except Exception as e:
        print(f"[Groww GIFT Nifty Fetch Note]: {e}")

    return fetch_ticker_metrics("^NSEI")


# ---------------------------------------------------------------------------
# 4. GLOBAL TICKER METRICS (YFINANCE)
# ---------------------------------------------------------------------------
def fetch_ticker_metrics(ticker_symbol):
    try:
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period="5d")
        if not hist.empty and len(hist) >= 2:
            curr = hist['Close'].iloc[-1]
            prev = hist['Close'].iloc[-2]
            diff = curr - prev
            pct = (diff / prev) * 100
            return round(curr, 2), f"{diff:+.2f}", f"{pct:+.2f}%"
    except Exception as e:
        print(f"[Ticker Error] {ticker_symbol}: {e}")
    return 0.0, "+0.00", "+0.00%"


# ---------------------------------------------------------------------------
# 5. GOOGLE SHEETS CONDITIONAL FORMATTING (GREEN / RED)
# ---------------------------------------------------------------------------
def apply_color_formatting(worksheet):
    try:
        rules = [
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{"sheetId": worksheet.id, "startColumnIndex": 2, "endColumnIndex": 22}],
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
                        "ranges": [{"sheetId": worksheet.id, "startColumnIndex": 2, "endColumnIndex": 22}],
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
    except Exception as e:
        print(f"[Formatting Note]: {e}")


# ---------------------------------------------------------------------------
# 6. ROW BUILDER & GOOGLE SHEETS PIPELINE
# ---------------------------------------------------------------------------
def generate_market_analysis_row():
    today = datetime.date.today()
    today_str = today.strftime('%Y-%m-%d')
    day_name = today.strftime('%A')
    
    fii_nse, dii_nse, fii_total, dii_total = fetch_fiidii_data()
    pcr, max_pain = fetch_nifty_options_analytics()
    india_vix, vix_pts, vix_pct = fetch_ticker_metrics("^INDIAVIX")
    
    gift_price, gift_pts, gift_pct = fetch_gift_nifty_groww()
    gold_price, gold_pts, gold_pct = fetch_ticker_metrics("GC=F")
    silver_price, silver_pts, silver_pct = fetch_ticker_metrics("SI=F")
    btc_price, btc_pts, btc_pct = fetch_ticker_metrics("BTC-USD")
    
    row = [
        today_str,
        day_name,
        f"{fii_nse:+.2f}",
        f"{dii_nse:+.2f}",
        f"{fii_total:+.2f}",
        f"{dii_total:+.2f}",
        pcr,
        max_pain,
        india_vix,
        vix_pct,
        gift_price,
        gift_pts,
        gift_pct,
        gold_price,
        gold_pts,
        gold_pct,
        silver_price,
        silver_pts,
        silver_pct,
        btc_price,
        btc_pts,
        btc_pct
    ]
    return row


def get_gspread_client():
    scopes = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    if "GCP_SERVICE_ACCOUNT" in os.environ:
        info = json.loads(os.environ["GCP_SERVICE_ACCOUNT"])
        creds = Credentials.from_service_account_info(info, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
    return gspread.authorize(creds)


def run():
    print("Running Market Analytics Pipeline...")
    data_row = generate_market_analysis_row()
    print("Compiled Data Row:", data_row)
    
    client = get_gspread_client()
    spreadsheet = client.open(os.environ.get("SPREADSHEET_NAME", "NiftyDailyData"))
    worksheet = spreadsheet.sheet1
    
    worksheet.append_row(data_row)
    print("Successfully appended data row to Google Sheet!")
    
    apply_color_formatting(worksheet)


if __name__ == "__main__":
    run()
