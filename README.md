# Google Earth polygons → Shapefile

Turn the polygons in a Google Earth project into an ESRI Shapefile. You can convert locally or export through Google Earth Engine.

The **Lidar Data** project is already converted: [`output/Lidar_Data.zip`](output/Lidar_Data.zip).

| NAME | AREA_HA |
|---|---:|
| Piallassa | 18,328.98 |
| Forli | 1,016.62 |
| Foce reno & comacchio | 18,599.36 |
| Campi bonifiche | 53,343.51 |
| Ridracoli Dam | 597.55 |

The output uses WGS84 (EPSG:4326) and has the fields `NAME, DESCR, FOLDER, AREA_M2, AREA_HA`. Areas are geodesic on the WGS84 ellipsoid.

## 1. Export the KML from Google Earth

In Google Earth on the web, open **Projects**. Click the **⋮** menu next to the project and choose **Export as KML file**. Save the file into `data/`.

## 2a. Convert locally (no Earth Engine account needed)

```bash
pip install pyshp pyproj
python kml_to_shapefile.py data/Lidar_Data.kml -o output/Lidar_Data
```

## 2b. Export through Google Earth Engine (Python)

This uploads the polygons as an `ee.FeatureCollection` and runs `Export.table.toDrive(fileFormat='SHP')`. You can also save them as an EE table asset.

```bash
pip install earthengine-api
earthengine authenticate
python gee_export.py data/Lidar_Data.kml --project YOUR_GCP_PROJECT \
    --folder EarthEngine --asset projects/YOUR_GCP_PROJECT/assets/lidar_areas --wait
```

The shapefile parts appear in the `EarthEngine` folder of your Google Drive.

## 2c. Google Earth Engine Code Editor

Paste `gee_code_editor_export.js` into <https://code.earthengine.google.com>. Set `SOURCE` to one of:

- `'asset'`: uses the asset created in step 2b, or the `output/Lidar_Data.zip` you uploaded through **Assets → NEW → Shape files**.
- `'drawn'`: uses polygons you trace with the drawing tools.

Click **Run**, then start the task in the **Tasks** tab.
