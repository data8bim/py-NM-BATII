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


#__title__ = 'SP - SHON - SHOB → Niveaux et infos projet'
#__doc__ = """Transfert les résulats des calculs de surfaces règlemantaires
#Description : Transfert les résulats des calculs de surfaces règlemantaires vers les niveaux et les informations projet.
#Les valeurs des surfaces porté par les niveaux sont celles qui seront prise en compte par PLANON.
#Un tableau unique : les nomenclatures du projet remplissent ce qu'elles calculent (en lecture seule),
#le reste se saisit à la main ou par un tableur Excel (.xlsx) exporté puis réimporté.

#Version : 4.0 — 2026-07-31
#Auteur : data8bim (d8b)
#"""


import clr

# 1) Charger les assemblies WPF
clr.AddReference("WindowsBase")
clr.AddReference("PresentationCore")
clr.AddReference("PresentationFramework")
clr.AddReference("System.Xaml")

import os
import sys
import re
import json
import codecs
import fnmatch
import traceback
from collections import defaultdict

# 2) 🔥 Ajouter lib/ au sys.path
script_dir = os.path.dirname(__file__)
# QUATRE niveaux : pushbutton -> pulldown -> panel -> tab -> .extension. Le
# bouton a gagne un cran d'imbrication en rejoignant « Donnees des surfaces » ;
# trois os.pardir s'arretaient sur NM-BATII.tab, ou il n'y a pas de lib/.
ext_dir    = os.path.abspath(os.path.join(script_dir, os.pardir, os.pardir,
                                          os.pardir, os.pardir))
lib_dir    = os.path.join(ext_dir, "lib")
if lib_dir not in sys.path:
    sys.path.append(lib_dir)

# 3) 🔥 Charger les styles personnalisés WPF
# show_alert pour tous les messages : ResultWindow.xaml (utilisée par
# show_xaml_message, conservée pour les erreurs de tout dernier recours) est en
# FontSize 25 et SizeToContent="WidthAndHeight" — un chemin de fichier y produit
# une fenêtre démesurée. AlertWindow.xaml est en FontSize 13, bornée à 600 px.
from dialogs.dialogs_styles_loader import load, show_alert
load(lib_dir=lib_dir)

# 4) Imports pour instancier la fenêtre XAML
from System.IO             import File
from System.Windows.Markup import XamlReader
from System.Diagnostics    import Process, ProcessStartInfo

# Contrôles WPF construits à la volée (cases à cocher de filtre) et outils de
# parcours de l'arbre visuel, pour la liste des niveaux à exporter.
from System.Windows.Controls import CheckBox    as _WPFCheckBox
from System.Windows.Controls import ListBoxItem as _ListBoxItem
from System.Windows.Media    import VisualTreeHelper as _VisualTreeHelper
from System.Windows.Input    import Keyboard     as _Keyboard
from System.Windows.Input    import ModifierKeys as _ModifierKeys
from System.Windows          import Thickness         as _Thickness
from System.Windows          import VerticalAlignment as _VerticalAlignment

# Contrôles du tableau « Surfaces du projet », construit ligne par ligne en
# Python (empilement de Border, comme lib/dialogs/mapping_table.py, plutôt
# qu'un DataGrid : pas de binding ni de convertisseur à écrire).
from System.Windows.Controls import (Border, Grid, Panel, TextBlock, TextBox,
                                     ColumnDefinition)
from System.Windows.Documents import Run, LineBreak
from System.Windows.Media    import Brushes, SolidColorBrush, Color
from System.Windows          import (GridLength, GridUnitType, FontWeights,
                                     TextWrapping, TextAlignment, TextTrimming,
                                     HorizontalAlignment, SystemParameters,
                                     Visibility)

# 5) Revit & config
from pyrevit            import forms, script
from Autodesk.Revit.DB  import (
    FilteredElementCollector,
    ViewSchedule,
    SectionType,
    Level,
    StorageType,
    Transaction,
    UnitUtils,
    UnitTypeId
)
from utils.config_loader import load_config
from utils.extrac_nom_fichier_convention import delimiter_from_regex, build_regex
# reload() explicite : le moteur IronPython de pyRevit est partagé et garde en
# cache (sys.modules) la version de surfaces_xlsx chargée au premier lancement.
# Sans cela, une signature modifiée dans lib/ n'est pas vue après un simple
# « Recharger » — seul un redémarrage complet de Revit la prendrait en compte.
import utils.surfaces_xlsx as _surfaces_xlsx_mod
reload(_surfaces_xlsx_mod)
from utils.surfaces_xlsx import (
    ecrire_tableur,
    lire_tableur,
    index_colonne,
    parse_nombre
)


# -------------------------------------------------------------------
def show_xaml_message(message, title="Message"):
    """
    Charge ResultWindow.xaml, assigne Title et txtMessage.Text, puis ShowDialog().
    Utilise FindName() pour retrouver txtMessage et btnClose.
    """
    xaml_path    = os.path.join(script_dir, "ResultWindow.xaml")
    xaml_content = File.ReadAllText(xaml_path)
    window       = XamlReader.Parse(xaml_content)

    # Titre
    window.Title = title

    # Récupération des contrôles nommés
    txt_msg = window.FindName("txtMessage")
    btn     = window.FindName("btnClose")

    if txt_msg is None or btn is None:
        raise Exception("Impossible de trouver txtMessage ou btnClose dans le XAML")

    # Injection du texte
    txt_msg.Text = message

    # Fermer au clic
    btn.Click += lambda s, e: window.Close()

    # Affichage modal
    window.ShowDialog()
# -------------------------------------------------------------------


# Charger la configuration
config   = load_config() or {}
surf_cfg = config.get("surface", {}) or {}
nm_cfg   = config.get("nm_convention_noms_fichiers", {}) or {}

# Paramètres partagés
param_shon     = surf_cfg.get("param_shon",       "ANS - SURFACE - SHON")
param_shob     = surf_cfg.get("param_shob",       "ANS - SURFACE - SHOB")
param_plancher = surf_cfg.get("param_s_plancher", "ANS - SURFACE - S Plancher")

# Noms de colonnes
col_shon       = surf_cfg.get("col_shon",      "SHON")
col_shob       = surf_cfg.get("col_shob",      "SHOB")
col_plancher   = surf_cfg.get("col_plancher",  "Surface Plancher - SP")
col_filter     = surf_cfg.get("col_filter",    "Nom")

# Defaults schedules
default_shon_schedule     = surf_cfg.get("default_shon_schedule")
default_plancher_schedule = surf_cfg.get("default_plancher_schedule")

# Paramètres « Auteur » (Paramètres → Surfaces). Un champ laissé vide désactive
# simplement la traçabilité pour ce type de surface.
param_shon_auteur     = surf_cfg.get("param_shon_auteur",       "")
param_shob_auteur     = surf_cfg.get("param_shob_auteur",       "")
param_plancher_auteur = surf_cfg.get("param_s_plancher_auteur", "")

# Ordre des trois paramètres de surface — repris tel quel par les deux
# méthodes (colonnes du tableur, totaux projet, récapitulatifs).
PARAMS_SURFACE = (param_shon, param_shob, param_plancher)

# Paramètre de surface → paramètre portant l'auteur du calcul.
PARAM_AUTEUR = {
    param_shon:     (param_shon_auteur     or u"").strip(),
    param_shob:     (param_shob_auteur     or u"").strip(),
    param_plancher: (param_plancher_auteur or u"").strip(),
}

# Écrit sur une surface **inchangée** dont l'auteur n'est pas encore renseigné :
# le bilan indique explicitement que le calcul n'est attribué à personne, au
# lieu de laisser une case vide qu'on pourrait croire oubliée. Une surface
# inchangée dont l'auteur est déjà renseigné n'est jamais réécrite.
AUTEUR_NON_RENSEIGNE = u"NON RENSEIGNE"

# Qualifications proposées dans la liste déroulante de l'auteur, gérées dans
# Paramètres → onglet Surfaces. Le repli ne sert que si l'onglet n'a jamais
# été enregistré depuis l'ajout de ce réglage.
QUALIFICATIONS_DEFAUT = [
    u"Géomètre (Surfaces certifiées)",
    u"Architecte (Surfaces certifiées)",
    u"Service Gestion Patrimoine",
]
qualifications_auteur = [
    q.strip() for q in (surf_cfg.get("qualifications_auteur") or [])
    if (q or u"").strip()
]
# Liste absente ou vidée par mégarde : sans repli, la liste déroulante ne
# contiendrait que l'invite et l'écriture serait impossible.
if not qualifications_auteur:
    qualifications_auteur = list(QUALIFICATIONS_DEFAUT)

# Entrée de tête de liste : tant qu'elle est sélectionnée, l'écriture est
# refusée — la qualification doit être un choix explicite.
QUALIFICATION_A_CHOISIR = u"Sélectionnez une qualification"

# Écart en deçà duquel une surface est considérée inchangée (centième de m²,
# précision du tableur et de l'affichage).
TOLERANCE_SURFACE = 0.005

# Libellé de la colonne des niveaux dans le tableur exporté.
COL_NIVEAU = u"Niveau"

doc = __revit__.ActiveUIDocument.Document


def parse_area_value(text):
    """'123,45 m²' → 123.45 (float)"""
    if not text:
        return None
    m = re.search(r"[\d\.,]+", text)
    if not m:
        return None
    try:
        return float(m.group().replace(',', '.'))
    except:
        return None


def find_schedule(name):
    """Retourne la ViewSchedule dont vs.Name == name."""
    for vs in FilteredElementCollector(doc).OfClass(ViewSchedule):
        if vs.Name == name:
            return vs
    return None


