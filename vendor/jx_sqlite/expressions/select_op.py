# encoding: utf-8
#
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http:# mozilla.org/MPL/2.0/.
#
# Contact: Kyle Lahnakoski (kyle@lahnakoski.com)
#


from dataclasses import dataclass
from typing import List

from jx_base.expressions import SelectOp as SelectOp_, LeavesOp, Variable, NULL
from jx_base.expressions.variable import get_variable
from jx_base.language import is_op
from jx_sqlite.expressions._utils import check
from jx_sqlite.expressions.sql_script import SqlScript
from mo_sqlite import (
    quote_column,
    SQL_COMMA,
    SQL_AS,
    SQL_SELECT,
    SQL,
    Log,
    ENABLE_TYPE_CHECKING, SQL_CR,
)
from mo_dots import concat_field, literal_field
from mo_json.types import to_jx_type, JX_IS_NULL
from mo_sql import ConcatSQL, SQL_FROM, sql_iso


class SelectOp(SelectOp_):
    @check
    def to_sql(self, schema):
        frum_sql = self.frum.to_sql(schema)
        schema = frum_sql.schema

        type = JX_IS_NULL
        sql_terms = []
        diff = False
        for name, expr in self:
            expr = get_variable(expr)

            if is_op(expr, Variable):
                var_name = expr.var
                cols = schema.leaves(var_name)
                if len(cols) == 0:
                    sql_terms.append(SelectOneSQL(name, NULL.to_sql(schema)))
                    continue
                else:
                    for rel_name, col in cols:
                        full_name = concat_field(name, rel_name)
                        type |= full_name + to_jx_type(col.json_type)
                        sql_terms.append(SelectOneSQL(full_name, Variable(col.es_column, col.json_type).to_sql(schema)))
            elif is_op(expr, LeavesOp):
                var_names = expr.term.vars()
                for var_name in var_names:
                    cols = schema.leaves(var_name)
                    for rel_name, col in cols:
                        full_name = concat_field(name,  literal_field(rel_name))
                        type |= full_name + to_jx_type(col.json_type)
                        sql_terms.append(SelectOneSQL(full_name, Variable(col.es_column, col.json_type).to_sql(schema)))
            else:
                type |= name + to_jx_type(expr.type)
                sql_terms.append(SelectOneSQL(name, expr.to_sql(schema)))

        return SqlScript(
            data_type=type,
            expr=ConcatSQL(SelectSQL(sql_terms), SQL_FROM, sql_iso(frum_sql)),
            frum=self,
            schema=schema,
        )


@dataclass
class SelectOneSQL(SQL):
    name: str
    value: SqlScript


class SelectSQL(SQL):
    __slots__ = ["terms"]

    def __init__(self, terms : List[SelectOneSQL]):
        if ENABLE_TYPE_CHECKING:
            if not isinstance(terms, list) or any(not isinstance(term, SelectOneSQL) for term in terms):
                Log.error("expecting list of SelectOne")
        self.terms = terms

    def __iter__(self):
        for s in SQL_SELECT:
            yield s
        comma = SQL_CR
        for term in self.terms:
            name, value = term.name, term.value
            yield from comma
            comma = SQL_COMMA
            yield from value
            yield from SQL_AS
            yield from quote_column(name)
