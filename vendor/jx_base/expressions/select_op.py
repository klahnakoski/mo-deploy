# encoding: utf-8
#
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http:# mozilla.org/MPL/2.0/.
#
# Contact: Kyle Lahnakoski (kyle@lahnakoski.com)
#

from __future__ import absolute_import, division, unicode_literals

from typing import Dict, Tuple, Iterable

from jx_base.expressions._utils import TYPE_CHECK, simplified
from jx_base.expressions.expression import jx_expression, Expression, _jx_expression
from jx_base.expressions.null_op import NULL
from jx_base.expressions.variable import Variable
from jx_base.expressions.leaves_op import LeavesOp
from jx_base.expressions.literal import Literal, ZERO
from jx_base.language import is_op
from jx_base.utils import is_variable_name
from mo_json import union_type
from mo_dots import (
    to_data,
    listwrap,
    coalesce,
    dict_to_data,
    from_data,
    Data,
    split_field,
    join_field,
    literal_field,
)
from mo_future import is_text
from mo_imports import export
from mo_logs import Log
from mo_math import UNION, is_number


class SelectOp(Expression):
    has_simple_form = True

    def __init__(self, terms):
        """
        :param terms: list OF {"name":name, "value":value} DESCRIPTORS
        """
        if TYPE_CHECK and (
            not isinstance(terms, list)
            or not all(isinstance(term, dict) for term in terms)
            or any(not term.get("name") for term in terms)
            or any(not term.get("aggregate") for term in terms)
            or any(not isinstance(term.get("default"), Expression) for term in terms)
        ):
            Log.error("expecting list of dicts with 'name' and 'aggreegate' property")
        Expression.__init__(self, None)
        self.terms: List[Dict[str, Expression]] = terms
        self.data_type = union_type(*(t["name"] + t["value"].type for t in terms))

    @classmethod
    def define(cls, expr):
        selects = to_data(expr).select
        terms = []
        for t in listwrap(selects):
            if is_op(t, SelectOp):
                terms = t.terms
            elif is_text(t):
                if not is_variable_name(t):
                    Log.error(
                        "expecting {{value}} a simple dot-delimited path name", value=t
                    )
                terms.append({"name": t, "value": _jx_expression(t, cls.lang)})
            elif t.name == None:
                if t.value == None:
                    Log.error(
                        "expecting select parameters to have name and value properties"
                    )
                elif is_text(t.value):
                    if not is_variable_name(t):
                        Log.error(
                            "expecting {{value}} a simple dot-delimited path name",
                            value=t.value,
                        )
                    else:
                        terms.append({
                            "name": t.value,
                            "value": _jx_expression(t.value, cls.lang),
                        })
                else:
                    Log.error("expecting a name property")
            else:
                terms.append({"name": t.name, "value": jx_expression(t.value)})
        return SelectOp(terms)

    @staticmethod
    def normalize_one(select, frum, format, schema=None):

        if is_text(select):
            if select == "*":
                return SelectOp([{
                    "name": ".",
                    "value": LeavesOp(Variable(".")),
                    "aggregate": "none",
                    "default": NULL,
                }])
            select = Data(value=select)
        else:
            select = to_data(select)
            if select.value == None and select.aggregate == None:
                Log.error("Expecting `value` or `aggregate` in select")

        canonical = Data()

        name = select.name
        value = select.value
        aggregate = select.aggregate

        if not value:
            canonical.name = coalesce(name, aggregate)
            canonical.value = jx_expression(".", schema=schema)
            canonical.aggregate = aggregate

            if not canonical.name and len(select):
                Log.error(BAD_SELECT, select=select)
        elif is_text(value):
            if value == ".":
                canonical.name = coalesce(name, aggregate, ".")
                canonical.value = jx_expression(value, schema=schema)
            elif value.endswith(".*"):
                root_name = value[:-2]
                canonical.name = coalesce(name, root_name)
                value = jx_expression(root_name, schema=schema)
                if not is_op(value, Variable):
                    Log.error("do not know what to do")
                canonical.value = LeavesOp(value, prefix=select.prefix)
            elif value.endswith("*"):
                root_name = value[:-1]
                path = split_field(root_name)

                canonical.name = coalesce(name, aggregate, join_field(path[:-1]))
                expr = jx_expression(root_name, schema=schema)
                if not is_op(expr, Variable):
                    Log.error("do not know what to do")
                canonical.value = LeavesOp(
                    expr, prefix=Literal((select.prefix or "") + path[-1] + ".")
                )
            else:
                canonical.name = coalesce(name, value.lstrip("."), aggregate)
                canonical.value = jx_expression(value, schema=schema)

        elif is_number(canonical.value):
            canonical.name = coalesce(name, text(canonical.value))
            canonical.value = jx_expression(value, schema=schema)
        else:
            canonical.name = coalesce(name, value, aggregate)
            canonical.value = jx_expression(value, schema=schema)

        canonical.aggregate = coalesce(
            canonical_aggregates[aggregate].name, aggregate, "none"
        )
        canonical.default = coalesce(
            jx_expression(select.default, schema=schema),
            canonical_aggregates[canonical.aggregate].default,
        )

        if format != "list" and canonical.name != ".":
            canonical.name = literal_field(canonical.name)

        return SelectOp([from_data(canonical)])

    @simplified
    def partial_eval(self, lang):
        new_terms = []
        diff = False
        for name, expr, agg, default in self:
            new_expr = expr.partial_eval(lang)
            if new_expr is expr:
                new_terms.append({
                    "name": name,
                    "value": expr,
                    "aggregate": agg,
                    "default": default,
                })
                continue
            diff = True

            if expr is NULL:
                continue
            elif is_op(expr, SelectOp):
                for t_name, t_value in expr.terms:
                    new_terms.append({
                        "name": concat_field(name, t_name),
                        "value": t_value,
                        "aggregate": agg,
                        "default": default,
                    })
            else:
                new_terms.append({
                    "name": name,
                    "value": new_expr,
                    "aggregate": agg,
                    "default": default,
                })
                diff = True
        if diff:
            return SelectOp(new_terms)
        else:
            return self

    def __iter__(self) -> Iterable[Tuple[str, Expression, str]]:
        """
        :return:  return iterator of (name, value) tuples
        """
        for term in self.terms:
            yield term["name"], term["value"], term["aggregate"], term["default"]

    def __data__(self):
        return {"select": [
            {
                "name": name,
                "value": value.__data__(),
                "aggregate": "none",
                "default": NULL,
            }
            for name, value, agg, default in self
        ]}

    def vars(self):
        return UNION(value for _, value in self)

    def map(self, map_):
        return SelectOp([
            {
                "name": name,
                "value": value.map(map_),
                "aggregate": agg,
                "default": default,
            }
            for name, value, agg, default in self
        ])


select_nothing = SelectOp([])
select_self = SelectOp([{
    "name": ".",
    "value": Variable("."),
    "aggregate": "none",
    "default": NULL,
}])

canonical_aggregates = dict_to_data({
    "none": {"name": ".", "default": NULL},
    "cardinality": {"name": "cardinality", "default": ZERO},
    "count": {"name": "count", "default": ZERO},
    "min": {"name": "minimum", "default": NULL},
    "minimum": {"name": "minimum", "default": NULL},
    "max": {"name": "maximum", "default": NULL},
    "maximum": {"name": "maximum", "default": NULL},
    "add": {"name": "sum", "default": NULL},
    "avg": {"name": "average", "default": NULL},
    "average": {"name": "average", "default": NULL},
    "mean": {"name": "average", "default": NULL},
})


export("jx_base.expressions.nested_op", select_self)
