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


#__title__ = 'Liste fichiers liés'
#__author__ = 'data8bim (d8b)'

import os
import sys
from pyrevit import revit, forms
from Autodesk.Revit.DB import (
    FilteredElementCollector,
    ImportInstance,
    RevitLinkInstance,
    RevitLinkType,
    ExternalFileReferenceType,
    BuiltInParameter,
    ImageInstance,
    ElementId,
)

# Ajouter lib/ au sys.path pour importer les utilitaires partagés
script_dir = os.path.dirname(__file__)
ext_dir = os.path.abspath(
    os.path.join(script_dir, os.pardir, os.pardir, os.pardir)
)
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

from dialogs.dialogs_styles_loader import show_alert

# Charger la boîte XAML
xaml_path = os.path.join(os.path.dirname(__file__), "DWGLinkedDumpDialog.xaml")
if not os.path.isfile(xaml_path):
    show_alert(u"Erreur", u"XAML introuvable :\n{}".format(xaml_path))
    raise SystemExit

doc = revit.doc

# ──────────────────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────────────────

def get_view_name(view_id):
    """Retourne le nom de la vue associée à un élément view-specific."""
    if view_id is None or view_id == ElementId.InvalidElementId:
        return u"Toutes les vues"
    view = doc.GetElement(view_id)
    if view:
        return view.Name
    return u"Vue inconnue"


def get_import_filename(inst):
    """Retourne le nom de fichier d'un ImportInstance via son type."""
    typ = doc.GetElement(inst.GetTypeId())
    if not typ:
        return u"<inconnu>"
    p = typ.get_Parameter(BuiltInParameter.SYMBOL_NAME_PARAM)
    if p:
        return p.AsString() or u"<sans nom>"
    return typ.Name or u"<inconnu>"


def classify_import(filename):
    """Retourne la catégorie CAO selon l'extension du fichier."""
    lower = filename.lower()
    if lower.endswith(".dwg"):
        return "DWG"
    if lower.endswith(".dxf"):
        return "DXF"
    if lower.endswith(".dgn"):
        return "DGN"
    if lower.endswith(".sat") or lower.endswith(".iges") or lower.endswith(".igs") or lower.endswith(".step"):
        return "3D (SAT/IGES)"
    return "CAO"


def get_rvt_link_info(inst):
    """Retourne (nom, statut) pour un RevitLinkInstance."""
    typ = doc.GetElement(inst.GetTypeId())
    name = inst.Name
    statut = u"?"
    if typ:
        try:
            ref = typ.GetExternalFileReference()
            path = ref.GetAbsolutePath() if ref else None
            if path:
                name = os.path.basename(str(path))
        except Exception:
            pass
        try:
            s = typ.GetLinkedFileStatus()
            statut_map = {
                0: u"Non chargé",
                1: u"Chargé",
                2: u"En cours de chargement",
                3: u"Introuvable",
                4: u"Non initialisé",
            }
            statut = statut_map.get(int(s), str(s))
        except Exception:
            statut = u"?"
    return name, statut


# ──────────────────────────────────────────────────────────────────────────────
# Collecte
# ──────────────────────────────────────────────────────────────────────────────

# RVT liés
rvt_lies = list(FilteredElementCollector(doc).OfClass(RevitLinkInstance))

# DWG/DXF/DGN liés et importés (ImportInstance)
cao_lies = {}    # {nom: [vue, ...]}
cao_importes = {}  # {(nom, categorie): [vue, ...]}

for inst in FilteredElementCollector(doc).OfClass(ImportInstance):
    fname = get_import_filename(inst)
    cat = classify_import(fname)
    vue = get_view_name(inst.OwnerViewId if inst.ViewSpecific else None)
    if inst.IsLinked:
        if fname not in cao_lies:
            cao_lies[fname] = []
        if vue not in cao_lies[fname]:
            cao_lies[fname].append(vue)
    else:
        key = (fname, cat)
        if key not in cao_importes:
            cao_importes[key] = []
        if vue not in cao_importes[key]:
            cao_importes[key].append(vue)

