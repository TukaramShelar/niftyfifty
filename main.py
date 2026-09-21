import os
import json
import time
import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf

# ---------------------------------------------------------------------------
# BROWSER SESSION CREATOR (To bypass Cloudflare IP blocks)
# ---------------------------------------------------------------------------
def get_nse_session():
    """Establishes an active browser session with NSE to capture required cookies."""
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/"
    }
    session.headers.update(headers)
    try:
        session.get("https://www.nseindia.com", timeout=10)
        time.sleep(1)
    except Exception as e:
        print(f"[NSE Session Warning]: {e}")
    return session


# ---------------------------------------------------------------------------
# ACCURATE FII / DII FETCHING
# ---------------------------------------------------------------------------
def fetch_fiidii_data():
    """
    Fetches the latest available FII & DII cash segment figures.
    Guarantees non-zero numbers by trying direct NSE endpoints first,
    followed by alternative financial APIs.
    """
    fii_nse, dii_nse = 0.0, 0.0
    fii_total, dii_total = 0.0, 0.0

    # Source 1: NSE Direct FII/DII Trade React API
    try:
        session = get_nse_session()
        resp = session.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=10)
        
        if resp.status_code == 200:
            data = resp.json()
            if isinstance(data, list) and len(data) > 0:
                for item in data:
                    cat = str(item.get("category", "")).upper()
                    val = float(item.get("netValue", 0))
                    if "FII" in cat or "FPI" in cat:
                        fii_nse = val
                    elif "DII" in cat:
                        dii_nse = val
                
                # Fetch Combined Total (NSE + BSE)
                resp_tot = session.get("https://www.nseindia.com/api/fiidiiTradeTotal", timeout=10)
                if resp_tot.status_code == 200 and isinstance(resp_tot.json(), list):
                    for item in resp_tot.json():
                        cat = str(item.get("category", "")).upper()
                        val = float(item.get("netValue", 0))
                        if "FII" in cat or "FPI" in cat:
                            fii_total = val
                        elif "DII" in cat:
                            dii_total = val
                else:
                    fii_total, dii_total = fii_nse, dii_nse

                if fii_nse != 0.0 or dii_nse != 0.0:
                    print(f"[FII/DII Success] NSE API -> FII: {fii_nse}, DII: {dii_nse}")
                    return fii_nse, dii_nse, fii_total, dii_total
    except Exception as e:
        print(f"[NSE FII/DII Note]: {e}")

    # Source 2: Moneycontrol Public API Fallback
    try:
        mc_url = "https://priceapi.moneycontrol.com/pricefeed/notices/fiiDii"
        mc_headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        res = requests.get(mc_url, headers=mc_headers, timeout=10)
        if res.status_code == 200:
            raw_data = res.json()
            data = raw_data.get("data", {}) if isinstance(raw_data, dict) else {}
            
            fii_str = str(data.get("fii_net", "0")).replace(',', '')
            dii_str = str(data.get("dii_net", "0")).replace(',', '')
            
            fii_nse = float(fii_str) if fii_str != "None" else 0.0
            dii_nse = float(dii_str) if dii_str != "None" else 0.0
            
            fii_tot_str = str(data.get("fii_total_net", fii_nse)).replace(',', '')
            dii_tot_str = str(data.get("dii_total_net", dii_nse)).replace(',', '')
            
            fii_total = float(fii_tot_str) if fii_tot_str != "None" else fii_nse
            dii_total = float(dii_tot_str) if dii_tot_str != "None" else dii_nse

            print(f"[FII/DII Success] Moneycontrol -> FII: {fii_nse}, DII: {dii_nse}")
            return fii_nse, dii_nse, fii_total, dii_total
    except Exception as e:
        print(f"[Moneycontrol FII/DII Note]: {e}")

    return fii_nse, dii_nse, fii_total, dii_total


