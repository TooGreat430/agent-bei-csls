"""Data ilustrasi (fiktif) untuk contoh tampilan dashboard daya saing harga dan pengujian."""
import random

HEROES = ["PERTAMINA ENDURO MATIC-S 0.8 LITER", "PERTAMINA ENDURO 4T 1 LITER",
          "PERTAMINA FASTRON ECOGREEN 5W-30 3.5 LITER", "PERTAMINA FASTRON TECHNO 10W-40 4 LITER",
          "PERTAMINA MEDITRAN SC DIESEL 15W-40 5 LITER", "PERTAMINA MEDITRAN S 40 5 LITER"]
CATALOG = [  # (segment, viscosity, kimap, ptpl product, base price/L, competitors)
    ("MCO", "10W-30", "K1", "PERTAMINA ENDURO MATIC-S 0.8 LITER", 76000, ["AHM MPX2 0.8 LITER", "SHELL ADVANCE AX7 0.8 LITER"]),
    ("MCO", "20W-50", "K2", "PERTAMINA ENDURO 4T 1 LITER", 52000, ["AHM MPX1 1 LITER", "CASTROL GO 1 LITER"]),
    ("MCO", "10W-40", "K3", "PERTAMINA ENDURO 4T RACING 0.8 LITER", 88000, ["MOTUL 3000 0.8 LITER"]),
    ("PCO", "5W-30", "K4", "PERTAMINA FASTRON ECOGREEN 5W-30 3.5 LITER", 82000, ["SHELL HELIX HX7 3.5 LITER"]),
    ("PCO", "10W-40", "K5", "PERTAMINA FASTRON TECHNO 10W-40 4 LITER", 90000, ["SHELL HELIX HX5 4 LITER", "CASTROL MAGNATEC 4 LITER"]),
    ("PCO", "0W-20", "K6", "PERTAMINA FASTRON GOLD 0W-20 4 LITER", 154000, ["TOTAL QUARTZ 0W-20 4 LITER"]),
    ("COMMERCIAL", "15W-40", "K7", "PERTAMINA MEDITRAN SC DIESEL 15W-40 5 LITER", 61000, ["SHELL RIMULA R4 5 LITER"]),
    ("COMMERCIAL", "SAE 40", "K8", "PERTAMINA MEDITRAN S 40 5 LITER", 55000, ["SHELL RIMULA R2 5 LITER"]),
]
ZONES = ["Nasional", "Zona 1", "Zona 2", "Zona 3"]


def make(seed=7, months_a=("2026-07", "2026-08", "2026-09"), months_b=("2026-04", "2026-05", "2026-06")):
    rnd = random.Random(seed)
    agg, monthly = [], []
    for seg, visc, kimap, ptpl, base, comps in CATALOG:
        for z in ZONES:
            zf = {"Nasional": 1.0, "Zona 1": 1.02, "Zona 2": 0.99, "Zona 3": 1.04}[z]
            for period, months in (("A", months_a), ("B", months_b)):
                drift = 1.0 if period == "A" else 0.985
                p = base * zf * drift
                gap = rnd.choice([-0.12, -0.08, -0.05, 0.01, 0.03])
                k = p * (1 - gap)
                for side, product, price in (("PTPL", ptpl, p), ("KOMP", "", k)):
                    agg.append({"PERIOD": period, "ZONE": z, "SEGMENT": seg, "VISCOSITY": visc, "KIMAP": kimap,
                                "SIDE": side, "PRODUCT": product, "HET": price * 1.06, "HJ": price,
                                "HTO": price * 0.86, "HT": price * 0.85, "MARG": price * 0.13 * (1.05 if side == "PTPL" else 1),
                                "N": rnd.randint(8, 60)})
                for mi, mo in enumerate(months):
                    pm = p * (1 + 0.004 * mi)
                    monthly.append({"MONTH": mo, "ZONE": z, "SEGMENT": seg, "KIMAP": kimap, "SIDE": "PTPL",
                                    "PRODUCT": ptpl, "BRAND": "PERTAMINA", "HJ": pm, "HTO": pm * 0.86})
                    for ci, comp in enumerate(comps):
                        trend = -0.012 * mi if ci == 0 else 0.004 * mi
                        km = k * (1 + trend)
                        monthly.append({"MONTH": mo, "ZONE": z, "SEGMENT": seg, "KIMAP": kimap, "SIDE": "KOMP",
                                        "PRODUCT": comp, "BRAND": comp.split()[0], "HJ": km, "HTO": km * 0.86})
    return agg, monthly
