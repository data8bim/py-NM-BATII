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


#__title__ = 'Contraintes\nde hauteur'
#__author__ = 'data8bim (d8b)'

# ─── Fenêtre non-modale via DispatcherFrame ───────────────────────────────────
#   - main() reste sur la pile d'appels → closures et handlers vivants
#   - DispatcherFrame traite TOUS les messages Win32 du thread (WPF + Revit)
#     → la sélection souris dans la vue Revit (bouton "Sélectionner" de la
#     portée "Pièces sélectionnées dans la vue active") fonctionne normalement.

import os

from pyrevit import revit, forms, script
from pyrevit import DB
from Autodesk.Revit.DB import Element
from Autodesk.Revit.DB.Architecture import Room as RoomClass
from Autodesk.Revit.UI.Selection import ISelectionFilter, ObjectType as PickObjectType
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from System.Windows import (
    Thickness, WindowState, GridLength, GridUnitType,
    HorizontalAlignment, VerticalAlignment
)
from System.Windows.Controls import CheckBox, TextBlock, Grid, Border, ColumnDefinition
from System.Windows.Input import Keyboard, Key as WpfKey
from System.Windows.Media import Brushes
import System.Windows.Threading as Threading

from dialogs.dialogs_styles_loader import load as _load_styles, show_alert
_load_styles()

doc   = revit.doc
uidoc = revit.uidoc
view  = doc.ActiveView

# Valeurs de contraintes par défaut, réappliquées à chaque ouverture du script
# (aucune persistance des dernières valeurs saisies : voir _on_defaults/main).
_DEFAULT_NB_NIVEAUX          = u'1'
_DEFAULT_DECALAGE_LIMITE     = u'0'
_DEFAULT_DECALAGE_INFERIEUR  = u'0'


class _RoomSelectionFilter(object, ISelectionFilter):
    """Restreint la sélection Revit aux seules pièces."""
    def AllowElement(self, element):
        return isinstance(element, RoomClass)
    def AllowReference(self, reference, point):
        return False


def _elem_name(e):
    """
    Contournement IronPython : Element.Name est implémenté en interface
    explicite sur certains types, ce qui fait échouer l'accès direct `e.Name`.
    """
    return Element.Name.__get__(e)


def _is_supported_view(v):
    """
    Le script ne peut être lancé que depuis une vue en plan (Plan d'étage,
    Plan de faux-plafond, Vue en plan...), à l'exclusion des gabarits de vue.
    Même principe que les vérifications natives de pyRevit
    (pyrevit.forms.check_modelview / check_viewtype) : un isinstance sur la
    classe DB.ViewPlan, qui couvre tous les types de plans (étage, plafond,
    aire, structure).
    """
    return isinstance(v, DB.ViewPlan) and not v.IsTemplate


# ─── Unités ────────────────────────────────────────────────────────────────────
def _length_unit(doc):
    """Unité d'affichage actuelle des longueurs du projet (Décalages)."""
    try:
        return doc.GetUnits().GetFormatOptions(DB.SpecTypeId.Length).GetUnitTypeId()
    except Exception:
        return DB.UnitTypeId.Millimeters


def _to_internal(value, unit_type_id):
    return DB.UnitUtils.ConvertToInternalUnits(value, unit_type_id)


# ─── Collecte ──────────────────────────────────────────────────────────────────
def _is_placed_room(room):
    try:
        return room.Location is not None
    except Exception:
        return False


def get_all_rooms():
    rooms = DB.FilteredElementCollector(doc)\
        .OfCategory(DB.BuiltInCategory.OST_Rooms)\
        .WhereElementIsNotElementType()\
        .ToElements()
    return [r for r in rooms if _is_placed_room(r)]


def get_view_rooms(active_view):
    try:
        rooms = DB.FilteredElementCollector(doc, active_view.Id)\
            .OfCategory(DB.BuiltInCategory.OST_Rooms)\
            .WhereElementIsNotElementType()\
            .ToElements()
    except Exception:
        rooms = []
    return [r for r in rooms if _is_placed_room(r)]


def get_all_levels_sorted():
    levels = list(DB.FilteredElementCollector(doc).OfClass(DB.Level).ToElements())
    levels.sort(key=lambda l: l.Elevation)
    return levels


def room_level_name(room):
    try:
        lvl = doc.GetElement(room.LevelId)
        return _elem_name(lvl) if lvl is not None else u''
    except Exception:
        return u''


