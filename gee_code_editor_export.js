/**
 * Google Earth Engine Code Editor script: export polygons as a Shapefile.
 *
 * Paste into https://code.earthengine.google.com and click Run, then start
 * the task in the "Tasks" tab. The shapefile (.shp/.shx/.dbf/.prj/.cpg)
 * lands in your Google Drive folder below.
 *
 * Where the polygons come from (pick ONE and set SOURCE):
 *   'asset'  - a table asset, e.g. the one created by
 *              `python gee_export.py my.kml --project P --asset projects/P/assets/my_areas`
 *              or uploaded via Assets > NEW > Shape files / CSV.
 *   'drawn'  - polygons you trace with the Code Editor drawing tools
 *              (each polygon layer appears as an import at the top of the script).
 */

var SOURCE = 'asset';                                  // 'asset' or 'drawn'
var ASSET_ID = 'projects/YOUR_PROJECT/assets/my_areas'; // used when SOURCE == 'asset'
var DRIVE_FOLDER = 'EarthEngine';
var FILE_PREFIX = 'google_earth_polygons';

var polygons;
if (SOURCE === 'asset') {
  polygons = ee.FeatureCollection(ASSET_ID);
} else {
  // Collect every polygon drawn with the Geometry tools (any number of layers).
  var layers = Map.drawingTools().layers();
  var feats = [];
  for (var i = 0; i < layers.length(); i++) {
    var layer = layers.get(i);
    var geoms = layer.geometries();
    for (var j = 0; j < geoms.length(); j++) {
      feats.push(ee.Feature(geoms.get(j), {name: layer.getName() + '_' + (j + 1)}));
    }
  }
  polygons = ee.FeatureCollection(feats);
}

// Shapefiles hold a single geometry type: keep only (multi)polygons and add area.
polygons = polygons
    .map(function (f) { return f.set('geom_type', f.geometry().type()); })
    .filter(ee.Filter.inList('geom_type', ['Polygon', 'MultiPolygon']))
    .map(function (f) {
      return f.set('area_ha', f.geometry().area({maxError: 1}).divide(1e4));
    });

print('Polygons to export:', polygons.size(), polygons);
Map.addLayer(polygons, {color: 'FF0000'}, 'polygons');
Map.centerObject(polygons);

Export.table.toDrive({
  collection: polygons,
  description: FILE_PREFIX + '_shp',
  folder: DRIVE_FOLDER,
  fileNamePrefix: FILE_PREFIX,
  fileFormat: 'SHP'
});
