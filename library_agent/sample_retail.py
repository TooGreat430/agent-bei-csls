"""Data ilustrasi survei harga retail (bukan data asli), selaras dengan KIMAP di sample_planogram.

Dipakai untuk contoh tampilan laporan Competitive Battlefield dan uji unit.
"""
from __future__ import annotations

import random

import pandas as pd

from .sample_planogram import KIMAPS

# Harga jual per kemasan (Rp) PTPL; kompetitor = PTPL × faktor
BASE_PRICE = {"A070113233": 52000, "A070207513": 50000, "A070114513": 55000, "A070114618": 60000,
              "A080220311": 330000, "A080220412": 290000, "A090330115": 420000, "A070119901": 40000}
COMP_FACTOR = {"AHM": 1.08, "YAMALUBE": 1.03, "FEDERAL": 0.97, "SHELL": 1.12, "CASTROL": 1.10, "MOTUL": 1.25}
PTPL_FACTOR = {"A070114513": 1.12, "A090330115": 1.15}          # PTPL lebih mahal (contoh Gap Harga / Double Jeopardy)
PTPL_MARGIN = {"A070113233": 0.17, "A070207513": 0.17, "A070114618": 0.10, "A080220311": 0.16,
               "A080220412": 0.16, "A070119901": 0.18}             # margin outlet PTPL (porsi harga jual)


def rows(seed: int = 11, per_region: int = 14) -> pd.DataFrame:
    rnd = random.Random(seed)
    out = []
    for sr in range(1, 8):
        for q, date in (("Q2", "2026-05-31"), ("Q3", "2026-08-31")):
            for kimap, seg, usage, visc, vol, brands in KIMAPS:
                if kimap not in BASE_PRICE:
                    continue
                for brand, series in brands.items():
                    for i in range(per_region):
                        base = BASE_PRICE[kimap] * (PTPL_FACTOR.get(kimap, 1.0) if brand == "PERTAMINA"
                                                    else COMP_FACTOR.get(brand, 1.0))
                        if brand == "PERTAMINA" and kimap == "A080220412" and q == "Q3":
                            base *= 1.12          # contoh: keunggulan harga berubah menjadi kerugian
                        hj = round(base * rnd.uniform(0.96, 1.04), -2)
                        rate = PTPL_MARGIN.get(kimap, 0.13) if brand == "PERTAMINA" else 0.14
                        marg = round(hj * rate, -2)
                        hto = round(hj - marg, -2)
                        qnr = f"{brand} {series} {visc} {vol:g} LITER"
                        out.append({"SURVEY_DATE": date, "SALES_REGION_CUSTOMER": sr, "OUTLET_ID": f"R{sr}{i:04d}",
                                    "QNR": qnr, "SEGMENT": seg, "HARGA_TEBUS": hto, "HARGA_JUAL": hj, "HTO": hto,
                                    "HET": round(hj * 1.05, -2), "USED_FOR": usage.title(), "VISCOSITY": visc,
                                    "BRAND": brand, "CONTENT": vol, "KIMAP": kimap, "OUTLIER_HTO": "DATA USE",
                                    "OUTLIER_HET": "DATA USE", "MARGIN_SURVEY": marg, "AVAILABILITY": "1",
                                    "TRADE_PROMO": 0, "LOYALTY": 0, "DT_PR": date})
    return pd.DataFrame(out)
