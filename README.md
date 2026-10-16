# Planet Zero: the public air feed

The air in Malaysia and Singapore, every hour, as JSON files anyone can read: the numbers the planetzero.ai site and its connector show, each with where it comes from.

**The feed:** https://yheushen.github.io/planetzero-feed/ (the `feed` branch of this repo, served by GitHub Pages)

**Ask your AI chat:** the connector at https://mcp.planetzero.ai/mcp (MCP, Streamable HTTP, no sign-in) answers from this feed: the air now, the numbers you may be shown, the next 5 days, the places and the sources, each number with what it is. How to add it: https://planetzero.ai/ask

| File | What |
|---|---|
| `now.json` | Every place: the hour, the 24-hour index, the community sensors within 10 km, the computer model's estimate, aqicn's current value; what each source did on the last run |
| `outlook.json` | The next 5 days per place on the PSI scale, from the CAMS model, with how it scored against what was measured |
| `grid.json` | For the globe: smoke and wind from computer models, and the fires NASA's satellites saw in the last 24 hours |
| `checks.json` | Our checks of numbers we may not republish (Google's): only our results, never Google's numbers |
| `scales.json` | The bands, their words and colours, and the advice for each |
| `status.json` | What each source did on the last run |
| `history/` | Hourly history per source and month (never aqicn's, whose terms do not allow keeping its archive) |
| `audit.json`, `audit/answers/` | What AI chats answered to our fixed questions about the air, scored against what was measured; their answers kept word for word as evidence |

## The rules every file follows

- Every number says what it is: its unit, band, time span (this hour or the past 24 hours), source, whether it was measured or estimated, and when.
- Only sources whose terms allow it. Google's and IQAir's numbers are never in the feed. When an AI chat's answer quotes IQAir, that is the assistant's answer, labelled "quoting IQAir"; we never fetch IQAir ourselves.
- Positions are rounded to 2 decimals (about 1 km).
- A failed fetch is shown as missing, never filled with an old value.

## How it is built

`engine/build_feed.py`, run by `.github/workflows/feed.yml` every hour at minute 18: an outside timer starts it on the hour, and GitHub's own schedule is a backup that builds only when the feed is over 40 minutes old. The engine reads only public sources; its keys are this repo's secrets. The website's code and the AI chat audit live in a private repo; the audit publishes its answers here.

The engine's code here is copied from that private repo by `feed-repo/sync.py`; change it there, not here.

## Credit lines

Each source's terms ask for its credit line. Every JSON file also carries a `credits` block for the sources it holds, with the date its data was fetched. Full terms: [ATTRIBUTION.md](ATTRIBUTION.md).

- **NEA (Singapore):** Contains information from 1-hour PM2.5 readings and Pollutant Standards Index (PSI) accessed on the date given in each file from data.gov.sg which is made available under the terms of the Singapore Open Data Licence version 1.0 (https://data.gov.sg/open-data-licence).
- **DOE (Malaysia):** Air Pollutant Index (API) from the Department of Environment Malaysia (DOE), via APIMS (https://eqms.doe.gov.my/APIMS/main). Data dan maklumat tertakluk di bawah Terma Penggunaan Data Terbuka Kerajaan Malaysia 1.0 (https://www.doe.gov.my/wp-content/uploads/2021/09/TermaPenggunaan.pdf).
- **OpenAQ (community sensors):** Community sensor data via OpenAQ (https://openaq.org), licence per location: AirGradient locations under CC BY 4.0 (data provided by AirGradient via OpenAQ, https://www.airgradient.com), Clarity locations under CC0 1.0. Each sensor's owner is named with its readings.
- **CAMS via Open-Meteo (computer model):** Air quality data by Open-Meteo.com (https://open-meteo.com), under CC BY 4.0. Contains modified Copernicus Atmosphere Monitoring Service information 2026. Neither the European Commission nor ECMWF is responsible for any use that may be made of the Copernicus information or data it contains.
- **Open-Meteo (wind):** Weather data by Open-Meteo.com (https://open-meteo.com), under CC BY 4.0.
- **NASA FIRMS (fires):** We acknowledge the use of data and/or imagery from NASA's Fire Information for Resource Management System (FIRMS) (https://earthdata.nasa.gov/firms), part of NASA's Land, Atmosphere Near real-time Capability for Earth observations (LANCE) (https://earthdata.nasa.gov/lance) and NASA's Earth Science Data and Information System (ESDIS). Datasets: S-NPP VIIRS NRT, doi:10.5067/FIRMS/VIIRS/VNP14IMGT_NRT.002; NOAA-20 VIIRS NRT, doi:10.5067/FIRMS/VIIRS/VJ114IMGT_NRT.002. Disclaimer: https://www.earthdata.nasa.gov/data/projects/lance/disclaimer. Near real-time detections; NASA's later standard products may differ.
- **aqicn (World Air Quality Index project):** Current values from the World Air Quality Index project (https://aqicn.org), relaying NEA and DOE. Data not verified by aqicn; not for paid use; its archive is not kept.
- **NASA GIBS (Earth's pictures):** We acknowledge the use of imagery provided by services from NASA's Global Imagery Browse Services (GIBS), part of NASA's Earth Science Data and Information System (ESDIS). Real Earth: VIIRS on NOAA-20, Suomi NPP and NOAA-21, corrected reflectance, true colour, with NASA's Blue Marble where none saw anything; smoke from space: VIIRS Deep Blue on NOAA-20, Suomi NPP and NOAA-21, aerosol optical depth, the last 3 days; carbon monoxide: AIRS on Aqua, 500 hPa, the last 6 days. Coastlines: © OpenStreetMap contributors (https://www.openstreetmap.org/copyright), under the Open Database License.
- **NOAA GFS (wind):** Wind: NOAA National Centers for Environmental Prediction (NCEP), Global Forecast System (GFS), 10 m wind at 1 degree, via NOMADS (https://nomads.ncep.noaa.gov). A computer model's estimate.
- **CelesTrak (orbits):** Orbit data: CelesTrak (https://celestrak.org), general perturbations elements, fetched at most once per 2-hour update.
- **CAMS global (computer model):** Generated using Copernicus Atmosphere Monitoring Service information 2026: CAMS global atmospheric composition forecasts (0.4 degrees), from the Copernicus Atmosphere Data Store, under CC BY 4.0. Neither the European Commission nor ECMWF is responsible for any use that may be made of the Copernicus information or data it contains.
- **OpenAQ (monitors worldwide):** Air monitors and community sensors worldwide via OpenAQ (https://openaq.org), the latest hour only, licence per location: CC BY 4.0, CC0 1.0, US Public Domain, Japan's Government Standard Terms of Use v2.0, ODC-BY, UK Open Government Licence or CC BY-SA 4.0. Each location's owner and licence are named with its reading.
- **Natural Earth (place names):** Made with Natural Earth. Free vector and raster map data @ naturalearthdata.com.

Nobody downloading these files gets more rights than each source grants.
