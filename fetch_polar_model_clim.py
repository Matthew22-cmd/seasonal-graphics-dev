"""The SEAS5's OWN hindcast climate for the polar cap.

**Why this is needed.**  The polar-cap section draws two halves: the
reanalysis (NOAA's CORe) on the left of the dashed line, and the model's
own run on the right.  For the two halves to be read against each other
they have to be on ONE scale, so the forecast is measured against the
OBSERVED climate - the CORe 1991-2020 climatology.

That works for a short run and it does not work for a seasonal one.  A
seasonal model's mean state is not the observed climate, and the
difference grows with the lead time:

    15 Nov 2026, ECMWF SEAS5 against the CORe analysis
        day 1        -254 m2/s2
        day 11       -920 m2/s2
        mid-Dec    about -3,100 against the observed climate
        Apr-May    about -5,000

So the far end of the chart was drawn as -2 to -4 sigma of a cold
stratosphere when it is really the model sitting below the observed
climate - the model's own drift, not a forecast.  (The June sigma of the
observed climate is only 647 m2/s2, so the drift was amplified fourfold
by the denominator.)

**The fix is the convention the rest of the site already uses.**  The
snow maps are "vs this model's own hindcast climate", and the SPV chart
draws the model's own climate as a line beside the forecast.  So the
forecast is measured against the model's OWN climate and added back to
the observed climate:

    plotted = observed_climate + (model - model_clim)

The reanalysis half is untouched (it is the observed climate against
itself), the two halves still meet at the dashed line, and the model's
mean-state drift is removed from the forecast.

**Where the model's own climate comes from.**  The C3S seasonal product
publishes it: `seasonal-monthly-pressure-levels` with
`product_type: hindcast_climate_mean` is the model's own hindcast
climate mean for each lead month - the same `product_type` the snowfall
anomaly charts use for "this model's own hindcast climate".

    python3 fetch_polar_model_clim.py
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import (LEVELS, SECTORS, read_grib_levels_sectors)  # noqa: E402

AREA = [90, -180, 60, 180]
OUT = os.path.join(DATA, "polar_model_clim.json")
GRIB = os.path.join(DATA, "_model_clim.grib")
STATE = os.path.join(DATA, "polar_model_clim_jobs.json")

# the ECMWF's seasonal system 51 (SEAS5), and the init the section uses
CENTRE = "ecmwf"
SYSTEM = 51
YEAR, MONTH, DAY = "2026", "11", "01"
# The MONTHLY product caps at lead month 6 (November to April) - that is
# a cap of the dataset, not of the model's range.  The SEAS5 runs to lead
# month 8, so the model's own climate for May and June has to come from
# the model's own past runs (the daily product serves historical inits).
LEADS = list(range(1, 7))          # lead months 1-6 (November to April)


def request():
    """The one request that carries the model's own climate."""
    return {
        "originating_centre": CENTRE,
        "system": str(SYSTEM),
        "variable": "geopotential",
        "pressure_level": ["%d" % l for l in LEVELS],
        "product_type": "hindcast_climate_mean",
        "year": YEAR,
        "month": MONTH,
        "leadtime_month": ["%d" % k for k in LEADS],
        "area": AREA,
        "data_format": "grib",
    }


def build(path):
    """The GRIB -> the model's own climate, for the cap and the sectors.

    -> {"lead": {k: {"cap": {...}, "sectors": {...}}}, ...}
    """
    times, vals, sec = read_grib_levels_sectors(path)
    # the monthly product writes the month on its first day, so the
    # validity date says which lead month the field is
    per_lead = {}
    print("   the times in the file: %s" % sorted(vals), flush=True)
    for t in sorted(vals):
        y, m = int(t[:4]), int(t[5:7])
        # The monthly product stamps a month on the FIRST of the month
        # AFTER the one it covers: the field dated 2026-12-01 is
        # November 2026, which is lead month 1 of a November init.
        k = ((y * 12 + m) - (int(YEAR) * 12 + int(MONTH))) % 12
        if k == 0:
            k = 12
        if k not in LEADS:
            print("   the time %s maps to lead month %d - skipped" % (t, k),
                  flush=True)
            continue
        lv = vals[t]
        if not all(l in lv for l in LEVELS):
            continue
        sd = sec.get(t, {})
        if not all(n in sd for n in SECTORS):
            continue
        if any(not all(l in sd[n] for l in LEVELS) for n in SECTORS):
            continue
        per_lead[k] = {
            "cap": {str(l): float(lv[l]) for l in LEVELS},
            "sectors": {n: {str(l): float(sd[n][l]) for l in LEVELS}
                        for n in SECTORS},
        }
    return per_lead


def main():
    import cds_direct
    cds = cds_direct.CDSDirect()

    # the account's queue is shared, so the room is checked first.  Only
    # the jobs that are still IN FLIGHT count: the account's job list
    # carries every request it has ever made, and the successful ones are
    # the great majority of it.
    for _ in range(180):
        live = [j for j in cds.live_jobs()
                if j.get("status") in ("accepted", "running", "queued",
                                       "executing")]
        if len(live) < 2:
            print("   the account holds %d job(s) in flight" % len(live),
                  flush=True)
            break
        print("   the account holds %d job(s); waiting for room" % len(live),
              flush=True)
        time.sleep(20)

    req = request()
    print("   the request: %s" % json.dumps(req), flush=True)
    jid = cds.submit("seasonal-monthly-pressure-levels", req)
    st = {"jobs": [{"job": jid, "status": "submitted"}]}
    json.dump(st, open(STATE, "w"), indent=1)
    print("   the job %s" % jid, flush=True)

    # wait for it
    for _ in range(720):
        s = cds.job_status(jid)
        if s in ("successful", "completed"):
            break
        if s in ("failed", "error", "rejected", "dismissed"):
            raise SystemExit("   the job is %s" % s)
        time.sleep(15)
    else:
        raise SystemExit("   the job did not finish in time")

    cds.download_job(jid, GRIB)
    print("   the GRIB: %d bytes" % os.path.getsize(GRIB), flush=True)

    per_lead = build(GRIB)
    if not per_lead:
        raise SystemExit("   the GRIB holds no complete lead month")
    out = {"centre": CENTRE, "system": SYSTEM, "init": "%s-%s-%s" % (YEAR, MONTH, DAY),
           "levels": list(LEVELS), "leads": {}}
    for k in sorted(per_lead):
        rec = per_lead[k]
        out["leads"][str(k)] = rec
        print("   lead month %d: the 10 hPa cap mean %10.1f" %
              (k, rec["cap"]["10"]), flush=True)
    with open(OUT + ".tmp", "w") as f:
        json.dump(out, f, indent=1)
    os.replace(OUT + ".tmp", OUT)
    print("   written: %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
