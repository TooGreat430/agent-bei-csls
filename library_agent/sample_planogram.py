"""Data ilustrasi planogram (bukan data asli) untuk contoh tampilan dan uji unit.

Skema mengikuti VM_PLANOGRAM. Termasuk baris berulang dan baris tanpa PAIR_KIMAP seperti data asli.
"""
from __future__ import annotations

import random

import pandas as pd

REGIONS = ["REGION I", "REGION II", "REGION III", "REGION IV", "REGION V", "REGION VI", "REGION VII"]
# (kimap, segment, usage, viscosity, volume, {brand: series})
KIMAPS = [
    ("A070113233", "MCO", "AUTOMATIC", "10W-30", 0.8, {"PERTAMINA": "ENDURO MATIC", "AHM": "SPX 2", "YAMALUBE": "MATIC",
                                                         "FEDERAL": "MATIC 30", "SHELL": "ADVANCE AX5 MATIC"}),
    ("A070207513", "MCO", "AUTOMATIC", "20W-40", 0.8, {"PERTAMINA": "ENDURO MATIC-G", "YAMALUBE": "MATIC", "AHM": "MPX 2"}),
    ("A070114513", "MCO", "MANUAL", "20W-40", 1.0, {"PERTAMINA": "ENDURO 4T", "AHM": "MPX 1", "CASTROL": "GO 4T",
                                                     "FEDERAL": "SUPREME XX"}),
    ("A070114618", "MCO", "MANUAL", "10W-40", 0.8, {"PERTAMINA": "ENDURO 4T RACING", "MOTUL": "5100", "SHELL": "ADVANCE AX7"}),
    ("A080220311", "PCO", "GASOLINE", "5W-30", 3.5, {"PERTAMINA": "FASTRON ECOGREEN", "SHELL": "HELIX HX7", "CASTROL": "MAGNATEC"}),
    ("A080220412", "PCO", "GASOLINE", "10W-40", 4.0, {"PERTAMINA": "FASTRON TECHNO", "SHELL": "HELIX HX5", "CASTROL": "GTX"}),
    ("A090330115", "COMMERCIAL", "DIESEL", "15W-40", 5.0, {"PERTAMINA": "MEDITRAN SC", "SHELL": "RIMULA R4", "CASTROL": "CRB TURBOMAX"}),
    ("A070119901", "MCO", "MANUAL", "20", 1.0, {"PERTAMINA": "MESRANIA 2T SUPER"}),
    ("A070119901", "MCO", "MANUAL", "NO VISCOSITY", 1.0, {"AHM": "2T", "FEDERAL": "2T SUPER"}),
]
PTPL_RATE = {"Q2": 0.50, "Q3": 0.54}
KIMAP_SHIFT = [0.05, -0.25, 0.10, -0.30, 0.0, -0.10, -0.20, 0.15, 0.0]
BRAND_SHIFT = {"AHM": 0.18, "YAMALUBE": 0.12, "SHELL": 0.05, "CASTROL": 0.02, "FEDERAL": 0.08, "MOTUL": -0.05}
AV_PENALTY = {"A070207513": 1, "A090330115": 1}


def rows(seed: int = 7, outlets_per_region: int = 45) -> pd.DataFrame:
    rnd = random.Random(seed)
    out = []
    for ri, reg in enumerate(REGIONS):
        for o in range(outlets_per_region):
            oid = f"{ri + 1}{o:05d}"
            for q, date in (("Q2", "2026-05-20"), ("Q3", "2026-08-18")):
                for ki, (kimap, seg, usage, visc, vol, brands) in enumerate(KIMAPS):
                    for brand, series in brands.items():
                        base = (PTPL_RATE[q] + KIMAP_SHIFT[ki]) - 0.06 * (ri % 3) if brand == "PERTAMINA" else 0.42 + BRAND_SHIFT.get(brand, 0)
                        if rnd.random() > base:
                            continue
                        a = rnd.choice([1, 2, 2, 3, 3, 4]) + (1 if brand == "PERTAMINA" and q == "Q3" and ri < 3 else 0) \
                            - (AV_PENALTY.get(kimap, 0) if brand == "PERTAMINA" else 0)
                        v = rnd.choice([1, 1, 2, 3])
                        rec = {"OUTLET_ID": oid, "SURVEY_DATE": date, "SUBCHANNEL": "Bengkel 2W Besar", "REGION": reg,
                               "PAIR_KIMAP": kimap if rnd.random() > 0.08 else None, "BRAND": brand, "SERIES": series,
                               "VISCOSITY": visc, "VOLUME": vol, "SEGMENT": seg, "USAGE": usage,
                               "AVAILABILITY_SCORE": float(min(max(a, 1), 5)), "VISIBILITY_SCORE": float(v),
                               "AV_SCORE": (min(max(a, 1), 5) + v) / 2, "DT_PR": date}
                        out.append(rec)
                        if rnd.random() < 0.15:   # baris berulang seperti data asli
                            out.append(dict(rec))
    return pd.DataFrame(out)
