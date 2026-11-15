"""Do the JMA and the BoM publish snowfall at all?

The site has no snow chart for them.  This asks the store for one month of
the monthly snowfall for each and prints what comes back, so the answer to
"is there snowfall for the JMA and the BoM" is measured and not guessed.
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cds_direct  # noqa: E402

DATASET = "seasonal-monthly-single-levels"
TARGETS = [("jma-jra3", "jma", "4"), ("bom-access-s2", "bom", "2"),
           ("ukmo-gloseas6", "ukmo", "610")]

cds = cds_direct.CDSDirect()
for tag, centre, system in TARGETS:
    req = {"originating_centre": centre, "system": system,
           "variable": "snowfall", "year": "2026", "month": "10",
           "leadtime_month": "1", "area": [60, -180, 30, 180],
           "data_format": "grib"}
    print(">> %s (%s system %s)" % (tag, centre, system), flush=True)
    try:
        jid = cds.submit(DATASET, req)
    except Exception as e:                              # noqa: BLE001
        print("   the request was refused: %s" % str(e)[:300], flush=True)
        continue
    print("   the job %s" % jid, flush=True)
    for _ in range(240):
        s = cds.job_status(jid)
        if s in ("successful", "completed"):
            print("   SUCCESS - the store has snowfall for %s" % tag, flush=True)
            break
        if s in ("failed", "error", "rejected", "dismissed"):
            msg = str(cds.job_message(jid))[:400] if hasattr(cds, "job_message") else ""
            print("   the job ended as %s: %s" % (s, msg), flush=True)
            break
        time.sleep(15)
    else:
        print("   the job did not finish in time", flush=True)
