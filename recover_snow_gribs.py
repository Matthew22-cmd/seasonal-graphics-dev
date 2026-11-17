"""Recover the seasonal snowfall GRIBs from the CDS's stored job results,
and work out which result belongs to which centre.

The panels were drawn from monthly snowfall pulls in early November, but
this sandbox does not hold the GRIBs any more (they are gitignored
working files).  The CDS keeps a job's result long after the archive
drops the data, so the original pulls can be recovered without any new
queue time.

A successful job's record does not say what it asked for, so each result
is opened and read: the member count, the lead months, the grid and the
init identify the centre (the ECMWF's SEAS5 has 51 members on a 1 degree
grid, the DWD's GCFS2.2 has 16 on a 0.5 degree grid, and so on).  The
same request re-run lands on the same object, so the results are
de-duplicated by their asset before anything is downloaded.

    python3 recover_snow_gribs.py
"""
import os, re, sys, json, time
import requests

HERE = os.path.dirname(os.path.abspath(__file__))
MDIR = os.path.join(HERE, "data", "models")
API = "https://cds.climate.copernicus.eu/api"
DATASET = "seasonal-monthly-single-levels"

# centre -> (the member count, the grid in degrees) from the published
# C3S description, used to identify a recovered file
EXPECT = {
    "ecmwf-seas5":     (51, 1.0),
    "ukmo-gloseas6":   (60, 1.0),
    "eccc-canesm5":    (20, 1.0),
    "eccc-gem5":       (20, 1.0),
    "cmcc-sps4":       (20, 1.0),
    "dwd-gcfs2":       (16, 0.5),
    "meteo-france-s9": (32, 0.25),
}


def session():
    key = re.search(r"key:\s*(\S+)", open(os.path.join(HERE, ".cdsapirc")).read()).group(1)
    s = requests.Session()
    s.headers.update({"PRIVATE-TOKEN": key})
    return s


def grib_param(path):
    """The GRIB's parameter name (sf = the seasonal snowfall)."""
    import eccodes
    with open(path, "rb") as f:
        try:
            gid = eccodes.codes_grib_new_from_file(f)
        except Exception:
            return None
        if gid is None:
            return None
        try:
            return eccodes.codes_get(gid, "shortName")
        finally:
            eccodes.codes_release(gid)


def grib_facts(path):
    """-> (members, the lead months, the grid, the init date)."""
    import eccodes
    members, steps, lats, lons = set(), set(), set(), set()
    init = None
    with open(path, "rb") as f:
        while True:
            try:
                gid = eccodes.codes_grib_new_from_file(f)
            except Exception:
                break
            if gid is None:
                break
            try:
                members.add(int(eccodes.codes_get(gid, "number")))
                steps.add(int(eccodes.codes_get(gid, "step")))
                lats.add(float(eccodes.codes_get(gid, "latitudeOfFirstGridPointInDegrees")))
                lats.add(float(eccodes.codes_get(gid, "latitudeOfLastGridPointInDegrees")))
                lons.add(float(eccodes.codes_get(gid, "longitudeOfFirstGridPointInDegrees")))
                lons.add(float(eccodes.codes_get(gid, "longitudeOfLastGridPointInDegrees")))
                if init is None:
                    init = eccodes.codes_get(gid, "dataDate")
            except Exception:
                pass
            eccodes.codes_release(gid)
    grid = None
    if len(lats) > 1 and len(lons) > 1:
        grid = [round(abs(sorted(lats)[-1] - sorted(lats)[0]), 3),
                round(abs(sorted(lons)[-1] - sorted(lons)[0]), 3)]
    return {"members": len(members), "steps": sorted(steps),
            "grid": grid, "init": init}


def main():
    S = session()
    r = S.get(API + "/retrieve/v1/jobs?limit=2000", timeout=180)
    jobs = sorted(r.json().get("jobs", []), key=lambda j: j.get("created", ""))
    sel = [j for j in jobs if j.get("status") == "successful"
           and j.get("processID") == DATASET
           and j.get("created", "") >= "2026-11-01"]

    # one entry per distinct stored file
    seen = {}
    for j in sel:
        asset = ((j.get("metadata", {}).get("results", {}) or {}).get("asset", {}) or {}).get("value", {}) or {}
        href = asset.get("href")
        size = asset.get("file:size") or 0
        if not href or href in seen:
            continue
        seen[href] = (j.get("jobID"), size, j.get("created"))
    print("the distinct stored results: %d" % len(seen))

    tmp = os.path.join(HERE, "data", "_snow_recover")
    os.makedirs(tmp, exist_ok=True)
    facts = []
    for href, (jid, size, created) in sorted(seen.items(), key=lambda kv: kv[1][2]):
        if size < 3e5:
            print("  %s  %.0f MB  (too small - a probe)" % (created[5:19], size / 1e6))
            continue
        out = os.path.join(tmp, jid + ".grib")
        if not os.path.exists(out):
            print("  %s  %.0f MB  downloading" % (created[5:19], size / 1e6), flush=True)
            try:
                dr = S.get(href, timeout=3600)
                if dr.status_code >= 400:
                    print("    HTTP %d" % dr.status_code)
                    continue
                with open(out + ".part", "wb") as f:
                    f.write(dr.content)
                os.rename(out + ".part", out)
            except Exception as e:
                print("    failed: %s" % str(e)[:90])
                continue
        try:
            fa = grib_facts(out)
            fa["param"] = grib_param(out)
        except Exception as e:
            print("    unreadable: %s" % str(e)[:90])
            continue
        lead_months = sorted(set(round(s / 720.0) for s in fa["steps"]))
        print("    %s: the param %s, %d members, the grid %s, the init %s, the lead months %s"
              % (jid[:8], fa["param"], fa["members"], fa["grid"], fa["init"], lead_months))
        fa.update({"job": jid, "path": out, "created": created, "lead_months": lead_months})
        facts.append(fa)

    with open(os.path.join(HERE, "data", "snow_recover_facts.json"), "w") as f:
        json.dump(facts, f, indent=1)
    print("the facts are in data/snow_recover_facts.json")


if __name__ == "__main__":
    main()
