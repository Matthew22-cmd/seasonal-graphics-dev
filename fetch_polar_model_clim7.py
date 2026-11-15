"""The SEAS5's OWN climate for lead months 7 and 8 (May and June).

**Why this is a separate pull.**  The model's own hindcast climate comes
from the C3S `seasonal-monthly-pressure-levels` product with
`product_type: hindcast_climate_mean` - one small request for lead months
1-6 (see fetch_polar_model_clim.py).  But the monthly product caps at lead
month 6, and the SEAS5's run reaches lead month 8, so the far end of the
section (May and June) has no published model climate.

The DAILY product (`seasonal-original-pressure-levels`) reaches 215 days,
and it serves HISTORICAL INITS.  So the model's own climate for the far
end is the mean of the model's own past runs:

    for each past November init, the polar-cap mean at the May-June leads
    -> the mean over the inits

which is exactly how the SPV chart's month-7 model climate was built
(data/m7_<YYYYMM>.npz, model_clim_m7.py).  Ten November inits are used
here, the same ten the wind chart uses.

**The window.**  A November init reaches lead month 6 in April, lead month
7 in May and lead month 8 in June.  April is pulled too, so the result can
be CHECKED against the monthly product's own lead month 6 - the same
season, the same lead, the same ensemble.

    python3 fetch_polar_model_clim7.py            # all ten inits
    python3 fetch_polar_model_clim7.py --years 3  # fewer, for a quick look
"""
import json
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import LEVELS, SECTORS, read_grib_levels_sectors  # noqa: E402

AREA = [90, -180, 60, 180]
OUT = os.path.join(DATA, "polar_model_clim7.json")
STATE = os.path.join(DATA, "polar_model_clim7_jobs.json")

CENTRE = "ecmwf"
SYSTEM = "51"
DATASET = "seasonal-original-pressure-levels"

# The November inits the model's own far-end climate is built from.  The
# SPV chart's month-7 climate uses the same ten.
INITS = [(2016, 11), (2017, 11), (2018, 11), (2019, 11), (2020, 11),
         (2021, 11), (2022, 11), (2023, 11), (2024, 11), (2025, 11)]

# The days of the three far lead months that are pulled: four in each of
# April (lead 6), May (lead 7) and June (lead 8).  The seasonal runs are
# initialised on the 1st at 00Z, so the 12Z value of a day sits at a lead
# of 12 + 24k hours.
# The daily product serves 215 days, so lead month 8 (June) only exists
# for the first three days - which is exactly the part of it the section
# draws.  April and May are pulled in full.
DAYS = {"04": [5, 13, 21, 29], "05": [5, 13, 21, 29], "06": [1, 3]}
# the days from 1 November to the 1st of each month: 1 April is day 151,
# 1 May is day 181 and 1 June is day 212.  So April is lead month 6, May
# is lead month 7 and June is lead month 8.
DAYS_FROM_NOV = {"04": 151, "05": 181, "06": 212}
MONTH_OF_LEAD = {"04": 6, "05": 7, "06": 8}


def lead_hours():
    """-> (the lead hours, {lead hour: (month, lead month)})"""
    hs = []
    tag = {}
    for mm, dd in DAYS.items():
        for d in dd:
            days = DAYS_FROM_NOV[mm] + d - 1
            h = 12 + 24 * days
            hs.append(h)
            tag[h] = (mm, MONTH_OF_LEAD[mm])
    return sorted(hs), tag


def request(year, month, hs):
    return {
        "originating_centre": CENTRE,
        "system": SYSTEM,
        "variable": "geopotential",
        "pressure_level": ["%d" % l for l in LEVELS],
        "year": str(year),
        "month": "%02d" % month,
        "day": "01",
        "leadtime_hour": [str(h) for h in hs],
        "area": AREA,
        "data_format": "grib",
    }


