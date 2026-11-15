# The polar cap time-height section (the 60-90N geopotential height anomaly)

The reference figure is severe-weather.eu's "ECMWF 11 Nov 12z: Polar Cap
(60-90N) Normalized Geopotential Height Anomaly" by Andrej Flis
(/@Recretos).  The section needs three halves: a climatology, an analysis
before the init, and the model's own forecast.

## What the reference actually is (measured pixel by pixel)
- The pressure axis is **LOGARITHMIC**: `y = 109 + log(p/10)/log(100) * 825`
  fits the tick rows to within 0.7 px.  An evenly spaced level axis is wrong.
- The palette is **NOT RdBu**.  It runs blue -> white -> **YELLOW** -> orange
  -> red.  Seventeen colours, sampled out of the reference's own colour bar:
  `#000e4e #00238c #0045b5 #0c6fd3 #359fe8 #6bbef0 #a8daf5 #daeef8
  #ffffff #fff685 #ffff00 #ffb700 #ff7300 #ff3300 #e20000 #ac0202 #6b0000`
  The breaks are the reference's tick values: -5 -4 -3 -2 -1.5 -1 -0.5 -0.2
  0.2 0.5 1 1.5 2 3 4 5.
- The right-hand axis is **LINEAR in altitude**, independent of the
  log-pressure axis: 0, 8, 16, 24, 32 km, each with the miles.
- The section is filled with smooth contours (`contourf`), not blocky cells.
- The layout: centred bold title, centred subtitle, a blue "<- ECMWF
  ANALYSIS" left of the split and a red "ECMWF 15-DAY FORECAST (11 Nov 12z)
  ->" right of it, a red dashed vertical split line, a dashed grey grid, and
  a horizontal colour bar with pointed ends below the panel.

## The climatology: ARCO, not the CDS
The CDS queue is saturated and the ERA5 pressure-level cost limit caps a
request at one year, so the climatology comes from
`https://storage.googleapis.com/gcp-public-data-arco-era5/ar/1959-2022-1h-240x121_equiangular_with_poles_conservative.zarr`
- The 1-hourly store has **all 37 levels**; the 6-hourly stores have only 13
  (no 10 or 30 hPa).  The 1-hourly 240x121 store is the one to use.
- 1991-2020 gives **10,958 days**; the polar cap is 21 latitude rows.
- **The 60N row is stored as 59.999999999999986** - an exact comparison
  silently drops the bottom row of the cap (500 hPa moves by 104 m2/s2 =
  0.2% = 0.1 sigma, and the change is NOT affine, so it does not cancel in
  the normalised anomaly).  Compare with a 1e-6 tolerance.
- The 240x121 grid is **1.5 degrees**, not 0.25.

## The forecast: the IFS open data is the queue-free route
`https://ecmwf-forecasts.s3.amazonaws.com/` - no queue, no cost limit.
- The plain LIST (the bucket root) answers **503**; the query with an
  explicit `?prefix=` is the one that works.
- **A double slash in the path fails 100%** (BUCKET ends in "/" and the
  format string adds another -> every request 404s, and no retry fixes it).
  This cost hours.
- The bucket keeps each cycle's forecast as one GRIB2 per step, with an
  `.index` file beside it listing every message's **byte offset and length**.
  Fetch only the `param: "z"` (geopotential) messages at the wanted levels
  with HTTP **Range** requests: 11 messages = 10 MB, against 96 MB for the
  whole step file.
- The 503s come in bursts and roughly **30-40% of the requests succeed**, so
  the answer is volume, not patience: many quick retries, and the byte
  ranges fetched with 8 threads.
- **The bucket throttles by DURATION as well as by burst**: after a heavy
  fetch it answers nothing for minutes.  A long pause clears it.  Probing it
  repeatedly while a fetch is running makes the throttle WORSE.
- Steps run 0..360 h at 3-hourly = **15 days**.
- The IFS open data does **NOT** carry 30 hPa (its levels are 10, 50, 100,
  150, 200, 250, 300, 400, 500, 600, 700, 850, 925, 1000), so an IFS
  section uses eleven of the reference's twelve levels.  The C3S seasonal
  archive DOES carry 30 hPa.
- The bucket retains every daily cycle for about a month, so the **analysis
  half is the step-0 field of each day's 12Z cycle** - no ERA5 needed.

## The seasonal route: the C3S sub-daily archive  (PROVEN WORKING)
`seasonal-original-pressure-levels` carries `geopotential` at exactly the
reference's twelve levels, with `leadtime_hour` out to 5159 h = **215 days =
the full run**, plus an `area` widget.  There is **no member-selection
parameter** - all the members always come back (SEAS5 gives 51).
- The runs are initialised at **00Z on the 1st**, so the 12Z value of a day
  is at lead time **12 + 24k** hours, not 24k (a 24k lead lands against the
  wrong calendar day in the climatology).
- The archive caps the response size, so the request is chunked: 15 days at
  twelve levels over the polar cap fits; 30 days does not.
- A three-day request (the leads 36, 60, 84) is enough to get through the
  queue when the archive is congested.

