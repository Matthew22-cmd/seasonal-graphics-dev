"""Export the seasonal snowfall fields for the interactive maps.

The maps page paints the snowfall on the world, so the browser needs the
field itself - not a picture of it.  This script reads the same monthly
snowfall GRIBs the panels are drawn from, with the same readers and the
same unit arithmetic (metres of water equivalent per second, accumulated
over the month and turned into inches of snow depth with the 10:1 ratio),
and writes one JSON per model for the browser:

    docs/data/snowmap_<tag>.json

The grid is a plain 1 degree box over the eastern United States, which is
what the panels show; the browser turns each cell into a rectangle and
projects it with the map's own projection, so the field lands on the flat
map, on the globe and on the polar projection identically.
"""
import os, sys, json
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
MDIR = os.path.join(DATA, "models")
OUT = os.path.join(HERE, "docs", "data")

# the box the panels cover, with a little margin so the field does not
# look cropped when it is painted on the globe
LAT0, LAT1 = 21.0, 52.0
LON0, LON1 = -129.0, -61.0
STEP = 1.0

# the models whose own panels are not published (they are pooled)
POOLED_INTO = {"eccc-canesm5": "eccc-cansips", "eccc-gem5": "eccc-cansips"}


def main():
    import plot_snow_models as PSM
    from plot_snow_ref import MONTH_NAMES
    from plot_snow_totals import boost_saturation, month_len

    os.makedirs(OUT, exist_ok=True)
    state_p = os.path.join(DATA, "models_fetched.json")
    state = json.load(open(state_p)) if os.path.exists(state_p) else {}

    lats = np.arange(LAT1, LAT0 - 0.01, -STEP)          # descending
    lons = np.arange(LON0, LON1 + 0.01, STEP)           # ascending
    LAT, LON = np.meshgrid(lats, lons)
    target_lat, target_lon = LAT.ravel(), LON.ravel()

    # the fixed colour ladder: the 0-300 in snow-depth scale the panels
    # use, so the maps and the panels are read the same way
    d = json.load(open(os.path.join(DATA, "snow_depth_scale.json")))
    # the scale file is stored from the top of the bar down; the browser
    # wants it ascending, with the colours in the same order
    levels = list(reversed(list(d["levels"])))
    colors = list(reversed(list(boost_saturation(list(d["colors"])))))
    colors[0] = "#ffffff"          # zero snowfall is white

    # a finer ramp for the map: the same ladder, interpolated, so the
    # field reads as a smooth field at world scale.  The legend keeps
    # the published ladder.
    RAMP = 48
    ramp = []
    for k in range(RAMP):
        u = k * (len(colors) - 1) / float(RAMP - 1)
        i0 = int(u)
        i1 = min(i0 + 1, len(colors) - 1)
        f = u - i0
        a = colors[i0].lstrip("#")
        b = colors[i1].lstrip("#")
        ca = [int(a[0:2], 16), int(a[2:4], 16), int(a[4:6], 16)]
        cb = [int(b[0:2], 16), int(b[2:4], 16), int(b[4:6], 16)]
        mix = "".join("%02x" % int(round(ca[t] + (cb[t] - ca[t]) * f))
                      for t in range(3))
        ramp.append("#" + mix)

    def to_lat_major(flat):
        """the flat field runs lon-major here (a column of lats for each
        lon); the browser walks it lat-major (a row of lons for each
        lat), so it is transposed on the way out."""
        return np.asarray(flat).reshape(len(lons), len(lats)).T.ravel().tolist()

    summary = []
    for tag, meta in sorted(state.items()):
        if tag in POOLED_INTO:
            continue
        d = os.path.join(MDIR, tag)
        fg = os.path.join(d, "snowfall_monthly.grib")
        cg = os.path.join(d, "snowfall_hindcast.grib")
        if not os.path.exists(fg):
            fg = os.path.join(d, "snowfall_monthly.npz")
        if not os.path.exists(fg):
            print("skip %s (no snowfall)" % tag)
            continue
        by_step = PSM.read_snowfall(fg)
        if not by_step:
            print("skip %s (unreadable)" % tag)
            continue
        ext = {}
        xp = os.path.join(d, "snowfall_ext.npz")
        if os.path.exists(xp):
            try:
                ext = PSM.read_extended(xp)
            except Exception as e:
                print("  %s: no extended months (%s)" % (tag, e))

        yms = [ym for ym in sorted(by_step) if PSM.month_end(ym) < PSM.SNOW_END]
        ext_yms = [ym for ym in sorted(ext)
                   if ym not in yms and PSM.month_end(ym) < PSM.SNOW_END
                   and (not ext[ym][3] or ext[ym][3] >= 20)]
        yms = yms + ext_yms
        if not yms:
            print("skip %s (nothing before the end)" % tag)
            continue

        lats0, lons0, order = PSM.grid_axes(by_step[yms[0]][0])
        monthly = []
        labels = []
        for ym in yms:
            y, m = ym
            if ym in ext_yms:
                la, lo, v, nd = ext[ym]
                ens = PSM.interp_to(target_lat, target_lon, la, lo, v)
                field = ens * 1000.0 / 25.4 * PSM.SNOW_RATIO
            else:
                recs = by_step[ym]
                stack = np.array([PSM.to_2d(r, lats0, lons0, order)
                                  for r in recs])
                ens = stack.mean(axis=0)
                days = month_len(y, m)
                mm = PSM.interp_to(target_lat, target_lon, lats0, lons0, ens)
                field = (mm * days * 86400.0 * 1000.0 / 25.4
                         * PSM.SNOW_RATIO)
            monthly.append(np.round(field, 2).tolist())
            labels.append("%s %d" % (MONTH_NAMES[m - 1], y))
        total = np.round(np.sum(np.array(monthly), axis=0), 2).tolist()

        init = meta.get("init") or ""
        out = {
            "tag": tag,
            "name": meta.get("name", tag),
            "init": init,
            "members": len(by_step[yms[0]]),
            # the browser walks the rows from the north down, so lat0 is
            # the northern edge of the grid
            "grid": {"lat0": float(LAT1), "dlat": float(STEP),
                     "nlat": int(len(lats)), "lon0": float(LON0),
                     "dlon": float(STEP), "nlon": int(len(lons))},
            "levels": levels,
            "colors": colors,
            "ramp": ramp,
            "months": [{"ym": "%04d-%02d" % ym, "label": lab}
                       for ym, lab in zip(yms, labels)],
            "fields": [to_lat_major(f) for f in monthly],
            "total": to_lat_major(total),
        }
        path = os.path.join(OUT, "snowmap_%s.json" % tag)
        with open(path, "w") as f:
            json.dump(out, f)
        size = os.path.getsize(path) / 1024.0
        print("  %-16s %d months, %.0f kB" % (tag, len(yms), size))
        summary.append(tag)

    # the list the maps page reads to build its model picker
    index = []
    for tag in summary:
        meta = state.get(tag, {})
        index.append({"tag": tag, "name": meta.get("name", tag),
                      "init": meta.get("init", "")})
    with open(os.path.join(OUT, "snowmap_tags.json"), "w") as f:
        json.dump(index, f)
    with open(os.path.join(DATA, "snowmap_tags.json"), "w") as f:
        json.dump(summary, f)
    print("exported %d models" % len(summary))


if __name__ == "__main__":
    main()