def room_number(room):
    try:
        p = room.get_Parameter(DB.BuiltInParameter.ROOM_NUMBER)
        return p.AsString() if p else u''
    except Exception:
        return u''


def room_name(room):
    try:
        p = room.get_Parameter(DB.BuiltInParameter.ROOM_NAME)
        return p.AsString() if p else u''
    except Exception:
        return u''


# ─── Calcul du niveau "Limite supérieure" ─────────────────────────────────────
def compute_target_level(room, levels_sorted, n_above):
    """Retourne le niveau situé n_above position(s) au-dessus du niveau de la
    pièce (dans la liste des niveaux du projet triés par élévation), ou None
    si introuvable (pas assez de niveaux au-dessus)."""
    try:
        lvl_id = room.LevelId
    except Exception:
        return None
    idx = None
    for i, lvl in enumerate(levels_sorted):
        if lvl.Id == lvl_id:
            idx = i
            break
    if idx is None:
        return None
    target_idx = idx + n_above
    if target_idx < 0 or target_idx >= len(levels_sorted):
        return None
    return levels_sorted[target_idx]


def apply_height_constraints(rooms, n_above, limit_offset_internal, base_offset_internal):
    levels_sorted = get_all_levels_sorted()
    n_ok = 0
    n_skip = 0
    with revit.Transaction(u"Contraintes de hauteur des pièces"):
        for room in rooms:
            target_level = compute_target_level(room, levels_sorted, n_above)
            if target_level is None:
                n_skip += 1
                continue
            try:
                p_upper = room.get_Parameter(DB.BuiltInParameter.ROOM_UPPER_LEVEL)
                p_lim   = room.get_Parameter(DB.BuiltInParameter.ROOM_UPPER_OFFSET)
                p_base  = room.get_Parameter(DB.BuiltInParameter.ROOM_LOWER_OFFSET)
                if p_upper is None or p_upper.IsReadOnly:
                    n_skip += 1
                    continue
                p_upper.Set(target_level.Id)
                if p_lim is not None and not p_lim.IsReadOnly:
                    p_lim.Set(limit_offset_internal)
                if p_base is not None and not p_base.IsReadOnly:
                    p_base.Set(base_offset_internal)
                n_ok += 1
            except Exception:
                n_skip += 1
    return n_ok, n_skip


# ─── Dialogue : sélection des niveaux ─────────────────────────────────────────
def show_levels_dialog(levels_sorted, current_selected_ids):
    xaml = script.get_bundle_file('LevelsDialog.xaml')
    dlg = forms.WPFWindow(xaml)
    dlg.Title = u'Sélectionner les niveaux'

    selected_set = set(current_selected_ids)
    visible_cbs  = []
    last_idx     = [-1]

    def _sync_all():
        for cb, lvl in visible_cbs:
            lid = lvl.Id.IntegerValue
            if bool(cb.IsChecked): selected_set.add(lid)
            else:                  selected_set.discard(lid)

    def populate(filter_text=u''):
        _sync_all()
        dlg.levelListPanel.Children.Clear()
        del visible_cbs[:]
        last_idx[0] = -1
        for lvl in levels_sorted:
            name = _elem_name(lvl)
            if filter_text and filter_text.lower() not in name.lower():
                continue
            cb = CheckBox()
            cb.Content   = name
            cb.IsChecked = (lvl.Id.IntegerValue in selected_set)
            cb.Margin    = Thickness(2, 2, 2, 2)
            idx = len(visible_cbs)

            def on_click(s, e, i=idx, level_elem=lvl, checkbox=cb):
                ns  = bool(checkbox.IsChecked)
                lid = level_elem.Id.IntegerValue
                shift = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                         Keyboard.IsKeyDown(WpfKey.RightShift))
                if shift and last_idx[0] >= 0:
                    lo, hi = min(last_idx[0], i), max(last_idx[0], i)
                    for j in range(lo, hi + 1):
                        if j < len(visible_cbs):
                            cb_j, lvl_j = visible_cbs[j]
                            cb_j.IsChecked = ns
                            lid_j = lvl_j.Id.IntegerValue
                            if ns: selected_set.add(lid_j)
                            else:  selected_set.discard(lid_j)
                else:
                    if ns: selected_set.add(lid)
                    else:  selected_set.discard(lid)
                last_idx[0] = i

            cb.Click += on_click
            dlg.levelListPanel.Children.Add(cb)
            visible_cbs.append((cb, lvl))

    populate()

    def on_search(s, e): populate(s.Text)
    def on_all(s, e):
        for cb, lvl in visible_cbs:
            cb.IsChecked = True
            selected_set.add(lvl.Id.IntegerValue)
    def on_none(s, e):
        for cb, lvl in visible_cbs:
            cb.IsChecked = False
            selected_set.discard(lvl.Id.IntegerValue)
    def on_invert(s, e):
        for cb, lvl in visible_cbs:
            ns = not bool(cb.IsChecked)
            cb.IsChecked = ns
            lid = lvl.Id.IntegerValue
            if ns: selected_set.add(lid)
            else:  selected_set.discard(lid)
    def on_ok(s, e):
        _sync_all()
        setattr(dlg, 'DialogResult', True)

    dlg.searchBox.TextChanged += on_search
    dlg.btnSelectAll.Click    += on_all
    dlg.btnDeselectAll.Click  += on_none
    dlg.btnInvert.Click       += on_invert
    dlg.btnOk.Click           += on_ok
    dlg.btnCancel.Click       += lambda s, e: setattr(dlg, 'DialogResult', False)

    if dlg.show_dialog():
        return selected_set
    return None


