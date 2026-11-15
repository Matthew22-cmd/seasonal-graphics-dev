"""The polar-cap climatology from NOAA's NCEP/NCAR Reanalysis (R1).

Why (15 Nov 2026):

The section's reanalysis half came from ARCO's native ERA5 store, and that
store's stratosphere is wrong in two ways at once: its level is about 600 m
too low at 10 hPa over the polar cap, and it does not have the sudden
stratospheric warming of late October 2026 at all.  Three products say so
(the ECMWF's own IFS analysis, NOAA's GEFSv12 and NOAA's CORe all agree
with each other and not with ARCO).

The ERA5 archive itself is the native product and the right answer, but it
is behind a CDS queue that has been sitting for hours.  R1 is not queued:
PSL serves it through a subset service, so the 1991-2020 record comes down
in thirty requests.

R1 is not the section's reanalysis - it stops in March 2026 - it is the
**climate**, and it is used as one:

  * it is a full, unmuted reanalysis, so its standard deviations are the
    real ones (ARCO's October sigma at 10 hPa is 710 m2/s2 where R1's is
    about 1,000, and an anomaly divided by a sigma that is too small comes
    out too big - that is what put the deep blue on the chart);
  * its 1991-2020 October-November mean agrees with the ARCO archives to
    within about 130 m, so it is on the same scale as the rest.

The file it writes has the same shape as the other climates: a mean and a
sigma per calendar month, for the cap and for the two sectors.

    python3 fetch_polar_clim_r1.py
"""
import os
import subprocess
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import SECTORS, cap_weights   # noqa: E402

LEVELS = [10, 30, 50, 100, 200, 300, 400, 500, 700, 850, 925, 1000]
YEARS = list(range(1991, 2021))
DAY = 15

BASE = ("https://psl.noaa.gov/thredds/ncss/grid/Datasets/ncep.reanalysis/"
        "Dailies/pressure/hgt.%d.nc")
OUT = os.path.join(DATA, "polar_cap_clim_r1.npz")

MONTH_NAMES = ["January", "February", "March", "April", "May", "June",
               "July", "August", "September", "October", "November",
               "December"]


def fetch(year, months):
    """The subset for the given months of one year -> (levels, lat, lon, values).

    The NCSS takes a list of time ranges, so the twelve days of a year come
    down in ONE request.
    """
    starts = "%04d-%02d-%02dT00:00:00Z" % (year, months[0], DAY)
    ends = "%04d-%02d-%02dT23:59:59Z" % (year, months[0], DAY)
    url = (BASE % year +
           "?var=hgt&north=90&west=0&east=357.5&south=60&horizStride=1"
           "&time_start=%s&time_end=%s"
           "&level=%s&accept=netcdf"
           % (starts, ends, "&".join(str(l) for l in LEVELS)))
    path = "/tmp/_r1_%d_%02d.nc" % (year, months[0])
    subprocess.run(["curl", "-sL", "--max-time", "300", url, "-o", path],
                   check=False)
    if not os.path.exists(path) or os.path.getsize(path) < 2000:
        raise RuntimeError("the %d subset did not come" % year)
    from scipy.io import netcdf_file
    f = netcdf_file(path, "r", mmap=False)
    try:
        lat = np.asarray(f.variables["lat"][:], float)
        lon = np.asarray(f.variables["lon"][:], float)
        lev = [float(x) for x in f.variables["level"][:]]
        data = np.asarray(f.variables["hgt"][:], float)   # (time, level, lat, lon)
    finally:
        f.close()
    os.remove(path)
    return lev, lat, lon, data


def cap_and_sectors(data, lat, lon, lev):
    """-> ({level: the cap mean}, {sector: {level: the mean}}) in m."""
    w = cap_weights(lat)
    used = w > 0
    lons = np.asarray(lon, float) % 360.0
    cap = {}
    sec = {name: {} for name in SECTORS}
    for i, l in enumerate(lev):
        f = data[i][used, :]
        cap[int(l)] = float((f * w[used, None]).sum() /
                            (f.shape[1] * w[used].sum()))
        for name, (a, b) in SECTORS.items():
            m = (lons >= a) & (lons < b) if b >= a else \
                (lons >= a) | (lons < b)
            if not m.any():
                continue
            g = f[:, m]
            sec[name][int(l)] = float((g * w[used, None]).sum() /
                                      (float(m.sum()) * w[used].sum()))
    return cap, sec


def main():
    rows = {}          # month -> [ [level values] ]
    srows = {n: {} for n in SECTORS}
    # every year and month, six at a time: the subset service is quick
    # and there is no queue
    from concurrent.futures import ThreadPoolExecutor
    jobs = [(y, m) for y in YEARS for m in range(1, 13)]

    def one(job):
        year, month = job
        try:
            lev, lat, lon, data = fetch(year, [month])
        except Exception as e:                     # noqa: BLE001
            return job, None, str(e)[:70]
        if data.shape[0] < 1:
            return job, None, "no data"
        cap, sec = cap_and_sectors(data[0], lat, lon, lev)
        if any(l not in cap for l in LEVELS):
            return job, None, "not every level"
        return job, (cap, sec), None

    with ThreadPoolExecutor(max_workers=6) as pool:
        for n, (job, got, err) in enumerate(pool.map(one, jobs), 1):
            year, month = job
            if got is None:
                print("   %d-%02d: %s" % (year, month, err), flush=True)
                continue
            cap, sec = got
            rows.setdefault(month, []).append([cap[l] for l in LEVELS])
            for name in SECTORS:
                sd = sec.get(name, {})
                if all(l in sd for l in LEVELS):
                    srows[name].setdefault(month, []).append(
                        [sd[l] for l in LEVELS])
            if n % 30 == 0:
                print("   %d of %d done" % (n, len(jobs)), flush=True)

    out = {}
    sout = {}
    for m in sorted(rows):
        a = np.asarray(rows[m], float)
        out[m] = {"n": int(a.shape[0]),
                  "mean": a.mean(axis=0).tolist(),
                  "sigma": a.std(axis=0, ddof=1).tolist()}
        print("   %-10s %2d years   the 10 hPa mean %10.1f  sigma %8.1f"
              % (MONTH_NAMES[m - 1], a.shape[0], out[m]["mean"][0],
                 out[m]["sigma"][0]), flush=True)
        for name in SECTORS:
            b = srows[name].get(m)
            if not b or len(b) < 2:
                continue
            b = np.asarray(b, float)
            sout.setdefault(name, {})[m] = {
                "n": int(b.shape[0]),
                "mean": b.mean(axis=0).tolist(),
                "sigma": b.std(axis=0, ddof=1).tolist()}

    np.savez_compressed(
        OUT,
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
    print("   -> %s" % OUT)


if __name__ == "__main__":
    main()
