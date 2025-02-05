# -*- coding: utf-8 -*-
"""
ddmanager
--------
Class that steers the DataDrivenUI
"""
from __future__ import absolute_import
"""
/***************************************************************************
 DataDrivenInputMask
                                 A QGIS plugin
 Applies a data-driven input mask to any PostGIS-Layer
                              -------------------
        begin                : 2012-06-21
        copyright            : (C) 2012 by Bernhard Strรถbl / Kommunale Immobilien Jena
        email                : bernhard.stroebl@jena.de
 ***************************************************************************/

/***************************************************************************
 *                                                                         *
 *   This program is free software; you can redistribute it and/or modify  *
 *   it under the terms of the GNU General Public License as published by  *
 *   the Free Software Foundation; either version 2 of the License, or     *
 *   (at your option) any later version.                                   *
 *                                                                         *
 ***************************************************************************/
"""

from builtins import str
from builtins import range
from builtins import object
# Import the PyQt and QGIS libraries
from qgis.PyQt import QtCore, QtGui, QtWidgets
from .dderror import DdError,  DbError

try:
    from qgis.PyQt import QtSql
except:
    DdError(QtWidgets.QApplication.translate(
        "DdError", "QtSql cannot be located on your system. Please install and try again."),
         fatal = True)
from qgis.core import *
from qgis.gui import *
import qgis.core

from .ddui import DataDrivenUi, DdFormWidget
from .ddattribute import *
from .dddialog import DdDialog,  DdSearchDialog
from . import ddtools
import xml.etree.ElementTree as ET
import os, re

