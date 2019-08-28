# encoding: utf-8
#
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http:# mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from __future__ import absolute_import, division, unicode_literals

import re

from jx_base.expressions import (AndOp as AndOp_, BasicEqOp as BasicEqOp_, BasicStartsWithOp as BasicStartsWithOp_, BooleanOp as BooleanOp_, CaseOp as CaseOp_, CoalesceOp as CoalesceOp_, ConcatOp as ConcatOp_, DivOp as DivOp_, EqOp as EqOp_, EsNestedOp as EsNestedOp_, ExistsOp as ExistsOp_, FALSE, FalseOp as FalseOp_, FindOp as FindOp_, GtOp as GtOp_, GteOp as GteOp_, InOp as InOp_, LengthOp as LengthOp_, Literal as Literal_, LtOp as LtOp_, LteOp as LteOp_, MissingOp as MissingOp_, NULL, NeOp as NeOp_, NotOp as NotOp_, NullOp, OrOp as OrOp_, PrefixOp as PrefixOp_, RegExpOp as RegExpOp_, ScriptOp as ScriptOp_, StringOp as StringOp_, SuffixOp as SuffixOp_, TRUE, TrueOp as TrueOp_, TupleOp, Variable as Variable_, WhenOp as WhenOp_, extend, is_literal)
from jx_base.language import Language, define_language, is_op
from jx_elasticsearch.es52.util import (
    MATCH_ALL,
    MATCH_NONE,
    es_and,
    es_exists,
    es_missing,
    es_not,
    es_or,
    es_script,
    pull_functions,
)
from jx_python.jx import value_compare
from mo_dots import Data, Null, is_container, is_many, literal_field, wrap
from mo_future import first
from mo_json import BOOLEAN, NESTED, OBJECT, python_type_to_json_type, STRING
from mo_logs import Log
from mo_math import MAX
from pyLibrary.convert import string2regexp, value2boolean


class Variable(Variable_):
    def to_esfilter(self, schema):
        v = self.var
        cols = schema.values(v, (OBJECT, NESTED))
        if len(cols) == 0:
            return MATCH_NONE
        elif len(cols) == 1:
            c = first(cols)
            return (
                {"term": {c.es_column: True}}
                if c.es_type == BOOLEAN
                else es_exists(c.es_column)
            )
        else:
            return es_and(
                [
                    {"term": {c.es_column: True}}
                    if c.es_type == BOOLEAN
                    else es_exists(c.es_column)
                    for c in cols
                ]
            )


class NeOp(NeOp_):
    def to_esfilter(self, schema):
        if not is_op(self.lhs, Variable_) or not is_literal(self.rhs):
            return self.to_es_script(schema).to_esfilter(schema)

        return es_not({"term": {self.lhs.var: self.rhs.to_esfilter(schema)}})


class CaseOp(CaseOp_):
    def to_esfilter(self, schema):
        if self.type == BOOLEAN:
            return (
                OrOp(
                    [AndOp([w.when, w.then]) for w in self.whens[:-1]] + self.whens[-1:]
                )
                .partial_eval()
                .to_esfilter(schema)
            )
        else:
            Log.error("do not know how to handle")
            return self.to_es_script(schema).script(schema).to_esfilter(schema)


class ConcatOp(ConcatOp_):
    def to_esfilter(self, schema):
        if is_op(self.value, Variable_) and is_literal(self.find):
            return {
                "regexp": {self.value.var: ".*" + string2regexp(self.find.value) + ".*"}
            }
        else:
            return self.to_es_script(schema).script(schema).to_esfilter(schema)


class Literal(Literal_):
    def to_esfilter(self, schema):
        return self.json


class CoalesceOp(CoalesceOp_):
    def to_esfilter(self, schema):
        return {"bool": {"should": [{"exists": {"field": v}} for v in self.terms]}}


class ExistsOp(ExistsOp_):
    def to_esfilter(self, schema):
        return self.field.exists().partial_eval().to_esfilter(schema)


@extend(NullOp)
def to_esfilter(self, schema):
    return MATCH_NONE


