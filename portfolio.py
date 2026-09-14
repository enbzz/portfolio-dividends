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
from duckduckgo_search import DDGS

def scarica_ultimo_csv_da_drive():
    creds_json = os.environ.get("GCP_SA_KEY_JSON")
    if not creds_json:
        print("Nessuna credenziale di Google Drive trovata nell'ambiente. Uso i file locali esistenti.")
        return

    creds_dict = json.loads(creds_json)
    creds = service_account.Credentials.from_service_account_info(
        creds_dict, scopes=['https://www.googleapis.com/auth/drive.readonly']
    )
    
    service = build('drive', 'v3', credentials=creds)
    id_cartella_drive = "1yTIFk78JwlL-M40qvavgJ75nUhj2obpP"
    query = f"'{id_cartella_drive}' in parents and trashed = false"
    
    results = service.files().list(
        q=query, pageSize=20, fields="files(id, name, createdTime)"
    ).execute()
    
    files = results.get('files', [])
    if not files:
        raise FileNotFoundError("Nessun file trovato nella cartella specificata su Google Drive.")
    
    files.sort(key=lambda x: x['createdTime'], reverse=True)
    piu_recente = files[0]
    
    file_id = piu_recente['id']
    file_name = piu_recente['name']
    print(f"Trovato file su Google Drive: {file_name} (ID: {file_id})")
    
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

def cerca_data_esatta_online(symbol, data_stimata):
    MIDA_MESI = {
        'january': 1, 'jan': 1, 'february': 2, 'feb': 2, 'march': 3, 'mar': 3, 
        'april': 4, 'apr': 4, 'may': 5, 'june': 6, 'jun': 6,
        'july': 7, 'jul': 7, 'august': 8, 'aug': 8, 'september': 9, 'sep': 9, 'sept': 9, 
        'october': 10, 'oct': 10, 'november': 11, 'nov': 11, 'december': 12, 'dec': 12,
        'gennaio': 1, 'febbraio': 2, 'marzo': 3, 'aprile': 4, 'maggio': 5, 'giugno': 6,
        'luglio': 7, 'agosto': 8, 'settembre': 9, 'ottobre': 10, 'novembre': 11, 'dicembre': 12
    }
    
    anno_str = data_stimata.strftime('%Y')
    query = f"{symbol} ex dividend date {anno_str}"
    
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=5))
            if not results:
                print(f"-> [WEB SEARCH] Nessun risultato restituito da DuckDuckGo per {symbol} (possibile blocco IP CI).")
            for r in results:
                snippet = r.get('body', '').lower()
                for nome_m, num_m in MIDA_MESI.items():
                    if nome_m in snippet:
                        match = re.search(rf'(\b\d{{1,2}}\s+{nome_m}\s+\d{{4}}|\b{nome_m}\s+\d{{1,2}},\s*\d{{4}}|\b\d{{1,2}}\s+{nome_m}|\b{nome_m}\s+\d{{1,2}})', snippet)
                        if match:
                            trovata_str = match.group(0)
                            parts = re.findall(r'\d+', trovata_str)
                            giorno = None
                            anno = int(anno_str)
                            
                            for p in parts:
                                if len(p) <= 2 and 1 <= int(p) <= 31:
                                    giorno = int(p)
                                elif len(p) == 4:
                                    anno = int(p)
                                    
                            if giorno:
                                try:
                                    data_verificata = datetime(anno, num_m, giorno)
                                    if abs((data_verificata - data_stimata).days) <= 45:
                                        print(f"-> [WEB VERIFIED] Data ufficiale trovata per {symbol}: {data_verificata.strftime('%Y-%m-%d')}")
                                        return data_verificata
                                except ValueError:
                                    continue
    except Exception as e:
        print(f"-> [WEB SEARCH ERROR] Impossibile verificare online la data per {symbol}: {e}")
        
    return None

