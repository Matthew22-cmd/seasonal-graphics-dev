"""Re-decode the model's own far-end climate from the jobs already in the store.

**Why this is needed.**  The first version of `fetch_polar_model_clim7.py`
kept ONE day per lead month, and the monthly product publishes a month's
MEAN.  The difference is not small: the polar cap warms by about 4,700
m2/s2 between the 5th and the 29th of April, and the monthly product says
299,082.5 for the April lead month where the single day said 296,625.6.

The GRIBs are deleted once they are decoded, but the jobs' results stay in
the store, so the days can be fetched again and averaged properly - with no
new queue time and no new requests.

    python3 redecode_polar_model_clim7.py
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from fetch_polar_model_clim7 import (STATE, build, lead_hours)  # noqa: E402


def main():
    import cds_direct
    cds = cds_direct.CDSDirect()
    hs, tag = lead_hours()
    st = json.load(open(STATE)) if os.path.exists(STATE) else {"jobs": []}
    changed = 0

    for job in st["jobs"]:
        jid = job.get("job")
        if not jid:
            continue
        status = job.get("status")
        if status in ("submitted", "accepted", "running"):
            # the job may have finished while the worker was stopped
            s = cds.job_status(jid)
            print("   the job %s is %s" % (str(jid)[:8], s), flush=True)
            if s not in ("successful", "completed"):
                continue
        path = os.path.join(DATA, "_redecode_%s.grib" % job["init"])
        try:
            cds.download_job(jid, path)
        except Exception as e:                            # noqa: BLE001
            print("   the result of %s could not be fetched: %s"
                  % (str(jid)[:8], str(e)[:150]), flush=True)
            continue
        rec = build(path, tag)
        os.remove(path)
        if not rec:
            print("   %s: the GRIB holds no complete lead month" % job["init"],
                  flush=True)
            continue
        job["status"] = "done"
        job["leads"] = sorted(rec.keys())
        job["values"] = rec
        changed += 1
        for lead in sorted(rec):
            print("   %s: lead month %s, %d day(s), the 10 hPa cap mean %10.1f"
                  % (job["init"], lead, rec[lead].get("days", 0),
                     rec[lead]["cap"]["10"]), flush=True)

    with open(STATE + ".tmp", "w") as f:
        json.dump(st, f, indent=1)
    os.replace(STATE + ".tmp", STATE)
    print("   %d init(s) re-decoded" % changed, flush=True)

    # the mean over the inits is rebuilt from the state file
    import fetch_polar_model_clim7 as F
    F.write_mean(st)


if __name__ == "__main__":
    main()
