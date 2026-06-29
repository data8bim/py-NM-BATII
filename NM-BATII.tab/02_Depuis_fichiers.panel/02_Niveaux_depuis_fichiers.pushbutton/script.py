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



#__title__ = 'Niveaux depuis fichiers'
#__author__ = 'data8bim (d8b)'

import sys
import os
import re
import traceback
import clr


# Chargement de Revit
from Autodesk.Revit.DB import (
    Level, BuiltInCategory,
    FilteredElementCollector, Transaction
)


# WPF pour la boîte 
from pyrevit import forms, revit


# 1) 🔥 Ajouter lib/ au sys.path
script_dir = os.path.dirname(__file__)
ext_dir    = os.path.abspath(
    os.path.join(script_dir, os.pardir, os.pardir, os.pardir)
)
lib_dir = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)


# Import des modules partagés
from utils.config_loader import load_config
from utils.selection_fichier import pick_file_info
from utils.extrac_nom_fichier_convention import extract_file_name_info, resolve_template, get_convention_template

# 🔥 Charger les styles personnalisés WPF
from dialogs.dialogs_styles_loader import load, show_alert
load(lib_dir=lib_dir)


def parse_code_key(code, n_num=2, n_demi=1):
    pat = r"([A-Z])([+-])(\d{" + str(n_num) + r"})_(\d{" + str(n_demi) + r"})"
    m = re.match(pat, code)
    if not m:
        return 0.0
    _, sign, num, demi = m.groups()
    num, demi = int(num), int(demi)
    base = num if sign == '+' else -(num + 1)
    return base + demi / float(10 ** n_demi)

def get_user_params(default_esp, origin_label):
    xaml_file = os.path.join(os.path.dirname(__file__), "LevelParamsWindow.xaml")
    win = forms.WPFWindow(xaml_file)

    win.txtEspacement.Text = str(default_esp)
    win.chkOrigin.Content = "Créer le niveau Origine {}".format(origin_label)
    win.chkOrigin.IsChecked = True

    result = {"esp": None, "create_origin": False}

    def on_ok(sender, e):
        try:
            result["esp"] = float(win.txtEspacement.Text.strip())
        except:
            result["esp"] = default_esp
        result["create_origin"] = win.chkOrigin.IsChecked
        win.Close()

    def on_cancel(sender, e):
        result["esp"] = None
        win.Close()

    win.btnOk.Click += on_ok
    win.btnCancel.Click += on_cancel

    win.ShowDialog()
    return result["esp"], result["create_origin"]

