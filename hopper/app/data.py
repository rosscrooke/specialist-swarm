"""Static San Francisco fixtures for the Hopper prototype.

Everything here is approximate and offline on purpose: coordinates and
elevations are rounded, transit is a simplified subset of real lines, fares are
2026-ish public prices, and ride-hail pricing is a SIMULATED model (no real
Uber/Lyft API). Swap these for GTFS / OSM / live feeds later without touching
the agents — they only see the tool functions in tools.py.
"""

# key: (display name, lat, lon, elevation_ft)
PLACES = {
    "ferry_building":   ("Ferry Building", 37.7955, -122.3937, 10),
    "embarcadero":      ("Embarcadero BART/Muni", 37.7929, -122.3970, 10),
    "salesforce_tower": ("Salesforce Tower", 37.7897, -122.3972, 20),
    "montgomery":       ("Montgomery St Station", 37.7894, -122.4013, 20),
    "moscone":          ("Moscone Center", 37.7842, -122.4016, 30),
    "union_square":     ("Union Square", 37.7880, -122.4075, 70),
    "powell":           ("Powell St Station", 37.7844, -122.4079, 50),
    "chinatown":        ("Chinatown (Dragon Gate)", 37.7906, -122.4058, 90),
    "nob_hill":         ("Nob Hill (Grace Cathedral)", 37.7919, -122.4134, 335),
    "washington_sq":    ("North Beach (Washington Sq)", 37.8008, -122.4100, 60),
    "coit_tower":       ("Coit Tower", 37.8024, -122.4058, 275),
    "pier_39":          ("Pier 39", 37.8087, -122.4098, 10),
    "fishermans_wharf": ("Fisherman's Wharf", 37.8080, -122.4177, 10),
    "lombard_st":       ("Lombard St (crooked block)", 37.8021, -122.4187, 280),
    "ghirardelli":      ("Ghirardelli Square", 37.8059, -122.4229, 20),
    "marina_green":     ("Marina Green", 37.8063, -122.4400, 10),
    "palace_fine_arts": ("Palace of Fine Arts", 37.8029, -122.4484, 20),
    "presidio":         ("Presidio Main Post", 37.8003, -122.4560, 100),
    "japantown":        ("Japantown", 37.7854, -122.4294, 150),
    "civic_center":     ("Civic Center", 37.7793, -122.4176, 60),
    "van_ness":         ("Van Ness Station", 37.7752, -122.4192, 50),
    "hayes_valley":     ("Hayes Valley", 37.7765, -122.4243, 80),
    "painted_ladies":   ("Painted Ladies (Alamo Sq)", 37.7762, -122.4328, 220),
    "church_duboce":    ("Church & Duboce", 37.7693, -122.4291, 80),
    "castro":           ("Castro", 37.7609, -122.4350, 160),
    "dolores_park":     ("Mission Dolores Park", 37.7596, -122.4269, 150),
    "mission_16th":     ("16th St Mission BART", 37.7650, -122.4197, 60),
    "mission_24th":     ("24th St Mission BART", 37.7524, -122.4184, 70),
    "haight_ashbury":   ("Haight-Ashbury", 37.7699, -122.4469, 250),
    "cole_carl":        ("Cole & Carl (N Judah)", 37.7656, -122.4498, 250),
    "ninth_judah":      ("9th Ave & Judah", 37.7622, -122.4663, 230),
    "golden_gate_park": ("Golden Gate Park (de Young)", 37.7715, -122.4687, 200),
    "ocean_beach":      ("Ocean Beach (Judah)", 37.7605, -122.5093, 40),
    "twin_peaks":       ("Twin Peaks", 37.7544, -122.4477, 910),
    "glen_park":        ("Glen Park BART", 37.7330, -122.4338, 270),
    "balboa_park":      ("Balboa Park BART", 37.7215, -122.4475, 270),
    "caltrain":         ("Caltrain 4th & King", 37.7766, -122.3947, 10),
    "oracle_park":      ("Oracle Park", 37.7786, -122.3893, 10),
    "chase_center":     ("Chase Center", 37.7680, -122.3877, 10),
    "sfo":              ("SFO Airport", 37.6213, -122.3790, 10),
}

