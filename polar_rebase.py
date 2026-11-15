"""Put a seasonal model's forecast on the same scale as the reanalysis.

**The problem.**  The polar-cap section draws two halves: the reanalysis
(NOAA's CORe) on the left of the dashed line and the model's own run on the
right.  Both are measured against the OBSERVED climate - the CORe 1991-2020
climatology - so that the two halves can be read against each other.

That works for a short run and it does not work for a seasonal one.  A
seasonal model's mean state is not the observed climate:

    the ECMWF SEAS5's own climate minus the CORe climate, 10 hPa, cap mean
        Nov -641     Dec -809     Jan -311     Feb -1,627
        Mar -1,654   Apr -2,908   May -5,300   Jun -4,941   m2/s2

so the far end of the SEAS5's section was drawn as -2 to -4 sigma of a cold
stratosphere when it is really the model sitting below the observed climate.
The June sigma of the observed climate is only 429 m2/s2 (631 on the day),
so the offset was amplified fourfold by the denominator.

**The fix is the convention the rest of the site already uses.**  The snow
maps are "vs this model's own hindcast climate", and the SPV chart draws
the model's own climate as a line beside the forecast.  So the forecast is
measured against the model's OWN climate and added back to the observed one:

    plotted = observed_climate + (model - model_clim)

The reanalysis half is untouched (it is the observed climate against
itself), the model's mean-state offset is removed from the forecast, and the
two halves still meet at the dashed line.

**Where the model's own climate comes from.**

  * Lead months 1-6 (November to April) - the C3S seasonal product publishes
    it: `seasonal-monthly-pressure-levels` with
    `product_type: hindcast_climate_mean`, the same product_type the
    snowfall anomaly charts use for "this model's own hindcast climate".
  * Lead months 7-8 (May, June) - the monthly product caps at lead month 6
    and the daily one stops at 215 days, so the far end comes from the
    model's own PAST November inits (the daily product serves historical
    inits), exactly as the SPV chart's month-7 climate was built.
  * One month before the chart's first day (October) - the observed climate
    is interpolated onto the days from the monthly means, and the first
    half of November leans on the October mean.  Without it the two halves
    would not meet at the dashed line.

**The interpolation is the same one the observed climate uses**, so the
model's climate and the observed climate land on the day in the same way:
the monthly means are anchored at the middle of each month and interpolated
onto the days, which keeps the forecast from stepping at every month
boundary.
"""
import datetime as dt
import json
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
sys.path.insert(0, HERE)

from polar_cap import daily_climate  # noqa: E402

# the chart's own init: lead months 1-6
CLIM_MAIN = os.path.join(DATA, "polar_model_clim.json")
# the month before the chart's first day: the anchor for the interpolation
CLIM_OCT = os.path.join(DATA, "polar_model_clim_oct.json")
# the model's own past runs: lead months 7-8 (May, June)
CLIM_FAR = os.path.join(DATA, "polar_model_clim7.json")

# The months whose value does NOT stand for the whole month.  The daily
# product stops at 215 days from the init, which is the 3rd of June, so the
# model's own climate for lead month 8 is the mean of 1 and 3 June and it
# stands for those days - there is nothing after them to interpolate
# towards, so it is anchored on the 1st of June and held flat afterwards.
ANCHOR_DAY = {8: 1}


def _lead_to_month(init_month, lead):
    """The calendar month a lead month of an init covers."""
    return ((init_month - 1 + lead - 1) % 12) + 1