@extend(FalseOp_)
def to_esfilter(self, schema):
    return MATCH_NONE


def _inequality_to_esfilter(self, schema):
    if is_op(self.lhs, Variable_) and is_literal(self.rhs):
        cols = schema.leaves(self.lhs.var)
        if not cols:
            lhs = self.lhs.var  # HAPPENS DURING DEBUGGING, AND MAYBE IN REAL LIFE TOO
        elif len(cols) == 1:
            lhs = first(cols).es_column
        else:
            Log.error("operator {{op|quote}} does not work on objects", op=self.op)
        return {"range": {lhs: {self.op: self.rhs.value}}}
    else:
        script = Painless[self].to_es_script(schema)
        if script.miss is not FALSE:
            Log.error("inequality must be decisive")
        return {"script": es_script(script.expr)}


class GtOp(GtOp_):
    to_esfilter = _inequality_to_esfilter


class GteOp(GteOp_):
    to_esfilter = _inequality_to_esfilter


class LtOp(LtOp_):
    to_esfilter = _inequality_to_esfilter


class LteOp(LteOp_):
    to_esfilter = _inequality_to_esfilter







class DivOp(DivOp_):
    def to_esfilter(self, schema):
        return NotOp(self.missing()).partial_eval().to_esfilter(schema)


class EqOp(EqOp_):
    def partial_eval(self):
        lhs = ES52[self.lhs].partial_eval()
        rhs = ES52[self.rhs].partial_eval()

        if is_literal(lhs):
            if is_literal(rhs):
                return FALSE if value_compare(lhs.value, rhs.value) else TRUE
            else:
                return EqOp([rhs, lhs])  # FLIP SO WE CAN USE TERMS FILTER

        return EqOp([lhs, rhs])

    def to_esfilter(self, schema):
        if is_op(self.lhs, Variable_) and is_literal(self.rhs):
            rhs = self.rhs.value
            lhs = self.lhs.var
            cols = schema.leaves(lhs)
            if not cols:
                Log.warning("{{col}} does not exist while processing {{expr}}", col=lhs, expr=self.__data__())

            if is_container(rhs):
                if len(rhs) == 1:
                    rhs = rhs[0]
                else:
                    types = Data()  # MAP JSON TYPE TO LIST OF LITERALS
                    for r in rhs:
                        types[python_type_to_json_type[r.__class__]] += [r]
                    if len(types) == 1:
                        jx_type, values = first(types.items())
                        for c in cols:
                            if jx_type == c.jx_type:
                                return {"terms": {c.es_column: values}}
                        return FALSE.to_esfilter(schema)
                    else:
                        return (
                            OrOp(
                                [
                                    EqOp([self.lhs, values])
                                    for t, values in types.items()
                                ]
                            )
                            .partial_eval()
                            .to_esfilter(schema)
                        )

            for c in cols:
                if c.jx_type == BOOLEAN:
                    rhs = pull_functions[c.jx_type](rhs)
                if python_type_to_json_type[rhs.__class__] == c.jx_type:
                    return {"term": {c.es_column: rhs}}
            return FALSE.to_esfilter(schema)
        else:
            return (
                ES52[
                    CaseOp(
                        [
                            WhenOp(self.lhs.missing(), **{"then": self.rhs.missing()}),
                            WhenOp(self.rhs.missing(), **{"then": FALSE}),
                            BasicEqOp([self.lhs, self.rhs]),
                        ]
                    )
                ]
                .partial_eval()
                .to_esfilter(schema)
            )


class FindOp(FindOp_):
    def to_esfilter(self, schema):
        if is_op(self.value, Variable_) and is_literal(self.find) and self.default is NULL and is_literal(self.start) and self.start.value == 0:
            columns = [c for c in schema.leaves(self.value.var) if c.jx_type == STRING]
            if len(columns) == 1:
                return {"regexp": {columns[0].es_column: ".*" + re.escape(self.find.value) + ".*"}}
        # CONVERT TO SCRIPT, SIMPLIFY, AND THEN BACK TO FILTER
        self.simplified = False
        return ES52[Painless[self].partial_eval()].to_esfilter(schema)

    def missing(self):
        return NotOp(self)

    def exists(self):
        return BooleanOp(self)


