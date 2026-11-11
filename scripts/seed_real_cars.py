"""Post real-car checks to a running AutoTruth AI server (default http://localhost:8010).

The texts below are TEST CLAIMS written for this project, some deliberately wrong, to exercise
the real manufacturer sheets in data/specs/. They are not published reviews. Any URLs given on the
command line are real published reviews, fetched live by the backend.

    python scripts/seed_real_cars.py [base_url] [review_url ...]
"""
import sys

import httpx

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8010"
P = "\n\n"  # paragraph break

TEXTS = [
    ("Test claims: Toyota Corolla (UK sheet, Jan 2026)", P.join([
        "The Toyota Corolla 2.0 Hybrid makes 176 bhp and does 0-62mph in 7.4 seconds. Top speed is 112 mph. "
        "The 1.8 Hybrid has 138 bhp and a 1.8-litre four-cylinder engine.",
        "Toyota quotes 64.2 mpg combined for the Corolla. The fuel tank holds 50 litres.",
        "The Touring Sports is 4,650 mm long with a 596-litre boot.",
        "The Corolla uses a CVT and weighs 1,400 kg. Some sites say the Corolla makes 200 bhp.",
        "The ride feels composed on UK roads.",
    ])),
    ("Test claims: Toyota Camry Hybrid (UK sheet, 2021)", P.join([
        "The 2021 Toyota Camry hybrid has 215 bhp, which is 160 kW, and hits 62mph in 8.3 seconds. "
        "In metric horsepower the Camry makes 218 hp. Top speed is 130 mph.",
        "It returns 52 mpg combined and has a 524-litre boot. The Camry has a 60-litre fuel tank.",
        "It is 4,885 mm long, front-wheel drive, and weighs about 1,600 kg. The 2.5-litre engine makes 221 Nm of torque.",
        "The cabin is quiet and the seats are comfortable.",
    ])),
    ("Test claims: Hyundai Elantra (Australian sheet)", P.join([
        "The Hyundai Elantra 2.0 MPi makes 112 kW and 192 Nm. The 1.6 T-GDi produces 150 kW and comes with a "
        "seven-speed dual-clutch transmission.",
        "The Elantra uses 7.0 L/100km combined. It is 4,620 mm long with a 458-litre boot, and the Elantra has a 60-litre fuel tank.",
        "The Sport Premium has smart cruise control. Paddle shifters are standard on the Sport Premium.",
        "Blind-spot collision warning is standard on the Elantra. Cruise control is standard on the Elantra.",
        "Some reviews claim the Elantra Sport makes 200 kW.",
        "The steering feels sharp and the ride is firm.",
    ])),
    ("Test claims: BMW 3 Series (Canadian 2020 product guide)", P.join([
        "The 2020 BMW 330i xDrive makes 255 hp and 400 Nm of torque from its 2.0-litre engine. It does 0-100 km/h in 5.6 seconds.",
        "The 330i xDrive weighs 1,711 kg and is 4,717 mm long. It has a 59-litre fuel tank. The 330i has a top speed of 250 km/h.",
        "The M340i xDrive produces 382 hp. The M340i xDrive hits 100 km/h in 3.9 seconds.",
        "Some sites claim the BMW 330i makes 300 hp.",
        "The steering is sharp and the chassis feels beautifully balanced.",
    ])),
    ("Test claims: Mercedes-Benz C 300 (US 2019 sheet)", P.join([
        "The 2019 Mercedes-Benz C 300 makes 255 hp and 273 lb-ft of torque. It uses a nine-speed automatic.",
        "EPA combined fuel economy is 27 mpg for the C 300. The C 300 has a 17.4-gallon fuel tank and 12.6 cubic feet of cargo space.",
        "The C 300 is 184.5 inches long. Top speed is 155 mph. The C 300 is available with all-wheel drive.",
        "One review says the C 300 makes 241 hp.",
        "The cabin feels properly luxurious.",
    ])),
    ("Test claims: Nissan Altima (US 2024 sheet)", P.join([
        "The 2024 Nissan Altima makes 188 horsepower. With all-wheel drive the Altima makes 182 hp.",
        "The Altima returns 32 mpg combined and uses a CVT. The fuel tank holds 16.2 gallons.",
        "The Altima is 192.9 inches long with 15.4 cubic feet of cargo space. The Altima is available with all-wheel drive.",
        "Some listings say the Altima makes 200 horsepower. The Altima seats five.",
        "The seats are comfortable on long drives.",
    ])),
]
URLS = sys.argv[2:]

with httpx.Client(base_url=BASE, timeout=120) as client:
    for title, text in TEXTS:
        a = client.post("/api/analyze", json={"text": text, "title": title, "author": "AutoTruth test claims", "use_llm": False}).json()
        print(f"{a['id']}  {title}\n    {a['vehicle']}  {a['counts']}")
        for v in a["verdicts"]:
            if v["status"] != "supported":
                print(f"      {v['status']:13} {v['claim']['text']:38} | {v['reason'][:120]}")
    for url in URLS:
        r = client.post("/api/analyze", json={"url": url, "use_llm": False})
        if r.status_code != 200:
            print(f"FAILED {url}: {r.status_code} {r.json().get('detail')}")
            continue
        a = r.json()
        print(f"{a['id']}  {a['source']['title'][:70]}\n    {a['vehicle']}  {a['counts']}  ({a['text_chars']} chars)")
