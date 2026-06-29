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


#__title__ = "Sélection\nNotes Textuelles"
#__doc__ = """Sélection de notes textuelles
#Description : Sélection en masse de notes textuelles selon leur contenu, couleur ou type Revit.

#Version : 3.3 — 2026-04-17
#Auteur : data8bim (d8b)
#"""


# ─── LARGEURS PAR DÉFAUT ──────────────────────────────────────────────────────
# Modifiez ces valeurs pour changer les largeurs initiales des colonnes.
# Format : pixels entiers. La somme doit laisser de la place dans la fenêtre.
# Col ✓ est fixe (30px). Cols Texte/Type/Vue sont proportionnelles (2:1:1 par défaut).
# Pour changer : modifiez COL_W_TEXT, COL_W_TYPE, COL_W_VIEW.
# Exemple : COL_W_TEXT=350, COL_W_TYPE=200, COL_W_VIEW=200
COL_W_TEXT = 0   # 0 = utiliser les proportions XAML (2*, *, *) au premier lancement
COL_W_TYPE = 0   # Mettre un nombre > 0 pour forcer une largeur fixe initiale
COL_W_VIEW = 0   # Ex: COL_W_TEXT=400, COL_W_TYPE=200, COL_W_VIEW=200

import os, codecs, json, clr

clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')
clr.AddReference('System.Windows.Forms')

import System.Windows.Forms as WinForms

from pyrevit import forms
from Autodesk.Revit.DB import (
    FilteredElementCollector, BuiltInParameter, TextNote, ElementId
)
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


# ─── Collecte ─────────────────────────────────────────────────────────────────
class NoteInfo(object):
    def __init__(self, elem_id, type_name, text, view_name, color_rgb, color_str):
        self.elem_id    = elem_id
        self.type_name  = type_name
        self.text       = text
        self.view_name  = view_name
        self.color_rgb  = color_rgb   # (R, G, B) tuple
        self.color_str  = color_str   # "#RRGGBB" pour filtre/tri
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
    notes = []
    for tn in FilteredElementCollector(doc).OfClass(TextNote):
        try:
            tn_type = doc.GetElement(tn.GetTypeId())
            type_name = u'(sans type)'
            if tn_type:
                p = tn_type.get_Parameter(BuiltInParameter.ALL_MODEL_TYPE_NAME)
                if p: type_name = (p.AsString() or u'(sans type)').strip()
            text = (tn.Text or u'').replace(u'\r\n', u' ').replace(u'\n', u' ').strip()
            if not text: text = u'(vide)'
            view = doc.GetElement(tn.OwnerViewId)
            view_name = (view.Name if view else u'(aucune vue)').strip()
            rgb = _get_note_color(doc, tn)
            color_str = u'#{:02X}{:02X}{:02X}'.format(rgb[0], rgb[1], rgb[2])
            notes.append(NoteInfo(tn.Id, type_name, text, view_name, rgb, color_str))
        except Exception as ex:
            _log(u'Collecte : ' + str(ex))
    notes.sort(key=lambda n: (n.type_name.lower(), n.text.lower()))
    return notes



# ─── Résultat ─────────────────────────────────────────────────────────────────
def _nm_dialog(title, msg, btn_label=u'OK', owner=None):
    """
    Boîte de dialogue au style NM (ResultWindow.xaml).
    Utilisée pour tous les messages du script — pas de forms.alert.
    """
    xaml = os.path.join(os.path.dirname(__file__), 'ResultWindow.xaml')
    try:
        w = forms.WPFWindow(xaml)
        w.Title           = title
        w.txtMessage.Text = msg
        w.btnClose.Content = btn_label
        w.btnClose.Click  += lambda s, e: setattr(w, 'DialogResult', True)
        if owner:
            try: w.Owner = owner
            except Exception: pass
        w.show_dialog()
    except Exception:
        # Dernier recours si le XAML ne charge pas
        import System.Windows.MessageBox as MB
        MB.Show(msg, title)


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

    # Col 7 : séparateur
    sep7 = Border(); sep7.Background = _SEP_CLR
    sep7.Width = 1; sep7.HorizontalAlignment = HorizontalAlignment.Center
    Grid.SetColumn(sep7, 7); g.Children.Add(sep7)

    # Col 8 : vue
    t8 = TextBlock(); t8.Text = note.view_name
    t8.VerticalAlignment = VerticalAlignment.Center
    t8.Margin = Thickness(6,0,0,0); t8.Foreground = Brushes.Gray
    t8.TextTrimming = TextTrimming.CharacterEllipsis; t8.ToolTip = note.view_name
    Grid.SetColumn(t8, 8); g.Children.Add(t8)

    return outer