class BasicEqOp(BasicEqOp_):
    def to_esfilter(self, schema):
        if is_op(self.lhs, Variable_) and is_literal(self.rhs):
            lhs = self.lhs.var
            cols = schema.leaves(lhs)
            if cols:
                lhs = first(cols).es_column
            rhs = self.rhs.value
            if is_many(rhs):
                if len(rhs) == 1:
                    return {"term": {lhs: first(rhs)}}
                else:
                    return {"terms": {lhs: rhs}}
            else:
                return {"term": {lhs: rhs}}
        else:
            return Painless[self].to_es_script(schema).to_esfilter(schema)


class MissingOp(MissingOp_):
    def to_esfilter(self, schema):
        if is_op(self.expr, Variable_):
            cols = schema.leaves(self.expr.var)
            if not cols:
                return MATCH_ALL
            elif len(cols) == 1:
                return es_missing(first(cols).es_column)
            else:
                return es_and([es_missing(c.es_column) for c in cols])
        else:
            return PainlessMissingOp.to_es_script(self, schema).to_esfilter(schema)


class NeOp(NeOp_):
    def to_esfilter(self, schema):
        if is_op(self.lhs, Variable_) and is_literal(self.rhs):
            columns = schema.values(self.lhs.var)
            if len(columns) == 0:
                return MATCH_ALL
            elif len(columns) == 1:
                return es_not({"term": {first(columns).es_column: self.rhs.value}})
            else:
                Log.error("column split to multiple, not handled")
        else:
            lhs = self.lhs.partial_eval().to_es_script(schema)
            rhs = self.rhs.partial_eval().to_es_script(schema)

            if lhs.many:
                if rhs.many:
                    return es_not(
                        ScriptOp(
                            (
                                "("
                                + lhs.expr
                                + ").size()==("
                                + rhs.expr
                                + ").size() && "
                                + "("
                                + rhs.expr
                                + ").containsAll("
                                + lhs.expr
                                + ")"
                            )
                        ).to_esfilter(schema)
                    )
                else:
                    return es_not(
                        ScriptOp(
                            "(" + lhs.expr + ").contains(" + rhs.expr + ")"
                        ).to_esfilter(schema)
                    )
            else:
                if rhs.many:
                    return es_not(
                        ScriptOp(
                            "(" + rhs.expr + ").contains(" + lhs.expr + ")"
                        ).to_esfilter(schema)
                    )
                else:
                    return es_not(
                        ScriptOp(
                            "(" + lhs.expr + ") != (" + rhs.expr + ")"
                        ).to_esfilter(schema)
                    )


class NotOp(NotOp_):
    def to_esfilter(self, schema):
        if is_op(self.term, MissingOp_) and is_op(self.term.expr, Variable_):
            # PREVENT RECURSIVE LOOP
            v = self.term.expr.var
            cols = schema.values(v, (OBJECT, NESTED))
            if len(cols) == 0:
                return MATCH_NONE
            elif len(cols) == 1:
                return {"exists": {"field": first(cols).es_column}}
            else:
                return es_or([{"exists": {"field": c.es_column}} for c in cols])
        else:
            operand = ES52[self.term].to_esfilter(schema)
            return es_not(operand)


class AndOp(AndOp_):
    def to_esfilter(self, schema):
        if not len(self.terms):
            return MATCH_ALL
        else:
            return es_and([ES52[t].to_esfilter(schema) for t in self.terms])


class OrOp(OrOp_):
    def to_esfilter(self, schema):

        if schema.snowflake.namespace.es_cluster.version.startswith("5."):
            # VERSION 5.2.x
            # WE REQUIRE EXIT-EARLY SEMANTICS, OTHERWISE EVERY EXPRESSION IS A SCRIPT EXPRESSION
            # {"bool":{"should"  :[a, b, c]}} RUNS IN PARALLEL
            # {"bool":{"must_not":[a, b, c]}} ALSO RUNS IN PARALLEL

            # OR(x) == NOT(AND(NOT(xi) for xi in x))
            output = es_not(
                es_and(
                    [NotOp(t).partial_eval().to_esfilter(schema) for t in self.terms]
                )
            )
            return output
        else:
            # VERSION 6.2+
            return es_or(
                [ES52[t].partial_eval().to_esfilter(schema) for t in self.terms]
            )


