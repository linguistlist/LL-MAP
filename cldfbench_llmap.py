import json
import pathlib
import zipfile
import operator
import functools
import mimetypes
import collections

from lxml.etree import fromstring
from cldfbench import Dataset as BaseDataset
from sqlalchemy import create_engine
from clldutils.path import md5
from clldutils.markup import add_markdown_text
from clldutils import jsonlib

NOTES = """
LL-MAP is a project designed to integrate language information with data from the physical and 
social sciences by means of a Geographical Information System (GIS). The most important part of 
the project is a language subsystem, which relates geographical information on the area in which 
a language is or has been spoken to data on resources relevant to the language. Through a link to 
the MultiTree project, information on all proposed genetic relationships of the languages is made 
available and viewable in a geographic context. The system also includes ancillary information on 
topography, political boundaries, demographics, climate, vegetation, and wildlife, thus providing 
a basis upon which to build hypotheses about language movement across territory. Some cultural 
information, e.g., on religion, ethnicity, and economics, is also included.

The LL-MAP system encourages collaboration between linguists, historians, archaeologists, 
ethnographers, and geneticists, as they explore the relationship between language and cultural 
adaptation and change. We hope it will elicit new insights and hypotheses, and that it will also 
serve as an educational resource. As a GIS, LL-MAP has the potential to be a captivating 
instructional tool, presenting complex data in a way accessible to all educational levels. 
Finally, as a free service available online, LL-MAP increases public knowledge of lesser-known 
languages and cultures, underlining the importance of language and linguistic diversity to 
cultural understanding and scientific inquiry.

LL-MAP started as a joint project of Eastern Michigan University (EMU) and Stockholm University, 
in collaboration with several projects and archives in the USA, Europe, and Australia. 
Collaborators include PARADISEC, The Alaska Native Language Center, The Tibetan-Himalayan Digital 
Library, and The WALS Project, as well as noted documentary linguists. Technical development is 
directed by The Institute for Geospatial Research and Education (IGRE) at EMU. The project was 
funded by a three-year grant from the National Science Foundation.


## Current limitations

Version 0.1 of this dataset will not contain the scans of maps from books. Since there is ~7GB of
such images, they have to be archived in separate deposits and linked from this dataset once this
is done.
"""
# YAML frontmatter to support multitree references in CLDF markdown:
FRONTMATTER = """---
cldf-datasets: {
  multitree: https://doi.org/10.5281/zenodo.10006569#rdf:ID=multitree
}
---
"""


def content(e):
    return collections.OrderedDict((ee.tag, ee.text) for ee in e)


def translate_filter(e):
    def f(feature):
        op = any if e[0].tag == 'Or' else all
        conditions = []
        filters = list(e[0]) if e[0].tag in {'And', 'Or'} else list(e)
        for filter in filters:
            c = content(filter)
            op_ = operator.eq if filter.tag == 'PropertyIsEqualTo' else operator.ne
            if c['PropertyName'] in feature['properties']:
                conditions.append(op_(feature['properties'][c['PropertyName']], c['Literal']))
        return op(conditions)
    return f


class Symbolizer:
    __match__ = {
        'Point': 'PointSymbolizer',
        'Polygon': 'PolygonSymbolizer',
        'MultiPolygon': 'PolygonSymbolizer',
        'LineString': 'LineSymbolizer',
        'MultiLineString': 'LineSymbolizer',
    }

    def __init__(self, e):
        self.e = e
        self.type = e.tag
        self.tags = [ee.tag for ee in e]

    @functools.cached_property
    def properties(self):
        props = {}

        def valid_color(attr, sel):
            color = sel[0].text.upper()
            if len(color) == 7:
                return {attr: color}
            assert color == '#'
            return {}

        if self.type == 'PolygonSymbolizer':
            gfill = self.e.xpath('Fill/GraphicFill/Graphic/Mark/Stroke/CssParameter[@name="stroke"]')
            if gfill:
                props.update(valid_color('fill', gfill))
            elif self.e.xpath('Fill/*[@name="fill"]'):
                props.update(valid_color('fill', self.e.xpath('Fill/*[@name="fill"]')))
                if 'fill' in props:
                    props['fill-opacity'] = 0.4
            if self.e.xpath('Stroke/*[@name="stroke"]'):
                props.update(valid_color('stroke', self.e.xpath('Stroke/*[@name="stroke"]')))
            if self.e.xpath('Stroke/*[@name="stroke-width"]'):
                props['stroke-width'] = self.e.xpath('Stroke/*[@name="stroke-width"]')[0].text
        elif self.type == 'PointSymbolizer':
            # Graphic -> Mark -> Fill|Stroke
            if self.e.xpath('Graphic/Mark/Fill/*[@name="fill"]'):
                props.update(valid_color('marker-color', self.e.xpath('Graphic/Mark/Fill/*[@name="fill"]')))
        elif self.type == 'LineSymbolizer':
            assert set(self.tags).issubset({'Stroke'}), self.tags
        else:
            assert self.type == 'TextSymbolizer'
            if self.e.xpath('Label/PropertyName'):
                props['title'] = self.e.xpath('Label/PropertyName')[0].text
        return props

    def __call__(self, feature):
        if self.__match__[feature['geometry']['type']] == self.type:
            for k, v in self.properties.items():
                feature['properties'].setdefault(k, v)
        if self.type == 'TextSymbolizer':
            for k, v in self.properties.items():
                if k == 'title' and v in feature['properties']:
                    feature['properties'].setdefault('title', feature['properties'][v])


