# encoding: utf-8
#
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http:# mozilla.org/MPL/2.0/.
#
# Contact: Kyle Lahnakoski (kyle@lahnakoski.com)
#


from jx_base.expressions import BasicNotOp as BasicNotOp_
from jx_sqlite.expressions._utils import check, SQLang
from jx_sqlite.expressions.sql_script import SqlScript
from mo_sqlite import sql_iso, SQL_NOT, ConcatSQL
from mo_json.types import JX_BOOLEAN


class BasicNotOp(BasicNotOp_):
    @check
    def to_sql(self, schema):
        term = self.term.partial_eval(SQLang).to_sql(schema)
        return SqlScript(
            data_type=JX_BOOLEAN,
            expr=ConcatSQL(SQL_NOT, sql_iso(term.frum)),
            frum=self,
            schema=schema,
        )