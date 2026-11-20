"""Data sintetis berbentuk hasil query outlet_sql/series_sql/audit_sql (untuk uji RFM tanpa BigQuery)."""
import random
from library_agent import rfm_engine as re_  # noqa: E402

def make(n=3000, seed=7):
    random.seed(seed)
    win = re_.window("2026-09")
    series = ["FASTRON TECHNO", "ENDURO 4T", "MEDITRAN SC", "PRIMA XP", "MESRANIA 2T", "ENDURO MATIC", "FASTRON ECOGREEN",
              "RORED", "MEDITRAN S", "TURALIK", "FASTRON GOLD", "ENDURO RACING"]
    regions = ["REGION I", "REGION II", "REGION III", "REGION IV", "REGION V", "REGION VI", "REGION VII"]
    stypes = [("OTO-8", "Bengkel 2W kecil"), ("OTO-6", "Toko Oli Kecil"), ("OTO-10", "Bengkel 4W kecil"), ("OTO-5", "Toko Oli Besar"),
              ("OTO-7", "Bengkel 2W Besar"), ("OTO-9", "Bengkel 4W Besar"), ("OTO-13", "Bengkel 2W dan 4W")]
    outlets, ser = [], {}
    for i in range(n):
        reg = random.choice(regions)
        st = random.choices(stypes, weights=[30, 8, 8, 3, 5, 4, 4])[0]
        size = random.lognormvariate(-3.2, 1.3) * (8 if st[0] == "OTO-5" else 1)
        kind = random.random()
        row = {"cust": f"C{i:06d}", "cname": f"OUTLET {i}", "region": reg, "n_region": 1, "stype": st[0], "stype_name": st[1]}
        p_active = random.choice([0.95, 0.8, 0.5, 0.25, 0.1])
        start = 0 if kind > 0.12 else random.randint(12, 18)        # sebagian entrant 2026
        stop = len(win["months"]) if random.random() > 0.15 else random.randint(6, 18)
        for k, (y, m) in enumerate(win["months"]):
            v = 0.0
            if start <= k < stop and random.random() < p_active:
                v = round(size * random.uniform(0.5, 1.5), 4)
            row[re_.mcol(y, m)] = v
        bought = random.sample(series, random.randint(1, 4))
        prev = [s for s in bought if random.random() < 0.8] if start == 0 else []
        cur = [s for s in bought if random.random() < 0.8] if stop > 12 else []
        row["s_prev"] = "|".join(sorted(prev)) or None
        row["s_cur"] = "|".join(sorted(cur)) or None
        outlets.append(row)
        coh = any(row[re_.mcol(2025, m)] > 0 for m in range(1, 13))
        vp = sum(row[re_.mcol(2025, m)] for m in range(1, 10))
        vc = sum(row[re_.mcol(2026, m)] for m in range(1, 10))
        for s in bought:
            key = (s, reg, coh)
            a = ser.setdefault(key, [0.0, 0.0])
            a[0] += vp / len(bought) * (s in prev)
            a[1] += vc / len(bought) * (s in cur)
    series_rows = [{"series": k[0], "region": k[1], "in_cohort": k[2], "vol_prev": v[0], "vol_cur": v[1]} for k, v in ser.items()]
    audit = {"rows_total": 412345, "rows_bad_id": 17, "rows_excluded_series": 5321, "vol_excluded_series": 120.5,
             "rows_negative": 44, "rows_zero": 1200, "rows_null_volume": 0, "outlets_all_types": n + 900,
             "outlets_selected_types": n, "outlets_multi_region": 12, "vol_all_types": 99999.1, "vol_selected_types": 50000.2,
             "first_month": "2025-01-01", "last_month": "2026-09-01", "n_series": len(series),
             "regions_json": '[{"region":"REGION I","n":400}]', "store_types_json": '[{"stype":"OTO-8","n":2000}]'}
    return outlets, series_rows, audit
