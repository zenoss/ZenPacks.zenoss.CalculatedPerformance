Calculated Performance Data Datasource

About
==============
This ZenPack adds a daemon (zencalcperfd) and a datasource
(Calculated Performance) that uses previously collected RRD
data values to calculate new data point values.
  Unlike a data point alias,
a calculated performance data source can use multiple
data points to perform the calculation, and can be used
to threshold and graph.  Unlike a data point alias,

As an example, a new datapoint might take the data from two
other datapoints on the same template, average them and convert
the result to a percentage using a modeled device attribute.
More concretely, a network IpInterface can be used to take
the total number of packets and divide that number by the
total number of errors and use that to determine the percentage
of errors on the interface over time.

The daemon calculates the values every minute for devices.


PREREQUISITES
==============
 
 Table xxx.1. Calculated Performance Prerequisites
 Prerequisite   Restriction
 Zenoss Version Zenoss Version 3.1 or higher
 Required ZenPacks  ZenPacks.zenoss.CalculatedPerformance

ADD A CALCULATED DATAPOINT TO A TEMPLATE
==========================================
1. Navigate to the template that you want to modify.
1. From the DataSources  area, click the plus sign to add a new datasource.
1. Provide a name for the new datasource and select the Calculated Performance
type, and then click Submit.  This will automatically create a new datapoint of the same name as the datasource.
1. Click on the new data source, which brings up an 'Edit Data Source' dialog.

Specify the parameters for the threshold.
 
 Table xx.2. Calculated Performance Data Source Options
 Name   Description
 Name   The name of the datasource.
 Expression Expression to use to create the new datapoint. For example,
 (hw.totalMemory - memAvailReal) / hw.totalMemory
 The above expression uses the totalMemory attriubte modeled from the device
 and uses the RRD data point memAvailReal to calculate a percentage used.

 Severity    The severity to apply to the event.
 Event Class    The event class to which any events will be sent on errors.
 Event Key    The event key which will help determine the event class if
 '/Unknown' is the event class.

 1. Click Save to save your changes.

The datapoint can now be used to graph or threshold.


Daemon
========
zencalcperfd
