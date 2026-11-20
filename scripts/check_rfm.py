"""Cek data & uji coba analisis RFM outlet sell-out (jalankan di Cloud Shell, folder repo, .venv aktif).

1) Cek data saja (cepat, ±1 menit):      python scripts/check_rfm.py
2) Cek + buat laporan lokal satu region:  python scripts/check_rfm.py --report SR7
3) Cek + laporan nasional:                python scripts/check_rfm.py --report nasional
   Opsi: --cutoff 2026-09 · --refresh (abaikan cache bucket)

Laporan uji disimpan di folder lokal ./rfm_uji/ (TIDAK diunggah ke bucket, TIDAK memakai Claude — narasi memakai
versi aturan agar cepat & gratis; angka sama persis dengan versi agent).
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from library_agent import rfm_engine as eng  # noqa: E402
from library_agent.clients import bigquery_client  # noqa: E402


def q(sql, params=None):
    from google.cloud import bigquery

    job = bigquery_client().query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params or []))
    return [dict(r) for r in job.result()]


def section(title):
    print(f"\n=== {title} " + "=" * max(0, 70 - len(title)))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cutoff", default="")
    ap.add_argument("--report", default="", help="SR1..SR7 atau 'nasional'")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()

    cfg = eng.config()
    if a.cutoff:
        eng.parse_cutoff(a.cutoff)
        cfg["cutoff"] = a.cutoff
    win = eng.window(cfg["cutoff"])
    t = eng._table(cfg["table"])
    series = eng._ident(cfg["series_column"])
    print(f"Tabel: {t}\nCut-off: {cfg['cutoff']} → baseline {win['label_base']}, YTD {win['label_ytd']}")
    print(f"Tipe outlet: {', '.join(cfg['store_types'])}\nKolom seri: {series} · dikecualikan: {cfg['exclude_pattern']}")

    from google.cloud import bigquery
    p = [bigquery.ScalarQueryParameter("start", "DATE", win["start"]),
         bigquery.ScalarQueryParameter("end", "DATE", win["end"])]

    section("1. Kolom tanggal DT_PR (harus = tanggal transaksi)")
    rows = q(f"""SELECT FORMAT_DATE('%Y-%m', DT_PR) AS bulan, COUNT(*) AS baris, COUNT(DISTINCT DT_PR) AS hari,
                 COUNT(DISTINCT CUSTOMER_CODE) AS outlet, ROUND(SUM(TOTAL_VOL_KL_DELIVERED), 2) AS kl_delivered,
                 ROUND(SUM(TOTAL_VOL_KL_APPROVED), 2) AS kl_approved
                 FROM `{t}` WHERE DT_PR BETWEEN @start AND @end GROUP BY 1 ORDER BY 1""", p)
    for r in rows:
        print(f"  {r['bulan']}: {r['baris']:>10,} baris · {r['hari']:>2} hari · {r['outlet']:>7,} outlet · "
              f"delivered {r['kl_delivered']:>12,} KL · approved {r['kl_approved']:>12,} KL")
    missing = {f"{y}-{m:02d}" for y, m in win["months"]} - {r["bulan"] for r in rows}
    print("  ⚠ Bulan tanpa data: " + ", ".join(sorted(missing)) if missing else "  ✓ Semua bulan periode ada datanya")
    print("  → Jika 'hari' per bulan hanya 1 (mis. tanggal proses), DT_PR BUKAN tanggal transaksi: beri tahu developer.")

    section("2. REGION_NAME → kode region laporan")
    for r in q(f"SELECT REGION_NAME AS r, COUNT(DISTINCT CUSTOMER_CODE) AS n FROM `{t}` "
               "WHERE DT_PR BETWEEN @start AND @end GROUP BY 1 ORDER BY 1", p):
        print(f"  {str(r['r']):<30} → {eng.region_key(r['r']):<6} ({r['n']:,} outlet)")

    section("3. Tipe outlet (STORETYPE)")
    for r in q(f"SELECT STORETYPE_CODE AS c, ANY_VALUE(STORETYPE_NAME) AS nm, COUNT(DISTINCT CUSTOMER_CODE) AS n "
               f"FROM `{t}` WHERE DT_PR BETWEEN @start AND @end GROUP BY 1 ORDER BY n DESC LIMIT 30", p):
        mark = "✓ dipakai" if str(r["c"] or "").strip().upper() in cfg["store_types"] else "  -"
        print(f"  {mark}  {str(r['c']):<10} {str(r['nm'])[:40]:<40} {r['n']:>8,} outlet")

    section(f"4. Seri produk ({series}) & pengecualian")
    for r in q(f"""SELECT {series} AS s, COUNT(*) AS baris, ROUND(SUM(TOTAL_VOL_KL_DELIVERED), 2) AS kl,
                   COUNTIF(REGEXP_CONTAINS(UPPER(CONCAT(IFNULL({series}, ''), ' ', IFNULL(PRODUCT_NAME, ''))), @ex)) AS kena
                   FROM `{t}` WHERE DT_PR BETWEEN @start AND @end GROUP BY 1 ORDER BY kl DESC LIMIT 40""",
               p + [bigquery.ScalarQueryParameter("ex", "STRING", cfg["exclude_pattern"].upper())]):
        print(f"  {str(r['s'])[:38]:<38} {r['kl']:>12,} KL  {r['baris']:>9,} baris" +
              (f"  ← {r['kena']:,} baris dikecualikan" if r["kena"] else ""))

    section("5. Status order & ID outlet")
    for r in q(f"SELECT SALES_ORDER_STATUS AS s, COUNT(*) AS n, ROUND(SUM(TOTAL_VOL_KL_DELIVERED), 2) AS kl "
               f"FROM `{t}` WHERE DT_PR BETWEEN @start AND @end GROUP BY 1 ORDER BY n DESC", p):
        print(f"  status {str(r['s']):<25} {r['n']:>10,} baris · {r['kl']:>12,} KL delivered")
    print("  → Laporan memakai TOTAL_VOL_KL_DELIVERED semua status (volume 0/negatif tetap dihitung sebagai bersih).")

    section("6. Tarik data RFM (sama seperti agent) & hitung")
    t0 = time.time()
    data = eng.fetch(cfg, refresh=a.refresh)
    print(f"  Data: {len(data['outlets']):,} outlet, {len(data['series']):,} baris seri · {time.time() - t0:.1f} dtk "
          f"(diambil {data.get('fetched_at') or '-'})")
    au = data["audit"]
    print(f"  Audit: {au.get('rows_total', 0):,} baris · ID kosong {au.get('rows_bad_id', 0):,} · baris dikecualikan "
          f"{au.get('rows_excluded_series', 0):,} · outlet multi-region {au.get('outlets_multi_region', 0):,}")
    t0 = time.time()
    res = eng.compute(data["outlets"], data["series"], data["audit"], cfg["cutoff"])
    k = res["kpi"]
    print(f"  Nasional: {k['outlets_valid']:,} outlet valid · baseline {k['outlets_baseline']:,} · entrant "
          f"{k['outlets_entrants']:,} · YTD {k['vol_ytd']:,.2f} KL · YoY {k['yoy_total_pct']}% · cohort YoY "
          f"{k['yoy_cohort_pct']}% · hitung {time.time() - t0:.1f} dtk")
    print(f"  Pemeriksaan: {res['checks']}")
    for s in res["segments"]:
        print(f"    {s['segment']:<24} {s['outlets']:>7,} outlet · {s['vol_share'] or 0:>5.1f}% volume")

    if a.report:
        from library_agent import rfm_report as rep

        scope = "" if a.report.lower() in ("nasional", "national", "") else a.report
        t0 = time.time()
        r = res if not scope else eng.compute(data["outlets"], data["series"], data["audit"], cfg["cutoff"], scope=scope)
        os.makedirs("rfm_uji", exist_ok=True)
        html_doc = rep.render_html(r, rep.fallback_narrative(r), source=f"Selling Out Intelligence — {t}",
                                   fetched_at=data.get("fetched_at", ""))
        name = f"rfm_uji/RFM_{r['scope']}_{cfg['cutoff']}"
        with open(name + ".html", "w", encoding="utf-8") as f:
            f.write(html_doc)
        with open(name + ".xlsx", "wb") as f:
            f.write(eng.register_excel(r))
        print(f"\n  ✓ Laporan uji: {name}.html dan {name}.xlsx ({time.time() - t0:.1f} dtk). Buka lewat Cloud Shell "
              "Editor (klik kanan → Download) untuk dicek tampilannya.")


if __name__ == "__main__":
    main()
