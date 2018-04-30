##############################################################################
#
# Copyright (C) Zenoss, Inc. 2015-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

"""An aggregation method should return both the datapoint,
and the value array with any in-place modification.

"""

import math


def _amean(values):
    if not values:
        return None
    return math.fsum(values)/float(len(values))


def _median(values):
    if not values:
        return None
    values = sorted(values)
    if len(values) % 2 == 0:
        fMidpoint = (len(values) - 1) / 2.0
        return _amean((
            values[int(math.floor(fMidpoint))],
            values[int(math.ceil(fMidpoint))]))
    else:
        fMidpoint = (len(values) - 1) / 2
        return values[fMidpoint]


def _bound(minValue=None, value=0, maxValue=None):
    """
    Ensure that 'value' is between the specified min and max values.
    """
    if minValue is not None:
        value = __builtins__['max'](minValue, value)
    if maxValue is not None:
        value = __builtins__['min'](maxValue, value)
    return value


def _nthPercentileRank(n, length):
    """Find the nth percentile rank in a list. Calculated according
    to the nearest-rank method.

    See: http://en.wikipedia.org/wiki/Percentile#Nearest_rank

    Modified to conform to zero-indexing, and to bound results to
    the dimensions of the list.

    WARNING: This method is not necessarily numerically sound if you pass
    a non-integer value for n. The calculations are subject to floating-
    point arithmetic issues.
    See: http://docs.python.org/tutorial/floatingpoint.html#tut-fp-issues
    """
    if 0 <= n <= 100:
        # This calculation was n/100.0 * length, but has been rearranged to
        # avoid floating-point representation errors.
        rank = int(round((n * length) / 100.0 + 0.5)) - 1
        # Bound result to the bounds of the list.
        return _bound(0, rank, length-1)
    else:
        raise ValueError(
            'n must be between 0 and 100, inclusive. Got: %s' % n)


def count(valuemap):
    return len(valuemap), valuemap


def sum(valuemap):
    return math.fsum(valuemap.values()), valuemap


def max(valuemap):
    return __builtins__['max'](valuemap.values()), valuemap


def min(valuemap):
    return __builtins__['min'](valuemap.values()), valuemap


def amean(valuemap):
    return _amean(valuemap.values()), valuemap


avg = amean


def median(valuemap):
    return _median(valuemap.values()), valuemap


def _deviations(midpointFunc, values):
    mid = midpointFunc(values)
    return [x - mid for x in values]


def _absoluteDeviations(midpointFunc, values):
    return [math.fabs(x) for x in _deviations(midpointFunc, values)]


def stddev(valuemap):
    """
    See: http://en.wikipedia.org/wiki/Standard_deviation

    Modifies the value map to contain the absolute deviation
    of the input values.

    """
    devs = _deviations(_amean, valuemap.values())
    std = math.sqrt(_amean([math.pow(x, 2) for x in devs]))
    return std, dict(zip(valuemap.keys(), devs))


std = stddev


def var(valuemap):
    """
    See: http://en.wikipedia.org/wiki/Variance

    Modifies the value map to contain the square of the deviation
    of the input values.

    """
    sqDevs = [math.pow(x, 2) for x in _deviations(_amean, valuemap.values())]
    return _amean(sqDevs), dict(zip(valuemap.keys(), sqDevs))


def mad(valuemap):
    """
    See: http://en.wikipedia.org/wiki/Median_absolute_deviation
    """
    medianDeviations = _absoluteDeviations(_median, valuemap.values())
    return _median(medianDeviations), dict(
        zip(valuemap.keys(), medianDeviations))


def madmax(valuemap, themax):
    """
    See: http://en.wikipedia.org/wiki/Median_absolute_deviation
    """
    medianDeviations = _absoluteDeviations(
        _median, map(
            lambda x: x if x < themax else themax or 0, valuemap.values()))
    return _median(medianDeviations), dict(
        zip(valuemap.keys(), medianDeviations))


def percentile(valuemap, n):
    """
    See: http://en.wikipedia.org/wiki/Percentile
    """
    rank = _nthPercentileRank(int(n), len(valuemap))
    return sorted(valuemap.values())[rank], valuemap


VALID_OPERATIONS = [
    'count',
    'sum',
    'max',
    'min',
    'amean',
    'avg',
    'median',
    'stddev',
    'std',
    'var',
    'mad',
    'madmax',
    'percentile',
]
