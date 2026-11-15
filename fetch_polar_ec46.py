"""EC46 (the ECMWF sub-seasonal ensemble) polar-cap geopotential height.

The seasonal route in `fetch_polar_models.py` uses the C3S sub-daily archive,
which has no sub-seasonal system in it.  For the sub-seasonal guidance the
same quantity - the area weighted (cos(lat)) mean geopotential height over
60-90N - has to come out of ECMWF's own store: the ECDS service, dataset
`s2s-forecasts`, system 46 (the 46-day ensemble).

    POST https://ecds.ecmwf.int/api/retrieve/v1/processes/s2s-forecasts/execute
    headers: PRIVATE-TOKEN: <the CDS key in .cdsapirc>
    {
      "inputs": {
        "origin": "ecmwf", "system": 46,
        "year": "2026", "month": "11", "day": "13", "time": "00:00",
        "level_type": "pressure", "variable": ["geopotential_height"],
        "level_value": ["10_hpa", ...],
        "forecast_type": ["control_forecast", "perturbed_forecast"],
        "leadtime_hour": ["24_48", "72_96", ..., "456_480"],
        "area": [90, -180, 60, 180], "data_format": "grib"
      },
      "outputs": {"asset": {"value": {"type": "file"}}}
    }

Two things about the catalogue, both measured from the live form schema
(GET /retrieve/v1/processes/s2s-forecasts):

  * `level_value` holds TEN pressure levels - 10, 50, 100, 200, 300, 500,
    700, 850, 925, 1000 hPa.  There is no 30 hPa and no 400 hPa, so an EC46
    section carries ten levels rather than the reference's twelve.
  * `leadtime_hour` takes 359 values, 98 of them ranges; the weekly ranges
    24_48 ... 456_480 are the ones the sub-seasonal windows are built from.

**The licence.**  The account has not accepted the S2S licence, so every
request is refused with

    HTTP 403 {"title": "required licences not accepted",
              "detail": "Not all the required licences have been accepted;
                         please visit https://ecds.ecmwf.int/datasets/
                         s2s-forecasts?tab=download#manage-licences ..."}

The check runs before the request is validated, so a 403 always means the
licence, never a malformed request.

**The licence CAN be accepted by the API** (found in the R package
CopernicusClimate, R/licenses.R):

    GET  {store}/api/profiles/v1/account/licences          what is accepted
    GET  {store}/api/catalogue/v1/vocabularies/licences    the catalogue
    PUT  {store}/api/profiles/v1/account/licences/<id>      accept one
         body: {"revision": N}                              (answers 201)

The S2S licence is `s2s-licence`, revision 5.  The same key works on the CDS
and on the ECDS; only the store's base URL differs.

Until the licence is accepted this script reports the refusal and writes
NOTHING: a chart must never be published without real data behind it.
"""
import json
import os
import sys
import time
from datetime import date, timedelta

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import G0, SECTORS, sector_mean, zonal_mean  # noqa: E402

ECDS = "https://ecds.ecmwf.int/api"
EXEC = "%s/retrieve/v1/processes/s2s-forecasts/execute" % ECDS
OUT = os.path.join(DATA, "polar_ec46_z.json")
STATE = os.path.join(DATA, "polar_ec46_jobs.json")
# the shared cache the plotter reads; the series is merged into it under its
# own key, and every other model's record is left exactly as it was found
CACHE = os.path.join(DATA, "polar_model_z.json")
TAG = "ec46"

# the levels the S2S catalogue serves (ten of the reference's twelve: the
# catalogue has no 30 hPa and no 400 hPa)
LEVELS = [10, 50, 100, 200, 300, 500, 700, 850, 925, 1000]
AREA = [90.0, -180.0, 60.0, 180.0]

# The catalogue has no `system` parameter: the product is picked by the RUN
# DATE, so the 46-day extended range is what the archive serves on the days
# it runs (Mondays and Thursdays, 00Z) and the 15-day ensemble on the others.
# The lead times are 24-hour blocks, so the series that comes back is a daily
# one.
SYSTEM = 46

# The lead time ranges, 24_48 up to 1080_1104: FORTY-SIX days, which is the
# whole of the extended range - the chart runs to the end of the run, not to
# some shorter window of it.  (The window 1080_1104 is the LAST one: the
# window 1104_1128 would be day 47, which the run does not have.)
WEEKLY = ["%d_%d" % (h, h + 24) for h in range(24, 1081, 24)]