# Images
images = []
try:
    for inst in FilteredElementCollector(doc).OfClass(ImageInstance):
        typ = doc.GetElement(inst.GetTypeId())
        if typ:
            p = typ.get_Parameter(BuiltInParameter.RASTER_SYMBOL_FILENAME)
            fname = p.AsString() if p else typ.Name
        else:
            fname = inst.Name or u"<inconnu>"
        vue = get_view_name(inst.OwnerViewId if inst.ViewSpecific else None)
        images.append((os.path.basename(fname) if fname else u"<inconnu>", vue))
except Exception:
    pass

# Nuages de points
nuages = []
try:
    from Autodesk.Revit.DB.PointClouds import PointCloudInstance
    for inst in FilteredElementCollector(doc).OfClass(PointCloudInstance):
        typ = doc.GetElement(inst.GetTypeId())
        name = typ.Name if typ else inst.Name or u"<inconnu>"
        nuages.append(name)
except Exception:
    pass


# ──────────────────────────────────────────────────────────────────────────────
# Formatage
# ──────────────────────────────────────────────────────────────────────────────

SEP  = u"=" * 60
SEP2 = u"-" * 40
lines = []

def section(titre, nb):
    lines.append(SEP)
    lines.append(u"  {} ({})".format(titre, nb))
    lines.append(SEP)

# 1. RVT liés
section(u"MODELES REVIT LIES (.rvt)", len(rvt_lies))
if rvt_lies:
    for inst in sorted(rvt_lies, key=lambda x: x.Name):
        name, statut = get_rvt_link_info(inst)
        lines.append(u"  * {}  [{}]".format(name, statut))
else:
    lines.append(u"  (aucun)")
lines.append(u"")

# 2. CAO liés
cao_lies_grouped = {}  # cat -> [(nom, vues)]
for fname, vues in sorted(cao_lies.items()):
    cat = classify_import(fname)
    if cat not in cao_lies_grouped:
        cao_lies_grouped[cat] = []
    cao_lies_grouped[cat].append((fname, vues))

nb_lies = sum(len(v) for v in cao_lies_grouped.values())
section(u"FICHIERS CAO LIES (DWG/DXF/DGN/...)", nb_lies)
if cao_lies_grouped:
    for cat in sorted(cao_lies_grouped.keys()):
        lines.append(u"  -- {} --".format(cat))
        for fname, vues in cao_lies_grouped[cat]:
            lines.append(u"  * {}".format(fname))
            for vue in vues:
                lines.append(u"      Vue : {}".format(vue))
else:
    lines.append(u"  (aucun)")
lines.append(u"")

# 3. CAO importés
cao_imp_grouped = {}  # cat -> [(nom, vues)]
for (fname, cat), vues in sorted(cao_importes.items()):
    if cat not in cao_imp_grouped:
        cao_imp_grouped[cat] = []
    cao_imp_grouped[cat].append((fname, vues))

nb_imp = sum(len(v) for v in cao_imp_grouped.values())
section(u"FICHIERS CAO IMPORTES (DWG/DXF/DGN/...)", nb_imp)
if cao_imp_grouped:
    for cat in sorted(cao_imp_grouped.keys()):
        lines.append(u"  -- {} --".format(cat))
        for fname, vues in cao_imp_grouped[cat]:
            lines.append(u"  * {}".format(fname))
            for vue in vues:
                lines.append(u"      Vue : {}".format(vue))
else:
    lines.append(u"  (aucun)")
lines.append(u"")

# 4. Images
section(u"IMAGES LIEES / IMPORTEES", len(images))
if images:
    for fname, vue in sorted(images):
        lines.append(u"  * {}  (Vue : {})".format(fname, vue))
else:
    lines.append(u"  (aucun)")
lines.append(u"")

# 5. Nuages de points
section(u"NUAGES DE POINTS", len(nuages))
if nuages:
    for name in sorted(nuages):
        lines.append(u"  * {}".format(name))
else:
    lines.append(u"  (aucun)")
lines.append(u"")

# ──────────────────────────────────────────────────────────────────────────────
# Affichage
# ──────────────────────────────────────────────────────────────────────────────

win = forms.WPFWindow(xaml_path)
win.Title = u"Fichiers liés – {}".format(doc.Title)
win.txtDump.Text = u"\n".join(lines)
win.btnClose.Click += lambda s, e: win.Close()
win.show_dialog()