# SF city bounding box (SFO allowed as the one exception — the city owns it).
SF_BOUNDS = {"lat": (37.70, 37.835), "lon": (-122.52, -122.35)}
SF_EXCEPTIONS = {"sfo"}

# Simplified transit: ordered stops + minutes between consecutive stops.
TRANSIT_LINES = [
    {"id": "BART", "mode": "bart", "name": "BART (SFO line)", "headway": 10,
     "stops": ["embarcadero", "montgomery", "powell", "civic_center", "mission_16th",
               "mission_24th", "glen_park", "balboa_park", "sfo"],
     "seg_min": [2, 2, 2, 3, 2, 4, 2, 20]},
    {"id": "N", "mode": "muni", "name": "Muni N Judah", "headway": 8,
     "stops": ["embarcadero", "montgomery", "powell", "civic_center", "van_ness",
               "church_duboce", "cole_carl", "ninth_judah", "ocean_beach"],
     "seg_min": [2, 2, 2, 2, 5, 7, 4, 14]},
    {"id": "T", "mode": "muni", "name": "Muni T Third (Central Subway)", "headway": 10,
     "stops": ["chinatown", "union_square", "moscone", "caltrain", "chase_center"],
     "seg_min": [2, 2, 4, 5]},
    {"id": "F", "mode": "muni", "name": "Muni F Market & Wharves", "headway": 12,
     "stops": ["castro", "church_duboce", "van_ness", "civic_center", "powell",
               "montgomery", "ferry_building", "pier_39", "fishermans_wharf"],
     "seg_min": [4, 5, 3, 4, 3, 5, 8, 4]},
    {"id": "39", "mode": "muni", "name": "Muni 39 Coit", "headway": 20,
     "stops": ["fishermans_wharf", "pier_39", "washington_sq", "coit_tower"],
     "seg_min": [3, 6, 6]},
    {"id": "PH", "mode": "cable", "name": "Powell-Hyde Cable Car", "headway": 10,
     "stops": ["powell", "union_square", "nob_hill", "lombard_st", "ghirardelli"],
     "seg_min": [3, 6, 7, 4]},
    {"id": "5", "mode": "muni", "name": "Muni 5 Fulton", "headway": 10,
     "stops": ["salesforce_tower", "civic_center", "painted_ladies", "golden_gate_park",
               "ocean_beach"],
     "seg_min": [9, 8, 10, 14]},
]

FARES = {"muni": 2.85, "cable": 8.00, "bart_city": 2.40, "bart_sfo": 10.95}

# SIMULATED ride-hail pricing — not real Uber/Lyft rates.
RIDE = {"base": 2.50, "per_mile": 1.35, "per_min": 0.32, "booking_fee": 2.95,
        "min_fare": 9.00, "pickup_wait_min": 4}

# Surge zones: (center place, radius_mi, multiplier, active hours, needs_event)
SURGE_ZONES = [
    ("oracle_park", 0.45, 1.9, range(17, 24), True),
    ("chase_center", 0.4, 1.8, range(17, 24), True),
    ("montgomery", 0.6, 1.4, range(16, 20), False),
]

# Bay Wheels docks (approximate) + public-ish pricing.
BIKE_DOCKS = ["ferry_building", "embarcadero", "salesforce_tower", "moscone", "union_square",
              "civic_center", "hayes_valley", "painted_ladies", "dolores_park", "mission_16th",
              "castro", "oracle_park", "caltrain", "marina_green", "fishermans_wharf",
              "golden_gate_park", "chase_center", "japantown"]
BIKE = {"unlock": 4.49, "included_min": 30, "classic_extra_per_15": 3.00,
        "ebike_per_min": 0.30}

MODE_COLORS = {"walk": "#16a34a", "ride": "#111827", "muni": "#dc2626", "bart": "#2563eb",
               "cable": "#a16207", "bike": "#7c3aed", "ebike": "#c026d3",
               # worldwide transit (Transitous); a line's own colour wins when the agency publishes one
               "bus": "#e04f16", "tram": "#0e9384", "metro": "#2e90fa", "rail": "#9e165f", "ferry": "#0086c9"}
