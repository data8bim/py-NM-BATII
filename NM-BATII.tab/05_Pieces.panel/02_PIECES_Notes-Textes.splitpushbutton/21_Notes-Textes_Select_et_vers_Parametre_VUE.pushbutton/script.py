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


#__title__ = ""Texte → Pièces\n[MASSE]"
#__doc__ = """Transfère en masse les valeurs des notes textuelles
#Description : Transfère en masse les valeurs des notes textuelles d’une vue vers un paramètre cible de chaque pièce.

#Version : 3.3 — 2026-04-17
#Auteur : data8bim (d8b)
#"""


# ─── LARGEURS PAR DÉFAUT ──────────────────────────────────────────────────────
# Col ✓ fixe (30px). Cols Texte/Type/Couleur proportionnelles (2:1:fixed) par défaut.
# Mettre un nombre > 0 pour forcer une largeur initiale en pixels.
COL_W_TEXT = 0   # 0 = proportions XAML (2*)
COL_W_TYPE = 0   # 0 = proportions XAML (*)

import os, codecs, json, clr

clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Windows.Forms')

import System.Windows.Forms as WinForms

from pyrevit import forms
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInParameter, BuiltInCategory,
    TextNote, ElementId, StorageType, Transaction, XYZ, ViewPlan
)
from Autodesk.Revit.DB.Architecture import Room
from Autodesk.Revit.DB.Mechanical  import Space
from System.Collections.Generic import List
import System
from System.Windows import (
    Thickness, HorizontalAlignment, VerticalAlignment,
    GridLength, GridUnitType, TextTrimming, FontWeights,
    Window, ResizeMode, WindowStartupLocation
)
from System.Windows.Controls import (
    Grid, CheckBox, TextBlock, TextBox, Border, Button,
    ColumnDefinition, RowDefinition, StackPanel, ScrollViewer,
    ScrollBarVisibility, RadioButton
)
from System.Windows.Input import Keyboard, Key as WpfKey
from System.Windows.Media import Brushes, SolidColorBrush, Color

try:
    import dialogs_styles_loader  # noqa: F401
except ImportError:
    pass

_ROW_ALT  = SolidColorBrush(Color.FromRgb(244, 247, 252))
_ROW_NORM = Brushes.White
_SEP_CLR  = SolidColorBrush(Color.FromRgb(142, 155, 170))
_LINE_CLR = SolidColorBrush(Color.FromRgb(220, 226, 232))

doc   = __revit__.ActiveUIDocument.Document   # noqa: F821
uidoc = __revit__.ActiveUIDocument            # noqa: F821

_MARKER      = u'\u2714 '   # ✔ préfixe : note recopiée avec succès
_MARKER_FAIL = u'\u2718 '   # ✘ préfixe : note non recopiée (cible introuvable ou erreur)


# ─── LOG ─────────────────────────────────────────────────────────────────────
def _load_main_config():
    cur = os.path.dirname(os.path.abspath(__file__))
    while not cur.lower().endswith('.extension'):
        parent = os.path.dirname(cur)
        if parent == cur: return {}
        cur = parent
    p = os.path.join(cur, 'config.json')
    if not os.path.isfile(p): return {}
    try:
        with codecs.open(p, 'r', 'utf-8') as f: return json.load(f)
    except Exception: return {}

_MAIN_CFG     = _load_main_config()
_LOGS_ENABLED = _MAIN_CFG.get('activer_logs_scripts', False)

def _log(msg):
    if _LOGS_ENABLED:
        print(u'[Notes Textuelles] ' + msg)


# ─── Utility : fermer toutes les fenêtres WPF ouvertes ───────────────────────
def close_all_windows():
    """Ferme toutes les fenêtres WPF ouvertes du script."""
    try:
        import System.Windows as SW
        # Copier la liste car la collection peut changer pendant l'itération
        windows = list(SW.Application.Current.Windows)
        for w in windows:
            try:
                # Ne pas lever d'exception si la fenêtre est déjà en cours de fermeture
                w.Close()
            except Exception:
                pass
    except Exception:
        pass


# ─── Collecte ─────────────────────────────────────────────────────────────────
class NoteInfo(object):
    def __init__(self, elem_id, type_name, text, color_rgb, color_str):
        self.elem_id    = elem_id
        self.type_name  = type_name
        self.text       = text
        self.color_rgb  = color_rgb
        self.color_str  = color_str
        self.checked    = False
        self.cb         = None
        self._border    = None
        self._row_cols  = None
        self._bg_border = None


def _get_note_color(doc, tn):
    """
    Retourne (R, G, B) de la note textuelle.
    Priorité :
      1. Substitution graphique dans la vue (ProjectionLineColor)
      2. Couleur du type de texte (BuiltInParameter.LINE_COLOR)
      3. Noir par défaut (0, 0, 0)
    LINE_COLOR est un entier encodé : R + G×256 + B×65536
    """
    try:
        view = doc.GetElement(tn.OwnerViewId)
        if view is not None:
            ovr = view.GetElementOverrides(tn.Id)
            c = ovr.ProjectionLineColor
            if c is not None and c.IsValid:
                return (int(c.Red), int(c.Green), int(c.Blue))
    except Exception:
        pass
    try:
        tn_type = doc.GetElement(tn.GetTypeId())
        if tn_type is not None:
            p = tn_type.get_Parameter(BuiltInParameter.LINE_COLOR)
            if p is not None and p.HasValue:
                ci = p.AsInteger()
                return (ci & 0xFF, (ci >> 8) & 0xFF, (ci >> 16) & 0xFF)
    except Exception:
        pass
    return (0, 0, 0)


def collect_text_notes(doc):
    """
    Collecte uniquement les notes textuelles de la vue active.
    Filtre par OwnerViewId = vue active → pas de mélange entre étages.
    """
    active_view_id = doc.ActiveView.Id
    notes = []
    for tn in FilteredElementCollector(doc, active_view_id).OfClass(TextNote):
        try:
            tn_type = doc.GetElement(tn.GetTypeId())
            type_name = u'(sans type)'
            if tn_type:
                p = tn_type.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
                if p: type_name = (p.AsString() or u'(sans type)').strip()
            text = (tn.Text or u'').replace(u'\r\n', u' ').replace(u'\n', u' ').strip()
            if not text: text = u'(vide)'
            rgb = _get_note_color(doc, tn)
            color_str = u'#{:02X}{:02X}{:02X}'.format(rgb[0], rgb[1], rgb[2])
            notes.append(NoteInfo(tn.Id, type_name, text, rgb, color_str))
        except Exception as ex:
            _log(u'Collecte : ' + str(ex))
    notes.sort(key=lambda n: (n.type_name.lower(), n.text.lower()))
    return notes



# ─── Résultat ─────────────────────────────────────────────────────────────────
def _nm_dialog(title, msg, btn_label=u'OK', owner=None, close_all=False):
    """
    Boîte de dialogue au style NM (ResultWindow.xaml).
    Utilisée pour tous les messages du script — pas de forms.alert.
    close_all : si True, ferme toutes les fenêtres WPF du script lorsque l'utilisateur clique sur le bouton.
    """
    xaml = os.path.join(os.path.dirname(__file__), 'ResultWindow.xaml')
    try:
        w = forms.WPFWindow(xaml)
        w.Title           = title
        w.txtMessage.Text = msg
        w.btnClose.Content = btn_label

        def _on_close(s, e):
            try:
                setattr(w, 'DialogResult', True)
            except Exception:
                pass
            # Fermer toutes les fenêtres WPF uniquement si demandé explicitement
            if close_all:
                try:
                    close_all_windows()
                except Exception:
                    pass

        w.btnClose.Click  += _on_close
        if owner:
            try: w.Owner = owner
            except Exception: pass
        w.show_dialog()
    except Exception:
        # Dernier recours si le XAML ne charge pas
        import System.Windows.MessageBox as MB
        MB.Show(msg, title)
        if close_all:
            try:
                close_all_windows()
            except Exception:
                pass