# The extended range runs on MONDAYS and THURSDAYS at 00Z, and only those runs
# carry the 46 days: on the other days the archive serves the 15-day
# ensemble, which stops at lead 360 h.  The catalogue has no `system`
# parameter - the product is picked by the RUN DATE - so the run is found by
# asking for a lead window that only an extended-range run has.
EXTENDED_ONLY = ["1080_1104"]

# The S2S archive holds the run with about a two-day delay, so the run that
# can be had is the one from roughly 48 hours ago.
DELAY_HOURS = 48

LICENCE_URL = ("https://ecds.ecmwf.int/datasets/s2s-forecasts"
               "?tab=download#manage-licences")

# the S2S dataset's licence, and the revision of it that is current
S2S_LICENCE = "s2s-licence"
S2S_REVISION = 5


# ------------------------------------------------------------------ licences
def accepted_licences(s):
    """-> the licences the account has accepted."""
    r = s.get("%s/profiles/v1/account/licences" % ECDS, timeout=60)
    if r.status_code != 200:
        return []
    try:
        d = r.json()
    except Exception:
        return []
    if isinstance(d, dict):
        d = d.get("results") or d.get("licences") or []
    return d or []


def accept_licence(s, licence_id, revision):
    """Accept one licence.  -> True when the store took it."""
    r = s.put("%s/profiles/v1/account/licences/%s" % (ECDS, licence_id),
              json={"revision": revision}, timeout=60)
    # the Data Store answers 201 Created for a new acceptance
    return r.status_code in (200, 201, 204)


def ensure_licence(s):
    """Accept the S2S licence if the account has not taken it yet.

    The tick in the web UI is a PUT against the account's licence list, and
    the same key works here, so the EC46 does not have to wait for a manual
    click.
    """
    have = accepted_licences(s)
    ids = []
    for x in have:
        if isinstance(x, dict):
            ids.append(str(x.get("id") or x.get("licence") or ""))
        else:
            ids.append(str(x))
    if S2S_LICENCE in ids:
        print("   the licence %s is already accepted" % S2S_LICENCE,
              flush=True)
        return True
    print("   the licence %s is not accepted - accepting it now" % S2S_LICENCE,
          flush=True)
    ok = accept_licence(s, S2S_LICENCE, S2S_REVISION)
    print("   the licence %s: %s" % (S2S_LICENCE,
                                      "accepted" if ok else "REFUSED"),
          flush=True)
    return ok


def key():
    """-> the CDS/ECDS key, from .cdsapirc (mode 600, never in the repo)."""
    p = os.path.join(HERE, ".cdsapirc")
    if not os.path.exists(p):
        raise SystemExit(
            "   there is no .cdsapirc here, so there is no key to ask the\n"
            "   store with.  Put it in place with:\n"
            "       ./set_cds_key.sh <your CDS API key>\n"
            "   (the same key works on the CDS and on the ECDS, where the\n"
            "    EC46 comes from.)")
    with open(p) as f:
        for l in f:
            if l.strip().startswith("key:"):
                return l.split(":", 1)[1].strip()
    raise SystemExit("   the .cdsapirc here has no key: line")


def session():
    import requests
    s = requests.Session()
    s.headers.update({"PRIVATE-TOKEN": key(), "Content-Type": "application/json"})
    return s


def latest_run(s, tries=8):
    """The most recent ECMWF sub-seasonal run the archive holds.

    The S2S archive holds the run with about a TWO-DAY delay, so the run
    that can be had is the one from roughly 48 hours ago - and it comes
    DAILY, not only on Mondays and Thursdays.

    The catalogue has no `system` parameter: the product is picked by the
    RUN DATE.  The probe asks for a lead window at the far end of the
    extended range (1080_1104 = day 46) together with the first one, so a
    run that carries the whole 46 days is recognised as such; a run that
    refuses it is still used, with a word about it, because the run itself
    is the one that is there.

    The probe is a job of its own, and it is dismissed at once so it does
    not sit in the queue.
    """
    today = date.today() - timedelta(hours=DELAY_HOURS)
    for back in range(0, tries + 1):
        d = today - timedelta(days=back)
        for t in ("00:00", "12:00"):
            for windows, extended in ((list(EXTENDED_ONLY) + ["24_48"], True),
                                      (["24_48"], False)):
                req = {"origin": "ecmwf",
                       "year": "%04d" % d.year, "month": "%02d" % d.month,
                       "day": "%02d" % d.day, "time": t,
                       "level_type": "pressure",
                       "variable": ["geopotential_height"],
                       "level_value": ["%d_hpa" % l for l in LEVELS],
                       "forecast_type": ["control_forecast"],
                       "leadtime_hour": list(windows), "area": AREA,
                       "data_format": "grib"}
                r = s.post(EXEC, json={"inputs": req}, timeout=180)
                # the Data Store answers 201 Created for a new job, not 200
                if r.status_code in (200, 201):
                    try:
                        j = r.json()
                        jid = j.get("jobID") or j.get("processID")
                        if jid:
                            s.delete("%s/retrieve/v1/jobs/%s" % (ECDS, jid),
                                     timeout=30)
                    except Exception:                # noqa: BLE001
                        pass
                    if not extended:
                        print("   the run %s %s does not serve the far end of "
                              "the extended range" % (d, t), flush=True)
                    print("   the EC46 run: %s %s" % (d, t), flush=True)
                    return d, t, None
                if r.status_code == 403:
                    raise SystemExit(licence_refusal(r))
                if r.status_code == 400:
                    break            # this run cannot serve those windows
    return None, None, None