def sum_fields_by_level(schedule_name, level_field, value_fields):
    """
    Lit la nomenclature, filtre sur col_filter, puis agrège par niveau.

    Une colonne absente n'est plus une erreur bloquante : depuis que la
    couverture est décidée cellule par cellule, un champ manquant signifie
    simplement « ce paramètre n'est pas calculé ici », et ses cellules
    resteront saisissables. Les anomalies sont donc renvoyées à l'appelant
    plutôt qu'affichées ici.

    Returns:
        tuple: (totals, avertissements)
            totals — { nom_champ: { nom_niveau: m² } }, limité aux champs
            réellement présents et aux niveaux réellement listés ;
            avertissements — liste de messages à présenter à l'utilisateur.
    """
    avertissements = []

    vs = find_schedule(schedule_name)
    if not vs:
        avertissements.append(
            u"Nomenclature introuvable : « {0} ».".format(schedule_name))
        return {}, avertissements

    body       = vs.GetTableData().GetSectionData(SectionType.Body)
    definition = vs.Definition

    # 1) champs visibles
    fields = []
    for i in range(definition.GetFieldCount()):
        f = definition.GetField(i)
        if not f.IsHidden:
            fields.append(f.GetName())

    # 2) index Niveau
    if level_field not in fields:
        avertissements.append(
            u"Champ « {0} » absent de la nomenclature « {1} » : elle ne peut "
            u"pas être rattachée aux niveaux.".format(level_field, schedule_name))
        return {}, avertissements
    idx_lvl = fields.index(level_field)

    # 3) index filtre
    idx_flt = fields.index(col_filter) if col_filter in fields else None

    # 4) index valeurs
    idx_vals = {}
    for vf in value_fields:
        if vf in fields:
            idx_vals[vf] = fields.index(vf)
        else:
            avertissements.append(
                u"Champ « {0} » absent de la nomenclature « {1} » : les "
                u"cellules correspondantes restent saisissables.".format(
                    vf, schedule_name))

    # 5) agrégation
    totals = {vf: defaultdict(float) for vf in idx_vals}
    for r in range(body.NumberOfRows):
        if idx_flt is not None and not body.GetCellText(r, idx_flt).strip():
            continue
        lvl_name = body.GetCellText(r, idx_lvl).strip()
        if not lvl_name:
            continue
        for vf, idx in idx_vals.items():
            area = parse_area_value(body.GetCellText(r, idx))
            if area is not None:
                totals[vf][lvl_name] += area

    return totals, avertissements


# ===================================================================
# Socle commun
# ===================================================================
def code_batiment():
    """
    Extrait le code construction (2e segment du nom de fichier), ou None si
    la convention de nommage n'est pas respectée (un message est alors déjà
    affiché à l'utilisateur).
    """
    file_name = os.path.basename(doc.PathName)
    name_bare = os.path.splitext(file_name)[0]
    delim     = delimiter_from_regex(build_regex(config))
    parts     = name_bare.split(delim)
    if len(parts) < 2 or not parts[1]:
        show_xaml_message(
            "Impossible d'extraire le code construction depuis le nom de fichier.\n"
            "Vérifiez la convention de nommage dans config.json.",
            title="Erreur"
        )
        return None
    return parts[1]


def niveaux_du_batiment(building_code):
    """
    Niveaux du projet dont le nom commence par le code construction, triés
    par altitude **décroissante** — niveau le plus haut en premier, comme dans
    l'arborescence de projet Revit et dans une coupe. Cet ordre est celui de la
    liste de la fenêtre, du tableur exporté et du tableau récapitulatif.
    Renvoie une liste d'éléments Level.
    """
    niveaux = [
        lvl for lvl in FilteredElementCollector(doc).OfClass(Level).ToElements()
        if lvl.Name.startswith(building_code)
    ]
    niveaux.sort(key=lambda l: l.Elevation, reverse=True)
    return niveaux


# --- Filtres par type de niveau -------------------------------------
# Même logique que 01_Lier_CAO et 01_Vues_en_masse : chaque préfixe déclaré
# dans Paramètres → Niveaux donne une case à cocher, regroupée par définition
# (« Batiment », « Toiture »…), plus une case « Autres » pour les niveaux
# qu'aucun préfixe ne reconnaît.
_niv_cfg      = config.get(u"creer_niveaux", {}) or {}
_prefixes_cfg = _niv_cfg.get(u"prefixes", []) or []
_signe_pos    = _niv_cfg.get(u"signe_positif", u"+")
_signe_neg    = _niv_cfg.get(u"signe_negatif", u"-")

# Types cochés à l'ouverture, dans cet ordre d'affichage. Volontairement
# propres à cet outil et non repris de
# « vues_en_masse.filtres_types_niveaux_defaut » : les surfaces réglementaires
# portent sur les niveaux de bâtiment ET de toiture. Les définitions absentes
# de ce tuple viennent ensuite par ordre alphabétique, « Autres » en dernier —
# l'ordre vaut pour la fenêtre d'export comme pour le tableau des surfaces,
# qui partagent construire_filtres_niveaux().
TYPES_AFFICHES_DEFAUT = (u"batiment", u"toiture")

# Niveaux affichés mais décochés à l'ouverture : le niveau de référence de
# toiture ne porte pas de surface réglementaire propre.
NIVEAUX_DECOCHES_DEFAUT = (u"T+00_0",)

_motifs_prefixes = []
for _p in _prefixes_cfg:
    _pfx  = _p.get(u"prefixe", u"")
    _defn = _p.get(u"definition", u"")
    if _pfx:
        _motifs_prefixes.append((
            re.compile(u"_" + re.escape(_pfx)
                       + u"[" + re.escape(_signe_pos) + re.escape(_signe_neg) + u"]"),
            _defn.lower()
        ))


def cle_type_niveau(nom_niveau):
    """Clé de définition du niveau (« batiment », « toiture »…), ou None."""
    for motif, cle in _motifs_prefixes:
        if motif.search(nom_niveau):
            return cle
    return None


def construire_filtres_niveaux():
    """
    Cases à cocher de filtre à créer, dans l'ordre d'affichage.

    Les définitions listées dans TYPES_AFFICHES_DEFAUT viennent en premier et
    dans cet ordre (« Bâtiment - R » puis « Toiture - T »), les autres ensuite
    par ordre alphabétique, « Autres » toujours en dernier. Ce sont aussi les
    seules cochées à l'ouverture.

    Returns:
        list: [(clé, libellé, coché_par_défaut)] — la clé None désigne
        l'entrée « Autres ».
    """
    def_vers_prefixes = {}
    for _p in _prefixes_cfg:
        _defn = _p.get(u"definition", u"")
        _pfx  = _p.get(u"prefixe", u"")
        if _defn:
            def_vers_prefixes.setdefault(_defn, []).append(_pfx)

    def _rang(definition):
        cle = definition.lower()
        if cle in TYPES_AFFICHES_DEFAUT:
            return (0, TYPES_AFFICHES_DEFAUT.index(cle), u"")
        return (1, 0, definition.lower())

    items = []
    for _defn in sorted(def_vers_prefixes.keys(), key=_rang):
        cle = _defn.lower()
        items.append((
            cle,
            u"{0} - {1}".format(_defn, u", ".join(def_vers_prefixes[_defn])),
            cle in TYPES_AFFICHES_DEFAUT
        ))
    items.append((None, u"Autres", False))
    return items


def coche_par_defaut(nom_niveau):
    """Le niveau est-il coché pour l'export à l'ouverture de la fenêtre ?"""
    nom = nom_niveau.lower()
    return not any(terme.lower() in nom for terme in NIVEAUX_DECOCHES_DEFAUT)


def lire_surface_m2(element, nom_param):
    """
    Valeur courante d'un paramètre de surface (en m²), ou None si le
    paramètre est absent, non renseigné ou d'un autre type de stockage.
    """
    prm = element.LookupParameter(nom_param)
    if prm is None or prm.StorageType != StorageType.Double:
        return None
    try:
        if not prm.HasValue:
            return None
        return UnitUtils.ConvertFromInternalUnits(prm.AsDouble(),
                                                  UnitTypeId.SquareMeters)
    except Exception:
        return None


def lire_texte(element, nom_param):
    """Valeur texte courante d'un paramètre, ou u'' si absent/non renseigné."""
    prm = element.LookupParameter(nom_param)
    if prm is None or prm.StorageType != StorageType.String:
        return u""
    try:
        return prm.AsString() or u""
    except Exception:
        return u""


def libelle_auteur(entreprise, qualification):
    """
    Valeur écrite dans les paramètres « Auteur » : nom d'entreprise en
    majuscules, tiret, qualification. Un des deux champs vide fait disparaître
    le séparateur plutôt que de laisser un « - » orphelin.
    """
    nom    = (entreprise or u"").strip().upper()
    qualif = (qualification or u"").strip()
    if nom and qualif:
        return u"{0} - {1}".format(nom, qualif)
    return nom or qualif


def surface_modifiee(actuelle, nouvelle):
    """
    La surface change-t-elle ? Un paramètre encore non renseigné qui reçoit une
    valeur compte comme une modification.
    """
    if nouvelle is None:
        return False
    if actuelle is None:
        return True
    return abs(nouvelle - actuelle) > TOLERANCE_SURFACE


def auteur_a_ecrire(modifiee, auteur_courant, auteur_saisi):
    """
    Valeur à écrire dans le paramètre « Auteur », ou None pour ne rien écrire.

    Règle arrêtée avec l'utilisateur :
      - surface modifiée            → l'entreprise déclarée pour cette exécution
      - surface inchangée, sans auteur → AUTEUR_NON_RENSEIGNE
      - surface inchangée, avec auteur → on n'y touche pas (l'auteur d'un tiers
        ne doit pas être écrasé par une exécution qui n'a rien recalculé)
    """
    if modifiee:
        return auteur_saisi or None
    if not (auteur_courant or u"").strip():
        return AUTEUR_NON_RENSEIGNE
    return None


def tracabilite_active():
    """
    Au moins un paramètre « Auteur » est-il déclaré dans Paramètres →
    Surfaces ? Sinon la déclaration d'auteur n'a rien où s'écrire et le groupe
    de saisie est masqué.
    """
    return any(PARAM_AUTEUR.values())


def entreprise_par_defaut():
    """« Nom de l'organisation » des informations projet, ou u''."""
    try:
        return doc.ProjectInformation.OrganizationName or u""
    except Exception:
        return u""


def qualification_par_defaut():
    """
    Qualification pré-sélectionnée : « Description de l'organisation » des
    informations projet si elle figure dans la liste configurée, sinon
    l'invite QUALIFICATION_A_CHOISIR — l'utilisateur doit alors choisir.
    """
    try:
        description = (doc.ProjectInformation.OrganizationDescription or u"").strip()
    except Exception:
        description = u""
    if description and description in qualifications_auteur:
        return description
    return QUALIFICATION_A_CHOISIR