class Rule:
    def __init__(self, e):
        self.filter = lambda f: True
        self.symbolizers = []
        for ee in e:
            if ee.tag == 'Filter':
                self.filter = translate_filter(ee)
            elif ee.tag.endswith('Symbolizer'):
                self.symbolizers.append(Symbolizer(ee))

    def __call__(self, feature):
        if self.filter(feature):
            for s in self.symbolizers:
                s(feature)


class Style:
    def __init__(self, s):
        stag, etag = '<NamedLayer', '</NamedLayer>'
        _, _, e = s.partition(stag)
        e, _, _ = e.partition(etag)
        e = fromstring(stag + e.replace('ogc:', '').replace('""', '"') + etag)
        assert [ee.tag for ee in e] == ['Name', 'UserStyle']
        assert [ee.tag for ee in e[1]] == ['Name', 'FeatureTypeStyle']
        assert {ee.tag for ee in e[1][1]} == {'Rule'}

        self.rules = []
        for rule in e[1][1]:
            tags = [ee.tag for ee in rule]
            assert set(tags).issubset({'Title', 'Filter', 'PolygonSymbolizer', 'TextSymbolizer', 'LineSymbolizer', 'PointSymbolizer',
                                       'Name', 'Abstract', 'MaxScaleDenominator'}), str(tags)
            assert tags.count('Filter') <= 1
            self.rules.append(Rule(rule))
        # Name: point|polygon|labels
        # Abstract: Do not remove this line: [LLMAP decorator="carrow"]
        # MaxScaleDenominator: 310000, ...

    def __call__(self, feature):
        for rule in self.rules:
            rule(feature)


class Database:
    def __init__(self):
        self.conn = create_engine("postgresql+psycopg2://postgres@/llmap_db")

    def query(self, sql):
        return [r for r in self.conn.execute(sql)]