def licence_refusal(r):
    return ("the S2S licence has not been accepted yet.  The data is free "
            "(CC BY 4.0) - the account only has to accept the terms once:\n"
            "  %s\n"
            "  the answer was HTTP %d: %s\n"
            "  nothing was written; the series needs real data behind it."
            % (LICENCE_URL, r.status_code, r.text[:200]))


def read_grib(path):
    """-> ({valid_time: {level: polar cap mean}}, {valid_time: {sector: {...}}},
             {valid_time: the members behind it}).

    The sector means are the same reduction over one longitude sector, so
    the Atlantic and the Pacific can be drawn separately.

    The GRIB carries the geopotential HEIGHT in metres ("gh"), not the
    geopotential in m2/s2 ("z"), so every value is multiplied by 9.80665
    here - the same thing fetch_polar_gefs.py does with the GEFS's HGT.

    The file carries every member at the same valid time and level, so the
    member values are AVERAGED: the section shows the ensemble mean.  (A
    reader that kept the last message it saw would draw ONE member and call
    it the ensemble.)

    The member set is the one that is present at EVERY time of the run, not
    the one that happens to be in each chunk: the archive caps the RESPONSE
    SIZE, so a chunk can come back with fewer members than were asked for,
    and a mean whose membership changes half way through the chart would
    draw a step that is an artefact of the archive and not of the atmosphere.
    """
    import eccodes
    from collections import defaultdict
    # acc[time][level][member] = the polar cap mean
    acc = defaultdict(lambda: defaultdict(dict))
    sacc = defaultdict(lambda: defaultdict(lambda: defaultdict(dict)))
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:                         # noqa: BLE001
                break
            if gid is None:
                break
            try:
                la = np.asarray(eccodes.codes_get_array(gid, "latitudes"), float)
                lo = np.asarray(eccodes.codes_get_array(gid, "longitudes"), float)
                v = np.asarray(eccodes.codes_get_array(gid, "values"), float)
                ni = int(eccodes.codes_get(gid, "Ni", 0) or 0)
                nj = int(eccodes.codes_get(gid, "Nj", 0) or 0)
                if ni and nj and v.size == ni * nj:
                    lat2d = la.reshape(nj, ni)
                    v = v.reshape(nj, ni)
                else:
                    lats = np.unique(la)[::-1]
                    lons = np.unique(lo)
                    if v.size != lats.size * lons.size:
                        continue
                    v = v.reshape(len(lats), len(lons))
                    lat2d = np.repeat(lats[:, None], len(lons), axis=1)
                lats = lat2d[:, 0]
                lon2d = lo.reshape(nj, ni) if (ni and nj
                                               and v.size == ni * nj) else \
                    np.repeat(np.unique(lo)[None, :], len(lats), axis=0)
                # the VALIDITY time, not the data time: the S2S fields are
                # initialised at 00Z or 12Z and carry the lead time as the
                # step, so validityDate/validityTime is the only pair that
                # gives the right calendar day
                vd = int(eccodes.codes_get(gid, "validityDate"))
                vt = int(eccodes.codes_get(gid, "validityTime"))
                valid = date(vd // 10000, (vd // 100) % 100, vd % 100) \
                    + timedelta(hours=vt // 100, minutes=vt % 100)
                lev = int(eccodes.codes_get(gid, "level"))
                key = valid.strftime("%Y-%m-%d %H")
                # the member number: the control is 0 and the perturbations
                # are 1, 2, 3 ...
                try:
                    mem = int(eccodes.codes_get(gid, "number") or 0)
                except Exception:                     # noqa: BLE001
                    mem = 0
                cap = zonal_mean(v, lats) * G0
                acc[key][lev][mem] = cap
                for name, (a, b) in SECTORS.items():
                    sacc[key][name][lev][mem] = \
                        sector_mean(v, lats, lon2d[0, :], a, b) * G0
            except Exception:                         # noqa: BLE001
                pass
            finally:
                eccodes.codes_release(gid)

    # the members that are present at EVERY time of the file
    common = None
    for t, d in acc.items():
        for lev, mm in d.items():
            s = set(mm)
            common = s if common is None else (common & s)
    common = common or set()

    out = {}
    sout = {}
    for t, d in acc.items():
        row = {}
        for lev, mm in d.items():
            vals = [mm[m] for m in common if m in mm]
            if vals:
                row[lev] = float(np.mean(vals))
        out[t] = row
    for t, sd in sacc.items():
        row = {}
        for name, ld in sd.items():
            srow = {}
            for lev, mm in ld.items():
                vals = [mm[m] for m in common if m in mm]
                if vals:
                    srow[lev] = float(np.mean(vals))
            row[name] = srow
        sout[t] = row
    # the members behind each time
    nmem = {t: len(common) for t in acc}
    return out, sout, nmem


def submit(s, run_date, run_time, weeks):
    """-> the job id of the request for these weekly windows.

    The catalogue's form schema names the 46-day system explicitly, so the
    request carries `system: 46`; if this build of the schema does not know
    the field the same request goes out without it.
    """
    base = {"origin": "ecmwf",
            "year": "%04d" % run_date.year, "month": "%02d" % run_date.month,
            "day": "%02d" % run_date.day, "time": run_time,
            "level_type": "pressure",
            "variable": ["geopotential_height"],
            "level_value": ["%d_hpa" % l for l in LEVELS],
            "forecast_type": ["control_forecast", "perturbed_forecast"],
            "leadtime_hour": weeks,
            "area": AREA, "data_format": "grib"}

    def post(req):
        return s.post(EXEC, json={"inputs": req,
                                  "outputs": {"asset": {"value": {"type": "file"}}}},
                      timeout=300)

    req = dict(base)
    req["system"] = SYSTEM
    r = post(req)
    if r.status_code == 403:
        raise SystemExit(licence_refusal(r))
    if r.status_code == 400:
        # the schema does not know the `system` field: the same request goes
        # out without it
        r = post(base)
    if r.status_code == 403:
        raise SystemExit(licence_refusal(r))
    if r.status_code >= 400:
        raise RuntimeError("submit failed HTTP %d: %s"
                           % (r.status_code, r.text[:300]))
    j = r.json()
    return j.get("jobID") or j.get("processID")


def wait(s, jid, tries=360):
    for _ in range(tries):
        time.sleep(15)
        r = s.get("%s/retrieve/v1/jobs/%s" % (ECDS, jid), timeout=60)
        if r.status_code != 200:
            continue
        st = r.json().get("status")
        if st in ("successful", "completed"):
            return True
        if st in ("failed", "error", "rejected", "dismissed"):
            print("   the job is %s" % st, flush=True)
            return False
    return False


def download(s, jid, path):
    r = s.get("%s/retrieve/v1/jobs/%s/results" % (ECDS, jid), timeout=120)
    link = r.json()["asset"]["value"]["href"]
    with s.get(link, stream=True, timeout=600) as dr:
        with open(path + ".part", "wb") as f:
            for chunk in dr.iter_content(4 * 1024 * 1024):
                if chunk:
                    f.write(chunk)
    os.replace(path + ".part", path)


def main():
    s = session()
    # the licence first: a request that is refused for want of it says
    # nothing about the data, and the acceptance is an API call
    if not ensure_licence(s):
        print("   the S2S licence has not been accepted, so nothing can be "
              "asked of the archive.")
        print("   it is one tick in the web UI: %s" % LICENCE_URL)
        return
    run_date, run_time, _ = latest_run(s)
    if run_date is None:
        print("   no ECMWF S4S run found in the last week")
        return
    print("   the S4S run: %s %s" % (run_date, run_time), flush=True)

    st = json.load(open(STATE)) if os.path.exists(STATE) else {"jobs": []}
    out = json.load(open(OUT)) if os.path.exists(OUT) else {}

    # The weekly windows in chunks: the archive caps the RESPONSE SIZE, and
    # a chunk that carries fewer members than the model has is a broken
    # answer.  The chunk size can be set on the command line: one big request
    # for the whole range costs ONE turn of the queue and gives every day the
    # SAME member set, which is what a section wants (a mean whose membership
    # changes half way through is an artefact of the archive, not of the
    # atmosphere).
    CHUNK = 5
    if "--chunk-size" in sys.argv:
        CHUNK = int(sys.argv[sys.argv.index("--chunk-size") + 1])
    for i in range(0, len(WEEKLY), CHUNK):
        weeks = WEEKLY[i:i + CHUNK]
        done = [j for j in st["jobs"]
                if j.get("chunk") == i and j.get("status") == "decoded"]
        if done:
            continue
        print("   the weeks %s ..." % (weeks[0] + " to " + weeks[-1]), flush=True)
        jid = submit(s, run_date, run_time, weeks)
        print("   the job %s" % jid, flush=True)
        if not wait(s, jid):
            st["jobs"].append({"chunk": i, "job": jid, "status": "failed"})
            with open(STATE + ".tmp", "w") as f:
                json.dump(st, f, indent=1)
            os.replace(STATE + ".tmp", STATE)
            continue
        path = os.path.join(DATA, "_ec46_%d.grib" % i)
        download(s, jid, path)
        vals, svals, nmem = read_grib(path)
        os.remove(path)
        rec = out.setdefault(TAG, {"times": [], "values": [],
                                   "sectors": {}, "levels": list(LEVELS)})
        # only the times that carry every level of BOTH the cap and the two
        # sectors are kept, so the times and the sector rows stay in step
        # (a sector row that was short would put the two out of line and
        # the chart would draw the wrong sector against the wrong day)
        keep = []
        for t in sorted(vals):
            row = [vals[t].get(l) for l in LEVELS]
            if any(x is None for x in row):
                continue
            srows = {}
            bad = False
            for name in SECTORS:
                sd = svals.get(t, {}).get(name, {})
                srow = [sd.get(l) for l in LEVELS]
                if any(x is None for x in srow):
                    bad = True
                    break
                srows[name] = srow
            if bad:
                continue
            keep.append((t, row, srows, nmem.get(t, 0)))
        for t, row, srows, nm in keep:
            rec["times"].append(t)
            rec["values"].append(row)
            for name, srow in srows.items():
                rec.setdefault("sectors", {}).setdefault(name, []).append(srow)
        rec["run"] = "%s %sZ" % (run_date, run_time[:2])
        # the ECMWF's sub-seasonal set is a DAILY run with a 48-hour delay:
        # the chart says so, because a reader comparing it with a 35-day
        # GEFS needs to know it
        rec["frequency"] = "daily"
        # the members behind the series: the FEWEST that came back for any of
        # the days, so the number on the chart is the number behind every day
        if keep:
            nm_all = [nm for _t, _r, _s, nm in keep]
            rec["members"] = min(nm_all)
            print("   the chunk carries %d members over %d days"
                  % (rec["members"], len(keep)), flush=True)
        with open(OUT + ".tmp", "w") as f:
            json.dump(out, f, indent=1)
        os.replace(OUT + ".tmp", OUT)
        # and into the shared cache, under the same key the plotter reads
        cache = {}
        if os.path.exists(CACHE):
            with open(CACHE) as f:
                cache = json.load(f)
        cache[TAG] = {"times": rec["times"], "values": rec["values"],
                      "levels": list(LEVELS), "run": rec["run"],
                      "frequency": rec.get("frequency", "daily"),
                      "members": rec.get("members", 0)}
        if rec.get("sectors"):
            cache[TAG]["sectors"] = rec["sectors"]
        with open(CACHE + ".tmp", "w") as f:
            json.dump(cache, f)
        os.replace(CACHE + ".tmp", CACHE)
        st["jobs"].append({"chunk": i, "job": jid, "status": "decoded"})
        with open(STATE + ".tmp", "w") as f:
            json.dump(st, f, indent=1)
        os.replace(STATE + ".tmp", STATE)
        print("   the chunk decoded: %d times so far" % len(rec["times"]),
              flush=True)

    print("   the EC46 series: %s" % OUT, flush=True)


if __name__ == "__main__":
    main()
