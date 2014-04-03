(function(){
    var ZC = Ext.ns('Zenoss.component');
    /**
     * @class Zenoss.component.AggComponentModel
     * @extends Ext.data.Model
     * Field definitions for the members grid
     **/
    Ext.define('Zenoss.component.AggComponentModel',  {
        extend: 'Ext.data.Model',
        idProperty: 'uid',
        fields: Zenoss.model.BASE_TREE_FIELDS.concat([
            {name: 'uid'},
            {name: 'id'},
            {name: 'name'},
            {name: 'meta_type'},
            {name: 'severity'},
            {name: 'monitor'}
        ])
    });

    /**
     * @class Zenoss.component.AggComponentStore
     * @extend Zenoss.DirectStore
     * Direct store for aggregate components
     */
    Ext.define("Zenoss.component.AggComponentStore", {
        extend: "Ext.data.TreeStore",
        constructor: function(config) {
            config = config || {};
            Ext.applyIf(config, {
                model: 'Zenoss.component.AggComponentModel',
                pageSize: 200,
                initialSortColumn: "name",
                root: 'data',
                nodeParam: 'uid',
                remoteSort: false,
                proxy: {
                    limitParam: undefined,
                    startParam: undefined,
                    pageParam: undefined,
                    sortParam: undefined,
                    type: 'direct',
                    directFn: Zenoss.remote.AggregatingCollectorRouter.getMembers,
                    reader: {
                        root: 'data',
                        totalProperty: 'count'
                    }
                }
            });
            this.callParent(arguments);
        }
    });

    /**
     * @class Zenoss.component.AggregatingComponentMembersPanel
     * @extend Zenoss.grid.Panel
     * Grid that displays the members of the aggregate collector component
     */
    Ext.define('Zenoss.component.AggregatingComponentMembersPanel', {
        extend: "Ext.tree.Panel",
        alias: "widget.AggregatingComponentMembersPanel",
        constructor: function(config) {
            config = Ext.applyIf(config || {}, {
                rootVisible: false,
                columns: [{
                    id: 'aggcomp_severity',
                    dataIndex: 'severity',
                    header: _t('Events'),
                    renderer: Zenoss.render.severity,
                    width: 50
                },{
                    xtype: 'treecolumn',
                    id: 'aggcomp_name',
                    dataIndex: 'name',
                    header: _t('Name'),
                    flex: 1,
                    renderer: function(value, metaData, record) {
                        return Zenoss.render.default_uid_renderer(record.get('uid'), value);
                    }
                },{
                    id: 'aggcomp_type',
                    dataIndex: 'meta_type',
                    header: _t('Type'),
                    renderer: function(value) {
                        return ZC.displayName(value)[0];
                    }
                }],
                store: Ext.create('Zenoss.component.AggComponentStore', {}),
                viewConfig: {
                    emptyText: _t('No data available')
                }
            });
            this.callParent([config]);
        }
    });

    /**
     * Show the "members" sub component grid if the current component grid is a type of
     * aggregate component.
     **/
    Zenoss.nav.appendTo('Component', [{
        id: 'aggregating_components_members',
        text: _t('Members'),
        xtype: 'container',
        layout: 'fit',
        autoScroll: true,
        style: {
            overflow: 'auto'
        },
        subComponentGridPanel: true,
        filterNav: function(navpanel) {
            // since we don't know the component type of all the aggregated components
            // only show members if the "numberOfMembers" attribute is a field in the current component grid
            var fields = Ext.pluck(navpanel.refOwner.componentgrid.fields, "name");
            return Ext.Array.contains(fields, "numberOfMembers");
        },
        refresh: function() {
            var root = this.aggtree.getRootNode(),
                tree = this.aggtree;
            root.setId(tree.uid);
            root.data.uid = tree.uid;
            root.uid = tree.uid;
            tree.expandAll();
        },
        setContext: function(uid) {
            this.add({
                xtype: "AggregatingComponentMembersPanel",
                ref: 'aggtree',
                root: {
                    uid: uid,
                    keys: this.keys,
                    id: uid
                }
            });
            this.aggtree.uid = uid;
            this.refresh();
        }
    }]);

}());