def _nm_confirm(title, msg, owner=None):
    """
    Boîte de confirmation Oui / Non au style NM.
    Retourne True si l'utilisateur clique Oui.
    """
    xaml = os.path.join(os.path.dirname(__file__), 'ResultWindow.xaml')
    result = [False]
    try:
        w = forms.WPFWindow(xaml)
        w.Title           = title
        w.txtMessage.Text = msg

        # Remplacer le bouton "Fermer" par deux boutons Oui/Non
        from System.Windows.Controls import StackPanel as SP, Button as BTN
        from System.Windows import HorizontalAlignment as HA, Thickness as TH
        from System.Windows import GridLength as GL, GridUnitType as GU
        from System.Windows.Controls import ColumnDefinition as CD, Grid as GD
        btn_grid = GD()
        c1 = CD(); c1.Width = GL(1, GU.Star)
        c2 = CD(); c2.Width = GL(8)
        c3 = CD(); c3.Width = GL(1, GU.Star)
        btn_grid.ColumnDefinitions.Add(c1)
        btn_grid.ColumnDefinitions.Add(c2)
        btn_grid.ColumnDefinitions.Add(c3)

        btn_yes = BTN(); btn_yes.Content = u'Oui'; btn_yes.Height = 30
        GD.SetColumn(btn_yes, 0)
        btn_no  = BTN(); btn_no.Content  = u'Non'; btn_no.Height  = 30
        GD.SetColumn(btn_no, 2)

        def on_yes(s, e): result[0] = True; setattr(w, 'DialogResult', True)
        def on_no(s, e):  result[0] = False; setattr(w, 'DialogResult', False)
        btn_yes.Click += on_yes; btn_no.Click += on_no
        btn_grid.Children.Add(btn_yes); btn_grid.Children.Add(btn_no)

        # Remplacer btnClose par btn_grid dans le parent Grid
        # (btnClose est dans la grille Row=2, col 0..2)
        w.btnClose.Visibility = System.Windows.Visibility.Collapsed
        parent_grid = w.btnClose.Parent
        GD.SetRow(btn_grid, 2); GD.SetColumnSpan(btn_grid, 3)
        parent_grid.Children.Add(btn_grid)

        if owner:
            try: w.Owner = owner
            except Exception: pass
        w.show_dialog()
    except Exception as ex:
        _log(u'_nm_confirm fallback : ' + str(ex))
        import System.Windows.MessageBox as MB
        import System.Windows.MessageBoxButton as MBB
        import System.Windows.MessageBoxResult as MBR
        r = MB.Show(msg, title, MBB.YesNo)
        result[0] = (r == MBR.Yes)
    return result[0]


def show_result_window(msg):
    _nm_dialog(u'Notes Textuelles', msg, u'Fermer')


# ─── Popup filtre multi-sélection (Shift+clic) ───────────────────────────────
def show_filter_popup(title, all_values, selected_set, owner):
    # Valeurs uniques, triées, sans doublons (strip déjà fait à la collecte)
    sorted_vals = sorted(set(all_values), key=lambda v: v.lower())

    dlg = Window()
    dlg.Title = title; dlg.Width = 460; dlg.Height = 500
    dlg.MinWidth = 300; dlg.MinHeight = 280
    dlg.ResizeMode = ResizeMode.CanResize
    dlg.WindowStartupLocation = WindowStartupLocation.CenterOwner
    dlg.Owner = owner

    root = Grid(); root.Margin = Thickness(10)
    for h in ['Auto','Auto','8','*','8','Auto','8','Auto']:
        rd = RowDefinition()
        if h == '*':      rd.Height = GridLength(1, GridUnitType.Star)
        elif h == 'Auto': rd.Height = GridLength(0, GridUnitType.Auto)
        else:             rd.Height = GridLength(int(h))
        root.RowDefinitions.Add(rd)

    lbl = TextBlock(); lbl.Text = u'Rechercher :'
    lbl.Margin = Thickness(0,0,0,3); Grid.SetRow(lbl, 0)

    sb = TextBox(); sb.Height = 26
    sb.VerticalContentAlignment = VerticalAlignment.Center
    Grid.SetRow(sb, 1)

    lb = Border(); lb.BorderThickness = Thickness(1); lb.BorderBrush = Brushes.LightGray
    Grid.SetRow(lb, 3)
    sv = ScrollViewer(); sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    lp = StackPanel(); lp.Margin = Thickness(6,4,6,4)
    sv.Content = lp; lb.Child = sv

    visible_cbs = []; last_idx = [-1]

    def populate(ft=u''):
        lp.Children.Clear(); del visible_cbs[:]; last_idx[0] = -1
        f = ft.lower().strip()
        for val in sorted_vals:
            if f and f not in val.lower(): continue
            cb = CheckBox()
            cb.Content   = val if len(val) <= 90 else val[:87] + u'...'
            cb.IsChecked = (val in selected_set)
            cb.Margin    = Thickness(2,1,2,1); cb.ToolTip = val
            idx = len(visible_cbs)
            def _mk(i, v, checkbox):
                def on_click(s, e):
                    ns = bool(checkbox.IsChecked)
                    shift = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                             Keyboard.IsKeyDown(WpfKey.RightShift))
                    if shift and last_idx[0] >= 0:
                        lo, hi = min(last_idx[0], i), max(last_idx[0], i)
                        for j in range(lo, hi+1):
                            if j < len(visible_cbs):
                                cj, vj = visible_cbs[j]; cj.IsChecked = ns
                                if ns: selected_set.add(vj)
                                else:  selected_set.discard(vj)
                    else:
                        if ns: selected_set.add(v)
                        else:  selected_set.discard(v)
                    last_idx[0] = i
                return on_click
            cb.Click += _mk(idx, val, cb)
            lp.Children.Add(cb); visible_cbs.append((cb, val))

    populate()
    sb.TextChanged += lambda s, e: populate(s.Text)

    bg = Grid()
    for w in [GridLength(1,GridUnitType.Star), GridLength(6), GridLength(1,GridUnitType.Star)]:
        cd = ColumnDefinition(); cd.Width = w; bg.ColumnDefinitions.Add(cd)
    Grid.SetRow(bg, 5)
    ba = Button(); ba.Content = u'Tout cocher'; ba.Height = 26; Grid.SetColumn(ba, 0)
    ba.Click += lambda s, e: [(setattr(c,'IsChecked',True), selected_set.add(v)) for c,v in visible_cbs]
    bn = Button(); bn.Content = u'Tout d\xe9cocher'; bn.Height = 26; Grid.SetColumn(bn, 2)
    bn.Click += lambda s, e: [(setattr(c,'IsChecked',False), selected_set.discard(v)) for c,v in visible_cbs]
    bg.Children.Add(ba); bg.Children.Add(bn)

    bo = Button(); bo.Content = u'OK'; bo.Height = 30; bo.FontWeight = FontWeights.SemiBold
    Grid.SetRow(bo, 7)
    bo.Click += lambda s, e: setattr(dlg, 'DialogResult', True)

    for child in [lbl, sb, lb, bg, bo]: root.Children.Add(child)
    dlg.Content = root
    return dlg.ShowDialog()


