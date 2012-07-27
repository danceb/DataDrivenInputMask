# -*- coding: utf-8 -*-
"""
/***************************************************************************
 DataDrivenDialog
                                 A QGIS plugin
 Applies a data-driven input mask to any PostGIS-Layer
                             -------------------
        begin                : 2012-06-21
        copyright            : (C) 2012 by Bernhard Ströbl / Kommunale Immobilien Jena
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

from PyQt4 import QtGui

# create the dialog
class DdDialog(QtGui.QDialog):
    def __init__(self,  iface,  ui,  layer,  feature,  db):
        QtGui.QDialog.__init__(self)
        # Set up the user interface from Designer.
        self.iface = iface
        self.ui = ui
        #QtGui.QMessageBox.information(None, "", str(self.ui))
        self.layer = layer
        self.feature = feature
        self.db = db
        self.ui.setupUi(self,  self.db)
        okBtn = self.ui.buttonBox.button(QtGui.QDialogButtonBox.Ok)
        okBtn.setEnabled(self.layer.isEditable())
        self.initialize()

    def initialize(self):
        self.ui.initialize(self.layer,  self.feature,  self.db)

    def accept(self):
        if self.ui.checkInput():
            self.ui.save(self.layer,  self.feature,  self.db)
            self.done(1)
