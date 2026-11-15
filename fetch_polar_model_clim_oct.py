"""The model's own climate for the month BEFORE the chart's first day.

**Why this is needed.**  The forecast half of the polar chart is re-based on
the model's own climate, and the model's climate is a MONTHLY climatology
that is interpolated onto the days the same way the observed climate is.
The chart starts on 2 November 2026, and the interpolation of the observed
climate on the first half of November leans on the OCTOBER mean - so the
model's October mean is needed as well, or the two halves do not meet at
the dashed line.

**The lead question.**  The chart's October sits at lead month 12 of the
November init, which no product publishes (the monthly product caps at
lead month 6, and the daily product stops at 215 days).  The October mean
published for the October 2026 init is lead month 1 of THAT init, so it is
not exactly the same quantity.

This request therefore asks for the October init's leads 1-6, which also
gives November at lead month 2 - and November at lead month 1 is already
known from the November init.  The difference between the two IS the
model's mean-state drift per lead month, so the lead gap can be measured
instead of guessed.

    python3 fetch_polar_model_clim_oct.py
"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import LEVELS  # noqa: E402
from fetch_polar_model_clim import build, request  # noqa: E402

OUT = os.path.join(DATA, "polar_model_clim_oct.json")
GRIB = os.path.join(DATA, "_model_clim_oct.grib")
STATE = os.path.join(DATA, "polar_model_clim_oct_jobs.json")

YEAR, MONTH, DAY = "2026", "10", "01"


def main():
    import cds_direct
    cds = cds_direct.CDSDirect()

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
    req["year"] = YEAR
    req["month"] = MONTH
    print("   the request: %s" % json.dumps(req), flush=True)
    jid = cds.submit("seasonal-monthly-pressure-levels", req)
    json.dump({"jobs": [{"job": jid, "status": "submitted"}]},
              open(STATE, "w"), indent=1)
    print("   the job %s" % jid, flush=True)

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

    import fetch_polar_model_clim
    old = (fetch_polar_model_clim.YEAR, fetch_polar_model_clim.MONTH)
    fetch_polar_model_clim.YEAR, fetch_polar_model_clim.MONTH = YEAR, MONTH
    per_lead = build(GRIB)
    fetch_polar_model_clim.YEAR, fetch_polar_model_clim.MONTH = old

    if not per_lead:
        raise SystemExit("   the GRIB holds no complete lead month")
    out = {"centre": "ecmwf", "system": 51, "init": "%s-%s-%s" % (YEAR, MONTH, DAY),
           "levels": list(LEVELS), "leads": {}}
    for k in sorted(per_lead):
        rec = per_lead[k]
        out["leads"][str(k)] = rec
        print("   the October init's lead month %d: the 10 hPa cap mean %10.1f"
              % (k, rec["cap"]["10"]), flush=True)
    with open(OUT + ".tmp", "w") as f:
        json.dump(out, f, indent=1)
    os.replace(OUT + ".tmp", OUT)
    print("   written: %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