# ─── Dialogue : sélection des pièces (tableau filtrable / triable) ────────────
def _make_room_row(data, selected_set, visible_rows, last_idx):
    b = Border()
    b.BorderThickness = Thickness(0, 0, 0, 1)
    b.BorderBrush = Brushes.Gainsboro
    b.Padding = Thickness(2, 3, 2, 3)

    g = Grid()
    widths = (30, None, 110, None)
    for w in widths:
        cd = ColumnDefinition()
        if w is None:
            cd.Width = GridLength(1, GridUnitType.Star)
        else:
            cd.Width = GridLength(w)
        g.ColumnDefinitions.Add(cd)

    cb = CheckBox()
    cb.IsChecked = (data['room'].Id.IntegerValue in selected_set)
    cb.VerticalAlignment = VerticalAlignment.Center
    cb.HorizontalAlignment = HorizontalAlignment.Center
    Grid.SetColumn(cb, 0)

    tb_niveau = TextBlock()
    tb_niveau.Text = data['niveau']
    tb_niveau.VerticalAlignment = VerticalAlignment.Center
    tb_niveau.Margin = Thickness(4, 0, 4, 0)
    Grid.SetColumn(tb_niveau, 1)

    tb_numero = TextBlock()
    tb_numero.Text = data['numero']
    tb_numero.VerticalAlignment = VerticalAlignment.Center
    tb_numero.Margin = Thickness(4, 0, 4, 0)
    Grid.SetColumn(tb_numero, 2)

    tb_nom = TextBlock()
    tb_nom.Text = data['nom']
    tb_nom.VerticalAlignment = VerticalAlignment.Center
    tb_nom.Margin = Thickness(4, 0, 4, 0)
    Grid.SetColumn(tb_nom, 3)

    g.Children.Add(cb)
    g.Children.Add(tb_niveau)
    g.Children.Add(tb_numero)
    g.Children.Add(tb_nom)
    b.Child = g

    idx = len(visible_rows)

    def on_click(s, e):
        ns  = bool(cb.IsChecked)
        rid = data['room'].Id.IntegerValue
        shift = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                 Keyboard.IsKeyDown(WpfKey.RightShift))
        if shift and last_idx[0] >= 0:
            lo, hi = min(last_idx[0], idx), max(last_idx[0], idx)
            for j in range(lo, hi + 1):
                if j < len(visible_rows):
                    cb_j, data_j = visible_rows[j]
                    cb_j.IsChecked = ns
                    rid_j = data_j['room'].Id.IntegerValue
                    if ns: selected_set.add(rid_j)
                    else:  selected_set.discard(rid_j)
        else:
            if ns: selected_set.add(rid)
            else:  selected_set.discard(rid)
        last_idx[0] = idx

    cb.Click += on_click
    visible_rows.append((cb, data))
    return b


