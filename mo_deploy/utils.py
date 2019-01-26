# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from __future__ import division
from __future__ import unicode_literals

from collections import namedtuple
import operator
import re

from mo_future import text_type
from mo_logs import Log


class Requirement(object):
    __slots__ = ["name", "type", "version"]

    def __init__(self, name, type, version):
        self.name = name
        self.type = type
        self.version = version

    def __and__(self, other):
        if other == None:
            return self
        elif self.name != other.name:
            Log.error("Can not compare")

        if self.type is None:
            return other
        elif _op_to_func[self.type](self.version, other.version):
            if other.type is None:
                return self
            elif _op_to_func[other.type](other.version, self.version):
                return Requirement(
                    name=self.name, type="==", version=max(self.version, other.version)
                )
            else:
                return self
        else:
            if other.type is None:
                return self
            elif _op_to_func[other.type](other.version, self.version):
                return other
            else:
                Log.error("versions do not interesct {v1} and {v2}", v1=self, v2=other)

    def __data__(self):
        return text_type(self)

    def __str__(self):
        if self.type:
            return self.name + self.type + str(self.version)
        else:
            return self.name

    def __unicode__(self):
        if self.type:
            return self.name + self.type + unicode(self.version)
        else:
            return self.name


def parse_req(line):
    result = re.match(r"^\s*([\w-]+)\s*(>|>=|==|<=|<)\s*([\d.]+)", line)
    if not result:
        return Requirement(line, None, None)

    return Requirement(result.group(1), result.group(2), result.group(3))


_op_to_func = {
    ">": operator.gt,
    ">=": operator.ge,
    "==": operator.eq,
    "<=": operator.le,
    "<": operator.lt,
}
