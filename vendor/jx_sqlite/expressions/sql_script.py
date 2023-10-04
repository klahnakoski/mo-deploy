# encoding: utf-8
#
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http:# mozilla.org/MPL/2.0/.
#
# Contact: Kyle Lahnakoski (kyle@lahnakoski.com)
#


from jx_base.expressions import (
    SqlScript as _SQLScript,
    Expression,
)
from jx_base.models.schema import Schema
from jx_sqlite.expressions._utils import check
from mo_sqlite import SQL
from mo_imports import export
from mo_json import JxType
from mo_logs import Log


class SqlScript(_SQLScript, SQL):
    __slots__ = ("_data_type", "sql_expr", "frum", "schema")

    def __init__(
        self,
        data_type: JxType,
        expr: SQL,
        frum: Expression,
        schema: Schema
    ):
        object.__init__(self)
        if expr == None:
            Log.error("expecting expr")
        if not isinstance(expr, SQL):
            Log.error("Expecting SQL")
        if not isinstance(data_type, JxType):
            Log.error("Expecting JxType")
        if schema is None:
            Log.error("expecting schema")

        self._data_type = data_type  # JSON DATA TYPE
        self.sql_expr = expr
        self.frum = frum  # THE ORIGINAL EXPRESSION THAT MADE expr
        self.schema = schema

    @property
    def type(self) -> JxType:
        return self._data_type

    @property
    def name(self):
        return "."

    def __getitem__(self, item):
        if not self.many:
            if item == 0:
                return self
            else:
                Log.error("this is a primitive value")
        else:
            Log.error("do not know how to handle")

    def __iter__(self):
        """
        ASSUMED TO OVERRIDE SQL.__iter__()
        """
        return self.sql_expr.__iter__()

    def to_sql(self, schema):
        return self

    @property
    def sql(self):
        return self.sql_expr

    def __str__(self):
        return str(self.sql)

    @check
    def to_sql(self, schema):
        return self

    def missing(self, lang):
        return self.miss

    def __data__(self):
        return {"script": self.script}

    def __eq__(self, other):
        if not isinstance(other, _SQLScript):
            return False
        return self.sql_expr == other.sql_expr


export("jx_sqlite.expressions._utils", SqlScript)
export("jx_sqlite.expressions.or_op", SqlScript)