def main():
    try:
        cfg         = load_config()
        prm         = cfg.get('creer_niveaux', {})
        esp_default = prm.get('espacement_default', 5.0)

        prefixes_cfg = prm.get('prefixes', [])
        sign_pos     = prm.get('signe_positif', '+')
        sign_neg     = prm.get('signe_negatif', '-')

        bat_prefix  = next((p['prefixe'] for p in prefixes_cfg if p.get('definition') == 'Batiment'),   'R')
        toit_prefix = next((p['prefixe'] for p in prefixes_cfg if p.get('definition') == 'Toiture'),    'T')
        fond_prefix = next((p['prefixe'] for p in prefixes_cfg if p.get('definition') == 'Fondations'), 'F')
        orig_prefix = next((p['prefixe'] for p in prefixes_cfg if p.get('definition') == 'Origine'),    'O')

        mark_toit   = toit_prefix + sign_pos
        mark_fond   = fond_prefix + sign_neg
        mark_pos    = bat_prefix  + sign_pos
        mark_neg    = bat_prefix  + sign_neg

        # Patterns depuis nm_convention_noms_fichiers.groupes (fallback creer_niveaux)
        nm       = cfg.get('nm_convention_noms_fichiers', {})
        _grp_map = {g.get('id', ''): g.get('regex', '') for g in nm.get('groupes', [])}
        _id_demi = _grp_map.get('demi-niv') or prm.get('id_demi_niveaux',   r'\d{1}')
        _id_num  = _grp_map.get('num-niv') or prm.get('id_numero_niveaux', r'\d{2}')

        _m_n    = re.search(r'\\d(?:\{(\d+)\})?', _id_demi)
        _n_demi = int(_m_n.group(1)) if (_m_n and _m_n.group(1)) else 1
        valeur_vrai_niveau = '_' + '0' * _n_demi

        _m_num = re.search(r'\\d(?:\{(\d+)\})?', _id_num)
        _n_num = int(_m_num.group(1)) if (_m_num and _m_num.group(1)) else 2

        # Identifiants de niveaux dérivés de la configuration
        _zeros_num  = '0' * _n_num
        _zeros_demi = '0' * _n_demi
        idt_rdc     = bat_prefix  + sign_pos + _zeros_num + '_' + _zeros_demi
        idt_rdc_bas = bat_prefix  + sign_neg + _zeros_num + '_' + _zeros_demi
        idt_orig    = orig_prefix + sign_pos + _zeros_num + '_' + _zeros_demi
        eleva_rdc   = prm.get('Eleva_Niv_Rdc', 0.0)
        eleva_orig  = prm.get('Eleva_Niv_Origine', 0.0)

        file_info = pick_file_info(file_ext='dwg;*.pdf', title='Sélectionnez un DWG ou PDF')
        if not file_info:
            return
        dwg_dir  = file_info['folder']
        basename = file_info['basename']

        info = extract_file_name_info(basename, cfg)
        if not info:
            show_alert(u'❌ Erreur Créer niveaux', u"Nom non conforme à la convention :\n{}".format(basename))
            return
        bat_code = info.get('building', '')

        esp, create_origin = get_user_params(esp_default, idt_orig)
        if esp is None:
            return
        to_ft = lambda m: m * 3.28084

        fichiers       = [f for f in os.listdir(dwg_dir) if f.lower().endswith(('.dwg', '.pdf'))]
        codes_found     = set()
        rdc_bas_present = False
        for fn in fichiers:
            base = os.path.splitext(fn)[0]
            fi = extract_file_name_info(base, cfg)
            if not fi or fi.get('building') != bat_code:
                continue
            code = "{}_{}".format(fi.get('level',''), fi.get('half',''))
            if 'X' in code:
                continue
            codes_found.add(code)
            if code == idt_rdc_bas:
                rdc_bas_present = True

        if not codes_found:
            show_alert(u'❌ Erreur Créer niveaux', u"Aucun niveau valide trouvé pour la construction '{}'".format(bat_code))
            return

        # --- Génération algorithmique des univers de niveaux ---
        def _get_num(code, mark):
            if not code.startswith(mark):
                return None
            rest = code[len(mark):]
            m = re.match(r'^(\d+)_', rest)
            return int(m.group(1)) if m else None

        max_pos = max_neg = max_toit = max_fond = 0
        for code in codes_found:
            n = _get_num(code, mark_pos)
            if n is not None:
                max_pos = max(max_pos, n)
                continue
            n = _get_num(code, mark_neg)
            if n is not None:
                max_neg = max(max_neg, n)
                continue
            n = _get_num(code, mark_toit)
            if n is not None:
                max_toit = max(max_toit, n)
                continue
            n = _get_num(code, mark_fond)
            if n is not None:
                max_fond = max(max_fond, n)

        # bat_global : R+ décroissant (max→00), puis R- croissant (00→max)
        bat_global = []
        for i in range(max_pos, -1, -1):
            bat_global.append(mark_pos + str(i).zfill(_n_num) + valeur_vrai_niveau)
        for i in range(0, max_neg + 1):
            bat_global.append(mark_neg + str(i).zfill(_n_num) + valeur_vrai_niveau)

        # roof_global : T+00 (gestion, premier), puis T+01→T+max
        roof_ref    = mark_toit + _zeros_num + valeur_vrai_niveau
        roof_global = [roof_ref]
        for i in range(1, max_toit + 1):
            roof_global.append(mark_toit + str(i).zfill(_n_num) + valeur_vrai_niveau)

        # fond_global : F-01→F-max (croissant), puis F-00 (gestion, dernier)
        fond_ref    = mark_fond + _zeros_num + valeur_vrai_niveau
        fond_global = []
        for i in range(1, max_fond + 1):
            fond_global.append(mark_fond + str(i).zfill(_n_num) + valeur_vrai_niveau)
        fond_global.append(fond_ref)

        if not rdc_bas_present:
            bat_global = [c for c in bat_global if c != idt_rdc_bas]

        # Niveaux pleins vs demi
        full_codes_found = set(c for c in codes_found if c.endswith(valeur_vrai_niveau))
        demi_found       = [c for c in codes_found if not c.endswith(valeur_vrai_niveau)]

        # Séparation demi-niveaux bâtiment / toiture (évite une interpolation croisée)
        bat_demi_found  = [c for c in demi_found if not c.startswith(mark_toit)]
        roof_demi_found = [c for c in demi_found if c.startswith(mark_toit)]

        roof_found = [c for c in roof_global if c in full_codes_found and c != roof_ref]
        fond_found = [c for c in fond_global if c in full_codes_found and c != fond_ref]
        bat_found  = [c for c in bat_global  if c in full_codes_found]
        if idt_rdc not in bat_found:
            bat_found.append(idt_rdc)
        if rdc_bas_present and idt_rdc_bas not in bat_found:
            bat_found.append(idt_rdc_bas)

        idx_min   = min(bat_global.index(c) for c in bat_found)
        idx_max   = max(bat_global.index(c) for c in bat_found)
        bat_range = bat_global[idx_min: idx_max + 1]

        codes_to_insert = [idt_rdc]
        if rdc_bas_present:
            codes_to_insert.append(idt_rdc_bas)
        for code in codes_to_insert:
            if code in bat_global and code not in bat_range:
                pos_csv   = bat_global.index(code)
                insert_at = sum(1 for c in bat_range if bat_global.index(c) < pos_csv)
                bat_range.insert(insert_at, code)

        idx_rdc = bat_range.index(idt_rdc)
        pos_m   = {}
        for i, lvl in enumerate(bat_range):
            pos_m[lvl] = eleva_rdc + (idx_rdc - i) * esp

        # key_map : codes_found + niveaux obligatoires + bat_range (niveaux intermédiaires)
        mandatory = set([idt_rdc, idt_rdc_bas, idt_orig, roof_ref, fond_ref])
        key_map   = {c: parse_code_key(c, _n_num, _n_demi)
                     for c in codes_found | mandatory | set(bat_range)}
        bat_bt     = list(reversed(bat_range))
        for lo, hi in zip(bat_bt, bat_bt[1:]):
            h_lo, h_hi = pos_m[lo], pos_m[hi]
            k_lo, k_hi = key_map[lo], key_map[hi]
            for d in bat_demi_found:
                k_d = key_map.get(d, 0.0)
                if d in pos_m:
                    continue
                if k_lo < k_d < k_hi:
                    pos_m[d] = h_lo + ((k_d - k_lo)/(k_hi - k_lo))*(h_hi - h_lo)

        # 14) Toiture générale
        if roof_global:
            general_roof = roof_global[0]
            max_b = max(pos_m[l] for l in bat_range)
            for idx, lvl in enumerate(
                    sorted(roof_found, key=lambda x: key_map[x]), 1):
                pos_m[lvl] = max_b + idx * esp
            pos_m[general_roof] = max_b + (len(roof_found) + 1) * esp

            # Demi-niveaux de toiture : interpolation entre niveaux pleins consécutifs
            if roof_demi_found:
                roof_full_by_elev = sorted(
                    [(c, pos_m[c]) for c in roof_global if c in pos_m],
                    key=lambda x: x[1]
                )
                for _i in range(len(roof_full_by_elev) - 1):
                    lo_code, lo_elev = roof_full_by_elev[_i]
                    hi_code, hi_elev = roof_full_by_elev[_i + 1]
                    _m_lo = re.match(r'[A-Z][+-](\d+)_', lo_code)
                    if not _m_lo:
                        continue
                    lo_num = int(_m_lo.group(1))
                    for d in roof_demi_found:
                        if d in pos_m:
                            continue
                        _m_d = re.match(r'[A-Z][+-](\d+)_(\d+)', d)
                        if not _m_d or int(_m_d.group(1)) != lo_num:
                            continue
                        fraction = int(_m_d.group(2)) / float(10 ** _n_demi)
                        pos_m[d] = lo_elev + fraction * (hi_elev - lo_elev)

        # 15) Fondation générale
        if fond_global:
            general_fond = fond_global[-1]
            min_b = min(pos_m[l] for l in bat_range)
            for idx, lvl in enumerate(
                    sorted(fond_found, key=lambda x: key_map[x], reverse=True), 1):
                pos_m[lvl] = min_b - idx * esp
            pos_m[general_fond] = min_b - (len(fond_found) + 1) * esp

        # 16) Origine optionnelle
        if create_origin and idt_orig:
            pos_m[idt_orig] = eleva_orig

        # 17) Création dans Revit
        sorted_levels = sorted(pos_m.items(), key=lambda x: x[1])
        doc = revit.doc
        existing = {
            lvl.Name for lvl in FilteredElementCollector(doc)
                .OfCategory(BuiltInCategory.OST_Levels)
                .WhereElementIsNotElementType()
        }
        created = []
        created_codes = []

        _tpl_nom_niveau = get_convention_template(
            cfg, 'niveaux-revit', '{construction}_{niveau}_{demi-niv}')

        _pat_code = r'^([A-Z])([+\-])(\d{' + str(_n_num) + r'})_(\d{' + str(_n_demi) + r'})$'

        t = Transaction(doc, "Créer niveaux depuis fichiers")
        t.Start()
        for code, elev_m in sorted_levels:
            _mc = re.match(_pat_code, code)
            if _mc:
                _pref, _sens, _num_str, _demi_str = _mc.groups()
            else:
                _pref = _sens = _num_str = _demi_str = ''
            _sous_tpl = {'niveau': _pref + _sens + _num_str}
            _vals     = {'construction': bat_code, 'demi-niv': _demi_str}
            name = resolve_template(_tpl_nom_niveau, _vals, _sous_tpl)
            if name not in existing:
                lvl = Level.Create(doc, to_ft(elev_m))
                lvl.Name = name
                created.append(name)
                created_codes.append(code)
        t.Commit()

        # 18) Confirmation finale
        res_xaml = os.path.join(os.path.dirname(__file__), "ResultWindow.xaml")
        res_win  = forms.WPFWindow(res_xaml)

        nb = len(created)

        # Niveaux de gestion des vues (créés systématiquement)
        management_fond = fond_global[-1] if fond_global else None
        management_toit = roof_global[0]  if roof_global else None

        # Comptage par catégorie
        nb_niveaux   = 0
        nb_demi      = 0
        nb_fond      = 0
        nb_toit      = 0
        nb_orig      = 0
        nb_mgmt_fond = 0
        nb_mgmt_toit = 0
        nb_mgmt_orig = 0
        for name, code in zip(created, created_codes):
            if idt_orig and code == idt_orig:
                nb_mgmt_orig += 1
            elif management_toit and code == management_toit:
                nb_mgmt_toit += 1
            elif management_fond and code == management_fond:
                nb_mgmt_fond += 1
            elif mark_toit and code.startswith(mark_toit):
                nb_toit += 1
            elif mark_fond and code.startswith(mark_fond):
                nb_fond += 1
            elif code.endswith(valeur_vrai_niveau):
                nb_niveaux += 1
            else:
                nb_demi += 1

        # Construction du tableau de résultats (DataTable → DataGrid WPF)
        clr.AddReference("System.Data")
        from System.Data import DataTable as SysDataTable
        dt = SysDataTable()
        dt.Columns.Add("Categorie")
        dt.Columns.Add("Nombre")
        dt.Columns.Add("IsTotal")
        dt.Columns.Add("IsSep")

        def add_row(label, count, is_total="0", is_sep="0"):
            r = dt.NewRow()
            r["Categorie"] = label
            r["Nombre"]    = str(count)
            r["IsTotal"]   = is_total
            r["IsSep"]     = is_sep
            dt.Rows.Add(r)

        def add_sep(label):
            add_row(label, u"", "0", "1")

        has_var  = nb_niveaux > 0 or nb_demi > 0 or nb_fond > 0 or nb_toit > 0 or nb_orig > 0
        has_mgmt = nb_mgmt_fond > 0 or nb_mgmt_toit > 0 or nb_mgmt_orig > 0

        if has_var:
            add_sep(u"Niveaux :")
            if nb_niveaux > 0: add_row(u"Niveaux",            nb_niveaux)
            if nb_demi    > 0: add_row(u"Demi-niveaux",       nb_demi)
            if nb_fond    > 0: add_row(u"Niveaux Fondations", nb_fond)
            if nb_toit    > 0: add_row(u"Niveaux Toitures",   nb_toit)
            if nb_orig    > 0: add_row(u"Niveaux Origine",    nb_orig)

        if has_mgmt:
            add_sep(u"Niveaux de gestion des vues :")
            if nb_mgmt_fond > 0: add_row(u"gestion vue Fondations", nb_mgmt_fond)
            if nb_mgmt_toit > 0: add_row(u"gestion vue Toitures",   nb_mgmt_toit)
            if nb_mgmt_orig > 0: add_row(u"gestion vue Origine",    nb_mgmt_orig)

        add_row(u"Total", nb, "1")

        if nb == 0:
            res_win.txtTitle.Text = u"Aucun niveau créé."
        else:
            res_win.txtTitle.Text = u"Niveaux créés"

        res_win.dataGrid.ItemsSource = dt.DefaultView
        res_win.btnClose.Click += lambda s, e: setattr(res_win, "DialogResult", True)
        # ✅ FIX pyRevit 6 : show_dialog() supprimé → ShowDialog() (WPF natif)
        res_win.ShowDialog()
        

    except Exception:
        show_alert(u"❌ Erreur inattendue", traceback.format_exc())


if __name__ == '__main__':
    main()
