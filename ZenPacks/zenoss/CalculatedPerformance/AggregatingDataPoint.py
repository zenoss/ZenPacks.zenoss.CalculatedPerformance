##############################################################################
# 
# Copyright (C) Zenoss, Inc. 2009, all rights reserved.
# 
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
# 
##############################################################################


from Products.ZenModel.RRDDataPoint import RRDDataPoint


class AggregatingDataPoint(RRDDataPoint):
    """
    A custom DataPoint class that adds the properties needed to calculate
    aggregations on other datapoints.
    """

    operation = ''
    arguments = ''

    # Meta-Data: persistent property definitions.
    _properties = RRDDataPoint._properties + (
        {'id':'operation', 'type':'string', 'mode':'w'},
        {'id':'arguments', 'type':'string', 'mode':'w'},
    )
