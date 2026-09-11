import os
import io
import glob
import re
import json
from datetime import datetime, timedelta
import pandas as pd
import yfinance as yf
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

def scarica_ultimo_csv_da_drive():
    """
    Si connette a Google Drive usando le credenziali salvate nell'ambiente
    e scarica il file CSV più recente contenente i dati del portafoglio.
    """
    # Legge le credenziali dalla variabile d'ambiente (iniettata da GitHub Secrets)
    creds_json = os.environ.get("GCP_SA_KEY_JSON")
    if not creds_json:
        print("Nessuna credenziale di Google Drive trovata nell'ambiente. Uso i file locali esistenti.")
        return

    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
    
    service = build('drive', 'v3', credentials=creds)
    
    # Cerca i file CSV nel Drive
    query = "mimeType = 'text/csv' and trashed = false"
    results = service.files().list(
        q=query, pageSize=10, fields="files(id, name, createdTime)"
    ).execute()
    
    files = results.get('files', [])
    if not files:
        raise FileNotFoundError("Nessun file CSV trovato su Google Drive.")
    
    # Ordina i file trovati per data di creazione (il più recente primo)
    files.sort(key=lambda x: x['createdTime'], reverse=True)
    piu_recente = files[0]
    
    file_id = piu_recente['id']
    file_name = piu_recente['name']
    print(f"Trovato file su Google Drive: {file_name} (ID: {file_id})")
    
    # Download del file
    request = service.files().get_media(fileId=file_id)
    fh = io.BytesIO()
    downloader = MediaIoBaseDownload(fh, request)
    done = False
    while not done:
        status, done = downloader.next_chunk()
        
    fh.seek(0)
    with open(file_name, 'wb') as f:
        f.write(fh.read())
        
    print(f"Scaricato con successo: {file_name}")

def trova_file_csv_piu_recente(directory='.'):
    pattern_data = re.compile(r'(\d{8})')
    file_csv = glob.glob(os.path.join(directory, '*.csv'))
    
    file_con_date = []
    for f in file_csv:
        nome_file = os.path.basename(f)
        match = pattern_data.search(nome_file)
        if match:
            str_data = match.group(1)
            try:
                dt = datetime.strptime(str_data, '%Y%m%d')
                file_con_date.append((dt, f))
            except ValueError:
                continue

    if file_con_date:
        file_con_date.sort(key=lambda x: x[0], reverse=True)
        return file_con_date[0][1]
    
    data_oggi = datetime.today().strftime('%Y%m%d')
    file_default = f"{data_oggi}.csv"
    if os.path.exists(file_default):
        return file_default
    
    raise FileNotFoundError("Nessun file CSV valido con formato data (YYYYMMDD) trovato nella cartella.")

def recupera_e_proietta_dividendi(open_tickers):
    """
    Recupera lo storico da yfinance e proietta le date future se non coprono l'orizzonte temporale,
    restituendo un dizionario con tuple (data, tipo_origine) dove tipo_origine è 'CONFERMATO' o 'PROIETTO'.
    """
    dizionario_dividendi = {}
    oggi = datetime.today()
    fine_proiezione = datetime(2050, 12, 31)
    
    for symbol in open_tickers:
        print(f"Elaborazione dividendi per: {symbol}...")
        date_storiche = []
        try:
            ticker_obj = yf.Ticker(symbol)
            divs = ticker_obj.dividends
            if not divs.empty:
                date_storiche = [ts.to_pydatetime().replace(tzinfo=None) for ts in divs.index]
        except Exception as e:
            print(f"Impossibile recuperare i dividendi da yfinance per {symbol}: {e}")
            
        eventi_ticker = []
        # Segna come storici/confermati quelli passati o presenti
        for d in sorted(list(set(date_storiche))):
            eventi_ticker.append((d, 'CONFERMATO'))
            
        # Se abbiamo uno storico, calcoliamo la frequenza per proiettare il futuro
        if len(date_storiche) > 0:
            date_ordinate = sorted(list(set(date_storiche)))
            if len(date_ordinate) > 1:
                diffs = [(date_ordinate[i+1] - date_ordinate[i]).days for i in range(len(date_ordinate)-1)]
                media_diff = sum(diffs) / len(diffs)
            else:
                media_diff = 365 # Default annuale se c'è una sola data
                
            if media_diff <= 45:
                intervallo_giorni = 30
            elif media_diff <= 120:
                intervallo_giorni = 90
            elif media_diff <= 220:
                intervallo_giorni = 180
            else:
                intervallo_giorni = 365

            ultima_data = date_ordinate[-1]
            prossima_data = ultima_data + timedelta(days=intervallo_giorni)
            
            # Proietta fino al 2050
            while prossima_data <= fine_proiezione:
                if prossima_data > oggi: # Aggiunge solo se è nel futuro
                    eventi_ticker.append((prossima_data, 'PROIETTO'))
                prossima_data += timedelta(days=intervallo_giorni)
                
        dizionario_dividendi[symbol] = sorted(eventi_ticker, key=lambda x: x[0])
        
    return dizionario_dividendi