## The GRIB reader: read validityDate, not dataDate
`eccodes.codes_get(gid, "dataDate")` returns a STRING ("20261015"), and
`dataTime` comes back as 0 on a fresh handle.  Reading the reference time
plus the step puts every ERA5 field at 00Z and every seasonal field a whole
day out.  Use **`validityDate`/`validityTime`**, which already carry the
reference time plus the step and work for both conventions:
- ERA5: dataTime 1200, step 0 -> validity 12Z
- the seasonal archive: the 00Z init plus the lead time -> validity 12Z
- `eccodes.codes_grib_new_from_file(f)` returns a HANDLE, not a generator:
  iterating over it raises a TypeError.

## The sandbox limits
- **3 GB of memory.**  A 100 MB byte-range buffer plus Python overhead gets
  the process OOM-killed.  Write the ranges straight to a file.
- Detached background processes are reaped when they sit idle.

## The validation that says the method is right
- The normalised anomaly of the ERA5 October against its own 1991-2020
  climatology, year by year, has a **30-year mean of 0.000**.
- The finished IFS section against the reference figure, sampled over the
  plot box: **the correlation of the anomaly field is 0.848** and the
  **sign agreement is 91.1%** (blue / warm / neutral).

## The design is ours, not the reference's

The reference figure (severe-weather.eu / @Recretos) was **measured** to
understand the physics and the geometry.  **None of its graphic design is
used** - the section is our own.

Kept, because it is physics and not decoration:
- the **logarithmic pressure axis** (10 hPa at the top, 1000 hPa at the
  bottom).  A linear axis crushes the stratosphere into a sliver.
- the separate **linear approximate-height axis** on the right.
- smooth `contourf` fills.

Replaced on purpose:
- the reference's 17-colour palette (blue -> white -> bright YELLOW ->
  orange -> red).  Ours is **navy -> white -> orange**, built from the
  colours the site already uses: `C_MEAN #12263f` and `C_ERA5 #c2410c`.
  Nine blues, one white centre, seven warms.
- the reference's **centred** title and subtitle.  Ours is **left aligned**
  with a plain-text summary on the right, the way the snow maps are done.
- the reference's "◄ ECMWF ANALYSIS / FORECAST ►" wording, its colour-bar
  label and its layout.

### The three-level shading
| part | alpha | meaning |
|---|---|---|
| ERA5 reanalysis | 1.00 | what happened |
| the model's own past days | 0.82 | the model's view of days that have passed |
| the model's future | 0.58 | what might happen |

The colour bar is drawn from a clean `ScalarMappable`, never from the last
`contourf` - otherwise it inherits that segment's alpha and looks washed
out.

## The domain map is a REAL map (14 Nov 2026)

The panel beside the two sector sections used to be a schematic: a circle
with two wedges in it, which says where the sectors are in longitude and
nothing else.  The user asked for "an actual map of both sectors", and the
map is now drawn from **Natural Earth's 1:50m land outline**
(`data/ne_50m_land.geojson`, committed to the repo, public domain), so the
reader can see that the North Pacific sector is the one over the Bering Sea
and Chukotka and that the North Atlantic sector is the one over the
Greenland Sea, Iceland and northern Scandinavia.

* the projection is the same azimuthal-equidistant polar projection the
  schematic used: the pole at the centre, Greenwich at the bottom, so the
  Pacific sector sits at the top of the map and the Atlantic sector at the
  bottom - the same arrangement as the panels beside it;
* the land is drawn as a **polygon collection** clipped to the 30N ring, and
  the sector wedges are laid OVER it at 62% opacity, so the geography shows
  through the sectors;
* the longitudes of a coastline ring are **unwrapped** before the
  projection, so a coast that crosses the antimeridian (Chukotka, the
  Aleutians) is drawn the short way round the pole and not straight across
  the middle of the map;
* the labels carry a white halo, because they sit over land now.

The map is drawn by `polar_cap.plot_domain_map()`, which reads the GeoJSON
once and caches it; the file is in the repo so the figure never depends on a
download at build time.

## The scripts
- `polar_cap.py` - the zonal mean, the climatology, the normalisation and
  the drawing routine (shared by every route).
- `fetch_polar_era5_arco.py` - the ERA5 1991-2020 climatology from ARCO.
- `fetch_polar_era5_recent.py` - the 90-day ERA5 reanalysis from the CDS.
- `fetch_polar_models.py` - the seasonal forecast from the C3S archive.
- `fetch_polar_ec46.py` - the EC46 run from ECDS (needs the licence).
- `plot_polar_cap.py` - the section for a seasonal model.
- `tools/polar_queue.sh` - the two fetchers, one after the other.

## What is NOT in scope any more
The IFS 15-day chart and the AIFS ensemble spread were built, validated and
then **removed** at the user's direction: the section is for the SEASONAL
guidance and EC46 only.  A medium-range forecast is a different product and
does not belong here.

## The ARCO native store must NOT be used for the stratosphere (12 Nov 2026)

`ar/full_37-1h-0p25deg-chunk-1.zarr-v3` is ARCO's own vertical interpolation of the
ERA5 pressure levels, not the CDS product. It **mutes the stratospheric variability**:

| event | reduced store | ARCO native store | seasonal model / IFS |
|---|---|---|---|
| Jan 2013 SSW, 14 Jan 2013, 10 hPa | **+2.07 σ** | **−0.17 σ** | agrees with the reduced store |
| Dec 2010 SSW, 4 Dec 2010, 10 hPa | +0.53 σ | −0.9 σ | (a vortex split, weak cap-mean signal) |
| Feb 2019 SSW | −0.4 σ | — | (a vortex split) |

