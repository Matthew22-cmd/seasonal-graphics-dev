"""The polar-cap section's reanalysis and its climate, from NOAA's CORe.

Why CORe (15 Nov 2026):

The section's reanalysis half came from ARCO's native ERA5 store, and that
store's stratosphere is **about 600 m too low** at 10 hPa over the polar
cap.  Three independent products say so:

| source | 10 hPa, mid Nov 2026 |
|---|---|
| ARCO's ERA5 (the store the chart was using) | ~290,700 m2/s2 |
| ECMWF's own IFS analysis (the EC46's control member) | 296,661 m2/s2 |
| NOAA's GEFSv12, day 1 of its forecast | 295,904 m2/s2 |
| **NOAA's CORe reanalysis** | 296,902 m2/s2 |

ARCO's stores are their own vertical interpolation of the ERA5 model levels,
and in the stratosphere that interpolation is what is wrong - the reduced
store and the native store agree with each other and disagree with the
atmosphere.  The ERA5 archive itself (the CDS product) is the native one,
but it is behind a queue that has been sitting for hours.

CORe is the fallback that needs no queue at all: NOAA's Conventional
Observation Reanalysis is on a public GCS bucket with wgrib2 inventories,
so the twelve messages the section needs are fetched **by byte range** -
about 1 MB a day out of a 35 MB file.

CORe is also, by design, the better climate: it assimilates no satellite
radiances, so its record has no jumps at the satellite transitions, which is
exactly what a 1991-2020 climatology must not have.

The pull gives two things, in the shapes the plotter already reads:

  * `data/polar_core_recent.npz`    - the recent days, the same shape as
    `data/polar_era5_recent.npz`;
  * `data/polar_cap_clim_core.npz`  - the 1991-2020 climate, the same shape
    as `data/polar_cap_clim_monthly.npz`.
"""
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import SECTORS, sector_mean, zonal_mean   # noqa: E402

LEVELS = [10, 30, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]
G0 = 9.80665

BUCKET = ("https://storage.googleapis.com/noaa-nws-ncep-core/grib/day/pgb/"
          "%s/%s/pgb.%s")
RECENT = os.path.join(DATA, "polar_core_recent.npz")
CLIM = os.path.join(DATA, "polar_cap_clim_core.npz")
STATE = os.path.join(DATA, "polar_core_state.json")

# how many days of reanalysis the section draws, and how many days of
# climate are built
RECENT_DAYS = 40
CLIM_YEARS = list(range(1991, 2021))
CLIM_DAY = "15"


# ------------------------------------------------------------------ the bucket
def _url(day):
    return BUCKET % (day[:4], day[4:6], day)


def _get(url, start=None, end=None):
    import requests
    headers = {}
    if start is not None:
        headers["Range"] = "bytes=%d-%s" % (start, (end - 1) if end else "")
    r = requests.get(url, headers=headers, timeout=120)
    r.raise_for_status()
    return r.content


def inventory(day):
    """-> [(offset, name, level), ...] for the day's file."""
    text = _get(_url(day) + ".idx").decode("utf-8", "ignore")
    out = []
    for line in text.splitlines():
        p = line.split(":")
        if len(p) < 5:
            continue
        try:
            off = int(p[1])
        except ValueError:
            continue
        out.append((off, p[3], p[4]))
    return out


def hgt_messages(day):
    """-> [(level hPa, the bytes of the message)], the twelve the section uses.

    The messages are pulled by byte range, so a day costs about a megabyte
    instead of the thirty-five the whole file holds.
    """
    msgs = inventory(day)
    want = []
    for i, (off, name, lev) in enumerate(msgs):
        if name != "HGT":
            continue
        mb = lev.split(" mb")[0]
        if not mb.isdigit() or int(mb) not in LEVELS:
            continue
        end = msgs[i + 1][0] if i + 1 < len(msgs) else None
        want.append((int(mb), off, end))
    out = []
    for mb, off, end in want:
        out.append((mb, _get(_url(day) + ".grb", off, end)))
    return out


def decode(messages):
    """-> {level: the polar cap mean}, {sector: {level: the sector mean}}."""
    import eccodes
    import threading
    cap = {}
    sec = {name: {} for name in SECTORS}
    tag = "%d_%d" % (os.getpid(), threading.get_ident())
    for mb, data in messages:
        tmp = os.path.join(DATA, "_core_%s_%d.grb" % (tag, mb))
        with open(tmp, "wb") as f:
            f.write(data)
        with open(tmp, "rb") as f:
            while True:
                try:
                    gid = eccodes.codes_grib_new_from_file(f)
                except Exception:                       # noqa: BLE001
                    break
                if gid is None:
                    break
                try:
                    la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                    lo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                    v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                    lats = np.unique(la)[::-1]
                    lons = np.unique(lo)
                    v = v.reshape(len(lats), len(lons))
                    # HGT is geopotential metres; the section is in m2/s2
                    cap[mb] = zonal_mean(v * G0, lats)
                    for name, (a, b) in SECTORS.items():
                        # the LONGITUDES go in here: passing the latitudes
                        # makes the sector mask meaningless and every
                        # sector mean comes back NaN
                        sec[name][mb] = sector_mean(v * G0, lats, lons, a, b)
                finally:
                    eccodes.codes_release(gid)
        os.remove(tmp)
    return cap, sec


