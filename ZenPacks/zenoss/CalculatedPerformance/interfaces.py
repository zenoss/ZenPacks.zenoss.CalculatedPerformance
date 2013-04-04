##############################################################################
#
# Copyright (C) Zenoss, Inc. 2011, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

from Products.Zuul.interfaces import IRRDDataSourceInfo
from Products.Zuul.form import schema
from Products.Zuul.utils import ZuulMessageFactory as _t


class ICalculatedPerformanceDataSourceInfo(IRRDDataSourceInfo):
    description = schema.Text(
        title=_t(u'Description'),
        group=_t('Detail'),
        xtype='twocolumntextarea')

    expression = schema.Text(
        title=_t(u'Expression'),
        group=_t('Detail'),
        xtype='twocolumntextarea')

    # NB: We don't care about the cycle time so much as we recalculate
    # every minute.
    # cycletime = schema.Int(title=_t(u'Cycle Time (seconds)'))
