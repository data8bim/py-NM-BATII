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



#__title__ = 'Parametres'
#__author__ = 'data8bim (d8b)'

import os, json, codecs
from pyrevit import forms


# ---------------------------------------------------------------------------
# Chargement / sauvegarde config.json
# ---------------------------------------------------------------------------
def load_config():
    cur = os.path.dirname(os.path.abspath(__file__))
    while not cur.lower().endswith('.extension'):
        parent = os.path.dirname(cur)
        if parent == cur:
            raise IOError("Dossier .extension introuvable depuis : " + cur)
        cur = parent
    cfg_path = os.path.join(cur, 'config.json')
    with codecs.open(cfg_path, 'r', 'utf-8') as f:
        return cfg_path, json.load(f)


def save_config(path, data):
    with codecs.open(path, 'w', 'utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    res_xaml = os.path.join(os.path.dirname(__file__), 'ResultWindow.xaml')
    res_win  = forms.WPFWindow(res_xaml)
    res_win.txtTitle.Text   = u"Paramètres"
    res_win.txtMessage.Text = u"Configuration enregistrée"
    res_win.btnClose.Click += lambda s, e: setattr(res_win, 'DialogResult', True)
    res_win.ShowDialog()


# ---------------------------------------------------------------------------
# Helpers lecture / ecriture des controles WPF
# ---------------------------------------------------------------------------
def txt(wpf, name):
    """Lire le texte d'un TextBox."""
    ctrl = getattr(wpf, name, None)
    return ctrl.Text.strip() if ctrl else ""


def set_txt(wpf, name, value):
    ctrl = getattr(wpf, name, None)
    if ctrl:
        ctrl.Text = str(value) if value is not None else ""


def chk(wpf, name):
    """Lire l'etat d'une CheckBox."""
    ctrl = getattr(wpf, name, None)
    return bool(ctrl.IsChecked) if ctrl else False


def set_chk(wpf, name, value):
    ctrl = getattr(wpf, name, None)
    if ctrl:
        ctrl.IsChecked = bool(value)


def get_color(wpf, r_name, g_name, b_name):
    """Lire une couleur [R, G, B] depuis 3 TextBox."""
    try:
        return [int(txt(wpf, r_name)),
                int(txt(wpf, g_name)),
                int(txt(wpf, b_name))]
    except (ValueError, TypeError):
        return [0, 0, 0]


def set_color(wpf, r_name, g_name, b_name, color):
    """Ecrire une couleur [R, G, B] dans 3 TextBox."""
    if isinstance(color, (list, tuple)) and len(color) >= 3:
        set_txt(wpf, r_name, color[0])
        set_txt(wpf, g_name, color[1])
        set_txt(wpf, b_name, color[2])
    else:
        set_txt(wpf, r_name, 0)
        set_txt(wpf, g_name, 0)
        set_txt(wpf, b_name, 0)


# ---------------------------------------------------------------------------
# Helper : construire une classe de caractères regex depuis une liste
# ---------------------------------------------------------------------------
def _build_char_class(chars):
    """Construit une regex [abc\-] depuis une liste de caractères."""
    if not chars:
        return ''
    parts = []
    has_dash = False
    for c in chars:
        if c == '-':
            has_dash = True
        elif c in ('\\', ']', '^'):
            parts.append('\\' + c)
        else:
            parts.append(c)
    result = ''.join(parts)
    if has_dash:
        result += '\\-'
    return '[' + result + ']'


# ---------------------------------------------------------------------------
# Fenetre Regex
# ---------------------------------------------------------------------------
def edit_regex_dialog(initial_pattern):
    xaml = os.path.join(os.path.dirname(__file__), 'RegexDialog.xaml')
    dlg  = forms.WPFWindow(xaml)
    dlg.Title = "Editeur Regex"
    dlg.regex_text.Text = initial_pattern
    dlg.btnCancel.Click += lambda s, e: setattr(dlg, 'DialogResult', False)
    dlg.btnSave.Click   += lambda s, e: setattr(dlg, 'DialogResult', True)
    return dlg.regex_text.Text if dlg.show_dialog() else initial_pattern


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    cfg_path, cfg = load_config()

    # Version installée (lue depuis extension.json)
    _ext_json = os.path.join(os.path.dirname(cfg_path), 'extension.json')
    try:
        with codecs.open(_ext_json, 'r', 'utf-8') as _ef:
            _ext_data = json.load(_ef)
        _version_installee = _ext_data.get('templates', {}).get('version', '?')
    except Exception:
        _version_installee = '?'

    # Sections avec valeur par defaut si absentes
    empl = cfg.setdefault('emplacements', {})
    enreg = empl.setdefault('enregistrements_rvt', {})
    sf   = cfg.setdefault('surface', {})
    cn   = cfg.setdefault('creer_niveaux', {})
    nc   = cfg.setdefault('nm_convention_noms_fichiers', {})
    dwg  = cfg.setdefault('fichiers_lies_dwg', {})
    _DEFAULT_PROFIL_OPTIONS = {
        u'color_mode': u'Conserver', u'layers': u'Tous', u'units': u'Metres',
        u'placement': u'Automatique - Emplacement partage',
        u'correct_lines': True, u'view_only': False,
    }
    _DEFAULT_PROFIL_VUES = {
        u'famille': u"Plan d'etage", u'type_personnalise': u'FM', u'vue_par_niveau': True,
    }
    _LOCKED_PROFIL_LABEL = u'< Par d\xe9faut >'
    _profils_raw = cfg.get(u'profils_liaison_cao', [])
    if not any(p.get(u'label') == _LOCKED_PROFIL_LABEL for p in _profils_raw):
        _profils_raw = [{
            u'label': _LOCKED_PROFIL_LABEL, u'systeme': True,
            u'options_liaisons': dict(_DEFAULT_PROFIL_OPTIONS),
            u'vues': dict(_DEFAULT_PROFIL_VUES),
        }] + list(_profils_raw)
    net  = cfg.setdefault('nettoyage', {})
    tc   = cfg.setdefault('nomenclatures_titres_couleurs', {})
    cc   = cfg.setdefault('nomenclatures_colonnes_couleurs', {})
    vm   = cfg.setdefault('vues_en_masse', {})
    vm_filtres = vm.setdefault('filtres_types_niveaux_defaut', {})
    cnv  = cfg.setdefault('conventions_nommage', {})

    xaml = os.path.join(os.path.dirname(__file__), 'WPFWindow.xaml')
    wpf  = forms.WPFWindow(xaml)
    wpf.Title = u"Paramètres"

    # ── Surfaces ─────────────────────────────────────────────────────────────
    set_txt(wpf, 'sf_param_shon',      sf.get('param_shon', ''))
    set_txt(wpf, 'sf_param_shob',      sf.get('param_shob', ''))
    set_txt(wpf, 'sf_param_s_plancher',sf.get('param_s_plancher', ''))
    set_txt(wpf, 'sf_col_shon',        sf.get('col_shon', ''))
    set_txt(wpf, 'sf_col_shob',        sf.get('col_shob', ''))
    set_txt(wpf, 'sf_col_plancher',    sf.get('col_plancher', ''))
    set_txt(wpf, 'sf_col_filter',      sf.get('col_filter', ''))
    set_txt(wpf, 'sf_default_shon',    sf.get('default_shon_schedule', ''))
    set_txt(wpf, 'sf_default_plancher',sf.get('default_plancher_schedule', ''))

    # ── Noms Niveaux ─────────────────────────────────────────────────────────
    set_txt(wpf, 'cn_espacement',    cn.get('espacement_default', 5.0))
    set_txt(wpf, 'cn_eleva_rdc',     cn.get('Eleva_Niv_Rdc', 0.0))
    set_txt(wpf, 'cn_eleva_origine', cn.get('Eleva_Niv_Origine', 0.0))

    # DataGrid unique des préfixes (système + personnalisés)
    import clr as _clr
    _clr.AddReference('System.Data')
    from System.Data import DataTable as SysDataTable
    from System.Windows.Input import Key
    from System.Windows.Controls.Primitives import ButtonBase
    from System.Windows import RoutedEventHandler
    from System.Windows.Controls import Button as _WpfButton

    _dt_pfx = SysDataTable()
    _dt_pfx.Columns.Add('prefixe')
    _dt_pfx.Columns.Add('definition')
    _dt_pfx.Columns.Add('positif', bool)
    _dt_pfx.Columns.Add('negatif', bool)
    _dt_pfx.Columns.Add('systeme', bool)

    for _p in cn.get('prefixes', []):
        _r = _dt_pfx.NewRow()
        _r['prefixe']    = _p.get('prefixe', '')
        _r['definition'] = _p.get('definition', '')
        _r['positif']    = bool(_p.get('positif', False))
        _r['negatif']    = bool(_p.get('negatif', False))
        _r['systeme']    = bool(_p.get('systeme', False))
        _dt_pfx.Rows.Add(_r)

    wpf.dgPrefixes.ItemsSource = _dt_pfx.DefaultView

    # DataGrid des sens de niveaux (sens-niv)
    _dt_sens = SysDataTable()
    _dt_sens.Columns.Add('signe')
    _dt_sens.Columns.Add('definition')

    _defaut_sens = [
        {'signe': '+', 'definition': u'Positif'},
        {'signe': '-', 'definition': u'N\xe9gatif'},
    ]
    for _s in (cn.get('sens') or _defaut_sens):
        _rs = _dt_sens.NewRow()
        _rs['signe']      = _s.get('signe', '')
        _rs['definition'] = _s.get('definition', '')
        _dt_sens.Rows.Add(_rs)

    wpf.dgSensNiveaux.ItemsSource = _dt_sens.DefaultView

    # Protection des lignes système
    def _is_sys_row(item):
        return hasattr(item, 'Row') and bool(item['systeme'])

    def _on_beginning_edit(s, e):
        if _is_sys_row(e.Row.Item) and e.Column.DisplayIndex != 0:
            e.Cancel = True

    def _on_preview_key_down(s, e):
        if e.Key == Key.Delete and _is_sys_row(wpf.dgPrefixes.SelectedItem):
            e.Handled = True

    wpf.dgPrefixes.BeginningEdit  += _on_beginning_edit
    wpf.dgPrefixes.PreviewKeyDown += _on_preview_key_down

    # ── Noms Fichiers ─────────────────────────────────────────────────────────
    # DataGrid des groupes atomiques
    _SYSTEM_IDS = {
        'site', 'construction', 'num-niv',
        'demi-niv', 'producteur', 'specialite',
    }
    # IDs dont la regex est auto-calculée depuis d'autres tables — exclus de dgGroupes
    _COMPUTED_IDS = ('pref-niv', 'sens-niv')

    _dt_grp = SysDataTable()
    _dt_grp.Columns.Add('label')
    _dt_grp.Columns.Add('id')
    _dt_grp.Columns.Add('regex')
    _dt_grp.Columns.Add('systeme',  bool)
    _dt_grp.Columns.Add('optionnel', bool)

    _defaut_groupes = [
        {'label': 'Site',                  'id': 'site',          'regex': r's\d{7}',         'systeme': True,  'optionnel': False},
        {'label': 'Construction',          'id': 'construction',  'regex': r'\d{3}',           'systeme': True,  'optionnel': False},
        {'label': u'Num\xe9ro niveau',     'id': 'num-niv',       'regex': r'\d{2}',           'systeme': True,  'optionnel': False},
        {'label': 'Demi-niveau',           'id': 'demi-niv',      'regex': r'\d{1}',           'systeme': True,  'optionnel': False},
        {'label': 'Producteur',            'id': 'producteur',    'regex': r'p\d{3}',          'systeme': True,  'optionnel': False},
        {'label': u'Sp\xe9cialit\xe9',     'id': 'specialite',    'regex': r'\d{3}',           'systeme': True,  'optionnel': False},
        {'label': 'Nom site court',        'id': 'nom-site-court','regex': r'[A-Z0-9-]+',      'systeme': False, 'optionnel': False},
        {'label': 'Reste du nom',          'id': 'rest-nom',      'regex': r'[A-Za-z0-9()-]+', 'systeme': False, 'optionnel': True},
    ]
    for _g in (nc.get('groupes') or _defaut_groupes):
        _gid = _g.get('id', '')
        if _gid in _COMPUTED_IDS:
            continue
        _rg = _dt_grp.NewRow()
        _rg['label']    = _g.get('label', '')
        _rg['id']       = _gid
        _rg['regex']    = _g.get('regex', '')
        _rg['systeme']  = bool(_g.get('systeme', _gid in _SYSTEM_IDS))
        _rg['optionnel']= bool(_g.get('optionnel', False))
        _dt_grp.Rows.Add(_rg)

    wpf.dgGroupes.ItemsSource = _dt_grp.DefaultView

    # Protection des lignes système (id non modifiable, suppression impossible)
    def _is_sys_grp_row(item):
        return hasattr(item, 'Row') and bool(item['systeme'])

    def _on_beginning_edit_grp(s, e):
        if _is_sys_grp_row(e.Row.Item) and e.Column.DisplayIndex == 1:
            e.Cancel = True

    def _on_preview_key_down_grp(s, e):
        if e.Key == Key.Delete and _is_sys_grp_row(wpf.dgGroupes.SelectedItem):
            e.Handled = True

    wpf.dgGroupes.BeginningEdit  += _on_beginning_edit_grp
    wpf.dgGroupes.PreviewKeyDown += _on_preview_key_down_grp

    set_txt(wpf, 'nc_val_nul',   nc.get('valeur_si_nul', ''))
    set_txt(wpf, 'nc_val_bim2d', nc.get('valeur_si_bim_2d', ''))

    # ── Templates de nommage (DataGrid unifié) ────────────────────────────────
    _defaut_templates = [
        {'id': 'fichiers',          'label': 'Fichiers',
         'systeme': True, 'template': '{site}_{construction}_{niveau}_{demi-niv}_{producteur}_{specialite}_{nom-site-court}_{rest-nom}'},
    ]
    _dt_tpl = SysDataTable()
    _dt_tpl.Columns.Add('label')
    _dt_tpl.Columns.Add('id')
    _dt_tpl.Columns.Add('template')
    _dt_tpl.Columns.Add('systeme', bool)
    for _t in (cnv.get('templates') or _defaut_templates):
        _rt = _dt_tpl.NewRow()
        _rt['label']    = _t.get('label', '')
        _rt['id']       = _t.get('id', '')
        _rt['template'] = _t.get('template', '')
        _rt['systeme']  = bool(_t.get('systeme', False))
        _dt_tpl.Rows.Add(_rt)
    wpf.dgTemplates.ItemsSource = _dt_tpl.DefaultView

    # Protection identifiant des lignes système dans dgTemplates
    def _is_sys_tpl_row(item):
        return hasattr(item, 'Row') and bool(item['systeme'])

    def _on_beginning_edit_tpl(s, e):
        if _is_sys_tpl_row(e.Row.Item) and e.Column.DisplayIndex == 1:
            e.Cancel = True

    def _on_preview_key_down_tpl(s, e):
        if e.Key == Key.Delete and _is_sys_tpl_row(wpf.dgTemplates.SelectedItem):
            e.Handled = True

    wpf.dgTemplates.BeginningEdit  += _on_beginning_edit_tpl
    wpf.dgTemplates.PreviewKeyDown += _on_preview_key_down_tpl

    # ── Vues personnalisées ────────────────────────────────────────────────────
    from utils.types_vues_personnalises import get_types_vues as _get_tvp
    from System import Int32 as _SysInt
    from System import Boolean as _SysBool
    _dt_tvp = SysDataTable()
    _dt_tvp.Columns.Add('ordre',   _SysInt)
    _dt_tvp.Columns.Add('label')
    _dt_tvp.Columns.Add('titre')
    _dt_tvp.Columns.Add('valeur_1')
    _dt_tvp.Columns.Add('valeur_2')
    _dt_tvp.Columns.Add('usage')
    _dt_tvp.Columns.Add('systeme')
    # Ordre : Temporaire=1, FM=2 toujours en tête, puis tri par 'ordre' config
    _TVP_LOCKED_ORDER = [u'Temporaire', u'FM']
    _TVP_LOCKED_ORDRE = {u'Temporaire': 1, u'FM': 2}
    def _tvp_sort_key(t):
        _lbl = t.get(u'label', u'')
        if _lbl in _TVP_LOCKED_ORDRE:
            return _TVP_LOCKED_ORDRE[_lbl]
        return t.get(u'ordre', 999)
    _tvp_auto_ord = [3]  # prochain ordre disponible pour les lignes utilisateur
    for _tvp in sorted(_get_tvp(cfg), key=_tvp_sort_key):
        _r = _dt_tvp.NewRow()
        _lbl_tvp = _tvp.get('label', '')
        _ord_tvp = _TVP_LOCKED_ORDRE.get(_lbl_tvp, _tvp.get('ordre', None))
        if _ord_tvp is None:
            _ord_tvp = _tvp_auto_ord[0]
        _tvp_auto_ord[0] = max(_tvp_auto_ord[0], int(_ord_tvp)) + 1
        _r['ordre']    = int(_ord_tvp)
        _r['label']    = _lbl_tvp
        _r['titre']    = _tvp.get('titre',    _tvp.get('nom', ''))  # compat
        _r['valeur_1'] = _tvp.get('valeur_1', '')
        _r['valeur_2'] = _tvp.get('valeur_2', '')
        _r['usage']    = _tvp.get('usage',    'Temporaire')
        _r['systeme']  = bool(_tvp.get('systeme', False))
        _dt_tvp.Rows.Add(_r)
    _dt_tvp.DefaultView.Sort = 'ordre ASC'
    wpf.dgTypesVues.ItemsSource = _dt_tvp.DefaultView

    # Dicts disponibilite types personnalises
    # _dispo_types_pers    : True = disponible dans "Lier CAO → Vues"
    # _dispo_types_pers_vp : True = disponible dans "Vues +"
    _dispo_types_pers    = {}
    _dispo_types_pers_vp = {}
    for _d in cfg.get(u'dispo_types_pers_lier_cao', []):
        _lbl_d = _d.get(u'label', u'')
        _dispo_types_pers[_lbl_d]    = bool(_d.get(u'lier_cao',  True))
        _dispo_types_pers_vp[_lbl_d] = bool(_d.get(u'vues_plus', True))

    _LOCKED_TVP_LABELS = {u'Temporaire', u'FM'}

    def _is_sys_tvp(item):
        return hasattr(item, 'Row') and str(item['label'] or u'') in _LOCKED_TVP_LABELS

    def _on_beginning_edit_tvp(s, e):
        # Ord.(0) et Label(1) et Usage(5) non éditables pour les lignes système
        # Colonnes : 0=Ord. 1=Label 2=Titre 3=Valeur-1 4=Valeur-2 5=Usage 6=Types 7=Gabarits
        if _is_sys_tvp(e.Row.Item) and e.Column.DisplayIndex in (0, 1, 5):
            e.Cancel = True

    def _on_preview_key_down_tvp(s, e):
        if e.Key == Key.Delete and _is_sys_tvp(wpf.dgTypesVues.SelectedItem):
            e.Handled = True

    wpf.dgTypesVues.BeginningEdit  += _on_beginning_edit_tvp
    wpf.dgTypesVues.PreviewKeyDown += _on_preview_key_down_tvp

    # ── Menu contextuel Vues personnalisées ───────────────────────────────────
    # Stocker l'item visé par le clic droit (SelectedItem peut ne pas être à jour au moment Opened)
    from System.Windows.Media import VisualTreeHelper as _VTH
    _tvp_ctx_item = [None]

    def _tvp_right_click(sender, e):
        _obj = e.OriginalSource
        while _obj is not None:
            _dc = getattr(_obj, 'DataContext', None)
            if _dc is not None and hasattr(_dc, 'Row'):
                _tvp_ctx_item[0] = _dc
                wpf.dgTypesVues.SelectedItem = _dc
                return
            try:
                _obj = _VTH.GetParent(_obj)
            except Exception:
                break
        _tvp_ctx_item[0] = None

    wpf.dgTypesVues.PreviewMouseRightButtonDown += _tvp_right_click

    _ctx_tvp       = wpf.dgTypesVues.ContextMenu
    _ctx_nouvelle  = _ctx_tvp.Items[0]
    _ctx_dupliquer = _ctx_tvp.Items[1]
    # Items[2] = Separator
    _ctx_supprimer = _ctx_tvp.Items[3]

    def _tvp_ctx_opened(sender, e):
        _sel     = _tvp_ctx_item[0]
        _has_sel = _sel is not None and hasattr(_sel, 'Row')
        _is_sys  = _has_sel and _is_sys_tvp(_sel)
        _ctx_dupliquer.IsEnabled = _has_sel
        _ctx_supprimer.IsEnabled = _has_sel and not _is_sys

    _ctx_tvp.Opened += _tvp_ctx_opened

    def _tvp_next_ordre():
        _vals = [int(_row['ordre']) for _row in _dt_tvp.Rows
                 if _row['ordre'] is not None]
        return (max(_vals) + 1) if _vals else 3

    def _tvp_nouvelle(sender, e):
        _r = _dt_tvp.NewRow()
        _r['ordre']    = _tvp_next_ordre()
        _r['label']    = u''
        _r['titre']    = u''
        _r['valeur_1'] = u''
        _r['valeur_2'] = u''
        _r['usage']    = u'Temporaire'
        _r['systeme']  = False
        _dt_tvp.Rows.Add(_r)

    def _tvp_dupliquer(sender, e):
        _sel = _tvp_ctx_item[0]
        if _sel is None or not hasattr(_sel, 'Row'):
            return
        _base     = str(_sel['label']) if _sel['label'] is not None else u''
        _existing = {str(_row['label']) for _row in _dt_tvp.DefaultView
                     if _row['label'] is not None}
        _idx = 2
        while True:
            _new_lbl = u'{}_{}'.format(_base, _idx)
            if _new_lbl not in _existing:
                break
            _idx += 1
        _r = _dt_tvp.NewRow()
        _r['ordre']    = _tvp_next_ordre()
        _r['label']    = _new_lbl
        _r['titre']    = str(_sel['titre'])    if _sel['titre']    is not None else u''
        _r['valeur_1'] = str(_sel['valeur_1']) if _sel['valeur_1'] is not None else u''
        _r['valeur_2'] = str(_sel['valeur_2']) if _sel['valeur_2'] is not None else u''
        _r['usage']    = str(_sel['usage'])    if _sel['usage']    is not None else u'Temporaire'
        _r['systeme']  = False
        _dt_tvp.Rows.Add(_r)

    def _tvp_supprimer(sender, e):
        _sel = _tvp_ctx_item[0]
        if _sel is None or not hasattr(_sel, 'Row'):
            return
        if _is_sys_tvp(_sel):
            return
        _sel.Row.Delete()

    _ctx_nouvelle.Click  += _tvp_nouvelle
    _ctx_dupliquer.Click += _tvp_dupliquer
    _ctx_supprimer.Click += _tvp_supprimer

    # ── Stockage en mémoire : Types de vues et Gabarits ──────────────────────
    # Clé : label → dict {vue_id: valeur}
    _types_vues_store   = {}
    for _tv in cfg.get('types_vues', []):
        _types_vues_store[_tv.get('label', '')] = dict(_tv.get('types', {}))

    _gabarits_store = {}
    for _gab in cfg.get('gabarits_vues', []):
        _gabarits_store[_gab.get('label', '')] = dict(_gab.get('gabarits', {}))

    # ── Helpers communs aux deux dialogues dynamiques ─────────────────────────
    def _get_vue_noms_from_grid():
        """Lit la liste (label, vue_id, col_key) depuis dgNommageVues."""
        _result = []
        for _r in wpf.dgNommageVues.ItemsSource:
            _lbl_v = str(_r['label']) if _r['label'] is not None else ''
            _vid_v = str(_r['id'])    if _r['id']    is not None else ''
            if _lbl_v or _vid_v:
                _key_v = 'col_' + _vid_v.replace('-', '_').replace(' ', '_')
                _result.append((_lbl_v, _vid_v, _key_v))
        return _result

    from System.Windows.Controls import DataGridTextColumn as _DGTxtCol
    from System.Windows.Controls import DataGridLength      as _DGLen
    from System.Windows.Controls import DataGridLengthUnitType as _DGLenUnit
    from System.Windows.Data      import Binding            as _DGBind
    import clr as _clr_dlg
    _clr_dlg.AddReference('System.Data')
    from System.Data import DataTable as _DT_dlg

    def _open_dynamic_dialog(xaml_name, dg_name, store, tvp_label,
                             title, description):
        """
        Ouvre une boite de dialogue avec un DataGrid à colonnes dynamiques
        (une colonne par entrée de 'Nommage des vues').

        xaml_name   : nom du fichier XAML (ex. 'GabaritsDialog.xaml')
        dg_name     : nom du contrôle DataGrid dans le XAML (ex. 'dgGabarits')
        store       : dict mutable {label: {vue_id: valeur}}
        tvp_label   : label de la ligne sélectionnée
        title       : titre de la fenêtre
        description : texte d'aide affiché en haut (ignoré si le XAML n'a pas
                      de TextBlock dédié — on force le titre à la place)
        """
        _vue_noms = _get_vue_noms_from_grid()
        if not _vue_noms:
            forms.alert(
                u"Aucun type de nommage de vue défini dans la table 'Nommage des vues'.",
                title=title
            )
            return

        _cur = dict(store.get(tvp_label, {}))

        _xaml = os.path.join(os.path.dirname(__file__), xaml_name)
        _dlg  = forms.WPFWindow(_xaml)
        _dlg.Title = u"{} — {}".format(title, tvp_label)

        # DataTable dynamique
        _dt = _DT_dlg()
        _dt.Columns.Add('_label_')
        for _lv, _iv, _kv in _vue_noms:
            _dt.Columns.Add(_kv)

        _row_d = _dt.NewRow()
        _row_d['_label_'] = tvp_label
        for _lv, _iv, _kv in _vue_noms:
            _row_d[_kv] = _cur.get(_iv, '')
        _dt.Rows.Add(_row_d)

        # Colonnes programmatiques
        _dg = getattr(_dlg, dg_name)
        _c_lbl          = _DGTxtCol()
        _c_lbl.Header   = u'Label'
        _c_lbl.Binding  = _DGBind('_label_')
        _c_lbl.IsReadOnly = True
        _c_lbl.Width    = _DGLen(110)
        _dg.Columns.Add(_c_lbl)
        for _lv, _iv, _kv in _vue_noms:
            _c         = _DGTxtCol()
            _c.Header  = _lv
            _c.Binding = _DGBind(_kv)
            _c.Width   = _DGLen(1, _DGLenUnit.Star)
            _dg.Columns.Add(_c)

        _dg.ItemsSource = _dt.DefaultView

        _dlg.btnCancel.Click += lambda s, e: setattr(_dlg, 'DialogResult', False)
        _dlg.btnOK.Click     += lambda s, e: setattr(_dlg, 'DialogResult', True)

        if not _dlg.show_dialog():
            return

        # Relire et mettre à jour le store
        _dv_row  = _dg.ItemsSource[0]
        _new_val = {}
        for _lv, _iv, _kv in _vue_noms:
            _val = _dv_row[_kv]
            _new_val[_iv] = str(_val).strip() if _val is not None else ''
        store[tvp_label] = _new_val

    def _on_tvp_button_click(sender, e):
        """
        Handler de clic bubble depuis les boutons du DataGrid 'Vues personnalisées'.
        Dispatche selon le Tag du bouton : 'types' ou 'gabarits'.
        """
        _el = e.OriginalSource
        while _el is not None:
            if isinstance(_el, _WpfButton):
                break
            _el = getattr(_el, 'Parent', None)
        if _el is None or not isinstance(_el, _WpfButton):
            return
        _row_item = _el.DataContext
        if not hasattr(_row_item, 'Row'):
            return
        _tvp_label = str(_row_item['label']) if _row_item['label'] is not None else ''
        if not _tvp_label:
            return

        _tag = str(_el.Tag) if _el.Tag is not None else ''
        if _tag == 'types':
            _open_dynamic_dialog(
                'TypesVuesDialog.xaml', 'dgTypesVues',
                _types_vues_store, _tvp_label,
                u'Types de vues',
                u"Renseignez le nom exact du type de vue Revit à appliquer pour chaque type de nommage.",
            )
        elif _tag == 'gabarits':
            _open_dynamic_dialog(
                'GabaritsDialog.xaml', 'dgGabarits',
                _gabarits_store, _tvp_label,
                u'Gabarits de vues',
                u"Renseignez le nom exact du gabarit de vue Revit à appliquer pour chaque type de vue.",
            )
        e.Handled = True

    wpf.dgTypesVues.AddHandler(ButtonBase.ClickEvent, RoutedEventHandler(_on_tvp_button_click))

    _dt_vue_nm = SysDataTable()
    _dt_vue_nm.Columns.Add('label')
    _dt_vue_nm.Columns.Add('id')
    _dt_vue_nm.Columns.Add('template')
    _dt_vue_nm.Columns.Add('vues_et_dwg', _SysBool)
    _dt_vue_nm.Columns.Add('vues_plus',   _SysBool)
    _defaut_nommage_vues = [
        {'label': u"Plan d'\xe9tage",           'id': u'vue-plan',       'template': u'{vue-pers-titre} - {niveau}',                              'vues_et_dwg': True,  'vues_plus': True},
        {'label': u"Plan de faux plafond",      'id': u'vue-plaf',       'template': u'{vue-pers-titre} - {niveau}',                              'vues_et_dwg': True,  'vues_plus': True},
        {'label': u"Vue en plan (Structure)",   'id': u'vue-structure',  'template': u'{vue-pers-titre} - {niveau}',                              'vues_et_dwg': True,  'vues_plus': True},
        {'label': u"Plan de surface",           'id': u'vue-surface',    'template': u'{vue-pers-titre} - {niveau}',                              'vues_et_dwg': False, 'vues_plus': False},
        {'label': u"Coupe",                     'id': u'vue-coupe',      'template': u'{vue-pers-titre} - COUPE',                                 'vues_et_dwg': False, 'vues_plus': False},
        {'label': u"\xc9l\xe9vation",           'id': u'vue-elevation',  'template': u'{vue-pers-titre} - ELEVATION',                             'vues_et_dwg': False, 'vues_plus': False},
        {'label': u"Vue 3D",                    'id': u'vue-3d',         'template': u'{vue-pers-titre} - 3D',                                    'vues_et_dwg': False, 'vues_plus': False},
        {'label': u"Vue de dessin",             'id': u'vue-dessin',     'template': u'{vue-pers-titre} - {vue-pers-valeur-1} - {vue-pers-valeur-2}', 'vues_et_dwg': True,  'vues_plus': True},
        {'label': u"L\xe9gende",               'id': u'vue-legende',    'template': u'{vue-pers-titre} - {vue-pers-valeur-1} - {vue-pers-valeur-2}', 'vues_et_dwg': True,  'vues_plus': True},
    ]
    for _v in (cnv.get('nommage_vues') or _defaut_nommage_vues):
        _rv = _dt_vue_nm.NewRow()
        _rv['label']      = _v.get('label', _v.get('famille', ''))
        _rv['id']         = _v.get('id', '')
        _rv['template']   = _v.get('template', '')
        _rv['vues_et_dwg'] = bool(_v.get('vues_et_dwg', False))
        _rv['vues_plus']   = bool(_v.get('vues_plus',   _v.get('vues_et_dwg', False)))
        _dt_vue_nm.Rows.Add(_rv)
    wpf.dgNommageVues.ItemsSource = _dt_vue_nm.DefaultView

    # ── Bouton Disponibilite Vues + DWG ───────────────────────────────────────
    def _open_vues_et_dwg_dispo(sender, args):
        _dlg_xaml = os.path.join(os.path.dirname(__file__), 'VuesEtDWGDispoDialog.xaml')
        _dlg = forms.WPFWindow(_dlg_xaml)
        _dlg.Title = u"Disponibilit\xe9s familles de vues"
        from System.Data import DataTable as _DT_dispo
        from System import Boolean as _SysBoolDlg
        _dt_dispo = _DT_dispo()
        _dt_dispo.Columns.Add('label')
        _dt_dispo.Columns.Add('vues_et_dwg', _SysBoolDlg)
        _dt_dispo.Columns.Add('vues_plus',   _SysBoolDlg)
        for _r in _dt_vue_nm.Rows:
            _dr = _dt_dispo.NewRow()
            _dr['label']      = str(_r['label']) if _r['label'] is not None else u''
            _dr['vues_et_dwg'] = bool(_r['vues_et_dwg']) if _r['vues_et_dwg'] is not None else False
            _dr['vues_plus']   = bool(_r['vues_plus'])   if _r['vues_plus']   is not None else False
            _dt_dispo.Rows.Add(_dr)
        _dlg.dgDispo.ItemsSource = _dt_dispo.DefaultView
        _dlg.btnOk.Click     += lambda s, e: setattr(_dlg, 'DialogResult', True)
        _dlg.btnCancel.Click += lambda s, e: setattr(_dlg, 'DialogResult', False)
        if _dlg.show_dialog():
            _dispo_rows = list(_dt_dispo.Rows)
            _nm_rows    = list(_dt_vue_nm.Rows)
            for _i, _dr in enumerate(_dispo_rows):
                if _i < len(_nm_rows):
                    _nm_rows[_i]['vues_et_dwg'] = bool(_dr['vues_et_dwg'])
                    _nm_rows[_i]['vues_plus']   = bool(_dr['vues_plus'])

    wpf.btnNommageVuesDispo.Click += _open_vues_et_dwg_dispo

    # ── Bouton Disponibilite Types personnalises → Lier CAO ───────────────────
    def _open_types_pers_dispo(sender, args):
        _dlg_xaml = os.path.join(os.path.dirname(__file__), 'TypesPersDispoDialog.xaml')
        _dlg = forms.WPFWindow(_dlg_xaml)
        _dlg.Title = u"Disponibilit\xe9s vues personnalis\xe9es"
        from System.Data import DataTable as _DT_tpd
        from System import Boolean as _SysBoolTpd
        _dt_tpd = _DT_tpd()
        _dt_tpd.Columns.Add('label')
        _dt_tpd.Columns.Add('lier_cao',  _SysBoolTpd)
        _dt_tpd.Columns.Add('vues_plus', _SysBoolTpd)
        for _r in _dt_tvp.Rows:
            _lbl_tpd = str(_r['label']) if _r['label'] is not None else u''
            if not _lbl_tpd:
                continue
            _dr = _dt_tpd.NewRow()
            _dr['label']     = _lbl_tpd
            _dr['lier_cao']  = _dispo_types_pers.get(_lbl_tpd,    True)
            _dr['vues_plus'] = _dispo_types_pers_vp.get(_lbl_tpd, True)
            _dt_tpd.Rows.Add(_dr)
        _dlg.dgDispo.ItemsSource = _dt_tpd.DefaultView
        _dlg.btnOk.Click     += lambda s, e: setattr(_dlg, 'DialogResult', True)
        _dlg.btnCancel.Click += lambda s, e: setattr(_dlg, 'DialogResult', False)
        if _dlg.show_dialog():
            for _dr in _dt_tpd.Rows:
                _lbl_tpd = str(_dr['label']) if _dr['label'] is not None else u''
                if _lbl_tpd:
                    _dispo_types_pers[_lbl_tpd]    = bool(_dr['lier_cao'])
                    _dispo_types_pers_vp[_lbl_tpd] = bool(_dr['vues_plus'])

    wpf.btnTypesPersDispo.Click += _open_types_pers_dispo

    # ── Nommage niveaux (code) ────────────────────────────────────────────────
    _dt_niv_code_nm = SysDataTable()
    _dt_niv_code_nm.Columns.Add('label')
    _dt_niv_code_nm.Columns.Add('id')
    _dt_niv_code_nm.Columns.Add('template')
    _defaut_nommage_niveaux_code = [
        {'label': 'Niveau (code)', 'id': 'niveau',
         'template': '{pref-niv}{sens-niv}{num-niv}'},
    ]
    for _nc2 in (cnv.get('nommage_niveaux_code') or _defaut_nommage_niveaux_code):
        _rnc = _dt_niv_code_nm.NewRow()
        _rnc['label']    = _nc2.get('label', '')
        _rnc['id']       = _nc2.get('id', '')
        _rnc['template'] = _nc2.get('template', '')
        _dt_niv_code_nm.Rows.Add(_rnc)
    wpf.dgNommageNiveauxCode.ItemsSource = _dt_niv_code_nm.DefaultView

    # ── Nommage niveaux Revit ──────────────────────────────────────────────────
    _dt_niv_nm = SysDataTable()
    _dt_niv_nm.Columns.Add('label')
    _dt_niv_nm.Columns.Add('id')
    _dt_niv_nm.Columns.Add('template')
    _defaut_nommage_niveaux = [
        {'label': 'Niveaux Revit', 'id': 'niveaux-revit',
         'template': '{construction}_{niveau}_{demi-niv}'},
    ]
    for _n in (cnv.get('nommage_niveaux') or _defaut_nommage_niveaux):
        _rn = _dt_niv_nm.NewRow()
        _rn['label']    = _n.get('label', '')
        _rn['id']       = _n.get('id', '')
        _rn['template'] = _n.get('template', '')
        _dt_niv_nm.Rows.Add(_rn)
    wpf.dgNommageNiveaux.ItemsSource = _dt_niv_nm.DefaultView

    # ── Nommage présentations ──────────────────────────────────────────────────
    _dt_present_nm = SysDataTable()
    _dt_present_nm.Columns.Add('label')
    _dt_present_nm.Columns.Add('id')
    _dt_present_nm.Columns.Add('template')
    _defaut_nommage_present = [
        {'label': u'Pr\xe9sentation', 'id': 'present-plan',
         'template': u'{construction} - {specialite} - {niveau}'},
    ]
    for _p in (cnv.get('nommage_presentations') or _defaut_nommage_present):
        _rp = _dt_present_nm.NewRow()
        _rp['label']    = _p.get('label', '')
        _rp['id']       = _p.get('id', '')
        _rp['template'] = _p.get('template', '')
        _dt_present_nm.Rows.Add(_rp)
    wpf.dgNommagePresent.ItemsSource = _dt_present_nm.DefaultView

    # ── Nommage exports ────────────────────────────────────────────────────────

    # ── Vues en masse : filtres types niveaux par defaut ──────────────────────
    # Construire les labels dynamiques depuis les prefixes
    pfx_by_def = {}
    for _p in cn.get('prefixes', []):
        _defn = _p.get('definition', '')
        _pfx  = _p.get('prefixe', '')
        if _defn:
            if _defn not in pfx_by_def:
                pfx_by_def[_defn] = []
            pfx_by_def[_defn].append(_pfx)

    def _label_def(defn_key):
        pfxs = pfx_by_def.get(defn_key, [])
        if pfxs:
            return u"{} - {}".format(defn_key, u", ".join(pfxs))
        return defn_key

    wpf.vm_batiment.Content  = _label_def(u'Batiment')
    wpf.vm_toiture.Content   = _label_def(u'Toiture')
    wpf.vm_fondations.Content = _label_def(u'Fondations')
    wpf.vm_origine.Content   = _label_def(u'Origine')
    # "Autres" : label fixe

    set_chk(wpf, 'vm_batiment',   vm_filtres.get('batiment',   True))
    set_chk(wpf, 'vm_toiture',    vm_filtres.get('toiture',    False))
    set_chk(wpf, 'vm_fondations', vm_filtres.get('fondations', False))
    set_chk(wpf, 'vm_origine',    vm_filtres.get('origine',    False))
    set_chk(wpf, 'vm_autres',     vm_filtres.get('autres',     False))

    # ── Liaisons DWG ─────────────────────────────────────────────────────────
    set_chk(wpf, 'dwg_include_sub',   dwg.get('include_sub', False))
    set_txt(wpf, 'dwg_layers',        dwg.get('layers_default', ''))
    set_txt(wpf, 'dwg_color_mode',    dwg.get('color_mode_default', ''))
    set_txt(wpf, 'dwg_unit',          dwg.get('unit_default', ''))
    set_txt(wpf, 'dwg_placement',     dwg.get('placement_default', ''))
    set_chk(wpf, 'dwg_correct_lines', dwg.get('correct_lines', True))
    set_chk(wpf, 'dwg_view_only',     dwg.get('view_only', True))

    # ── Profils Liaison CAO ────────────────────────────────────────────────────
    _dt_profils = SysDataTable()
    _dt_profils.Columns.Add(u'ordre',   _SysInt)
    _dt_profils.Columns.Add(u'label')
    _dt_profils.Columns.Add(u'systeme')

    # Store en mémoire : label → {'options_liaisons': {...}, 'vues': {...}}
    _profils_store = {}
    # Tri : < Par défaut > (ordre=1) toujours en premier, puis par ordre config
    def _profil_sort_key(p):
        if p.get(u'label') == _LOCKED_PROFIL_LABEL: return 1
        return p.get(u'ordre', 999)
    _profils_sorted = sorted(_profils_raw, key=_profil_sort_key)
    _profil_auto_ord = [2]
    for _p in _profils_sorted:
        _lbl_p = _p.get(u'label', u'')
        _sys_p = (_lbl_p == _LOCKED_PROFIL_LABEL)
        _ord_p = 1 if _sys_p else _p.get(u'ordre', None)
        if _ord_p is None:
            _ord_p = _profil_auto_ord[0]
        if not _sys_p:
            _profil_auto_ord[0] = max(_profil_auto_ord[0], int(_ord_p)) + 1
        _r = _dt_profils.NewRow()
        _r[u'ordre']   = int(_ord_p)
        _r[u'label']   = _lbl_p
        _r[u'systeme'] = _sys_p
        _profils_store[_lbl_p] = {
            u'options_liaisons': dict(_p.get(u'options_liaisons', _DEFAULT_PROFIL_OPTIONS)),
            u'vues':             dict(_p.get(u'vues',             _DEFAULT_PROFIL_VUES)),
        }
        _dt_profils.Rows.Add(_r)
    _dt_profils.DefaultView.Sort = u'ordre ASC'
    wpf.dgProfilsLiaison.ItemsSource = _dt_profils.DefaultView

    def _is_sys_profil(item):
        return hasattr(item, u'Row') and str(item[u'label'] or u'') == _LOCKED_PROFIL_LABEL

    def _on_beginning_edit_profil(s, e):
        if _is_sys_profil(e.Row.Item):
            e.Cancel = True

    wpf.dgProfilsLiaison.BeginningEdit += _on_beginning_edit_profil

    # Clic droit → sélection de la ligne
    _profil_ctx_item = [None]

    def _profil_right_click(sender, e):
        _obj = e.OriginalSource
        while _obj is not None:
            _dc = getattr(_obj, u'DataContext', None)
            if _dc is not None and hasattr(_dc, u'Row'):
                _profil_ctx_item[0] = _dc
                wpf.dgProfilsLiaison.SelectedItem = _dc
                return
            try:
                _obj = _VTH.GetParent(_obj)
            except Exception:
                break
        _profil_ctx_item[0] = None

    wpf.dgProfilsLiaison.PreviewMouseRightButtonDown += _profil_right_click

    _ctx_profil    = wpf.dgProfilsLiaison.ContextMenu
    _ctx_p_nouveau = _ctx_profil.Items[0]
    _ctx_p_dupliquer = _ctx_profil.Items[1]
    # Items[2] = Separator
    _ctx_p_supprimer = _ctx_profil.Items[3]

    def _profil_ctx_opened(sender, e):
        _sel     = _profil_ctx_item[0]
        _has_sel = _sel is not None and hasattr(_sel, u'Row')
        _is_sys  = _has_sel and _is_sys_profil(_sel)
        _ctx_p_dupliquer.IsEnabled = _has_sel
        _ctx_p_supprimer.IsEnabled = _has_sel and not _is_sys

    _ctx_profil.Opened += _profil_ctx_opened

    def _profil_next_ordre():
        _vals = [int(_row[u'ordre']) for _row in _dt_profils.Rows
                 if _row[u'ordre'] is not None]
        return (max(_vals) + 1) if _vals else 2

    def _profil_nouveau(sender, e):
        _new_lbl = u'Nouveau profil'
        _existing = {str(_row[u'label']) for _row in _dt_profils.DefaultView
                     if _row[u'label'] is not None}
        _idx = 2
        _candidate = _new_lbl
        while _candidate in _existing:
            _candidate = u'{}_{}'.format(_new_lbl, _idx)
            _idx += 1
        _r = _dt_profils.NewRow()
        _r[u'ordre']   = _profil_next_ordre()
        _r[u'label']   = _candidate
        _r[u'systeme'] = False
        _dt_profils.Rows.Add(_r)
        _profils_store[_candidate] = {
            u'options_liaisons': dict(_DEFAULT_PROFIL_OPTIONS),
            u'vues':             dict(_DEFAULT_PROFIL_VUES),
        }

    def _profil_dupliquer(sender, e):
        _sel = _profil_ctx_item[0]
        if _sel is None or not hasattr(_sel, u'Row'):
            return
        _base = str(_sel[u'label']) if _sel[u'label'] is not None else u''
        _existing = {str(_row[u'label']) for _row in _dt_profils.DefaultView
                     if _row[u'label'] is not None}
        _idx = 2
        while True:
            _new_lbl = u'{}_{}'.format(_base, _idx)
            if _new_lbl not in _existing:
                break
            _idx += 1
        _r = _dt_profils.NewRow()
        _r[u'ordre']   = _profil_next_ordre()
        _r[u'label']   = _new_lbl
        _r[u'systeme'] = False
        _dt_profils.Rows.Add(_r)
        _src = _profils_store.get(_base, {})
        _profils_store[_new_lbl] = {
            u'options_liaisons': dict(_src.get(u'options_liaisons', _DEFAULT_PROFIL_OPTIONS)),
            u'vues':             dict(_src.get(u'vues',             _DEFAULT_PROFIL_VUES)),
        }

    def _profil_supprimer(sender, e):
        _sel = _profil_ctx_item[0]
        if _sel is None or not hasattr(_sel, u'Row'):
            return
        if _is_sys_profil(_sel):
            return
        _lbl = str(_sel[u'label']) if _sel[u'label'] is not None else u''
        _sel.Row.Delete()
        _profils_store.pop(_lbl, None)

    _ctx_p_nouveau.Click   += _profil_nouveau
    _ctx_p_dupliquer.Click += _profil_dupliquer
    _ctx_p_supprimer.Click += _profil_supprimer

    # Boutons Configurer… dans les cellules du DataGrid
    def _on_profil_button_click(sender, e):
        _el = e.OriginalSource
        while _el is not None:
            if isinstance(_el, _WpfButton):
                break
            _el = getattr(_el, u'Parent', None)
        if _el is None or not isinstance(_el, _WpfButton):
            return
        _row_item = _el.DataContext
        if not hasattr(_row_item, u'Row'):
            return
        _lbl_p = str(_row_item[u'label']) if _row_item[u'label'] is not None else u''
        if not _lbl_p:
            return
        _tag = str(_el.Tag) if _el.Tag is not None else u''
        _store_p = _profils_store.setdefault(_lbl_p, {
            u'options_liaisons': dict(_DEFAULT_PROFIL_OPTIONS),
            u'vues':             dict(_DEFAULT_PROFIL_VUES),
        })

        if _tag == u'options':
            _xaml_po = os.path.join(os.path.dirname(__file__), u'ProfileOptionsDialog.xaml')
            _dlg_po  = forms.WPFWindow(_xaml_po)
            _dlg_po.Title = u'Options de liaisons — {}'.format(_lbl_p)
            _opts = _store_p.get(u'options_liaisons', _DEFAULT_PROFIL_OPTIONS)
            # Pré-remplir les combos
            _color_map = {u'Conserver': 0, u'Inverser': 1, u'Noir et blanc': 2}
            _dlg_po.cmbColorMode.SelectedIndex = _color_map.get(_opts.get(u'color_mode', u'Conserver'), 0)
            _layer_map = {u'Tous': 0, u'Visibles': 1}
            _dlg_po.cmbLayers.SelectedIndex = _layer_map.get(_opts.get(u'layers', u'Tous'), 0)
            _unit_map = {u'Metres': 0, u'Centimetres': 1, u'Millimetres': 2, u'Automatique': 3}
            _dlg_po.cmbUnits.SelectedIndex = _unit_map.get(_opts.get(u'units', u'Metres'), 0)
            _place_map = {
                u'Automatique - Emplacement partage': 0,
                u'Automatique - Centre a centre': 1,
                u'Automatique - Origine vers origine interne': 2,
            }
            _dlg_po.cmbPlacement.SelectedIndex = _place_map.get(_opts.get(u'placement', u'Automatique - Emplacement partage'), 0)
            _dlg_po.chkCorrectLines.IsChecked = bool(_opts.get(u'correct_lines', True))
            _dlg_po.chkViewOnly.IsChecked     = bool(_opts.get(u'view_only', False))
            _dlg_po.btnOK.Click     += lambda s2, e2: setattr(_dlg_po, u'DialogResult', True)
            _dlg_po.btnCancel.Click += lambda s2, e2: setattr(_dlg_po, u'DialogResult', False)
            if _dlg_po.show_dialog():
                _color_rev = {0: u'Conserver', 1: u'Inverser', 2: u'Noir et blanc'}
                _layer_rev = {0: u'Tous', 1: u'Visibles'}
                _unit_rev  = {0: u'Metres', 1: u'Centimetres', 2: u'Millimetres', 3: u'Automatique'}
                _place_rev = {0: u'Automatique - Emplacement partage',
                              1: u'Automatique - Centre a centre',
                              2: u'Automatique - Origine vers origine interne'}
                _store_p[u'options_liaisons'] = {
                    u'color_mode':    _color_rev.get(_dlg_po.cmbColorMode.SelectedIndex, u'Conserver'),
                    u'layers':        _layer_rev.get(_dlg_po.cmbLayers.SelectedIndex, u'Tous'),
                    u'units':         _unit_rev.get(_dlg_po.cmbUnits.SelectedIndex, u'Metres'),
                    u'placement':     _place_rev.get(_dlg_po.cmbPlacement.SelectedIndex, u'Automatique - Emplacement partage'),
                    u'correct_lines': bool(_dlg_po.chkCorrectLines.IsChecked),
                    u'view_only':     bool(_dlg_po.chkViewOnly.IsChecked),
                }

        elif _tag == u'vues':
            _xaml_pv = os.path.join(os.path.dirname(__file__), u'ProfileVuesDialog.xaml')
            _dlg_pv  = forms.WPFWindow(_xaml_pv)
            _dlg_pv.Title = u'Options de vues — {}'.format(_lbl_p)
            _vues_p = _store_p.get(u'vues', _DEFAULT_PROFIL_VUES)
            _fam_map = {u"Plan d'etage": 0, u'Plans de faux-plafonds': 1,
                        u'Plan de structure': 2, u'Vue de dessin': 3}
            _dlg_pv.cmbFamille.SelectedIndex = _fam_map.get(_vues_p.get(u'famille', u"Plan d'etage"), 0)
            # Remplir cmbTypePerso avec les labels des vues personnalisées
            from utils.types_vues_personnalises import get_types_vues as _get_tvp2
            _tvp_labels2 = [t.get(u'label', u'') for t in _get_tvp2(cfg)]
            _dlg_pv.cmbTypePerso.ItemsSource = _tvp_labels2
            _tp_cur = _vues_p.get(u'type_personnalise', u'FM')
            _dlg_pv.cmbTypePerso.SelectedIndex = _tvp_labels2.index(_tp_cur) if _tp_cur in _tvp_labels2 else 0
            _dlg_pv.chkVueParNiveau.IsChecked = bool(_vues_p.get(u'vue_par_niveau', True))
            _dlg_pv.btnOK.Click     += lambda s2, e2: setattr(_dlg_pv, u'DialogResult', True)
            _dlg_pv.btnCancel.Click += lambda s2, e2: setattr(_dlg_pv, u'DialogResult', False)
            if _dlg_pv.show_dialog():
                _fam_rev = {0: u"Plan d'etage", 1: u'Plans de faux-plafonds',
                            2: u'Plan de structure', 3: u'Vue de dessin'}
                _sel_tp = _dlg_pv.cmbTypePerso.SelectedItem
                _store_p[u'vues'] = {
                    u'famille':          _fam_rev.get(_dlg_pv.cmbFamille.SelectedIndex, u"Plan d'etage"),
                    u'type_personnalise': str(_sel_tp) if _sel_tp is not None else u'FM',
                    u'vue_par_niveau':   bool(_dlg_pv.chkVueParNiveau.IsChecked),
                }
        e.Handled = True

    from System.Windows.Controls.Primitives import ButtonBase as _ButtonBase2
    wpf.dgProfilsLiaison.AddHandler(
        _ButtonBase2.ClickEvent, RoutedEventHandler(_on_profil_button_click))

    # ── Nettoyage ─────────────────────────────────────────────────────────────
    set_chk(wpf, 'net_dwg_imports', net.get('dwg_imports', True))
    set_chk(wpf, 'net_dwg_liens',   net.get('dwg_liens', False))
    set_chk(wpf, 'net_lignes',      net.get('lignes', True))
    set_chk(wpf, 'net_texts',       net.get('texts', True))
    set_chk(wpf, 'net_pieces',      net.get('pieces_espaces', True))
    set_chk(wpf, 'net_zones',       net.get('zones_pochages', True))

    # ── Couleurs Titres ───────────────────────────────────────────────────────
    set_color(wpf,'tc_styles_r','tc_styles_g','tc_styles_b', tc.get('tables_de_styles', [192,192,192]))
    set_color(wpf,'tc_types_r', 'tc_types_g', 'tc_types_b',  tc.get('saisies_types',   [232,113,134]))
    set_color(wpf,'tc_occur_r', 'tc_occur_g', 'tc_occur_b',  tc.get('saisies_occurrences', [255,255,151]))
    set_color(wpf,'tc_pres_r',  'tc_pres_g',  'tc_pres_b',   tc.get('nomenclatures_presentations', [241,141,0]))

    # ── Couleurs Colonnes ─────────────────────────────────────────────────────
    set_color(wpf,'cc_readonly_r','cc_readonly_g','cc_readonly_b', cc.get('colonnes_readonly', [192,192,192]))
    set_color(wpf,'cc_types_r',   'cc_types_g',   'cc_types_b',    cc.get('colonnes_types',   [232,113,134]))
    set_color(wpf,'cc_occur_r',   'cc_occur_g',   'cc_occur_b',    cc.get('colonnes_occurrences', [255,255,151]))

    # ── Emplacements ──────────────────────────────────────────────────────────
    set_txt(wpf, 'el_nb_rep_parents', enreg.get('nb_rep_parents_enregistrement_rvt', 1))

    # ── LOG ───────────────────────────────────────────────────────────────────
    set_chk(wpf, 'log_activer', cfg.get('activer_logs_scripts', True))

    # ── Mises à jour ──────────────────────────────────────────────────────────
    _maj_cfg = cfg.setdefault('mises_a_jour', {})
    set_txt(wpf, 'maj_source_url',
            _maj_cfg.get('source_url', 'https://github.com/data8bim/py-NM-BATII'))
    set_txt(wpf, 'maj_version_installee', _version_installee)
    import System.Threading
    set_txt(wpf, 'maj_version_dispo', u'Vérification en cours...')
    wpf.maj_version_dispo.Foreground = System.Windows.Media.Brushes.Gray

    # Vérification automatique de la version disponible (thread arrière-plan)
    _src_url = _maj_cfg.get('source_url', 'https://github.com/data8bim/py-NM-BATII').strip()
    _ver_inst = _version_installee

    def _check_version_bg():
        try:
            _maj_script = os.path.normpath(os.path.join(
                os.path.dirname(__file__),
                '..', '..', '02_Mises_a_jour.pushbutton', 'script.py'
            ))
            _ns = {'__file__': _maj_script, '__name__': '__exec__'}
            execfile(_maj_script, _ns)
            if _src_url.lower().startswith('http'):
                _v, _ = _ns['get_remote_version_github'](_src_url)
            else:
                _v, _ = _ns['get_remote_version_serveur'](_src_url)

            def _update():
                wpf.maj_version_dispo.Text = _v
                if _v != _ver_inst:
                    wpf.maj_version_dispo.Foreground = System.Windows.Media.SolidColorBrush(
                        System.Windows.Media.Color.FromRgb(0, 140, 0))
                else:
                    wpf.maj_version_dispo.Foreground = System.Windows.Media.Brushes.DarkGray
            wpf.Dispatcher.BeginInvoke(System.Action(_update))

        except Exception as _ex:
            def _update_err():
                wpf.maj_version_dispo.Text = u'Erreur de connexion'
                wpf.maj_version_dispo.Foreground = System.Windows.Media.Brushes.Crimson
            wpf.Dispatcher.BeginInvoke(System.Action(_update_err))

    _t = System.Threading.Thread(
        System.Threading.ThreadStart(_check_version_bg))
    _t.IsBackground = True
    _t.Start()

    # Bouton Vérifier / Installer une mise à jour
    def _on_lancer_maj(s, e):
        try:
            maj_script = os.path.normpath(os.path.join(
                os.path.dirname(__file__),
                '..', '..', '02_Mises_a_jour.pushbutton', 'script.py'
            ))
            if not os.path.isfile(maj_script):
                from pyrevit import forms as _f
                _f.alert(
                    u"Script de mise à jour introuvable :\n{0}".format(maj_script),
                    title=u"Erreur"
                )
                return
            _ns = {'__file__': maj_script, '__name__': '__exec__'}
            execfile(maj_script, _ns)
            _ns['main']()
        except Exception as _ex:
            import traceback
            from pyrevit import forms as _f
            _f.alert(
                u"Erreur lors du lancement de la mise à jour :\n\n{0}\n\n{1}".format(
                    str(_ex), traceback.format_exc()
                ),
                title=u"Erreur"
            )
    wpf.btnLancerMaj.Click += _on_lancer_maj

    # Liens cliquables onglet À propos
    import subprocess as _sp
    def _open_url(url):
        def _handler(s, e):
            _sp.Popen(['cmd', '/c', 'start', '', url])
        return _handler
    wpf.lien_depot.MouseLeftButtonUp   += _open_url('https://github.com/data8bim/py-NM-BATII')
    wpf.lien_pyrevit.MouseLeftButtonUp += _open_url('https://github.com/pyrevitlabs/pyRevit')
    wpf.lien_tabler.MouseLeftButtonUp  += _open_url('https://tabler.io/icons')

    # Boutons
    wpf.btnCancel.Click += lambda s, e: setattr(wpf, 'DialogResult', False)
    wpf.btnSave.Click   += lambda s, e: setattr(wpf, 'DialogResult', True)

    if not wpf.show_dialog():
        return

    # ── Lecture et sauvegarde ─────────────────────────────────────────────────

    # Surfaces
    cfg['surface'] = {
        'param_shon':               txt(wpf, 'sf_param_shon'),
        'param_shob':               txt(wpf, 'sf_param_shob'),
        'param_s_plancher':         txt(wpf, 'sf_param_s_plancher'),
        'col_shon':                 txt(wpf, 'sf_col_shon'),
        'col_shob':                 txt(wpf, 'sf_col_shob'),
        'col_plancher':             txt(wpf, 'sf_col_plancher'),
        'col_filter':               txt(wpf, 'sf_col_filter'),
        'default_shon_schedule':    txt(wpf, 'sf_default_shon'),
        'default_plancher_schedule':txt(wpf, 'sf_default_plancher'),
    }

    # Noms Niveaux
    try:    esp = float(txt(wpf, 'cn_espacement'))
    except: esp = 5.0
    try:    eleva_rdc = float(txt(wpf, 'cn_eleva_rdc'))
    except: eleva_rdc = 0.0
    try:    eleva_ori = float(txt(wpf, 'cn_eleva_origine'))
    except: eleva_ori = 0.0

    # Lecture du DataGrid des préfixes
    prefixes_out = []
    for _row in wpf.dgPrefixes.ItemsSource:
        _pfx = _row['prefixe']
        _def = _row['definition']
        _pos = _row['positif']
        _neg = _row['negatif']
        _sys = _row['systeme']
        if _pfx or _def:
            prefixes_out.append({
                'systeme':    bool(_sys) if _sys is not None else False,
                'prefixe':    str(_pfx) if _pfx is not None else '',
                'definition': str(_def) if _def is not None else '',
                'positif':    bool(_pos) if _pos is not None else False,
                'negatif':    bool(_neg) if _neg is not None else False,
            })

    sens_out = []
    for _row in wpf.dgSensNiveaux.ItemsSource:
        _sg = str(_row['signe'])      if _row['signe']      is not None else ''
        _df = str(_row['definition']) if _row['definition'] is not None else ''
        if _sg:
            sens_out.append({'signe': _sg, 'definition': _df})

    cfg['creer_niveaux'] = {
        'prefixes':          prefixes_out,
        'sens':              sens_out,
        'Eleva_Niv_Rdc':     eleva_rdc,
        'espacement_default':esp,
        'Eleva_Niv_Origine': eleva_ori,
    }

    # Noms Fichiers
    # Calculer les regex auto (pref-niv depuis dgPrefixes, sens-niv depuis dgSensNiveaux)
    _pfx_chars_save = [str(_row['prefixe']) for _row in wpf.dgPrefixes.ItemsSource
                       if _row['prefixe'] and str(_row['prefixe']).strip()]
    _pref_regex_save = _build_char_class(_pfx_chars_save) if _pfx_chars_save else r'[RTFO]'
    _sens_chars_save = [str(_row['signe']) for _row in wpf.dgSensNiveaux.ItemsSource
                        if _row['signe'] and str(_row['signe']).strip()]
    _sens_regex_save = _build_char_class(_sens_chars_save) if _sens_chars_save else r'[+\-]'

    groupes_out = []
    for _row in wpf.dgGroupes.ItemsSource:
        _lbl = str(_row['label'])    if _row['label']    is not None else ''
        _id  = str(_row['id'])       if _row['id']       is not None else ''
        _rgx = str(_row['regex'])    if _row['regex']    is not None else ''
        _sys = _row['systeme']
        _opt = _row['optionnel']
        if _id or _lbl:
            groupes_out.append({
                'systeme':  bool(_sys) if _sys is not None else False,
                'optionnel':bool(_opt) if _opt is not None else False,
                'label':    _lbl,
                'id':       _id,
                'regex':    _rgx,
            })
    # Injecter pref-niv et sens-niv (calculés automatiquement, hors table)
    _idx_construction = next((i for i, g in enumerate(groupes_out) if g['id'] == 'construction'), 1)
    groupes_out.insert(_idx_construction + 1, {
        'systeme': True, 'optionnel': False,
        'label': u'Pr\xe9fixe niveau', 'id': 'pref-niv', 'regex': _pref_regex_save,
    })
    groupes_out.insert(_idx_construction + 2, {
        'systeme': True, 'optionnel': False,
        'label': 'Sens niveau', 'id': 'sens-niv', 'regex': _sens_regex_save,
    })
    cfg['nm_convention_noms_fichiers'] = {
        'valeur_si_nul':    txt(wpf, 'nc_val_nul'),
        'valeur_si_bim_2d': txt(wpf, 'nc_val_bim2d'),
        'groupes':          groupes_out,
    }

    # Vues personnalisées
    tvp_out = []
    for _row in wpf.dgTypesVues.ItemsSource:
        _lbl  = str(_row['label'])    if _row['label']    is not None else ''
        _tit  = str(_row['titre'])    if _row['titre']    is not None else ''
        _val1 = str(_row['valeur_1']) if _row['valeur_1'] is not None else ''
        _val2 = str(_row['valeur_2']) if _row['valeur_2'] is not None else ''
        _usg  = str(_row['usage'])    if _row['usage']    is not None else 'Temporaire'
        _sys  = _row['systeme']
        _ord  = _row['ordre']
        if _lbl:
            tvp_out.append({
                'ordre':    int(_ord) if _ord is not None else 999,
                'label':    _lbl,
                'titre':    _tit,
                'valeur_1': _val1,
                'valeur_2': _val2,
                'usage':    _usg,
                'systeme':  bool(_sys) if _sys is not None else False,
            })
    cfg['types_vues_personnalises'] = tvp_out

    # Disponibilite types personnalises (Lier CAO → Vues + Vues +)
    dispo_tpd_out = []
    for _row in wpf.dgTypesVues.ItemsSource:
        _lbl = str(_row['label']) if _row['label'] is not None else ''
        if _lbl:
            dispo_tpd_out.append({
                'label':    _lbl,
                'lier_cao': _dispo_types_pers.get(_lbl, True),
                'vues_plus': _dispo_types_pers_vp.get(_lbl, True),
            })
    cfg['dispo_types_pers_lier_cao'] = dispo_tpd_out

    # Types de vues (par label × vue_id) : depuis le store mis à jour par les dialogues
    types_vues_out = []
    for _row in wpf.dgTypesVues.ItemsSource:
        _lbl = str(_row['label']) if _row['label'] is not None else ''
        if _lbl:
            types_vues_out.append({
                'label': _lbl,
                'types': _types_vues_store.get(_lbl, {}),
            })
    cfg['types_vues'] = types_vues_out

    # Gabarits de vues : depuis le store mis à jour par les dialogues
    gabarits_out = []
    for _row in wpf.dgTypesVues.ItemsSource:
        _lbl = str(_row['label']) if _row['label'] is not None else ''
        if _lbl:
            gabarits_out.append({
                'label':    _lbl,
                'gabarits': _gabarits_store.get(_lbl, {}),
            })
    cfg['gabarits_vues'] = gabarits_out

    # Conventions de nommage
    templates_out = []
    for _row in wpf.dgTemplates.ItemsSource:
        _tlbl = str(_row['label'])    if _row['label']    is not None else ''
        _tid  = str(_row['id'])       if _row['id']       is not None else ''
        _ttpl = str(_row['template']) if _row['template'] is not None else ''
        _tsys = _row['systeme']
        if _tid or _tlbl:
            templates_out.append({
                'systeme':  bool(_tsys) if _tsys is not None else False,
                'label':    _tlbl,
                'id':       _tid,
                'template': _ttpl,
            })
    nommage_vues_out = []
    for _row in wpf.dgNommageVues.ItemsSource:
        _lbl = str(_row['label'])    if _row['label']    is not None else ''
        _id  = str(_row['id'])       if _row['id']       is not None else ''
        _tpl = str(_row['template']) if _row['template'] is not None else ''
        _ved = bool(_row['vues_et_dwg']) if _row['vues_et_dwg'] is not None else False
        _vp  = bool(_row['vues_plus'])   if _row['vues_plus']   is not None else False
        if _lbl or _id:
            nommage_vues_out.append({
                'label': _lbl, 'id': _id, 'template': _tpl,
                'vues_et_dwg': _ved, 'vues_plus': _vp,
            })
    nommage_present_out = []
    for _row in wpf.dgNommagePresent.ItemsSource:
        _lbl = str(_row['label'])    if _row['label']    is not None else ''
        _id  = str(_row['id'])       if _row['id']       is not None else ''
        _tpl = str(_row['template']) if _row['template'] is not None else ''
        if _lbl or _id:
            nommage_present_out.append({'label': _lbl, 'id': _id, 'template': _tpl})
    nommage_niveaux_code_out = []
    for _row in wpf.dgNommageNiveauxCode.ItemsSource:
        _lbl = str(_row['label'])    if _row['label']    is not None else ''
        _id  = str(_row['id'])       if _row['id']       is not None else ''
        _tpl = str(_row['template']) if _row['template'] is not None else ''
        if _lbl or _id:
            nommage_niveaux_code_out.append({'label': _lbl, 'id': _id, 'template': _tpl})
    nommage_niveaux_out = []
    for _row in wpf.dgNommageNiveaux.ItemsSource:
        _lbl = str(_row['label'])    if _row['label']    is not None else ''
        _id  = str(_row['id'])       if _row['id']       is not None else ''
        _tpl = str(_row['template']) if _row['template'] is not None else ''
        if _lbl or _id:
            nommage_niveaux_out.append({'label': _lbl, 'id': _id, 'template': _tpl})
    cfg['conventions_nommage'] = {
        'templates':             templates_out,
        'nommage_niveaux_code':  nommage_niveaux_code_out,
        'nommage_niveaux':       nommage_niveaux_out,
        'nommage_vues':          nommage_vues_out,
        'nommage_presentations': nommage_present_out,
    }

    # Vues en masse : filtres types niveaux par defaut
    cfg.setdefault('vues_en_masse', {})['filtres_types_niveaux_defaut'] = {
        'batiment':   chk(wpf, 'vm_batiment'),
        'toiture':    chk(wpf, 'vm_toiture'),
        'fondations': chk(wpf, 'vm_fondations'),
        'origine':    chk(wpf, 'vm_origine'),
        'autres':     chk(wpf, 'vm_autres'),
    }

    # Liaisons DWG
    cfg['fichiers_lies_dwg'] = {
        'include_sub':       chk(wpf, 'dwg_include_sub'),
        'layers_default':    txt(wpf, 'dwg_layers'),
        'color_mode_default':txt(wpf, 'dwg_color_mode'),
        'unit_default':      txt(wpf, 'dwg_unit'),
        'placement_default': txt(wpf, 'dwg_placement'),
        'correct_lines':     chk(wpf, 'dwg_correct_lines'),
        'view_only':         chk(wpf, 'dwg_view_only'),
    }

    # Profils Liaison CAO
    profils_out = []
    for _row_p in wpf.dgProfilsLiaison.ItemsSource:
        _lbl_p = str(_row_p[u'label']) if _row_p[u'label'] is not None else u''
        if not _lbl_p:
            continue
        _sys_p = (_lbl_p == _LOCKED_PROFIL_LABEL)
        _ord_p = _row_p[u'ordre']
        _store_entry = _profils_store.get(_lbl_p, {})
        profils_out.append({
            u'ordre':   int(_ord_p) if _ord_p is not None else 999,
            u'label':   _lbl_p,
            u'systeme': _sys_p,
            u'options_liaisons': dict(_store_entry.get(u'options_liaisons', _DEFAULT_PROFIL_OPTIONS)),
            u'vues':             dict(_store_entry.get(u'vues',             _DEFAULT_PROFIL_VUES)),
        })
    cfg[u'profils_liaison_cao'] = profils_out

    # Nettoyage
    cfg['nettoyage'] = {
        'dwg_imports':    chk(wpf, 'net_dwg_imports'),
        'dwg_liens':      chk(wpf, 'net_dwg_liens'),
        'lignes':         chk(wpf, 'net_lignes'),
        'texts':          chk(wpf, 'net_texts'),
        'pieces_espaces': chk(wpf, 'net_pieces'),
        'zones_pochages': chk(wpf, 'net_zones'),
    }

    # Couleurs Titres
    cfg['nomenclatures_titres_couleurs'] = {
        'tables_de_styles':          get_color(wpf,'tc_styles_r','tc_styles_g','tc_styles_b'),
        'saisies_types':             get_color(wpf,'tc_types_r', 'tc_types_g', 'tc_types_b'),
        'saisies_occurrences':       get_color(wpf,'tc_occur_r', 'tc_occur_g', 'tc_occur_b'),
        'nomenclatures_presentations':get_color(wpf,'tc_pres_r', 'tc_pres_g',  'tc_pres_b'),
    }

    # Couleurs Colonnes
    cfg['nomenclatures_colonnes_couleurs'] = {
        'colonnes_readonly':    get_color(wpf,'cc_readonly_r','cc_readonly_g','cc_readonly_b'),
        'colonnes_types':       get_color(wpf,'cc_types_r',   'cc_types_g',   'cc_types_b'),
        'colonnes_occurrences': get_color(wpf,'cc_occur_r',   'cc_occur_g',   'cc_occur_b'),
    }

    # LOG
    cfg['activer_logs_scripts'] = chk(wpf, 'log_activer')

    # Mises à jour
    cfg['mises_a_jour'] = {
        'source_url': txt(wpf, 'maj_source_url'),
    }

    # Emplacements
    try:    nb_rep = int(txt(wpf, 'el_nb_rep_parents'))
    except: nb_rep = 1
    if nb_rep < 0: nb_rep = 0
    cfg['emplacements'] = {
        'enregistrements_rvt': {
            'nb_rep_parents_enregistrement_rvt': nb_rep,
        }
    }

    # Garantir que emplacements est en tete du JSON
    empl_data = cfg.pop('emplacements')
    ordered_cfg = {'emplacements': empl_data}
    ordered_cfg.update(cfg)
    save_config(cfg_path, ordered_cfg)


if __name__ == '__main__':
    main()