# ─── Popup filtre état cases à cocher ────────────────────────────────────────
def show_check_filter_popup(current_state, owner):
    dlg = Window()
    dlg.Title = u'Filtrer par \xe9tat'; dlg.Width = 300; dlg.Height = 185
    dlg.ResizeMode = ResizeMode.NoResize
    dlg.WindowStartupLocation = WindowStartupLocation.CenterOwner
    dlg.Owner = owner
    root = StackPanel(); root.Margin = Thickness(16)
    result = [current_state]
    options = [('all', u'Tous'), ('checked', u'Coch\xe9s seulement'),
               ('unchecked', u'Non coch\xe9s seulement')]
    rbs = []
    for val, lbl in options:
        rb = RadioButton(); rb.Content = lbl; rb.IsChecked = (val == current_state)
        rb.Margin = Thickness(0,4,0,4); rb.GroupName = u'cf'; root.Children.Add(rb)
        rbs.append((rb, val))
    bo = Button(); bo.Content = u'OK'; bo.Height = 28; bo.Margin = Thickness(0,12,0,0)
    bo.FontWeight = FontWeights.SemiBold
    def on_ok(s, e):
        for rb, val in rbs:
            if bool(rb.IsChecked): result[0] = val; break
        setattr(dlg, 'DialogResult', True)
    bo.Click += on_ok
    root.Children.Add(bo); dlg.Content = root; dlg.ShowDialog()
    return result[0]


# ─── Pré-construction d'une ligne (appelé UNE SEULE FOIS par note) ───────────
def _build_note_row(note, init_widths):
    """
    Construit le Border+Grid d'une ligne une seule fois.
    init_widths = [w0, w1, w2, w3, w4, w5, w6] en pixels
    (même structure 7 colonnes que le headerGrid).
    Les ColumnDefinitions sont stockées dans note._row_cols pour la sync.
    """
    outer = Border()
    outer.Padding         = Thickness(0)
    outer.BorderThickness = Thickness(0,0,0,1)
    outer.BorderBrush     = _LINE_CLR
    note._border = outer

    bg = Border(); bg.Padding = Thickness(0,3,0,3)
    outer.Child = bg; note._bg_border = bg

    g = Grid()
    row_cols = []
    for w in init_widths:
        cd = ColumnDefinition()
        cd.Width = GridLength(w) if w > 0 else GridLength(1, GridUnitType.Star)
        g.ColumnDefinitions.Add(cd)
        row_cols.append(cd)
    note._row_cols = row_cols
    bg.Child = g

    # Col 0 : checkbox
    cb = CheckBox()
    cb.IsChecked = note.checked
    cb.VerticalAlignment = VerticalAlignment.Center
    cb.HorizontalAlignment = HorizontalAlignment.Center
    Grid.SetColumn(cb, 0); g.Children.Add(cb)
    note.cb = cb

    # Col 1 : séparateur fixe
    sep1 = Border(); sep1.Background = _SEP_CLR
    sep1.Width = 1; sep1.HorizontalAlignment = HorizontalAlignment.Center
    Grid.SetColumn(sep1, 1); g.Children.Add(sep1)

    # Col 2 : texte
    t2 = TextBlock(); t2.Text = note.text
    t2.VerticalAlignment = VerticalAlignment.Center
    t2.Margin = Thickness(6,0,4,0)
    t2.TextTrimming = TextTrimming.CharacterEllipsis; t2.ToolTip = note.text
    Grid.SetColumn(t2, 2); g.Children.Add(t2)

    # Col 3 : séparateur
    sep3 = Border(); sep3.Background = _SEP_CLR
    sep3.Width = 1; sep3.HorizontalAlignment = HorizontalAlignment.Center
    Grid.SetColumn(sep3, 3); g.Children.Add(sep3)

    # Col 4 : type
    t4 = TextBlock(); t4.Text = note.type_name
    t4.VerticalAlignment = VerticalAlignment.Center
    t4.Margin = Thickness(6,0,4,0); t4.Foreground = Brushes.DarkSlateBlue
    t4.FontWeight = FontWeights.SemiBold
    t4.TextTrimming = TextTrimming.CharacterEllipsis; t4.ToolTip = note.type_name
    Grid.SetColumn(t4, 4); g.Children.Add(t4)

    # Col 5 : séparateur
    sep5 = Border(); sep5.Background = _SEP_CLR
    sep5.Width = 1; sep5.HorizontalAlignment = HorizontalAlignment.Center
    Grid.SetColumn(sep5, 5); g.Children.Add(sep5)

    # Col 6 : couleur (pastille colorée + code hex)
    from System.Windows.Media import Color as WpfColor, SolidColorBrush as SCB
    r, gv, b = note.color_rgb
    note_brush = SCB(WpfColor.FromRgb(r, gv, b))
    sp_color = StackPanel()
    sp_color.Orientation         = System.Windows.Controls.Orientation.Horizontal
    sp_color.VerticalAlignment   = VerticalAlignment.Center
    sp_color.HorizontalAlignment = HorizontalAlignment.Left
    sp_color.Margin              = Thickness(6,0,4,0)

    swatch = Border()
    swatch.Width               = 14; swatch.Height = 14
    swatch.Background          = note_brush
    swatch.BorderBrush         = Brushes.Gray
    swatch.BorderThickness     = Thickness(1)
    swatch.CornerRadius        = System.Windows.CornerRadius(2)
    swatch.Margin              = Thickness(0,0,4,0)
    swatch.VerticalAlignment   = VerticalAlignment.Center

    t6_color = TextBlock()
    t6_color.Text            = note.color_str
    t6_color.VerticalAlignment = VerticalAlignment.Center
    t6_color.FontSize        = 10
    t6_color.Foreground      = Brushes.DimGray
    t6_color.ToolTip         = u'R:{} G:{} B:{}'.format(r, gv, b)

    sp_color.Children.Add(swatch)
    sp_color.Children.Add(t6_color)
    Grid.SetColumn(sp_color, 6); g.Children.Add(sp_color)

    return outer


# ─── Sauvegarde / Chargement de la configuration de sélection ────────────────
#
# Format JSON :
# {
#   "version": 1,
#   "selection": [
#     {"elem_id": 12345, "text": "NIV 0", "type_name": "3mm"},
#     ...
#   ]
# }
#
# La correspondance au chargement se fait d'abord par elem_id (fiable dans le
# même projet), puis par (text + type_name) si l'elem_id n'existe plus
# (projet re-ouvert, notes recréées).