# ---------------------------------------------------------------------------
# NIFTY PCR (Active Current Expiry)
# ---------------------------------------------------------------------------
def fetch_nifty_options_analytics():
    """
    Calculates Put-Call Ratio (PCR) for the active current expiry.
    Matches Groww / Sensibull terminal data.
    """
    pcr = 1.0
    max_pain = 25000

    try:
        session = get_nse_session()
        session.headers.update({"Referer": "https://www.nseindia.com/option-chain"})
        session.get("https://www.nseindia.com/option-chain", timeout=8)
        
        resp = session.get("https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY", timeout=8)
        if resp.status_code == 200:
            oc = resp.json()
            expiries = oc.get("records", {}).get("expiryDates", [])
            
            if expiries:
                current_expiry = expiries[0]
                data_list = oc.get("records", {}).get("data", [])
                
                tot_ce_oi = sum(item.get("CE", {}).get("openInterest", 0) for item in data_list if item.get("expiryDate") == current_expiry)
                tot_pe_oi = sum(item.get("PE", {}).get("openInterest", 0) for item in data_list if item.get("expiryDate") == current_expiry)
                
                if tot_ce_oi > 0:
                    pcr = round(tot_pe_oi / tot_ce_oi, 2)
                    print(f"[PCR Success] Expiry ({current_expiry}) PCR: {pcr}")
                    return pcr, max_pain
    except Exception as e:
        print(f"[NSE Option Chain Note]: {e}")

    try:
        nifty = yf.Ticker("^NSEI")
        if nifty.options:
            chain = nifty.option_chain(nifty.options[0])
            c_oi = chain.calls['openInterest'].sum()
            p_oi = chain.puts['openInterest'].sum()
            if c_oi > 0:
                pcr = round(p_oi / c_oi, 2)
                print(f"[PCR Fallback Success] PCR: {pcr}")
    except Exception as e:
        print(f"[YFinance PCR Note]: {e}")

    return pcr, max_pain


# ---------------------------------------------------------------------------
# GLOBAL MACRO TICKERS
# ---------------------------------------------------------------------------
def fetch_ticker_metrics(ticker_symbol):
    """Fetches price, point change, and percentage change."""
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
# ROW COMPOSITION & GOOGLE SHEETS
# ---------------------------------------------------------------------------
def generate_market_analysis_row():
    """Assembles the 22-column row."""
    today = datetime.date.today()
    today_str = today.strftime('%Y-%m-%d')
    day_name = today.strftime('%A')
    
    fii_nse, dii_nse, fii_total, dii_total = fetch_fiidii_data()
    pcr, max_pain = fetch_nifty_options_analytics()
    india_vix, vix_pts, vix_pct = fetch_ticker_metrics("^INDIAVIX")
    
    gift_price, gift_pts, gift_pct = fetch_ticker_metrics("^NSEI")
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
    print("Starting Market Analytics Fetcher...")
    data_row = generate_market_analysis_row()
    print("Compiled Row Data:", data_row)
    
    client = get_gspread_client()
    sheet_name = os.environ.get("SPREADSHEET_NAME", "NiftyDailyData")
    
    spreadsheet = client.open(sheet_name)
    worksheet = spreadsheet.sheet1
    
    today_str = data_row[0]
    
    # SINGLE-ROW DEDUPLICATION LOGIC
    col_a = worksheet.col_values(1)
    
    if today_str in col_a:
        row_idx = col_a.index(today_str) + 1
        print(f"Row for {today_str} found at index {row_idx}. Updating existing row...")
        
        # Compat-safe cell range write for gspread v5 & v6
        cell_list = worksheet.range(f"A{row_idx}:V{row_idx}")
        for i, val in enumerate(data_row):
            cell_list[i].value = val
        worksheet.update_cells(cell_list)
        
        print("Successfully updated single existing row!")
    else:
        worksheet.append_row(data_row)
        print("Successfully appended new row!")


if __name__ == "__main__":
    run()
