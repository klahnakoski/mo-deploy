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

from copy import copy
from math import isnan

from jx_base import DataClass
from jx_base import Snowflake
from jx_sqlite.sqlite import quote_column, SQL, SQL_DESC, SQL_ASC
from mo_dots import (
    Data,
    concat_field,
    is_data,
    is_list,
    join_field,
    split_field,
    is_sequence,
    missing, is_missing, coalesce,
)
from mo_future import is_text, text
from mo_json import BOOLEAN, ARRAY, NUMBER, OBJECT, STRING, json2value, T_BOOLEAN, INTEGER
from mo_json.typed_encoder import untype_path
from mo_logs import Log
from mo_math import randoms
from mo_times import Date
from mo_json.types import _B, _I, _N, _T, _S, _A, T_ARRAY, T_TEXT, T_NUMBER, T_INTEGER, IS_PRIMITIVE_KEY

DIGITS_TABLE = "__digits__"
ABOUT_TABLE = "meta.about"


GUID = "_id"  # user accessible, unique value across many machines
UID = "__id__"  # internal numeric id for single-database use
ORDER = "__order__"
PARENT = "__parent__"
COLUMN = "__column"

ALL_TYPES = "bns"


def unique_name():
    return randoms.string(20)


def column_key(k, v):
    if v == None:
        return None
    elif isinstance(v, bool):
        return k, "boolean"
    elif is_text(v):
        return k, "string"
    elif is_list(v):
        return k, None
    elif is_data(v):
        return k, "object"
    elif isinstance(v, Date):
        return k, "number"
    else:
        return k, "number"


POS_INF = float("+inf")


def value_to_jx_type(v):
    if v == None:
        return None
    elif isinstance(v, bool):
        return BOOLEAN
    elif is_text(v):
        return STRING
    elif is_data(v):
        return OBJECT
    elif isinstance(v, float):
        if isnan(v) or abs(v) == POS_INF:
            return None
        return NUMBER
    elif isinstance(v, (int, Date)):
        return NUMBER
    elif is_sequence(v):
        return ARRAY
    return None


def table_alias(i):
    """
    :param i:
    :return:
    """
    return "__t" + text(i) + "__"


def get_document_value(document, column):
    """
    RETURN DOCUMENT VALUE IF MATCHES THE column (name, type)

    :param document: THE DOCUMENT
    :param column: A (name, type) PAIR
    :return: VALUE, IF IT IS THE SAME NAME AND TYPE
    """
    v = document.get(split_field(column.name)[0], None)
    return get_if_type(v, column.type)


def get_if_type(value, type):
    if is_type(value, type):
        if type == "object":
            return "."
        if isinstance(value, Date):
            return value.unix
        return value
    return None


def is_type(value, type):
    if value == None:
        return False
    elif is_text(value) and type == "string":
        return value
    elif is_list(value):
        return False
    elif is_data(value) and type == "object":
        return True
    elif isinstance(value, (int, float, Date)) and type == "number":
        return True
    return False


def typed_column(name, sql_key):
    if len(sql_key) > 1:
        Log.error("not expected")
    return concat_field(name, "$" + sql_key)


def untyped_column(column_name):
    """
    :param column_name:  DATABASE COLUMN NAME
    :return: (NAME, TYPE) PAIR
    """
    if "$" in column_name:
        path = split_field(column_name)
        return join_field([p for p in path[:-1] if p != "$a"]), path[-1][1:]
    elif column_name in [GUID]:
        return column_name, "n"
    else:
        return column_name, None


untype_field = untyped_column


def _make_column_name(number):
    return COLUMN + text(number)


sql_aggs = {
    "avg": "AVG",
    "average": "AVG",
    "count": "COUNT",
    "first": "FIRST_VALUE",
    "last": "LAST_VALUE",
    "max": "MAX",
    "maximum": "MAX",
    "median": "MEDIAN",
    "min": "MIN",
    "minimum": "MIN",
    "sum": "SUM",
    "add": "SUM",
}

STATS = {
    "count": "COUNT({{value}})",
    "std": "SQRT((1-1.0/COUNT({{value}}))*VARIANCE({{value}}))",
    "min": "MIN({{value}})",
    "max": "MAX({{value}})",
    "sum": "SUM({{value}})",
    "median": "MEDIAN({{value}})",
    "sos": "SUM({{value}}*{{value}})",
    "var": "(1-1.0/COUNT({{value}}))*VARIANCE({{value}})",
    "avg": "AVG({{value}})",
}

quoted_GUID = quote_column(GUID)
quoted_UID = quote_column(UID)
quoted_ORDER = quote_column(ORDER)
quoted_PARENT = quote_column(PARENT)