def _read(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return None


def model_clim_calendar(verbose=True):
    """The model's own climate, by CALENDAR month.

    -> {month: {"cap": {level: value},
                "sectors": {sector: {level: value}}}}, or None.

    The chart's own init wins for the months it covers; the October init
    supplies the anchor for the first days of the chart, and the model's own
    past November inits supply the far end.
    """
    main = _read(CLIM_MAIN)
    if not main:
        return None
    init_month = int(str(main.get("init", "2026-11"))[5:7])
    out = {}

    # 1. the month before the chart's first day - the anchor for the
    #    interpolation over the first half of November
    oct_ = _read(CLIM_OCT)
    if oct_:
        omonth = int(str(oct_.get("init", "2026-10"))[5:7])
        for k, rec in (oct_.get("leads") or {}).items():
            m = _lead_to_month(omonth, int(k))
            if m in out:
                continue
            out[m] = {"cap": dict(rec.get("cap") or {}),
                      "sectors": {n: dict(v)
                                  for n, v in (rec.get("sectors") or {}).items()}}

    # 2. the chart's own init - leads 1 to 6 (November to April)
    for k, rec in (main.get("leads") or {}).items():
        m = _lead_to_month(init_month, int(k))
        out[m] = {"cap": dict(rec.get("cap") or {}),
                  "sectors": {n: dict(v)
                              for n, v in (rec.get("sectors") or {}).items()}}

    # 3. the model's own past runs - leads 7 and 8 (May, June).  Their
    #    lead 6 is the same season and lead as the chart's own April, so it
    #    is a check on the pull rather than a second value for April.
    far = _read(CLIM_FAR)
    if far:
        for k, rec in (far.get("leads") or {}).items():
            k = int(k)
            m = _lead_to_month(init_month, k)
            if m in out:
                if verbose and m == _lead_to_month(init_month, 6):
                    a = out[m]["cap"].get("10")
                    b = rec.get("cap", {}).get("10")
                    if a is not None and b is not None:
                        print("   the model's own climate for %s: the monthly "
                              "product says %10.1f, the past runs say %10.1f "
                              "(%+.1f m2/s2)" % (m, a, b, b - a))
                continue
            out[m] = {"cap": dict(rec.get("cap") or {}),
                      "sectors": {n: dict(v)
                                  for n, v in (rec.get("sectors") or {}).items()}}
    return out or None


def _monthly_bias(model_clim, obs_mean, obs_months, levels, get):
    """The model's bias against the observed climate, month by month.

    model_clim: {month: {"cap": {...}, "sectors": {...}}}
    obs_mean:   {month: array(nlev)} the observed climate's monthly means
    obs_months: the calendar months obs_mean is keyed by
    levels:     the levels of the chart
    get:        "cap" or the name of a sector

    -> {month: array(nlev)} or None
    """
    obs = {int(m): np.asarray(v, float) for m, v in obs_months.items()}
    out = {}
    for m, rec in model_clim.items():
        if get == "cap":
            vals = rec.get("cap") or {}
        else:
            vals = (rec.get("sectors") or {}).get(get) or {}
        if not vals or m not in obs:
            continue
        o = obs[m]
        if len(o) != len(levels):
            continue
        row = np.array([float(vals.get(str(l), np.nan))
                        for l in levels], float)
        if not np.all(np.isfinite(row)):
            continue
        out[int(m)] = row - o
    return out or None


def model_clim_on_days(days, monthly, init, anchor_day=None):
    """The model's own climate, put on the days.

    The monthly values are anchored the way the OBSERVED climate is
    anchored - at the middle of the month - and interpolated onto the days
    between the anchors, so the model's curve and the observed curve can be
    compared day by day.

    Two departures from that rule:

    * the month before the model's init is anchored as well, because the
      observed climate's interpolation over the first half of November
      leans on its October mean and the model's has to lean on the same
      one, or the two halves of the chart do not meet at the dashed line;
    * a month whose value stands for the first days of the month - the
      model's own climate for June is the mean of 1 and 3 June, because
      the daily product stops at 215 days, which is the 3rd of June - is
      anchored on those days and held flat afterwards, because there is
      nothing after them to interpolate towards.

    monthly:    {month: array(nlev)} the model's own climate, month by month
    init:       the model's init, "2026-11-01"
    anchor_day: {month: day} the anchor of the months that do not sit in
                the middle of the month

    -> (n, nlev)
    """
    if not monthly:
        return None
    nlev = len(next(iter(monthly.values())))
    y0, m0 = int(str(init)[:4]), int(str(init)[5:7])
    # the cycle of anchored months: the month before the init, then the
    # init's own month onwards for as many months as the model covers
    pm = m0 - 1
    py = y0 if pm >= 1 else y0 - 1
    pts = []
    for k in range(-1, 13):
        m = ((m0 - 1 + k) % 12) + 1
        if k < 0:
            y = py
        else:
            y = y0 + (1 if m < m0 else 0)
        if m not in monthly:
            continue
        day = (anchor_day or {}).get(m)
        if day is None:
            nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
            ndays = (nxt - dt.date(y, m, 1)).days
            day = 1 + (ndays + 1) // 2
        pts.append((dt.date(y, m, int(day)).toordinal(), monthly[m]))
    if not pts:
        return None
    pts.sort(key=lambda p: p[0])
    xs = np.array([p[0] for p in pts], float)
    ys = np.array([p[1] for p in pts], float)

    out = np.empty((len(days), nlev), float)
    for i, d in enumerate(days):
        o = dt.datetime.strptime(d[:10], "%Y-%m-%d").date().toordinal()
        # the days before the first anchor and after the last one take the
        # nearest value: the curve is not extrapolated past what it knows
        if o <= xs[0]:
            out[i] = ys[0]
            continue
        if o >= xs[-1]:
            out[i] = ys[-1]
            continue
        for k in range(nlev):
            out[i, k] = np.interp(o, xs, ys[:, k])
    return out


def _init_digits(init):
    """The init date of a climate file as eight digits, or None."""
    s = "".join(ch for ch in str(init) if ch.isdigit())
    return s[:8] if len(s) >= 8 else None


def climate_matches(run):
    """Is this the model's OWN climate - the one for this chart's init?

    The model climate on disk belongs to ONE model and ONE init.  A chart of
    another model - the GEFS, say - must not be re-based with it, because
    the correction is that model's own bias and nobody else's.

    -> True, False, or None when the chart does not say which run it is
    """
    main = _read(CLIM_MAIN)
    if not main:
        return False
    want = _init_digits(main.get("init", ""))
    if not run:
        return None
    got = _init_digits(run)
    if not got:
        return None
    return got == want


def correction(days, levels, obs_mean, obs_months, sector=None,
               mode="forecast", run=None):
    """The correction the plotted values need, and a note for the reader.

    The correction is the difference between the model's own climate and
    the observed climate, both put on the days.  It is the difference of the
    two CURVES and not the difference of the two monthly means, because the
    two curves are anchored differently: the observed climate is anchored at
    the middle of every month, while the model's own June - the mean of 1
    and 3 June, because the daily product stops at 215 days - stands for
    the first days of June.

    obs_mean:   {month: array(nlev)} the observed climate's monthly means -
                the cap's own, or a sector's.
    obs_months: the calendar months the observed climate is anchored at.
    sector:     the sector's name, for a sector chart.
    mode: "forecast" - only the forecast half is measured against the
          model's own climate, so the reanalysis half keeps its own
          reference.
          "both"    - both halves are measured against the model's own
          climate, so the forecast starts exactly where the analysis ends.
    run:    the chart's own run, so the correction is only used for the
            model the climate belongs to.

    -> (corr (n, nlev), note) or None
    """
    if climate_matches(run) is False:
        return None, None
    mc = model_clim_calendar()
    if not mc:
        return None, None
    obs = {int(m): np.asarray(v, float) for m, v in obs_mean.items()}
    # the model's own climate, month by month
    monthly = {}
    for m, rec in mc.items():
        vals = (rec.get("cap") if sector is None
                else (rec.get("sectors") or {}).get(sector)) or {}
        if not vals:
            continue
        row = np.array([float(vals.get(str(l), np.nan)) for l in levels], float)
        if not np.all(np.isfinite(row)):
            continue
        monthly[int(m)] = row
    if not monthly:
        return None, None

    # the model's curve on the days
    main = _read(CLIM_MAIN) or {}
    init = str(main.get("init", "2026-11-01"))
    # the anchor of the months that do not stand for the whole month: the
    # lead month is turned into the calendar month of this init
    m0 = int(init[5:7])
    anchor = {}
    for lead, day in ANCHOR_DAY.items():
        anchor[((m0 - 1 + lead - 1) % 12) + 1] = day
    mcurve = model_clim_on_days(days, monthly, init, anchor_day=anchor)
    if mcurve is None:
        return None, None
    # the observed curve on the days: the same interpolation the chart's
    # own normalisation uses, so the two are on one scale
    omean = np.array([obs[m] for m in sorted(obs)], float)
    ocurve = daily_climate(days, list(sorted(obs)), omean)
    corr = mcurve - ocurve
    note = ("the forecast vs the model's own climate" if mode == "forecast"
            else "both halves vs the model's own climate")
    return corr, note