# --- Réglages « Auteur » retenus d'une session à l'autre --------------
# script.get_data_file() écrit dans %APPDATA%\pyRevit\ : propre à l'utilisateur
# Windows, et toujours accessible en écriture même si l'extension est sur un
# partage réseau. Même mécanique que les fichiers `last_mapping` des autres
# boutons MAPP.
_AUTEUR_PREFS = script.get_data_file('auteur_surfaces', 'NM-Auteur-Surfaces')


def charger_prefs_auteur():
    """
    Réglages « Auteur » personnalisés par l'utilisateur, ou {} s'il n'en a
    jamais posé. La lecture ne doit jamais faire échouer le script : un
    fichier corrompu ou illisible équivaut à une absence de personnalisation.
    """
    if not os.path.isfile(_AUTEUR_PREFS):
        return {}
    try:
        with codecs.open(_AUTEUR_PREFS, 'r', 'utf-8') as f:
            donnees = json.load(f)
        return donnees if isinstance(donnees, dict) else {}
    except Exception:
        return {}


def enregistrer_prefs_auteur(entreprise, qualification):
    """
    Mémorise les seuls réglages qui s'écartent de ce que fournissent les
    informations projet.

    Tant que l'utilisateur se contente du pré-remplissage, rien n'est figé :
    un autre projet, avec un autre « Nom de l'organisation », retrouve donc
    bien sa propre valeur. Revenir au pré-remplissage efface la
    personnalisation précédente (le fichier est réécrit à chaque application).
    """
    prefs      = {}
    entreprise = (entreprise or u"").strip()
    if entreprise and entreprise != (entreprise_par_defaut() or u"").strip():
        prefs['entreprise'] = entreprise
    if qualification and qualification != qualification_par_defaut():
        prefs['qualification'] = qualification
    try:
        with codecs.open(_AUTEUR_PREFS, 'w', 'utf-8') as f:
            json.dump(prefs, f, indent=2, ensure_ascii=False)
    except Exception:
        # Écriture impossible (droits, disque) : sans conséquence sur
        # l'écriture des surfaces, qui vient d'aboutir.
        pass


def entreprise_pre_remplie():
    """Entreprise personnalisée si elle existe, sinon le nom du projet."""
    return charger_prefs_auteur().get('entreprise') or entreprise_par_defaut()


def qualification_pre_remplie():
    """
    Qualification personnalisée si elle existe *et* figure toujours dans la
    liste configurée — celle-ci peut avoir changé dans Paramètres → Surfaces
    depuis, auquel cas la valeur mémorisée ne correspondrait à aucune entrée
    de la liste déroulante.
    """
    qualification = charger_prefs_auteur().get('qualification')
    if qualification and qualification in qualifications_auteur:
        return qualification
    return qualification_par_defaut()


def appliquer_surfaces(donnees, levels, titre_transaction,
                       niveaux_conserves=None, actuelles=None, auteur=None):
    """
    Écrit les surfaces sur les niveaux puis les totaux sur les informations
    projet, dans une seule transaction.

    Parameters:
        donnees (dict): { nom_niveau: { nom_param: surface_m2 } } — niveaux
            dont les paramètres sont réécrits.
        levels (dict): { nom_niveau: élément Level }.
        titre_transaction (str): nom de la transaction Revit.
        niveaux_conserves (dict): { nom_niveau: { nom_param: surface_m2 } }
            optionnel — niveaux dont la surface actuelle est **conservée**
            telle quelle (aucune écriture sur le niveau) mais qui **entrent
            dans les totaux** des informations projet. Sert à la méthode par
            imports : un niveau absent du tableur ne doit ni perdre sa valeur,
            ni disparaître du total du bâtiment.
        actuelles (dict): { nom_niveau: { nom_param: m² | None } } optionnel —
            valeurs portées avant écriture. Sert à déterminer quelles surfaces
            changent réellement, seul cas où l'auteur est réécrit.
        auteur (unicode): valeur à inscrire dans les paramètres « Auteur » des
            surfaces modifiées. None désactive toute écriture d'auteur.

    Returns:
        tuple: (totaux, avertissements)
            totaux — { nom_param: total_m2 } écrit sur les infos projet ;
            avertissements — liste de messages (paramètres absents ou en
            lecture seule), à présenter à l'utilisateur.
    """
    avertissements = []
    totaux         = dict((prm, 0.0) for prm in PARAMS_SURFACE)
    manquants      = set()
    actuelles      = actuelles or {}

    # Traçabilité partielle : signalée, mais non bloquante.
    if auteur:
        sans_auteur = [prm for prm in PARAMS_SURFACE if not PARAM_AUTEUR.get(prm)]
        if sans_auteur:
            avertissements.append(
                u"Aucun paramètre « Auteur » configuré pour : {0} — "
                u"traçabilité non écrite pour ce(s) type(s) de surface.".format(
                    u", ".join(sans_auteur)))
    # Un type de surface dont au moins un niveau change fait porter l'auteur au
    # total correspondant des informations projet.
    projet_modifie = dict((prm, False) for prm in PARAMS_SURFACE)

    def _ecrire_auteur(element, nom_param, modifiee, portee):
        """Applique la règle d'écriture de l'auteur à un élément."""
        nom_auteur = PARAM_AUTEUR.get(nom_param)
        # auteur vide ou None : traçabilité inactive, rien n'est écrit.
        if not nom_auteur or not auteur:
            return
        valeur = auteur_a_ecrire(modifiee, lire_texte(element, nom_auteur), auteur)
        if valeur is None:
            return
        prm = element.LookupParameter(nom_auteur)
        if prm is None:
            manquants.add(u"« {0} » ({1})".format(nom_auteur, portee))
            return
        if prm.IsReadOnly:
            manquants.add(u"« {0} » en lecture seule ({1})".format(nom_auteur, portee))
            return
        prm.Set(valeur)

    t = Transaction(doc, titre_transaction)
    t.Start()
    try:
        # Niveaux hors écriture : comptés dans les totaux, surfaces intactes.
        # Seul l'auteur peut y être complété, et uniquement s'il est vide.
        for nom_niveau, valeurs in (niveaux_conserves or {}).items():
            for nom_param in PARAMS_SURFACE:
                totaux[nom_param] += valeurs.get(nom_param) or 0.0
            lvl_elem = levels.get(nom_niveau)
            if lvl_elem is not None:
                for nom_param in PARAMS_SURFACE:
                    _ecrire_auteur(lvl_elem, nom_param, False, u"niveaux")

        for nom_niveau in sorted(donnees.keys()):
            lvl_elem = levels.get(nom_niveau)
            if lvl_elem is None:
                avertissements.append(u"Niveau absent du projet : {0}".format(nom_niveau))
                continue

            valeurs_avant = actuelles.get(nom_niveau, {})
            for nom_param in PARAMS_SURFACE:
                if nom_param not in donnees[nom_niveau]:
                    continue
                surface = donnees[nom_niveau][nom_param] or 0.0
                totaux[nom_param] += surface

                modifiee = surface_modifiee(valeurs_avant.get(nom_param), surface)
                if modifiee:
                    projet_modifie[nom_param] = True

                prm = lvl_elem.LookupParameter(nom_param)
                if prm is None:
                    manquants.add(u"« {0} » (niveaux)".format(nom_param))
                elif prm.IsReadOnly:
                    manquants.add(u"« {0} » en lecture seule (niveaux)".format(nom_param))
                else:
                    prm.Set(UnitUtils.ConvertToInternalUnits(surface,
                                                              UnitTypeId.SquareMeters))

                _ecrire_auteur(lvl_elem, nom_param, modifiee, u"niveaux")

        proj_info = doc.ProjectInformation
        for nom_param in PARAMS_SURFACE:
            prm = proj_info.LookupParameter(nom_param)
            if prm is None:
                manquants.add(u"« {0} » (informations projet)".format(nom_param))
            elif prm.IsReadOnly:
                manquants.add(u"« {0} » en lecture seule (informations projet)".format(nom_param))
            else:
                prm.Set(UnitUtils.ConvertToInternalUnits(totaux[nom_param],
                                                          UnitTypeId.SquareMeters))

            _ecrire_auteur(proj_info, nom_param, projet_modifie[nom_param],
                           u"informations projet")

        t.Commit()
    except Exception:
        if t.HasStarted() and not t.HasEnded():
            t.RollBack()
        raise

    avertissements.extend(sorted(manquants))
    return totaux, avertissements


def formater_totaux(totaux):
    """Bloc texte des trois totaux projet, pour les récapitulatifs."""
    return u"\n".join(
        u"  {0} : {1:.2f} m²".format(nom_param, totaux.get(nom_param, 0.0))
        for nom_param in PARAMS_SURFACE
    )


# ===================================================================
# Source « nomenclatures » : quelles cellules sont calculées, et à quelle
# valeur. Tout ce que ces nomenclatures ne couvrent pas reste saisissable
# (à la main dans le tableau, ou par import .xlsx).
# ===================================================================
def choisir_nomenclatures():
    """
    Nomenclatures retenues pour SHON/SHOB d'une part, Surface Plancher de
    l'autre. Chacune peut être abandonnée : les paramètres correspondants
    n'ont alors aucune source calculée et deviennent intégralement
    saisissables — c'est ce qui remplace l'ancien parcours « par imports ».

    Returns:
        tuple: (nom_shon_shob | None, nom_plancher | None)
    """
    sched_names = [
        vs.Name
        for vs in FilteredElementCollector(doc).OfClass(ViewSchedule).ToElements()
    ]
    if not sched_names:
        return None, None

    if default_shon_schedule and default_shon_schedule in sched_names:
        shon_name = default_shon_schedule
    else:
        cand = [n for n in sched_names if col_shon in n or col_shob in n] or sched_names
        shon_name = forms.SelectFromList.show(
            cand,
            title=u"Nomenclature SHON / SHOB — Annuler = saisie libre",
            button_name=u"OK")

    plank_cand = [n for n in sched_names if "PLANCHER" in n.upper()]
    if default_plancher_schedule and default_plancher_schedule in plank_cand:
        plancher_name = default_plancher_schedule
    else:
        cand2 = plank_cand or sched_names
        plancher_name = forms.SelectFromList.show(
            cand2,
            title=u"Nomenclature Surface Plancher — Annuler = saisie libre",
            button_name=u"OK")

    return shon_name, plancher_name