# ─── Sauvegarde / Chargement de la configuration de sélection ────────────────
#
# Format JSON :
# {
#   "version": 1,
#   "selection": [
#     {"elem_id": 12345, "text": "NIV 0", "type_name": "3mm", "view_name": "Plan RDC"},
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
             'text': n.text, 'type_name': n.type_name, 'view_name': n.view_name}
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

def save_terms(all_notes, owner=None):
    """
    Enregistre les textes des notes cochées dans un fichier de valeurs.
    Si le fichier existe déjà, complète avec les nouveaux termes absents.
    """
    checked = [n for n in all_notes if n.checked]
    if not checked:
        _nm_dialog(u'Aucune s\xe9lection',
                   u'Aucune note coch\xe9e.\nCochez des notes avant d\'enregistrer les termes.',
                   owner=owner)
        return

    new_terms = sorted(set(n.text.strip() for n in checked if n.text.strip()),
                       key=lambda t: t.lower())

    dlg = WinForms.SaveFileDialog()
    dlg.Title      = u'Enregistrer les termes de texte'
    dlg.Filter     = u'Termes notes textuelles (*.NM-Note-Txt-Exp)|*.NM-Note-Txt-Exp|Tous (*.*)|*.*'
    dlg.DefaultExt = 'NM-Note-Txt-Exp'
    dlg.FileName   = 'termes_notes_textuelles.NM-Note-Txt-Exp'
    if dlg.ShowDialog() != WinForms.DialogResult.OK:
        return

    # Si le fichier existe, proposer de le compléter
    existing_terms = set()
    file_exists = os.path.isfile(dlg.FileName)
    if file_exists:
        try:
            with codecs.open(dlg.FileName, 'r', 'utf-8') as f:
                existing_data = json.load(f)
            existing_terms = set(existing_data.get('terms', []))
        except Exception:
            existing_terms = set()

    if file_exists and existing_terms:
        added   = [t for t in new_terms if t not in existing_terms]
        already = len(new_terms) - len(added)
        if not added:
            _nm_dialog(u'Aucun nouveau terme',
                       u'Les {} terme(s) s\xe9lectionn\xe9(s) sont d\xe9j\xe0 tous pr\xe9sents dans le fichier.\n'
                       u'Aucune modification effectu\xe9e.'.format(len(new_terms)),
                       owner=owner)
            return
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

    try:
        with codecs.open(dlg.FileName, 'w', 'utf-8') as f:
            json.dump({'version': 1, 'terms': final_terms}, f,
                      indent=2, ensure_ascii=False)
        _log(u'Termes sauvegardes : {} total, {} ajoutes'.format(len(final_terms), n_added))
        _nm_dialog(u'Termes enregistr\xe9s',
                   u'{} terme(s) au total dans le fichier.\n'
                   u'{} nouveau(x) terme(s) ajout\xe9(s).\n\n{}'.format(
                       len(final_terms), n_added, dlg.FileName),
                   owner=owner)
    except Exception as ex:
        _nm_dialog(u'Erreur', u'Erreur lors de la sauvegarde :\n' + str(ex), owner=owner)


