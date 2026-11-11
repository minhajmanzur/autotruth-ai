"""Generate the demo specification PDFs in data/specs/.

The vehicles are FICTIONAL. They exist so the demo and the benchmark have
ground truth that nobody can dispute, without passing off invented numbers as
a real manufacturer's. Drop real brochures into data/specs/ to use real cars.

    python scripts/make_demo_specs.py
"""
from __future__ import annotations

import json
from pathlib import Path

from reportlab.lib.colors import HexColor
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

OUT = Path(__file__).resolve().parents[1] / "data" / "specs"
S, O, N = "Standard", "Optional", "Not available"


def solara_dims(kerb: str) -> list[tuple[str, str]]:
    return [("Overall length", "4,920 mm"), ("Overall width", "1,840 mm"), ("Overall height", "1,445 mm"),
            ("Wheelbase", "2,825 mm"), ("Ground clearance", "145 mm"), ("Kerb weight", kerb),
            ("Cargo volume", "428 L"), ("Seating capacity", "5")]


DOCS = [
    {
        "id": "meridian-solara-2025-gcc",
        "meta": {"make": "Meridian", "model": "Solara", "year": 2025, "market": "GCC",
                 "title": "2025 Meridian Solara - Official Specifications (GCC)"},
        "doc_no": "MS-25-GCC-01", "issued": "January 2025",
        "trims": {
            "SE": [
                ("Engine & Performance", [
                    ("Engine type", "2.5 L 4-cylinder, naturally aspirated"),
                    ("Displacement", "2,487 cc"),
                    ("Maximum power", "203 hp (151 kW) @ 6,600 rpm"),
                    ("Maximum torque", "250 Nm (184 lb-ft) @ 5,000 rpm"),
                    ("0–100 km/h", "8.4 s"),
                    ("Top speed", "210 km/h"),
                ]),
                ("Transmission & Drivetrain", [
                    ("Transmission", "8-speed automatic"),
                    ("Drivetrain", "Front-wheel drive (FWD)"),
                    ("Powertrain type", "Petrol"),
                ]),
                ("Fuel Economy (NEDC)", [
                    ("Fuel consumption (combined)", "6.5 L/100 km (15.4 km/l)"),
                    ("Fuel consumption (city)", "8.3 L/100 km (12.0 km/l)"),
                    ("Fuel consumption (highway)", "5.4 L/100 km (18.5 km/l)"),
                    ("Fuel tank capacity", "60 L"),
                ]),
                ("Dimensions & Weights", solara_dims("1,530 kg")),
                ("Safety & Driver Assistance", [
                    ("Airbags", "7"), ("Adaptive cruise control", O), ("Blind spot monitor", O),
                    ("Lane keeping assist", S), ("360-degree camera", N),
                ]),
                ("Comfort & Technology", [
                    ("Panoramic sunroof", N), ("Wireless phone charger", O), ("Ventilated front seats", N),
                    ("Head-up display", N), ("Apple CarPlay", S),
                ]),
                ("Warranty", [("Vehicle warranty", "5 years / 150,000 km")]),
            ],
            "XLE Hybrid": [
                ("Engine & Performance", [
                    ("Engine type", "2.5 L 4-cylinder hybrid, naturally aspirated"),
                    ("Displacement", "2,487 cc"),
                    ("Engine power", "184 hp (137 kW) @ 6,000 rpm"),
                    ("Combined system power", "225 hp (168 kW)"),
                    ("Maximum torque", "221 Nm (163 lb-ft) @ 3,600–5,200 rpm"),
                    ("0–100 km/h", "7.8 s"),
                    ("Top speed", "180 km/h"),
                ]),
                ("Transmission & Drivetrain", [
                    ("Transmission", "e-CVT (electronically controlled continuously variable)"),
                    ("Drivetrain", "Front-wheel drive (FWD)"),
                    ("Powertrain type", "Hybrid (petrol-electric)"),
                ]),
                ("Fuel Economy (NEDC)", [
                    ("Fuel consumption (combined)", "4.2 L/100 km (23.8 km/l)"),
                    ("Fuel consumption (city)", "4.0 L/100 km (25.0 km/l)"),
                    ("Fuel consumption (highway)", "4.5 L/100 km (22.2 km/l)"),
                    ("Fuel tank capacity", "50 L"),
                ]),
                ("Dimensions & Weights", solara_dims("1,640 kg")),
                ("Safety & Driver Assistance", [
                    ("Airbags", "9"), ("Adaptive cruise control", S), ("Blind spot monitor", S),
                    ("Lane keeping assist", S), ("360-degree camera", S),
                ]),
                ("Comfort & Technology", [
                    ("Panoramic sunroof", S), ("Wireless phone charger", S), ("Ventilated front seats", O),
                    ("Head-up display", O), ("Apple CarPlay", S),
                ]),
                ("Warranty", [("Vehicle warranty", "5 years / 150,000 km"),
                              ("Hybrid battery warranty", "8 years / 160,000 km")]),
            ],
        },
    },
    {
        "id": "meridian-solara-2025-europe",
        "meta": {"make": "Meridian", "model": "Solara", "year": 2025, "market": "Europe",
                 "title": "2025 Meridian Solara - Technical Data (Europe)"},
        "doc_no": "MS-25-EU-03", "issued": "February 2025",
        "trims": {
            "Excel Hybrid": [
                ("Engine & Performance", [
                    ("Engine type", "2.5 L 4-cylinder hybrid, naturally aspirated"),
                    ("Displacement", "2,487 cc"),
                    ("Engine power", "178 PS (131 kW) @ 5,700 rpm"),
                    ("Combined system power", "218 PS (160 kW)"),
                    ("Maximum torque", "221 Nm (163 lb-ft) @ 3,600–5,200 rpm"),
                    ("0–100 km/h", "8.1 s"),
                    ("Top speed", "180 km/h"),
                ]),
                ("Transmission & Drivetrain", [
                    ("Transmission", "e-CVT (electronically controlled continuously variable)"),
                    ("Drivetrain", "Front-wheel drive (FWD)"),
                    ("Powertrain type", "Hybrid (petrol-electric)"),
                ]),
                ("Fuel Economy & Emissions (WLTP)", [
                    ("Fuel consumption (combined)", "4.8 L/100 km (20.8 km/l)"),
                    ("CO2 emissions (combined)", "108 g/km"),
                    ("Fuel tank capacity", "50 L"),
                ]),
                ("Dimensions & Weights", solara_dims("1,655 kg")),
                ("Safety & Driver Assistance", [
                    ("Airbags", "8"), ("Adaptive cruise control", S), ("Blind spot monitor", S),
                    ("Lane keeping assist", S), ("360-degree camera", O),
                ]),
                ("Comfort & Technology", [
                    ("Panoramic sunroof", O), ("Wireless phone charger", S), ("Ventilated front seats", N),
                    ("Head-up display", S), ("Apple CarPlay", S),
                ]),
                ("Warranty", [("Vehicle warranty", "3 years / 100,000 km"),
                              ("Hybrid battery warranty", "8 years / 160,000 km")]),
            ],
        },
    },
    {
        "id": "kestrel-ridgeback-2025-gcc",
        "meta": {"make": "Kestrel", "model": "Ridgeback", "year": 2025, "market": "GCC",
                 "title": "2025 Kestrel Ridgeback - Official Specifications (GCC)"},
        "doc_no": "KR-25-GCC-02", "issued": "March 2025",
        "trims": {
            "Adventure": [
                ("Engine & Performance", [
                    ("Engine type", "2.0 L 4-cylinder, turbocharged"),
                    ("Displacement", "1,998 cc"),
                    ("Maximum power", "245 hp (183 kW) @ 5,500 rpm"),
                    ("Maximum torque", "370 Nm (273 lb-ft) @ 1,800–4,000 rpm"),
                    ("0–100 km/h", "7.6 s"),
                    ("Top speed", "205 km/h"),
                ]),
                ("Transmission & Drivetrain", [
                    ("Transmission", "8-speed automatic"),
                    ("Drivetrain", "All-wheel drive (AWD)"),
                    ("Powertrain type", "Petrol"),
                ]),
                ("Fuel Economy (NEDC)", [
                    ("Fuel consumption (combined)", "9.1 L/100 km (11.0 km/l)"),
                    ("Fuel consumption (city)", "11.4 L/100 km (8.8 km/l)"),
                    ("Fuel consumption (highway)", "7.6 L/100 km (13.2 km/l)"),
                    ("Fuel tank capacity", "72 L"),
                ]),
                ("Dimensions & Weights", [
                    ("Overall length", "4,890 mm"), ("Overall width", "1,930 mm"), ("Overall height", "1,790 mm"),
                    ("Wheelbase", "2,850 mm"), ("Ground clearance", "215 mm"), ("Kerb weight", "1,985 kg"),
                    ("Cargo volume", "583 L"), ("Seating capacity", "5"), ("Towing capacity (braked)", "2,000 kg"),
                ]),
                ("Safety & Driver Assistance", [
                    ("Airbags", "7"), ("Adaptive cruise control", S), ("Blind spot monitor", S),
                    ("360-degree camera", O), ("Hill descent control", S), ("Locking rear differential", N),
                ]),
                ("Comfort & Technology", [
                    ("Panoramic sunroof", O), ("Third-row seats", N), ("Ventilated front seats", N),
                    ("Wireless phone charger", S),
                ]),
                ("Warranty", [("Vehicle warranty", "5 years / 100,000 km")]),
            ],
            "Summit": [
                ("Engine & Performance", [
                    ("Engine type", "3.5 L V6, naturally aspirated"),
                    ("Displacement", "3,456 cc"),
                    ("Maximum power", "295 hp (220 kW) @ 6,600 rpm"),
                    ("Maximum torque", "356 Nm (263 lb-ft) @ 4,700 rpm"),
                    ("0–100 km/h", "7.2 s"),
                    ("Top speed", "210 km/h"),
                ]),
                ("Transmission & Drivetrain", [
                    ("Transmission", "10-speed automatic"),
                    ("Drivetrain", "Four-wheel drive (4WD) with low range"),
                    ("Powertrain type", "Petrol"),
                ]),
                ("Fuel Economy (NEDC)", [
                    ("Fuel consumption (combined)", "10.4 L/100 km (9.6 km/l)"),
                    ("Fuel consumption (city)", "13.2 L/100 km (7.6 km/l)"),
                    ("Fuel consumption (highway)", "8.5 L/100 km (11.8 km/l)"),
                    ("Fuel tank capacity", "80 L"),
                ]),
                ("Dimensions & Weights", [
                    ("Overall length", "4,890 mm"), ("Overall width", "1,930 mm"), ("Overall height", "1,810 mm"),
                    ("Wheelbase", "2,850 mm"), ("Ground clearance", "235 mm"), ("Kerb weight", "2,130 kg"),
                    ("Cargo volume", "583 L"), ("Seating capacity", "7"), ("Towing capacity (braked)", "3,500 kg"),
                ]),
                ("Safety & Driver Assistance", [
                    ("Airbags", "9"), ("Adaptive cruise control", S), ("Blind spot monitor", S),
                    ("360-degree camera", S), ("Hill descent control", S), ("Locking rear differential", S),
                ]),
                ("Comfort & Technology", [
                    ("Panoramic sunroof", S), ("Third-row seats", S), ("Ventilated front seats", S),
                    ("Wireless phone charger", S),
                ]),
                ("Warranty", [("Vehicle warranty", "5 years / 100,000 km")]),
            ],
        },
    },
    {
        "id": "voltaire-e-line-2024-europe",
        "meta": {"make": "Voltaire", "model": "E-Line", "year": 2024, "market": "Europe",
                 "title": "2024 Voltaire E-Line - Technical Data (Europe)"},
        "doc_no": "VE-24-EU-05", "issued": "September 2024",
        "trims": {
            "Standard Range": [
                ("Motor & Performance", [
                    ("Motor type", "Permanent-magnet synchronous, single rear motor"),
                    ("Maximum power", "150 kW (201 hp)"),
                    ("Maximum torque", "310 Nm (229 lb-ft)"),
                    ("0–100 km/h", "7.3 s"),
                    ("Top speed", "160 km/h"),
                ]),
                ("Transmission & Drivetrain", [
                    ("Transmission", "Single-speed reduction gear"),
                    ("Drivetrain", "Rear-wheel drive (RWD)"),
                    ("Powertrain type", "Battery electric"),
                ]),
                ("Battery, Range & Charging (WLTP)", [
                    ("Battery capacity (usable)", "58 kWh"),
                    ("Range (WLTP combined)", "435 km (270 mi)"),
                    ("Energy consumption (WLTP)", "15.2 kWh/100 km"),
                    ("DC fast charging power", "120 kW"),
                    ("AC charging power", "11 kW"),
                ]),
                ("Dimensions & Weights", [
                    ("Overall length", "4,580 mm"), ("Overall width", "1,860 mm"), ("Overall height", "1,570 mm"),
                    ("Wheelbase", "2,770 mm"), ("Ground clearance", "155 mm"), ("Kerb weight", "1,790 kg"),
                    ("Cargo volume", "440 L"), ("Seating capacity", "5"),
                ]),
                ("Safety & Driver Assistance", [
                    ("Airbags", "7"), ("Adaptive cruise control", S), ("360-degree camera", O),
                ]),
                ("Comfort & Technology", [
                    ("Heat pump", O), ("Panoramic glass roof", N), ("Vehicle-to-load", N), ("Head-up display", N),
                ]),
                ("Warranty", [("Vehicle warranty", "4 years / 100,000 km"),
                              ("Battery warranty", "8 years / 160,000 km")]),
            ],
            "Long Range": [
                ("Motor & Performance", [
                    ("Motor type", "Permanent-magnet synchronous, single rear motor"),
                    ("Maximum power", "210 kW (282 hp)"),
                    ("Maximum torque", "350 Nm (258 lb-ft)"),
                    ("0–100 km/h", "6.1 s"),
                    ("Top speed", "180 km/h"),
                ]),
                ("Transmission & Drivetrain", [
                    ("Transmission", "Single-speed reduction gear"),
                    ("Drivetrain", "Rear-wheel drive (RWD)"),
                    ("Powertrain type", "Battery electric"),
                ]),
                ("Battery, Range & Charging (WLTP)", [
                    ("Battery capacity (usable)", "77 kWh"),
                    ("Range (WLTP combined)", "560 km (348 mi)"),
                    ("Energy consumption (WLTP)", "15.6 kWh/100 km"),
                    ("DC fast charging power", "170 kW"),
                    ("AC charging power", "11 kW"),
                ]),
                ("Dimensions & Weights", [
                    ("Overall length", "4,580 mm"), ("Overall width", "1,860 mm"), ("Overall height", "1,570 mm"),
                    ("Wheelbase", "2,770 mm"), ("Ground clearance", "155 mm"), ("Kerb weight", "1,960 kg"),
                    ("Cargo volume", "440 L"), ("Seating capacity", "5"),
                ]),
                ("Safety & Driver Assistance", [
                    ("Airbags", "7"), ("Adaptive cruise control", S), ("360-degree camera", S),
                ]),
                ("Comfort & Technology", [
                    ("Heat pump", S), ("Panoramic glass roof", S), ("Vehicle-to-load", S), ("Head-up display", O),
                ]),
                ("Warranty", [("Vehicle warranty", "4 years / 100,000 km"),
                              ("Battery warranty", "8 years / 160,000 km")]),
            ],
        },
    },
]

