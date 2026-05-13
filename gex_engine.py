import os
import json
import pandas as pd
import requests

# CONFIG
TRADIER_TOKEN = os.getenv('TRADIER_TOKEN')
# Paste your Google Web App URL here or put it in GitHub Secrets
APPS_SCRIPT_URL = os.getenv('APPS_SCRIPT_URL') 
HEADERS = {'Authorization': f'Bearer {TRADIER_TOKEN}', 'Accept': 'application/json'}

def run_gex(symbol):
    # --- MATH SECTION ---
    quote = requests.get(f'https://api.tradier.com/v1/markets/quotes?symbols={symbol}', headers=HEADERS).json()
    spot = float(quote['quotes']['quote']['last'])

    exps_req = requests.get(f'https://api.tradier.com/v1/markets/options/expirations?symbol={symbol}', headers=HEADERS).json()
    valid_exps = exps_req['expirations']['date'][:6]

    master_df = pd.DataFrame()
    for exp in valid_exps:
        url = f'https://api.tradier.com/v1/markets/options/chains?symbol={symbol}&expiration={exp}&greeks=true'
        resp = requests.get(url, headers=HEADERS).json()
        if not resp['options']: continue
        df = pd.DataFrame(resp['options']['option'])
        df['gamma'] = df['greeks'].apply(lambda x: x.get('gamma', 0) if x else 0)
        df['gex'] = df['gamma'] * df['open_interest'] * 100 * spot * (spot * 0.01)
        df.loc[df['option_type'] == 'put', 'gex'] *= -1
        master_df[exp] = df.groupby('strike')['gex'].sum()

    master_df = master_df.sort_index()
    atm_strike = master_df.index[min(range(len(master_df.index)), key=lambda i: abs(master_df.index[i]-spot))]
    final_df = master_df.iloc[max(0, master_df.index.get_loc(atm_strike)-15):master_df.index.get_loc(atm_strike)+16]
    final_df = final_df.sort_index(ascending=False).fillna(0)

    # --- PUSH SECTION ---
    payload = {
        "symbol": symbol,
        "atmStrike": atm_strike,
        "strikes": final_df.index.tolist(),
        "expirations": final_df.columns.tolist(),
        "values": final_df.values.tolist()
    }
    
    # Sending data to your Google Web App URL
    response = requests.post(APPS_SCRIPT_URL, json=payload)
    print(f"Status for {symbol}: {response.text}")

if __name__ == "__main__":
    for ticker in ["SPY", "QQQ"]:
        run_gex(ticker)