def show_rooms_dialog(rooms, current_selected_ids):
    xaml = script.get_bundle_file('RoomsPickerDialog.xaml')
    dlg = forms.WPFWindow(xaml)
    dlg.Title = u'Sélectionner les pièces'

    rooms_data = [{
        'room':   r,
        'niveau': room_level_name(r),
        'numero': room_number(r),
        'nom':    room_name(r),
    } for r in rooms]

    selected_set = set(current_selected_ids)
    visible_rows = []
    last_idx     = [-1]
    _vs = {'f_niveau': u'', 'f_numero': u'', 'f_nom': u'', 'sort': None}

    def _sync_all():
        for cb, data in visible_rows:
            rid = data['room'].Id.IntegerValue
            if bool(cb.IsChecked): selected_set.add(rid)
            else:                  selected_set.discard(rid)

    def populate():
        _sync_all()
        dlg.roomListPanel.Children.Clear()
        del visible_rows[:]
        last_idx[0] = -1

        fn  = _vs['f_niveau'].lower()
        fnu = _vs['f_numero'].lower()
        fno = _vs['f_nom'].lower()
        visible_data = [
            d for d in rooms_data
            if (not fn  or fn  in d['niveau'].lower())
            and (not fnu or fnu in d['numero'].lower())
            and (not fno or fno in d['nom'].lower())
        ]
        s = _vs['sort']
        if   s == 'niveau_asc':  visible_data.sort(key=lambda d: d['niveau'].lower())
        elif s == 'niveau_desc': visible_data.sort(key=lambda d: d['niveau'].lower(), reverse=True)
        elif s == 'numero_asc':  visible_data.sort(key=lambda d: d['numero'].lower())
        elif s == 'numero_desc': visible_data.sort(key=lambda d: d['numero'].lower(), reverse=True)
        elif s == 'nom_asc':     visible_data.sort(key=lambda d: d['nom'].lower())
        elif s == 'nom_desc':    visible_data.sort(key=lambda d: d['nom'].lower(), reverse=True)

        for data in visible_data:
            dlg.roomListPanel.Children.Add(
                _make_room_row(data, selected_set, visible_rows, last_idx))

    def _update_sort_btns():
        s = _vs['sort']
        dlg.btnSortNiveau.Content = (u'A\u2192Z' if s == 'niveau_asc' else
                                     u'Z\u2192A' if s == 'niveau_desc' else u'\u21c5')
        dlg.btnSortNumero.Content = (u'A\u2192Z' if s == 'numero_asc' else
                                     u'Z\u2192A' if s == 'numero_desc' else u'\u21c5')
        dlg.btnSortNom.Content    = (u'A\u2192Z' if s == 'nom_asc' else
                                     u'Z\u2192A' if s == 'nom_desc' else u'\u21c5')

    populate()

    def on_search_niveau(s, e): _vs['f_niveau'] = s.Text or u''; populate()
    def on_search_numero(s, e): _vs['f_numero'] = s.Text or u''; populate()
    def on_search_nom(s, e):    _vs['f_nom']    = s.Text or u''; populate()

    def on_sort_niveau(s, e):
        cur = _vs['sort']
        if cur == 'niveau_asc': _vs['sort'] = 'niveau_desc'
        elif cur == 'niveau_desc': _vs['sort'] = None
        else: _vs['sort'] = 'niveau_asc'
        _update_sort_btns(); populate()

    def on_sort_numero(s, e):
        cur = _vs['sort']
        if cur == 'numero_asc': _vs['sort'] = 'numero_desc'
        elif cur == 'numero_desc': _vs['sort'] = None
        else: _vs['sort'] = 'numero_asc'
        _update_sort_btns(); populate()

    def on_sort_nom(s, e):
        cur = _vs['sort']
        if cur == 'nom_asc': _vs['sort'] = 'nom_desc'
        elif cur == 'nom_desc': _vs['sort'] = None
        else: _vs['sort'] = 'nom_asc'
        _update_sort_btns(); populate()

    def on_all(s, e):
        for cb, data in visible_rows:
            cb.IsChecked = True
            selected_set.add(data['room'].Id.IntegerValue)

    def on_none(s, e):
        for cb, data in visible_rows:
            cb.IsChecked = False
            selected_set.discard(data['room'].Id.IntegerValue)

    def on_invert(s, e):
        for cb, data in visible_rows:
            ns  = not bool(cb.IsChecked)
            cb.IsChecked = ns
            rid = data['room'].Id.IntegerValue
            if ns: selected_set.add(rid)
            else:  selected_set.discard(rid)

    def on_ok(s, e):
        _sync_all()
        setattr(dlg, 'DialogResult', True)

    dlg.searchNiveau.TextChanged += on_search_niveau
    dlg.searchNumero.TextChanged += on_search_numero
    dlg.searchNom.TextChanged    += on_search_nom
    dlg.btnSortNiveau.Click      += on_sort_niveau
    dlg.btnSortNumero.Click      += on_sort_numero
    dlg.btnSortNom.Click         += on_sort_nom
    dlg.btnSelectAll.Click       += on_all
    dlg.btnDeselectAll.Click     += on_none
    dlg.btnInvert.Click          += on_invert
    dlg.btnOk.Click              += on_ok
    dlg.btnCancel.Click          += lambda s, e: setattr(dlg, 'DialogResult', False)

    if dlg.show_dialog():
        return selected_set
    return None


