# encoding: utf-8
#
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http:# mozilla.org/MPL/2.0/.
#
# Contact: Kyle Lahnakoski (kyle@lahnakoski.com)
#


from jx_base.expressions.base_multi_op import BaseMultiOp
from jx_base.expressions.literal import Literal
from mo_logs import logger


class PercentileOp(BaseMultiOp):
    op = "percentile"

    def __init__(self, term, percentile=None):
        if percentile is None:
            percentile = Literal(0.5)
        if not isinstance(percentile, float):
            logger.error("Expecting `percentile` to be a float")
        BaseMultiOp.__init__(self, term, Literal(percentile))
