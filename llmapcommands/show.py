"""

"""
import json
import pathlib

from cldfbench_llmap import Dataset
from clldutils.misc import data_url

HTML_TMPL = """
<!DOCTYPE html>
<html lang="en">
<head>
	<base target="_top">
	<meta charset="utf-8">
	<meta name="viewport" content="width=device-width, initial-scale=1">
	
	<title>---</title>
<!-- CSS Reset -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/normalize/8.0.1/normalize.css">

<!-- Milligram CSS -->
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/milligram/1.4.1/milligram.css">	
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" integrity="sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=" crossorigin=""/>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js" integrity="sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=" crossorigin=""></script>

	<style>
		html, body {
			height: 100%;
			margin: 0;
		}
		.leaflet-container {
			height: 400px;
			width: 600px;
			max-width: 100%;
			max-height: 100%;
		}
	</style>

	
</head>
<body>

<div class="container">
    <h1>TITLE</h1>
  <div class="row">
  <div class="column">
<p>
DESCRIPTION
</p>
</div>
</div>
<div class="row">
  <div class="column">
CONTENT
</div>
</div>
</body>
</html>
"""

LEAFLET_TMPL = """
<div id='map' class='leaflet-container'></div>

<script>
var geojsons = [GEOJSONS],
    base = L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19,
        attribution: '&copy; <a href="http://www.openstreetmap.org/copyright">OpenStreetMap</a>'
    }),
    layers = [],
    overlays = [],
    layer,
    bounds;

layers.push(base);

function onEachFeature(feature, layer) {
    if (feature.properties) {
        var html = '<table><tbody>';
        for (prop in feature.properties) {
            html += '<tr><th>' + prop + '</th>';
            html += '<td>' + feature.properties[prop] + '</td></tr>';
        }
        layer.bindPopup(html + '</tbody></table>');
    }
}

for (let i = 0; i < geojsons.length; i++) {
    layer = L.geoJSON(geojsons[i], {onEachFeature: onEachFeature});
    if (bounds) {
        bounds.extend(layer);
    } else {
        bounds = layer.getBounds();
    }
    layers.push(layer);
    overlays.push(layer);
}
const map = L.map('map', {'layers': layers});
map.fitBounds(bounds);
var layerControl = L.control.layers([base], overlays).addTo(map);
</script>
"""

IMAGE_TMPL = """
<div>
    <img width="100%" src="SRC" />
</div>
"""


def register(parser):
    parser.add_argument('mid')


def run(args):
    ds = Dataset()
    for row in ds.cldf_reader().objects('ContributionTable'):
        if row.id == args.mid:
            print(row.cldf.name)
            print('')
            print(row.cldf.description)

            for l in row.all_related('languageReference'):
                print(l.cldf.name, l.cldf.glottocode)

            leaflet_maps, image_maps = [], []
            for i, media in enumerate(row.all_related('mediaReference')):
                if media.cldf.mediaType == 'application/geo+json':
                    leaflet_maps.append(pathlib.Path(media.cldf.downloadUrl.unsplit()).read_text(encoding='utf8')
                    )
                else:
                    image_maps.append(IMAGE_TMPL.replace(
                        'SRC',
                         data_url(pathlib.Path(media.cldf.downloadUrl.unsplit()), mimetype=media.cldf.mediaType)))

                #print(media.cldf.name, media.cldf.downloadUrl.unsplit())
            page = HTML_TMPL.replace(
                'CONTENT',
                '\n'.join(image_maps + [LEAFLET_TMPL.replace('GEOJSONS', ', '.join(leaflet_maps))])
            ).replace('TITLE', row.cldf.name).replace('DESCRIPTION', row.cldf.description)
            pathlib.Path('res.html').write_text(page, encoding='utf8')
