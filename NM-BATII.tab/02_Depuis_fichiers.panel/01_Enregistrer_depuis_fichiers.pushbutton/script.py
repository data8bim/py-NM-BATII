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

import os
import sys
import re
import json
import codecs
import traceback

import clr
clr.AddReference('PresentationFramework')
clr.AddReference('PresentationCore')
clr.AddReference('WindowsBase')

from System.Windows import (
    WindowStartupLocation, GridLength, GridUnitType,
    Thickness, HorizontalAlignment, TextWrapping, Clipboard
)
from System.Windows.Controls import (
    Grid, ColumnDefinition, RowDefinition,
    CheckBox, TextBox, TextBlock
)

from pyrevit import forms, revit, script as pyscript
from Autodesk.Revit.DB import SaveAsOptions

# ─── Chemin lib/ ─────────────────────────────────────────────────────────────

script_dir = os.path.dirname(__file__)
ext_dir    = os.path.abspath(os.path.join(script_dir, os.pardir, os.pardir, os.pardir))
lib_dir    = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

from utils.config_loader                     import load_config
from utils.extrac_nom_fichier_convention     import (delimiter_from_regex, build_regex,
                                                     diagnostiquer_nom_fichier,
                                                     get_convention_template)
from dialogs.dialogs_styles_loader           import load as load_styles, show_alert

# ─── Système de logs ──────────────────────────────────────────────────────────

def _parse_bool_like(v):
    if isinstance(v, bool): return v
    if isinstance(v, (int, float)): return bool(v)
    if isinstance(v, str):
        s = v.strip().lower()
        if s in ("true", "1", "yes", "y", "on"):  return True
        if s in ("false", "0", "no",  "n", "off"): return False
    return None

_cfg_log = load_config() or {}
ACTIVER_LOGS = True
try:
    _parsed = _parse_bool_like(_cfg_log.get("activer_logs_scripts", True))
    if _parsed is not None:
        ACTIVER_LOGS = _parsed
except Exception:
    ACTIVER_LOGS = True

_output = None
if ACTIVER_LOGS:
    try:
        _output = pyscript.get_output()
    except Exception:
        _output = None

def log(msg):
    if not ACTIVER_LOGS:
        return
    try:
        if _output:
            _output.print_md(msg)
        else:
            print(msg)
    except Exception:
        try:
            print(msg)
        except Exception:
            pass


# ─── Constantes ──────────────────────────────────────────────────────────────

_ACTION_REPLACE = "replace"
_ACTION_RENAME  = "rename"

_LAST_SAVE_FILE = os.path.join(script_dir, "_last_save.NM-Save-rvt")


# ─── Persistance état des cases à cocher ─────────────────────────────────────