def surfaces_calculees(niveaux, building_code, shon_name, plancher_name):
    """
    Surfaces issues des nomenclatures, **cellule par cellule**.

    Un niveau peut être calculé pour un paramètre et pas pour un autre : il
    figure dans une nomenclature mais pas dans l'autre, ou l'une des deux ne
    porte pas la colonne attendue. Seuls les couples (niveau, paramètre)
    réellement présents dans une nomenclature sont retenus — c'est ce qui
    décide ensuite du verrouillage de la cellule.

    Returns:
        tuple: (donnees, avertissements)
            donnees — { nom_niveau: { nom_param: m² } }, restreint aux
            cellules calculées ;
            avertissements — anomalies à présenter (colonne absente, niveau
            cité par une nomenclature mais inconnu du bâtiment…).
    """
    avertissements = []
    par_param      = {}   # nom_param -> { nom_niveau: m² }

    if shon_name:
        totaux, avertis = sum_fields_by_level(
            shon_name, "Niveau", [col_shon, col_shob])
        avertissements.extend(avertis)
        if col_shon in totaux:
            par_param[param_shon] = totaux[col_shon]
        if col_shob in totaux:
            par_param[param_shob] = totaux[col_shob]

    if plancher_name:
        totaux, avertis = sum_fields_by_level(
            plancher_name, "Niveau", [col_plancher])
        avertissements.extend(avertis)
        if col_plancher in totaux:
            par_param[param_plancher] = totaux[col_plancher]

    noms_projet = set(lvl.Name for lvl in niveaux)

    donnees = {}
    for lvl in niveaux:
        valeurs = {}
        for nom_param in PARAMS_SURFACE:
            table = par_param.get(nom_param)
            # `in` et non `.get(nom, 0.0)` : c'est toute la différence entre
            # « pas calculé » (cellule saisissable) et « calculé à 0 »
            # (cellule verrouillée sur 0,00 m²).
            if table is not None and lvl.Name in table:
                valeurs[nom_param] = table[lvl.Name]
        if valeurs:
            donnees[lvl.Name] = valeurs

    # Niveaux cités par une nomenclature, portant bien le code du bâtiment,
    # mais absents du projet : leur surface ne sera reportée nulle part.
    inconnus = set()
    for table in par_param.values():
        for nom in table.keys():
            if nom.startswith(building_code) and nom not in noms_projet:
                inconnus.add(nom)
    if inconnus:
        avertissements.append(
            u"Niveau(x) présent(s) dans une nomenclature mais absent(s) du "
            u"projet, donc ignoré(s) :\n  " + u"\n  ".join(sorted(inconnus)))

    return donnees, avertissements


# ===================================================================
# Échanges avec un tableur (.xlsx) — export puis réimport, depuis le tableau
# ===================================================================
# Suffixe de la colonne qui, dans le tableur exporté, indique d'où vient la
# valeur de la colonne précédente. Purement informatif : à l'import, la
# provenance est redéterminée depuis les nomenclatures du projet, jamais lue
# dans le fichier — sans quoi un fichier retouché pourrait faire passer une
# saisie pour un calcul.
COL_SUFFIXE_SOURCE = u" — source"
SOURCE_NOMENCLATURE = u"Nomenclature (lecture seule)"
SOURCE_SAISIE       = u"Saisie / import"


def exporter_tableur(chemin, niveaux, building_code, valeur_de, est_calculee):
    """
    Écrit le tableur .xlsx des surfaces.

    Chaque paramètre de surface donne deux colonnes : la valeur, puis sa
    provenance. Les cellules calculées par une nomenclature sont exportées
    grisées et verrouillées — elles sont là pour que l'utilisateur contrôle
    ses totaux, pas pour être modifiées.

    Parameters:
        chemin (str): .xlsx à écrire (écrasé s'il existe).
        niveaux (list): éléments Level à exporter, dans l'ordre voulu.
        building_code (unicode): code construction, pour le nom d'onglet.
        valeur_de (callable): (nom_niveau, nom_param) -> m² | None, la valeur
            actuellement retenue dans le tableau (nomenclature ou saisie).
        est_calculee (callable): (nom_niveau, nom_param) -> bool.

    Returns:
        str: le chemin écrit.
    """
    entetes = [COL_NIVEAU]
    for nom_param in PARAMS_SURFACE:
        entetes.append(nom_param)
        entetes.append(nom_param + COL_SUFFIXE_SOURCE)

    lignes  = []
    verrous = set()
    for i, lvl in enumerate(niveaux):
        ligne = [lvl.Name]
        for j, nom_param in enumerate(PARAMS_SURFACE):
            calculee = est_calculee(lvl.Name, nom_param)
            valeur   = valeur_de(lvl.Name, nom_param)
            ligne.append(round(valeur, 2) if valeur is not None else None)
            ligne.append(SOURCE_NOMENCLATURE if calculee else SOURCE_SAISIE)
            # Colonnes : 0 = niveau, puis (valeur, source) par paramètre.
            col_valeur = 1 + j * 2
            if calculee:
                verrous.add((i, col_valeur))
            # La colonne de provenance n'est jamais saisissable.
            verrous.add((i, col_valeur + 1))
        lignes.append(ligne)

    ecrire_tableur(chemin, entetes, lignes,
                   nom_feuille=u"Surfaces {0}".format(building_code),
                   cellules_verrouillees=verrous)
    return chemin


def ouvrir_fichier(chemin):
    """
    Ouvre le fichier avec l'application associée sur le poste.

    Returns:
        bool: False si aucune application n'a pu être lancée (le message
        d'export reste alors le seul retour visible, sans faire échouer
        l'export lui-même).
    """
    # UseShellExecute doit être forcé : sous .NET (Revit 2025+) il vaut False
    # par défaut, et Process.Start refuse alors un document non exécutable.
    psi = ProcessStartInfo(chemin)
    psi.UseShellExecute = True
    try:
        Process.Start(psi)
        return True
    except Exception:
        return False


def lire_donnees_tableur(chemin, niveaux, calculees):
    """
    Lit un tableur renseigné et en extrait les valeurs à reprendre, **cellule
    par cellule**.

    Les cellules déjà couvertes par une nomenclature sont ignorées : les
    calculs du projet priment sur le tableur. Celles qui ont malgré tout été
    modifiées dans le fichier sont listées, pour que l'utilisateur ne croie
    pas sa saisie prise en compte.

    Parameters:
        chemin (str): tableur à lire.
        niveaux (list): niveaux du bâtiment, seuls noms acceptés.
        calculees (dict): { nom_niveau: { nom_param: m² } } issu des
            nomenclatures. La provenance est relue ici depuis le projet, et
            jamais depuis la colonne « source » du fichier : un tableur
            retouché ne doit pas pouvoir faire passer une saisie pour un
            calcul.

    Returns:
        dict: { (nom_niveau, nom_param): m² } à appliquer, ou None si une
        anomalie bloquante a été signalée à l'utilisateur.
    """
    def est_calculee(nom, nom_param):
        return nom in calculees and nom_param in calculees[nom]

    entetes, lignes = lire_tableur(chemin)

    # 1) Repérage des colonnes attendues
    idx_niveau = index_colonne(entetes, COL_NIVEAU)
    if idx_niveau is None:
        show_alert(
            u"Erreur",
            u"Colonne « {0} » introuvable dans le tableur.\n\n"
            u"Colonnes lues :\n  {1}\n\n"
            u"Réexportez le tableur sans renommer les en-têtes.".format(
                COL_NIVEAU, u"\n  ".join(e for e in entetes if e)))
        return None

    # Une colonne de paramètre absente n'est plus bloquante : le tableur peut
    # avoir été produit pour ne renseigner qu'une partie des surfaces.
    idx_params = {}
    absents    = []
    for nom_param in PARAMS_SURFACE:
        idx = index_colonne(entetes, nom_param)
        if idx is None:
            absents.append(nom_param)
        else:
            idx_params[nom_param] = idx
    if not idx_params:
        show_alert(
            u"Erreur",
            u"Aucune colonne de paramètre de surface n'a été reconnue.\n\n"
            u"Colonnes lues :\n  {0}\n\n"
            u"Les en-têtes doivent correspondre aux paramètres configurés "
            u"dans Paramètres → onglet Surfaces.".format(
                u"\n  ".join(e for e in entetes if e)))
        return None

    # 2) Lecture des lignes
    noms_projet = set(lvl.Name for lvl in niveaux)
    valeurs     = {}
    vus         = set()
    inconnus    = []
    doublons    = []
    invalides   = []
    ignorees    = []

    for i, ligne in enumerate(lignes):
        num_ligne = i + 2  # +1 en-tête, +1 pour un numéro de ligne Excel
        brut_nom  = ligne[idx_niveau] if idx_niveau < len(ligne) else None
        if brut_nom is None:
            continue
        nom_niveau = u"{0}".format(brut_nom).strip()
        if not nom_niveau:
            continue

        if nom_niveau not in noms_projet:
            inconnus.append(u"ligne {0} : {1}".format(num_ligne, nom_niveau))
            continue
        if nom_niveau in vus:
            doublons.append(u"ligne {0} : {1}".format(num_ligne, nom_niveau))
            continue
        vus.add(nom_niveau)

        for nom_param, idx in idx_params.items():
            brut = ligne[idx] if idx < len(ligne) else None
            try:
                valeur = parse_nombre(brut)
            except ValueError:
                invalides.append(u"ligne {0}, colonne « {1} » : {2}".format(
                    num_ligne, nom_param, brut))
                continue
            if valeur is not None and valeur < 0:
                invalides.append(
                    u"ligne {0}, colonne « {1} » : valeur négative ({2})".format(
                        num_ligne, nom_param, valeur))
                continue

            if est_calculee(nom_niveau, nom_param):
                # Nomenclature prioritaire : la valeur du fichier n'est reprise
                # dans aucun cas. On ne le signale que si elle diffère, sinon
                # l'utilisateur qui réimporte un export intact serait noyé.
                if valeur is not None and surface_modifiee(
                        valeur, calculees[nom_niveau][nom_param]):
                    ignorees.append(u"{0} — {1}".format(nom_niveau, nom_param))
                continue

            # Cellule vide == 0 m², même règle que dans le tableau.
            valeurs[(nom_niveau, nom_param)] = (
                valeur if valeur is not None else 0.0)

    # 3) Anomalies bloquantes — rien n'est repris tant qu'elles subsistent
    anomalies = []
    if inconnus:
        anomalies.append(u"Nom(s) de niveau ne correspondant à aucun niveau "
                         u"du bâtiment :\n  " + u"\n  ".join(inconnus))
    if doublons:
        anomalies.append(u"Niveau(x) présent(s) plusieurs fois dans le tableur :\n  "
                         + u"\n  ".join(doublons))
    if invalides:
        anomalies.append(u"Valeur(s) non numérique(s) :\n  "
                         + u"\n  ".join(invalides))
    if anomalies:
        show_alert(
            u"Erreur",
            u"Import abandonné, aucune valeur n'a été reprise.\n\n"
            + u"\n\n".join(anomalies))
        return None

    if not valeurs and not ignorees:
        show_alert(
            u"Attention",
            u"Le tableur ne contient aucune valeur exploitable.\n\n"
            u"Les niveaux du bâtiment absents du tableur conservent "
            u"simplement les valeurs affichées dans le tableau.")
        return None

    # 4) Anomalies non bloquantes — l'import a lieu, mais l'utilisateur doit
    #    savoir ce qui n'a pas été repris.
    remarques = []
    if absents:
        remarques.append(u"Colonne(s) absente(s) du tableur, laissée(s) "
                         u"inchangée(s) :\n  " + u"\n  ".join(absents))
    if ignorees:
        remarques.append(
            u"Valeur(s) ignorée(s) car calculée(s) par une nomenclature — "
            u"les nomenclatures sont prioritaires :\n  "
            + u"\n  ".join(sorted(ignorees)))
    if remarques:
        show_alert(u"Import partiel", u"\n\n".join(remarques))

    return valeurs