# ─── Interface principale ──────────────────────────────────────────────────────
def main():
    if not _is_supported_view(view):
        show_alert(
            u"Contraintes de hauteur",
            u"Ce script ne peut être lancé que depuis une vue en plan "
            u"(Plan d'étage, Plan de faux-plafond, Vue en plan...)."
        )
        return

    rooms_all = get_all_rooms()
    if not rooms_all:
        show_alert(u"Contraintes de hauteur", u"Aucune pièce placée dans ce projet.")
        return

    levels_sorted = get_all_levels_sorted()
    if len(levels_sorted) < 2:
        show_alert(
            u"Contraintes de hauteur",
            u"Le projet ne comporte pas assez de niveaux pour définir une limite supérieure."
        )
        return

    xaml_path = os.path.join(os.path.dirname(__file__), 'WPFWindow.xaml')
    wpf = forms.WPFWindow(xaml_path)

    wpf.txtNbNiveaux.Text         = _DEFAULT_NB_NIVEAUX
    wpf.txtDecalageLimite.Text    = _DEFAULT_DECALAGE_LIMITE
    wpf.txtDecalageInferieur.Text = _DEFAULT_DECALAGE_INFERIEUR

    state = {
        'niveaux_ids':          set(),
        'selection_rooms':      [],
        'vue_selection_rooms':  [],
    }

    def _on_nb_niveaux_preview(s, e):
        e.Handled = not e.Text.isdigit()

    def _on_defaults(s, e):
        wpf.txtNbNiveaux.Text         = _DEFAULT_NB_NIVEAUX
        wpf.txtDecalageLimite.Text    = _DEFAULT_DECALAGE_LIMITE
        wpf.txtDecalageInferieur.Text = _DEFAULT_DECALAGE_INFERIEUR

    def _on_niveaux(s, e):
        result = show_levels_dialog(levels_sorted, state['niveaux_ids'])
        if result is not None:
            state['niveaux_ids'] = result
            wpf.txtNiveauxCount.Text = u"({} niveau(x) sélectionné(s))".format(len(result))
            wpf.rbNiveaux.IsChecked = True

    def _on_selection(s, e):
        current_ids = set(r.Id.IntegerValue for r in state['selection_rooms'])
        result = show_rooms_dialog(rooms_all, current_ids)
        if result is not None:
            state['selection_rooms'] = [r for r in rooms_all if r.Id.IntegerValue in result]
            wpf.txtSelectionCount.Text = u"({} pièce(s) sélectionnée(s))".format(len(state['selection_rooms']))
            wpf.rbSelection.IsChecked = True

    def _on_vue_selection(s, e):
        wpf.WindowState = WindowState.Minimized
        try:
            refs = uidoc.Selection.PickObjects(
                PickObjectType.Element, _RoomSelectionFilter(),
                u"Sélectionnez les pièces puis cliquez sur Terminer"
            )
            picked = [doc.GetElement(r.ElementId) for r in refs]
            state['vue_selection_rooms'] = [r for r in picked if r is not None and _is_placed_room(r)]
        except Exception:
            pass
        wpf.WindowState = WindowState.Normal
        wpf.Activate()
        wpf.txtVueSelectionCount.Text = u"({} pièce(s) sélectionnée(s))".format(len(state['vue_selection_rooms']))
        wpf.rbVueSelection.IsChecked = True

    def _on_apply(s, e):
        n_text = (wpf.txtNbNiveaux.Text or u'').strip()
        if not n_text or not n_text.isdigit() or int(n_text) < 1:
            show_alert(
                u"Contraintes de hauteur",
                u"« Nombre de niveaux au-dessus » doit être un nombre entier positif (1, 2, 3...)."
            )
            return
        n_above = int(n_text)

        try:
            lim_text = (wpf.txtDecalageLimite.Text or u'0').strip().replace(u',', u'.')
            limit_offset = float(lim_text) if lim_text else 0.0
        except ValueError:
            show_alert(u"Contraintes de hauteur", u"« Décalage limite » doit être une valeur numérique.")
            return

        try:
            base_text = (wpf.txtDecalageInferieur.Text or u'0').strip().replace(u',', u'.')
            base_offset = float(base_text) if base_text else 0.0
        except ValueError:
            show_alert(u"Contraintes de hauteur", u"« Décalage inférieur » doit être une valeur numérique.")
            return

        if wpf.rbToutes.IsChecked:
            rooms = rooms_all
        elif wpf.rbNiveaux.IsChecked:
            if not state['niveaux_ids']:
                show_alert(u"Contraintes de hauteur", u"Sélectionnez au moins un niveau.")
                return
            rooms = [r for r in rooms_all if r.LevelId.IntegerValue in state['niveaux_ids']]
        elif wpf.rbSelection.IsChecked:
            if not state['selection_rooms']:
                show_alert(u"Contraintes de hauteur", u"Sélectionnez au moins une pièce.")
                return
            rooms = state['selection_rooms']
        elif wpf.rbVueActive.IsChecked:
            rooms = get_view_rooms(view)
        else:
            if not state['vue_selection_rooms']:
                show_alert(
                    u"Contraintes de hauteur",
                    u"Aucune pièce sélectionnée. Cliquez sur « Sélectionner »."
                )
                return
            rooms = state['vue_selection_rooms']

        if not rooms:
            show_alert(u"Contraintes de hauteur", u"Aucune pièce à traiter selon les critères choisis.")
            return

        unit = _length_unit(doc)
        limit_offset_i = _to_internal(limit_offset, unit)
        base_offset_i  = _to_internal(base_offset, unit)

        n_ok, n_skip = apply_height_constraints(rooms, n_above, limit_offset_i, base_offset_i)

        msg = u"{} pièce(s) mise(s) à jour.".format(n_ok)
        if n_skip:
            msg += u"\n{} pièce(s) ignorée(s) (pas de niveau disponible {} niveau(x) au-dessus).".format(
                n_skip, n_above)
        show_alert(u"Contraintes de hauteur", msg)
        wpf.Close()

    def _on_close(s, e):
        wpf.Close()

    wpf.txtNbNiveaux.PreviewTextInput += _on_nb_niveaux_preview
    wpf.btnDefaults.Click     += _on_defaults
    wpf.btnNiveaux.Click      += _on_niveaux
    wpf.btnSelection.Click    += _on_selection
    wpf.btnVueSelection.Click += _on_vue_selection
    wpf.btnApply.Click        += _on_apply
    wpf.btnClose.Click        += _on_close

    frame = Threading.DispatcherFrame()
    wpf.Closed += lambda s, e: setattr(frame, 'Continue', False)
    wpf.Show()
    Threading.Dispatcher.PushFrame(frame)


