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


#__title__ = "Nettoyer Vues"
#__doc__ = """Nettoyer les vues
#Description : Nettoie en une passe : DWG importés, DWG liés, lignes, notes textuelles, pièces et espaces non nommés et hachures issues des dwg décomposés (zones de pochages).

#Version : 3.3 — 2026-04-17
#Auteur : data8bim (d8b)
#"""


import os
import sys

from pyrevit import revit, DB, script, forms
from System.Windows.Controls import CheckBox
from System.Collections.Generic import List

# 1) Ajouter lib/ au sys.path pour importer les utilitaires partagés
script_dir = os.path.dirname(__file__)
ext_dir    = os.path.abspath(os.path.join(script_dir, os.pardir, os.pardir, os.pardir))
lib_dir    = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

# 2) Import du chargeur de config
from utils.config_loader import load_config

# 3) Chargement de la config et extraction des valeurs par défaut
config             = load_config()
nettoyage_defaults = config.get("nettoyage", {})

# 4) Charger les styles WPF (facultatif)
from dialogs.dialogs_styles_loader import load as load_styles
load_styles(lib_dir=lib_dir)

# 5) Définition des chemins vers les XAML
xaml_path   = os.path.join(script_dir, "CleanViewsDialog.xaml")
result_xaml = os.path.join(script_dir, "ResultWindow.xaml")

# 6) Types de vues autorisées
VALID_VIEW_TYPES = {
    DB.ViewType.FloorPlan,
    DB.ViewType.CeilingPlan,
    DB.ViewType.EngineeringPlan,
    DB.ViewType.AreaPlan,
    DB.ViewType.Elevation,
    DB.ViewType.Section
}

# 7) Liste des opérations proposées
OPERATIONS = [
    ("dwg_imports",    "DWG importés (non liés)"),
    ("dwg_liens",      "DWG liés"),
    ("lignes",         "Lignes de modèle"),
    ("texts",          "Notes textuelles"),
    ("pieces_espaces", "Pièces et Espaces sans nom"),
    ("zones_pochages", "Hachurages dwg (Zones de pochages)")
]


class CleanAllDialog(forms.WPFWindow):
    """Boîte de dialogue pour le nettoyage global."""
    def __init__(self, xaml_file):
        forms.WPFWindow.__init__(self, xaml_file)

        self.selected_ops   = set()
        self.selected_views = []
        self.defaults       = nettoyage_defaults

        # Liste complète des vues pour le filtre
        self.all_views = []

        # Init UI
        self._init_operations()
        self._init_views()
        self._bind_events()

    def _init_operations(self):
        """Crée les CheckBox d’opérations."""
        for key, label in OPERATIONS:
            cb = CheckBox()
            cb.Content   = label
            cb.Tag       = key
            cb.IsChecked = bool(self.defaults.get(key, False))
            self.panelOptions.Children.Add(cb)

    def _init_views(self):
        """Charge, trie et affiche les vues dans le ListBox."""
        all_views = DB.FilteredElementCollector(revit.doc) \
                      .OfClass(DB.View) \
                      .WhereElementIsNotElementType() \
                      .ToElements()

        self.all_views = sorted(
            (v for v in all_views
               if not v.IsTemplate and v.ViewType in VALID_VIEW_TYPES),
            key=lambda v: v.Name
        )

        # Affichage initial sans filtre
        self.listBoxViews.ItemsSource = List[DB.View](self.all_views)

    def _bind_events(self):
        """Enregistre les handlers UI."""
        # Opérations
        self.btnSelectAllOps.Click   += lambda s,e: self._check_all(self.panelOptions, True)
        self.btnDeselectAllOps.Click += lambda s,e: self._check_all(self.panelOptions, False)

        # Vues (SelectAll / UnselectAll / Invert)
        self.btnSelectAllViews.Click   += lambda s,e: self.listBoxViews.SelectAll()
        self.btnDeselectAllViews.Click += lambda s,e: self.listBoxViews.UnselectAll()
        self.btnInvertViews.Click      += lambda s,e: self._invert_listbox(self.listBoxViews)

        # Filtre TextChanged
        self.txtFilterViews.TextChanged += self._on_filter_text_changed

        # Validation / Annulation
        self.OkButton.Click     += self._on_ok
        self.CancelButton.Click += self._on_user_cancel
        self.Closing            += self._on_user_cancel_dialog

    def _check_all(self, panel, check):
        """Coche/décoche toutes les cases d’un StackPanel."""
        for cb in panel.Children:
            cb.IsChecked = check

    def _invert_listbox(self, lb):
        """Inverse la sélection pour tous les items du ListBox."""
        current = set(lb.SelectedItems)
        lb.UnselectAll()
        for item in lb.Items:
            if item not in current:
                lb.SelectedItems.Add(item)

    def _on_filter_text_changed(self, sender, args):
        """Filtre la liste des vues dès que le texte change."""
        txt = self.txtFilterViews.Text.strip().lower()
        if not txt:
            filtered = self.all_views
        else:
            filtered = [v for v in self.all_views if txt in v.Name.lower()]

        # Réaffecte la source (utilise System.Collections.Generic.List pour compatibilité)
        self.listBoxViews.ItemsSource = List[DB.View](filtered)

    def _on_ok(self, sender, args):
        """Récupère sélection et ferme."""
        # Opérations
        for cb in self.panelOptions.Children:
            if getattr(cb, "IsChecked", False):
                self.selected_ops.add(cb.Tag)

        # Vues
        for v in self.listBoxViews.SelectedItems:
            self.selected_views.append(v)

        self.Close()

    def _on_user_cancel(self, sender, args):
        """Annuler -> exit."""
        self.Close()
        script.exit()

    def _on_user_cancel_dialog(self, sender, args):
        """Fermer via croix -> exit."""
        script.exit()