The January 2013 event is the clean test: the reduced store shows the textbook
0 → +2 σ rise over two weeks, the native store flattens it to +0.7 σ and sits 2 σ
too cold. So:

* the **reduced** store (`1959-2022-1h-240x121_equiangular_with_poles_conservative.zarr`)
  is faithful, and its climatology is the right one to normalise against — but it
  **ends in 2022**;
* the **CDS** (`reanalysis-era5-pressure-levels`) is the native product the seasonal
  models and the IFS agree with, so it is the route for both the recent 90 days and
  the climatology (`reanalysis-era5-pressure-levels-monthly-means`);
* `data/polar_cap_clim_native.npz` (the ARCO native climatology) is kept only for
  the record and is **not** used.

The rule that follows: *a climatology must be built from the same product and grid
as the data it normalises* — and here, the same product means the same publisher.

## The sub-seasonal side of the section (13 Nov 2026)

### The chart's colours and its layout

The user asked for the colour family of the reference figure (blue -> white ->
yellow -> orange -> red) but not the reference's design, and then rejected a
first attempt as too muted.  The ramp in `polar_cap.py` is now FULLY SATURATED
in the reference's family: nine blues from a royal blue out to a pale tint, a
white centre, then a bright yellow, gold, orange, vermilion, a vivid red and a
deep red.  The lesson: a dark, desaturated end reads as a hole in the chart and
a dusty warm side makes a strong anomaly look weak - the reference's colours
are electric (its deepest blue is #0000c4 and its brightest red #ea3323) and
that brightness is the point.

The layout is ours: a short figure (13.5 x 7.0 in) with the panel given most
of it, the title and descriptor on the left, the two side labels just above
the panel, the colour bar below it and the handle bottom right.  The first
version was 7.6 in tall with a wide empty band above the panel; the user
called that "too much space".

### GEFSv12 - 16 days is the whole horizon

NOAA publishes the GEFSv12 ensemble to **f384 = 16 days**, and no further.
Verified in the 20261113 00Z run: the 0.5-degree control
(`atmos/pgrb2ap5`) and the perturbations (`atmos/pgrb2bp5`) both stop at
f384, and the 0.25-degree control (`atmos/pgrb2sp25`) stops at f240/f384.
There is **no 35-day GEFSv12 to draw** - the 35-day window the user asked for
is the ECMWF extended run's, not NOAA's.

### EC46 - the licence is the only thing missing

* The ECMWF **open-data bucket carries no extended range**.
  `s3://ecmwf-forecasts` holds `YYYYMMDD/HH/{ifs,aifs-ens,aifs-single}` only;
  the `ec46/` prefix exists but is empty, and the old ENFO stream is gone.
  There is no GCS mirror and the Azure container is not `ecef`.
* The **extended range runs on Mondays and Thursdays at 00Z**, 51 members,
  leg B at ~36 km from day 15 to day 46.
* The ECDS catalogue has exactly three datasets: `s2s-forecasts`,
  `tigge-forecasts`, `s2s-reforecasts`.  The EC46 is `s2s-forecasts` with
  `system: 46`, and it serves **ten levels only** (10, 50, 100, 200, 300, 500,
  700, 850, 925, 1000 hPa - no 30 hPa and no 400 hPa), which is why
  `fetch_polar_ec46.py` asks for those ten and not the chart's twelve.
* The blocker is one click, and the data is free:
  `https://ecds.ecmwf.int/datasets/s2s-forecasts?tab=download#manage-licences`.
  Until it is ticked every POST answers **403 "required licences not
  accepted"**.  The licence check runs BEFORE validation, so a malformed
  request also answers 403 and never 422.

### The ERA5 half

`fetch_polar_era5_recent.py` pulls the CDS `reanalysis-era5-pressure-levels`
for the polar cap, **one request per month** (the CDS shares the day list
across the months in a request, so months of different lengths cannot be
combined), into `data/polar_era5_recent.npz`.  The chart then shows 90 days
of what happened before the run.

### The queue

The account can hold **two running jobs plus a couple more in the "accepted"
state** - the admission gate counts the running ones, so a third submission
is refused ("Maximum number queued requests for this dataset has been
reached").  Jobs that will never be used should be **dismissed** (DELETE
`/retrieve/v1/jobs/<full uuid>`) rather than left to hold the queue: two
worthless UKMO daily chunks were dismissed on 13 Nov to let the ERA5 pull
through.

## THE SCOPE (13 Nov 2026, restated after I drifted)

**What the EC46 is for — and nothing else:**

1. the **polar-cap geopotential height anomaly** section, 60-90N, in metres,
   the same field and the same colours as every other section on the page;
2. **potentially** the same section split into the **North Pacific and the
   North Atlantic** sectors, 60-90N, as we discussed.

**What it is NOT:**

* **no 10 hPa wind panel for the EC46** - the deliverable is the height
  anomaly, not a wind chart (the user corrected this on 13 Nov);
* **no lagged ensemble** for the UKMO/JMA/BoM daily wind - cancelled, and
  those three keep their monthly wind charts;
* **not the ECDS API** - the EC46 comes from the **free and open** route
  (ECMWF's open portal, CC-BY, ~48 h after the run).

**Where the other products stand (13 Nov 2026):**

* the seasonal daily 10 hPa zonal-mean zonal wind is **done and on the
  1 November 2026 init** for CMCC (184 d, 50 members), DWD (181 d, 50),
  ECCC canSIPS (214 d, 40), METFR (212 d, 51) and SEAS5;
* the UKMO, JMA and BoM keep their full-ensemble **monthly** wind charts;
* the sector means (North Pacific 120-240E, North Atlantic 300-60E) come out
  of the same pass over the GRIB as the polar-cap mean, and the sector's own
  1991-2020 climate comes from the CDS 30-year monthly means.

## 15 Nov 2026 - the EC46 as it actually is, and the cold bias on the reanalysis side

### The EC46 is 101 members, a daily run, and its GRIB is in METRES

* **101 members**, not 51.  The run of 2026-11-13 00Z answered with 101
  members at every one of the first five days, and the run is **daily**
  with a **48-hour delay** (so the run available on 15 Nov is the 13 Nov
  one).  The chart's descriptor says so: *"2026-11-13 00Z run - daily -
  101 members"*.
* **The S2S GRIB carries the geopotential HEIGHT in metres ("gh"), not the
  geopotential in m2/s2 ("z").**  The 10 hPa values came out at ~30,250 -
  a number that is a HEIGHT, and the chart's own guard ("the values must
  be a few hundred thousand m2/s2") refused the series.  Every value is
  now multiplied by **9.80665** in `fetch_polar_ec46.read_grib`, exactly as
  `fetch_polar_gefs.py` does with the GEFS's HGT.
* The S2S fields are initialised at 00Z, so **validityDate/validityTime**
  is the pair that gives the calendar day; and the series is one value per
  calendar day (the earliest of the day), so the 00Z runs are kept instead
  of being dropped by a "12Z only" filter.
* The member set is the one present at **every** time of the file, and the
  number on the chart is the **fewest** members behind any of its days.

### The cold bias on the reanalysis side is NOT the atmosphere

Measured on 15 Nov 2026, the polar-cap 10 hPa geopotential height:

| source | value on 13-14 Nov 2026 |
|---|---|
| ARCO native store, the recent 91 days | ~291,000 m2/s2 |
| ARCO native store, its own 1991-2020 climate (November) | 292,148 m2/s2 |
| ARCO reduced store, its daily climate (13 Nov) | 290,880 m2/s2 |
| CDS **monthly means** (November) | 279,958 m2/s2 |
| NOAA GEFSv12, day 1 of its forecast | 295,904 m2/s2 |
| ECMWF EC46, day 1 of its run | 296,663 m2/s2 |

Two things stand out:

1. **The two ARCO stores agree with each other and disagree with both
   models by about 4,500 m2/s2 (450 m) at 10 hPa.**  Day 1 of a forecast
   is the analysis, so the analysis and the models should agree; the
   ERA5-derived numbers are the ones that sit apart.  That is what put the
   deep blue on the left of the section, and it is not an SSW signal.
2. **The CDS's MONTHLY means are 12,000 m2/s2 colder still** and their
   sigma is smaller than anything else (427 m2/s2 in October, where the
   ARCO native store has 710 and the reduced store 930).  They are not the
   reference either.

So the climate the chart is measured against has to come from the **CDS
DAILY** reanalysis - the same product and the same grid as the reanalysis
half, with the real ERA5's spread.  `fetch_polar_clim_cdsdaily.py` builds
it from the 15th of each month of 1991-2020 in **one** request (the CDS
shares the day list across the years), and both the section and the sector
panels prefer it over the ARCO native store's climate.

### The naming

The user asked (15 Nov 2026) that the reanalysis side is not called "the
ERA5 half" - that is a description of its place in the figure, not a name.
It is the **ERA5 reanalysis** on the chart, and it is the **ERA5 analysis**
in the running text.

## 15 Nov 2026 - the ERA5 in ARCO's store is 600 m too low, and it MISSES the SSW

The "excess cold" on the reanalysis side of the section is not the
atmosphere.  Four independent products were put side by side at 10 hPa over
the polar cap, and the ARCO store is the odd one out:

| source | 13-14 Nov 2026 | what it is |
|---|---|---|
| ARCO's ERA5 (the store the chart was using) | ~290,900 m2/s2 | ARCO's own 37-level vertical interpolation |
| ECMWF's IFS analysis (the EC46's **control member**) | 296,661 | the analysis itself |
| NOAA's GEFSv12, day 1 of its forecast | 295,904 | the GFS analysis + 12 h |
| NOAA's **CORe** reanalysis (12 Nov) | 296,902 | a conventional-observation reanalysis |

The difference grows with height and vanishes in the troposphere: +5,170 at
10 hPa, +982 at 100 hPa, +58 at 300 hPa, +20 at 400 hPa.  That is the
signature of a temperature difference of about 7 K in the 100-10 hPa layer,
which is what a wrong vertical interpolation looks like.

### The gap is not a constant - it is a sudden stratospheric warming

The ARCO value and the CORe value were differenced day by day over the
40 days to 13 Nov 2026:

| date | the gap (CORe - ARCO) |
|---|---|
| 5 Oct | +1,053 |
| 17 Oct | +1,385 |
| 25 Oct | +2,115 |
| 29 Oct | +3,403 |
| 1 Nov | +4,891 |
| 4-6 Nov | +6,875 to +7,505 |
| 13 Nov | +5,290 |

The ARCO value keeps falling through late October and early November while
the CORe's **rises** - the polar cap height stops its seasonal decline and
turns up.  That is a sudden stratospheric warming, and **ARCO's ERA5 does
not have it**.  It shows the opposite sign, which is what put the deep blue
on the left of the section.

### What each product is good for

* **NOAA's CORe** - on a public GCS bucket with wgrib2 inventories:
  `https://storage.googleapis.com/noaa-nws-ncep-core/grib/day/pgb/YYYY/MM/pgb.YYYYMMDD`
  with a `.idx` next to it, so the twelve HGT messages the section needs are
  fetched **by byte range** (about 1 MB a day out of a 35 MB file) - no
  queue, no key.  `fetch_polar_core.py` does it.
  **But CORe's historical files cannot carry the climate**: its 15th of
  November reads 289,177 (1991), 291,115 (2005), 288,264 (2015), 289,574
  (2021) and 290,798 (2024) - about 6,000 m2/s2 below its own recent files.
  Its recent stream and its look-alike archive are not the same climate, so
  normalising the recent CORe against a CORe climate gives +4 sigma and a
  chart that is wrong in the other direction.  CORe is a **cross-check**,
  not a replacement.
* **The CDS's native ERA5** is the right product for both halves: the ERA5
  archive *is* the IFS analysis, so it must agree with the EC46's control
  member.  The monthly means file in this repo (`polar_cap_clim_monthly.npz`)
  is 4% low in the stratosphere and is not to be trusted; the climate is
  rebuilt from the CDS **daily** product by `fetch_polar_clim_cdsdaily.py`
  (one request: the CDS shares the day list across the years).
* **The ARCO stores** - both the native and the reduced one - are ARCO's own
  interpolation, and both are low in the stratosphere.  Neither may be used
  for the section.

### A correction, if the CDS stays in the queue

The ARCO-to-truth offset is measured (40 days x 12 levels against the CORe
above) and is smooth in height.  Correcting the ARCO data and the ARCO
climate by that measured per-level offset is a proper calibration, and it
keeps the two halves of the section on one scale.  It is the fallback if the
CDS request does not come through.

### The fourth opinion: NCEP's Reanalysis 1, through PSL's subset service

PSL serves R1 through a NetCDF subset service, so the 1991-2020 record
comes down without a queue and without a key:

    https://psl.noaa.gov/thredds/ncss/grid/Datasets/ncep.reanalysis/Dailies/pressure/hgt.YYYY.nc
    ?var=hgt&north=90&west=0&east=357.5&south=60&horizStride=1
    &time_start=YYYY-11-15T00:00:00Z&time_end=YYYY-11-15T23:59:59Z
    &level=10&30&50&100&200&300&400&500&700&850&925&1000&accept=netcdf

(`fetch_polar_clim_r1.py` does it, thirty requests, the 15th of each month
of each year.)  The NCSS takes **one** time range per request - a comma
separated list of ranges is refused - and the R1 daily files stop on
17 March 2026, so R1 can be the climate but never the reanalysis.  The
NCEP/DOE Reanalysis II stops on 28 February 2026 as well.

R1's 1991-2020 climate and the ARCO native climate, November, 10 hPa:

| | the 10 hPa mean | the sigma |
|---|---|---|
| R1 | 291,583 m2/s2 | 1,444 |
| the ARCO native store | 292,148 | 2,112 |
| the CORe's look-alike archive | 290,490 | 1,682 |

and they agree at **every** level to within about 500 m2/s2 (at 30 hPa
they agree to 1).  So the reanalysis archives agree with each other, and
the three forecast products - the ECMWF's own IFS analysis, NOAA's GEFSv12
and NOAA's CORe - agree with each other about 5,000 m2/s2 above them at
10 hPa.  The ERA5 archive and the IFS analysis are the same model, so
that gap is either the archives' vertical interpolation or the forecast
products' level, and the CDS's native ERA5 will say which.

The **sigma** is the other half of the story.  The ARCO native store's
October sigma at 10 hPa is 710 m2/s2 where R1's is 740 - the same - but in
November the ARCO's is 2,112 against R1's 1,444.  A muted sigma makes an
anomaly too big, and the deep blue on the left of the section was mostly
the **missing stratospheric warming**, not the sigma: the ARCO value keeps
falling through late October while the CORe's turns up.

### The ARCO values in the section were also mislabelled

`fetch_polar_era5_recent.py` asked the CDS for the **first** days of a
month and labelled the answer with the **last** days of the window: a
window that starts on the 17th asked for the 1st to the 7th and called it
the 17th to the 23rd.  The day list is now the window's own days, and the
tail of the window is asked for in chunks, because a request for days the
archive does not have yet (the reanalysis lags by a few days) fails whole.

### The section now runs on NOAA's CORe (the FV3-GFS reanalysis)

The reanalysis half of the section is **CORe** - NOAA CPC's Conventional
Observation Reanalysis, which is built on the FV3-GFS model - and it is
both the data and the climate, so the two halves of every chart are
measured against one system.

CORe is free and **queue-free**.  The daily files are at

    https://storage.googleapis.com/noaa-nws-ncep-core/grib/day/pgb/YYYY/MM/pgb.YYYYMMDD.grb

with a sibling `.idx` (the wgrib2 inventory), so only the twelve HGT
messages are fetched, by byte range - about 1 MB a day out of a 35 MB file.
CPC's own tree is at

    https://ftp.cpc.ncep.noaa.gov/CORe/CDAS_clone_temporary/

and it is the **same system**: the clone's 1991-11-15 12Z gives 289,812
m2/s2 at 10 hPa where the bucket's daily mean for that day gives 289,177
(the difference is the daily mean against the 12Z value).  So the bucket's
history and its recent files are one product, and the climate built from
the bucket's daily files is the right climate for the bucket's recent
files.  The clone's tree goes back to 1950 and has 6-hourly pgb files;
the bucket's daily files are the ones used here.

**The CORe's scale and the models agree.**  On 13 November 2026 at 10 hPa:
the CORe 296,257; the EC46's control member (the IFS analysis) 296,661;
the GEFSv12 day 1 295,904; the ARCO-store ERA5 290,966.  The CORe's
1991-2020 November mean is 290,490 with a sigma of 1,682, so the recent
state is about +3.4 sigma and the models sit at +3.6 sigma - the two
halves of the chart agree to within 0.2 sigma, and the late-October 2026
stratospheric warming is visible as a warm pulse at the left of the
section instead of the deep blue the ARCO store drew.

**A bug worth remembering.**  `sector_mean()` takes the longitudes, and
`fetch_polar_core.py` was passing the **latitudes** (`la2[0, :]`) in that
slot, so the sector mask was meaningless and every sector mean came back
NaN - the sector panels came out blank.  The CORe's sector means are now
real: the North Atlantic 290,093 and the North Pacific 301,665 against the
cap's 296,257 on 13 November 2026.

### The GEFS ensemble is 31 members, and it always was

The 24-member member set was an ARTEFACT OF MY OWN LISTING, not NCEP
thinning the ensemble.  The S3 listing of a cycle directory is PAGINATED
(thousands of keys) and the keys come in member order, so a listing that
stops half way loses the LAST members (gep25 ... gep30) - and a member set
built from it is short at every lead, which reads exactly like an archive
that has dropped members.

Measured on the 20261114 00Z cycle, with the pagination followed to the
end: **gec00 and gep01..gep30 - all 31 members - are present at EVERY lead
from f012 to f840**, in both the pgrb2a and the pgrb2b halves.  The
archive does not thin the ensemble at long leads.

`fetch_polar_gefs.py` now (a) restarts the whole listing if a page fails,
(b) checks the member count at every lead and says so out loud, and (c)
takes the members common to EVERY lead rather than those at the longest
lead alone.  The chart now says "31 members".

### The three lagged centres: the UKMO, the JMA and the BoM

These three run a **lagged ensemble**: their members are not all started on
the same day.  The UKMO's 62 members start two per day over 31 consecutive
days (2026-10-02 .. 2026-11-01), the JMA's 155 five per day over the same
31 days, and the BoM's 99 eleven per day over nine days.

The C3S sub-daily product's `day` input selects the members **started on
that day**, so the pipeline's `day=["01"]` request comes back with 2
members for the UKMO and 5 for the JMA.  That is not a broken answer: it is
the whole of the members that started on the 1st.  Asking for a date that
is not a start date is refused outright by MARS ("Restricted access to
current C3S seasonal forecast non-ECMWF contribution"), which is why
"day 02" and "day 15" fail rather than coming back empty.

`fetch_lagged_u10.py` asks for every start day of the run and decodes each
member from its OWN validity date (never dataDate, which is the member's
start date and differs from member to member).  The start days are read
off the monthly pull, which carries the whole lagged ensemble - so no
request is needed to find them.

The monthly u10 pull is worth keeping anyway: it is the chart the three
centres publish, and it is the only thing that knows the run's layout.

### The lagged daily wind is built: three bugs on the way

The three lagged centres now publish a DAILY 10 hPa zonal-mean zonal wind
(UKMO 62 members, JMA 155, BoM 99) instead of the monthly one.  Three
traps had to be cleared first, and each of them looked like something else:

1. **The member numbering is not the same for every centre.**  The UKMO
   numbers the members of a start day from ONE (1, 2) and the JMA numbers
   them from ZERO (0, 1, 2, 3, 4).  Reading the index into the start
   day's group as `number - 1` shifted the JMA's whole ensemble by one and
   made two members of every day collide: the chart showed 121 members
   where there were 150.  The index is now taken from the SET of numbers
   the day actually used, which is only known once the whole file has been
   read - so the pairing is a second pass.

2. **The BoM's sub-daily product is stored at 24-HOUR steps**, not the
   12-hour steps the other two use: a request for its 12- or 36-hour lead
   comes back as MarsNoDataError, while 24, 48, 72, 168 and 264 are all
   there.  Asking for the whole run at the 12-hour phase therefore
   returned NOTHING for the BoM - it read like "the BoM has no sub-daily
   product", which it does not.  `LEAD_PHASE` carries the phase per
   centre, and the BoM's chart says "24-hour steps".

3. **A short chunk is not a big chunk.**  The JMA's first answer was short
   by 29 members, and the half-size retry was short by 29 as well - the
   response size was never the problem.  The chunk plan was reading the
   phase from the wrong place (the `chunk_plan` call did not pass the tag),
   so the retry asked for the same wrong-phase leads again.

**The coverage is real.**  Every member of every start day spans the whole
valid range, so the chart draws the whole ensemble; the number of members
present on a given day falls away at the far end only because the members
that started earliest run out of lead time first, which is what a lagged
ensemble does.

### The ECDS queue

The EC46 (the ECMWF sub-seasonal ensemble) comes from the ECMWF Data
Store's `s2s-forecasts` dataset, and the store's queue sat **accepted**
for hours on 15 November - a tiny control-only request for one lead did
not start either, so it is the store, not the request.  Two things had to
change in `fetch_polar_ec46.py`:

* **a job already in the store is ADOPTED**, not asked for again - a
  second request for the same chunk only makes the queue longer and takes
  the account's room away from the chunk that is already there;
* **the room check counts the jobs the account already holds**, and the
  limit is a total (two), so the room wanted is the number to ADD.

The stall limit was also too aggressive: a job that had been queued for two
and a half hours was dismissed as "stuck" after eight checks (two
minutes) and asked for again, which made the queue longer.  It is now
generous enough to ride out a congested store.

### The four sectors cover the whole cap

The by-sector figure used to split the cap into the North Pacific and the
North Atlantic and left the Barents-Kara wedge unaccounted for.  It is now
four contiguous sectors, so the width-weighted mean of the four is the cap
mean exactly (CORe +1 m2/s2, GEFS +0, SEAS5 -0):

| sector | longitude | width |
|---|---|---|
| `natl` | 300E-60E | 120 deg |
| `npac` | 120E-240E | 120 deg |
| `narctic` | 240E-300E | 60 deg |
| `nbarents` | 60E-120E | 60 deg |

**A date label centred on its tick hangs half outside its panel.**  On the
sector figure the panels sit shoulder to shoulder, and the last date of
one panel ran straight into the first date of the next ("18 Dec30 Oct").
The panels share one time axis, so the outer panels now carry the start
and the end date and the inner ones leave those two labels out.  The TICKS
stay on every panel, so the gridlines still line up.

### The EC46 queue, 15 November (afternoon)

The store processed **nothing** for this account after 02:58Z.  Two
requests sit `accepted` with no message - chunk 0 (`9302be85`, queued
08:01:42Z) and chunk 10 (`4c1015b9`, queued 09:34:31Z).  A fresh 5-day
request also sat `accepted`.  The jobs are recorded in
`data/polar_ec46_jobs.json`, so a restarted fetcher adopts them again
instead of asking for those chunks a second time.

**There is no other route to the S2S data** - all checked on 15 Nov:

* the CDS catalogue (144 collections) has no `s2s` or sub-seasonal entry;
* the open `ecmwf-forecasts` S3 bucket carries `ifs/`, `aifs-ens/` and
  `aifs-single/` only - no extended range;
* `ecmwf-open-data`, `s2s-forecasts` and `ecmwf-s2s` are not buckets.

**The stall limit is 60 hours, not 6.**  On 15 Nov 2026 the store processed
nothing for this account for more than twelve hours: the two jobs sat
`accepted` from 08:01Z and 09:34Z, and the last successful job finished at
02:58Z.  A six-hour stall limit would have dismissed a job that had already
waited nearly eight hours, and a dismissal puts the request at the BACK of
the queue.  `wait()` now waits 14400 checks (60 hours at 15 s) before it
gives up on a job that has not started.

### What the store did on 15 November (the queue's own answers)

The store was not idle - it was **failing** the old jobs.  At 17:20Z the
chunk-0 job (`9302be85`, queued 08:01:42Z) came back `failed` and was
then deleted by the store (`404 ... job deleted`).  A store-side failure
is the store's answer to the request, not a reason to skip the chunk, so
`wait()` now returns what happened (`done` / `failed` / `timeout`) and a
failed chunk is **asked for again** (up to three times), waiting for room
in the queue before each new request.

**A submitted job is recorded in the state file AT ONCE**, not when its
chunk is finished.  A job that is live in the store but not in the state
file cannot be adopted after a restart, and the chunk is asked for a
second time - which takes the account's room away from the job that is
already queued.

## 15 Nov 2026 - the SEAS5's far end was the MODEL's own mean state, not a forecast

### The complaint, and what it turned out to be

The SEAS5's polar-cap section drew its far end (April to June 2027) as
-2 to -4 sigma of a **cold stratosphere**, and the user was right that
nothing had been fixed.  It was not the atmosphere and it was not the
reanalysis: the **forecast half was measured against the OBSERVED climate**,
and a seasonal model's mean state is not the observed climate.

Measured, 10 hPa, polar-cap mean, the model's own climate against the CORe
1991-2020 climate:

| lead month | Nov | Dec | Jan | Feb | Mar | Apr | May | Jun |
|---|---|---|---|---|---|---|---|---|
| the model's bias (m2/s2) | -641 | -809 | -311 | -1,627 | -1,654 | -2,909 | -3,168 | -4,745 |

What the re-basing does to the 10 hPa cap, the model minus the observed
climate before and after:

| the day | before | after |
|---|---|---|
| 2026-11-02 (the first forecast day) | +3.43 sigma | +4.04 sigma |
| 2026-12-15 | -0.90 | -0.68 |
| 2027-02-15 | +0.33 | +0.69 |
| 2027-04-15 | -0.93 | +0.16 |
| 2027-05-15 | **-2.89** | **+0.43** |
| 2027-06-01 | **-3.75** | **+0.31** |

And the observed climate's own sigma at 10 hPa falls to **429 m2/s2 in
June** (631 on the day), so an offset of 5,000 was amplified to several
sigma by the denominator.

**The model's mean state does not drift with the lead** - the same
calendar month at two different leads differs by only a few hundred m2/s2
(November at lead 1 of the November init: 289,848.6; November at lead 2 of
the October init: 289,892.3, a difference of +43.7).  So the far-end offset
is a seasonal mismatch, not a runaway drift, and subtracting the model's own
climate removes it.

### The fix: the forecast is measured against the model's OWN hindcast climate

    plotted = observed_climate + (model - model_clim)

The reanalysis half is untouched (it is the observed climate against
itself), the model's own offset is removed from the forecast, and the two
halves still meet at the dashed line.

Where the model's own climate comes from:

* **Lead months 1-6 (November to April)** - `seasonal-monthly-pressure-levels`
  with `product_type: hindcast_climate_mean`, one small request
  (`fetch_polar_model_clim.py`).  10 hPa cap means: 289,848.6 / 286,904.7 /
  288,481.9 / 290,971.9 / 293,705.3 / 299,082.5.
* **Lead months 7-8 (May, June)** - the monthly product caps at lead month
  6 and the daily one stops at 215 days, so the far end comes from the
  model's own **past November inits** through the daily product, exactly as
  the SPV chart's month-7 climate was built (`fetch_polar_model_clim7.py`,
  ten inits 2016-2025).  The past inits' **lead 6 (April)** is the check on
  the pull: the same season and the same lead as the monthly product's.
  It agrees: the monthly product says 299,082.5 and the ten past runs say
  **299,317.2** - a difference of 235 m2/s2 between two independent routes.

### The month's MEAN, not one day of it

The first version of the pull kept ONE day per lead month, and the monthly
product publishes a month's mean.  They are not the same number: the polar
cap warms by about 4,700 m2/s2 between the 5th and the 29th of April, so
the single day said 296,625.6 where the month says 299,082.5.  The days of
a lead month are averaged now (`redecode_polar_model_clim7.py` re-decoded
the finished inits from the jobs still in the store - the GRIBs are deleted
after decoding, but the job results are not).

The model's mean state turns out to be nearly the same every year: over
ten November inits the April lead month has a spread of 340 m2/s2 and the
June lead month 180, so ten inits is far more than enough.

### June is anchored on the FIRST of the month, not the middle

The daily product stops at 215 days from the init, which is the 3rd of
June, so the model's own climate for lead month 8 is the mean of 1 and
3 June and it stands for those days.  The observed climate is anchored at
the middle of every month, so the two curves cannot be anchored the same
way - and the correction has to be the difference of the two CURVES, not
the difference of the two monthly means.

Anchoring June in the middle drew the last three days of the chart as
+2 sigma at 10 hPa (the model's value belongs to the start of the month,
and the interpolation ran it up towards the middle).  Anchored on the 1st
of June and held flat afterwards, the last three days read +0.31, +0.67 and
+1.05 sigma - which is what the model actually says.
* **October**, the month before the chart's first day - the observed climate
  is interpolated onto the days from the monthly means, and the first half
  of November leans on the October mean, so the model needs an October
  anchor too or the two halves do not meet (`fetch_polar_model_clim_oct.py`).
  The October init's lead 1 is used; the model's mean state moves by only a
  few hundred m2/s2 per lead month, so the lead difference is second order.

### The date trap in the monthly product

The monthly product stamps a month on the FIRST of the month AFTER the one
it covers: the field dated `2026-12-01` is **November 2026**, which is lead
month 1 of a November init.  The lead has to be worked out from the
validity date, not from the number of fields.

### The interpolation is the observed climate's own

The model's monthly means are anchored at the middle of each calendar month
and interpolated onto the days exactly as `daily_climate` does it for the
observed climate, so the two stay on one scale and the forecast does not
step at every month boundary.  The interpolation is LINEAR, so
`interp(model) - interp(observed) = interp(model - observed)`: the bias can
be interpolated on its own and it is the same thing.

### The step the re-basing leaves at the dashed line

The reanalysis half keeps the observed climate as its reference and the
forecast is measured against the model's own, so the two halves differ by
the model's bias at the init: **+1.0 sigma at 10 hPa** on 15 November 2026
(the model sat 641 m2/s2 below the observed climate in November, and the
interpolation of the first days of November leans on the October anchor,
which is 1,246 below).  It reads as no step at all on the chart - the SSW
runs straight through the line - and the alternative, measuring both halves
against the model's climate, was checked and rejected: it would move the
reanalysis half, which is the published CORe record, off the scale the rest
of the site quotes.

### The GEFS is NOT re-based

`polar_rebase.climate_matches()` refuses the correction for any chart whose
run is not the model's own init - the GEFS's 35-day run drifts very little
(a few hundred m2/s2) and it keeps the observed climate, so the two charts
are on the same footing where they can be.