class BooleanOp(BooleanOp_):
    def to_esfilter(self, schema):
        if is_op(self.term, Variable_):
            return es_exists(self.term.var)
        elif is_op(self.term, FindOp):
            return self.term.to_esfilter(schema)
        else:
            return self.to_es_script(schema).to_esfilter(schema)


class LengthOp(LengthOp_):
    def to_esfilter(self, schema):
        return {"regexp": {self.var.var: self.pattern.value}}


class RegExpOp(RegExpOp_):
    def to_esfilter(self, schema):
        if is_literal(self.pattern) and is_op(self.var, Variable_):
            cols = schema.leaves(self.var.var)
            if len(cols) == 0:
                return MATCH_NONE
            elif len(cols) == 1:
                return {"regexp": {first(cols).es_column: self.pattern.value}}
            else:
                Log.error("regex on not supported ")
        else:
            Log.error("regex only accepts a variable and literal pattern")


@extend(TrueOp_)
def to_esfilter(self, schema):
    return MATCH_ALL


class EsNestedOp(EsNestedOp_):
    def to_esfilter(self, schema):
        if self.path.var == ".":
            return {"query": self.query.to_esfilter(schema)}
        else:
            return {
                "nested": {
                    "path": self.path.var,
                    "query": self.query.to_esfilter(schema),
                }
            }


class BasicStartsWithOp(BasicStartsWithOp_):
    def to_esfilter(self, schema):
        if not self.value:
            return MATCH_ALL
        elif is_op(self.value, Variable_) and is_literal(self.prefix):
            var = first(schema.leaves(self.value.var)).es_column
            return {"prefix": {var: self.prefix.value}}
        else:
            output = PainlessBasicStartsWithOp.to_es_script(self, schema)
            if output is false_script:
                return MATCH_NONE
            return output


class PrefixOp(PrefixOp_):
    def partial_eval(self):
        expr = PainlessStringOp(self.expr).partial_eval()
        prefix = PainlessStringOp(self.prefix).partial_eval()

        if prefix is NULL:
            return TRUE
        if expr is NULL:
            return FALSE

        return PrefixOp([expr, prefix])

    def to_esfilter(self, schema):
        if is_literal(self.prefix) and not self.prefix.value:
            return MATCH_ALL

        expr = self.expr

        if expr is NULL:
            return MATCH_NONE
        elif not expr:
            return MATCH_ALL

        if is_op(expr, StringOp_):
            expr = expr.term

        if is_op(expr, Variable_) and is_literal(self.prefix):
            col = first(schema.leaves(expr.var))
            if not col:
                return MATCH_NONE
            return {"prefix": {col.es_column: self.prefix.value}}
        else:
            return PainlessPrefixOp.to_es_script(self, schema).to_esfilter(schema)


class SuffixOp(SuffixOp_):
    def to_esfilter(self, schema):
        if not self.suffix:
            return MATCH_ALL
        elif is_op(self.expr, Variable_) and is_literal(self.suffix):
            var = first(schema.leaves(self.expr.var)).es_column
            return {"regexp": {var: ".*" + string2regexp(self.suffix.value)}}
        else:
            return PainlessSuffixOp.to_es_script(self, schema).to_esfilter(schema)


class InOp(InOp_):
    def to_esfilter(self, schema):
        if is_op(self.value, Variable_):
            var = self.value.var
            cols = schema.leaves(var)
            if not cols:
                return MATCH_NONE
            col = first(cols)
            var = col.es_column

            if is_literal(self.superset):
                if col.jx_type == BOOLEAN:
                    if is_literal(self.superset) and not is_many(self.superset.value):
                        return {"term": {var: value2boolean(self.superset.value)}}
                    else:
                        return {"terms": {var: map(value2boolean, self.superset.value)}}
                else:
                    if is_literal(self.superset) and not is_many(self.superset.value):
                        return {"term": {var: self.superset.value}}
                    else:
                        return {"terms": {var: self.superset.value}}
            elif is_op(self.superset, TupleOp):
                return OrOp([
                    EqOp([self.value, s])
                    for s in self.superset.terms
                ]).partial_eval().to_esfilter(schema)
        # THE HARD WAY
        return Painless[self].to_es_script(schema).to_esfilter(schema)


