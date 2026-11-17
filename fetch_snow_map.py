"""Re-pull the monthly seasonal snowfall for the maps.

The panels were drawn from monthly snowfall pulls in November, but this
sandbox no longer holds the GRIBs, and the CDS purged those job results
from its store.  So the fields are pulled again - the same request the
panels were built from, so the numbers are the same numbers.

One request at a time: the account's queue takes a couple of jobs and a
burst of submissions is simply rejected.

    python3 fetch_snow_map.py [--only ecmwf-seas5,...]
"""
import os, re, sys, json, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
MDIR = os.path.join(HERE, "data", "models")
API = "https://cds.climate.copernicus.eu/api"
DATASET = "seasonal-monthly-single-levels"

# the same order and the same requests as the panels were built from
CENTRES = [
    ("ecmwf-seas5",     "ecmwf",         "51",  6),
    ("ukmo-gloseas6",   "ukmo",          "610", 6),
    ("eccc-canesm5",    "eccc",          "4",   6),
    ("eccc-gem5",       "eccc",          "5",   6),
    ("cmcc-sps4",       "cmcc",          "4",   6),
    ("dwd-gcfs2",       "dwd",           "22",  6),
    ("meteo-france-s9", "meteo_france",  "9",   6),
]
YEAR, MONTH = "2026", "11"


def session():
    key = re.search(r"key:\s*(\S+)", open(os.path.join(HERE, ".cdsapirc")).read()).group(1)
    s = requests.Session()
    s.headers.update({"PRIVATE-TOKEN": key})
    return s


def retrieve(S, req, out, tries=5):
    for attempt in range(tries):
        try:
            r = S.post("%s/retrieve/v1/processes/%s/execute" % (API, DATASET),
                       json={"inputs": req}, timeout=240)
        except Exception as e:
            print("      http error: %s" % str(e)[:110], flush=True)
            time.sleep(25)
            continue
        if r.status_code in (400, 422):
            txt = r.text
            if "Maximum number queued" in txt:
                print("      the queue is full - pausing 120s", flush=True)
                time.sleep(120)
                continue
            print("      rejected: %s" % txt[:200], flush=True)
            return False
        if r.status_code not in (200, 201):
            print("      HTTP %d: %s" % (r.status_code, r.text[:120]), flush=True)
            time.sleep(25)
            continue
        jid = r.json().get("jobID")
        print("      the job %s" % jid[:8], flush=True)
        t0 = time.time()
        while time.time() - t0 < 21600:
            time.sleep(15)
            try:
                st = S.get(API + "/retrieve/v1/jobs/" + jid, timeout=90).json().get("status")
            except Exception:
                continue
            if st == "successful":
                try:
                    link = S.get(API + "/retrieve/v1/jobs/%s/results" % jid,
                                 timeout=180).json()["asset"]["value"]["href"]
                except Exception:
                    print("      no result link", flush=True)
                    return False
                dr = S.get(link, timeout=3600)
                if dr.status_code >= 400:
                    print("      download HTTP %d" % dr.status_code, flush=True)
                    time.sleep(20)
                    continue
                with open(out + ".part", "wb") as f:
                    f.write(dr.content)
                os.rename(out + ".part", out)
                print("      done: %.0f MB" % (len(dr.content) / 1e6), flush=True)
                return True
            if st in ("rejected", "failed"):
                try:
                    tb = (S.get(API + "/retrieve/v1/jobs/" + jid, timeout=90).json()
                          .get("metadata", {}).get("results", {}).get("traceback", "") or "")
                except Exception:
                    tb = ""
                if "Maximum number queued" in tb:
                    print("      the queue is full - pausing 120s", flush=True)
                    time.sleep(120)
                    break
                print("      %s: %s" % (st, tb[-160:]), flush=True)
                return False
        else:
            print("      timed out", flush=True)
            return False
    return False


def main():
    only = []
    for a in sys.argv[1:]:
        if a.startswith("--only="):
            only = [x for x in a.split("=", 1)[1].split(",") if x]
    S = session()
    for tag, centre, system, leads in CENTRES:
        if only and tag not in only:
            continue
        d = os.path.join(MDIR, tag)
        os.makedirs(d, exist_ok=True)
        out = os.path.join(d, "snowfall_monthly.grib")
        if os.path.exists(out) and os.path.getsize(out) > 1e6:
            print("== %s already there" % tag, flush=True)
            continue
        print("== %s (%s:%s) %s-%s" % (tag, centre, system, YEAR, MONTH), flush=True)
        req = {"originating_centre": centre, "system": system,
               "variable": "snowfall", "product_type": "monthly_mean",
               "year": YEAR, "month": MONTH,
               "leadtime_month": [str(k) for k in range(1, leads + 1)],
               "data_format": "grib"}
        if not retrieve(S, req, out):
            print("   FAILED", flush=True)
        time.sleep(5)


if __name__ == "__main__":
    main()