def genera_ics(dizionario_dividendi, output_ics_filename="cedole_portafoglio.ics"):
    """
    Genera il file ICS distinguendo gli eventi confermati da quelli stimati/proiettati.
    """
    righe_ics = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Portfolio Dividend Calendar//IT",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH"
    ]
    
    for symbol, lista_eventi in dizionario_dividendi.items():
        for dt, tipo in lista_eventi:
            dt_str = dt.strftime('%Y%m%d')
            dt_end_str = (dt + timedelta(days=1)).strftime('%Y%m%d')
            
            if tipo == 'PROIETTO':
                uid = f"dividend-proj-{symbol}-{dt_str}@portafoglio"
                summary = f"Stacco Cedola [STIMA]: {symbol}"
                description = f"[PROIEZIONE STIMATA] Data stimata basata sulla frequenza storica per la posizione {symbol}. Da verificare."
            else:
                uid = f"dividend-conf-{symbol}-{dt_str}@portafoglio"
                summary = f"Stacco Cedola: {symbol}"
                description = f"Data di stacco / pagamento confermata da storico per la posizione {symbol}."
            
            righe_ics.extend([
                "BEGIN:VEVENT",
                f"UID:{uid}",
                f"DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}",
                f"DTSTART;VALUE=DATE:{dt_str}",
                f"DTEND;VALUE=DATE:{dt_end_str}",
                f"SUMMARY:{summary}",
                f"DESCRIPTION:{description}",
                "END:VEVENT"
            ])
            
    righe_ics.append("END:VCALENDAR")
    
    with open(output_ics_filename, 'w', encoding='utf-8') as f:
        f.write("\r\n".join(righe_ics))
    
    print(f"File calendario ICS generato con successo: {output_ics_filename}")

def elabora_portafoglio():
    file_csv = trova_file_csv_piu_recente()
    print(f"File selezionato per l'elaborazione: {file_csv}")

    df = pd.read_csv(file_csv)

    df_clean = df[df['Symbol'].notna()].copy()
    df_clean['Symbol'] = df_clean['Symbol'].str.strip()
    df_clean['Type_clean'] = df_clean['Type'].astype(str).str.strip().str.lower()
    df_clean = df_clean[~df_clean['Symbol'].str.contains('CASH|=X', case=False, na=False)].copy()

    def is_position_closed(group):
        group_sorted = group.sort_values('Id')
        types = group_sorted['Type_clean'].tolist()
        sell_all_indices = [i for i, t in enumerate(types) if t == 'sell all']
        if not sell_all_indices:
            return False 
        last_sell_all_idx = max(sell_all_indices)
        buys_after_sell = [i for i, t in enumerate(types) if t == 'buy' and i > last_sell_all_idx]
        return len(buys_after_sell) == 0

    closed_tickers = set()
    open_tickers = set()

    for symbol, group in df_clean.groupby('Symbol', sort=False):
        if is_position_closed(group):
            closed_tickers.add(symbol)
        else:
            open_tickers.add(symbol)

    return file_csv, open_tickers, closed_tickers

# --- ESECUZIONE ---
# 1. Scarica il CSV aggiornato da Google Drive (sfruttando il Secret)
scarica_ultimo_csv_da_drive()

# 2. Elabora il portafoglio e genera le proiezioni
file_utilizzato, posizioni_aperte, posizioni_chiuse = elabora_portafoglio()
dizionario_cedole = recupera_e_proietta_dividendi(posizioni_aperte)

output_ics_filename = f"cedole_proiettate_{os.path.splitext(os.path.basename(file_utilizzato))[0]}.ics"
genera_ics(dizionario_cedole, output_ics_filename)

print(f"\nPosizioni APERTE ({len(posizioni_aperte)}): {sorted(list(posizioni_aperte))}")
print(f"\nPosizioni CHIUSE ESCLUSE ({len(posizioni_chiuse)}): {sorted(list(posizioni_chiuse))}")