class ScriptOp(ScriptOp_):
    def to_esfilter(self, schema):
        return {"script": es_script(self.script)}


class WhenOp(WhenOp_):
    def to_esfilter(self, schema):
        output = OrOp(
            [
                AndOp([self.when, BooleanOp(self.then)]),
                AndOp([NotOp(self.when), BooleanOp(self.els_)]),
            ]
        ).partial_eval()

        return output.to_esfilter(schema)


def split_expression_by_depth(where, schema, output=None, var_to_depth=None):
    """
    :param where: EXPRESSION TO INSPECT
    :param schema: THE SCHEMA
    :param output:
    :param var_to_depth: MAP FROM EACH VARIABLE NAME TO THE DEPTH
    :return:
    """
    """
    It is unfortunate that ES can not handle expressions that
    span nested indexes.  This will split your where clause
    returning {"and": [filter_depth0, filter_depth1, ...]}
    """
    vars_ = where.vars()

    if var_to_depth is None:
        if not vars_:
            return Null
        # MAP VARIABLE NAMES TO HOW DEEP THEY ARE
        var_to_depth = {
            v.var: max(len(c.nested_path) - 1, 0) for v in vars_ for c in schema[v.var]
        }
        all_depths = set(var_to_depth.values())
        if len(all_depths) == 0:
            all_depths = {0}
        output = wrap([[] for _ in range(MAX(all_depths) + 1)])
    else:
        all_depths = set(var_to_depth[v.var] for v in vars_)

    if len(all_depths) == 1:
        output[first(all_depths)] += [where]
    elif is_op(where, AndOp_):
        for a in where.terms:
            split_expression_by_depth(a, schema, output, var_to_depth)
    else:
        Log.error("Can not handle complex where clause")

    return output


def split_expression_by_path(
    expr, schema, output=None, var_to_columns=None, lang=Language
):
    """
    :param expr: EXPRESSION TO INSPECT
    :param schema: THE SCHEMA
    :param output: THE MAP FROM PATH TO EXPRESSION WE WANT UPDATED
    :param var_to_columns: MAP FROM EACH VARIABLE NAME TO THE DEPTH
    :return: output: A MAP FROM PATH TO EXPRESSION
    """
    where_vars = expr.vars()
    if var_to_columns is None:
        var_to_columns = {v.var: schema.leaves(v.var) for v in where_vars}
        output = wrap({schema.query_path[0]: []})
        if not var_to_columns:
            output["\\."] += [expr]  # LEGIT EXPRESSIONS OF ZERO VARIABLES
            return output

    all_paths = set(c.nested_path[0] for v in where_vars for c in var_to_columns[v.var])

    if len(all_paths) == 0:
        output["\\."] += [expr]
    elif len(all_paths) == 1:
        output[literal_field(first(all_paths))] += [expr]
    elif is_op(expr, AndOp_):
        for w in expr.terms:
            split_expression_by_path(w, schema, output, var_to_columns, lang=lang)
    else:
        Log.error("Can not handle complex expression clause")

    return output


def get_type(var_name):
    type_ = var_name.split(".$")[1:]
    if not type_:
        return "j"
    return json_type_to_es_script_type.get(type_[0], "j")


json_type_to_es_script_type = {"string": "s", "boolean": "b", "number": "n"}


ES52 = define_language("ES52", vars())


from jx_elasticsearch.es52.painless import (
    false_script,
    PrefixOp as PainlessPrefixOp,
    SuffixOp as PainlessSuffixOp,
    MissingOp as PainlessMissingOp,
    StringOp as PainlessStringOp,
    BasicStartsWithOp as PainlessBasicStartsWithOp,
    Painless,
)
