import pathlib
import mimetypes
import collections

from cldfbench import Dataset as BaseDataset
from sqlalchemy import create_engine
from clldutils.path import md5


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
        """
        Download files to the raw/ directory. You can use helpers methods of `self.raw_dir`, e.g.

        >>> self.raw_dir.download(url, fname)
        """
        pass

    def cmd_makecldf(self, args):
        """
        Convert the raw data to a CLDF dataset.

        >>> args.writer.objects['LanguageTable'].append(...)
        """
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
            }
        ) # application/geo+json

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

        dataset_in_geojson = {int(p.stem): 1 for p in self.raw_dir.joinpath('geojson').glob('*.geojson')}
        print(len(dataset_in_geojson))
        geojson = collections.defaultdict(list)
        for row in db.query("""select l.map_id_id, l.dataset_id_id from maps_layer as l"""):
            if row['map_id_id'] in maps:
                p = self.raw_dir / 'geojson' / '{}.geojson'.format(row['dataset_id_id'])
                if p.exists():
                    geojson[row['map_id_id']].append(p)
                    #print('+', row)
                    del dataset_in_geojson[row['dataset_id_id']]
                else:
                    #print('-', row)
                    pass
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
            for p in geojson.get(mid, []):
                fid = md5(p)
                lfids.add(fid)
                if fid not in fids:
                    args.writer.objects['MediaTable'].append(dict(
                        ID=fid,
                        Name=p.name,
                        Media_Type='application/geo+json',
                        Download_URL=str(p),
                        filesize=p.stat().st_size,
                    ))
                    fids.add(fid)
            args.writer.objects['ContributionTable'].append(dict(
                ID=str(mid),
                Name=map['name'],
                Description=map['description'],
                Contributor='',
                Language_IDs=sorted(code for _, code, _, _ in map2langs.get(mid, [])),
                Media_IDs=sorted(lfids),
            ))

        #print(len(dataset_in_geojson))