# --- Tableau « Surfaces du projet », avant écriture ------------------
# Largeur fixe de la colonne « Niveau » ; les colonnes de valeurs se partagent
# le reste. Réduite depuis que l'origine se lit au fond de chaque cellule :
# la colonne ne porte plus que le nom du niveau, sans mention accolée.
_TABLE_LARGEUR_NIVEAU = 150
# Marge interne identique pour l'en-tête, les lignes et les totaux : c'est ce
# qui garantit l'alignement des colonnes entre les trois Grid.
_TABLE_PADDING = _Thickness(6, 4, 6, 4)
# Fond d'une cellule dont la saisie n'est pas un nombre.
_TABLE_FOND_INVALIDE = Brushes.MistyRose
# Fond d'une cellule calculée par une nomenclature, donc en lecture seule.
# Assez soutenu pour se distinguer du WhiteSmoke d'une ligne paire, assez
# discret pour ne pas concurrencer le rouge des valeurs modifiées. Freeze()
# parce que la brosse est partagée par toutes les cellules du tableau.
_TABLE_FOND_CALCULEE = SolidColorBrush(Color.FromRgb(226, 233, 240))
_TABLE_FOND_CALCULEE.Freeze()
# Taille de la mention « (m²) » accolée au nom du paramètre en en-tête : plus
# petite que le texte courant pour que l'en-tête tienne sur une seule ligne.
_TABLE_MENTION_TAILLE = 10

# Traits du quadrillage, façon tableur. Gris foncé plutôt que noir : assez
# soutenu pour tenir sur les fonds de cellule (gris des valeurs calculées,
# rose d'une saisie invalide) sans durcir le tableau.
_TABLE_TRAIT = SolidColorBrush(Color.FromRgb(0x44, 0x44, 0x44))
_TABLE_TRAIT.Freeze()
# Séparateurs de l'en-tête : même teinte que le reste du quadrillage, pour
# qu'aucune ligne du tableau ne détonne. Le nom distinct est conservé car
# _table_separateurs() permet toujours de dissocier les deux si besoin.
_TABLE_TRAIT_ENTETE = _TABLE_TRAIT


def _table_colonnes(grid):
    """Applique les colonnes du tableau à un Grid (en-tête, ligne ou totaux)."""
    cd = ColumnDefinition()
    cd.Width = GridLength(_TABLE_LARGEUR_NIVEAU)
    grid.ColumnDefinitions.Add(cd)
    for _ in PARAMS_SURFACE:
        cd = ColumnDefinition()
        cd.Width = GridLength(1, GridUnitType.Star)
        grid.ColumnDefinitions.Add(cd)
    return grid


def _table_separateurs(grid, brosse=None):
    """
    Traits verticaux entre les cellules — ce qui donne au tableau son aspect
    de tableur. Posés sur le Grid de l'en-tête comme sur celui de chaque
    ligne : les colonnes étant définies à l'identique par _table_colonnes(),
    les traits s'alignent d'une ligne à l'autre.

    À appeler APRÈS avoir ajouté les cellules : un fond de cellule opaque
    (valeur calculée, saisie invalide) recouvrirait sinon le trait de sa
    propre colonne. Tous les traits verticaux du tableau sont ainsi produits
    de la même façon — un Border rempli, jamais un trait de bordure — ce qui
    leur donne exactement le même rendu.
    """
    for i in range(len(PARAMS_SURFACE)):
        sep = Border()
        sep.Width               = 1
        sep.Background          = brosse or _TABLE_TRAIT
        sep.HorizontalAlignment = HorizontalAlignment.Right
        sep.VerticalAlignment   = _VerticalAlignment.Stretch
        sep.SnapsToDevicePixels = True
        Grid.SetColumn(sep, i)
        Panel.SetZIndex(sep, 1)
        grid.Children.Add(sep)
    return grid


def _table_cellule(texte, colonne, gras=False, brosse=None, a_droite=False,
                   mention=None, sans_retour=False, taille=None):
    """
    Une cellule de texte du tableau (lecture seule).

    `mention`, si fourni, est ajouté à la suite de `texte` dans une taille de
    police réduite (_TABLE_MENTION_TAILLE) — cas du nom de niveau suivi de
    « (hors nomenclature) »/« (hors tableur) », ou de l'unité « (m²) » sur les
    en-têtes, pour que la cellule tienne sur une ligne.

    `sans_retour` force une seule ligne (en-têtes) : le texte est tronqué par
    des points de suspension plutôt que de passer à la ligne, ce qui garantit
    la hauteur de la rangée d'en-tête même si la fenêtre est réduite.
    """
    tb = TextBlock()
    # Padding et non Margin : une cellule qui porte un fond (valeur calculée)
    # doit le voir couvrir toute la case, marge comprise. Le TextBlock reste
    # donc etire sur la colonne, et c'est TextAlignment — pas
    # HorizontalAlignment — qui pousse le texte a droite.
    tb.Padding = _TABLE_PADDING
    if sans_retour:
        tb.TextWrapping = TextWrapping.NoWrap
        tb.TextTrimming = TextTrimming.CharacterEllipsis
    else:
        tb.TextWrapping = TextWrapping.Wrap
    if taille is not None:
        tb.FontSize = taille
    if gras:
        tb.FontWeight = FontWeights.Bold
    if brosse is not None:
        tb.Foreground = brosse
    if a_droite:
        tb.TextAlignment = TextAlignment.Right
    if mention:
        tb.Inlines.Add(Run(texte))
        run_mention = Run(u"  " + mention)
        run_mention.FontSize = _TABLE_MENTION_TAILLE
        tb.Inlines.Add(run_mention)
    else:
        tb.Text = texte
    Grid.SetColumn(tb, colonne)
    return tb


def _table_cellule_calculee(texte, colonne):
    u"""
    Cellule en lecture seule (valeur calculée par une nomenclature) : fond
    coloré remplissant toute la case, texte à droite.

    Returns:
        tuple: (Border à placer dans la ligne, TextBlock dont la couleur de
        texte est pilotée par _rafraichir).
    """
    tb = TextBlock()
    tb.Text          = texte
    tb.Padding       = _TABLE_PADDING
    tb.TextWrapping  = TextWrapping.Wrap
    tb.TextAlignment = TextAlignment.Right

    # Pas de BorderThickness ici : le trait de séparation est posé par
    # _table_separateurs(), appelé après les cellules donc dessiné par-dessus
    # ce fond. Un trait de bordure porté par la cellule aurait un rendu
    # différent des autres — un trait de 1 px est lissé sur deux pixels aux
    # échelles d'affichage non entières, et paraît alors plus clair.
    cadre = Border()
    cadre.Child              = tb
    cadre.Background         = _TABLE_FOND_CALCULEE
    cadre.SnapsToDevicePixels = True
    Grid.SetColumn(cadre, colonne)
    return cadre, tb


def _table_saisie(texte, colonne):
    """
    Une cellule de saisie du tableau (méthode par imports). Le gestionnaire
    TextChanged est branché par l'appelant, qui a besoin du contrôle lui-même
    pour le construire.

    Bordure et fond sont mis à plat *localement* : le quadrillage et l'alternance
    de couleur des lignes doivent transparaître, comme dans un tableur. Ces
    valeurs locales écrasent volontairement les Setter de NMTextBoxStandard.
    """
    tb = TextBox()
    tb.Text            = texte
    tb.Margin          = _Thickness(0)
    tb.Padding         = _TABLE_PADDING
    tb.BorderThickness = _Thickness(0)
    tb.Background      = Brushes.Transparent
    tb.TextAlignment   = TextAlignment.Right
    tb.VerticalContentAlignment = _VerticalAlignment.Center
    Grid.SetColumn(tb, colonne)
    return tb


def _table_format(valeur):
    """Surface affichée, ou tiret cadratin si le paramètre n'est pas renseigné."""
    if valeur is None:
        return u"—"
    return u"{0:,.2f}".format(valeur).replace(u",", u" ").replace(u".", u",")


def _table_format_saisie(valeur):
    """Comme _table_format, mais une cellule de saisie vide vaut 0 m²."""
    if valeur is None:
        return u""
    return u"{0:,.2f}".format(valeur).replace(u",", u" ").replace(u".", u",")