def build(path, tag):
    """The GRIB -> {lead month: {"cap": {...}, "sectors": {...}}}.

    The days of a lead month are AVERAGED, because that is what the
    monthly product publishes: a model's own climate is the mean over the
    lead month.  A single day is a different number - the polar cap warms
    by about 4,700 m2/s2 between the 5th and the 29th of April - and the
    April lead month is the check on this pull: the monthly product says
    299,082.5 for the 10 hPa cap mean and the single day says 296,625.6.
    """
    times, vals, sec = read_grib_levels_sectors(path)
    acc = {}
    for t in sorted(vals):
        # the time the field is valid at; the lead hour is what the
        # request asked for, and the decoder keeps the validity time
        h = _lead_hour(t)
        if h not in tag:
            continue
        mm, lead = tag[h]
        lv = vals[t]
        sd = sec.get(t, {})
        if not all(l in lv for l in LEVELS):
            continue
        if not all(n in sd and all(l in sd[n] for l in LEVELS)
                   for n in SECTORS):
            continue
        a = acc.setdefault(str(lead), {
            "n": 0,
            "cap": {str(l): 0.0 for l in LEVELS},
            "sectors": {n: {str(l): 0.0 for l in LEVELS} for n in SECTORS}})
        a["n"] += 1
        for l in LEVELS:
            a["cap"][str(l)] += float(lv[l])
        for n in SECTORS:
            for l in LEVELS:
                a["sectors"][n][str(l)] += float(sd[n][l])
    out = {}
    for k, a in acc.items():
        n = max(1, a["n"])
        out[k] = {"days": a["n"],
                  "cap": {l: v / n for l, v in a["cap"].items()},
                  "sectors": {sn: {l: v / n for l, v in sv.items()}
                              for sn, sv in a["sectors"].items()}}
    return out


def _lead_hour(t):
    """The validity time -> the lead hour in the request.

    The seasonal runs are initialised on the 1st at 00Z and the values are
    at 12Z, so the lead is 12 + 24k.  The decoder hands back the
    validity time, so the day is counted from the 1st of November.
    """
    import datetime as dt
    d = dt.datetime.strptime(t[:10], "%Y-%m-%d")
    # the init of the year the run started
    for init_year in (d.year - 1, d.year):
        init = dt.datetime(init_year, 11, 1)
        days = (d - init).days
        if 0 <= days <= 300:
            return 12 + 24 * days
    return None


