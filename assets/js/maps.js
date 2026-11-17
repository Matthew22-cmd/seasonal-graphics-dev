/* ------------------------------------------------------------------
   Interactive Natural Earth maps for the seasonal graphics site.

   Three configurations of the WHOLE WORLD, in the spirit of the
   ECMWF interactive viewer:

     2D Map   the flat world on an equirectangular grid
     3D Globe the same world on an orthographic globe you can spin
     Polar    the same world on a north polar projection - the whole
              Earth, centred on the pole

   The two sectors of the polar cap section - the North Pacific and
   the North Atlantic, 60N-90N - are marked on all three, in the
   colours the static charts use.  The base map is Natural Earth 1:50m
   data that is committed to the repository, so the site never depends
   on a download at build time.
   ------------------------------------------------------------------ */
(function () {
  "use strict";

  var NE = "assets/ne/";
  var SRC = {
    countries: NE + "ne_50m_admin_0_countries.geojson",
    lakes: NE + "ne_50m_lakes.geojson",
    land: NE + "ne_50m_land.geojson"
  };

  /* The two sectors the polar section is drawn for: the North Pacific
     (120E-240E) and the North Atlantic (300E-60E), both 60N-90N. */
  var SECTORS = [
    {id: "npac", name: "North Pacific", lon0: 120, lon1: 240,
     colour: "#f4b740", ink: "#3a2600", flatLabelLon: 150},
    {id: "natl", name: "North Atlantic", lon0: 300, lon1: 60,
     colour: "#3d7fd1", ink: "#0d2f5e"}
  ];

  /* The polar view keeps the arrangement of the static charts: the pole
     at the centre, Greenwich at the BOTTOM, the Pacific at the top and
     the Atlantic at the bottom.  d3's azimuthal projections put the
     projection's own longitude at the bottom, so the rotation is 0. */
  var POLAR_ROT = [0, -90];

  var state = {view: "globe", data: {}, rot: [-40, -25], drag: null};

  function el(id) { return document.getElementById(id); }

  /* ---------------------------------------------------------------- */

  function sectorRing(s) {
    /* The sector as a lat/lon ring: the bottom edge along 60N, up the
       far meridian to the pole, and back down the near meridian.
       Two things matter here:
         - the ring must NOT run along 90N.  The pole is a single point
           on the sphere, so a ring that follows the 90N parallel is
           degenerate and d3 reads it as covering the whole globe.
         - the winding decides which side of the ring d3 treats as the
           inside, so the ring goes out along the near meridian first.
           Wound the other way d3 reads the complement - the whole
           globe - as the sector. */
    var lon1 = (s.lon1 > s.lon0) ? s.lon1 : s.lon1 + 360;
    return [[s.lon0 % 360, 60],
            [lon1 % 360, 90],
            [lon1 % 360, 60],
            [s.lon0 % 360, 60]];
  }

  function sectorPoly(s) {
    return {type: "Polygon", coordinates: [sectorRing(s)]};
  }

  function sectorLabel(s, flat) {
    var lon1 = (s.lon1 > s.lon0) ? s.lon1 : s.lon1 + 360;
    var lon = (s.lon0 + (lon1 - s.lon0) / 2) % 360;
    /* on the flat map the Pacific sector straddles the map's edge, so its
       label sits inside the eastern piece instead of on the seam */
    if (flat && s.flatLabelLon !== undefined) { lon = s.flatLabelLon; }
    return [lon, 74];
  }

  function drawSectors(g, path, proj, label, flat) {
    var s = SECTORS.map(function (sec) {
      return {sec: sec, poly: sectorPoly(sec), at: sectorLabel(sec, flat)};
    });
    g.selectAll("path.sector").data(s).join("path")
      .attr("class", "sector")
      .attr("fill", function (d) { return d.sec.colour; })
      .attr("d", function (d) { return path(d.poly); });
    if (label) {
      /* d3's geoPath returns null for a point that falls outside the
         projection's clip extent - on the globe that is a sector on the
         far side - so the label is only placed when it has a position. */
      g.selectAll("text.sector").data(s).join("text")
        .attr("class", "sectorlabel")
        .attr("fill", function (d) { return d.sec.ink; })
        .text(function (d) { return d.sec.name; })
        .each(function (d) {
          /* the projection returns the position, or null when the point
             is not visible - on the globe that is the far side */
          var q = proj(d.at);
          d3.select(this)
            .attr("x", q ? q[0] : -999)
            .attr("y", q ? q[1] : -999)
            .attr("display", q ? null : "none");
        });
    }
  }

  function capLine() {
    var c = [];
    for (var i = 0; i <= 360; i++) { c.push([i % 360, 60]); }
    return {type: "LineString", coordinates: c};
  }

  /* ---------------------------------------------------------------- */
  /* 2D map - the flat world                                         */

  function drawFlat(svg, W, H) {
    var proj = d3.geoEquirectangular()
      .fitExtent([[10, 10], [W - 10, H - 10]], {type: "Sphere"});
    var path = d3.geoPath(proj);

    svg.append("path").datum({type: "Sphere"}).attr("class", "ocean")
      .attr("d", path);
    svg.append("path").datum(d3.geoGraticule10()).attr("class", "grat")
      .attr("d", path);

    var g = svg.append("g");
    g.selectAll("path.country").data(state.data.countries.features)
      .join("path").attr("class", "country").attr("d", path)
      .on("mousemove", function (ev, d) {
        var p = d3.pointer(ev, svg.node());
        showTip(ev, d.properties.NAME, p[0], p[1]);
      })
      .on("mouseleave", hideTip);
    g.selectAll("path.lake").data(state.data.lakes.features)
      .join("path").attr("class", "lake").attr("d", path);

    /* the cap's edge, at 60N */
    svg.append("path").datum(capLine()).attr("class", "capedge")
      .attr("d", path);

    drawSectors(g, path, proj, true, true);

    note("The whole world on an equirectangular grid, with the two polar " +
         "sectors of the polar cap section marked. The equirectangular " +
         "projection squeezes the polar regions, which is why the polar " +
         "view exists.");
  }

  /* ---------------------------------------------------------------- */
  /* 3D globe                                                        */

  function drawGlobe(svg, W, H) {
    var proj = d3.geoOrthographic()
      .fitExtent([[10, 10], [W - 10, H - 10]], {type: "Sphere"})
      .rotate(state.rot);
    var path = d3.geoPath(proj);

    /* the limb: a soft blue rim, the way the atmosphere reads on the
       ECMWF viewer */
    var r = path({type: "Sphere"}).length;
    var defs = svg.append("defs");
    var grad = defs.append("radialGradient")
      .attr("id", "atmosgrad").attr("cx", "50%").attr("cy", "50%")
      .attr("r", "50%");
    grad.append("stop").attr("offset", "62%").attr("stop-color", "#3d8fe8")
      .attr("stop-opacity", 0);
    grad.append("stop").attr("offset", "82%").attr("stop-color", "#4f9df0")
      .attr("stop-opacity", .35);
    grad.append("stop").attr("offset", "93%").attr("stop-color", "#79b9ff")
      .attr("stop-opacity", .75);
    grad.append("stop").attr("offset", "100%").attr("stop-color", "#a8d2ff")
      .attr("stop-opacity", 0);
    svg.append("circle")
      .attr("class", "atmos")
      .attr("cx", W / 2).attr("cy", H / 2).attr("r", r * 1.16)
      .attr("fill", "url(#atmosgrad)");

    svg.append("path").datum({type: "Sphere"}).attr("class", "ocean")
      .attr("d", path);
    svg.append("path").datum(d3.geoGraticule10()).attr("class", "grat")
      .attr("d", path);

    var g = svg.append("g");
    g.selectAll("path.country").data(state.data.countries.features)
      .join("path").attr("class", "country").attr("d", path)
      .on("mousemove", function (ev, d) {
        var p = d3.pointer(ev, svg.node());
        showTip(ev, d.properties.NAME, p[0], p[1]);
      })
      .on("mouseleave", hideTip);
    g.selectAll("path.lake").data(state.data.lakes.features)
      .join("path").attr("class", "lake").attr("d", path);

    /* the cap's edge at 60N */
    svg.append("path").datum(capLine()).attr("class", "capedge")
      .attr("d", path);

    drawSectors(g, path, proj, true);

    /* the projection takes a bare [lon, lat]; d3's geoPath is the one
       that wants a GeoJSON object */
    var pole = proj([0, 90]);
    if (pole) {
      svg.append("circle")
        .attr("class", "pole")
        .attr("cx", pole[0]).attr("cy", pole[1]).attr("r", 3);
    }

    svg.call(d3.drag()
      .on("start", function (ev) { state.drag = d3.pointer(ev, this); })
      .on("drag", function (ev) {
        var p = d3.pointer(ev, this);
        var dx = p[0] - state.drag[0], dy = p[1] - state.drag[1];
        state.rot[0] += dx * 0.45;
        state.rot[1] = Math.max(-90, Math.min(90, state.rot[1] - dy * 0.45));
        state.drag = p;
        draw();
      }));

    note("The same world on an orthographic globe - drag it to spin. The " +
         "polar cap is the ring north of 60N; the two sectors are marked " +
         "in the colours the polar charts use.");
  }

  /* ---------------------------------------------------------------- */
  /* polar - the whole world on a north polar projection              */

  function drawPolar(svg, W, H) {
    var proj = d3.geoAzimuthalEquidistant()
      .rotate(POLAR_ROT)
      .fitExtent([[10, 10], [W - 10, H - 10]], {type: "Sphere"});
    var path = d3.geoPath(proj);

    /* the globe as a disc */
    svg.append("path").datum({type: "Sphere"}).attr("class", "ocean")
      .attr("d", path);

    var g = svg.append("g");
    g.selectAll("path.country").data(state.data.countries.features)
      .join("path").attr("class", "country").attr("d", path)
      .on("mousemove", function (ev, d) {
        var p = d3.pointer(ev, svg.node());
        showTip(ev, d.properties.NAME, p[0], p[1]);
      })
      .on("mouseleave", hideTip);
    g.selectAll("path.lake").data(state.data.lakes.features)
      .join("path").attr("class", "lake").attr("d", path);

    /* the graticule: the latitude circles and the longitude spokes */
    var grat = {type: "MultiLineString", coordinates: []};
    [60, 30].forEach(function (lat) {
      var c = [];
      for (var i = 0; i <= 360; i++) { c.push([i % 360, lat]); }
      grat.coordinates.push(c);
    });
    for (var lon = 0; lon < 360; lon += 30) {
      grat.coordinates.push([[lon, 60], [lon, 90]]);
    }
    svg.append("path").datum(grat).attr("class", "grat").attr("d", path);

    drawSectors(g, path, proj, true);

    /* the edge of the cap, at 60N, solid */
    svg.append("path").datum(capLine()).attr("class", "capedge")
      .attr("d", path);

    note("The whole world on a north polar projection: the pole at the " +
         "centre, every continent radiating from it, the 60N edge of the " +
         "polar cap solid. The North Pacific sector is at the top and the " +
         "North Atlantic at the bottom, exactly as on the stratosphere " +
         "page.");
  }

  /* ---------------------------------------------------------------- */

  var tip = null;
  function showTip(ev, text, x, y) {
    if (!tip) { tip = el("maptip"); }
    tip.textContent = text;
    tip.style.left = (x + 14) + "px";
    tip.style.top = (y + 10) + "px";
    tip.style.display = "block";
  }
  function hideTip() { if (tip) { tip.style.display = "none"; } }

  function note(text) {
    var n = el("mapnote");
    if (n) { n.textContent = text; }
  }

  function draw() {
    if (!state.data.countries) { return; }
    var svg = d3.select("#mapsvg");
    svg.selectAll("*").remove();
    var box = el("mapbox");
    var W = Math.max(320, Math.round(box.clientWidth));
    var H;
    if (state.view === "flat") {
      H = Math.round(Math.min(560, Math.max(260, W * 0.46)));
    } else if (state.view === "polar") {
      H = Math.round(Math.min(680, Math.max(360, W * 0.62)));
    } else {
      H = Math.round(Math.min(600, Math.max(380, W * 0.62)));
    }
    svg.attr("width", W).attr("height", H)
      .attr("viewBox", "0 0 " + W + " " + H);
    if (state.view === "flat") { drawFlat(svg, W, H); }
    else if (state.view === "globe") { drawGlobe(svg, W, H); }
    else { drawPolar(svg, W, H); }
  }

  function load() {
    var todo = [];
    if (!state.data.countries) { todo.push(SRC.countries); }
    if (!state.data.lakes) { todo.push(SRC.lakes); }
    if (!state.data.land) { todo.push(SRC.land); }
    if (!todo.length) { draw(); return; }
    var n = el("mapload");
    if (n) { n.style.display = "block"; }
    Promise.all(todo.map(function (u) { return d3.json(u); }))
      .then(function (res) {
        var i = 0;
        if (!state.data.countries) { state.data.countries = res[i++]; }
        if (!state.data.lakes) { state.data.lakes = res[i++]; }
        if (!state.data.land) { state.data.land = res[i++]; }
        var n2 = el("mapload");
        if (n2) { n2.style.display = "none"; }
        draw();
      }).catch(function (e) {
        var n3 = el("mapload");
        if (n3) {
          n3.style.display = "block";
          n3.textContent = "The map data could not be loaded: " + e;
        }
      });
  }

  function setView(v) {
    state.view = v;
    var btns = document.querySelectorAll("#mapviews button");
    Array.prototype.forEach.call(btns, function (b) {
      b.classList.toggle("active", b.dataset.view === v);
    });
    var box = el("mapbox");
    if (box) { box.className = "mapbox " + v; }
    load();
  }

  function init() {
    if (typeof d3 === "undefined") { return; }
    var btns = document.querySelectorAll("#mapviews button");
    Array.prototype.forEach.call(btns, function (b) {
      b.addEventListener("click", function () { setView(b.dataset.view); });
    });
    window.addEventListener("resize", draw);
    setView(state.view);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