def afficher_tableau_surfaces(niveaux, donnees, actuelles, building_code):
    u"""
    Tableau « Surfaces du projet » présenté AVANT écriture : un niveau par
    ligne, une colonne par paramètre de surface, une ligne de totaux.

    Point d'entrée unique de l'outil. Les trois modes de renseignement y
    cohabitent, **cellule par cellule** :
      - calculée par une nomenclature → fond gris, lecture seule ;
      - saisie manuelle ou import .xlsx → fond de ligne, saisissable ;
      - dans les deux cas, texte rouge si la valeur va changer.
    Un même niveau peut donc être calculé pour un paramètre et saisi pour un
    autre : c'est `donnees` qui le dit, couple par couple.

    La fenêtre porte aussi le groupe « Auteur des calculs de surfaces »
    (entreprise + qualification) : l'auteur retenu est renvoyé avec les
    données.

    Parameters:
        niveaux (list): éléments Level à afficher, dans l'ordre voulu.
        donnees (dict): { nom_niveau: { nom_param: m² } } valeurs calculées
            par les nomenclatures, restreint aux cellules réellement
            couvertes. Tout le reste est saisissable.
        actuelles (dict): { nom_niveau: { nom_param: m² | None } } valeurs
            portées aujourd'hui par les niveaux.
        building_code (unicode): code construction, pour l'export .xlsx.

    Returns:
        tuple: (valide, donnees_finales, auteur)
            valide — True si l'utilisateur clique sur « Appliquer » ;
            donnees_finales — les valeurs retenues, augmentées des niveaux
            non calculés dont au moins une cellule a été corrigée ;
            auteur — « ENTREPRISE - qualification » à inscrire, ou u'' si
            aucun paramètre « Auteur » n'est configuré.
    """
    dlg = forms.WPFWindow(os.path.join(script_dir, "SurfacesProjetDialog.xaml"))
    # Cellules saisissables : « Appliquer » ne doit pas rester le bouton par
    # défaut, sinon la touche Entrée frappée dans une cellule valide et ferme
    # la fenêtre au lieu de confirmer la saisie.
    dlg.btnApply.IsDefault = False

    # ── Auteur des calculs ───────────────────────────────────────────
    # Le groupe remplace l'ancienne fenêtre séparée. Masqué si aucun
    # paramètre « Auteur » n'est configuré : il n'y aurait rien où écrire.
    tracabilite = tracabilite_active()
    if tracabilite:
        # Réglages retenus de la session précédente s'il y en a, sinon les
        # informations projet (cf. entreprise_pre_remplie).
        dlg.txtEntreprise.Text = entreprise_pre_remplie()
        dlg.cmbQualification.ItemsSource = (
            [QUALIFICATION_A_CHOISIR] + list(qualifications_auteur))
        dlg.cmbQualification.SelectedItem = qualification_pre_remplie()
    else:
        dlg.grpAuteur.Visibility = Visibility.Collapsed

    def _qualification_choisie():
        u"""Qualification retenue, ou u'' tant que l'invite est sélectionnée."""
        valeur = dlg.cmbQualification.SelectedItem
        if valeur is None or valeur == QUALIFICATION_A_CHOISIR:
            return u""
        return u"{0}".format(valeur)

    def _auteur_courant():
        return libelle_auteur(dlg.txtEntreprise.Text, _qualification_choisie())

    def _maj_apercu(sender=None, args=None):
        if not tracabilite:
            return
        apercu = _auteur_courant()
        dlg.txtApercuAuteur.Text = (
            u"Inscrit sur les surfaces modifiées : {0}".format(apercu)
            if apercu else
            u"Renseignez l'entreprise et choisissez une qualification.")

    if tracabilite:
        dlg.txtEntreprise.TextChanged        += _maj_apercu
        dlg.cmbQualification.SelectionChanged += _maj_apercu
        _maj_apercu()

    a_du_hors_source = any(
        lvl.Name not in donnees or nom_param not in donnees[lvl.Name]
        for lvl in niveaux for nom_param in PARAMS_SURFACE
    )
    # Une phrase par ligne, libellé en gras : plus lisible qu'un paragraphe
    # compact. `txtLegende` (TextWrapping="Wrap") absorbe les lignes trop
    # longues sans perdre le retour explicite entre elles.
    lignes_legende = [
        (u"Fond gris : ",
         u"valeur calculée par une nomenclature, en lecture seule — les "
         u"nomenclatures sont prioritaires sur toute saisie.")
    ]
    if a_du_hors_source:
        lignes_legende.append(
            (u"Fond clair : ",
             u"valeur libre, modifiable ici ou par import .xlsx ; une "
             u"cellule vide vaut 0,00 m²."))
    lignes_legende.append(
        (u"Texte rouge : ",
         u"valeur qui sera modifiée, et sur laquelle l'auteur sera inscrit."))
    lignes_legende.append(
        (u"Les filtres : ",
         u"ne masquent que l'affichage. Les totaux portent toujours sur "
         u"tous les niveaux du bâtiment."))
    if not tracabilite:
        lignes_legende.append(
            (None,
             u"Aucun paramètre « Auteur » n'est configuré dans Paramètres → "
             u"Surfaces : la traçabilité ne sera pas écrite."))

    dlg.txtLegende.Inlines.Clear()
    for i, (libelle, reste) in enumerate(lignes_legende):
        if i > 0:
            dlg.txtLegende.Inlines.Add(LineBreak())
        if libelle:
            run_libelle = Run(libelle)
            run_libelle.FontWeight = FontWeights.Bold
            # Noir explicite : txtLegende hérite du gris #666666 posé dans le
            # XAML, qui adoucirait sinon le gras au lieu de le faire ressortir.
            run_libelle.Foreground = Brushes.Black
            dlg.txtLegende.Inlines.Add(run_libelle)
        dlg.txtLegende.Inlines.Add(Run(reste))

    # ── En-tête ──────────────────────────────────────────────────────
    grille = _table_colonnes(Grid())
    grille.Children.Add(_table_cellule(u"Niveau", 0, gras=True,
                                       brosse=Brushes.White,
                                       sans_retour=True))
    for i, nom_param in enumerate(PARAMS_SURFACE):
        grille.Children.Add(_table_cellule(
            nom_param, i + 1, gras=True,
            brosse=Brushes.White, a_droite=True,
            mention=u"(m²)", sans_retour=True, taille=12))
    _table_separateurs(grille, _TABLE_TRAIT_ENTETE)
    marge_defilement = _Thickness(0, 0, 0, 0)
    try:
        marge_defilement = _Thickness(
            0, 0, SystemParameters.VerticalScrollBarWidth, 0)
    except Exception:
        pass
    dlg.headerHost.Margin = marge_defilement
    dlg.headerHost.Child  = grille

    # Valeurs retenues, cellules de saisie et totaux : l'état vit ici, et
    # _rafraichir() le reprojette sur l'affichage à chaque frappe.
    saisies            = {}   # (nom_niveau, nom_param) -> float | None
    invalides          = {}   # (nom_niveau, nom_param) -> bool
    controles          = {}   # (nom_niveau, nom_param) -> TextBox (saisissable)
    controles_calcules = {}   # (nom_niveau, nom_param) -> TextBlock (calculé)
    controles_total    = {}   # nom_param -> TextBlock

    def _issue_source(nom, nom_param):
        u"""
        Cette cellule est-elle calculée par une nomenclature ? La question se
        pose couple par couple : un même niveau peut être calculé pour la SHON
        et laissé libre pour la Surface Plancher.
        """
        return nom in donnees and nom_param in donnees[nom]

    def _cellule_editable(nom, nom_param):
        # Règle unique de l'outil : les nomenclatures priment, tout le reste
        # est saisissable (à la main ou par import .xlsx).
        return not _issue_source(nom, nom_param)

    def _valeur_retenue(nom, nom_param):
        u"""
        Surface prise en compte pour cette cellule : la saisie si
        l'utilisateur l'a touchée (ou si un import l'a renseignée), sinon la
        valeur calculée, sinon celle déjà en place sur le niveau.
        """
        if (nom, nom_param) in saisies:
            return saisies[(nom, nom_param)]
        if _issue_source(nom, nom_param):
            return donnees[nom][nom_param]
        return actuelles.get(nom, {}).get(nom_param)

    def _totaux_et_modifs():
        u"""
        Totaux projet, colonnes concernées et état de chaque cellule. Une
        cellule est « modifiée » dès que sa valeur retenue s'écarte de celle
        portée aujourd'hui par le niveau — y compris sur un niveau hors
        tableur que l'utilisateur vient de corriger : c'est ce même critère
        qui décide de l'écriture de l'auteur.
        """
        totaux  = dict((prm, 0.0) for prm in PARAMS_SURFACE)
        modifs  = dict((prm, False) for prm in PARAMS_SURFACE)
        par_cel = {}
        for lvl in niveaux:
            nom = lvl.Name
            for nom_param in PARAMS_SURFACE:
                valeur   = _valeur_retenue(nom, nom_param)
                actuelle = actuelles.get(nom, {}).get(nom_param)
                modifiee = surface_modifiee(actuelle, valeur)
                par_cel[(nom, nom_param)] = modifiee
                if modifiee:
                    modifs[nom_param] = True
                totaux[nom_param] += valeur or 0.0
        return totaux, modifs, par_cel

    def _niveau_corrige(nom):
        u"""Niveau hors tableur dont l'utilisateur a changé au moins une
        cellule : il doit entrer dans l'écriture."""
        for nom_param in PARAMS_SURFACE:
            if surface_modifiee(actuelles.get(nom, {}).get(nom_param),
                                _valeur_retenue(nom, nom_param)):
                return True
        return False

    def _rafraichir(sender=None, args=None):
        totaux, modifs, par_cel = _totaux_et_modifs()
        for cle, ctrl in controles.items():
            if invalides.get(cle):
                ctrl.Background = _TABLE_FOND_INVALIDE
                ctrl.Foreground = Brushes.Black
            else:
                # Transparent, pas ClearValue : le fond doit laisser voir
                # l'alternance de couleur de la ligne, comme dans un tableur.
                ctrl.Background = Brushes.Transparent
                ctrl.Foreground = (Brushes.Red if par_cel.get(cle)
                                   else Brushes.Black)
        # Une valeur calculée aussi peut différer de celle portée aujourd'hui
        # par le niveau : elle sera écrite, donc elle doit apparaître en rouge
        # au même titre qu'une saisie.
        for cle, ctrl in controles_calcules.items():
            ctrl.Foreground = (Brushes.Red if par_cel.get(cle)
                               else Brushes.Black)
        for nom_param, ctrl in controles_total.items():
            ctrl.Text       = _table_format(totaux[nom_param])
            ctrl.Foreground = (Brushes.Red if modifs[nom_param]
                               else Brushes.Black)

    def _mk_handler(nom, nom_param, ctrl):
        def _on_change(sender, args):
            texte = ctrl.Text
            if not (texte or u"").strip():
                # Cellule vidée : 0 m², même règle que dans le tableur.
                saisies[(nom, nom_param)] = 0.0
                invalides[(nom, nom_param)] = False
            else:
                try:
                    valeur = parse_nombre(texte)
                except ValueError:
                    invalides[(nom, nom_param)] = True
                else:
                    if valeur is not None and valeur < 0:
                        invalides[(nom, nom_param)] = True
                    else:
                        saisies[(nom, nom_param)] = valeur
                        invalides[(nom, nom_param)] = False
            _rafraichir()
        return _on_change

    # ── Filtres par type de niveau ───────────────────────────────────
    # Le tableau contient TOUS les niveaux du bâtiment ; les cases décident de
    # ceux qui sont affichés. Elles ne masquent que l'affichage : les totaux et
    # l'écriture portent toujours sur l'ensemble, y compris les niveaux
    # décochés.
    filtres = []

    def _niveaux_visibles():
        if not filtres:
            return list(niveaux)
        cles_actives = set()
        autres_actif = False
        for cle, case in filtres:
            if case.IsChecked:
                if cle is None:
                    autres_actif = True
                else:
                    cles_actives.add(cle)
        visibles = []
        for lvl in niveaux:
            cle = cle_type_niveau(lvl.Name)
            if (cle in cles_actives) or (cle is None and autres_actif):
                visibles.append(lvl)
        return visibles

    def _construire_lignes(sender=None, args=None):
        u"""
        (Re)construit les lignes affichées. Appelée à l'ouverture puis à chaque
        changement de filtre : les valeurs saisies survivent, elles vivent dans
        `saisies` et non dans les contrôles, qui sont recréés.
        """
        controles.clear()
        controles_calcules.clear()
        dlg.rowsPanel.Children.Clear()
        for rang, lvl in enumerate(_niveaux_visibles()):
            nom   = lvl.Name
            ligne = _table_colonnes(Grid())
            # Plus de mention « hors nomenclature » accolée au nom : l'origine
            # se lit désormais cellule par cellule, au fond de chacune.
            ligne.Children.Add(_table_cellule(nom, 0))

            for i, nom_param in enumerate(PARAMS_SURFACE):
                valeur = _valeur_retenue(nom, nom_param)
                if _cellule_editable(nom, nom_param):
                    # Corriger la cellule d'un niveau non calculé le fait
                    # entrer dans l'écriture (cf. _niveau_corrige).
                    invalides.setdefault((nom, nom_param), False)
                    ctrl = _table_saisie(_table_format_saisie(valeur), i + 1)
                    ctrl.TextChanged += _mk_handler(nom, nom_param, ctrl)
                    controles[(nom, nom_param)] = ctrl
                    ligne.Children.Add(ctrl)
                else:
                    # Calculée : fond gris pour la distinguer d'une cellule
                    # libre, et pas de zone de saisie — donc non modifiable.
                    cadre, texte_ctrl = _table_cellule_calculee(
                        _table_format(valeur), i + 1)
                    controles_calcules[(nom, nom_param)] = texte_ctrl
                    ligne.Children.Add(cadre)

            # Après les cellules : les traits passent ainsi par-dessus les
            # fonds opaques (valeur calculée, saisie invalide).
            _table_separateurs(ligne)

            bordure                 = Border()
            bordure.Child           = ligne
            bordure.BorderThickness = _Thickness(1, 0, 1, 1)
            bordure.BorderBrush     = _TABLE_TRAIT
            bordure.SnapsToDevicePixels = True
            bordure.Background      = (Brushes.White if rang % 2 == 0
                                       else Brushes.WhiteSmoke)
            dlg.rowsPanel.Children.Add(bordure)
        _rafraichir()

    # ── Ligne de totaux ──────────────────────────────────────────────
    # Construite AVANT les lignes : _construire_lignes() termine par
    # _rafraichir(), qui met à jour les cellules de totaux.
    totaux, modifs, par_cel = _totaux_et_modifs()
    ligne_totaux = _table_colonnes(Grid())
    ligne_totaux.Children.Add(_table_cellule(
        u"TOTAL — infos projet", 0, gras=True))
    for i, nom_param in enumerate(PARAMS_SURFACE):
        cellule = _table_cellule(
            _table_format(totaux[nom_param]), i + 1, gras=True,
            brosse=Brushes.Red if modifs[nom_param] else Brushes.Black,
            a_droite=True)
        controles_total[nom_param] = cellule
        ligne_totaux.Children.Add(cellule)
    _table_separateurs(ligne_totaux)
    dlg.totalHost.Margin = marge_defilement
    dlg.totalHost.Child  = ligne_totaux

    # ── Filtres puis lignes ──────────────────────────────────────────
    # Mêmes cases, même ordre et mêmes cases cochées que la fenêtre d'export :
    # « Bâtiment - R » et « Toiture - T » à l'ouverture, les autres types
    # restant accessibles d'un clic.
    for cle, libelle, coche in construire_filtres_niveaux():
        case = _WPFCheckBox()
        case.Content   = libelle
        case.IsChecked = coche
        case.Margin    = _Thickness(0, 0, 12, 2)
        case.VerticalContentAlignment = _VerticalAlignment.Center
        dlg.pnlFiltresTypes.Children.Add(case)
        filtres.append((cle, case))
        case.Checked   += _construire_lignes
        case.Unchecked += _construire_lignes

    # ── Bouton « remettre à 0 » ──────────────────────────────────────
    # Porte exactement sur les cellules saisissables, c'est-à-dire celles
    # qu'aucune nomenclature ne calcule.
    if a_du_hors_source:
        dlg.btnZeroHorsSource.Content = u"Valeurs hors nomenclature à 0"
        dlg.btnZeroHorsSource.ToolTip = (
            u"Remet à 0,00 m² toutes les valeurs qu'aucune nomenclature ne "
            u"calcule, y compris celles masquées par un filtre.")

        def _remettre_a_zero(sender, args):
            for lvl in niveaux:
                for nom_param in PARAMS_SURFACE:
                    if _issue_source(lvl.Name, nom_param):
                        continue
                    saisies[(lvl.Name, nom_param)]   = 0.0
                    invalides[(lvl.Name, nom_param)] = False
            # Reconstruction : les zones de saisie portent leur texte, il faut
            # les recréer pour qu'elles affichent le 0.
            _construire_lignes()

        dlg.btnZeroHorsSource.Click += _remettre_a_zero
    else:
        dlg.btnZeroHorsSource.Visibility = Visibility.Collapsed

    # ── Échanges tableur ─────────────────────────────────────────────
    def _on_export(sender, args):
        niveaux_choisis = choisir_niveaux_export(niveaux)
        if not niveaux_choisis:
            return

        dossier_init = os.path.dirname(doc.PathName) if doc.PathName else ""
        base_nom     = os.path.splitext(os.path.basename(doc.PathName))[0] \
                       if doc.PathName else doc.Title
        chemin = forms.save_file(
            file_ext="xlsx",
            init_dir=dossier_init,
            default_name=u"{0}_Surfaces-niveaux.xlsx".format(
                base_nom or u"Projet"),
            title=u"Exporter le tableur des surfaces par niveau")
        if not chemin:
            return
        # forms.save_file ne force pas l'extension si l'utilisateur la retire.
        if not chemin.lower().endswith(".xlsx"):
            chemin += ".xlsx"

        try:
            # L'export part de l'état affiché — saisies en cours comprises —
            # et non des valeurs portées par le modèle : ce que l'utilisateur
            # voit est ce qu'il retrouve dans le tableur.
            exporter_tableur(chemin, niveaux_choisis, building_code,
                             _valeur_retenue, _issue_source)
        except Exception:
            show_alert(u"Erreur à l'export", traceback.format_exc())
            return

        message = u"**{0}** niveau(x) exporté(s) dans **{1}**.\n\n" \
                  u"Renseignez les cellules non grisées, puis revenez " \
                  u"importer le fichier.".format(
                      len(niveaux_choisis), os.path.basename(chemin))
        if not ouvrir_fichier(chemin):
            message += u"\n\nLe tableur n'a pas pu être ouvert " \
                       u"automatiquement, ouvrez-le depuis :\n{0}".format(
                           os.path.dirname(chemin))
        show_alert(u"Export terminé", message)

    def _on_import(sender, args):
        dossier_init = os.path.dirname(doc.PathName) if doc.PathName else ""
        chemin = forms.pick_file(
            file_ext="xlsx",
            init_dir=dossier_init,
            title=u"Choisir le tableur des surfaces renseigné")
        if not chemin:
            return

        try:
            valeurs = lire_donnees_tableur(chemin, niveaux, donnees)
        except Exception:
            show_alert(u"Erreur à l'import", traceback.format_exc())
            return
        if not valeurs:
            return

        # L'import alimente les mêmes `saisies` que la frappe au clavier :
        # rien n'est écrit dans le modèle, l'utilisateur garde la main jusqu'à
        # « Appliquer ».
        for cle, valeur in valeurs.items():
            saisies[cle]   = valeur
            invalides[cle] = False
        _construire_lignes()

        show_alert(
            u"Import terminé",
            u"**{0}** valeur(s) reprise(s) depuis **{1}**.\n\n"
            u"Vérifiez le tableau puis appliquez.".format(
                len(valeurs), os.path.basename(chemin)))

    dlg.btnExport.Click += _on_export
    dlg.btnImport.Click += _on_import

    _construire_lignes()

    valide = {"ok": False, "auteur": u""}

    def _appliquer(sender, args):
        # Saisies non numériques : contrôlées ici plutôt qu'en désactivant le
        # bouton, car un filtre peut masquer la cellule fautive — un bouton
        # grisé sans explication laisserait l'utilisateur bloqué.
        fautives = sorted(cle for cle, ko in invalides.items() if ko)
        if fautives:
            show_alert(
                u"Valeurs non numériques",
                u"Corrigez ces cellules avant d'appliquer :\n  {0}\n\n"
                u"Attendu : un nombre de m² (une cellule vide vaut 0,00).".format(
                    u"\n  ".join(u"{0} — {1}".format(nom, prm)
                                 for nom, prm in fautives)),
                close_label=u"Retour")
            return
        if tracabilite:
            # Refus d'écrire tant que la qualification n'est pas choisie : le
            # dialogue reste ouvert, le message dit quoi corriger.
            if not _qualification_choisie():
                show_alert(
                    u"Qualification manquante",
                    u"Choisissez une qualification dans la liste « {0} » avant "
                    u"d'appliquer.\n\nElle qualifie la fiabilité des surfaces "
                    u"écrites dans le bilan.".format(u"Qualification"),
                    close_label=u"Retour")
                dlg.cmbQualification.Focus()
                return
            if not (dlg.txtEntreprise.Text or u"").strip():
                show_alert(
                    u"Entreprise manquante",
                    u"Renseignez le nom de l'entreprise ayant réalisé les "
                    u"calculs avant d'appliquer.",
                    close_label=u"Retour")
                dlg.txtEntreprise.Focus()
                return
            valide["auteur"] = _auteur_courant()
            # Mémorisé seulement une fois la saisie validée : les deux champs
            # sont alors renseignés, et l'utilisateur a confirmé son choix en
            # appliquant. Fermer par Annuler ne retient donc rien.
            enregistrer_prefs_auteur(dlg.txtEntreprise.Text,
                                     _qualification_choisie())
        valide["ok"] = True
        setattr(dlg, "DialogResult", True)

    dlg.btnApply.Click += _appliquer
    dlg.show_dialog()

    if not valide["ok"]:
        return False, donnees, u""

    # Niveaux à écrire : ceux de la source, plus ceux qui n'en venaient pas
    # mais dont l'utilisateur a corrigé une cellule (saisie manuelle ou
    # remise à 0). Les autres restent conservés.
    donnees_finales = {}
    for lvl in niveaux:
        nom = lvl.Name
        if nom not in donnees and not _niveau_corrige(nom):
            continue
        donnees_finales[nom] = dict(
            (nom_param, _valeur_retenue(nom, nom_param) or 0.0)
            for nom_param in PARAMS_SURFACE
        )
    return True, donnees_finales, valide["auteur"]