def main():
    import cds_direct
    cds = cds_direct.CDSDirect()
    hs, tag = lead_hours()
    print("   %d lead hours: %s" % (len(hs), hs), flush=True)

    st = json.load(open(STATE)) if os.path.exists(STATE) else {"jobs": []}
    done = {j.get("init") for j in st["jobs"] if j.get("status") == "done"}
    years = int(sys.argv[sys.argv.index("--years") + 1]) \
        if "--years" in sys.argv else len(INITS)

    for year, month in INITS[:years]:
        key = "%04d-%02d" % (year, month)
        if key in done:
            print("   %s: done already" % key, flush=True)
            continue
        # A job that is already in the store is ADOPTED, not asked for a
        # second time: the account's queue is small and a duplicate request
        # would take the room away from the job that is already waiting.
        live_job = None
        for j in st["jobs"]:
            if j.get("init") == key and j.get("status") in (
                    "submitted", "accepted", "running") and j.get("job"):
                live_job = j
                break
        if live_job is not None:
            jid = live_job["job"]
            print("   the init %s: the job %s is already in the store"
                  % (key, str(jid)[:8]), flush=True)
            ok = False
            for _ in range(720):
                s = cds.job_status(jid)
                if s in ("successful", "completed"):
                    ok = True
                    break
                if s in ("failed", "error", "rejected", "dismissed"):
                    print("   the job is %s" % s, flush=True)
                    break
                time.sleep(15)
            if not ok:
                continue
            path = os.path.join(DATA, "_model_clim7_%s.grib" % key)
            cds.download_job(jid, path)
            print("   the GRIB: %d bytes" % os.path.getsize(path), flush=True)
            rec = build(path, tag)
            os.remove(path)
            live_job["status"] = "done"
            live_job["leads"] = sorted(rec.keys())
            live_job["values"] = rec
            with open(STATE + ".tmp", "w") as f:
                json.dump(st, f, indent=1)
            os.replace(STATE + ".tmp", STATE)
            for lead in sorted(rec):
                print("   %s: lead month %s, %d day(s), the 10 hPa cap mean "
                      "%10.1f" % (key, lead, rec[lead].get("days", 0),
                                  rec[lead]["cap"]["10"]), flush=True)
            continue
        # the room is made first: the store refuses a request when the
        # account already holds too many jobs
        for _ in range(180):
            live = [j for j in cds.live_jobs()
                    if j.get("status") in ("accepted", "running", "queued",
                                           "executing")]
            if len(live) < 2:
                break
            print("   the account holds %d job(s); waiting for room"
                  % len(live), flush=True)
            time.sleep(20)

        print("   the init %s ..." % key, flush=True)
        try:
            jid = cds.submit(DATASET, request(year, month, hs))
        except Exception as e:                          # noqa: BLE001
            print("   the request was refused: %s" % str(e)[:200], flush=True)
            st["jobs"].append({"init": key, "status": "refused",
                               "note": str(e)[:300]})
            with open(STATE + ".tmp", "w") as f:
                json.dump(st, f, indent=1)
            os.replace(STATE + ".tmp", STATE)
            continue
        st["jobs"].append({"init": key, "job": jid, "status": "submitted"})
        with open(STATE + ".tmp", "w") as f:
            json.dump(st, f, indent=1)
        os.replace(STATE + ".tmp", STATE)
        print("   the job %s" % jid, flush=True)

        ok = False
        for _ in range(720):
            s = cds.job_status(jid)
            if s in ("successful", "completed"):
                ok = True
                break
            if s in ("failed", "error", "rejected", "dismissed"):
                print("   the job is %s" % s, flush=True)
                break
            time.sleep(15)
        if not ok:
            continue
        path = os.path.join(DATA, "_model_clim7_%s.grib" % key)
        cds.download_job(jid, path)
        print("   the GRIB: %d bytes" % os.path.getsize(path), flush=True)
        rec = build(path, tag)
        os.remove(path)
        st["jobs"][-1]["status"] = "done"
        st["jobs"][-1]["leads"] = sorted(rec.keys())
        # the decoded values are kept, so the GRIB does not have to be
        # fetched again to build the mean over the inits
        st["jobs"][-1]["values"] = rec
        with open(STATE + ".tmp", "w") as f:
            json.dump(st, f, indent=1)
        os.replace(STATE + ".tmp", STATE)
        for lead in sorted(rec):
            print("   %s: lead month %s, the 10 hPa cap mean %10.1f"
                  % (key, lead, rec[lead]["cap"]["10"]), flush=True)

    write_mean(st)


def write_mean(st):
    """The mean over the inits -> data/polar_model_clim7.json."""
    per_lead = {}
    for j in st["jobs"]:
        if j.get("status") != "done":
            continue
        for lead, rec in (j.get("values") or {}).items():
            per_lead.setdefault(lead, []).append(rec)
    if not per_lead:
        raise SystemExit("   nothing decoded yet")
    out = {"centre": CENTRE, "system": SYSTEM, "levels": list(LEVELS),
           "leads": {}}
    for lead, recs in sorted(per_lead.items()):
        cap = np.mean([[r["cap"][str(l)] for l in LEVELS] for r in recs], axis=0)
        sec = {}
        for n in SECTORS:
            a = np.mean([[r["sectors"][n][str(l)] for l in LEVELS]
                         for r in recs], axis=0)
            sec[n] = {str(l): float(a[i]) for i, l in enumerate(LEVELS)}
        out["leads"][lead] = {
            "n": len(recs),
            "cap": {str(l): float(cap[i]) for i, l in enumerate(LEVELS)},
            "sectors": sec}
        print("   lead month %s: %d inits, the 10 hPa cap mean %10.1f"
              % (lead, len(recs), cap[0]), flush=True)
    with open(OUT + ".tmp", "w") as f:
        json.dump(out, f, indent=1)
    os.replace(OUT + ".tmp", OUT)
    print("   written: %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
