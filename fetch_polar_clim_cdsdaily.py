"""The polar-cap climatology built from the CDS DAILY reanalysis.

The chart measures a 15-day ERA5 reanalysis and a model's forecast against
the SAME climatology, so the climatology has to be the real ERA5's.

Two earlier climates were both wrong in a way that showed on the chart:

* the ARCO native store (`full_37-1h-...`) is ARCO's own vertical
  interpolation of the ERA5 pressure levels.  It mutes the stratospheric
  variability: its October sigma at 10 hPa is 710 m2/s2 where the real
  ERA5's is about 930.  An anomaly divided by a sigma that is too small
  comes out too big - which is what put the deep blue on the left of the
  chart, and it was not an atmospheric signal but the climate's own muted
  spread being divided by.

* the CDS MONTHLY means (`reanalysis-era5-pressure-levels-monthly-means`)
  come out about 11,000 m2/s2 (1,100 m) colder in the stratosphere than
  both ARCO stores and than the models, and their sigma is smaller still
  (427 m2/s2 in October).  A product that is that far from everything else
  is not the reference.

This builds the climate from the CDS DAILY product instead, on the same
grid and the same reduction as the reanalysis half: the 15th of each month
of 1991-2020, twelve levels, over the polar cap, at 12Z.  The CDS shares
the day list across the years, so the whole 30-year record is ONE request.

The result is the same shape as the other climates (a mean and a sigma per
calendar month, for the cap and for the two sectors), so the plotter can
read it with the same code.
"""
import json
import os
import sys
import time
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import read_grib_levels_sectors   # noqa: E402

LEVELS = [10, 30, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]
AREA = [90, -180, 60, 180]
YEARS = list(range(1991, 2021))
DAY = "15"

STATE = os.path.join(DATA, "polar_clim_cdsdaily_jobs.json")
OUT = os.path.join(DATA, "polar_cap_clim_cdsdaily.npz")

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November",
               "December"]


def submit(cds):
    """The one request that carries the whole 30-year climatology."""
    req = {"variable": ["geopotential"],
           "pressure_level": ["%d" % l for l in LEVELS],
           "year": ["%04d" % y for y in YEARS],
           "month": ["%02d" % m for m in range(1, 13)],
           "day": [DAY],
           "time": "12:00",
           "area": AREA,
           "data_format": "grib"}
    jid = cds.submit("reanalysis-era5-pressure-levels", req)
    json.dump({"jobs": [{"job": jid, "status": "accepted"}]},
              open(STATE, "w"), indent=1)
    print("   the daily climatology request: %s" % jid, flush=True)
    return jid


def build(path):
    """The GRIB -> the per-month mean and sigma over the 30 years."""
    times, vals, sec = read_grib_levels_sectors(path)
    by_month = defaultdict(dict)
    by_month_s = defaultdict(dict)
    for t, levels in vals.items():
        by_month[t[:7]][t] = levels
    for t, sdict in sec.items():
        by_month_s[t[:7]][t] = sdict
    rows = []
    srows = []
    for ym in sorted(by_month):
        for t in sorted(by_month[ym]):
            lv = by_month[ym][t]
            if all(l in lv for l in LEVELS):
                rows.append((ym, [lv[l] for l in LEVELS]))
                sd = by_month_s.get(ym, {}).get(t, {})
                srows.append((ym, {name: [d[l] for l in LEVELS]
                                   for name, d in sd.items()
                                   if all(l in d for l in LEVELS)}))
                break
    if not rows:
        raise SystemExit("the GRIB has no complete month")
    print("   %d months read" % len(rows), flush=True)

    out = {}
    sout = {}
    for m in range(1, 13):
        a = np.array([r[1] for r in rows if int(r[0][5:7]) == m], float)
        a = a[np.isfinite(a).all(axis=1)]
        if a.shape[0] < 2:
            print("   month %02d has only %d years - skipped" % (m, a.shape[0]))
            continue
        out[m] = {"n": int(a.shape[0]),
                  "mean": a.mean(axis=0).tolist(),
                  "sigma": a.std(axis=0, ddof=1).tolist()}
        print("   %-10s %2d years   the 10 hPa mean %10.1f  sigma %8.1f"
              % (MONTH_NAMES[m - 1], a.shape[0], out[m]["mean"][0],
                 out[m]["sigma"][0]), flush=True)
        names = sorted({n for _, sd in srows for n in sd})
        for name in names:
            b = np.array([sd[name] for ym, sd in srows
                          if int(ym[5:7]) == m and name in sd], float)
            if b.ndim != 2 or b.shape[0] < 2:
                continue
            b = b[np.isfinite(b).all(axis=1)]
            if b.shape[0] < 2:
                continue
            sout.setdefault(name, {})[m] = {
                "n": int(b.shape[0]),
                "mean": b.mean(axis=0).tolist(),
                "sigma": b.std(axis=0, ddof=1).tolist()}

    np.savez_compressed(OUT,
                        levels=np.array(LEVELS),
                        months=np.array(sorted(out)),
                        mean=np.array([out[m]["mean"] for m in sorted(out)], float),
                        sigma=np.array([out[m]["sigma"] for m in sorted(out)], float),
                        count=np.array([out[m]["n"] for m in sorted(out)], int),
                        sector_names=np.array(sorted(sout)),
                        sector_data=np.array(
                            [{name: {int(m): {"mean": sout[name][m]["mean"],
                                             "sigma": sout[name][m]["sigma"],
                                             "n": sout[name][m]["n"]}
                                     for m in sout[name]}
                              for name in sorted(sout)}], dtype=object))
    print("   the sector climates: %s" % ", ".join(
        "%s (%d months)" % (n, len(sout[n])) for n in sorted(sout)), flush=True)
    print("   -> %s" % OUT)
    return OUT


def main():
    import cds_direct
    cds = cds_direct.CDSDirect()
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"jobs": []}
    job = None
    for j in st.get("jobs", []):
        if j.get("status") not in ("rejected", "failed", "dismissed"):
            job = j["job"]
    if job is None:
        for _ in range(240):
            n = sum(1 for j in cds.live_jobs()
                    if j.get("status") in ("accepted", "running", "queued"))
            if n < 2:
                break
            print("   the account's queue is full - waiting", flush=True)
            time.sleep(30)
        job = submit(cds)
    else:
        print("   the request already in flight: %s" % job, flush=True)

    path = os.path.join(DATA, "_clim_cdsdaily.grib")
    for _ in range(400):
        status = cds.job_status(job)
        print("   the job: %s" % status, flush=True)
        if status in ("successful", "completed"):
            break
        if status in ("failed", "rejected", "dismissed"):
            raise SystemExit("the request was %s" % status)
        time.sleep(30)
    cds.download_job(job, path)
    build(path)
    os.remove(path)


if __name__ == "__main__":
    main()