def choisir_niveaux_export(niveaux):
    """
    Choix des niveaux à faire figurer dans le tableur exporté.

    Reprend la liste à cases à cocher de 01_Lier_CAO : filtre texte, filtres
    par type de niveau, et sélection en masse. Seuls les niveaux cochés *et
    affichés* sont retenus — un niveau masqué par un filtre n'entre pas dans
    le tableur, même si son état coché est conservé pour le cas où le filtre
    serait rouvert.

    Returns:
        list: éléments Level retenus, vide si l'utilisateur annule.
    """
    xaml = os.path.join(script_dir, "ExportSurfacesDialog.xaml")
    dlg  = forms.WPFWindow(xaml)
    retenus = {"niveaux": []}

    # --- Liste des niveaux à exporter --------------------------------
    ordre_niveaux = [lvl.Name for lvl in niveaux]
    # Coché au départ : tout sauf les niveaux de référence sans surface
    # propre (cf. NIVEAUX_DECOCHES_DEFAUT).
    etat     = {"selection": set(n for n in ordre_niveaux
                                 if coche_par_defaut(n))}
    filtres  = []  # (clé, case à cocher), rempli après création de la fenêtre

    def _memoriser_selection():
        """
        Reporte dans etat['selection'] l'état des seules lignes affichées :
        un niveau masqué par un filtre conserve son état précédent.
        """
        affiches   = list(dlg.lstNiveaux.Items)
        selection  = set(dlg.lstNiveaux.SelectedItems)
        for nom in affiches:
            if nom in selection:
                etat["selection"].add(nom)
            else:
                etat["selection"].discard(nom)

    def _rafraichir_liste(sender=None, args=None):
        _memoriser_selection()

        noms = ordre_niveaux
        if filtres:
            cles_actives = set()
            autres_actif = False
            for cle, case in filtres:
                if case.IsChecked:
                    if cle is None:
                        autres_actif = True
                    else:
                        cles_actives.add(cle)
            noms = [n for n in noms
                    if (cle_type_niveau(n) in cles_actives)
                    or (cle_type_niveau(n) is None and autres_actif)]

        motif = dlg.txtListFilter.Text.strip().lower()
        if motif:
            if u'*' in motif:
                noms = [n for n in noms if fnmatch.fnmatch(n.lower(), motif)]
            else:
                noms = [n for n in noms if motif in n.lower()]

        dlg.lstNiveaux.ItemsSource = noms
        for nom in noms:
            if nom in etat["selection"]:
                dlg.lstNiveaux.SelectedItems.Add(nom)

    for cle, libelle, coche in construire_filtres_niveaux():
        case = _WPFCheckBox()
        case.Content   = libelle
        case.IsChecked = coche
        case.Margin    = _Thickness(0, 0, 12, 2)
        case.VerticalContentAlignment = _VerticalAlignment.Center
        dlg.pnlFiltresTypes.Children.Add(case)
        filtres.append((cle, case))
        case.Checked   += _rafraichir_liste
        case.Unchecked += _rafraichir_liste

    dlg.txtListFilter.TextChanged += _rafraichir_liste
    _rafraichir_liste()

    def _tout_selectionner(sender, args):
        for item in dlg.lstNiveaux.Items:
            if not dlg.lstNiveaux.SelectedItems.Contains(item):
                dlg.lstNiveaux.SelectedItems.Add(item)

    def _tout_deselectionner(sender, args):
        dlg.lstNiveaux.SelectedItems.Clear()

    def _inverser_selection(sender, args):
        nouvelle = [item for item in dlg.lstNiveaux.Items
                    if not dlg.lstNiveaux.SelectedItems.Contains(item)]
        dlg.lstNiveaux.SelectedItems.Clear()
        for item in nouvelle:
            dlg.lstNiveaux.SelectedItems.Add(item)

    def _clic_ligne(sender, e):
        # Clic sur la case à cocher elle-même : comportement standard inchangé.
        d = e.OriginalSource
        while d is not None and not isinstance(d, _ListBoxItem):
            if isinstance(d, _WPFCheckBox):
                return
            d = _VisualTreeHelper.GetParent(d)
        if d is None:
            return
        # Maj+clic (plage) et Ctrl+clic (ajout/retrait) : comportement standard
        # du ListBox inchangé.
        mods = _Keyboard.Modifiers
        if (mods & _ModifierKeys.Shift) == _ModifierKeys.Shift or \
           (mods & _ModifierKeys.Control) == _ModifierKeys.Control:
            return
        # Clic simple ailleurs sur la ligne : bascule cette seule ligne sans
        # désélectionner les autres (même effet que la case à cocher).
        d.IsSelected = not d.IsSelected
        e.Handled = True

    dlg.btnSelectAll.Click   += _tout_selectionner
    dlg.btnDeselectAll.Click += _tout_deselectionner
    dlg.btnInvert.Click      += _inverser_selection
    dlg.lstNiveaux.PreviewMouseLeftButtonDown += _clic_ligne

    def _valider(sender, args):
        _memoriser_selection()
        noms_choisis = set(dlg.lstNiveaux.SelectedItems)
        choisis      = [lvl for lvl in niveaux if lvl.Name in noms_choisis]
        if not choisis:
            show_alert(u"Attention",
                       u"Aucun niveau sélectionné. Cochez au moins un niveau "
                       u"à exporter.")
            return
        retenus["niveaux"] = choisis
        setattr(dlg, "DialogResult", True)

    dlg.btnOk.Click += _valider
    dlg.show_dialog()
    return retenus["niveaux"]


