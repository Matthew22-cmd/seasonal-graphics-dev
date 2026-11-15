"""Cross-check for the GEFS v12 series: our ensemble mean against NCEP's own.

`fetch_polar_gefs.py` computes the ensemble mean from the member files.
NCEP publishes the same mean as `geavg.*`.  This pulls the `geavg` file for
one lead and the twelve levels, reduces it the same way, and prints the two
side by side.

The comparison that matters is with the member set the chart uses: NCEP's
own `geavg` is the mean over the FULL ensemble (the control and thirty
perturbed members), while the chart runs on the 24 members that are present
at every one of the 35 days.  The difference between the two is the size of
the sampling noise, and it is printed in standard deviations of the polar
cap's own day-to-day spread - the number that says whether the 24-member
mean is a fair stand-in for the 31-member one.

    python3 verify_polar_gefs.py
"""
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

import fetch_polar_gefs as f  # noqa: E402
from polar_cap import LEVELS, read_grib_levels  # noqa: E402


def ours(lead):
    """-> our own ensemble mean at this lead, from the series cache."""
    p = os.path.join(DATA, "polar_model_z.json")
    if not os.path.exists(p):
        return None, None
    rec = json.load(open(p)).get(f.TAG)
    if not rec:
        return None, None
    times = rec.get("times") or []
    for k, t in enumerate(times):
        if abs((int(t[:4]) * 372 + int(t[5:7]) * 31 + int(t[8:10]))
               - (int(str(lead)) // 24 + 2026 * 372)) < 3:
            return rec["values"][k], rec.get("members")
    # fall back on the first lead
    return (rec["values"][0] if rec.get("values") else None), rec.get("members")


def main():
    f.HOSTS = f.live_hosts()
    date, hour = f.find_cycle()
    f.DATE, f.HOUR = date, hour
    lead = 12
    parts = {}
    for part in ("a", "b"):
        base = "atmos/%sgeavg.t00z.pgrb2%s.0p50.f%03d" % (f.PARTS[part], part,
                                                           lead)
        try:
            msgs = f.read_idx(base + ".idx")
        except Exception as e:                         # noqa: BLE001
            print("   the geavg %s half is not there: %s" % (part, e))
            continue
        size = f.head_size(base)
        alloff = sorted(set(x[0] for x in msgs))
        blob = b""
        for lev in LEVELS:
            if f.PART_OF[lev] != part:
                continue
            hit = [o for o, v, l in msgs if v == "HGT" and l == "%d mb" % lev]
            if not hit:
                print("   the geavg %s half has no %d hPa" % (part, lev))
                continue
            off = hit[0]
            nxt = [o for o in alloff if o > off]
            end = nxt[0] if nxt else size
            r = f.get_first(base, headers={"Range": "bytes=%d-%d" % (off, end - 1)})
            blob += r.content
        parts[part] = blob
    if not parts:
        print("   NCEP's ensemble mean is not published for this lead")
        return
    tmp = os.path.join(DATA, "_gefs_geavg.grib2")
    with open(tmp, "wb") as fp:
        for part in sorted(parts):
            fp.write(parts[part])
    row, srow, t = f.read_cap_mean(tmp)
    os.remove(tmp)
    if not row:
        print("   NCEP's own ensemble mean could not be read")
        return

    print("   the cycle: %s %sZ, the lead f%03d (%s)" % (date, hour, lead, t))
    print("   NCEP's own ensemble mean (the control and 30 members):")
    print("      " + "  ".join("%d:%.0f" % (l, row.get(l, float("nan")))
                               for l in LEVELS))

    mine, nmem = ours(lead)
    if mine is None:
        print("   our own series is not in the cache yet")
        return
    print("   ours (the %s members the chart uses):" % nmem)
    print("      " + "  ".join("%d:%.0f" % (l, v) for l, v in zip(LEVELS, mine)))
    diff = [row.get(l, float("nan")) - v for l, v in zip(LEVELS, mine)]
    print("   the difference:")
    print("      " + "  ".join("%d:%+.0f" % (l, v) for l, v in zip(LEVELS, diff)))

    # how big is that, against the polar cap's own day-to-day spread?
    try:
        from polar_cap import load_clim_native, daily_climate
        nat = load_clim_native()
        if nat:
            months, clevs, cmean, csig = nat[0]
            j = clevs.index(10)
            mm, ms = daily_climate([t], months, cmean[:, [j]], csig[:, [j]])
            sig = float(ms[0][0])
            print("   the daily sigma of the polar cap at 10 hPa: %.0f m2/s2" % sig)
            print("   the difference at 10 hPa: %+.0f m2/s2 = %+.3f sigma"
                  % (diff[0], diff[0] / sig))
    except Exception as e:                            # noqa: BLE001
        print("   the sigma could not be worked out: %s" % str(e)[:80])


if __name__ == "__main__":
    main()
