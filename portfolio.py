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
    open_tickers = set()  # <-- Corretto da "in set()" a "= set()"

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