def sql_text_array_to_set(column):
    def _convert(row):
        text = row[column]
        if text == None:
            return set()
        else:
            value = json2value(row[column])
            return set(value) - {None}

    return _convert


def get_column(column, json_type=None, default=None):
    """
    :param column: The column you want extracted
    :return: a function that can pull the given column out of sql resultset
    """

    to_type = json_type_to_python_type.get(json_type)

    if to_type is None:
        def _get(row):
            value = row[column]
            if is_missing(value):
                return default
            return value

        return _get

    def _get_type(row):
        value = row[column]
        if is_missing(value):
            return default
        return to_type(value)

    return _get_type


json_type_to_python_type = {T_BOOLEAN: bool}


def set_column(row, col, child, value):
    """
    EXECUTE `row[col][child]=value` KNOWING THAT row[col] MIGHT BE None
    :param row:
    :param col:
    :param child:
    :param value:
    :return:
    """
    if child == ".":
        row[col] = value
    else:
        column = row[col]

        if column is None:
            column = row[col] = {}
        Data(column)[child] = value


def copy_cols(cols, nest_to_alias):
    """
    MAKE ALIAS FOR EACH COLUMN
    :param cols:
    :param nest_to_alias:  map from nesting level to subquery alias
    :return:
    """
    output = set()
    for c in cols:
        c = copy(c)
        c.es_index = nest_to_alias[c.nested_path[0]]
        output.add(c)
    return output


ColumnMapping = DataClass(
    "ColumnMapping",
    [
        {  # EDGES ARE AUTOMATICALLY INCLUDED IN THE OUTPUT, USE THIS TO INDICATE EDGES SO WE DO NOT DOUBLE-PRINT
            "name": "is_edge",
            "default": False,
        },
        {  # TRACK NUMBER OF TABLE COLUMNS THIS column REPRESENTS
            "name": "num_push_columns",
            "nulls": True,
        },
        {  # NAME OF THE PROPERTY (USED BY LIST FORMAT ONLY)
            "name": "push_list_name",
            "nulls": True,
        },
        {  # PATH INTO COLUMN WHERE VALUE IS STORED ("." MEANS COLUMN HOLDS PRIMITIVE VALUE)
            "name": "push_column_child",
            "nulls": True,
        },
        {"name": "push_column_index", "nulls": True},  # THE COLUMN NUMBER
        {  # THE COLUMN NAME FOR TABLES AND CUBES (WITH NO ESCAPING DOTS, NOT IN LEAF FORM)
            "name": "push_column_name",
            "nulls": True,
        },
        {"name": "pull", "nulls": True},  # A FUNCTION THAT WILL RETURN A VALUE
        {  # A LIST OF MULTI-SQL REQUIRED TO GET THE VALUE FROM THE DATABASE
            "name": "sql",
        },
        "type",  # THE NAME OF THE JSON DATA TYPE EXPECTED
        {  # A LIST OF PATHS EACH INDICATING AN ARRAY
            "name": "nested_path",
            "type": list,
            "default": ["."],
        },
        "column_alias",
    ],
    constraint={"and": [
        {"in": {"type": ["0", "boolean", "number", "string", "object"]}},
        {"gte": [{"length": "nested_path"}, 1]},
    ]},
)

sqlite_type_to_simple_type = {
    "TEXT": STRING,
    "REAL": NUMBER,
    "INT": INTEGER,
    "INTEGER": INTEGER,
    "TINYINT": BOOLEAN,
}

sqlite_type_to_type_key = {
    "ARRAY": _A,
    "TEXT": _S,
    "REAL": _N,
    "INTEGER": _I,
    "TINYINT": _B,
    "TRUE": _B,
    "FALSE": _B,
}

type_key_json_type = {
    _A: T_ARRAY,
    _S: T_TEXT,
    _N: T_NUMBER,
    _I: T_INTEGER,
    _B: T_BOOLEAN,
}

sort_to_sqlite_order = {
    -1: SQL_DESC,
    0: SQL_ASC,
    1: SQL_ASC
}

class BasicSnowflake(Snowflake):
    def __init__(self, query_paths, columns):
        self._query_paths = query_paths
        self._columns = columns

    @property
    def query_paths(self):
        return self._query_paths

    @property
    def columns(self):
        return self._columns

    @property
    def column(self):
        return ColumnLocator(self._columns)


class ColumnLocator(object):
    def __init__(self, columns):
        self.columns = columns

    def __getitem__(self, column_name):
        return [c for c in self.columns if untype_path(c.name) == column_name]