def load_terms(all_notes, apply_view_fn, update_counter_fn, owner=None):
    """
    Charge un fichier de termes et coche toutes les notes dont le texte
    figure dans la liste des termes.
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

    # Ensemble des termes (insensible à la casse pour la comparaison)
    terms_lower = set(t.strip().lower() for t in terms if t.strip())

    # Décocher toutes, puis cocher les correspondantes
    for n in all_notes:
        n.checked = False
        if n.cb is not None: n.cb.IsChecked = False

    n_found = 0
    for n in all_notes:
        if n.text.strip().lower() in terms_lower:
            n.checked = True
            if n.cb is not None: n.cb.IsChecked = True
            n_found += 1

    _log(u'Termes charges : {} termes, {} notes cochees'.format(len(terms), n_found))
    apply_view_fn()
    update_counter_fn()

    n_not_found = len(terms_lower) - len(
        set(n.text.strip().lower() for n in all_notes if n.checked))
    msg = u'{} note(s) coch\xe9e(s) correspondant aux {} terme(s) du fichier.'.format(
        n_found, len(terms))
    if n_not_found > 0:
        msg += (u'\n\n{} terme(s) du fichier n\'ont trouv\xe9 aucune note dans ce projet\n'
                u'(notes absentes ou textes l\xe9g\xe8rement diff\xe9rents).').format(n_not_found)
    _nm_dialog(u'Termes charg\xe9s', msg, owner=owner)
    return n_found


# ─── Main ────────────────────────────────────────────────────────────────────
def main():
    _log(u'Demarrage')

    all_notes = collect_text_notes(doc)
    _log(u'{} notes'.format(len(all_notes)))

    if not all_notes:
        _nm_dialog(u'Aucune note', u'Aucune note textuelle trouv\xe9e dans ce projet.')
        return

    # Valeurs uniques (strip déjà fait à la collecte → pas de doublons par espaces)
    unique_texts  = sorted(set(n.text      for n in all_notes), key=lambda t: t.lower())
    unique_types  = sorted(set(n.type_name for n in all_notes), key=lambda t: t.lower())
    unique_colors = sorted(set(n.color_str for n in all_notes))   # tri hex naturel
    unique_views  = sorted(set(n.view_name for n in all_notes), key=lambda t: t.lower())
    # Filtres : ensemble VIDE = aucun filtre actif (toutes les notes passent)
    #           ensemble NON VIDE = seules les valeurs présentes passent
    # → Par défaut aucun filtre n'est appliqué, toutes les notes sont visibles.
    filter_texts  = set()
    filter_types  = set()
    filter_colors = set()
    filter_views  = set()
    filter_check  = ['all']   # 'all' | 'checked' | 'unchecked'

    # État de tri : {'col': None|'text'|'type'|'color'|'view', 'dir': None|'asc'|'desc'}
    _sort = {'col': None, 'dir': None}

    xaml_path = os.path.join(os.path.dirname(__file__), 'WPFWindow.xaml')
    wpf       = forms.WPFWindow(xaml_path)
    wpf.Title = u'S\xe9lection de Notes Textuelles ({} notes)'.format(len(all_notes))

    hdr_cols    = wpf.headerGrid.ColumnDefinitions   # 9 cols
    notes_panel = wpf.notesPanel

    # Largeurs initiales — 9 colonnes :
    # [0:30 ✓] [1:4 sep] [2:Texte] [3:4 split] [4:Type]
    # [5:4 split] [6:110 Couleur] [7:4 split] [8:Vue]
    init_w = [COL_W_TEXT, COL_W_TYPE, COL_W_VIEW]
    def _init_widths():
        return [30, 4,
                init_w[0] if init_w[0] > 0 else 0,
                4,
                init_w[1] if init_w[1] > 0 else 0,
                4,
                110,   # Couleur : largeur fixe initiale
                4,
                init_w[2] if init_w[2] > 0 else 0]

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
        wpf.btnSortView.Content  = _sort_label('view')

    def _update_filter_labels():
        # Ensemble vide = filtre inactif → label neutre sans compteur
        # Ensemble non vide = filtre actif → label avec compteur
        nt  = len(filter_texts);  ntt  = len(unique_texts)
        ny  = len(filter_types);  nty  = len(unique_types)
        nc  = len(filter_colors); ntc  = len(unique_colors)
        nv  = len(filter_views);  ntv  = len(unique_views)
        chk = {'all': u'\u25bc Tout', 'checked': u'\u25bc Coch\xe9s',
               'unchecked': u'\u25bc Non coch\xe9s'}
        wpf.btnFilterCheck.Content = chk.get(filter_check[0], u'\u25bc')
        wpf.btnFilterText.Content  = (u'\u25bc Texte' if nt == 0
                                      else u'\u25bc Texte : {}/{}'.format(nt, ntt))
        wpf.btnFilterType.Content  = (u'\u25bc Type' if ny == 0
                                      else u'\u25bc Type : {}/{}'.format(ny, nty))
        wpf.btnFilterColor.Content = (u'\u25bc Couleur' if nc == 0
                                      else u'\u25bc Couleur : {}/{}'.format(nc, ntc))
        wpf.btnFilterView.Content  = (u'\u25bc Vue' if nv == 0
                                      else u'\u25bc Vue : {}/{}'.format(nv, ntv))

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
            if filter_views  and note.view_name not in filter_views:  continue
            result.append(note)

        col = _sort['col']; rev = (_sort['dir'] == 'desc')
        if   col == 'text':  result.sort(key=lambda n: n.text.lower(),      reverse=rev)
        elif col == 'type':  result.sort(key=lambda n: n.type_name.lower(), reverse=rev)
        elif col == 'color': result.sort(key=lambda n: n.color_str,         reverse=rev)
        elif col == 'view':  result.sort(key=lambda n: n.view_name.lower(), reverse=rev)

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
    wpf.btnSortView.Click  += _make_sort_handler('view')

    # ── Handlers filtres ─────────────────────────────────────────────────────
    def on_filter_check(s, e):
        filter_check[0] = show_check_filter_popup(filter_check[0], wpf); apply_view()
    def on_filter_text(s, e):
        show_filter_popup(u'Filtrer par texte',    unique_texts,  filter_texts,  wpf); apply_view()
    def on_filter_type(s, e):
        show_filter_popup(u'Filtrer par type',     unique_types,  filter_types,  wpf); apply_view()
    def on_filter_color(s, e):
        show_filter_popup(u'Filtrer par couleur',  unique_colors, filter_colors, wpf); apply_view()
    def on_filter_view(s, e):
        show_filter_popup(u'Filtrer par vue',      unique_views,  filter_views,  wpf); apply_view()

    wpf.btnFilterCheck.Click += on_filter_check
    wpf.btnFilterText.Click  += on_filter_text
    wpf.btnFilterType.Click  += on_filter_type
    wpf.btnFilterColor.Click += on_filter_color
    wpf.btnFilterView.Click  += on_filter_view

    # ── Handlers réinitialisation des filtres ─────────────────────────────────
    # Vider l'ensemble = filtre inactif = toutes les notes de la colonne passent
    def on_reset_text(s, e):
        filter_texts.clear();  apply_view()
    def on_reset_type(s, e):
        filter_types.clear();  apply_view()
    def on_reset_color(s, e):
        filter_colors.clear(); apply_view()
    def on_reset_view(s, e):
        filter_views.clear();  apply_view()

    wpf.btnResetText.Click  += on_reset_text
    wpf.btnResetType.Click  += on_reset_type
    wpf.btnResetColor.Click += on_reset_color
    wpf.btnResetView.Click  += on_reset_view

    # ── Réinitialisation filtre cases à cocher ────────────────────────────────
    def on_reset_check(s, e):
        filter_check[0] = 'all'; apply_view()
    wpf.btnResetCheck.Click += on_reset_check

    # ── Réinitialisation globale (tous les filtres d'un coup) ─────────────────
    def on_reset_all(s, e):
        filter_texts.clear()
        filter_types.clear()
        filter_colors.clear()
        filter_views.clear()
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
    wpf.btnSaveTerms.Click += lambda s, e: save_terms(all_notes, owner=wpf)
    wpf.btnLoadTerms.Click += lambda s, e: load_terms(
        all_notes, apply_view, _update_counter, owner=wpf)

    apply_view()
    wpf.show_dialog()


if __name__ == '__main__':
    main()
