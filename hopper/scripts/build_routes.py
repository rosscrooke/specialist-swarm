"""Build app/fixtures/routes.json: which airport pairs have scheduled nonstop service.

    python scripts/build_routes.py routes.dat

routes.dat is OpenFlights' route database (https://openflights.org/data, ODbL 1.0; last
updated June 2014): https://raw.githubusercontent.com/jpatokal/openflights/master/data/routes.dat
Only nonstop routes between airports in fixtures/airports.json are kept, stored both ways.
The output is a derived database under the same ODbL licence.
"""
import csv
import json
import sys
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent.parent / "app" / "fixtures"


def main(src):
    ours = {row[0] for row in json.loads((FIXTURES / "airports.json").read_text())["airports"]}
    routes = {}
    with open(src, newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if len(row) < 9 or row[7] not in ("0", ""):          # stops: nonstop only
                continue
            a, b = row[2], row[4]
            if a in ours and b in ours and a != b:
                routes.setdefault(a, set()).add(b)
                routes.setdefault(b, set()).add(a)
    out = {"source": "OpenFlights routes.dat (ODbL 1.0, https://openflights.org/data), nonstop, June 2014",
           "routes": {k: " ".join(sorted(v)) for k, v in sorted(routes.items())}}
    (FIXTURES / "routes.json").write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(f"{len(routes)} airports, {sum(len(v) for v in routes.values()) // 2} routes")


if __name__ == "__main__":
    main(sys.argv[1])