def recupera_e_proietta_dividendi(open_tickers):
    dizionario_dividendi = {}
    oggi = datetime.today().replace(hour=0, minute=0, second=0, microsecond=0)
    fine_proiezione = datetime(2050, 12, 31)
    
    for symbol in open_tickers:
        print(f"\nElaborazione dividendi per: {symbol}...")
        date_storiche = set()
        
        try:
            ticker_obj = yf.Ticker(symbol)
            divs = ticker_obj.dividends
            if not divs.empty:
                for ts in divs.index:
                    d = ts.to_pydatetime().replace(tzinfo=None)
                    date_storiche.add(d)
        except Exception as e:
            print(f"Impossibile recuperare i dividendi storici da yfinance per {symbol}: {e}")
            
        data_ufficiale_futura = None
        try:
            cal = ticker_obj.calendar
            if isinstance(cal, dict):
                ex_date_val = cal.get('Ex-Dividend Date') or cal.get('exDividendDate')
                if ex_date_val:
                    if isinstance(ex_date_val, datetime):
                        data_ufficiale_futura = ex_date_val.replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
                    elif isinstance(ex_date_val, str):
                        data_ufficiale_futura = datetime.strptime(ex_date_val[:10], '%Y-%m-%d')
            elif isinstance(cal, pd.DataFrame) and not cal.empty:
                for idx in ['Ex-Dividend Date', 'exDividendDate']:
                    if idx in cal.index:
                        ex_date_val = cal.loc[idx].iloc[0]
                        if pd.notna(ex_date_val):
                            data_ufficiale_futura = pd.to_datetime(ex_date_val).replace(tzinfo=None, hour=0, minute=0, second=0, microsecond=0)
                            break
        except Exception as e:
            print(f"Nota: impossibile leggere il calendario nativo yfinance per {symbol}: {e}")

        if data_ufficiale_futura:
            print(f"-> [YFINANCE CALENDAR] Data ufficiale trovata via yfinance per {symbol}: {data_ufficiale_futura.strftime('%Y-%m-%d')}")

        eventi_ticker = []
        
        for d in sorted(list(date_storiche)):
            if d <= oggi:
                eventi_ticker.append((d, 'CONFERMATO'))

        ha_data_ufficiale_futura = False
        if data_ufficiale_futura and data_ufficiale_futura > oggi:
            eventi_ticker.append((data_ufficiale_futura, 'CONFERMATO'))
            ha_data_ufficiale_futura = True

        date_ordinate = sorted(list(date_storiche))
        if len(date_ordinate) > 0:
            if len(date_ordinate) > 1:
                diffs = [(date_ordinate[i+1] - date_ordinate[i]).days for i in range(len(date_ordinate)-1)]
                media_diff = sum(diffs) / len(diffs)
            else:
                media_diff = 365
                
            if media_diff <= 45:
                intervallo_giorni = 30
            elif media_diff <= 120:
                intervallo_giorni = 90
            elif media_diff <= 220:
                intervallo_giorni = 180
            else:
                intervallo_giorni = 365

            ultima_data = date_ordinate[-1]
            punto_partenza = data_ufficiale_futura if ha_data_ufficiale_futura else ultima_data
            prossima_data = punto_partenza + timedelta(days=intervallo_giorni)
            
            while prossima_data <= fine_proiezione:
                if prossima_data > oggi and not (ha_data_ufficiale_futura and prossima_data == data_ufficiale_futura):
                    if (prossima_data - oggi).days <= 35:
                        data_reale = cerca_data_esatta_online(symbol, prossima_data)
                        if data_reale:
                            eventi_ticker.append((data_reale, 'CONFERMATO'))
                        else:
                            eventi_ticker.append((prossima_data, 'PROIETTO'))
                    else:
                        eventi_ticker.append((prossima_data, 'PROIETTO'))
                prossima_data += timedelta(days=intervallo_giorni)
                
        eventi_unici = {}
        for dt, tipo in eventi_ticker:
            if dt not in eventi_unici or tipo == 'CONFERMATO':
                eventi_unici[dt] = tipo
                
        lista_finale = sorted([(dt, tipo) for dt, tipo in eventi_unici.items()], key=lambda x: x[0])
        dizionario_dividendi[symbol] = lista_finale
        
    return dizionario_dividendi

def genera_ics(dizionario_dividendi, output_ics_filename="cedole_proiettate.ics"):
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
                description = f"Data di stacco / pagamento confermata da dati ufficiali o verificata online per la posizione {symbol}."
            
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
    df.columns = [str(col).strip() for col in df.columns]
    
    col_map = {}
    for col in df.columns:
        col_lower = col.lower()
        if col_lower == 'symbol':
            col_map['Symbol'] = col
        elif col_lower == 'type':
            col_map['Type'] = col
        elif col_lower == 'id':
            col_map['Id'] = col

    if 'Symbol' not in col_map or 'Type' not in col_map:
        raise KeyError(f"Colonne necessarie non trovate nel CSV. Colonne disponibili: {list(df.columns)}")

    s_col = col_map['Symbol']
    t_col = col_map['Type']
    id_col = col_map.get('Id', df.columns[0])

    df_clean = df[df[s_col].notna()].copy()
    df_clean['Symbol'] = df_clean[s_col].str.strip()
    df_clean['Type_clean'] = df_clean[t_col].astype(str).str.strip().str.lower()
    df_clean = df_clean[~df_clean['Symbol'].str.contains('CASH|=X', case=False, na=False)].copy()

    def is_position_closed(group):
        if id_col in group.columns:
            group_sorted = group.sort_values(id_col)
        else:
            group_sorted = group
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
scarica_ultimo_csv_da_drive()
file_utilizzato, posizioni_aperte, posizioni_chiuse = elabora_portafoglio()
dizionario_dividendi = recupera_e_proietta_dividendi(posizioni_aperte)

output_ics_filename = "cedole_proiettate.ics"
genera_ics(dizionario_dividendi, output_ics_filename)

print(f"\nPosizioni APERTE ({len(posizioni_aperte)}): {sorted(list(posizioni_aperte))}")
print(f"\nPosizioni CHIUSE ESCLUSE ({len(posizioni_chiuse)}): {sorted(list(posizioni_chiuse))}")
