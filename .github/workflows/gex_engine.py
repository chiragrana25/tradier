import os
import pandas as pd
import requests
import gspread
from google.oauth2.service_account import Credentials

# --- CONFIGURATION ---
# In GitHub, these are stored in Settings > Secrets
TRADIER_TOKEN = os.getenv('TRADIER_TOKEN')
SERVICE_ACCOUNT_FILE = 'service_account.json'
SHEET_NAME = 'GEX Dashboard' 

HEADERS = {'Authorization': f'Bearer {TRADIER_TOKEN}', 'Accept': 'application/json'}

def get_gex_data(symbol):
    # 1. Get Spot
    quote = requests.get(f'https://api.tradier.com/v1/markets/quotes?symbols={symbol}', headers=HEADERS).json()
    spot = float(quote['quotes']['quote']['last'])

    # 2. Get Expirations (Next 30 Days)
    exps_req = requests.get(f'https://api.tradier.com/v1/markets/options/expirations?symbol={symbol}', headers=HEADERS).json()
    all_exps = exps_req['expirations']['date']
    
    # Filter for ~30 DTE
    valid_exps = all_exps[:8] # Adjust based on frequency of expirations

    master_df = pd.DataFrame()

    for exp in valid_exps:
        url = f'https://api.tradier.com/v1/markets/options/chains?symbol={symbol}&expiration={exp}&greeks=true'
        resp = requests.get(url, headers=HEADERS).json()
        if not resp['options']: continue
        
        df = pd.DataFrame(resp['options']['option'])
        df['gamma'] = df['greeks'].apply(lambda x: x.get('gamma', 0) if x else 0)
        
        # Institutional GEX Math: Gamma * OI * 100 * Spot * (Spot * 0.01)
        df['gex'] = df['gamma'] * df['open_interest'] * 100 * spot * (spot * 0.01)
        df.loc[df['option_type'] == 'put', 'gex'] *= -1
        
        master_df[exp] = df.groupby('strike')['gex'].sum()

    # 3. Handle High-to-Low Sorting and Strike Window
    master_df = master_df.sort_index()
    atm_idx = (master_df.index.to_series() - spot).abs().argsort().iloc[0]
    final_df = master_df.iloc[max(0, atm_idx-15):atm_idx+16]
    final_df = final_df.sort_index(ascending=False).fillna(0)
    
    return final_df, spot

def run_update(symbol):
    scope = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=scope)
    client = gspread.authorize(creds)
    
    df, spot = get_gex_data(symbol)
    ss = client.open(SHEET_NAME)
    
    try:
        ws = ss.worksheet(symbol)
    except:
        ws = ss.add_worksheet(title=symbol, rows="100", cols="20")

    ws.clear()
    header = ["Strike"] + df.columns.tolist()
    data = [header] + [[idx] + row.tolist() for idx, row in df.iterrows()]
    ws.update('A1', data)

    # --- API LEVEL FORMATTING (True Heatmap) ---
    sheet_id = ws.id
    requests_body = {
        "requests": [
            {
                # Custom Number Format (M/K Labels)
                "repeatCell": {
                    "range": {"sheetId": sheet_id, "startRowIndex": 1, "startColumnIndex": 1},
                    "cell": {"userEnteredFormat": {"numberFormat": {"type": "NUMBER", "pattern": '[>999999]#,##0.0,,"M";[<-999999]-#,##0.0,,"M";[>999]#,##0.0,"K";[<-999]-#,##0.0,"K";0'}}},
                    "fields": "userEnteredFormat.numberFormat"
                }
            },
            {
                # 3-Point Gradient (Green-White-Red)
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [{"sheetId": sheet_id, "startRowIndex": 1, "endRowIndex": len(data), "startColumnIndex": 1, "endColumnIndex": len(header)}],
                        "gradientRule": {
                            "minpoint": {"color": {"red": 0.9, "green": 0.4, "blue": 0.4}, "type": "MIN"},
                            "midpoint": {"color": {"red": 1, "green": 1, "blue": 1}, "type": "NUMBER", "value": "0"},
                            "maxpoint": {"color": {"red": 0.4, "green": 0.8, "blue": 0.5}, "type": "MAX"}
                        }
                    },
                    "index": 0
                }
            }
        ]
    }
    ss.batch_update(requests_body)

if __name__ == "__main__":
    # You can read from a CSV or list
    for ticker in ["SPY", "QQQ"]:
        run_update(ticker)
