##############################################################################
#
# Copyright (C) Zenoss, Inc. 2015-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

from zope.interface import Attribute

from Products.Zuul.form import schema
from Products.Zuul.interfaces import IFacade
from Products.Zuul.interfaces.component import IComponentInfo
from Products.Zuul.interfaces.template import IRRDDataSourceInfo, IDataPointInfo
from Products.Zuul.utils import ZuulMessageFactory as _t


class IAggregatingDataSourceInfo(IRRDDataSourceInfo):
    """
    Defines what fields should be displayed on the edit dialog
    for this datasource in the Zenoss web interface.
    """

    cycletime = schema.TextLine(
        title=_t(u'Cycle Time (seconds)'))
    method = schema.TextLine(
        title=_t(u'Method'),
        group=_t(u'Target'))
    datasource = schema.TextLine(
        title=_t(u'Datasource'),
        group=_t(u'Target'))
    datapoint = schema.TextLine(
        title=_t(u'Datapoint'),
        group=_t(u'Target'))
    rra = schema.TextLine(
        title=_t(u'RRA'),
        group=_t(u'Target'))
    asRate = schema.Bool(
        title=_t(u'Rate?'),
        group=_t(u'Target'))
    debug = schema.Bool(
        title=_t(u'Verbose Debug Logging'))

    minimumInterval = schema.Int(
        title=_t(u'Minimum Interval (seconds)'))
    useBasisInterval = schema.Bool(
        title=_t(u'Use Basis Interval'))
    maximumInterval = schema.Int(
        title=_t(u'Maximum Interval (seconds)'))


class IAggregatingDataPointInfo(IDataPointInfo):

    operation = schema.TextLine(
        title=_t(u"Operation"),
        group=_t(u"Aggregation"))
    arguments = schema.TextLine(
        title=_t(u"Arguments (comma-separated)"),
        group=_t(u"Aggregation"))


class IElementPoolInfo(IComponentInfo):

    members = Attribute("Members of this pool")
    # NOTE: this field must be on the on the "fields" of the component grid
    # for the members grid to be displayed.
    numberOfMembers = Attribute(
        "The count of the number of members in this pool")


class IElementPoolFacade(IFacade):
    """A facade for the ElementPool facade."""
    pass


class ICalculatedPerformanceDataSourceInfo(IRRDDataSourceInfo):

    cycletime = schema.Int(
        title=_t(u'Cycle Time (seconds)'))

    description = schema.Text(
        title=_t(u'Description'),
        group=_t('Detail'),
        xtype='twocolumntextarea')

    expression = schema.Text(
        title=_t(u'Expression'),
        group=_t('Detail'),
        xtype='twocolumntextarea')

    extraContexts = schema.Text(
        title=_t(u'Extra Contexts'),
        group=_t('Detail'),
        xtype='twocolumntextarea')

    asRate = schema.Bool(
        title=_t(u'Rate?'),
        group=_t('Target'))

    debug = schema.Bool(
        title=_t(u'Verbose Debug Logging'))

    minimumInterval = schema.Int(
        title=_t(u'Minimum Interval (seconds)'))
    useBasisInterval = schema.Bool(
        title=_t(u'Use Basis Interval'))
    maximumInterval = schema.Int(
        title=_t(u'Maximum Interval (seconds)'))
