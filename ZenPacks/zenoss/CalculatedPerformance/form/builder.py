#
#
# Copyright (C) Zenoss, Inc. 2014, all rights reserved.
#
# This content is made available according to terms specified in
# License.zenoss under the directory where your Zenoss product is installed.
#
#


from Products.Zuul.infos.component import ComponentFormBuilder


class FilteredComponentFormBuilder(ComponentFormBuilder):

    def render(self, fieldsets=True):
        ob = self.context._object
        # find out if we can edit this form
        readOnly = True
        if hasattr(ob, 'isUserCreated'):
            readOnly = not ob.isUserCreated()
        # status field filter
        fieldFilter = lambda field: field != 'status'
        # construct the form
        form = super(ComponentFormBuilder, self).render(fieldsets,
                                                        readOnly=readOnly,
                                                        fieldFilter=fieldFilter)
        form['userCanModify'] = not readOnly or self.hasAlwaysEditableField
        return form