INK, MUTED, RULE = HexColor("#111827"), HexColor("#6b7280"), HexColor("#d1d5db")
LEFT, VALUE_X, RIGHT = 56, 300, A4[0] - 56
TOP, BOTTOM = A4[1] - 64, 72


def build(doc: dict) -> Path:
    path = OUT / f"{doc['id']}.pdf"
    c = canvas.Canvas(str(path), pagesize=A4)
    meta = doc["meta"]
    name = f"{meta['year']} {meta['make']} {meta['model']}"
    page = 0

    def footer() -> None:
        c.setFont("Helvetica", 8)
        c.setFillColor(MUTED)
        c.drawString(LEFT, 40, f"Page {page} · {doc['doc_no']} · {name} · Fictional vehicle, AutoTruth AI demo data")
        c.setFillColor(INK)

    def new_page() -> float:
        nonlocal page
        if page:
            footer()
            c.showPage()
        page += 1
        return TOP

    y = new_page()
    c.setFont("Helvetica-Bold", 26)
    c.drawString(LEFT, y - 120, name)
    c.setFont("Helvetica-Bold", 13)
    c.drawString(LEFT, y - 150, f"Official Specifications - {meta['market']} Market")
    c.setFont("Helvetica", 10)
    for i, line in enumerate([
        f"Document number: {doc['doc_no']}",
        f"Issued: {doc['issued']}",
        "Grades covered: " + ", ".join(doc["trims"]),
        "This is a fictional vehicle created as demonstration data for AutoTruth AI.",
    ]):
        c.drawString(LEFT, y - 180 - i * 16, line)

    for trim, sections in doc["trims"].items():
        y = new_page()
        c.setFont("Helvetica-Bold", 18)
        c.drawString(LEFT, y, f"Trim: {trim}")
        y -= 14
        for heading, rows in sections:
            if y - 30 - 16 * min(len(rows), 3) < BOTTOM:
                y = new_page()
            y -= 24
            c.setFont("Helvetica-Bold", 13)
            c.drawString(LEFT, y, heading)
            y -= 6
            c.setStrokeColor(RULE)
            c.line(LEFT, y, RIGHT, y)
            for label, value in rows:
                if y - 16 < BOTTOM:
                    y = new_page()
                y -= 16
                c.setFont("Helvetica", 10)
                c.drawString(LEFT, y, label)
                c.drawString(VALUE_X, y, value)
    footer()
    c.save()
    path.with_suffix(".meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for d in DOCS:
        print("wrote", build(d).name)
