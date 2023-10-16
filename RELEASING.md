# Releasing LL-MAP

```shell
cldfbench makecldf cldfbench_llmap.py --glottolog-version v4.8 --with-zenodo --with-cldfreadme
pytest
```

```shell
cldfbench readme cldfbench_llmap.py
```

```shell
rm llmap.sqlite
cldf createdb cldf llmap.sqlite
```

```shell
cldferd --format compact.svg cldf > erd.svg
```