def save_selection_config(all_notes):
    """Enregistre les notes cochées dans un fichier JSON."""
    checked = [n for n in all_notes if n.checked]
    if not checked:
        _nm_dialog(u'Aucune s\xe9lection',
                   u'Aucune note coch\xe9e \xe0 enregistrer.\n'
                   u'Cochez des notes avant de sauvegarder.')
        return

    dlg = WinForms.SaveFileDialog()
    dlg.Title      = u'Enregistrer la configuration de s\xe9lection'
    dlg.Filter     = u'Config s\xe9lection notes (*.NM-Note-Txt-Sel)|*.NM-Note-Txt-Sel|Tous (*.*)|*.*'
    dlg.DefaultExt = 'NM-Note-Txt-Sel'
    dlg.FileName   = 'selection_notes_textuelles.NM-Note-Txt-Sel'
    if dlg.ShowDialog() != WinForms.DialogResult.OK:
        return

    data = {
        'version':   1,
        'selection': [
            {'elem_id': n.elem_id.IntegerValue,
             'text': n.text, 'type_name': n.type_name}
            for n in checked
        ]
    }
    try:
        with codecs.open(dlg.FileName, 'w', 'utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        _log(u'Config sauvegardee : {} notes'.format(len(checked)))
        _nm_dialog(u'Configuration enregistr\xe9e',
                   u'{} note(s) coch\xe9e(s) enregistr\xe9e(s).\n\n{}'.format(
                       len(checked), dlg.FileName))
    except Exception as ex:
        _nm_dialog(u'Erreur', u'Erreur lors de la sauvegarde :\n' + str(ex))


def load_selection_config(all_notes, apply_view_fn, update_counter_fn):
    """
    Charge une configuration JSON et coche les notes correspondantes.
    Correspondance : d'abord par elem_id, puis (text + type_name) en fallback.
    """
    dlg = WinForms.OpenFileDialog()
    dlg.Title      = u'Charger une configuration de s\xe9lection'
    dlg.Filter     = u'Config s\xe9lection notes (*.NM-Note-Txt-Sel)|*.NM-Note-Txt-Sel|Tous (*.*)|*.*'
    dlg.DefaultExt = 'NM-Note-Txt-Sel'
    if dlg.ShowDialog() != WinForms.DialogResult.OK:
        return None

    try:
        with codecs.open(dlg.FileName, 'r', 'utf-8') as f:
            data = json.load(f)
    except Exception as ex:
        _nm_dialog(u'Erreur de lecture', u'Impossible de lire le fichier :\n' + str(ex))
        return None

    saved = data.get('selection', [])
    if not saved:
        _nm_dialog(u'Fichier vide', u'Le fichier ne contient aucune s\xe9lection.')
        return None

    by_id       = {n.elem_id.IntegerValue: n for n in all_notes}
    by_texttype = {}
    for n in all_notes:
        key = (n.text.strip().lower(), n.type_name.strip().lower())
        by_texttype.setdefault(key, []).append(n)

    for n in all_notes:
        n.checked = False
        if n.cb is not None: n.cb.IsChecked = False

    n_found = 0
    for entry in saved:
        eid  = entry.get('elem_id')
        txt  = (entry.get('text', u'') or u'').strip().lower()
        ttyp = (entry.get('type_name', u'') or u'').strip().lower()
        matched = None
        if eid is not None and eid in by_id:
            matched = by_id[eid]
        elif (txt, ttyp) in by_texttype:
            matched = by_texttype[(txt, ttyp)][0]
        if matched is not None and not matched.checked:
            matched.checked = True
            if matched.cb is not None: matched.cb.IsChecked = True
            n_found += 1

    _log(u'Config chargee : {}/{} notes'.format(n_found, len(saved)))
    apply_view_fn()
    update_counter_fn()

    n_missed = len(saved) - n_found
    msg = u'{} note(s) coch\xe9e(s) sur {} dans la configuration.'.format(n_found, len(saved))
    if n_missed > 0:
        msg += (u'\n\n{} note(s) n\'ont pas \xe9t\xe9 retrouv\xe9e(s) dans le projet actuel\n'
                u'(supprim\xe9es ou modifi\xe9es depuis la sauvegarde).').format(n_missed)
    _nm_dialog(u'Configuration charg\xe9e', msg)
    return (n_found, len(saved))


# ─── Termes de texte ─────────────────────────────────────────────────────────
#
# Format du fichier de termes (JSON) :
# {
#   "version": 1,
#   "terms": ["NIV 0", "Carrelage", "C001", ...]
# }
# Les termes sont les textes exacts (après strip) des notes textuelles.
# Un terme par note, valeurs uniques, triées.

def save_terms(all_notes, owner=None, copy_settings=None):
    """
    Enregistre les textes des notes cochées dans un fichier de valeurs.
    - Retire le préfixe ✔  avant d'enregistrer (valeur nettoyée).
    - Ne duplique pas une valeur déjà présente (après nettoyage).
    - Enregistre aussi les réglages "Copie vers" si fournis.
    copy_settings : dict {'target': 'Pieces'|'Espaces', 'param': str} ou None
    """
    checked = [n for n in all_notes if n.checked]
    if not checked:
        _nm_dialog(u'Aucune s\xe9lection',
                   u'Aucune note coch\xe9e.\nCochez des notes avant d\'enregistrer les termes.',
                   owner=owner)
        return

    def _clean(t):
        """Retire le préfixe ✔  du texte."""
        s = t.strip()
        if s.startswith(_MARKER): s = s[len(_MARKER):]
        return s.strip()

    # Termes nettoyés, uniques, sans vides
    new_terms = sorted(set(_clean(n.text) for n in checked if _clean(n.text)),
                       key=lambda t: t.lower())

    dlg = WinForms.SaveFileDialog()
    dlg.Title      = u'Enregistrer les termes de texte'
    dlg.Filter     = u'Termes notes textuelles (*.NM-Note-Txt-Exp)|*.NM-Note-Txt-Exp|Tous (*.*)|*.*'
    dlg.DefaultExt = 'NM-Note-Txt-Exp'
    dlg.FileName   = 'termes_notes_textuelles.NM-Note-Txt-Exp'
    if dlg.ShowDialog() != WinForms.DialogResult.OK:
        return

    # Si le fichier existe, lire les termes existants (nettoyés aussi)
    existing_terms = set()
    existing_settings = {}
    file_exists = os.path.isfile(dlg.FileName)
    if file_exists:
        try:
            with codecs.open(dlg.FileName, 'r', 'utf-8') as f:
                existing_data = json.load(f)
            # Nettoyer les termes existants au cas où ils auraient un ✔
            existing_terms    = set(_clean(t) for t in existing_data.get('terms', []) if _clean(t))
            existing_settings = existing_data.get('copy_settings', {})
        except Exception:
            existing_terms = set()

    if file_exists and existing_terms:
        added   = [t for t in new_terms if t not in existing_terms]
        already = len(new_terms) - len(added)

        # Détecter si les réglages "Copie vers" ont changé
        settings_changed = (copy_settings and copy_settings != existing_settings)

        if not added:
            # Aucun nouveau terme — vérifier si les réglages ont changé
            if settings_changed:
                new_target = copy_settings.get('target', u'')
                new_param  = copy_settings.get('param',  u'')
                old_target = existing_settings.get('target', u'')
                old_param  = existing_settings.get('param',  u'')
                msg_confirm = (
                    u'Les {} terme(s) s\xe9lectionn\xe9(s) sont d\xe9j\xe0 tous pr\xe9sents '
                    u'dans le fichier.\n\nEn revanche, les r\xe9glages "Copie vers" ont chang\xe9 :\n'
                    u'  Cible : {}\u2192{}\n'
                    u'  Param\xe8tre : {}\u2192{}\n\n'
                    u'Mettre \xe0 jour les r\xe9glages dans le fichier ?'
                ).format(len(new_terms),
                         old_target, new_target,
                         old_param,  new_param)
                if not _nm_confirm(u'Mettre \xe0 jour les r\xe9glages', msg_confirm, owner=owner):
                    return
                # Écrire le fichier avec les nouveaux réglages, termes inchangés
                final_terms = sorted(existing_terms, key=lambda t: t.lower())
                n_added = 0
            else:
                _nm_dialog(u'Aucune modification',
                           u'Les {} terme(s) s\xe9lectionn\xe9(s) sont d\xe9j\xe0 tous pr\xe9sents '
                           u'dans le fichier\net les r\xe9glages "Copie vers" sont identiques.\n'
                           u'Aucune modification effectu\xe9e.'.format(len(new_terms)),
                           owner=owner)
                return
        else:
            msg_confirm = (
                u'Le fichier contient d\xe9j\xe0 {} terme(s).\n\n'
                u'{} nouveau(x) terme(s) vont \xeatre ajout\xe9(s).\n'
                u'{} terme(s) existent d\xe9j\xe0 et ne seront pas dupliqu\xe9(s).\n\n'
                u'Confirmer l\'ajout ?'
            ).format(len(existing_terms), len(added), already)
            if not _nm_confirm(u'Ajouter des termes au fichier', msg_confirm, owner=owner):
                return
            final_terms = sorted(existing_terms | set(new_terms), key=lambda t: t.lower())
            n_added = len(added)
    else:
        final_terms = new_terms
        n_added     = len(final_terms)

    # Réglages "Copie vers" : nouveaux réglages écrasent les anciens si fournis
    settings_to_save = existing_settings
    if copy_settings:
        settings_to_save = copy_settings

    try:
        data_out = {'version': 1, 'terms': final_terms}
        if settings_to_save:
            data_out['copy_settings'] = settings_to_save
        with codecs.open(dlg.FileName, 'w', 'utf-8') as f:
            json.dump(data_out, f, indent=2, ensure_ascii=False)
        _log(u'Termes sauvegardes : {} total, {} ajoutes'.format(len(final_terms), n_added))
        msg = (u'{} terme(s) au total dans le fichier.\n'
               u'{} nouveau(x) terme(s) ajout\xe9(s).\n\n{}').format(
                   len(final_terms), n_added, dlg.FileName)
        if settings_to_save:
            msg += u'\n\nR\xe9glages "Copie vers" enregistr\xe9s :\nCible : {}\nParam\xe8tre : {}'.format(
                settings_to_save.get('target', u''), settings_to_save.get('param', u''))
        _nm_dialog(u'Termes enregistr\xe9s', msg, owner=owner)
    except Exception as ex:
        _nm_dialog(u'Erreur', u'Erreur lors de la sauvegarde :\n' + str(ex), owner=owner)


def load_terms(all_notes, apply_view_fn, update_counter_fn,
               on_copy_settings=None, owner=None):
    """
    Charge un fichier de termes, coche les notes correspondantes (après
    nettoyage du préfixe ✔), et applique les réglages "Copie vers" si présents.
    on_copy_settings : callable(target_str, param_str) pour mettre à jour l'UI
    """
    dlg = WinForms.OpenFileDialog()
    dlg.Title      = u'Charger un fichier de termes'
    dlg.Filter     = u'Termes notes textuelles (*.NM-Note-Txt-Exp)|*.NM-Note-Txt-Exp|Tous (*.*)|*.*'
    dlg.DefaultExt = 'NM-Note-Txt-Exp'
    if dlg.ShowDialog() != WinForms.DialogResult.OK:
        return None

    try:
        with codecs.open(dlg.FileName, 'r', 'utf-8') as f:
            data = json.load(f)
    except Exception as ex:
        _nm_dialog(u'Erreur de lecture', u'Impossible de lire le fichier :\n' + str(ex),
                   owner=owner)
        return None

    terms = data.get('terms', [])
    if not terms:
        _nm_dialog(u'Fichier vide', u'Le fichier ne contient aucun terme.', owner=owner)
        return None

    def _clean(t):
        s = t.strip()
        if s.startswith(_MARKER): s = s[len(_MARKER):]
        return s.strip()

    # Comparaison insensible à la casse, après nettoyage ✔
    terms_lower = set(_clean(t).lower() for t in terms if _clean(t))

    for n in all_notes:
        n.checked = False
        if n.cb is not None: n.cb.IsChecked = False

    n_found = 0
    for n in all_notes:
        # Ne pas cocher les notes déjà marquées ✔ (déjà traitées)
        if n.text.startswith(_MARKER):
            continue
        if _clean(n.text).lower() in terms_lower:
            n.checked = True
            if n.cb is not None: n.cb.IsChecked = True
            n_found += 1

    _log(u'Termes charges : {} termes, {} notes cochees'.format(len(terms), n_found))
    apply_view_fn()
    update_counter_fn()

    # Appliquer les réglages "Copie vers" si présents et callback fourni
    copy_settings = data.get('copy_settings', {})
    settings_msg  = u''
    if copy_settings and on_copy_settings:
        t_val = copy_settings.get('target', u'')
        p_val = copy_settings.get('param',  u'')
        if t_val or p_val:
            on_copy_settings(t_val, p_val)
            settings_msg = u'\n\nR\xe9glages "Copie vers" restaur\xe9s :\nCible : {}\nParam\xe8tre : {}'.format(
                t_val, p_val)

    n_not_found = len(terms_lower) - len(
        set(_clean(n.text).lower() for n in all_notes if n.checked))
    msg = u'{} note(s) coch\xe9e(s) correspondant aux {} terme(s) du fichier.'.format(
        n_found, len(terms))
    if n_not_found > 0:
        msg += (u'\n\n{} terme(s) du fichier n\'ont trouv\xe9 aucune note dans cette vue\n'
                u'(notes absentes ou textes l\xe9g\xe8rement diff\xe9rents).').format(n_not_found)
    msg += settings_msg
    _nm_dialog(u'Termes charg\xe9s', msg, owner=owner)
    return n_found


# ─── Fonctions Copie vers Pièces / Espaces ───────────────────────────────────
def _get_target_params(doc, use_spaces=False):
    """
    Retourne la liste triée des noms de paramètres String d'instance
    non-lecture seule des Pièces (ou Espaces si use_spaces=True).
    """
    cat = (BuiltInCategory.OST_MEPSpaces if use_spaces
           else BuiltInCategory.OST_Rooms)
    elems = (FilteredElementCollector(doc)
             .OfCategory(cat)
             .WhereElementIsNotElementType()
             .ToElements())
    if not elems:
        return []
    sample = elems[0]
    return sorted(set(
        p.Definition.Name
        for p in sample.Parameters
        if not p.IsReadOnly and p.StorageType == StorageType.String
    ))


def _get_current_view_level_z(doc):
    """
    Retourne l'élévation Z du niveau de la vue active + 0.1 ft.
    Nécessaire pour GetRoomAtPoint / GetSpaceAtPoint.
    """
    view = doc.ActiveView
    if isinstance(view, ViewPlan):
        lvl = view.GenLevel
        if lvl:
            return lvl.Elevation + 0.1
    return 0.0


def _popup_conflict(conflicts, owner):
    """
    Affiche une fenêtre de choix quand plusieurs notes pointent
    vers la même Pièce/Espace.
    conflicts : list de (room_name, room_id_int, [NoteInfo, ...])
    Retourne un dict {room_id_int: NoteInfo choisie} ou None si annulé.
    """
    from System.Windows import Window as WpfWin, Thickness as TH
    from System.Windows import GridLength as GL, GridUnitType as GU
    from System.Windows import HorizontalAlignment as HA, VerticalAlignment as VA
    from System.Windows import ResizeMode, WindowStartupLocation
    from System.Windows.Controls import (
        Grid as WG, StackPanel as SP, ScrollViewer as SV,
        GroupBox as GB, RadioButton as RB, Button as BTN,
        TextBlock as TB, ColumnDefinition as CD, RowDefinition as RD,
        ScrollBarVisibility
    )

    dlg = WpfWin()
    dlg.Title = u'Conflits de notes \u2014 choisir la valeur \xe0 copier'
    dlg.Width = 520; dlg.Height = 480
    dlg.MinWidth = 380; dlg.MinHeight = 300
    dlg.ResizeMode = ResizeMode.CanResize
    dlg.WindowStartupLocation = WindowStartupLocation.CenterOwner
    try: dlg.Owner = owner
    except Exception: pass

    root = WG(); root.Margin = TH(10)
    rd_top = RD(); rd_top.Height = GL(1, GU.Star)
    rd_btn = RD(); rd_btn.Height = GL(0, GU.Auto)
    root.RowDefinitions.Add(rd_top); root.RowDefinitions.Add(rd_btn)

    sv = SV(); sv.VerticalScrollBarVisibility = ScrollBarVisibility.Auto
    WG.SetRow(sv, 0)
    panel = SP(); panel.Margin = TH(0, 0, 0, 8)
    sv.Content = panel

    result = {}
    radio_groups = {}   # room_id_int → [(rb, note)]

    for room_name, room_id_int, notes in conflicts:
        gb = GB()
        gb.Header = u'{} ({} notes)'.format(room_name, len(notes))
        gb.Margin = TH(0, 0, 0, 8)
        inner = SP(); inner.Margin = TH(4, 4, 4, 4)
        rbs = []
        for i, note in enumerate(notes):
            rb = RB()
            rb.Content   = u'  ' + (note.text if len(note.text) <= 80 else note.text[:77]+u'...')
            rb.IsChecked = (i == 0)
            rb.ToolTip   = note.text
            rb.Margin    = TH(2, 1, 2, 1)
            rb.GroupName = u'conflict_{}'.format(room_id_int)
            inner.Children.Add(rb)
            rbs.append((rb, note))
        radio_groups[room_id_int] = rbs
        gb.Content = inner
        panel.Children.Add(gb)

    btn_row = WG(); WG.SetRow(btn_row, 1)
    cd1 = CD(); cd1.Width = GL(1, GU.Star)
    cd2 = CD(); cd2.Width = GL(8)
    cd3 = CD(); cd3.Width = GL(1, GU.Star)
    btn_row.ColumnDefinitions.Add(cd1)
    btn_row.ColumnDefinitions.Add(cd2)
    btn_row.ColumnDefinitions.Add(cd3)

    btn_ok  = BTN(); btn_ok.Content  = u'Valider les choix'; btn_ok.Height = 30
    btn_ann = BTN(); btn_ann.Content = u'Annuler';            btn_ann.Height = 30
    WG.SetColumn(btn_ok, 0); WG.SetColumn(btn_ann, 2)

    cancelled = [False]
    def on_ok(s, e):
        for room_id_int, rbs in radio_groups.items():
            for rb, note in rbs:
                if bool(rb.IsChecked):
                    result[room_id_int] = note; break
        setattr(dlg, 'DialogResult', True)
    def on_cancel(s, e):
        cancelled[0] = True; setattr(dlg, 'DialogResult', False)

    btn_ok.Click  += on_ok
    btn_ann.Click += on_cancel
    btn_row.Children.Add(btn_ok); btn_row.Children.Add(btn_ann)

    root.Children.Add(sv); root.Children.Add(btn_row)
    dlg.Content = root
    dlg.ShowDialog()
    return None if cancelled[0] else result


def _copy_to_targets(doc, uidoc, all_notes, param_name, use_spaces, owner):
    """
    Copie le texte des notes cochées dans le paramètre param_name
    des Pièces (ou Espaces) qui les contiennent.

    Comportement :
    - Si une seule note → Pièce : copie directe
    - Si plusieurs notes → Pièce : popup de choix
    - La note dont le texte est copié reçoit le préfixe ✔
    - Les autres notes de la même Pièce ne sont pas marquées
    """
    checked = [n for n in all_notes if n.checked]
    if not checked:
        _nm_dialog(u'Aucune s\xe9lection',
                   u'Aucune note coch\xe9e.\nCochez au moins une note avant de copier.',
                   owner=owner)
        return

    z = _get_current_view_level_z(doc)
    cat = (BuiltInCategory.OST_MEPSpaces if use_spaces
           else BuiltInCategory.OST_Rooms)
    cat_label = u'Espace' if use_spaces else u'Pi\xe8ce'

    # Regrouper les notes cochées par Pièce/Espace
    target_to_notes = {}   # elem_id_int → [NoteInfo]
    target_names    = {}   # elem_id_int → nom affiché
    no_target       = []   # NoteInfo sans cible trouvée

    for note in checked:
        try:
            tn = doc.GetElement(note.elem_id)
            pt2d = tn.Coord
            pt3d = XYZ(pt2d.X, pt2d.Y, z)
            if use_spaces:
                target = doc.GetSpaceAtPoint(pt3d)
            else:
                target = doc.GetRoomAtPoint(pt3d)
            if target is None:
                no_target.append(note)
                continue
            tid = target.Id.IntegerValue
            target_to_notes.setdefault(tid, []).append(note)
            # Nom affiché
            p_name = target.get_Parameter(BuiltInParameter.ROOM_NAME)
            p_num  = target.get_Parameter(BuiltInParameter.ROOM_NUMBER)
            tname  = u''
            if p_name and p_name.HasValue: tname = p_name.AsString() or u''
            if p_num  and p_num.HasValue:
                tname = (p_num.AsString() or u'') + u' ' + tname
            target_names[tid] = tname.strip() or u'{}({})'.format(cat_label, tid)
        except Exception as ex:
            _log(u'Copie - erreur localisation note : ' + str(ex))
            no_target.append(note)

    if not target_to_notes:
        _nm_dialog(u'Aucune cible',
                   u'Aucune note coch\xe9e ne se trouve dans une {}.\n'
                   u'V\xe9rifiez la vue active et la localisation des notes.'.format(cat_label),
                   owner=owner)
        return

    # Détecter les conflits (plusieurs notes → même cible)
    conflicts = [
        (target_names[tid], tid, notes)
        for tid, notes in target_to_notes.items()
        if len(notes) > 1
    ]

    # Résolution des conflits par popup
    conflict_choices = {}
    if conflicts:
        conflict_choices = _popup_conflict(conflicts, owner)
        if conflict_choices is None:
            return   # annulé par l'utilisateur

    # Construire le dict final {tid → NoteInfo à copier}
    final = {}
    for tid, notes in target_to_notes.items():
        if len(notes) == 1:
            final[tid] = notes[0]
        else:
            chosen = conflict_choices.get(tid)
            if chosen is not None:
                final[tid] = chosen

    if not final:
        return

    # Notes dans final → candidats au succès
    # Notes cochées mais pas dans final (hors cible ou non choisies) → échec
    final_note_ids = set(id(n) for n in final.values())
    notes_not_in_final = [n for n in checked
                          if id(n) not in final_note_ids]

    # Transaction
    n_ok = n_skip = 0
    errors = []
    t = Transaction(doc, u'Copie Notes \u2192 {}'.format(cat_label + u's'))
    t.Start()
    try:
        for tid, note in final.items():
            try:
                target = doc.GetElement(ElementId(tid))
                param  = target.LookupParameter(param_name)
                if param is None or param.IsReadOnly:
                    # Écriture impossible → marquer la note ✘
                    tn = doc.GetElement(note.elem_id)
                    raw = tn.Text
                    if raw.startswith(_MARKER):      raw = raw[len(_MARKER):]
                    elif raw.startswith(_MARKER_FAIL): raw = raw[len(_MARKER_FAIL):]
                    tn.Text = _MARKER_FAIL + raw
                    n_skip += 1
                    continue
                # Copier la valeur nettoyée (sans préfixe ✔/✘ éventuel)
                raw_text = note.text
                if raw_text.startswith(_MARKER):       raw_text = raw_text[len(_MARKER):]
                elif raw_text.startswith(_MARKER_FAIL): raw_text = raw_text[len(_MARKER_FAIL):]
                param.Set(raw_text)
                # Marquer la note ✔ (remplace ✘ si présent)
                tn = doc.GetElement(note.elem_id)
                raw = tn.Text
                if raw.startswith(_MARKER):       raw = raw[len(_MARKER):]
                elif raw.startswith(_MARKER_FAIL): raw = raw[len(_MARKER_FAIL):]
                tn.Text = _MARKER + raw
                n_ok += 1
            except Exception as ex:
                errors.append(str(ex))
                # Exception → marquer la note ✘
                try:
                    tn = doc.GetElement(note.elem_id)
                    raw = tn.Text
                    if raw.startswith(_MARKER):       raw = raw[len(_MARKER):]
                    elif raw.startswith(_MARKER_FAIL): raw = raw[len(_MARKER_FAIL):]
                    tn.Text = _MARKER_FAIL + raw
                except Exception: pass
                n_skip += 1

        # Notes hors Pièce/Espace ou non choisies en conflit → marquer ✘
        for note in no_target + notes_not_in_final:
            try:
                tn = doc.GetElement(note.elem_id)
                raw = tn.Text
                if raw.startswith(_MARKER):       raw = raw[len(_MARKER):]
                elif raw.startswith(_MARKER_FAIL): raw = raw[len(_MARKER_FAIL):]
                if not raw.startswith(_MARKER):   # ne pas écraser un ✔ existant
                    tn.Text = _MARKER_FAIL + raw
            except Exception: pass

        t.Commit()
    except Exception as ex:
        t.RollBack()
        _nm_dialog(u'Erreur de transaction',
                   u'Erreur lors de la copie :\n' + str(ex), owner=owner)
        return

    lines = [u'{} {}(s) mise(s) \xe0 jour \u2014 param\xe8tre \xab{}\xbb'.format(
             n_ok, cat_label, param_name)]
    if no_target:
        lines.append(u'{} note(s) hors {}(s) ignor\xe9e(s)'.format(
            len(no_target), cat_label))
    if n_skip:
        lines.append(u'{} \xe9criture(s) impossible(s) (param\xe8tre absent ou lecture seule)'.format(n_skip))
    if errors:
        lines.append(u'{} erreur(s)'.format(len(errors)))
        for e in errors[:3]: _log(e)
    # Ici on veut fermer toutes les boîtes du script quand l'utilisateur clique OK
    _nm_dialog(u'Copie termin\xe9e', u'\n'.join(lines), owner=owner, close_all=True)


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    _log(u'Demarrage')

    all_notes = collect_text_notes(doc)
    _log(u'{} notes'.format(len(all_notes)))

    if not all_notes:
        _nm_dialog(u'Aucune note', u'Aucune note textuelle trouv\xe9e dans ce projet.')
        return

    unique_texts  = sorted(set(n.text      for n in all_notes), key=lambda t: t.lower())
    unique_types  = sorted(set(n.type_name for n in all_notes), key=lambda t: t.lower())
    unique_colors = sorted(set(n.color_str for n in all_notes))
    # Filtres vide = inactif (toutes notes passent)
    filter_texts  = set()
    filter_types  = set()
    filter_colors = set()
    filter_check  = ['all']

    _sort = {'col': None, 'dir': None}

    xaml_path = os.path.join(os.path.dirname(__file__), 'WPFWindow.xaml')
    wpf       = forms.WPFWindow(xaml_path)
    wpf.Title = u'Notes Textuelles \u2014 Vue active : {} ({} notes)'.format(
        doc.ActiveView.Name, len(all_notes))

    hdr_cols    = wpf.headerGrid.ColumnDefinitions   # 7 cols (sans Vue)
    notes_panel = wpf.notesPanel

    # Largeurs initiales — 7 colonnes :
    # [0:30 ✓] [1:4 sep] [2:2* Texte] [3:4 split] [4:* Type] [5:4 split] [6:110 Couleur]
    init_w = [COL_W_TEXT, COL_W_TYPE]
    def _init_widths():
        return [30, 4,
                init_w[0] if init_w[0] > 0 else 0,
                4,
                init_w[1] if init_w[1] > 0 else 0,
                4,
                110]

    # Pré-construction des lignes WPF (fait UNE SEULE FOIS)
    _log(u'Pre-construction des {} lignes...'.format(len(all_notes)))
    for note in all_notes:
        _build_note_row(note, _init_widths())

    # ── Synchronisation colonnes (LayoutUpdated → ActualWidth en pixels) ──────
    _cached_w = [None]

    def _sync(s=None, e=None):
        new_w = [hdr_cols[i].ActualWidth for i in range(hdr_cols.Count)]
        if new_w == _cached_w[0] or new_w[0] == 0.0:
            return
        _cached_w[0] = new_w[:]
        for note in all_notes:
            if note._row_cols:
                for i, cd in enumerate(note._row_cols):
                    if new_w[i] > 0:
                        cd.Width = GridLength(new_w[i])

    wpf.headerGrid.LayoutUpdated += _sync

    visible_notes = []
    last_idx      = [-1]

    def _update_counter():
        nc = sum(1 for n in all_notes if n.checked)
        wpf.txtCounter.Text = u'{} coch\xe9e(s) / {} affich\xe9e(s) / {} totale(s)'.format(
            nc, len(visible_notes), len(all_notes))

    def _sort_label(col_key):
        if _sort['col'] != col_key: return u'\u21c5'
        return u'A\u2192Z' if _sort['dir'] == 'asc' else u'Z\u2192A'

    def _update_sort_btns():
        wpf.btnSortText.Content  = _sort_label('text')
        wpf.btnSortType.Content  = _sort_label('type')
        wpf.btnSortColor.Content = _sort_label('color')

    def _update_filter_labels():
        # Ensemble vide = filtre inactif → label neutre sans compteur
        # Ensemble non vide = filtre actif → label avec compteur
        nt  = len(filter_texts);  ntt  = len(unique_texts)
        ny  = len(filter_types);  nty  = len(unique_types)
        nc  = len(filter_colors); ntc  = len(unique_colors)
        chk = {'all': u'\u25bc Tout', 'checked': u'\u25bc Coch\xe9s',
               'unchecked': u'\u25bc Non coch\xe9s'}
        wpf.btnFilterCheck.Content = chk.get(filter_check[0], u'\u25bc')
        wpf.btnFilterText.Content  = (u'\u25bc Texte' if nt == 0
                                      else u'\u25bc Texte : {}/{}'.format(nt, ntt))
        wpf.btnFilterType.Content  = (u'\u25bc Type' if ny == 0
                                      else u'\u25bc Type : {}/{}'.format(ny, nty))
        wpf.btnFilterColor.Content = (u'\u25bc Couleur' if nc == 0
                                      else u'\u25bc Couleur : {}/{}'.format(nc, ntc))

    def apply_view():
        """Filtre + tri + StackPanel. Réutilise les lignes pré-construites.
        Règle : ensemble de filtre VIDE = filtre inactif (toutes les valeurs passent).
        """
        fc = filter_check[0]
        result = []
        for note in all_notes:
            if fc == 'checked'   and not note.checked: continue
            if fc == 'unchecked' and note.checked:     continue
            # Filtre actif seulement si l'ensemble est non vide
            if filter_texts  and note.text      not in filter_texts:  continue
            if filter_types  and note.type_name not in filter_types:  continue
            if filter_colors and note.color_str not in filter_colors: continue
            result.append(note)

        col = _sort['col']; rev = (_sort['dir'] == 'desc')
        if   col == 'text':  result.sort(key=lambda n: n.text.lower(),      reverse=rev)
        elif col == 'type':  result.sort(key=lambda n: n.type_name.lower(), reverse=rev)
        elif col == 'color': result.sort(key=lambda n: n.color_str,         reverse=rev)

        notes_panel.Children.Clear()
        del visible_notes[:]
        last_idx[0] = -1

        for i, note in enumerate(result):
            note._bg_border.Background = _ROW_ALT if i % 2 == 1 else _ROW_NORM
            notes_panel.Children.Add(note._border)
            visible_notes.append(note)

        _update_counter()
        _update_filter_labels()
        _update_sort_btns()

    # ── Handlers tri ─────────────────────────────────────────────────────────
    def _make_sort_handler(col_key):
        def on_sort(s, e):
            if _sort['col'] != col_key:
                _sort['col'] = col_key; _sort['dir'] = 'asc'
            elif _sort['dir'] == 'asc':
                _sort['dir'] = 'desc'
            else:
                _sort['col'] = None; _sort['dir'] = None
            apply_view()
        return on_sort

    wpf.btnSortText.Click  += _make_sort_handler('text')
    wpf.btnSortType.Click  += _make_sort_handler('type')
    wpf.btnSortColor.Click += _make_sort_handler('color')

    # ── Handlers filtres ─────────────────────────────────────────────────────
    def on_filter_check(s, e):
        filter_check[0] = show_check_filter_popup(filter_check[0], wpf); apply_view()
    def on_filter_text(s, e):
        show_filter_popup(u'Filtrer par texte',    unique_texts,  filter_texts,  wpf); apply_view()
    def on_filter_type(s, e):
        show_filter_popup(u'Filtrer par type',     unique_types,  filter_types,  wpf); apply_view()
    def on_filter_color(s, e):
        show_filter_popup(u'Filtrer par couleur',  unique_colors, filter_colors, wpf); apply_view()

    wpf.btnFilterCheck.Click += on_filter_check
    wpf.btnFilterText.Click  += on_filter_text
    wpf.btnFilterType.Click  += on_filter_type
    wpf.btnFilterColor.Click += on_filter_color

    # ── Handlers réinitialisation des filtres ─────────────────────────────────
    # Vider l'ensemble = filtre inactif = toutes les notes de la colonne passent
    def on_reset_text(s, e):
        filter_texts.clear();  apply_view()
    def on_reset_type(s, e):
        filter_types.clear();  apply_view()
    def on_reset_color(s, e):
        filter_colors.clear(); apply_view()

    wpf.btnResetText.Click  += on_reset_text
    wpf.btnResetType.Click  += on_reset_type
    wpf.btnResetColor.Click += on_reset_color

    # ── Réinitialisation filtre cases à cocher ────────────────────────────────
    def on_reset_check(s, e):
        filter_check[0] = 'all'; apply_view()
    wpf.btnResetCheck.Click += on_reset_check

    # ── Réinitialisation globale (tous les filtres d'un coup) ─────────────────
    def on_reset_all(s, e):
        filter_texts.clear()
        filter_types.clear()
        filter_colors.clear()
        filter_check[0] = 'all'
        apply_view()
    wpf.btnResetAll.Click += on_reset_all

    # ── Shift+clic sur les checkboxes ─────────────────────────────────────────
    def _wire_all_checkboxes():
        """Câble les handlers Shift+clic sur toutes les notes pré-construites."""
        for note in all_notes:
            def _mk(note_ref):
                def on_click(s, e):
                    try:
                        cur_idx = visible_notes.index(note_ref)
                    except ValueError:
                        note_ref.checked = bool(note_ref.cb.IsChecked)
                        _update_counter(); return
                    ns = bool(note_ref.cb.IsChecked)
                    shift = (Keyboard.IsKeyDown(WpfKey.LeftShift) or
                             Keyboard.IsKeyDown(WpfKey.RightShift))
                    if shift and last_idx[0] >= 0:
                        lo, hi = min(last_idx[0], cur_idx), max(last_idx[0], cur_idx)
                        for j in range(lo, hi+1):
                            if j < len(visible_notes):
                                vn = visible_notes[j]
                                vn.checked = ns; vn.cb.IsChecked = ns
                    else:
                        note_ref.checked = ns
                    last_idx[0] = cur_idx
                    _update_counter()
                return on_click
            note.cb.Click += _mk(note)

    _wire_all_checkboxes()

    # ── Handlers sélection ───────────────────────────────────────────────────
    wpf.btnSelectAll.Click   += lambda s, e: (
        [setattr(n,'checked',True)  or setattr(n.cb,'IsChecked',True)  for n in visible_notes],
        _update_counter())
    wpf.btnDeselectAll.Click += lambda s, e: (
        [setattr(n,'checked',False) or setattr(n.cb,'IsChecked',False) for n in visible_notes],
        _update_counter())
    wpf.btnInvert.Click      += lambda s, e: (
        [setattr(n,'checked',not n.checked) or setattr(n.cb,'IsChecked',n.checked)
         for n in visible_notes],
        _update_counter())

    def on_apply(s, e):
        checked = [n for n in all_notes if n.checked]
        if not checked:
            _nm_dialog(u'Aucune s\xe9lection',
                       u'Aucune note coch\xe9e.\nCochez au moins une note avant d\'appliquer.')
            return
        ids = List[ElementId]()
        for n in checked: ids.Add(n.elem_id)
        uidoc.Selection.SetElementIds(ids)
        _log(u'{} notes selectionnees'.format(len(checked)))
        show_result_window(u'{} note(s) textuelle(s)\ns\xe9lectionn\xe9e(s) dans Revit'.format(
            len(checked)))
        wpf.Close()

    wpf.btnApply.Click += on_apply
    wpf.btnClose.Click += lambda s, e: wpf.Close()

    # ── Handlers configuration sélection ─────────────────────────────────────
    wpf.btnSaveConfig.Click += lambda s, e: save_selection_config(all_notes)
    wpf.btnLoadConfig.Click += lambda s, e: load_selection_config(
        all_notes, apply_view, _update_counter)

    # ── Handlers termes de texte ──────────────────────────────────────────────
    def _get_copy_settings():
        """Lit les réglages Copie vers courants de l'UI."""
        use_sp = bool(wpf.rbEspaces.IsChecked)
        param  = wpf.cmbTargetParam.SelectedItem
        return {
            'target': u'Espaces' if use_sp else u'Pieces',
            'param':  u'{}'.format(param) if param else u''
        }

    def _apply_copy_settings(target_str, param_str):
        """Restaure les réglages Copie vers dans l'UI."""
        if target_str == u'Espaces':
            wpf.rbEspaces.IsChecked = True
        else:
            wpf.rbPieces.IsChecked = True
        _reload_target_params()
        # Sélectionner le paramètre dans le ComboBox
        for i in range(wpf.cmbTargetParam.Items.Count):
            if u'{}'.format(wpf.cmbTargetParam.Items[i]) == param_str:
                wpf.cmbTargetParam.SelectedIndex = i
                break

    wpf.btnSaveTerms.Click += lambda s, e: save_terms(
        all_notes, owner=wpf, copy_settings=_get_copy_settings())
    wpf.btnLoadTerms.Click += lambda s, e: load_terms(
        all_notes, apply_view, _update_counter,
        on_copy_settings=_apply_copy_settings, owner=wpf)

    apply_view()

    # ── GroupBox Copie vers ────────────────────────────────────────────────────
    # Charger les paramètres des Pièces au démarrage (Pièces sélectionnées par défaut)
    def _reload_target_params():
        use_sp = bool(wpf.rbEspaces.IsChecked)
        params = _get_target_params(doc, use_spaces=use_sp)
        wpf.cmbTargetParam.Items.Clear()
        for p in params:
            wpf.cmbTargetParam.Items.Add(p)
        if params:
            wpf.cmbTargetParam.SelectedIndex = 0

    _reload_target_params()

    wpf.rbPieces.Checked  += lambda s, e: _reload_target_params()
    wpf.rbEspaces.Checked += lambda s, e: _reload_target_params()

    def on_copy_to(s, e):
        param = wpf.cmbTargetParam.SelectedItem
        if not param:
            _nm_dialog(u'Aucun param\xe8tre',
                       u'S\xe9lectionnez un param\xe8tre cible dans la liste.')
            return
        use_sp = bool(wpf.rbEspaces.IsChecked)
        _copy_to_targets(doc, uidoc, all_notes,
                         u'{}'.format(param), use_sp, wpf)

    wpf.btnCopyTo.Click += on_copy_to

    wpf.show_dialog()


if __name__ == '__main__':
    main()
