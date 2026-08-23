# -*- coding: utf-8 -*-

# Copyright (C) 2026 data8bim (d8b)
#
# This file is part of py-NM-BATII.
#
# py-NM-BATII is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# py-NM-BATII is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with py-NM-BATII. If not, see <https://www.gnu.org/licenses/>.


#__title__ = 'Légende de motif/couleur'
#__author__ = 'data8bim (d8b)'

from Autodesk.Revit.UI import RevitCommandId, PostableCommand

# __revit__ est l'UIApplication fournie par pyRevit
uiapp = __revit__  # noqa

# Récupère l'ID de la commande native "Légende de motif/couleur"
# (Annoter > Couleur > Légende de motif/couleur)
cmd_id = RevitCommandId.LookupPostableCommandId(PostableCommand.ColorFillLegend)

# Exécute la commande
uiapp.PostCommand(cmd_id)
