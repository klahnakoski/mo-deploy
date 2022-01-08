# encoding: utf-8
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.
#
# Author: Kyle Lahnakoski (kyle@lahnakoski.com)
#
from __future__ import division, unicode_literals

import operator
import re

from mo_future import text

from mo_logs import Log
from mo_times import Date

TODAY = int(Date.now().format("%y%j"))


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
        elif _op_to_func[self.type](other.version, self.version):
            if other.type is None:
                return self
            elif _op_to_func[other.type](self.version, other.version):
                return Requirement(
                    name=self.name, type="==", version=max(self.version, other.version)
                )
            else:
                return self
        else:
            if other.type is None:
                return self
            elif _op_to_func[other.type](self.version, other.version):
                return other
            else:
                # IF YOU ARE HERE, THEN THERE IS MORE THAN ONE PATH TO THIS LIBRARY
                # AND THE AUTOMATION HAS DECIDED ON TWO DIFFERENT VERSIONS.  LOCK THE
                # VERSIONS FOR ALL DEPENDENCIES, OR UNLOCK THEM ALL.
                # FANCY DEPENDENCY RESOLUTION IS NOT SUPPORTED
                Log.error("versions do not intersect {v1} and {v2}", v1=self.version, v2=other.version)

    def __data__(self):
        return text(self)

    def __str__(self):
        if self.type:
            return self.name + self.type + text(self.version)
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
