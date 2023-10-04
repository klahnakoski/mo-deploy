# encoding: utf-8
#
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http:# mozilla.org/MPL/2.0/.
#
# Contact: Kyle Lahnakoski (kyle@lahnakoski.com)
#


from jx_base.expressions import CountOp as CountOp_
from jx_sqlite.expressions._utils import SQLang, check
from jx_sqlite.expressions.sql_script import SqlScript
from mo_sqlite import JoinSQL, SQL_SUM, sql_iso
from mo_json import JX_INTEGER


class CountOp(CountOp_):
    @check
    def to_sql(self, schema):
        acc = []
        for term in self.terms:
            m = term.missing(SQLang).invert(SQLang).partial_eval(SQLang)
            acc.append(sql_iso(m.to_sql(schema).frum))
        return SqlScript(
            data_type=JX_INTEGER,
            expr=JoinSQL(SQL_SUM, acc),
            frum=self,
            schema=schema,
        )