class DdManager(object):
    """DdManager manages all masks in the current project"""

    def __init__(self,  iface):
        self.iface = iface
        self.ddLayers = dict()
        settings = QgsSettings()
        settings.beginGroup("Qgis/digitizing")
        a = settings.value("line_color_alpha",200,type=int)
        b = settings.value("line_color_blue",0,type=int)
        g = settings.value("line_color_green",0,type=int)
        r = settings.value("line_color_red",255,type=int)
        lw = settings.value("line_width",1,type=int)
        settings.endGroup()
        self.rubberBandColor = QtGui.QColor(r, g, b, a)
        self.rubberBandWidth = lw
        self.showConfigInfo = True
        self.latestConfigTablesVersion = False
        # is set to true if config tabels are created or updated

    def __debug(self,  title,  str):
        QgsMessageLog.logMessage(title + "\n" + str)

    def __str__(self):
        return "<ddmanager.DdManager>"

    def saveSearchPath(self,  path = ""):
        settings = QgsSettings()
        settings.beginGroup("DataDrivenInputMask")
        settings.setValue(u"lastSearchPath", path)
        settings.endGroup()

    def getSearchPath(self):
        settings = QgsSettings()
        settings.beginGroup("DataDrivenInputMask")
        path = settings.value("lastSearchPath",  "",  type=str)
        settings.endGroup()

        return path

    def setLastSearch(self,  layer,  root):
        layerValues = self.__getLayerValues(layer)

        if layerValues != None:
            if root == None:
                return False
            else:
                self.ddLayers[layer.id()][6] =  root
                return True
        else:
            return False

    def highlightFeature(self,  layer,  feature):
        '''highlight the feature if it has a geometry'''
        geomType = layer.geometryType()

        if geomType <= 2:
            if geomType == 0:
                marker = QgsVertexMarker(self.iface.mapCanvas())
                marker.setIconType(3) # ICON_BOX
                marker.setColor(self.rubberBandColor)
                marker.setIconSize(12)
                marker.setPenWidth (3)
                try:
                    marker.setCenter(feature.geometry().centroid().asPoint())
                    return marker
                except:
                    return None
            else:
                rubberBand = QgsRubberBand(self.iface.mapCanvas())
                rubberBand.setColor(self.rubberBandColor)
                rubberBand.setWidth(self.rubberBandWidth)
                rubberBand.setToGeometry(feature.geometry(),  layer)
                return rubberBand
        else:
            return None

    def initLayer(self,  layer,  skip = [],  labels = {},  fieldOrder = [],  fieldGroups = {},  minMax = {},  noSearchFields = [],  \
        showParents = True,  createAction = True,  db = None,  inputMask = True,  searchMask = True,  \
        inputUi = None,  searchUi = None,  helpText = "", fieldDisable = []):
        '''api method initLayer: initialize this layer with a data-driven input mask.
        In case there is configuration for this layer in the database read this
        configuration and apply what is provided there.
        Returns a Boolean stating the success of the initialization
        Parameters:
        WARNING: if config tables are used, the parameters' objects survive
        and are thus applied to the next layer, too. Be sure to also pass ALL optional
        paramerters when calling initLayer()

        - layer [QgsVectorLayer]
        - skip [array [string]]: field names to not show
        - labels [dict] with entries: "fieldname": "label"
        - fieldOrder [array[string]]: containing the field names in the order they should be shown
        - fieldGroups [dict] with entries: fieldName: [tabTitle, tabTooltip] for each group a tab is created and the fields from fieldName onwards (refers to fieldOrder) are grouped in this tab; tabTooltip is optional
        - minMax [dict] with entries: "fieldname": [min, max] - strings; use for numerical or date fields only!
        - noSearchFields [array[string]] with fields not to be shown in the search form, if empty all fields are shown. Skipped fields are never shown in the search form, no matter if they are included here
        - showParents [Boolean] show tabs for 1-to-1 relations (parents)
        - createAction [Boolean]: add an action to the layer's list of actions
        - db [QtSql.QSqlDatabase]
        - inputMask [Boolean]: create a data-edit mask
        - searchMask [Boolean]: create a data-search mask
        - inputUi [ddui.DdDialogWidget]: apply this inputUi
        - searchUi [ddui.DdDialogWidget]: apply this as search ui
        - helpText [string] help text for this mask, may be html formatted
        - fieldDisable [array[string]]: field names whose DdInputWidget shall be disabled in the inputMask'''

        thisSize = None # stores the size of the DdDialog
        root = ET.Element('DdSearch')

        if inputUi != None:
            inputMask = False # do not make one but use the one provided

        if searchUi != None:
            searchMask = False # do not make one but use the one provided

        if u'PostgreSQL' != layer.dataProvider().storageType()[0:10] :
            DdError(QtWidgets.QApplication.translate("DdError", "Layer is not a PostgreSQL layer: ") +
                layer.name(),  iface = self.iface)
            return False
        else:
            if db == None:
                db = self.__createDb(layer)

            thisTable = self.makeDdTable(layer,  db)

            if thisTable == None:
                return False
            else:
                if inputMask or searchMask:
                    # check for config tables
                    ddConfigTable = DdTable(schemaName = "public",  tableName = "dd_table")
                    readConfigTables = self.existsInDb(ddConfigTable, db)

                    if not readConfigTables:
                        readConfigTables = self.createConfigTables(db)
                    if readConfigTables:
                        readConfigTables = self.isAccessible(db,  ddConfigTable,  showError = False)

                    if not readConfigTables:
                        if self.showConfigInfo:
                            self.iface.messageBar().pushMessage(QtWidgets.QApplication.translate("DdInfo",
                                "Config tables either not found or not accessible, loading default mask"))
                            self.showConfigInfo = False
                    else:
                        readConfigTables = self.updateConfigTables(db)

                    # we want at least one automatically created mask
                    ddui = DataDrivenUi(self.iface)
                    autoInputUi,  autoSearchUi = ddui.createUi(
                        thisTable,  db,  skip,  labels,  fieldOrder,  fieldGroups,  minMax,  \
                        noSearchFields, showParents,  True,  inputMask,  searchMask,  helpText,  createAction,  \
                        readConfigTables = readConfigTables, fieldDisable = fieldDisable)

                    if inputUi == None:
                        # use the automatically created mask if none has been provided
                        inputUi = autoInputUi

                    if searchUi == None:
                        searchUi = autoSearchUi

                    if not inputMask or not searchMask:
                        # at least one mask shall not be initialized
                        try:
                            layerValues = self.ddLayers[layer.id]
                            # see if the layer has been initialized already
                        except KeyError:
                            layerValues = None

                        if layerValues != None:
                            # layer has been initialized before!
                            if not inputMask and inputUi == None:
                                # user did not provide a mask
                                inputUi = layerValues[2] # keep current
                            if not searchMask and searchUi == None:
                                searchUi = layerValues[3] # keep current
                    #else:
                        #self.ddLayers.pop(layer.id(),  None) # remove entries if they exist

                    self.ddLayers[layer.id()] = [thisTable,  db,  inputUi,  searchUi,  showParents,  thisSize,  root]
                    # parameter 6 holds the last search or None if no last search exists
                    self.__connectSignals(layer)

                    if createAction:
                        self.addAction(layer)

                    return True
                else:
                    # no auto masks, both were provided
                    self.ddLayers[layer.id()] = [thisTable,  db,  inputUi,  searchUi,  showParents,  thisSize,  root]
                    return True

    def createDdTable(self, db, schemaName, tableName,
            withOid = True, withComment = True):
        '''create a DdTable object from the passed in variables'''

        thisTable = DdTable(schemaName = schemaName, tableName = tableName)

        if db == None:
            return None

        if withOid:
            thisTable.oid = self.__getOid(thisTable, db)

        if withComment:
            comment = self.__getComment(thisTable, db)

            if comment:
                thisTable.comment = comment

        if not self.__isTable(thisTable,  db):
            DdError(
                QtWidgets.QApplication.translate("DdError",
                    "Layer is not a PostgreSQL table: ") +
                    schemaName + "." + tableName, iface = self.iface,
                showInLog = True)
            return None
        else:
            return thisTable

    def makeDdTable(self,  layer,  db = None):
        '''make a DdTable object from the passed in layer, returns None, if layer is not suitable'''
        if 0 != layer.type():   # not a vector layer
            DdError(
                QtWidgets.QApplication.translate("DdError",
                    "Layer is not a vector layer: ") +
                    layer.name(), iface = self.iface,
                    showInLog = True)
            return None
        else:
            if u'PostgreSQL' != layer.dataProvider().storageType()[0:10] :
                DdError(
                    QtWidgets.QApplication.translate("DdError",
                        "Layer is not a PostgreSQL layer: ") +
                        layer.name(), iface = self.iface,
                        showInLog = True)
                return None
            else:
                layerSrc = self.__analyzeSource(layer)
                relation = layerSrc["table"].split('"."')
                schema = relation[0].replace('"', '')
                table = relation[1].replace('"', '')
                thisTable = DdTable(schemaName = schema,  tableName = table,  title = layer.name())

                if db == None:
                    db = self.__createDb(layer)

                    if db == None:
                        return None

                thisTable.oid = self.__getOid(thisTable, db)
                comment = self.__getComment(thisTable, db)

                if comment:
                    thisTable.comment = comment

                if not self.__isTable(thisTable,  db):
                    DdError(
                        QtWidgets.QApplication.translate("DdError",
                            "Layer is not a PostgreSQL table: ") +
                            layer.name(), iface = self.iface,
                            showInLog = True)
                    return None
                else:
                    return thisTable

    def addAction(self, layer, actionName = u'showDdForm', ddManagerName = "ddManager",
        newIcon = None):
        '''api method to add an action to the layer with a self defined name'''

        defaultTitle = QtWidgets.QApplication.translate("DdLabel", "Show Input Form")

        if actionName == u'showDdForm':
            newTitle = defaultTitle
        else:
            newTitle = actionName
            actionName = u'showDdForm'

        createAction = True
        actionToRemove = None

        #check if the action is already attached
        for act in layer.actions().actions():
            if act.command().find(";ddManager.showDdForm([% $id %]);") != -1:
                # action has already been attached
                thisTitle = act.shortTitle()

                if thisTitle == newTitle: # the action exists with the given title
                    createAction = False
                    break
                else:
                    if newTitle == defaultTitle:
                        # action is already in place and we would replace it with an action with default title
                        # and that's what it is or it has a custom title, so nothing to do
                        createAction = False
                        break
                    else: # action with default title exists and is to be replaced
                        # with an action with a custom title
                        actionToRemove = thisTitle

        if createAction:
            if actionToRemove != None:
                self.removeAction(layer, actionToRemove)

            if not QtCore.QFile(newIcon).exists():
                newIcon = os.path.abspath(os.path.dirname(__file__) + '/datadriveninputmask.png')

            if qgis.core.Qgis.QGIS_VERSION_INT >= 33000:
                actionType = QgsAction.GenericPython
            else:
                actionType = 1 # actionType 1: Python

            newAction = QgsAction(actionType, actionName,
                "app=QgsApplication.instance();ddManager=app." + ddManagerName +
                ";ddManager.showDdForm([% $id %]);", newIcon, False, newTitle, {'Field', 'Feature', 'Canvas'})
            layer.actions().addAction(newAction)

    def removeAction(self, layer, actionName, actionTitle = None):
        '''api method to remove an action from the layer'''

        actionToRemove = None

        for act in layer.actions().actions():
            if act.name() == actionName:
                if actionTitle == None:
                    actionToRemove = act.id() # no matter which tiltle
                    break
                else:
                    if actionTitle == act.shortTitle:
                        actionToRemove = act.id()
                    break

        if actionToRemove != None:
            layer.actions().removeAction(actionToRemove)

    def showFeatureForm(self, layer, feature, showParents = True,
            title = None, askForSave = True, multiEdit = False, forEdit = True):
        '''
        api method showFeatureForm: show the data-driven input mask for a layer and a feature
        if the data provider allows editing and for Edit is True, the layer is turned into editing mode
        if the user clicks OK all changes to the feature are committed (no undo!)
        if askForSave is true and the layer has pending changes the user is asked if the changes
        shall be commited before the mask is opened
        if multiEdit is True then the changes are applied to all selected Features in the layer
        returns 1 if user clicked OK, 0 if CANCEL
        '''

        layerValues = self.__getLayerValues(layer,  inputMask = True,  searchMask = False)

        if layerValues != None:
            parentsInMask = layerValues[4]

            if parentsInMask and not showParents:
                self.initLayer(layer,  showParents = False,  inputMask = True,  searchMask = False,  \
                            skip = [],  labels = {},  fieldOrder = [],  fieldGroups = {},  minMax = {},  noSearchFields = [],  \
                            createAction = True,  db = None,   inputUi = None,  searchUi = None,  helpText = ""
                               )
                layerValues = self.__getLayerValues(layer,  inputMask = True,  searchMask = False)

        if layerValues != None:
            result = 1
            wasEditable = layer.isEditable()

            if forEdit:
                if wasEditable:
                    if layer.isModified() and askForSave:
                        #ask user to save or discard changes
                        reply = QtWidgets.QMessageBox.question(None, QtWidgets.QApplication.translate("DdInfo", "Unsaved changes"),
                            QtWidgets.QApplication.translate("DdInfo", "Do you want to save the changes to layer ") +
                            layer.name() + "?",
                            QtWidgets.QMessageBox.Discard | QtWidgets.QMessageBox.Cancel | QtWidgets.QMessageBox.Save)

                        if reply == QtWidgets.QMessageBox.Cancel:
                            result = 0
                        else:
                            if reply == QtWidgets.QMessageBox.Discard:
                                if not layer.rollBack():
                                    DdError(QtWidgets.QApplication.translate("DdError", "Could not discard changes for layer: ") +
                                    layer.name(),  iface = self.iface)
                                    result = 0
                                else:
                                    if feature.id() <= 0: # new feature discarded
                                        result = 0
                            elif reply == QtWidgets.QMessageBox.Save:
                                if not layer.commitChanges():
                                    DdError(QtWidgets.QApplication.translate("DdError", "Could not save changes for layer: ")  +
                                    layer.name(),  iface = self.iface)
                                    result = 0

                            if result == 1:
                                layer.startEditing()
                else:
                    if self.isEditable(layer):
                        layer.startEditing()

            if result == 1:
                if multiEdit:
                    highlightGeom = None
                else:
                    highlightGeom = self.highlightFeature(layer, feature)

                db = layerValues[1]

                if not db.isValid():
                    db = self.__createDb(layer)

                if db == None:
                    return None

                ui = layerValues[2]
                thisSize = layerValues[5]
                dlg = DdDialog(self, ui, layer, feature, db, multiEdit,
                    title = title)
                dlg.show()
                if thisSize != None:
                    dlg.resize(thisSize)

                result = dlg.exec_()

                if result == 1:
                    layer.layerModified.emit()
                # store size
                thisSize = dlg.size()
                self.ddLayers[layer.id()][5] = thisSize
                #handle highlightGeom

                if highlightGeom != None:
                    self.iface.mapCanvas().scene().removeItem(highlightGeom)
                    highlightGeom = None

                if not wasEditable:
                    layer.rollBack()
        else:
            result = 0

        return result

    def showSearchForm(self,  layer,  root = None):
        '''api method showSearchForm: show the data-driven search mask for a layer
        root is a search-XML Element to be applied upon startup, if not given lastSearch is applied
        returns 1 if user clicked OK, 0 if CANCEL'''
        layerValues = self.__getLayerValues(layer,  inputMask = False,  searchMask = True)

        if layerValues != None:
            #QtGui.QMessageBox.information(None, "", str(layerValues[2]))
            db = layerValues[1]

            if not db.isValid():
                db = self.__createDb(layer)

                if db != None:
                    self.setDb(layer, db)
                else:
                    return None

            searchUi = layerValues[3]
            thisSize = layerValues[5]
            dlg = DdSearchDialog(searchUi,  layer,  db,  root = root)
            dlg.show()

            if thisSize != None:
                dlg.resize(thisSize)

            result = dlg.exec_()
            newSize = dlg.size()
            self.ddLayers[layer.id()][5] = newSize
            return result

    def showDdForm(self,  fid):
        aLayer = self.iface.activeLayer()

        if aLayer != None:
            feat = aLayer.getFeature(fid)

            if feat != None:
                self.showFeatureForm(aLayer,  feat)

    def setUi(self,  layer,  ui,  searchUi = None,  showParents = None,  thisSize = None):
        '''api method to exchange the default ui with a custom ui'''

        layerValues = self.__getLayerValues(layer)

        if layerValues != None:
            #QtGui.QMessageBox.information(None, "", str(layerValues[2]))
            thisTable = layerValues[0]
            db = layerValues[1]

            if searchUi == None:
                searchUi = layerValues[3]

            if showParents == None:
                showParents = layerValues[4]

            self.ddLayers[layer.id()] = [thisTable,  db,  ui,  searchUi,  showParents,  thisSize,  None]

    def addFormWidget(self, layer, label, toolTip = None, toUi = True, toSearchUi = True):
        layerValues = self.__getLayerValues(layer)
        thisTable = layerValues[0]
        aTable = DdTable(thisTable.oid, thisTable.schemaName,
            thisTable.tableName, toolTip, label)
        ui = layerValues[2]
        searchUi = layerValues[3]


        if toUi:
            newUiForm = DdFormWidget(aTable)
            ui.addFormWidget(newUiForm)

        if toSearchUi:
            newSearchUiForm = DdFormWidget(aTable)
            searchUi.addFormWidget(newSearchUiForm)

    def addInputWidget(self, layer, inputWidget, ddFormWidgetIndex = None,
            beforeWidget = None, toUi = True, toSearchUi = True):
        '''api method to add a DdWidget into the ui of a layer'''
        layerValues = self.__getLayerValues(layer)
        ui = layerValues[2]
        searchUi = layerValues[3]

        if ui != None and toUi:
            ui.addInputWidget(inputWidget, ddFormWidgetIndex, beforeWidget)

        if searchUi != None and toSearchUi:
            searchUi.addInputWidget(inputWidget, ddFormWidgetIndex, beforeWidget)

    def addInputWidgetBefore(self, layer, inputWidget, beforeAttributeName,
            toUi = True, toSearchUi = True):
        '''api method to add a DdWidget into the ui of a layer before
        the widget of attribute with beforeAttributeName. Will
        be placed in the same form'''

        foundWidget = self.__getInputWidget(layer, beforeAttributeName)
        if foundWidget != None:
            formIndex = foundWidget[1]
            widgetIndex = foundWidget[2]
        else:
            formIndex = None
            widgetIndex = None
        self.addInputWidget(layer, inputWidget, formIndex, widgetIndex,
            toUi, toSearchUi)

    def addInputWidgetAfter(self, layer, inputWidget, afterAttributeName,
            toUi = True, toSearchUi = True):
        '''api method to add a DdWidget into the ui of a layer after
        the widget of attribute with afterAttributeName. Will
        be placed in the same form'''

        foundWidget = self.__getInputWidget(layer, afterAttributeName)
        if foundWidget != None:
            formIndex = foundWidget[1]
            widgetIndex = foundWidget[2] +1
        else:
            formIndex = None
            widgetIndex = None
        self.addInputWidget(layer, inputWidget, formIndex, widgetIndex,
            toUi, toSearchUi)

    def removeInputWidget(self, layer, attributeName, fromUi = True,
        fromSearchUi = True):
        '''api method to remove the DdWidget for a certain attribute'''

        layerValues = self.__getLayerValues(layer)
        ui = layerValues[2]
        searchUi = layerValues[3]
        foundWidget = self.__getInputWidget(layer, attributeName)

        if foundWidget != None:
            formIndex = foundWidget[1]
            widgetIndex = foundWidget[2]

            if ui != None and fromUi:
                ui.forms[formIndex].inputWidgets.pop(widgetIndex)

            if searchUi != None and fromSearchUi:
                searchUi.forms[formIndex].inputWidgets.pop(widgetIndex)

        return None

    def getInputWidget(self, layer, attributeName):
        '''api method returning the DdWidget for a certain attribute'''
        foundWidget = self.__getInputWidget(layer, attributeName)

        if foundWidget != None:
            return foundWidget[0]
        else:
            return None

    def replaceInputWidget(self, layer, attributeName, newWidget,
        toUi = True, toSearchUi = True):
        '''api method to replace a DdWidget in the ui of a layer
        with another one'''

        retValue = False
        foundWidget = self.__getInputWidget(layer, attributeName)

        if foundWidget != None:
            formIndex = foundWidget[1]
            widgetIndex = foundWidget[2]
            layerValues = self.__getLayerValues(layer)
            ui = layerValues[2]
            searchUi = layerValues[3]

            if ui != None and toUi:
                ui.forms[formIndex].inputWidgets[widgetIndex] = newWidget
                retValue = True

            if searchUi != None and toSearchUi:
                searchUi.forms[formIndex].inputWidgets[widgetIndex] = newWidget
                retValue = True

        return retValue

    def enableInputWidget(self, layer, attributeName, doEnable):
        '''api method to enable a DdWidget, i.e. set its Ddattribute
        to enableWidget'''

        inputWidget = self.getInputWidget(layer, attributeName)

        if inputWidget == None:
            return False
        else:
            inputWidget.attribute.enableWidget = doEnable


    def getDbForLayer(self,  layer):
        return self.__createDb(layer)

    def existsInDb(self,  ddTable,  db):
        return self.__getOid(ddTable,  db) != None

    def setDb(self,  layer,  db):
        '''api method to set the db for a layer'''
        layerValues = self.__getLayerValues(layer)

        if layerValues != None:
            thisTable = layerValues[0]
            oldDb = layerValues[1]
            self.__disconnectDb(oldDb)
            ui = layerValues[2]
            searchUi = layerValues[3]
            showParents = layerValues[4]
            thisSize = layerValues[5]
            self.ddLayers[layer.id()] = [thisTable,  db,  ui,  searchUi,  showParents,  thisSize,  None]

    def findPostgresLayer(self, db,  ddTable):
        procLayer = None # ini

        for aTreeLayer in QgsProject.instance().layerTreeRoot().findLayers():
            layer = aTreeLayer.layer()

            if layer != None:
                if 0 == layer.type(): # vectorLayer
                    src = layer.source()

                    if ("table=\"" + ddTable.schemaName + "\".\"" + ddTable.tableName + "\"" in src) and \
                        (db.databaseName() in src) and \
                        (db.hostName() in src):
                        procLayer = layer
                        break

        return procLayer

    def isEditable(self,  layer):
        '''check if data provider allows editing of table'''
        dp = layer.dataProvider()
        caps = dp.capabilities()
        return (caps & QgsVectorDataProvider.AddFeatures and caps & QgsVectorDataProvider.DeleteFeatures and \
            caps & QgsVectorDataProvider.ChangeAttributeValues)

    def isAccessible(self,  db,  ddTable,  showError = True):
        '''check if user has right to access this table'''
        query = QtSql.QSqlQuery(db)
        sQuery = "SELECT * FROM \"" + ddTable.schemaName + "\".\"" + ddTable.tableName + "\" LIMIT 1;"
        query.prepare(sQuery)
        query.exec_()

        if query.isActive():
            query.finish()
            return True
        else:
            query.finish()

            if showError:
                self.showQueryError(query,  True)
            return False

    def shuffleGroup(self, groupName, toTop = True):
        '''move position of group in layer panel to top or bottom'''

        group = self.getGroup(groupName)

        if group != None:
            root = QgsProject.instance().layerTreeRoot()

            if toTop:
                group2 = root.insertGroup(0, groupName)
            else:
                group2 = root.addGroup(groupName)

            root.removeChildNode(group)

            return group2
        else:
            return None

    def createGroup(self, groupName, atTop = True):
        '''create group in layer panel'''

        group = self.getGroup(groupName)

        if group == None:
            root = QgsProject.instance().layerTreeRoot()

            if atTop:
                return root.insertGroup(0, groupName)
            else:
                return root.addGroup(groupName)
        else:
            return self.shuffleGroup(groupName, atTop)

    def getGroup(self, groupName):
        '''Find group groupName in layer panel'''

        return QgsProject.instance().layerTreeRoot().findGroup(groupName)

    def moveLayerToGroup(self, layer, groupName):
        '''move layer to group in layer panel'''
        group = self.getGroup(groupName)

        if group == None:
            atTop = groupName != "DataDrivenInputMask"
            group = self.createGroup(groupName, atTop)
        else:
            if group.findLayer(layer.id()) != None:
                return True

        if group != None:
            root = QgsProject.instance().layerTreeRoot()
            layerTreeLayer = root.findLayer(layer.id())

            if layerTreeLayer != None:
                wasVisible = layerTreeLayer.itemVisibilityChecked()
                newLayerTreeLayer = group.addLayer(layer)
                newLayerTreeLayer.setItemVisibilityChecked(wasVisible)

                if root.removeLayer(layer) == None: # if layer in Root
                    try:
                        layerTreeLayer.parent().removeLayer(layer)
                        # if layer in root, crashed QGIS when calling parent() :-(
                    except:
                        pass
                return True
            else:
                return False
        else:
            return False

    def moveLayerintoDdGroup(self, layer):
        self.moveLayerToGroup(layer, "DataDrivenInputMask")

    def loadPostGISLayer(self,  db, ddTable, displayName = None,
        geomColumn = None, whereClause = None, keyColumn = None,
        intoDdGroup = True):

        if not self.isAccessible(db,  ddTable):
            DdError(QtWidgets.QApplication.translate("DdError", "Cannot not load table: ")+
            ddTable.schemaName + "." + ddTable.tableName,  fatal = True,  iface = self.iface)

        if not displayName:
            displayName = ddTable.schemaName + "." + ddTable.tableName

        uri = QgsDataSourceUri()
        thisPort = db.port()

        #these numbers are best guesses from the enumeration
        if hasattr(db, "sslmode"):
            if db.sslMode == "prefer":
                sslMode = QgsDataSourceUri.SslPprefer
            elif db.sslMode == "disable":
                sslMode = QgsDataSourceUri.SslDisable
            elif db.sslMode == "allow":
                sslMode = QgsDataSourceUri.SslAllow
            elif db.sslMode == "require":
                sslMode = QgsDataSourceUri.SslRequire
            elif db.sslMode == "verifyCA":
                sslMode = QgsDataSourceUri.SslVerifyCA
            elif db.sslMode == "verifyFull":
                sslMode = QgsDataSourceUri.SslVerifyFull
            else:
                sslMode = QgsDataSourceUri.SslPrefer # default anyway
        else:
            sslMode = QgsDataSourceUri.SslPrefer

        if thisPort == -1:
            thisPort = 5432

        # set service name or host name, port as well as database name, username and password
        authcfg = None #ini'

        serviceName = db.connectOptions().split("service=")[1]

        if serviceName != None:
            if hasattr(db, "authcfg"):
                authcfg = db.authcfg

                if authcfg != None:
                    uri.setConnection(serviceName, db.databaseName(), None, None, sslmode = sslMode, authConfigId = authcfg)

            if authcfg == None:
                uri.setConnection(serviceName, db.databaseName(), db.userName(), db.password(), sslmode = sslMode, authConfigId = '')

        if serviceName == None:
            if hasattr(db, "authcfg"):
                authcfg = db.authcfg

                if authcfg != None:
                    uri.setConnection(db.hostName(), str(thisPort), db.databaseName(),
                        None, None, sslmode = sslMode, authConfigId = authcfg)

            if authcfg == None:
                uri.setConnection(db.hostName(), str(thisPort), db.databaseName(),
                    db.userName(), db.password(), sslmode = sslMode)

        # set database schema, table name, geometry column and optionaly subset (WHERE clause) and key column
        uri.setDataSource(ddTable.schemaName, ddTable.tableName, geomColumn)

        if whereClause:
            uri.setSql(whereClause)

        if keyColumn:
            uri.setKeyColumn(keyColumn)

        if authcfg != None:
            layerUri = uri.uri(False)
        else:
            layerUri = uri.uri()

        vlayer = QgsVectorLayer(layerUri, displayName, "postgres",  QgsVectorLayer.LayerOptions(False,False))
        # double check if layer is valid
        if not vlayer.dataProvider().isValid():
            DdError(QtWidgets.QApplication.translate("DdError", "Cannot not load table: ") +
            ddTable.schemaName + "." + ddTable.tableName,  fatal = True,  iface = self.iface)

        QgsProject.instance().addMapLayer(vlayer)

        if intoDdGroup:
            self.moveLayerintoDdGroup(vlayer)

        return vlayer

    def quit(self):
        for ddLayer in list(self.ddLayers.values()):
            db = ddLayer[1]
            self.__disconnectDb(db)

    #Slots
    def editingStarted(self):
        layer = self.iface.activeLayer()

        if layer:
            layerValues = self.__getLayerValues(layer)

            if layerValues != None:
                db = layerValues[1]

                if not db:
                    db = self.__ceateDb(layer)
                    self.setDb(layer,  db)

    def editingStopped(self):
        pass
        # better keep the connection, if too many connections exist we must change this
        #self.__disconnectDb(db)
        #self.setDb(layer,  None)

    def __getLayerValues(self,  layer,  inputMask = True,  searchMask = True):
        '''Get this layer's values from ddLayers or create them'''

        try:
            layerValues = self.ddLayers[layer.id()]
        except KeyError:
            if self.initLayer(layer,  skip = [],  labels = {},  fieldOrder = [],  fieldGroups = {},  minMax = {},  noSearchFields = [],  \
                showParents = True,  createAction = True,  db = None,  inputMask = True,  searchMask = True,  \
                inputUi = None,  searchUi = None,  helpText = ""):
                layerValues = self.ddLayers[layer.id()]
            else:
                layerValues = None

        if layerValues != None:
            # check if needed masks are initialized
            inputMask = (inputMask and layerValues[2] == None)
            searchMask = (searchMask and layerValues[3] == None)

            if inputMask or searchMask:
                if self.initLayer(layer,  skip = [],  inputMask = inputMask,  searchMask = searchMask):
                    layerValues = self.ddLayers[layer.id()]
                else:
                    layerValues = None

        return layerValues

    def __getComment(self,  thisTable,  db):
        ''' query the DB to get a table's comment'''
        query = QtSql.QSqlQuery(db)
        sQuery = "SELECT description FROM pg_description \
        WHERE objoid = :oid AND objsubid = 0"
        # objsubid = 0 is the table, objsubid > 0 are comments on fields
        query.prepare(sQuery)
        query.bindValue(":oid", thisTable.oid)
        query.exec_()

        comment = None

        if query.isActive():
            if query.size() == 0:
                query.finish()
            else:
                while query.next():
                    comment = query.value(0)
                    break
                query.finish()
        else:
            DbError(query)

        return comment

    def __getOid(self,  thisTable,  db):
        return ddtools.getOid(thisTable,  db)

    def __isTable(self,  thisTable,  db):
        '''checks if the given relation is a table'''

        query = QtSql.QSqlQuery(db)
        sQuery = "SELECT * FROM pg_tables WHERE schemaname = :schema AND tablename = :table"
        query.prepare(sQuery)
        query.bindValue(":schema", thisTable.schemaName)
        query.bindValue(":table", thisTable.tableName)
        query.exec_()

        if query.isActive():
            if query.size() == 0:
                query.finish()
                return False
            else:
                query.finish()
                return True
        else:
            DbError(query)
            return False

    def __connectSignals(self,  layer):
        layer.editingStarted.connect(self.editingStarted)
        layer.editingStopped.connect(self.editingStopped)

    def __analyzeSource(self,  layer):
        '''Split the layer's source information and return them as a dict'''
        src = layer.source()
        result = dict()

        # allow spaces in dbname
        p = re.match('(dbname=\'(?P<name>[^\']*)\' *)+', src)

        if p != None:
            result["dbname"] = p.groups()[1]

        srcList = src.split(' ')

        for anElement in srcList:
            aPair = anElement.replace("'",  "").split("=")
            value = ""

            for i in range(len(aPair)):
                if i == 0:
                    key = aPair[i]
                elif i == 1:
                    value = aPair[i]
                else: # if value element contains "=", e.g. in passwords
                    value += "=" + aPair[i]

                if key == "dbname" and p != None:
                    continue
                else:
                    result[key] = value

        return result

    def __executeConfigQuery(self,  db, sQuery):
        '''execute a query for manipulating the config tables
        returns the query or None on error '''
        query = QtSql.QSqlQuery(db)
        query.exec_(sQuery)

        if query.isActive():
            return query
        else:
            query.finish()
            self.showQueryError(query,  True)
            return None


    def __connectDb(self, qSqlDatabaseName, host,
            database, port, username, passwd, sslmode = None,
            authcfg = None):
        '''connect to the PostgreSQL DB'''

        db = QtSql.QSqlDatabase.addDatabase ("QPSQL",  qSqlDatabaseName)
        db.setHostName(host)
        db.setPort(port)
        db.setDatabaseName(database)
        db.setUserName(username)
        db.setPassword(passwd)
        db.authcfg = authcfg
        db.sslMode = sslmode

        if sslmode == "require":
            db.setConnectOptions("requiressl=1")

        ok = db.open()

        if not ok:
            DdError(QtWidgets.QApplication.translate("DdError", "Could not connect to PostgreSQL database: ") +
            database,  iface = self.iface)
            self.showError(db.lastError().text())
            return None
        else:
            return db

    def __connectServiceDb(self,  qSqlDatabaseName,  service,  username,  passwd, authcfg = None):
        '''connect to the PostgreSQL DB via pg_service'''
        db = QtSql.QSqlDatabase.addDatabase ("QPSQL",  qSqlDatabaseName)
        db.setConnectOptions(f"service={service}")
        db.setUserName(username)
        db.setPassword(passwd)
        db.authcfg = authcfg
        ok = db.open()

        if not ok:
            DdError(QtWidgets.QApplication.translate("DdError", "Could not connect to PostgreSQL service: ") +
            service,  iface = self.iface)
            return None
        else:
            return db

    def __createDb(self,  layer):
        '''create a QtSql.QSqlDatabase object  for the DB-connection this layer comes from'''
        layerSrc = self.__analyzeSource(layer)
        authcfg = None # initialize

        try:
            service = layerSrc["service"]
            host = None
        except KeyError:
            try:
                host = layerSrc["host"]
            except KeyError:
                host = '127.0.0.1' # we assume localhost

            dbname = layerSrc["dbname"]

        try:
            authcfg = layerSrc["authcfg"]
        except KeyError:
            pass

        if authcfg == None:
            try:
                user = layerSrc["user"]
            except KeyError:
                user, ok = QtWidgets.QInputDialog.getText(None,
                    QtWidgets.QApplication.translate("DdWarning", "Username missing"),
                    QtWidgets.QApplication.translate("DdWarning", "Enter username for ") +
                    dbname + "." + host)

                if not ok:
                    return None

            try:
                password = layerSrc["password"]
            except KeyError:
                password, ok = QtWidgets.QInputDialog.getText(None,
                    QtWidgets.QApplication.translate("DdWarning", "Password missing"),
                    QtWidgets.QApplication.translate("DdWarning", "Enter password for ") +
                    user + u"@" + dbname + host,
                    QtWidgets.QLineEdit.Password)

                if not ok:
                    return None
        else:
            amc = qgis.core.QgsAuthMethodConfig()
            QgsApplication.authManager().loadAuthenticationConfig(authcfg, amc, True)
            user = amc.config( "username" )
            password = amc.config( "password" )

        try:
            sslmode = layerSrc["sslmode"]
        except KeyError:
            sslmode = None

        if host == None:
            db = self.__connectServiceDb(layer.id(), service, user, password, authcfg)
        else:
            db = self.__connectDb(layer.id(), host, dbname,
                int(layerSrc["port"]), user,
                password, sslmode, authcfg)

        return db

    def __disconnectDb(self,  db):
        '''disconnect from the DB'''
        if db:
            db.close()
            db = None

    def __getInputWidget(self, layer, attributeName):
        layerValues = self.__getLayerValues(layer)
        ui = layerValues[2]
        searchUi = layerValues[3]

        if ui != None:
            theseForms = ui.forms
        else:
            if searchUi != None:
                theseForms = searchUi.forms
            else:
                return None

        for i in range(len(theseForms)):
            theseInputWidgets = theseForms[i].inputWidgets

            for j in range(len(theseInputWidgets)):
                aDdWidget = theseInputWidgets[j]
                if aDdWidget.attribute.name == attributeName:
                    return [aDdWidget, i, j]

        return None

    def updateConfigTables(self,  db):
        '''function to update the config tables if anything changes'''

        if self.latestConfigTablesVersion:
            return True # do not check if it has already been checked

        changeToVersion060 = False
        sQuery = "SELECT t.typname as typ \
        FROM pg_attribute att \
        JOIN pg_type t ON att.atttypid = t.oid \
        JOIN pg_class c ON attrelid = c.oid \
        JOIN pg_namespace n ON c.relnamespace = n.oid \
        WHERE n.nspname = \'public\' AND c.relname = \'dd_field\' \
        AND attname= \'field_min\'"
        query = self.__executeConfigQuery(db,  sQuery)

        if query != None:
            while query.next():
                changeToVersion060 = query.value(0) == "float8"
            query.finish()
        else:
            return False

        if changeToVersion060:
            #recreate table and transfer data
            sQuery = "ALTER TABLE \"public\".\"dd_field\" RENAME \"field_min\" TO \"field_min_old\"; \
            ALTER TABLE \"public\".\"dd_field\" RENAME \"field_max\" TO \"field_max_old\"; \
            ALTER TABLE \"public\".\"dd_field\" ADD COLUMN \"field_min\" VARCHAR(32) NULL; \
            ALTER TABLE \"public\".\"dd_field\" ADD COLUMN \"field_max\" VARCHAR(32) NULL; \
            COMMENT ON COLUMN  \"public\".\"dd_field\".\"field_min\" IS \'min value of the field (only for numeric and date fields). Use point as decimal seperator, format date as \"yyyy-MM-dd\", insert \"today\" to set the min date on the current date.\';\
            COMMENT ON COLUMN  \"public\".\"dd_field\".\"field_max\" IS \'max value of the field (only for numeric and date fields). Use point as decimal seperator, format date as \"yyyy-MM-dd\", insert \"today\" to set the max date on the current date.\'; "
            query = self.__executeConfigQuery(db,  sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "UPDATE \"public\".\"dd_field\" SET \"field_min\" = CAST (\"field_min_old\" as varchar) WHERE \"field_min_old\" IS NOT NULL; \
            UPDATE \"public\".\"dd_field\" SET \"field_max\" = CAST (\"field_max_old\" as varchar) WHERE \"field_max_old\" IS NOT NULL;"

            query = self.__executeConfigQuery(db,  sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "ALTER TABLE \"public\".\"dd_field\" DROP COLUMN \"field_min_old\"; \
            ALTER TABLE \"public\".\"dd_field\" DROP COLUMN \"field_max_old\";"
            query = self.__executeConfigQuery(db,  sQuery)

            if query != None:
                query.finish()
            else:
                return False

        changeToVersion090 = False

        sQuery = "SELECT \"field_enabled\" FROM \"public\".\"dd_field\";"

        query = QtSql.QSqlQuery(db)
        query.exec_(sQuery)

        if not query.isActive():
            changeToVersion090 = True

        query.finish()

        if changeToVersion090:
            sQuery = "ALTER TABLE \"public\".\"dd_field\" \
                ADD COLUMN field_enabled boolean;"
            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "UPDATE \"public\".\"dd_field\" \
                SET field_enabled = true;"
            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "ALTER TABLE \"public\".\"dd_field\" \
                ALTER COLUMN field_enabled SET NOT NULL;"

            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "ALTER TABLE \"public\".\"dd_field\" \
                ALTER COLUMN field_enabled SET DEFAULT true;"

            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "COMMENT ON COLUMN \"public\".\"dd_field\".\"field_enabled\" \
                IS \'Enable or disable this field in the input mask\';"

            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

        changeToVersion200 = False

        sQuery = "SELECT \"field_multiline\" FROM \"public\".\"dd_field\";"

        query = QtSql.QSqlQuery(db)
        query.exec_(sQuery)

        if not query.isActive():
            changeToVersion200 = True

        query.finish()

        if changeToVersion200:
            sQuery = "ALTER TABLE \"public\".\"dd_field\" \
                ADD COLUMN \"field_multiline\" boolean;"
            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "ALTER TABLE \"public\".\"dd_field\" \
                ALTER COLUMN \"field_multiline\" SET DEFAULT false;"
            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "COMMENT ON COLUMN \"public\".\"dd_field\".\"field_multiline\" \
            IS \'If the field is a char field, make it multiline\';"
            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "ALTER TABLE \"public\".\"dd_field\" \
                ADD COLUMN \"lookup_field\" VARCHAR(256);"
            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "COMMENT ON COLUMN  \"public\".\"dd_field\".\"lookup_field\" \
            IS \'If the field contains a foreign key to a lookup table, input the name of the field in the lookup table containing the values to be displayed in the combo box.\';"
            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

        changeToVersion220a = False

        sQuery = "SELECT \"lookup_expression\" FROM \"public\".\"dd_field\";"

        query = QtSql.QSqlQuery(db)
        query.exec_(sQuery)

        if not query.isActive():
            changeToVersion220a = True

        query.finish()

        if changeToVersion220a:
            sQuery = "ALTER TABLE \"public\".\"dd_field\" \
                ADD COLUMN \"lookup_expression\" TEXT;"
            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "COMMENT ON COLUMN  \"public\".\"dd_field\".\"lookup_expression\" \
            IS \'If the field contains a foreign key to a lookup table, input an expression containing the values to be displayed in the combo box. The most simple expression is the name of a field.\';"
            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "UPDATE \"public\".\"dd_field\" \
                SET \"lookup_expression\" = \'\"\' || lookup_field || \'\"\';"
            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "ALTER TABLE \"public\".\"dd_field\" \
                DROP COLUMN \"lookup_field\";"
            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

        changeToVersion220b = False

        sQuery = "SELECT \"where_clause\" FROM \"public\".\"dd_field\";"

        query = QtSql.QSqlQuery(db)
        query.exec_(sQuery)

        if not query.isActive():
            changeToVersion220b = True

        query.finish()

        if changeToVersion220b:
            sQuery = "ALTER TABLE \"public\".\"dd_field\" \
                ADD COLUMN \"where_clause\" TEXT;"
            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

            sQuery = "COMMENT ON COLUMN \"public\".\"dd_field\".\"where_clause\" IS \'If the field contains a foreign key to a lookup table, input an SQL-WHERE clause (without the WHERE keyword!) to filter the values available in the combo box.\';"
            query = self.__executeConfigQuery(db, sQuery)

            if query != None:
                query.finish()
            else:
                return False

        self.latestConfigTablesVersion = True
        return True

    def createConfigTables(self,  db):
        sQuery = "CREATE TABLE  \"public\".\"dd_table\" (\
            \"id\" SERIAL NOT NULL,\
            \"table_schema\" VARCHAR(256) NOT NULL,\
            \"table_name\" VARCHAR(256) NOT NULL,\
            \"table_help\" TEXT NULL,\
            \"table_action\" BOOLEAN NOT NULL DEFAULT \'t\',\
            PRIMARY KEY (\"id\"));\
        GRANT SELECT ON TABLE \"public\".\"dd_table\" TO public;\
        COMMENT ON TABLE \"public\".\"dd_table\" IS \'DataDrivenInputMask: contains tables with a configuration for the mask, no need to input tables for which the default data-driven mask is to be shown\';\
        COMMENT ON COLUMN \"public\".\"dd_table\".\"table_schema\" IS \'name of the schema\';\
        COMMENT ON COLUMN \"public\".\"dd_table\".\"table_name\" IS \'name of the table\';\
        COMMENT ON COLUMN \"public\".\"dd_table\".\"table_help\" IS \'Help string to be shown if user clicks the help button, this string can be HTML formatted.\';\
        COMMENT ON COLUMN \"public\".\"dd_table\".\"table_action\" IS \'Create a layer action to show the mask\';\
        INSERT INTO \"public\".\"dd_table\" (\"table_schema\", \"table_name\") VALUES(\'public\', \'dd_table\');\
        INSERT INTO \"public\".\"dd_table\" (\"table_schema\", \"table_name\") VALUES(\'public\', \'dd_tab\');\
        INSERT INTO \"public\".\"dd_table\" (\"table_schema\", \"table_name\") VALUES(\'public\', \'dd_field\');\
        CREATE TABLE  \"public\".\"dd_tab\" (\
            \"id\" SERIAL NOT NULL,\
            \"dd_table_id\" INTEGER NOT NULL,\
            \"tab_alias\" VARCHAR(256) NULL,\
            \"tab_order\" INTEGER NOT NULL DEFAULT 0,\
            \"tab_tooltip\" VARCHAR(256) NULL,\
            PRIMARY KEY (\"id\"),\
            CONSTRAINT \"fk_dd_tab_dd_table\"\
                FOREIGN KEY (\"dd_table_id\")\
                REFERENCES \"public\".\"dd_table\" (\"id\")\
                ON DELETE CASCADE\
                ON UPDATE CASCADE);\
        GRANT SELECT ON TABLE \"public\".\"dd_tab\" TO public;\
        CREATE INDEX \"idx_fk_dd_tab_dd_table_idx\" ON \"public\".\"dd_tab\" (\"dd_table_id\");\
        COMMENT ON TABLE \"public\".\"dd_tab\" IS \'DataDrivenInputMask: contains tabs for tables\';\
        COMMENT ON COLUMN \"public\".\"dd_tab\".\"dd_table_id\" IS \'Table for which this tab is used\';\
        COMMENT ON COLUMN \"public\".\"dd_tab\".\"tab_alias\" IS \'Label the tab with this string, leave empty if you want the data-driven tabs\';\
        COMMENT ON COLUMN \"public\".\"dd_tab\".\"tab_order\" IS \'Order of the tabs in the mask (if a mask contains more than one tabs)\';\
        COMMENT ON COLUMN \"public\".\"dd_tab\".\"tab_tooltip\" IS \'tooltip to be shown for this tab\';\
        INSERT INTO \"public\".\"dd_tab\" (\"dd_table_id\") VALUES(1);\
        INSERT INTO \"public\".\"dd_tab\" (\"dd_table_id\") VALUES(2);\
        INSERT INTO \"public\".\"dd_tab\" (\"dd_table_id\") VALUES(3);\
        CREATE TABLE  \"public\".\"dd_field\" (\
            \"id\" SERIAL NOT NULL,\
            \"dd_tab_id\" INTEGER NOT NULL,\
            \"field_name\" VARCHAR(256) NOT NULL,\
            \"field_alias\" VARCHAR(256) NULL,\
            \"field_skip\" BOOLEAN NOT NULL DEFAULT \'f\',\
            \"field_search\" BOOLEAN NOT NULL DEFAULT \'t\',\
            \"field_order\" INTEGER NOT NULL DEFAULT 0,\
            \"field_min\" VARCHAR(32) NULL,\
            \"field_max\" VARCHAR(32) NULL,\
            \"field_enabled\" BOOLEAN NOT NULL DEFAULT \'t\',\
            \"field_multiline\" BOOLEAN NULL DEFAULT \'f\',\
            \"lookup_expression\" TEXT NULL,\
            \"where_clause\" TEXT NULL,\
            PRIMARY KEY (\"id\"),\
            CONSTRAINT \"fk_dd_field_dd_tab\"\
                FOREIGN KEY (\"dd_tab_id\")\
                REFERENCES \"public\".\"dd_tab\" (\"id\")\
                ON DELETE CASCADE\
                ON UPDATE CASCADE);\
        GRANT SELECT ON TABLE \"public\".\"dd_field\" TO public;\
        CREATE INDEX \"idx_fk_dd_field_dd_tab_idx\" ON \"public\".\"dd_field\" (\"dd_tab_id\");\
        COMMENT ON TABLE  \"public\".\"dd_field\" IS \'DataDrivenInputMask: the data-driven mask for fields can be configured here.\';\
        COMMENT ON COLUMN  \"public\".\"dd_field\".\"dd_tab_id\" IS \'All fields not included here will be put in the tab with the highest tab_order. One and the same field should be included in _one_ tab only.\';\
        COMMENT ON COLUMN  \"public\".\"dd_field\".\"field_name\" IS \'Name of the field in the database\';\
        COMMENT ON COLUMN  \"public\".\"dd_field\".\"field_alias\" IS \'Alias of the field to be used in the mask\';\
        COMMENT ON COLUMN  \"public\".\"dd_field\".\"field_skip\" IS \'skip this field in the input and search mask, i.e. hide it from the user\';\
        COMMENT ON COLUMN  \"public\".\"dd_field\".\"field_search\" IS \'include this field in the search mask, if skip is true the field is not shown in the search mask, no matter if search is true\';\
        COMMENT ON COLUMN  \"public\".\"dd_field\".\"field_order\" IS \'order of the fields in the mask\';\
        COMMENT ON COLUMN  \"public\".\"dd_field\".\"field_min\" IS \'min value of the field (only for numeric and date fields). Use point as decimal seperator, format date as \"yyyy-MM-dd\", insert \"today\" to set the min date on the current date or \"today +/- num_days\" for a certain day relative to the current date.\';\
        COMMENT ON COLUMN  \"public\".\"dd_field\".\"field_max\" IS \'max value of the field (only for numeric and date fields). Use point as decimal seperator, format date as \"yyyy-MM-dd\", insert \"today\" to set the max date on the current date or \"today +/- num_days\" for a certain day relative to the current date.\';\
        COMMENT ON COLUMN  \"public\".\"dd_field\".\"field_enabled\" IS \'Enable or disable this field in the input mask\';\
        COMMENT ON COLUMN \"public\".\"dd_field\".\"field_multiline\" IS \'If the field is a char field, make it multiline\';\
        COMMENT ON COLUMN \"public\".\"dd_field\".\"lookup_expression\" IS \'If the field contains a foreign key to a lookup table, input an expression containing the values to be displayed in the combo box. The most simple expression is the name of a field.\'; \
        COMMENT ON COLUMN \"public\".\"dd_field\".\"where_clause\" IS \'If the field contains a foreign key to a lookup table, input an SQL-WHERE clause (without the WHERE keyword!) to filter the values available in the combo box.\'; \
        INSERT INTO \"public\".\"dd_field\" (\"dd_tab_id\", \"field_name\", \"field_skip\") VALUES(1, \'id\', \'t\');\
        INSERT INTO \"public\".\"dd_field\" (\"dd_tab_id\", \"field_name\", \"field_skip\") VALUES(2, \'id\', \'t\');\
        INSERT INTO \"public\".\"dd_field\" (\"dd_tab_id\", \"field_name\", \"field_skip\") VALUES(3, \'id\', \'t\');"

        query = self.__executeConfigQuery(db,  sQuery)

        if query != None:
            query.finish()
            self.iface.messageBar().pushMessage(QtWidgets.QApplication.translate("DdInfo",
                    "Config tables created! SELECT has been granted to \"public\"."))
            self.latestConfigTablesVersion = True
            return True
        else:
            return False

    def showQueryError(self, query,  withSql = False):
        self.iface.messageBar().pushMessage(
            "Database Error",  "%(error)s" % {"error": query.lastError().text()},
            level=Qgis.Critical)

        if withSql:
            self.iface.messageBar().pushMessage("Query",
                "%(query)s" % {"query": query.lastQuery()},level=Qgis.Critical)

    def showError(self,  msg):
        DdError(msg,  iface = self.iface)
