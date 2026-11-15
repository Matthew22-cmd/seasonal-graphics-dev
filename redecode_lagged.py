"""Rebuild the lagged daily u10 series from the store's job results.

The series that the daily wind charts are drawn from was assembled by
merging the decoded chunks of each centre's pull.  The merge wrote the
whole row of every chunk, so at each chunk boundary the chunk's empty
cells (NaN) landed on top of the accumulator's good values: the series
came out with holes, and the number of members on a day fell from 155 to
55 and back.  The chart then jumped because the ensemble mean was taken
over a different member set on different days.

Nothing is re-requested here: the archive no longer serves the BoM's
October inits (MarsNoDataError), but the CDS still holds every job
result, and each one is downloaded, decoded and merged with the fixed
merge (fetch_lagged_u10.merge writes only the cells that hold a value).
"""
import argparse
import json
import os
import shutil
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch_lagged_u10 import (CENTRES, DATASET, MDIR, RUN_DAYS, build_matrix,
                              ensemble_layout, merge, read_lagged_u10,
                              record_daily_members, trim_to_run)
from u10_daily import save_npz

# The jobs of the last complete pull, in the order they were run.  The
# three centres each had one group for the 2026-10 inits (split into
# chunks) and one job for the 2026-11 inits.
JOBS = {
    "ukmo-gloseas6": [
        ("0bcb919b-ca70-4645-add1-2dec634abb98", "2026-10 chunk 0"),
        ("c1ff68c7-094b-49cd-a443-ddee4e06f8ed", "2026-10 chunk 1"),
        ("7eb6e9cc-1782-4fc8-9617-9be4441e3701", "2026-11"),
    ],
    "jma-jra3": [
        ("4cc2f58a-707e-4797-b22f-3fd6adb5529c", "2026-10 chunk 0"),
        ("e4c59c2e-6eaf-4f0d-a34e-ca13ca6fe8a1", "2026-10 chunk 1"),
        ("3191bea4-91dd-4010-8e45-3fb3ebe627fd", "2026-10 chunk 2"),
        ("a3487dea-2f4c-46d9-999d-251671f35442", "2026-11"),
    ],
    "bom-access-s2": [
        ("e55efcae-8ecf-47af-a7fe-fca2baea71ca", "2026-10 chunk 0"),
        ("f29bded1-940b-4395-8661-ca1b895a0da2", "2026-10 chunk 1"),
        ("85b5fe16-7f91-4292-b4a1-3691637e6154", "2026-10 chunk 2"),
        ("17523b34-47fd-42e3-a3e9-b0a568e1bd98", "2026-11"),
    ],
}

STATE = os.path.join(MDIR, "_lagged_redecode_state.json")


def load_state():
    try:
        with open(STATE) as f:
            return json.load(f)
    except Exception:
        return {}


def save_state(st):
    tmp = STATE + ".%d" % os.getpid()
    with open(tmp, "w") as f:
        json.dump(st, f, indent=1)
    os.replace(tmp, STATE)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default=",".join(JOBS))
    ap.add_argument("--keep-grib", action="store_true")
    args = ap.parse_args()
    import cds_direct
    cds = cds_direct.CDSDirect()
    state = load_state()

    for tag in [t for t in args.tag.split(",") if t]:
        lay = ensemble_layout(tag)
        if not lay:
            print("%s: no monthly u10 pull on disk" % tag, flush=True)
            continue
        days, numbering, nmem = lay
        counts = sorted({len(numbering[d]) for d in days})
        npz = os.path.join(MDIR, tag, "u10_daily.npz")
        st = state.setdefault(tag, {})
        print("\n%s: %d members on %d start days" % (tag, nmem, len(days)),
              flush=True)

        acc = [None, None, None, None]
        for jid, what in JOBS[tag]:
            if st.get(jid) == "done" and not args.keep_grib:
                print("   %s (%s): already merged" % (what, jid[:8]), flush=True)
                continue
            gpath = os.path.join(MDIR, tag, "_redecode_%s.grib" % jid[:8])
            print("   %s (%s): fetching the result" % (what, jid[:8]), flush=True)
            try:
                cds.download_job(jid, gpath)
            except Exception as e:
                print("      the result is not there: %s" % str(e)[:200],
                      flush=True)
                continue
            mb = os.path.getsize(gpath) / 1e6
            try:
                recs, members = read_lagged_u10(gpath, numbering)
                d2, a2, b2, per_day = build_matrix(recs, members)
            finally:
                if not args.keep_grib and os.path.exists(gpath):
                    os.remove(gpath)
            print("      %.0f MB, %d records, %d members, %d dates (%s .. %s)"
                  % (mb, len(recs), len(members), len(d2),
                     d2[0] if d2 else "-", d2[-1] if d2 else "-"), flush=True)
            if not members:
                continue
            if acc[0] is None:
                acc = [d2, a2, b2, members]
            else:
                acc = merge(acc, (d2, a2, b2, members))
            st[jid] = "done"
            save_state(state)

        if not acc[0]:
            print("   nothing was merged", flush=True)
            continue
        init_date = max(days)
        trimmed, per_day = trim_to_run(acc, init_date, RUN_DAYS.get(tag, 215))
        d, a, b, mem = trimmed
        if not d:
            d, a, b, mem = acc
        centre, system = CENTRES[tag]
        save_npz(npz, d, a, b, mem,
                 meta=dict(tag=tag, centre=centre, system=system,
                           init="%04d-%02d" % init_of(tag),
                           lagged=True, start_days=len(days),
                           members_per_start_day=counts,
                           members=len(mem), days=len(d),
                           members_per_day=sorted(set(per_day.values()))
                           if per_day else [],
                           source=DATASET))
        record_daily_members(tag, len(mem))
        print("   %s: %d members x %d days (%s .. %s), %d members on every day"
              % (tag, len(mem), len(d), d[0], d[-1],
                 min(per_day.values()) if per_day else 0), flush=True)
        save_state(state)


def init_of(tag):
    from fetch_lagged_u10 import init_of as _f
    return _f(tag)


if __name__ == "__main__":
    main()
