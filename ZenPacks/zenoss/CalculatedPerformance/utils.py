##############################################################################
#
# Copyright (C) Zenoss, Inc. 2014-2018, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
##############################################################################

from functools import partial, wraps
from pprint import pformat
import itertools
import keyword
import logging
import re
import time

from Products.ZenModel.DeviceHW import DeviceHW
from Products.ZenModel.OperatingSystem import OperatingSystem
from Products.ZenModel.ZenModelRM import ZenModelRM


def get_ds_key(ds):
    return '{device}_{component}:{datasource}'.format(
        device=ds.device,
        component=ds.component or '',
        datasource=ds.datasource)


def get_target_id(target):
    if 'device' in target:
        return '{device_id}_{target_id}'.format(
            device_id=target['device'].get('id', ''),
            target_id=target.get('id', ''))
    else:
        return target.get('id', '') + '_'


def toposort(datasources):
    """A leaf-first topological sort on dependencies."""
    datasources_by_key = {get_ds_key(ds): ds for ds in datasources}
    dependencies = {}

    # Find all items that don't depend on anything.
    for ds_key, ds in datasources_by_key.iteritems():
        target_keys = set()

        for target_dp in ds.params.get('targetDatapoints', []):
            target_ds, _, _, _, targets = target_dp
            for target in targets:
                target_key = '{}:{}'.format(
                    get_target_id(target), target_ds)

                if target_key == ds_key:
                    continue

                target_keys.add(target_key)

                if target_key not in datasources_by_key:
                    dependencies[target_key] = set()

                dependencies[ds_key] = target_keys

    while True:
        ordered_ds_keys = set(
            item for item, dep in dependencies.iteritems() if not dep)

        if not ordered_ds_keys:
            break

        for ds_key in ordered_ds_keys:
            ds = datasources_by_key.get(ds_key)
            if ds:
                yield ds

        dependencies = {
            item: (dep - ordered_ds_keys)
            for item, dep in dependencies.iteritems()
            if item not in ordered_ds_keys}

    if dependencies:
        raise Exception(
            "Cyclic dependencies exist among these items:\n%s" % '\n'.join(
                repr(x) for x in dependencies.iteritems()))


def grouper(n, iterable):
    it = iter(iterable)
    while True:
        chunk = tuple(itertools.islice(it, n))
        if not chunk:
            return
        yield chunk


class SimpleObject(object):
    """
    Simple class that can have arbitrary attributes assigned to it.
    """
    def __repr__(self):
        return 'SimpleObject: %s' % pformat(self.__dict__)


# These methods will be added to the evaluation locals
# for the calculated expressions.

def pct(numerator, denominator):
    """
    This method calculates the percentage of the numerator and denominator,
    which can be either numerics or lists of numerics. None is filtered out.
    The value 0.0 is returned if the denominatorList sums to zero.

    sum(numerator) / sum(denominator) * 100.0

    """
    bottom = denominator if isinstance(
        denominator, (list, tuple)) else [denominator]

    denominator = sum(x for x in bottom if x is not None)
    if denominator == 0.0:
        return 0.0

    top = numerator if isinstance(numerator, (list, tuple)) else [numerator]
    numerator = sum(x for x in top if x is not None)

    return numerator / denominator * 100.0


def avg(dpList):
    """Average a list of datapoints.

    A list with no non-None items has an average of zero.

    """
    if not dpList:
        return 0.0

    dpList = [x for x in dpList if x is not None]
    if not dpList:
        return 0.0

    return sum(dpList) / len(dpList)


def createDeviceDictionary(obj_attrs):
    """
    Returns a dictionary of simple objects suitable for passing into eval().
    """
    # Add in default methods
    vars = {
        'pct': pct,
        'avg': avg,
        }

    for key, value in obj_attrs.items():
        # For example, turn here.hw.totalMemory=1024 into:
        # vars['here'].hw.totalMemory = 1024
        # This way, vars can be passed in to eval
        parts = key.split(".")
        if parts[0] not in vars:
            base = vars[parts[0]] = SimpleObject()
        else:
            base = vars[parts[0]]

        for part in parts[1:-1]:
            if not hasattr(base, part):
                setattr(base, part, SimpleObject())
            base = getattr(base, part)
        setattr(base, parts[-1], value)

    return vars


varNameRe = re.compile(
    r"(?<=datapoint\[['\"])[^'\"]+(?=['\"]\])|"  # datapoint['dpname']
    r"[A-Za-z][A-Za-z0-9_\.]*")  # dpname


# 'x', 'y', 'i', 'j' are not keywords, but will be ignored,
# so that lists can be used.
_reserved = ['avg', 'pct', 'rrd_paths', 'datapoint'] + \
            ['x', 'y', 'i', 'j']


def isReserved(name):
    return keyword.iskeyword(name) or \
           __builtins__.has_key(name) or \
           name in _reserved


def getVarNames(expression):
    return itertools.ifilterfalse(
        isReserved,
        varNameRe.findall(expression))


def _getAndCall(obj, attr, default=None):
    base = getattr(obj, attr, default)
    if base is None:
        return None

    # Backwards-compatibility for 'hw' and 'os' references.
    if callable(base) and not isinstance(base, (DeviceHW, OperatingSystem)):
        base = base()
    return base


def _maybeChain(iterables):
    for it in iterables:
        if hasattr(it, '__iter__') and not isinstance(it, ZenModelRM):
            for element in it:
                yield element
        else:
            yield it


def dotTraverse(base, path):
    """Traverse object attributes with a . separating attributes.

    e.g., base=find("deviceId") ; dotTraverse(base, "hw.totalMemory")
        --> 2137460736
    Callable attributes along the chain will be called with no arguments,
    except for DeviceHW and OperatingSystem instances.

    """
    if not path:
        return None

    path = path.split(".")
    if path[0] == 'here':
        path.pop(0)

    while len(path) > 0:
        if base is None:
            return None

        attr = path.pop(0)

        if hasattr(base, attr):
            base = _getAndCall(base, attr)
        elif hasattr(base, '__iter__') and not isinstance(base, ZenModelRM):
            # If iterable, get the attr for each and chain it.
            getFunc = partial(_getAndCall, attr=attr, default=None)
            base = list(
                x for x in _maybeChain(map(getFunc, base))
                if x is not None)
        else:
            base = None

    return base


def async_timeit(log, msg_prefix='', msg_suffix='', threshold=60):
    """Log execution time of the decorated function."""
    msg = "took %.1f seconds"
    if msg_prefix:
        msg = "{} {}".format(msg_prefix, msg)
    if msg_suffix:
        msg = "{} {}".format(msg, msg_suffix)

    def log_execution_time(result, start_time):
        exec_time = time.time() - start_time
        log_func = log.warning if exec_time > threshold else log.debug
        log_func(msg, exec_time)
        return result

    def func_decorator(func):
        @wraps(func)
        def func_wrapper(*args, **kw):
            start_time = time.time()
            deferred = func(*args, **kw)
            deferred.addBoth(log_execution_time, start_time=start_time)
            return deferred
        return func_wrapper

    return func_decorator


class ContextLogAdapter(logging.LoggerAdapter):

    def process(self, msg, kwargs):
        return '{} {}'.format(self.extra['context'], msg), kwargs