def load_last_state():
    """
    Charge le dernier état des cases à cocher depuis _LAST_SAVE_FILE.
    Retourne un dict {group_name: bool, "__bim2d__": bool} ou {} si absent/invalide.
    """
    if not os.path.isfile(_LAST_SAVE_FILE):
        return {}
    try:
        with codecs.open(_LAST_SAVE_FILE, "r", "utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_last_state(checkboxes, chk_bim2d):
    """
    Sauvegarde l'état courant des cases à cocher dans _LAST_SAVE_FILE.
    Les erreurs d'écriture sont silencieuses pour ne pas bloquer l'utilisateur.
    """
    state = {gname: bool(chk.IsChecked) for gname, chk in checkboxes.items()}
    state["__bim2d__"] = bool(chk_bim2d.IsChecked)
    try:
        with codecs.open(_LAST_SAVE_FILE, "w", "utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ─── Helpers regex ───────────────────────────────────────────────────────────

def resoudre_groupe_niveau(naming, groups_ordered):
    """
    Retourne le nom du groupe de niveau dans la regex de convention.

    Ce nom derive de l'identifiant du sous-template "Niveau (code)" via
    _safe_name() : 'niveau-code' -> 'niveau_code'. L'ancien identifiant
    'niveau' reste accepte pour les config.json anterieurs au renommage.

    On detecte le nom reellement present dans la regex plutot que de le coder
    en dur : sans cela, le niveau ne serait plus remplace par la valeur
    "sans niveau" et cesserait d'etre un groupe obligatoire.
    """
    explicite = naming.get("group_niveau")
    if explicite:
        return explicite
    for candidat in ("niveau_code", "niveau"):
        if candidat in groups_ordered:
            return candidat
    return "niveau_code"


def get_named_groups_ordered(pattern):
    """Retourne la liste des noms de groupes dans leur ordre d'apparition dans la regex."""
    return re.findall(r'\(\?P<([^>]+)>', pattern)


def parse_filename_all_groups(filename_noext, pattern):
    """
    Applique la regex sur le nom de fichier (sans extension).
    Retourne un dict {group_name: valeur_str} pour tous les groupes nommés,
    ou None si la regex ne correspond pas.
    """
    try:
        m = re.match(pattern, filename_noext)
    except re.error:
        return None
    if not m:
        return None
    return {k: (v or "") for k, v in m.groupdict().items()}


def build_final_name(groups_ordered, mandatory_groups,
                     checkboxes, textboxes,
                     delimiter, bim2d_suffix, chk_bim2d):
    """
    Reconstruit le nom final en suivant l'ordre des groupes dans la regex.
    - Groupes obligatoires : toujours inclus (si non vides).
    - Groupes optionnels  : inclus uniquement si leur case est cochée.
    - Suffixe BIM-2D      : ajouté à la fin si coché.
    """
    parts = []
    for gname in groups_ordered:
        if gname in mandatory_groups:
            val = textboxes[gname].Text.strip()
            if val:
                parts.append(val)
        else:
            chk = checkboxes.get(gname)
            if chk and chk.IsChecked:
                val = textboxes[gname].Text.strip()
                if val:
                    parts.append(val)
    name = delimiter.join(parts)
    if chk_bim2d.IsChecked and bim2d_suffix:
        bim2d_clean = bim2d_suffix.lstrip("_")
        if bim2d_clean:
            name = (name + delimiter + bim2d_clean) if name else bim2d_clean
    return name


# ─── Grille dynamique ────────────────────────────────────────────────────────

def build_groups_grid(groups_ordered, group_values, mandatory_groups, bim2d_label="BIM-2D"):
    """
    Construit un Grid WPF dynamique :
      Row 0 : case à cocher  (groupes optionnels uniquement)
      Row 1 : étiquette      (nom du groupe, underscores remplacés par espaces)
      Row 2 : champ texte    (valeur extraite du fichier témoin)
    + une colonne BIM-2D supplémentaire à la fin.

    Les styles NM (NMTextBoxStandard, NMCheckBoxStandard…) s'appliquent
    automatiquement via les styles implicites définis dans Window.Resources
    du XAML hôte.

    Retourne (grid, checkboxes_dict, textboxes_dict, chk_bim2d).
    """
    n_groups = len(groups_ordered)
    n_cols   = n_groups + 1          # +1 pour BIM-2D

    grid = Grid()
    grid.Margin = Thickness(0, 0, 0, 5)

    for _i in range(n_cols):
        col = ColumnDefinition()
        col.Width    = GridLength(1, GridUnitType.Star)
        col.MinWidth = 55
        grid.ColumnDefinitions.Add(col)

    for _i in range(3):              # row 0 = checkboxes, 1 = labels, 2 = textboxes
        row = RowDefinition()
        row.Height = GridLength.Auto
        grid.RowDefinitions.Add(row)

    checkboxes = {}
    textboxes  = {}

    for col_idx, gname in enumerate(groups_ordered):
        is_mandatory = gname in mandatory_groups
        value        = (group_values or {}).get(gname, "")

        # Row 0 : case à cocher uniquement pour les groupes optionnels
        if not is_mandatory:
            chk = CheckBox()
            chk.IsChecked            = bool(value)
            chk.HorizontalAlignment  = HorizontalAlignment.Center
            chk.Margin               = Thickness(2)
            Grid.SetRow(chk, 0)
            Grid.SetColumn(chk, col_idx)
            grid.Children.Add(chk)
            checkboxes[gname] = chk

        # Row 1 : étiquette
        lbl = TextBlock()
        lbl.Text                = gname.replace("_", " ")
        lbl.HorizontalAlignment = HorizontalAlignment.Center
        lbl.TextWrapping        = TextWrapping.Wrap
        lbl.Margin              = Thickness(2)
        Grid.SetRow(lbl, 1)
        Grid.SetColumn(lbl, col_idx)
        grid.Children.Add(lbl)

        # Row 2 : champ texte
        txt = TextBox()
        txt.Text                = value
        txt.Margin              = Thickness(2)
        txt.HorizontalAlignment = HorizontalAlignment.Stretch
        Grid.SetRow(txt, 2)
        Grid.SetColumn(txt, col_idx)
        grid.Children.Add(txt)
        textboxes[gname] = txt

    # ── Colonne BIM-2D (dernière) ────────────────────────────────────────────
    bim2d_col = n_groups

    chk_bim2d                       = CheckBox()
    chk_bim2d.IsChecked             = True
    chk_bim2d.HorizontalAlignment   = HorizontalAlignment.Center
    chk_bim2d.Margin                = Thickness(2)
    Grid.SetRow(chk_bim2d, 0)
    Grid.SetColumn(chk_bim2d, bim2d_col)
    grid.Children.Add(chk_bim2d)

    lbl_bim2d                       = TextBlock()
    lbl_bim2d.Text                  = bim2d_label
    lbl_bim2d.HorizontalAlignment   = HorizontalAlignment.Center
    lbl_bim2d.Margin                = Thickness(2)
    Grid.SetRow(lbl_bim2d, 1)
    Grid.SetColumn(lbl_bim2d, bim2d_col)
    grid.Children.Add(lbl_bim2d)

    return grid, checkboxes, textboxes, chk_bim2d


# ─── Dialogues auxiliaires ───────────────────────────────────────────────────

def show_file_exists_dialog(path):
    """
    Affiche le dialogue "fichier existant".
    Retourne _ACTION_REPLACE, _ACTION_RENAME, ou None si la fenêtre est fermée.
    """
    win = forms.WPFWindow(os.path.join(script_dir, "FileExistsDialog.xaml"))
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.txtPath.Text          = path

    choice = {"action": None}

    def on_rename(s, e):
        choice["action"] = _ACTION_RENAME
        win.DialogResult = True

    def on_replace(s, e):
        choice["action"] = _ACTION_REPLACE
        win.DialogResult = True

    win.btnRename.Click  += on_rename
    win.btnReplace.Click += on_replace

    if not win.show_dialog():
        return None
    return choice["action"]


def show_rename_dialog(default_name):
    """Retourne le nouveau nom saisi par l'utilisateur, ou None si annulé."""
    win = forms.WPFWindow(os.path.join(script_dir, "RenameDialog.xaml"))
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.txtName.Text          = default_name

    result = {"value": None}

    def on_ok(s, e):
        result["value"] = win.txtName.Text.strip()
        win.DialogResult = True

    def on_cancel(s, e):
        win.DialogResult = False

    win.btnOk.Click     += on_ok
    win.btnCancel.Click += on_cancel

    win.show_dialog()
    return result["value"]


def show_path_dialog(path):
    """Affiche le chemin final avec un bouton de copie dans le presse-papiers."""
    win = forms.WPFWindow(os.path.join(script_dir, "PathDialog.xaml"))
    win.WindowStartupLocation = WindowStartupLocation.CenterScreen
    win.txtPath.Text          = path
    win.btnCopy.Click  += lambda s, e: Clipboard.SetText(path)
    win.btnClose.Click += lambda s, e: setattr(win, "DialogResult", True)
    win.show_dialog()


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    try:
        load_styles(lib_dir=lib_dir)

        # ── Config ──────────────────────────────────────────────────────────
        log(u"## Enregistrer RVT depuis fichiers")
        cfg     = load_config()
        naming  = cfg.get("nm_convention_noms_fichiers", {})
        pattern      = build_regex(cfg)
        delimiter    = delimiter_from_regex(pattern)
        bim2d_suffix = naming.get("valeur_si_bim_2d", "_BIM-2D").strip()
        log(u"Délimiteur : `{}`".format(delimiter))

        if not pattern:
            show_alert(u"Erreur configuration", u"Aucune regex configurée dans config.json (clé : regle_regex).")
            return

        try:
            re.compile(pattern)
        except re.error as err:
            show_alert(u"Erreur configuration", u"Regex invalide dans config.json :\n{0}".format(err))
            return

        # ── Groupes nommés ───────────────────────────────────────────────────
        groups_ordered = get_named_groups_ordered(pattern)
        if not groups_ordered:
            show_alert(u"Erreur configuration", u"Aucun groupe nommé (?P<...>) trouvé dans la regex.")
            return

        # Groupes obligatoires (gérés par le panel Paramètres, pas de checkbox)
        # Les noms utilisés sont ceux des groupes dans la regex (safe_name : '-' → '_')
        _g_niveau_regex = resoudre_groupe_niveau(naming, groups_ordered)
        mandatory_groups = set([
            naming.get("group_site",         "site"),
            naming.get("group_construction", "construction"),
            _g_niveau_regex,
            naming.get("group_demi",         "demi_niv"),
        ])

        # ── Fichier témoin ───────────────────────────────────────────────────
        _src = forms.pick_file(
            files_filter=(
                u"Fichiers plan (*.dwg;*.dwf;*.pdf;*.rvt)"
                u"|*.dwg;*.dwf;*.pdf;*.rvt"
                u"|DWG (*.dwg)|*.dwg"
                u"|DWF (*.dwf)|*.dwf"
                u"|PDF (*.pdf)|*.pdf"
                u"|RVT (*.rvt)|*.rvt"
            ),
            title=u"Choisissez un fichier témoin"
        )
        if not _src:
            return
        file_info = {
            "full_path": _src,
            "folder":    os.path.dirname(_src),
            "filename":  os.path.basename(_src),
            "basename":  os.path.splitext(os.path.basename(_src))[0],
        }

        # ── Extraction des valeurs depuis le nom ─────────────────────────────
        group_values = parse_filename_all_groups(file_info["basename"], pattern)
        if group_values is None:
            # Diagnostic element par element : indique OU la lecture echoue,
            # plutot qu'un simple "non conforme" qui laisse chercher.
            try:
                _ok_diag, _lignes = diagnostiquer_nom_fichier(
                    file_info["basename"], cfg)
                _detail = u"\n".join(_lignes)
            except Exception:
                _detail = u""
            _msg = (u"Le fichier sélectionné ne respecte pas la convention "
                    u"de nommage :\n\n    {0}\n\n".format(file_info["basename"]))
            if _detail:
                _msg += _detail + u"\n\n"
            _msg += (u"Convention attendue :\n    {0}\n\n"
                     u"Veuillez renommer correctement tous les fichiers du projet\n"
                     u"avant de relancer cette commande.".format(
                         get_convention_template(cfg, "fichiers",
                                                 u"(non configurée)")))
            show_alert(u"Nom non conforme à la convention", _msg)
            return

        # ── Valeurs par défaut (remplacent les valeurs extraites du témoin) ──
        #
        # niveau  → valeur_pour_sans_niveau  (ex. "RXXX")
        # demi    → valeur_si_nul répétée autant de fois que de caractères dans
        #           la valeur extraite du fichier témoin (ex. "0" → "X", "00" → "XX")
        # BIM-2D  → libellé dérivé de valeur_si_bim_2d (ex. "_BIM-2D" → "BIM-2D")

        _g_niveau = _g_niveau_regex
        _g_demi   = naming.get("group_demi",   "demi_niv")

        _val_nul      = naming.get("valeur_si_nul", "X")
        _cn           = cfg.get("creer_niveaux", {})
        _idt_rdc      = _cn.get("Idt_Niv_Rdc", "")
        _code_part    = _idt_rdc.split("_")[0] if _idt_rdc else ""
        _val_sans_niv = (_val_nul * len(_code_part)) if _code_part else (_val_nul * 4)
        _null_char    = _val_nul[0] if _val_nul else "X"

        # Niveau : toujours remplacé par la valeur "sans niveau"
        group_values[_g_niveau] = _val_sans_niv

        # Demi-niveau : null_char × len(valeur extraite), minimum 1 caractère
        _extracted_demi = group_values.get(_g_demi, "")
        group_values[_g_demi] = _null_char * max(1, len(_extracted_demi))

        # Label BIM-2D : suffixe config sans le(s) underscore(s) de tête
        bim2d_label = bim2d_suffix.lstrip("_") or "BIM-2D"

        # ── Dialogue SaveAs ─────────────────────────────────────────────────
        saveas_xaml = os.path.join(script_dir, "SaveAsDialog.xaml")
        if not os.path.isfile(saveas_xaml):
            show_alert(u"Erreur", u"XAML introuvable :\n{0}".format(saveas_xaml))
            return

        win = forms.WPFWindow(saveas_xaml)
        win.WindowStartupLocation = WindowStartupLocation.CenterScreen

        # Grille dynamique insérée en tête du StackPanel principal
        groups_grid, checkboxes, textboxes, chk_bim2d = build_groups_grid(
            groups_ordered, group_values, mandatory_groups, bim2d_label
        )
        win.mainPanel.Children.Insert(0, groups_grid)

        # ── Restauration du dernier état des cases à cocher ──────────────────
        _last = load_last_state()
        for gname, chk in checkboxes.items():
            if gname in _last:
                chk.IsChecked = _last[gname]
        if "__bim2d__" in _last:
            chk_bim2d.IsChecked = _last["__bim2d__"]

        # ── Aperçu temps réel ────────────────────────────────────────────────
        def get_preview():
            name = build_final_name(
                groups_ordered, mandatory_groups,
                checkboxes, textboxes,
                delimiter, bim2d_suffix, chk_bim2d
            )
            return (name + ".rvt") if name else u"(nom vide)"

        def update_preview(s, e):
            win.lblPreview.Text = u"Apercu : " + get_preview()

        chk_bim2d.Checked   += update_preview
        chk_bim2d.Unchecked += update_preview
        for chk in checkboxes.values():
            chk.Checked   += update_preview
            chk.Unchecked += update_preview
        for txt in textboxes.values():
            txt.TextChanged += update_preview

        def on_ok(s, e):
            save_last_state(checkboxes, chk_bim2d)
            win.DialogResult = True

        win.btnOk.Click     += on_ok
        win.btnCancel.Click += lambda s, e: setattr(win, "DialogResult", False)

        update_preview(None, None)

        if not win.show_dialog():
            return

        # ── Dossier cible (remontée de n niveaux) ────────────────────────────
        nb_rep = (cfg.get("emplacements", {})
                     .get("enregistrements_rvt", {})
                     .get("nb_rep_parents_enregistrement_rvt", 1))
        try:
            nb_rep = int(nb_rep)
        except (ValueError, TypeError):
            nb_rep = 1
        nb_rep = max(0, nb_rep)

        folder = file_info["folder"]
        for _ in range(nb_rep):
            parent = os.path.dirname(folder)
            if parent and parent != folder:
                folder = parent

        # ── Nom final ────────────────────────────────────────────────────────
        user_name = get_preview()
        if user_name == u"(nom vide)":
            show_alert(u"Erreur", u"Le nom de fichier est vide. Vérifiez les champs.")
            return
        if not user_name.lower().endswith(".rvt"):
            user_name += ".rvt"

        target = os.path.join(folder, user_name)
        doc    = revit.doc

        # ── Gestion fichier existant ─────────────────────────────────────────
        while os.path.exists(target):
            action = show_file_exists_dialog(target)

            if action == _ACTION_REPLACE:
                opts = SaveAsOptions()
                opts.OverwriteExistingFile = True
                doc.SaveAs(target, opts)
                break

            elif action == _ACTION_RENAME:
                nouvelle = show_rename_dialog(user_name)
                if not nouvelle:
                    return
                if not nouvelle.lower().endswith(".rvt"):
                    nouvelle += ".rvt"
                user_name = nouvelle
                target    = os.path.join(folder, user_name)

            else:
                return  # fenêtre fermée (X) → abandon

        else:
            opts = SaveAsOptions()
            opts.OverwriteExistingFile = True
            doc.SaveAs(target, opts)

        show_path_dialog(target)

    except Exception:
        show_alert(u"Erreur inattendue", traceback.format_exc())


main()
