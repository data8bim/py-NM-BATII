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
    forms.alert("Configuration enregistree", title="Config")


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

    # Sections avec valeur par defaut si absentes
    sf   = cfg.setdefault('surface', {})
    cn   = cfg.setdefault('creer_niveaux', {})
    nc   = cfg.setdefault('nm_convention_noms_fichiers', {})
    dwg  = cfg.setdefault('fichiers_lies_dwg', {})
    net  = cfg.setdefault('nettoyage', {})
    tc   = cfg.setdefault('nomenclatures_titres_couleurs', {})
    cc   = cfg.setdefault('nomenclatures_colonnes_couleurs', {})

    xaml = os.path.join(os.path.dirname(__file__), 'WPFWindow.xaml')
    wpf  = forms.WPFWindow(xaml)
    wpf.Title = "Configurer config.json"

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
    set_txt(wpf, 'cn_espacement',      cn.get('espacement_default', 5.0))
    set_txt(wpf, 'cn_marq_toit',       cn.get('Marq_Niv_Toit', ''))
    set_txt(wpf, 'cn_marq_fondations', cn.get('Marq_Niv_Fondations', ''))
    set_txt(wpf, 'cn_idt_bat_pos',     cn.get('Idt_Niv_Batiment_pos', ''))
    set_txt(wpf, 'cn_idt_bat_neg',     cn.get('Idt_Niv_Batiment_neg', ''))
    set_txt(wpf, 'cn_idt_rdc',         cn.get('Idt_Niv_Rdc', ''))
    set_txt(wpf, 'cn_idt_rdc_bas',     cn.get('Idt_Niv_Rdc_bas', ''))
    set_txt(wpf, 'cn_eleva_rdc',       cn.get('Eleva_Niv_Rdc', 0.0))
    set_txt(wpf, 'cn_idt_origine',     cn.get('Idt_Niv_Origine', ''))
    set_txt(wpf, 'cn_eleva_origine',   cn.get('Eleva_Niv_Origine', 0.0))

    # ── Noms Fichiers ─────────────────────────────────────────────────────────
    set_txt(wpf, 'nc_delimiteur',      nc.get('delimiteur', '_'))
    set_txt(wpf, 'nc_pos_site',        nc.get('pos_code_site', 0))
    set_txt(wpf, 'nc_pos_bat',         nc.get('pos_code_bat', 1))
    set_txt(wpf, 'nc_pos_niv',         nc.get('pos_code_niv', 2))
    set_txt(wpf, 'nc_pos_demi',        nc.get('pos_code_demi_niv', 3))
    set_txt(wpf, 'nc_pos_prod',        nc.get('pos_code_prod', 4))
    set_txt(wpf, 'nc_pos_nom_court',   nc.get('pos_nom_site_court', 6))
    set_txt(wpf, 'nc_pos_rest',        nc.get('pos_rest_nom', 7))
    set_txt(wpf, 'nc_grp_site',        nc.get('group_site', ''))
    set_txt(wpf, 'nc_grp_bat',         nc.get('group_batiment', ''))
    set_txt(wpf, 'nc_grp_niv',         nc.get('group_niveau', ''))
    set_txt(wpf, 'nc_grp_demi',        nc.get('group_demi', ''))
    set_txt(wpf, 'nc_grp_prod',        nc.get('group_prod', ''))
    set_txt(wpf, 'nc_grp_site_court',  nc.get('group_site_nom_court', ''))
    set_txt(wpf, 'nc_grp_rest',        nc.get('group_rest_nom', ''))
    set_txt(wpf, 'nc_val_nul',         nc.get('valeur_si_nul', ''))
    set_txt(wpf, 'nc_val_vrai_niv',    nc.get('valeur_pour_vrai_niveau', ''))
    set_txt(wpf, 'nc_val_sans_niv',    nc.get('valeur_pour_sans_niveau', ''))
    set_txt(wpf, 'nc_val_bim2d',       nc.get('valeur_si_bim_2d', ''))
    set_chk(wpf, 'nc_use_regex',       nc.get('utiliser_regex', False))
    wpf._pattern = nc.get('regle_regex', '')
    wpf.btnEditRegex.ToolTip = wpf._pattern

    wpf.btnEditRegex.Click += lambda s, e: (
        setattr(wpf, '_pattern', edit_regex_dialog(wpf._pattern)),
        setattr(wpf.btnEditRegex, 'ToolTip', wpf._pattern)
    )

    # ── Noms Vues ─────────────────────────────────────────────────────────────
    set_txt(wpf, 'vt_vue_type', cfg.get('vue_type_personnalise', ''))

    # ── Liaisons DWG ─────────────────────────────────────────────────────────
    set_chk(wpf, 'dwg_include_sub',   dwg.get('include_sub', False))
    set_txt(wpf, 'dwg_layers',        dwg.get('layers_default', ''))
    set_txt(wpf, 'dwg_color_mode',    dwg.get('color_mode_default', ''))
    set_txt(wpf, 'dwg_unit',          dwg.get('unit_default', ''))
    set_txt(wpf, 'dwg_placement',     dwg.get('placement_default', ''))
    set_chk(wpf, 'dwg_correct_lines', dwg.get('correct_lines', True))
    set_chk(wpf, 'dwg_view_only',     dwg.get('view_only', True))

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

    # ── LOG ───────────────────────────────────────────────────────────────────
    set_chk(wpf, 'log_activer', cfg.get('activer_logs_scripts', True))

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
    cfg['creer_niveaux'] = {
        'espacement_default':  esp,
        'Marq_Niv_Toit':       txt(wpf, 'cn_marq_toit'),
        'Marq_Niv_Fondations': txt(wpf, 'cn_marq_fondations'),
        'Idt_Niv_Batiment_pos':txt(wpf, 'cn_idt_bat_pos'),
        'Idt_Niv_Batiment_neg':txt(wpf, 'cn_idt_bat_neg'),
        'Idt_Niv_Rdc':         txt(wpf, 'cn_idt_rdc'),
        'Idt_Niv_Rdc_bas':     txt(wpf, 'cn_idt_rdc_bas'),
        'Eleva_Niv_Rdc':       eleva_rdc,
        'Idt_Niv_Origine':     txt(wpf, 'cn_idt_origine'),
        'Eleva_Niv_Origine':   eleva_ori,
    }

    # Noms Fichiers
    def to_int(wpf, name, default=0):
        try:    return int(txt(wpf, name))
        except: return default

    cfg['nm_convention_noms_fichiers'] = {
        'delimiteur':            txt(wpf, 'nc_delimiteur'),
        'pos_code_site':         to_int(wpf, 'nc_pos_site',     0),
        'pos_code_bat':          to_int(wpf, 'nc_pos_bat',      1),
        'pos_code_niv':          to_int(wpf, 'nc_pos_niv',      2),
        'pos_code_demi_niv':     to_int(wpf, 'nc_pos_demi',     3),
        'pos_code_prod':         to_int(wpf, 'nc_pos_prod',     4),
        'pos_nom_site_court':    to_int(wpf, 'nc_pos_nom_court',6),
        'pos_rest_nom':          to_int(wpf, 'nc_pos_rest',     7),
        'group_site':            txt(wpf, 'nc_grp_site'),
        'group_batiment':        txt(wpf, 'nc_grp_bat'),
        'group_niveau':          txt(wpf, 'nc_grp_niv'),
        'group_demi':            txt(wpf, 'nc_grp_demi'),
        'group_prod':            txt(wpf, 'nc_grp_prod'),
        'group_site_nom_court':  txt(wpf, 'nc_grp_site_court'),
        'group_rest_nom':        txt(wpf, 'nc_grp_rest'),
        'valeur_si_nul':         txt(wpf, 'nc_val_nul'),
        'valeur_pour_vrai_niveau':txt(wpf,'nc_val_vrai_niv'),
        'valeur_pour_sans_niveau':txt(wpf,'nc_val_sans_niv'),
        'valeur_si_bim_2d':      txt(wpf, 'nc_val_bim2d'),
        'utiliser_regex':        chk(wpf, 'nc_use_regex'),
        'regle_regex':           wpf._pattern,
    }

    # Noms Vues
    cfg['vue_type_personnalise'] = txt(wpf, 'vt_vue_type')

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

    save_config(cfg_path, cfg)


if __name__ == '__main__':
    main()