# ── ExternalEvent : main() s'execute sur le thread Revit ──────────────────────
#
# Pourquoi : appeler PickObjects depuis un ExternalEvent fait afficher par Revit
# le panneau ruban « Autoriser selection multiple » (gros boutons Terminer /
# Annuler / Multiple) au lieu de la discrete barre d'options obtenue en appel
# direct. UI de selection uniformisee pour toute l'extension.
#
# Difficulte : apres le retour de Execute(), IronPython/pyRevit vide les globals
# du module, ce qui casserait tout le code de ce fichier. On en sauvegarde une
# COPIE au demarrage et on la restaure en tete de Execute() : le code existant
# reste utilisable tel quel, sans etre reecrit.

class _ActionHandler(IExternalEventHandler):

    def __init__(self):
        self._fn      = [None]           # mutable — pas de nonlocal en IPy 2.7
        self._globals = dict(globals())  # snapshot ICI : globals encore vivants

    def planifier(self, fn):
        self._fn[0] = fn

    def Execute(self, uiapp):
        try:
            globals().update(self._globals)
        except Exception:
            pass
        fn = self._fn[0]
        self._fn[0] = None
        if fn:
            try:
                fn()
            except Exception:
                # Ne jamais avaler en silence : remonter la cause.
                import traceback
                try:
                    import System.Windows as _SW
                    _SW.MessageBox.Show(traceback.format_exc(),
                                        u'NM-BATII — Erreur')
                except Exception:
                    pass

    def GetName(self):
        return u"NM-BATII — Contraintes de hauteur des pieces"


if __name__ == '__main__':
    # Le handler est instancie APRES toutes les definitions : c'est a cet
    # instant qu'est pris le snapshot des globals restaure par Execute().
    _action_handler = _ActionHandler()
    _ext_event      = ExternalEvent.Create(_action_handler)
    _action_handler.planifier(main)
    _ext_event.Raise()