# ===================================================================
# Point d'entrée
# ===================================================================
def main():
    # Les en-têtes du tableur sont les noms des paramètres : un champ laissé
    # vide dans Paramètres → Surfaces rendrait la colonne inexploitable, et
    # l'écriture sur les niveaux impossible.
    non_configures = [
        libelle
        for libelle, nom_param in [(u"Param. SHON",             param_shon),
                                   (u"Param. SHOB",             param_shob),
                                   (u"Param. Surface Plancher", param_plancher)]
        if not (nom_param or u"").strip()
    ]
    if non_configures:
        show_alert(
            u"Configuration incomplète",
            u"Paramètre(s) non renseigné(s) dans Paramètres → onglet "
            u"Surfaces :\n  {0}\n\nComplétez la configuration avant de "
            u"lancer l'outil.".format(u"\n  ".join(non_configures)))
        return

    building_code = code_batiment()
    if not building_code:
        return

    niveaux = niveaux_du_batiment(building_code)
    if not niveaux:
        show_alert(
            u"Attention",
            u"Aucun niveau ne commence par « {0} ». Vérifiez la convention "
            u"de nommage.".format(building_code))
        return

    # 1) Ce que les nomenclatures calculent — cellule par cellule. Renoncer à
    #    une nomenclature rend simplement ses colonnes saisissables.
    shon_name, plancher_name = choisir_nomenclatures()
    calculees, avertissements = surfaces_calculees(
        niveaux, building_code, shon_name, plancher_name)
    if avertissements:
        show_alert(u"Nomenclatures", u"\n\n".join(avertissements))

    # 2) Valeurs en place avant écriture : elles déterminent quelles surfaces
    #    changent réellement, seul cas où l'auteur du calcul est réécrit.
    actuelles = {}
    for lvl in niveaux:
        actuelles[lvl.Name] = dict(
            (nom_param, lire_surface_m2(lvl, nom_param))
            for nom_param in PARAMS_SURFACE
        )

    # 3) Tableau unique : calculs, saisie manuelle et échanges tableur au même
    #    endroit, auteur des calculs compris.
    valide, donnees, auteur = afficher_tableau_surfaces(
        niveaux, calculees, actuelles, building_code)
    if not valide:
        return

    # 4) Niveaux ni calculés ni corrigés : surface conservée, mais comptée
    #    dans les totaux écrits sur les informations projet — le total écrit
    #    est donc bien celui qu'affiche le tableau.
    conserves = dict(
        (lvl.Name, actuelles[lvl.Name])
        for lvl in niveaux if lvl.Name not in donnees
    )

    # 5) Écriture niveaux + informations projet
    levels = dict((lvl.Name, lvl) for lvl in niveaux)
    totaux, avertissements = appliquer_surfaces(
        donnees, levels, "MàJ surfaces niveau + projet",
        niveaux_conserves=conserves, actuelles=actuelles, auteur=auteur)

    message = u"Terminé — **{0}** niveau(x) mis à jour, **{1}** conservé(s)." \
              u"\nAuteur : **{2}**\n\nTotaux projet :\n{3}".format(
                  len(donnees), len(conserves), auteur or u"(non tracé)",
                  formater_totaux(totaux))
    if avertissements:
        message += u"\n\nAvertissements :\n  " + u"\n  ".join(avertissements)
    show_alert(u"Terminé", message)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        err = traceback.format_exc()
        show_xaml_message(err, title="Erreur inattendue")
