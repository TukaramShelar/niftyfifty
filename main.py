import os
import json
import datetime
import requests
import gspread
from google.oauth2.service_account import Credentials
import yfinance as yf

def get_nse_session():
    """Creates a browser-mimicking session for NSE endpoints."""
    session = requests.Session()
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/"
    }
    session.headers.update(headers)
    try:
        session.get("https://www.nseindia.com", timeout=10)
    except Exception as e:
        print(f"Session init warning: {e}")
    return session


def fetch_fiidii_data():
    """Fetches FII/DII cash segment data for NSE and combined exchanges."""
    fii_nse, dii_nse, fii_total, dii_total = 0.0, 0.0, 0.0, 0.0
    session = get_nse_session()
    
    try:
        resp_react = session.get("https://www.nseindia.com/api/fiidiiTradeReact", timeout=10)
        if resp_react.status_code == 200:
            for item in resp_react.json():
                cat = str(item.get("category", "")).upper()
                val = float(item.get("netValue", 0))
                if "FII" in cat or "FPI" in cat:
                    fii_nse = val
                elif "DII" in cat:
                    dii_nse = val

        resp_total = session.get("https://www.nseindia.com/api/fiidiiTradeTotal", timeout=10)
        if resp_total.status_code == 200:
            for item in resp_total.json():
                cat = str(item.get("category", "")).upper()
                val = float(item.get("netValue", 0))
                if "FII" in cat or "FPI" in cat:
                    fii_total = val
                elif "DII" in cat:
                    dii_total = val
        else:
            fii_total, dii_total = fii_nse, dii_nse
    except Exception as e:
        print(f"Warning: FII/DII fetch error - {e}")
    
    return fii_nse, dii_nse, fii_total, dii_total


def fetch_nifty_options_analytics():
    """Fetches Nifty Option Chain and calculates current expiry PCR."""
    pcr, max_pain_strike = 1.0, 25000
    session = get_nse_session()
    
    try:
        session.get("https://www.nseindia.com/option-chain", timeout=10)
        resp = session.get("https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY", timeout=10)
        
        if resp.status_code == 200:
            oc_data = resp.json()
            records = oc_data.get("records", {})
            expiry_dates = records.get("expiryDates", [])
            
            if expiry_dates:
                current_expiry = expiry_dates[0]
                data_list = records.get("data", [])
                
                total_call_oi = sum(item.get("CE", {}).get("openInterest", 0) for item in data_list if item.get("expiryDate") == current_expiry)
                total_put_oi = sum(item.get("PE", {}).get("openInterest", 0) for item in data_list if item.get("expiryDate") == current_expiry)
                
                if total_call_oi > 0:
                    pcr = round(total_put_oi / total_call_oi, 2)
                    
            filtered_ce = oc_data.get("filtered", {}).get("CE", {})
            if "totOI" in filtered_ce:
                max_pain_strike = oc_data.get("filtered", {}).get("data", [{}])[0].get("strikePrice", 25000)
    except Exception as e:
        print(f"Warning: Options Analytics fetch error - {e}")
        
    return pcr, max_pain_strike


def fetch_ticker_metrics(ticker_symbol):
    """Safely fetches price, point change, and percentage change using yfinance."""
    try:
        ticker = yf.Ticker(ticker_symbol)
        hist = ticker.history(period="5d")
        
        if not hist.empty and len(hist) >= 2:
            current_price = hist['Close'].iloc[-1]
            prev_close = hist['Close'].iloc[-2]
            point_change = current_price - prev_close
            pct_change = (point_change / prev_close) * 100
            
            return round(current_price, 2), f"{point_change:+.2f}", f"{pct_change:+.2f}%"
    except Exception as e:
        print(f"Warning: Ticker fetch error for {ticker_symbol} - {e}")
        
    return 0.0, "+0.00", "+0.00%"


def generate_market_analysis_row():
    """Compiles all parameters into the 22-column structure."""
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
    """Authenticates using GCP_SERVICE_ACCOUNT secret or local service_account.json."""
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    if "GCP_SERVICE_ACCOUNT" in os.environ:
        service_account_info = json.loads(os.environ["GCP_SERVICE_ACCOUNT"])
        creds = Credentials.from_service_account_info(service_account_info, scopes=scopes)
    else:
        creds = Credentials.from_service_account_file("service_account.json", scopes=scopes)
        
    return gspread.authorize(creds)


def run():
    print("Fetching Nifty 50 Options & Market Analysis Data...")
    data_row = generate_market_analysis_row()
    print("Generated Row:", data_row)
    
    client = get_gspread_client()
    sheet_name = os.environ.get("SPREADSHEET_NAME", "NiftyDailyData")
    
    spreadsheet = client.open(sheet_name)
    worksheet = spreadsheet.sheet1
    
    today_str = data_row[0]
    
    # Safe gspread append logic
    try:
        dates_in_col_a = worksheet.col_values(1)
        if today_str in dates_in_col_a:
            row_index = dates_in_col_a.index(today_str) + 1
            print(f"Row for {today_str} already exists at row {row_index}. Updating...")
            worksheet.update(values=[data_row], range_name=f"A{row_index}:V{row_index}")
            print("Successfully updated row!")
        else:
            worksheet.append_row(data_row)
            print("Successfully appended new row!")
    except Exception as e:
        print(f"Row update error, falling back to direct append: {e}")
        worksheet.append_row(data_row)


if __name__ == "__main__":
    run()