# Data sources

## Primary — real public data

### DataMeet / Indian Railways
- **URL**: https://github.com/datameet/railways
- **Licence**: CC0 (public domain dedication)
- **Authoritative?** Community-compiled from Indian Railways sources. Treat as
  SEMI-OFFICIAL: the content is real, the compilation is not an IR publication.
- **Files and verified field names**
  - `stations.json` — GeoJSON FeatureCollection. Properties: `state`, `code`,
    `name`, `zone`, `address`. Point geometry gives longitude, latitude.
  - `trains.json` — GeoJSON FeatureCollection. Properties include `number`,
    `name`, `type`, `from_station_code`, `from_station_name`,
    `to_station_code`, `to_station_name`, `distance`, `duration_h`,
    `duration_m`, `departure`, `arrival`, `zone`, `classes`, `return_train`,
    and class flags (`first_ac`, `second_ac`, `third_ac`, `sleeper`,
    `chair_car`, `first_class`). LineString geometry gives the route.
  - `schedules.json` — array. Fields: `train_number`, `train_name`,
    `station_code`, `station_name`, `arrival`, `departure`, `day`, `id`.
- **Vintage**: compiled around 2016 (the README links an account of the
  gathering at sajjad.in). **No date is stated in the repository.** This is the
  single most important limitation of the dataset and must be declared: the
  timetable is a historical snapshot, not today's timetable.
- **What it does NOT provide**: division boundaries; inter-station distances;
  track count; electrification; any freight; any maintenance data.

### OpenStreetMap (optional, for track configuration)
- **URL**: https://www.openstreetmap.org ; Overpass API at
  https://overpass-api.de/api/interpreter
- **Licence**: ODbL — attribution required if you redistribute derived data.
- **Tags used**: `railway=rail`, `tracks`, `electrified`, `voltage`, `gauge`,
  `usage`.
- **Limitation**: coverage of `tracks` and `electrified` in India is uneven.
  Where a section has no usable tag the declared fallback is used and the row
  is tagged provenance E, not A. `sections.track_source` records which.

## Context — verified public facts about the study area
- Salem division, Southern Railway: inaugurated 14 November 2006; 862 route km;
  entire broad-gauge line electrified.
  https://en.wikipedia.org/wiki/Salem_railway_division
- Jolarpettai–Shoranur line: 366 km; electrified in stages, Jolarpettai–Morappur
  1989-90, Salem Jn 1990-91, Erode Jn 1991-92, Coimbatore 1995-96, Shoranur
  1996-97. https://en.wikipedia.org/wiki/Jolarpettai%E2%80%93Shoranur_line
- These are context only. **No dataset field depends on them.** They are quoted
  so a reader can sanity-check the corridor, not used as inputs.

## Rules and manuals — provenance class C
- AC Traction Manual Vol. II Pt. I Ch. VI, Power Blocks and Permits-to-Work:
  https://indianrailways.gov.in/railwayboard/uploads/codesmanual/ACTraction-II-P-I/ACTractionIIPartICh6.htm
- ACTM Ch. 17 as reproduced by Southern Railway Madurai ZTI:
  https://railnet.in/sr/mdzti/content/files/Chapter-17.pdf
- Indian Railways Track Machine Manual Ch. 3 and Ch. 5:
  https://indianrailways.gov.in/railwayboard/uploads/codesmanual/IRTMM-RDSO/TMM_Ch/TMM_Ch_3.html
  https://indianrailways.gov.in/railwayboard/uploads/codesmanual/IRTMM-RDSO/TMM_Ch/TMM_Ch_5.html
- Indian Railways General Rules Ch. 15 (Permanent Way and Works):
  https://irfca.org/docs/rulebook/gr-pway.html
- Railway Board circular, Fixed-Time Integrated Corridor Blocks, 29 Dec 2016:
  https://indianrailways.gov.in/railwayboard/uploads/directorate/tracks/Track_3/Corridor_Block_291216.pdf
  (existence confirmed; contents not retrieved — OBTAIN THIS)
- CAG Report No. 45 of 2018, Ch. 3, for the corridor block norm and the
  block-shortfall figures:
  https://cag.gov.in/uploads/download_audit_report/2018/Chapter_3_Utilisation_of_resources_and_infrastructure_for_track_maintenance_of_Report_No.45_of_2018_%E2%80%93_Compli_1.pdf

## Checked and NOT used
- **data.gov.in railway timetable catalogue** — the catalogue entry exists but
  did not resolve to a downloadable, machine-readable resource when checked.
  Verify in a browser before depending on it.
- **NTES / RailRadar** — no documented public bulk or open API. Live running
  data is not available to us, which is why no field in this dataset claims to
  be observed running performance.
- **Working Time Tables** — zonal WTTs would give real section running times,
  loop lengths and line capacity. Not reliably published online. This is the
  single most valuable document to obtain from a division.