class Dataset(BaseDataset):
    dir = pathlib.Path(__file__).parent
    id = "llmap"

    def cldf_specs(self):  # A dataset must declare all CLDF sets it creates.
        return super().cldf_specs()

    def cmd_download(self, args):
        pass

    def cmd_readme(self, args):
        return add_markdown_text(BaseDataset.cmd_readme(self, args), NOTES, section='Description')

    def cmd_makecldf(self, args):
        t = args.writer.cldf.add_component(
            'ContributionTable',
            {
                'name': 'Language_IDs',
                'propertyUrl': 'http://cldf.clld.org/v1.0/terms.rdf#languageReference',
                'separator': ' ',
            },
            {
                'name': 'Media_IDs',
                'propertyUrl': 'http://cldf.clld.org/v1.0/terms.rdf#mediaReference',
                'separator': ' ',
            },
            {
                'name': 'Related',
                "dc:format": "text/markdown",
                "dc:conformsTo": "CLDF Markdown",
            }
            #id,name,title,author_fn,author_ln,description,digitized,source,image,related,datasource,license,downloaded,created,contact,creator,note

        )
        t.common_props['dc:description'] = (
            "Contributions in LL-map are descriptions of geographic maps, which are often linked "
            "to languoids and media files.")
        args.writer.cldf.add_component('LanguageTable')
        args.writer.cldf.add_component(
            'MediaTable',
            {
                'name': 'filesize',
                'datatype': 'integer',
            },
            {
                'name': 'Layer_Order',
                'datatype': 'integer',
                'dc:description': 'For GeoJSON data, this number fixes the order in which layers '
                                  'are to be added to a map.',
            }
        )

        gcodes = {l['code']: l['glottocode']
                  for l in self.etc_dir.read_csv('languages.csv', dicts=True) if l['glottocode']}

        db = Database()
        maps = {int(r['id']): r for r in self.etc_dir.read_csv('contributions.csv', dicts=True)}
        images = collections.defaultdict(list)
        for mid, map in maps.items():
            for img in map['image'].split('\n'):
                if img.strip():
                    p = self.raw_dir / 'maps' / img.strip()
                    assert p.exists()
                    if p.suffix == '.html':
                        for pp in p.parent.iterdir():
                            if pp.name != p.name:
                                images[mid].append(pp)
                    else:
                        images[mid].append(p)

        map2langs = collections.defaultdict(list)
        for row in db.query("""\
select mc.map_id, c.primary_name, c.code, c.standard_id, c.type from maps_map_codes as mc, maps_code as c
where mc.code_id = c.id"""):
            if row['map_id'] in maps:
                map2langs[row['map_id']].append((row['primary_name'], row['code'], row['standard_id'], row['type']))

        dataset_in_geojson = {int(p.stem): 1 for p in self.raw_dir.joinpath('geojson').glob('*.geojson') if not p.stem.endswith('_inc')}
        print(len(dataset_in_geojson))
        geojson = collections.defaultdict(list)
        for row in db.query("""select l.map_id_id, l.dataset_id_id, l.name, l.layer_order, l.style from maps_layer as l"""):
            # style:  https://schemas.opengis.net/sld/ReadMe.txt
            if row['map_id_id'] in maps:
                p = self.raw_dir / 'geojson' / '{}.geojson'.format(row['dataset_id_id'])
                if p.exists():
                    geojson[row['map_id_id']].append(
                        (p, row['name'], Style(row['style']) if row['style'] else None, row['layer_order']))
                    del dataset_in_geojson[row['dataset_id_id']]

        with zipfile.ZipFile(self.cldf_dir / 'geojson.zip', mode='w', compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zip:
            lids, fids = set(), set()
            for mid, map in maps.items():
                if (mid not in images) and (mid not in geojson):
                    assert map['source'] or map['datasource']
                for name, code, sid, type in map2langs.get(mid, []):
                    if code not in lids:
                        args.writer.objects['LanguageTable'].append(dict(
                            ID=code,
                            Name=name,
                            Glottocode=gcodes.get(code),
                        ))
                        lids.add(code)
                lfids = set()
                for p in images.get(mid, []):
                    fid = md5(p)
                    lfids.add(fid)
                    if fid not in fids:
                        args.writer.objects['MediaTable'].append(dict(
                            ID=fid,
                            Name=p.name,
                            Media_Type=mimetypes.guess_type(p.name)[0],
                            Download_URL=str(p),
                            filesize=p.stat().st_size,
                        ))
                        fids.add(fid)
                for p, title, style, layer_order in geojson.get(mid, []):
                    geo = jsonlib.load(p)
                    for feature in geo['features']:
                        if style:
                            style(feature)
                        if 'ID' in feature['properties']:
                            del feature['properties']['ID']
                    zip.writestr(p.name, json.dumps(geo, separators=(',', ':')))
                    fid = p.name.replace('.', '_')
                    lfids.add(fid)
                    if fid not in fids:
                        args.writer.objects['MediaTable'].append(dict(
                            ID=fid,
                            Name=p.name,
                            Description=title,
                            Layer_Order=int(layer_order),
                            Media_Type='application/geo+json',
                            Download_URL='file:///geojson.zip',
                            Path_In_Zip=p.name,
                        ))
                        fids.add(fid)
                args.writer.objects['ContributionTable'].append(dict(
                    ID=str(mid),
                    Name=map['name'],
                    Description=map['description'],
                    Contributor='{} {}'.format(map['author_fn'], map['author_ln']) if map['author_fn'] else map['creator'],
                    Language_IDs=sorted(code for _, code, _, _ in map2langs.get(mid, [])),
                    Media_IDs=sorted(lfids),
                    Related='{}{}'.format(
                        FRONTMATTER if 'multitree' in map['related'] else '', map['related'])
                    if map['related'] else None,
                ))
