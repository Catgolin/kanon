import json
from pathlib import Path

import requests_mock

from histropy.tables.htable import DISHAS_REQUEST_URL, HTable
from histropy.units.radices import BasedReal, RadixBase

Sexagesimal: BasedReal = RadixBase.name_to_base["sexagesimal"].type


class TestHTable:
    @requests_mock.Mocker(kw="mock")
    def test_read(self, **kwargs):
        path = Path(__file__).parent / 'data/table_content-180.json'
        with open(path, "r") as f:
            content = json.load(f)
        kwargs["mock"].get(DISHAS_REQUEST_URL.format(180), json=content)

        table: HTable = HTable.read(180, format="dishas")

        assert table.loc[Sexagesimal(1)] == table[0]

        assert table.loc[3][1] is Sexagesimal(6, 27, sign=-1)