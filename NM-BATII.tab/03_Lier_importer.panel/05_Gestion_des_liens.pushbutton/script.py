# -*- coding: utf-8 -*-

# Copyright 2026 data8bim (d8b)
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


#__title__ = 'Gestion des liens'
#__author__ = 'data8bim (d8b)'

from Autodesk.Revit.UI import RevitCommandId, PostableCommand

# __revit__ est l'UIApplication fournie par pyRevit
uiapp = __revit__  # noqa

# Récupère l'ID de la commande "Gestion des liens"
cmd_id = RevitCommandId.LookupPostableCommandId(PostableCommand.ManageLinks)

# Exécute la commande
uiapp.PostCommand(cmd_id)