def day_means(day):
    """-> ({level: cap mean}, {sector: {level: mean}}) for one day."""
    cap, sec = decode(hgt_messages(day))
    return cap, sec


# ------------------------------------------------------------------ the pull
def available_days(year, month):
    """The days the bucket holds for a month."""
    import requests
    prefix = "grib/day/pgb/%s/%s/" % (year, month)
    r = requests.get("https://storage.googleapis.com/storage/v1/b/"
                     "noaa-nws-ncep-core/o?prefix=%s&maxResults=1000"
                     % prefix, timeout=120)
    r.raise_for_status()
    names = [i["name"] for i in r.json().get("items", [])]
    out = []
    for n in names:
        b = os.path.basename(n)
        if b.startswith("pgb.") and b.endswith(".grb"):
            out.append(b[4:-4])
    return sorted(out)


def pull_recent(n_days=RECENT_DAYS):
    """The last n_days days the bucket holds -> data/polar_core_recent.npz."""
    # the days that are actually there: the bucket is a few days behind, so
    # the window is found by listing the months rather than by counting back
    # from today
    today = time.strftime("%Y%m%d")
    y, m = int(today[:4]), int(today[4:6])
    days = []
    for _ in range(4):
        days = available_days("%04d" % y, "%02d" % m) + days
        m -= 1
        if m == 0:
            m, y = 12, y - 1
        if len(days) >= n_days:
            break
    days = sorted(days)[-n_days:]
    print("   the window: %s -> %s" % (days[0], days[-1]), flush=True)

    times, values, sectors = [], [], {n: [] for n in SECTORS}
    with ThreadPoolExecutor(max_workers=6) as pool:
        got = list(pool.map(day_means, days))
    for day, (cap, sec) in zip(days, got):
        if not cap or any(l not in cap for l in LEVELS):
            print("   %s has no complete set of levels - skipped" % day)
            continue
        times.append("%s-01 12" % "%s-%s-%s" % (day[:4], day[4:6], day[6:]))
        values.append([cap[l] for l in LEVELS])
        for name in SECTORS:
            sd = sec.get(name, {})
            if any(l not in sd for l in LEVELS):
                times.pop()
                values.pop()
                break
            sectors[name].append([sd[l] for l in LEVELS])
    np.savez_compressed(RECENT, times=np.array(times), levels=np.array(LEVELS),
                        values=np.asarray(values, float),
                        sector_names=np.array(sorted(sectors)),
                        sector_data=np.asarray([sectors[n] for n in sorted(sectors)],
                                               float))
    print("   the recent CORe: %d days -> %s" % (len(times), RECENT))
    return RECENT


def pull_climate():
    """The 15th of each month of 1991-2020 -> data/polar_cap_clim_core.npz."""
    days = ["%04d%02d%s" % (y, m, CLIM_DAY) for y in CLIM_YEARS
            for m in range(1, 13)]
    print("   the climate: %d days of CORe" % len(days), flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        got = list(pool.map(day_means, days))
    by_month = {}
    by_month_s = {n: {} for n in SECTORS}
    for day, (cap, sec) in zip(days, got):
        m = int(day[4:6])
        if not cap or any(l not in cap for l in LEVELS):
            continue
        by_month.setdefault(m, []).append([cap[l] for l in LEVELS])
        for name in SECTORS:
            sd = sec.get(name, {})
            if all(l in sd for l in LEVELS):
                by_month_s[name].setdefault(m, []).append(
                    [sd[l] for l in LEVELS])
    out = {}
    sout = {}
    for m in sorted(by_month):
        a = np.asarray(by_month[m], float)
        out[m] = {"n": int(a.shape[0]),
                  "mean": a.mean(axis=0).tolist(),
                  "sigma": a.std(axis=0, ddof=1).tolist()}
        print("   month %02d: %2d years   the 10 hPa mean %10.1f  sigma %8.1f"
              % (m, a.shape[0], out[m]["mean"][0], out[m]["sigma"][0]), flush=True)
        for name in SECTORS:
            b = by_month_s[name].get(m)
            if not b or len(b) < 2:
                continue
            b = np.asarray(b, float)
            sout.setdefault(name, {})[m] = {
                "n": int(b.shape[0]),
                "mean": b.mean(axis=0).tolist(),
                "sigma": b.std(axis=0, ddof=1).tolist()}
    np.savez_compressed(CLIM,
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
    print("   -> %s" % CLIM)
    return CLIM


if __name__ == "__main__":
    what = sys.argv[1] if len(sys.argv) > 1 else "both"
    if what in ("recent", "both"):
        print("   the recent CORe ...", flush=True)
        pull_recent()
    if what in ("clim", "both"):
        print("   the CORe climate ...", flush=True)
        pull_climate()