def resolve_excluded_categories(doc):
    """ID de catégories à exclure pour les lignes."""
    excluded = set()
    bic_groups = [
        ["OST_RoomSeparationLines"],
        ["OST_MEPSpaceSeparationLines", "OST_SpaceSeparationLines"],
        ["OST_AreaSchemeLines", "OST_AreaBoundaryLines", "OST_AreaLines"]
    ]
    for group in bic_groups:
        for name in group:
            try:
                eid = DB.ElementId(getattr(DB.BuiltInCategory, name))
                excluded.add(eid.IntegerValue)
            except:
                pass

    localized_sets = [
        {"Room Separation Lines", "Séparation de pièce", "Room Separation"},
        {"Space Separation Lines", "Séparation d'espace", "Space Separation"},
        {"Area Boundary Lines", "Limites d'aire", "Area Boundary"}
    ]
    for cat in doc.Settings.Categories:
        cname = (cat.Name or "").strip()
        for names in localized_sets:
            if cname in names:
                excluded.add(cat.Id.IntegerValue)
    return excluded


def main():
    dialog = CleanAllDialog(xaml_path)
    try:
        dialog.ShowDialog()
    except SystemExit:
        return

    ops   = dialog.selected_ops
    views = dialog.selected_views

    # 1. Aucune vue
    if not views:
        result_win = forms.WPFWindow(result_xaml)
        result_win.txtMessage.Text = u"⚠️ Aucune vue à nettoyer sélectionnée"
        result_win.btnClose.Click += lambda s, e: result_win.Close()
        result_win.ShowDialog()
        return

    # 2. Aucune option
    if not ops:
        result_win = forms.WPFWindow(result_xaml)
        result_win.txtMessage.Text = u"⚠️ Aucune option de nettoyage sélectionnée"
        result_win.btnClose.Click += lambda s, e: result_win.Close()
        result_win.ShowDialog()
        return

    doc    = revit.doc
    output = script.get_output()

    # Prépare les sets d'ID à supprimer
    to_delete = {
        "dwg_imports":             set(),
        "dwg_liens":               set(),
        "lignes":                  set(),
        "texts":                   set(),
        "pieces_espaces":          set(),
        "zones_pochages":          set(),
        "zones_pochages_type_ids": set()
    }

    # Types de zones .dwg- à supprimer
    all_types = DB.FilteredElementCollector(doc) \
                   .OfClass(DB.FilledRegionType) \
                   .ToElements()
    for ft in all_types:
        name = ft.get_Parameter(DB.BuiltInParameter.SYMBOL_NAME_PARAM).AsString()
        if name and ".dwg-" in name:
            to_delete["zones_pochages_type_ids"].add(ft.Id)

    excluded_cats = resolve_excluded_categories(doc)

    # Parcours des vues sélectionnées
    for view in views:
        vid = view.Id

        # DWG importés / liés
        if "dwg_imports" in ops or "dwg_liens" in ops:
            imps = DB.FilteredElementCollector(doc, vid) \
                      .OfClass(DB.ImportInstance) \
                      .ToElements()
            for imp in imps:
                try:
                    if imp.IsLinked and "dwg_liens" in ops:
                        to_delete["dwg_liens"].add(imp.Id)
                    elif not imp.IsLinked and "dwg_imports" in ops:
                        to_delete["dwg_imports"].add(imp.Id)
                except:
                    pass

        # Lignes
        if "lignes" in ops:
            curves = DB.FilteredElementCollector(doc, vid) \
                        .OfClass(DB.CurveElement) \
                        .ToElements()
            for c in curves:
                if c.Category and c.Category.Id.IntegerValue not in excluded_cats:
                    to_delete["lignes"].add(c.Id)

        # Notes textuelles
        if "texts" in ops:
            text_ids = DB.FilteredElementCollector(doc, vid) \
                          .OfClass(DB.TextNote) \
                          .ToElementIds()
            to_delete["texts"].update(text_ids)

        # Pièces et espaces
        if "pieces_espaces" in ops:
            rooms = DB.FilteredElementCollector(doc, vid) \
                       .OfCategory(DB.BuiltInCategory.OST_Rooms) \
                       .WhereElementIsNotElementType() \
                       .ToElements()
            for r in rooms:
                p = r.LookupParameter("Nom")
                if p and p.AsString() == "Pièce":
                    to_delete["pieces_espaces"].add(r.Id)

            spaces = DB.FilteredElementCollector(doc, vid) \
                        .OfCategory(DB.BuiltInCategory.OST_MEPSpaces) \
                        .WhereElementIsNotElementType() \
                        .ToElements()
            for s in spaces:
                p = s.LookupParameter("Nom")
                if p and p.AsString() == "Espace":
                    to_delete["pieces_espaces"].add(s.Id)

        # Zones .dwg-
        if "zones_pochages" in ops:
            regions = DB.FilteredElementCollector(doc, vid) \
                         .OfClass(DB.FilledRegion) \
                         .ToElements()
            for reg in regions:
                if reg.GetTypeId() in to_delete["zones_pochages_type_ids"]:
                    to_delete["zones_pochages"].add(reg.Id)

    # Transaction
    t = DB.Transaction(doc, "Nettoyage global")
    t.Start()

    # Suppression des éléments
    for key in (
        "dwg_imports",
        "dwg_liens",
        "lignes",
        "texts",
        "pieces_espaces",
        "zones_pochages"
    ):
        for eid in to_delete[key]:
            try:
                doc.Delete(eid)
            except Exception as ex:
                output.print_md(
                    "- ⚠️ Erreur suppression {0} ID `{1}` : {2}"
                    .format(key, eid.IntegerValue, ex)
                )

    # Suppression des types de zones
    if "zones_pochages" in ops:
        for tid in to_delete["zones_pochages_type_ids"]:
            try:
                doc.Delete(tid)
            except Exception as ex:
                output.print_md(
                    "- ⚠️ Erreur suppression type zone ID `{0}` : {1}"
                    .format(tid.IntegerValue, ex)
                )

    t.Commit()

    # Message de fin
    count = len(views)
    if count == 0:
        message = u"❌ Aucune vue nettoyée."
    elif count == 1:
        message = u"✅ 1 vue nettoyée."
    else:
        message = u"✅ {} vues nettoyées.".format(count)

    result_win = forms.WPFWindow(result_xaml)
    result_win.txtMessage.Text = message
    result_win.btnClose.Click += lambda s, e: result_win.Close()
    result_win.ShowDialog()


if __name__ == "__main__":
    main()
