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

import os, sys, json, codecs, re
from pyrevit import forms

# Feuille de styles WPF partagee (lib/dialogs/dialogs_styles.xaml) : rend
# disponibles les cles NMButtonAppliquer / NMButtonAnnuler utilisees par les
# pieds de dialogue. Tous les styles y sont nommes (x:Key), le chargement
# n'applique donc rien de lui-meme aux controles existants.
_lib = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'lib')
if _lib not in sys.path:
    sys.path.insert(0, _lib)
from dialogs.dialogs_styles_loader import load as _charger_styles
_charger_styles()


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


def _lire_cle_disque(cfg_path, section, cle, defaut):
    """
    Relit UNE cle dans config.json tel qu'il est SUR LE DISQUE.

    Sert aux reglages que cette fenetre ne montre nulle part mais reecrit quand
    meme, parce qu'ils partagent une section avec les siens. Un seul cas
    aujourd'hui : `surface/etiquettes_actif`, l'interrupteur d'etiquetage de la
    palette « Surfaces » (seul reglage ecrit hors de cette fenetre, via
    set_valeur). L'onglet Surfaces reconstruit toute la section `surface`, il
    doit donc recopier cet interrupteur — et le recopier a jour.

    Sans cette relecture, enregistrer remettait l'interrupteur dans l'etat ou il
    se trouvait A L'OUVERTURE de la fenetre. Le risque etait theorique tant que
    « Enregistrer » fermait les Parametres ; il ne l'est plus depuis qu'elle
    reste ouverte, potentiellement des heures, pendant qu'on se sert de la
    palette.

    Repli sur `defaut` si le fichier est illisible : mieux vaut reecrire la
    valeur connue que faire echouer tout l'enregistrement.
    """
    try:
        with codecs.open(cfg_path, 'r', 'utf-8') as f:
            return (json.load(f).get(section) or {}).get(cle, defaut)
    except Exception:
        return defaut


def save_config(path, data):
    """
    Ecrit config.json. AUCUNE confirmation modale : « Enregistrer » ne ferme
    plus la fenetre, et une boite a cliquer a chaque ecriture couterait un clic
    de plus a chaque passe d'une meme session de reglages. Le retour visible est
    le temoin « Enregistre a HH:MM:SS » du pied de fenetre (voir _on_save_click).

    Une erreur d'ecriture, elle, remonte : l'exception traverse et pyRevit
    l'affiche. Un enregistrement qui echoue en silence serait le pire des cas.

    sort_keys : l'ordre d'un dict IronPython 2.7 n'est pas stable d'une
    execution a l'autre. Sans tri, un simple enregistrement sans rien changer
    reecrivait le fichier dans un ordre different et produisait un diff de
    plusieurs milliers de lignes, ou la vraie modification etait introuvable.
    MEME mise en forme que utils.config_loader.save_config, qui ecrit le meme
    fichier depuis la palette « Surfaces » : trier d'un seul cote ne servirait
    a rien, la premiere ecriture de l'autre defaisant le tri.
    """
    with codecs.open(path, 'w', 'utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False, sort_keys=True)


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


def _commit_datagrid_edit(dg):
    """
    Force la validation de la cellule/ligne en cours d'édition d'un DataGrid.
    Un clic sur un bouton "OK" situé hors de la grille ne déclenche pas
    toujours le commit du binding de la dernière case cochée/cellule
    modifiée (le focus n'a pas encore quitté la cellule) : sans cet appel,
    la dernière modification peut être silencieusement perdue.
    """
    try:
        dg.CommitEdit()
        dg.CommitEdit()
    except Exception:
        pass


def _int_or(val, default):
    """
    Convertit val en int, ou retourne default si impossible. Couvre le cas
    d'une cellule de DataGrid laissée vide via la ligne d'ajout intégrée
    (System.DBNull, distinct de None, que int() ne sait pas convertir).
    """
    try:
        return int(val)
    except Exception:
        return default


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
# Auteur des calculs de surfaces
# ---------------------------------------------------------------------------
# Qualifications proposees a l'utilisateur par 02_SURF_SP-SHON-SHOB tant que
# l'onglet Surfaces n'a jamais ete enregistre. L'utilisateur peut en ajouter,
# en retirer ou en renommer : la liste vit ensuite dans config.json.
QUALIFICATIONS_AUTEUR_DEFAUT = [
    u"Géomètre (Surfaces certifiées)",
    u"Architecte (Surfaces certifiées)",
    u"Service Gestion Patrimoine",
]


def lignes_non_vides(texte):
    u"""
    Zone de saisie multiligne -> liste de valeurs. Les lignes vides et les
    espaces de bordure sont ignores, les doublons ecartes en conservant
    l'ordre de saisie.
    """
    valeurs = []
    for ligne in (texte or u'').replace(u'\r\n', u'\n').replace(u'\r', u'\n').split(u'\n'):
        ligne = ligne.strip()
        if ligne and ligne not in valeurs:
            valeurs.append(ligne)
    return valeurs


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
# Referentiel des styles de surfaces (ordre, reperes, couleurs, etiquettes)
# ---------------------------------------------------------------------------

# Teintes proposees en acces direct : dix-huit tons, tous assez soutenus pour
# rester lisibles en bande de quelques pixels, et suffisamment ecartes pour se
# distinguer les uns des autres. Trois rangees de six dans le panneau.
# Le bouton « Autre couleur… » ouvre le selecteur Windows pour le reste : la
# palette guide sans enfermer.
_PALETTE_COULEURS = [
    (u'Rouge',        u'#D32F2F'),
    (u'Orange',       u'#F57C00'),
    (u'Ambre',        u'#FFA000'),
    (u'Jaune',        u'#FBC02D'),
    (u'Citron vert',  u'#AFB42B'),
    (u'Vert',         u'#388E3C'),
    (u'Turquoise',    u'#00897B'),
    (u'Cyan',         u'#0097A7'),
    (u'Bleu clair',   u'#0288D1'),
    (u'Bleu',         u'#1976D2'),
    (u'Indigo',       u'#303F9F'),
    (u'Violet',       u'#7B1FA2'),
    (u'Rose',         u'#C2185B'),
    (u'Framboise',    u'#AD1457'),
    (u'Brun',         u'#6D4C41'),
    (u'Gris ardoise', u'#607D8B'),
    (u'Gris',         u'#9E9E9E'),
    (u'Anthracite',   u'#37474F'),
]


def _hex_vers_rvb(hexa):
    """'#RRGGBB' -> (r, v, b), ou None si la valeur est inexploitable."""
    if not hexa:
        return None
    t = hexa.strip().lstrip(u'#')
    if len(t) != 6:
        return None
    try:
        return (int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))
    except ValueError:
        return None


def _choisir_couleur_libre(couleur_initiale, proprietaire=None):
    """
    Selecteur de couleur Windows. Retourne '#RRGGBB', ou None si annule.

    System.Windows.Forms plutot qu'un selecteur WPF maison : WPF n'en fournit
    aucun en standard, et la boite Windows offre le nuancier, la composition
    libre et les couleurs personnalisees — que personne n'a envie de reecrire.

    Trois precautions, aucune superflue :

    1. Pas d'import de `System.Drawing` : sous .NET 8, `System.Drawing.dll`
       n'est qu'une facade de types transferes et `ColorTranslator` n'y est pas
       resolvable (verifie au MetadataReader). La couleur de depart est donc
       construite en appelant `Color.FromArgb` sur l'instance que ColorDialog
       fournit deja, ce qui evite d'avoir a nommer le type.
    2. Ancrage sur le handle Win32 de la fenetre appelante : une boite WinForms
       sans proprietaire peut s'ouvrir DERRIERE la fenetre WPF modale.
    3. `int()` puis `%02X` : les composantes sont des `System.Byte`, dont
       str.format n'honore pas toujours le gabarit sous IronPython.

    Aucune exception n'est avalee : l'appelant les affiche. Un echec muet est
    indebogable, c'est la regle de [[palette-non-modale-globals-ironpython]].
    """
    import clr as _clr
    _clr.AddReference('System.Windows.Forms')
    from System.Windows.Forms import ColorDialog, DialogResult, NativeWindow
    from System import IntPtr

    boite = ColorDialog()
    boite.FullOpen = True          # panneau de composition deploye d'emblee
    boite.AnyColor = True

    rvb = _hex_vers_rvb(couleur_initiale)
    if rvb is not None:
        try:
            boite.Color = boite.Color.FromArgb(rvb[0], rvb[1], rvb[2])
        except Exception:
            pass    # pre-selection perdue, le selecteur reste utilisable

    ancre = None
    try:
        from System.Windows.Interop import WindowInteropHelper
        handle = WindowInteropHelper(proprietaire).Handle
        if handle != IntPtr.Zero:
            ancre = NativeWindow()
            ancre.AssignHandle(handle)
    except Exception:
        ancre = None

    try:
        if ancre is not None:
            resultat = boite.ShowDialog(ancre)
        else:
            resultat = boite.ShowDialog()
    finally:
        if ancre is not None:
            try:
                ancre.ReleaseHandle()
            except Exception:
                pass

    if resultat != DialogResult.OK:
        return None
    c = boite.Color
    return u'#%02X%02X%02X' % (int(c.R), int(c.G), int(c.B))


def _brosse(hexa):
    """Pinceau WPF depuis '#RRGGBB', ou None si la valeur est inexploitable."""
    if not hexa:
        return None
    try:
        from System.Windows.Media import ColorConverter, SolidColorBrush
        return SolidColorBrush(ColorConverter.ConvertFromString(hexa))
    except Exception:
        return None


def _lire_styles_du_projet(nom_table, col_calcul):
    """
    Noms de cles et types de calcul de la nomenclature de styles du projet actif.

    Lecture volontairement minimale — ni commentaire ni ElementId : ce dialogue
    ne fait que classer et colorer, l'ecriture dans le modele n'est pas son
    affaire. Les lignes d'une nomenclature de CLES sont de vrais elements, d'ou
    le collecteur borne a la vue de la nomenclature.

    Returns:
        tuple: (liste de {'nom', 'calcul'}, message d'anomalie ou u'')
    """
    if not nom_table:
        return [], u"Aucune nomenclature de clés déclarée ci-dessus."
    try:
        return _lire_styles_du_projet_brut(nom_table, col_calcul)
    except Exception as ex:
        # Une lecture qui echoue ne doit pas empecher de reordonner ce qui est
        # deja enregistre : le dialogue reste utilisable, l'anomalie s'affiche.
        return [], u"Lecture de la nomenclature impossible : {0}".format(ex)


def _lire_styles_du_projet_brut(nom_table, col_calcul):
    """Corps de _lire_styles_du_projet, sans garde — voir son docstring."""
    from pyrevit import HOST_APP
    from Autodesk.Revit.DB import (FilteredElementCollector, ViewSchedule,
                                   Element, StorageType)

    doc = HOST_APP.doc
    vue = None
    for vs in FilteredElementCollector(doc).OfClass(ViewSchedule):
        try:
            nom_vs = vs.Name
        except Exception:
            nom_vs = Element.Name.__get__(vs)
        if nom_vs == nom_table:
            vue = vs
            break
    if vue is None:
        return [], (u"Nomenclature « {0} » introuvable dans le projet "
                    u"actif.".format(nom_table))

    styles = []
    for elem in FilteredElementCollector(doc, vue.Id).ToElements():
        try:
            # Element.Name est implemente en interface explicite : elem.Name
            # leve AttributeError sur certains types en IronPython.
            nom = Element.Name.__get__(elem)
        except Exception:
            continue
        if not nom:
            continue
        calcul = u''
        if col_calcul:
            try:
                p = elem.LookupParameter(col_calcul)
                if p is not None:
                    if p.StorageType == StorageType.String:
                        calcul = p.AsString() or u''
                    else:
                        calcul = p.AsValueString() or u''
            except Exception:
                calcul = u''
        # strip() des DEUX cotes : le type de calcul sert de clef au mappage des
        # etiquettes, et il est lu ici dans le projet mais la dans config.json,
        # ou il a ete nettoye. Une espace de fin cote Revit suffirait a ce que
        # les deux ne se reconnaissent plus — le reglage semblerait perdu.
        styles.append({u'nom': nom.strip(), u'calcul': calcul.strip()})
    return styles, u''


def _hsv_vers_hex(h, s, v):
    """Teinte (0-360), saturation et valeur (0-1) -> '#RRGGBB'."""
    c = v * s
    x = c * (1 - abs(((h / 60.0) % 2) - 1))
    m = v - c
    if h < 60:
        r, g, b = c, x, 0
    elif h < 120:
        r, g, b = x, c, 0
    elif h < 180:
        r, g, b = 0, c, x
    elif h < 240:
        r, g, b = 0, x, c
    elif h < 300:
        r, g, b = x, 0, c
    else:
        r, g, b = c, 0, x
    return u'#%02X%02X%02X' % (int(round((r + m) * 255)),
                               int(round((g + m) * 255)),
                               int(round((b + m) * 255)))


def _teintes_distinctes(n):
    """
    n couleurs de teintes regulierement espacees sur le cercle chromatique.

    Saturation moderee et valeur haute : un remplissage de plan doit rester
    assez clair pour qu'une etiquette posee dessus reste lisible.
    """
    if n <= 0:
        return []
    return [_hsv_vers_hex(360.0 * i / n, 0.45, 0.95) for i in range(n)]


_MOTIF_AUCUN = u'< Inchangé >'

# ── Echange de reglages ─────────────────────────────────────────────────────
#
# Extension PROPRE a l'extension : le contenu est du JSON, mais un .json
# quelconque n'a aucun sens ici. Le filtre des boites de fichiers s'appuie
# dessus.
_EXT_REGLAGES     = u'.NM-Surf-Config'
# Signature INTERNE, verifiee a l'import. L'extension seule ne protege de rien :
# renommer un fichier est trivial, et un contenu etranger produirait des
# reglages incoherents sans que personne ne comprenne pourquoi.
_MARQUE_REGLAGES  = u'nm-batii/styles-surfaces'
# 2 depuis l'ajout des etiquettes. Les fichiers en version 1 restent LISIBLES :
# ils n'ont pas de section « etiquettes », et l'import laisse alors le mappage
# courant intact au lieu de l'effacer — un fichier ecrit avant que la
# fonctionnalite existe ne peut rien dire des etiquettes, et ne doit donc rien
# leur faire.
_VERSION_REGLAGES  = 2
_VERSIONS_LUES     = (1, 2)

# Champs echanges. Le NOM DE CLE sert d'identifiant, comme dans config.json :
# c'est ce qui rend un fichier de reglages valable sur n'importe quel projet.
_CHAMPS_REGLAGES = (u'nom', u'couleur', u'couleur_plan', u'motif_plan')


def _exporter_reglages(parent, entrees, etiquettes):
    """Ecrit les reglages courants dans un fichier .NM-Surf-Config."""
    from Microsoft.Win32 import SaveFileDialog
    from dialogs.dialogs_styles_loader import show_alert
    import datetime

    boite = SaveFileDialog()
    boite.Title = u"Exporter les réglages des styles de surfaces"
    boite.Filter = u"Réglages de styles NM-BATII (*{0})|*{0}".format(_EXT_REGLAGES)
    boite.DefaultExt = _EXT_REGLAGES
    boite.FileName = u"styles-surfaces" + _EXT_REGLAGES
    if boite.ShowDialog(parent) != True:
        return

    defaut, par_calcul = _etiquettes_vers_config(etiquettes or {})
    donnees = {
        u'format':    _MARQUE_REGLAGES,
        u'version':   _VERSION_REGLAGES,
        u'genere_le': datetime.datetime.now().strftime('%Y-%m-%d %H:%M'),
        u'styles':    [dict((c, e.get(c, u'')) for c in _CHAMPS_REGLAGES)
                       for e in entrees],
        # Meme forme que dans config.json : un seul format a lire, et le
        # fichier reste comparable au reglage en place.
        u'etiquettes': {u'defaut': defaut, u'par_calcul': par_calcul},
    }
    try:
        with codecs.open(boite.FileName, 'w', 'utf-8') as f:
            json.dump(donnees, f, ensure_ascii=False, indent=2,
                      separators=(u', ', u': '))
    except Exception as ex:
        show_alert(u"NM-BATII — Export",
                   u"Écriture impossible :\n\n{0}".format(ex))
        return
    show_alert(u"NM-BATII — Export",
               u"{0} style(s) et {1} étiquette(s) par type de calcul "
               u"exporté(s) vers :\n{2}".format(
                   len(entrees), len(par_calcul), boite.FileName))


def _etiquettes_depuis_fichier(donnees):
    """
    Section « etiquettes » d'un fichier de reglages -> reglages exploitables.

    Retourne None si le fichier n'en porte pas : un fichier ecrit avant que les
    etiquettes existent ne dit rien a leur sujet, l'import doit donc laisser le
    mappage en place plutot que de l'effacer.
    """
    brut = donnees.get(u'etiquettes')
    if not isinstance(brut, dict):
        return None
    par_calcul = brut.get(u'par_calcul')
    return _etiquettes_depuis_config({
        'etiquette_defaut':      brut.get(u'defaut'),
        'etiquettes_par_calcul': par_calcul if isinstance(par_calcul, list) else [],
    })


def _importer_reglages(parent):
    """
    Lit un fichier .NM-Surf-Config.

    Returns:
        tuple: (liste des reglages de style, reglages d'etiquettes ou None),
            ou None si l'import n'a pas abouti. Le second terme vaut None quand
            le fichier ne porte pas d'etiquettes — a ne pas confondre avec un
            mappage vide, qui, lui, s'applique.

    La signature et la version sont verifiees avant toute exploitation : une
    extension se renomme, et un contenu etranger accepte en silence donnerait
    des reglages incoherents impossibles a diagnostiquer.
    """
    from Microsoft.Win32 import OpenFileDialog
    from dialogs.dialogs_styles_loader import show_alert

    boite = OpenFileDialog()
    boite.Title = u"Importer des réglages de styles de surfaces"
    boite.Filter = u"Réglages de styles NM-BATII (*{0})|*{0}".format(_EXT_REGLAGES)
    boite.DefaultExt = _EXT_REGLAGES
    boite.Multiselect = False
    if boite.ShowDialog(parent) != True:
        return None

    try:
        with codecs.open(boite.FileName, 'r', 'utf-8') as f:
            donnees = json.load(f)
    except Exception as ex:
        show_alert(u"NM-BATII — Import",
                   u"Lecture impossible :\n\n{0}".format(ex))
        return None

    if not isinstance(donnees, dict) \
            or donnees.get(u'format') != _MARQUE_REGLAGES:
        show_alert(u"NM-BATII — Import",
                   u"Ce fichier n'est pas un fichier de réglages de styles de "
                   u"surfaces NM-BATII.\n\nIl a peut-être été renommé, ou "
                   u"provient d'une autre fonction de l'extension.")
        return None
    if donnees.get(u'version') not in _VERSIONS_LUES:
        show_alert(u"NM-BATII — Import",
                   u"Version de fichier non prise en charge : {0}\n\nCette "
                   u"version de l'extension lit les versions {1}.".format(
                       donnees.get(u'version'),
                       u", ".join(unicode(v) for v in _VERSIONS_LUES)))
        return None

    reglages = []
    vus = set()
    for brut in (donnees.get(u'styles') or []):
        if not isinstance(brut, dict):
            continue
        nom = (brut.get(u'nom') or u'').strip()
        if not nom or nom in vus:
            continue
        vus.add(nom)
        reglages.append(dict(
            (c, (brut.get(c) or u'').strip()) for c in _CHAMPS_REGLAGES))
    if not reglages:
        show_alert(u"NM-BATII — Import",
                   u"Ce fichier ne contient aucun style exploitable.")
        return None
    return reglages, _etiquettes_depuis_fichier(donnees)

# Rendu des motifs : partage avec la palette « Surfaces », qui affiche les
# memes pastilles. reload() explicite, le moteur IronPython de pyRevit gardant
# en cache la version chargee au premier lancement.
import dialogs.apercu_motifs as _mod_apercu
reload(_mod_apercu)
from dialogs.apercu_motifs import infos_motifs as _infos_motifs
from dialogs.apercu_motifs import pinceau_apercu as _pinceau_apercu


def _dialogue_couleur_plan(parent, nom_style, couleur, motif, infos_motifs):
    """
    Regle l'apparence d'un style dans le choix de couleurs Revit.

    Couleur ET motif ensemble : c'est le couple que Revit applique a une
    entree, les separer obligerait a repasser sur chaque style. L'apercu montre
    le resultat des deux, et se refait a chaque changement de l'un ou l'autre.

    Returns:
        tuple: (couleur, motif) valides, ou None si annule.
    """
    from System.Windows import Thickness
    from System.Windows.Controls import Button
    from System.Windows.Media import Brushes

    motifs_dispo = sorted(infos_motifs.keys(), key=lambda n: n.lower())

    xaml = os.path.join(os.path.dirname(__file__), 'CouleurPlanDialog.xaml')
    dlg  = forms.WPFWindow(xaml)
    dlg.txtStyle.Text = nom_style

    etat = {u'couleur': couleur or u''}

    def _motif_courant():
        choisi = dlg.cboMotif.SelectedItem
        return u'' if (choisi is None or choisi == _MOTIF_AUCUN) else choisi

    def _rafraichir():
        # Nominal proche de la taille reelle du bandeau : le pinceau est etire
        # pour remplir, un ecart important inclinerait les hachures a tort.
        info = infos_motifs.get(_motif_courant())
        dlg.brdApercu.Background = (_pinceau_apercu(etat[u'couleur'], info,
                                                    390, 44)
                                    or Brushes.Transparent)

    def _poser(hexa):
        etat[u'couleur'] = hexa
        _rafraichir()

    def _pastille(nom_couleur, hexa):
        b = Button()
        b.Width = 26
        b.Height = 26
        b.Margin = Thickness(0, 0, 4, 4)
        b.MinWidth = 0
        b.MinHeight = 0
        b.Padding = Thickness(0)
        b.Background = _brosse(hexa) or Brushes.Transparent
        b.ToolTip = nom_couleur
        b.Click += (lambda s, e, _h=hexa: _poser(_h))
        return b

    for _nom_c, _hexa in _PALETTE_COULEURS:
        dlg.pnlCouleurs.Children.Add(_pastille(_nom_c, _hexa))

    def _on_autre(s, e):
        from dialogs.dialogs_styles_loader import show_alert
        try:
            hexa = _choisir_couleur_libre(etat[u'couleur'], dlg)
        except Exception as ex:
            show_alert(u"NM-BATII — Couleur",
                       u"Le sélecteur de couleur n'a pas pu s'ouvrir :\n\n{0}"
                       .format(ex))
            return
        if hexa:
            _poser(hexa)

    dlg.btnAutreCouleur.Click += _on_autre
    dlg.btnSansCouleur.Click  += (lambda s, e: _poser(u''))

    dlg.cboMotif.Items.Add(_MOTIF_AUCUN)
    for m in motifs_dispo:
        dlg.cboMotif.Items.Add(m)
    if motif and motif in motifs_dispo:
        dlg.cboMotif.SelectedItem = motif
    else:
        dlg.cboMotif.SelectedIndex = 0
    dlg.cboMotif.SelectionChanged += (lambda s, e: _rafraichir())

    dlg.btnOk.Click     += lambda s, e: setattr(dlg, 'DialogResult', True)
    dlg.btnCancel.Click += lambda s, e: setattr(dlg, 'DialogResult', False)

    _rafraichir()
    try:
        dlg.Owner = parent
    except Exception:
        pass

    if not dlg.show_dialog():
        return None
    return etat[u'couleur'], _motif_courant()


_AIDE_ORDRE = (
    u"**À quoi sert cette fenêtre**\n"
    u"Elle règle l’apparence des boutons de la palette « Surfaces » et les "
    u"couleurs que prennent les surfaces dans les plans de Revit.\n\n"

    u"**Sauvegarde des réglages**\n"
    u"Les réglages sont enregistrés dans la configuration de l’extension, et "
    u"non dans le projet Revit. Ils sont identifiés par le NOM DE CLÉ DE "
    u"STYLE. Un réglage défini ici s’applique donc à tous les projets "
    u"utilisant les mêmes noms de clé.\n"
    u"Les clés de style absentes du projet actif, mais provenant d’autres "
    u"projets Revit, sont conservées dans la liste afin de préserver leurs "
    u"réglages et de pouvoir les réutiliser dans d’autres projets.\n"
    u"Ces clés de style « absentes du projet actif » peuvent être "
    u"supprimées de la liste, mais assurez-vous au préalable qu’elles ne sont "
    u"plus nécessaires dans d’autres projets et que vous avez sauvegardé vos "
    u"réglages.\n\n"

    u"**Ordre d’affichage**\n"
    u"Permet d’ordonner la position des boutons dans la palette "
    u"« Surfaces », de haut en bas. Vous pouvez sélectionner plusieurs "
    u"boutons par Ctrl+clic et Maj+clic, puis « Monter » ou "
    u"« Descendre » l’ensemble de la sélection.\n\n"

    u"**Repère du bouton**\n"
    u"Le REPÈRE du bouton est une bande colorée au bord gauche du bouton, "
    u"dans la palette. Il sert uniquement de repère visuel pour les boutons. "
    u"Par exemple une couleur pour les boutons de surfaces incluses dans le "
    u"calcul, une couleur pour les boutons de surfaces exclues.\n"
    u"Vous pouvez sélectionner plusieurs boutons par Ctrl+clic et Maj+clic, "
    u"pour attribuer une couleur de repère de bouton à l’ensemble de la "
    u"sélection de boutons. ATTENTION : ne pas confondre la couleur de "
    u"repère de bouton avec les couleurs de surface.\n\n"

    u"**Couleur de surface**\n"
    u"La COULEUR DE SURFACE est la couleur appliquée à la surface afin de "
    u"distinguer chaque type de surface sur les plans. Chaque style de surface "
    u"doit être identifiable par rapport aux autres. Pour cela, vous pouvez "
    u"attribuer à chaque style de surface une couleur et un motif de "
    u"remplissage de votre choix. Le réglage s’effectue style par style, en "
    u"cliquant sur la pastille située à droite du nom de la clé de style de "
    u"surface.\n\n"

    u"**Teintes distinctes**\n"
    u"Permet d’attribuer automatiquement des couleurs bien différenciées sur "
    u"les styles AFFICHÉS. Si les styles sont filtrés par la liste "
    u"déroulante « Type de calcul », le bouton Teintes distinctes traite "
    u"uniquement les styles affichés du type de calcul, sans modifier les "
    u"autres. Sans filtre, le bouton Teintes distinctes traite l’ensemble des "
    u"styles affichés, en regroupant les styles par type de calcul (chaque "
    u"type de calcul repart du début du cercle). C’est une remise à plat : "
    u"les motifs de remplissage reviennent au remplissage plein, pour qu’une "
    u"teinte neuve ne se retrouve pas sur une hachure héritée d’un réglage "
    u"précédent. Les repères des boutons, eux, ne sont jamais "
    u"touchés.\n\n"

    u"**Étiquettes**\n"
    u"Le bouton « Étiquettes… » ouvre le réglage de l’étiquette posée par la "
    u"palette sur chaque surface traitée. Le choix se fait PAR TYPE DE CALCUL "
    u"et non par clé de style : les étiquettes se distinguent par famille "
    u"réglementaire, quatre à six lignes suffisent donc là où il en faudrait "
    u"une cinquantaine.\n"
    u"C’est la palette, et non ce réglage, qui décide d’étiqueter ou non : "
    u"elle porte la case « Étiqueter » et une liste déroulante permettant de "
    u"choisir ponctuellement une autre étiquette.\n\n"

    u"**Sauvegarde et restauration des réglages**\n"
    u"« Exporter » enregistre l’ordre, les repères, les couleurs et motifs "
    u"de surface ainsi que les étiquettes dans un fichier "
    u"« .NM-Surf-Config ».\n"
    u"« Importer » remplace les réglages courants par ceux du fichier. Les "
    u"styles de votre projet qui n’y figurent pas ne disparaissent pas : ils "
    u"passent en fin de liste, sans réglage. Un fichier créé avant l’arrivée "
    u"des étiquettes ne contient pas de mappage : le vôtre est alors conservé "
    u"tel quel. Rien n’est enregistré tant que vous n’avez pas validé cette "
    u"fenêtre, puis enregistré les paramètres.\n\n"

    u"**Dans Revit**\n"
    u"Une entrée n’existe dans un choix de couleurs que pour une valeur "
    u"réellement employée par une surface.\n"
    u"Dans la palette « Surfaces », les couleurs sont implémentées à chaque "
    u"attribution d’un style de surface.\n"
    u"Vous pouvez également utiliser le bouton « Couleurs » pour forcer "
    u"l’implémentation des couleurs dans un projet entier sans toucher aux "
    u"surfaces."
)

_TOUS_CALCULS = u'< Tous les types >'
# Filtre d'entretien : rassemble les styles connus de la configuration mais
# absents de la nomenclature du projet ouvert. Sans lui, ces orphelins n'etaient
# visibles que noyes dans « Tous les types », et donc introuvables en pratique.
_ABSENTS = u'< Absents du projet actif >'


def _dialogue_ordre_styles(parent, ordre_actuel, etiquettes_actuelles,
                           nom_table, col_calcul):
    """
    Ouvre le referentiel des styles de surfaces.

    Ordre, reperes, couleurs, motifs ET etiquettes : les etiquettes ont leur
    propre dialogue, ouvert d'ici, mais elles transitent par celui-ci parce que
    c'est lui qui porte l'export et l'import — un fichier de reglages doit
    emporter le referentiel entier, pas la moitie.

    Args:
        parent: fenetre proprietaire.
        ordre_actuel (list): [{'nom', 'couleur'}, ...] deja enregistre.
        etiquettes_actuelles (dict): {'defaut': {...}, 'par_calcul': {...}}.
        nom_table (str): nomenclature de cles, telle que saisie dans le
            formulaire — et non telle qu'enregistree : l'utilisateur vient
            peut-etre de la corriger.
        col_calcul (str): colonne du type de calcul, meme remarque.

    Returns:
        tuple: (liste ordonnee, reglages d'etiquettes), ou None si annule.
    """
    from System.Windows import (Thickness, GridLength, GridUnitType,
                                HorizontalAlignment, VerticalAlignment,
                                CornerRadius, TextWrapping)
    from System.Windows.Controls import (ListBoxItem, Grid, ColumnDefinition,
                                         TextBlock, Border, Button,
                                         StackPanel, Orientation)
    from System.Windows.Input import Cursors
    from System.Windows.Media import Brushes, TranslateTransform

    xaml = os.path.join(os.path.dirname(__file__), 'StylesOrdreDialog.xaml')
    dlg  = forms.WPFWindow(xaml)

    styles_projet, anomalie = _lire_styles_du_projet(nom_table, col_calcul)

    # Type de calcul par nom de cle, pour le filtre. Les styles connus de la
    # configuration mais absents du projet actif n'en ont pas : ils restent
    # listes — ils servent aux autres projets — et sont signales.
    calcul_par_nom = {}
    for s in styles_projet:
        calcul_par_nom[s[u'nom']] = s[u'calcul']

    # Ordre de travail : la configuration d'abord (elle porte le classement
    # voulu), puis les styles du projet qu'elle ne connait pas encore.
    entrees = []
    vus     = set()
    for e in ordre_actuel:
        entrees.append({u'nom':          e[u'nom'],
                        u'couleur':      e.get(u'couleur', u''),
                        u'couleur_plan': e.get(u'couleur_plan', u''),
                        u'motif_plan':   e.get(u'motif_plan', u'')})
        vus.add(e[u'nom'])
    for s in styles_projet:
        if s[u'nom'] not in vus:
            entrees.append({u'nom': s[u'nom'], u'couleur': u'',
                            u'couleur_plan': u'', u'motif_plan': u''})
            vus.add(s[u'nom'])

    if anomalie:
        dlg.txtInfo.Text = (
            u"{0}\nLes styles déjà enregistrés restent modifiables ci-dessous."
            .format(anomalie))
    else:
        dlg.txtInfo.Text = u"{0} style(s) lus dans « {1} ».".format(
            len(styles_projet), nom_table)

    # ── Aide, en vis-a-vis du dialogue ───────────────────────────────────────
    # Non modale, et volontairement : l'aide decrit des reglages qu'on veut
    # essayer en la lisant. Une boite modale par-dessus aurait oblige a la
    # fermer a chaque fois.
    #
    # Elle est POSSEDEE par le dialogue (Owner). ShowDialog() desactive les
    # fenetres de l'application, mais pas celles ouvertes apres lui : l'aide
    # reste donc utilisable. Et Owner la maintient au-dessus du dialogue puis la
    # ferme avec lui.
    #
    # Dictionnaire plutot qu'une variable : pas de `nonlocal` en IronPython 2.7.
    aide = {u'fen': None}

    def _placer_aide(fen):
        """Colle l'aide au flanc droit du dialogue — a gauche si l'ecran manque."""
        from System.Windows import SystemParameters
        marge = 8.0
        largeur = fen.ActualWidth or fen.Width
        fen.Top = dlg.Top
        fen.Height = dlg.ActualHeight or dlg.Height
        droite = dlg.Left + (dlg.ActualWidth or dlg.Width)
        bord = (SystemParameters.VirtualScreenLeft
                + SystemParameters.VirtualScreenWidth)
        if droite + marge + largeur <= bord:
            fen.Left = droite + marge
        else:
            fen.Left = max(SystemParameters.VirtualScreenLeft,
                           dlg.Left - marge - largeur)

    def _on_aide(s, e):
        # Deja ouverte : la ramener au premier plan plutot qu'en empiler une
        # seconde.
        if aide[u'fen'] is not None:
            try:
                aide[u'fen'].Activate()
                return
            except Exception:
                aide[u'fen'] = None
        try:
            from dialogs.dialogs_styles_loader import _set_rich_text
            fen = forms.WPFWindow(os.path.join(os.path.dirname(__file__),
                                               'StylesAideDialog.xaml'))
            _set_rich_text(fen.txtAide, _AIDE_ORDRE)
            fen.Owner = dlg
            fen.btnFermer.Click += (lambda s2, e2: fen.Close())
            fen.Closed += (lambda s2, e2: aide.__setitem__(u'fen', None))
            aide[u'fen'] = fen
            _placer_aide(fen)
            fen.Show()
        except Exception:
            # Repli sur le message modal : mieux vaut une aide genante qu'une
            # aide absente.
            aide[u'fen'] = None
            from dialogs.dialogs_styles_loader import show_alert
            show_alert(u"NM-BATII — Styles de surfaces", _AIDE_ORDRE)

    def _suivre_aide(s, e):
        """L'aide reste collee au dialogue quand on le deplace ou le redimensionne."""
        if aide[u'fen'] is not None:
            try:
                _placer_aide(aide[u'fen'])
            except Exception:
                pass

    def _fermer_aide(s, e):
        # Owner s'en charge deja ; explicite quand meme, car le repli ci-dessus
        # peut avoir laisse une fenetre sans proprietaire.
        fen = aide[u'fen']
        aide[u'fen'] = None
        if fen is not None:
            try:
                fen.Close()
            except Exception:
                pass

    dlg.btnAide.Click     += _on_aide
    dlg.LocationChanged   += _suivre_aide
    dlg.SizeChanged       += _suivre_aide
    dlg.Closed            += _fermer_aide

    # ── Liste deroulante des types de calcul ─────────────────────────────────
    valeurs_calcul = []
    for s in styles_projet:
        if s[u'calcul'] and s[u'calcul'] not in valeurs_calcul:
            valeurs_calcul.append(s[u'calcul'])
    valeurs_calcul.sort(key=lambda v: v.lower())
    dlg.cboCalcul.Items.Add(_TOUS_CALCULS)
    if any(calcul_par_nom.get(e[u'nom']) is None for e in entrees):
        dlg.cboCalcul.Items.Add(_ABSENTS)
    for v in valeurs_calcul:
        dlg.cboCalcul.Items.Add(v)
    dlg.cboCalcul.SelectedIndex = 0

    # Etat mutable partage par les callbacks — pas de nonlocal en IronPython 2.7
    etat = {
        u'indices':     [],     # index dans `entrees` de chaque ligne affichee
        u'pistes':      [],     # (libelle, cadre) par ligne, pour la mesure
        u'decalages':   [],     # la translation de chaque libelle
        u'decalage':    0.0,    # position courante de l'ascenseur du texte
    }

    def _filtre_courant():
        """None = tout afficher ; _ABSENTS = les orphelins ; sinon un calcul."""
        sel = dlg.cboCalcul.SelectedItem
        return None if (sel is None or sel == _TOUS_CALCULS) else sel

    # Lu UNE fois : la liste se reconstruit a chaque filtre, relire les motifs
    # du document a chaque fois serait inutilement couteux.
    from pyrevit import HOST_APP as _HOST_MOTIFS
    infos_motifs = _infos_motifs(_HOST_MOTIFS.doc)

    def _on_pastille_plan(sender, args):
        """Clic sur une pastille : regle la couleur de surface et son motif."""
        try:
            i = sender.Tag
            if i is None:
                return
            e = entrees[i]
            resultat = _dialogue_couleur_plan(dlg, e[u'nom'],
                                              e.get(u'couleur_plan', u''),
                                              e.get(u'motif_plan', u''),
                                              infos_motifs)
            if resultat is None:
                return
            e[u'couleur_plan'], e[u'motif_plan'] = resultat
            _rafraichir_liste(set([e[u'nom']]))
        except Exception as ex:
            from dialogs.dialogs_styles_loader import show_alert
            show_alert(u"NM-BATII — Couleur de surface",
                       u"Réglage impossible :\n\n{0}".format(ex))

    def _maj_ascenseur():
        """
        Regle l'ascenseur du texte sur le libelle le plus long.

        Le debordement est MESURE PAR WPF, jamais estime : c'est l'ecart entre
        la largeur reelle du libelle et celle de son cadre, tous deux lus apres
        mise en page. Les tentatives precedentes calculaient cette largeur a la
        main, hors arbre visuel, et se trompaient sans que rien ne le signale.

        Suppose la virtualisation de la liste desactivee — sans quoi seules les
        lignes visibles auraient une largeur, et la course s'arreterait avant
        les libelles hors ecran.

        L'ascenseur n'apparait que si quelque chose depasse : un ascenseur
        inerte laisserait croire qu'il reste du texte a decouvrir.
        """
        from System.Windows import Visibility
        try:
            debord = 0.0
            for libelle, cadre in etat[u'pistes']:
                try:
                    ecart = libelle.ActualWidth - cadre.ActualWidth
                    if ecart > debord:
                        debord = ecart
                except Exception:
                    continue
            if debord < 1:
                dlg.sbTexte.Visibility = Visibility.Collapsed
                dlg.sbTexte.Value = 0
                _appliquer_decalage(0.0)
                return
            dlg.sbTexte.Visibility = Visibility.Visible
            dlg.sbTexte.Minimum = 0
            dlg.sbTexte.Maximum = debord
            dlg.sbTexte.ViewportSize = max(1.0, dlg.lstStyles.ActualWidth)
            if dlg.sbTexte.Value > debord:
                dlg.sbTexte.Value = debord
        except Exception:
            pass

    def _appliquer_decalage(valeur):
        """
        Decale TOUS les libelles d'une meme valeur — et eux seuls.

        Translation et non ScrollToHorizontalOffset : celui-ci se borne au
        debordement de SA ligne, si bien qu'un libelle court ne bougeait pas
        d'un pixel pendant que les longs defilaient. Le defilement doit etre
        uniforme, comme les colonnes d'un tableau qui restent alignees.

        Les reperes et les pastilles ne portent aucune transformation : ils
        demeurent a leur bord.
        """
        etat[u'decalage'] = valeur
        for transformation in etat[u'decalages']:
            try:
                transformation.X = -valeur
            except Exception:
                continue

    def _rafraichir_liste(noms_a_selectionner=None):
        """Reconstruit la liste ; `noms_a_selectionner` est un ensemble de noms."""
        calcul = _filtre_courant()
        dlg.lstStyles.Items.Clear()
        etat[u'indices'] = []
        etat[u'pistes'] = []
        etat[u'decalages'] = []
        a_reselectionner = []
        for i, e in enumerate(entrees):
            c = calcul_par_nom.get(e[u'nom'])
            if calcul == _ABSENTS:
                if c is not None:
                    continue
            elif calcul is not None and c != calcul:
                continue

            # Disposition alignee sur celle des boutons de la palette : BANDE
            # de repere au bord gauche, libelle, PASTILLE de couleur de surface au
            # bord droit. Les deux temoins gardent des formes differentes pour
            # ne pas etre confondus.
            ligne = Grid()
            for largeur in (GridLength(6),
                            GridLength(1, GridUnitType.Star),
                            GridLength(0, GridUnitType.Auto)):
                cd = ColumnDefinition()
                cd.Width = largeur
                ligne.ColumnDefinitions.Add(cd)

            repere = Border()
            repere.Background = _brosse(e[u'couleur']) or Brushes.Transparent
            repere.CornerRadius = CornerRadius(3)
            repere.ToolTip = u"Repère du bouton dans la palette"
            Grid.SetColumn(repere, 0)
            ligne.Children.Add(repere)

            # Le type de calcul n'est PAS repris en fin de libelle : il
            # allongeait chaque ligne sans rien apprendre — la liste deroulante
            # du haut le donne deja, et le filtre le rend evident.
            libelle = TextBlock()
            if c is None:
                libelle.Text = u"{0}   (absent du projet actif)".format(e[u'nom'])
                libelle.Foreground = Brushes.Gray
            else:
                libelle.Text = e[u'nom']
            libelle.Margin = Thickness(8, 3, 4, 3)
            # Ni troncature ni retour a la ligne : c'est l'ascenseur du bas qui
            # donne acces a la fin des libelles.
            libelle.TextWrapping = TextWrapping.NoWrap

            # StackPanel horizontal : il mesure ses enfants avec une largeur
            # INFINIE. Pose directement dans la colonne, le TextBlock serait
            # mesure a la largeur disponible, et le texte au-dela ne serait pas
            # DESSINE — le decaler ne revelerait qu'une zone blanche.
            #
            # SURTOUT PAS de ScrollViewer ici, bien qu'il rende le meme service
            # et davantage : imbrique dans une ListBoxItem, il CASSE LA
            # SELECTION — clics perdus et selections qui restent accrochees.
            # Constate en usage, c'est redhibitoire.
            decalage = TranslateTransform()
            piste = StackPanel()
            piste.Orientation = Orientation.Horizontal
            piste.Children.Add(libelle)
            piste.RenderTransform = decalage

            # Le libelle deborde volontairement de sa colonne ; ce cadre le
            # coupe pour qu'il n'empiete pas sur la pastille.
            cadre = Border()
            cadre.ClipToBounds = True
            cadre.Child = piste
            Grid.SetColumn(cadre, 1)
            ligne.Children.Add(cadre)

            etat[u'pistes'].append((libelle, cadre))
            etat[u'decalages'].append(decalage)

            # Pastille CLIQUABLE : la couleur de surface et son motif se reglent
            # style par style, la ou on les voit. Un Border et non un Button —
            # un bouton dans une ListBoxItem capterait le clic de selection.
            motif_txt = e.get(u'motif_plan') or u''
            plan = Border()
            plan.Background = (_pinceau_apercu(e[u'couleur_plan'],
                                               infos_motifs.get(motif_txt),
                                               16, 16)
                               or Brushes.Transparent)
            plan.BorderBrush = Brushes.Gray
            plan.BorderThickness = Thickness(1)
            plan.CornerRadius = CornerRadius(2)
            plan.Width = 16
            plan.Height = 16
            plan.Margin = Thickness(6, 0, 6, 0)
            plan.VerticalAlignment = VerticalAlignment.Center
            plan.Cursor = Cursors.Hand
            plan.Tag = i
            plan.ToolTip = u"Couleur de surface : {0}{1}\nCliquez pour la " \
                           u"modifier.".format(
                               e[u'couleur_plan'] or u"aucune",
                               u"" if not motif_txt
                               else u"  •  motif : {0}".format(motif_txt))
            plan.MouseLeftButtonUp += _on_pastille_plan
            Grid.SetColumn(plan, 2)
            ligne.Children.Add(plan)

            item = ListBoxItem()
            item.Content = ligne
            item.HorizontalContentAlignment = HorizontalAlignment.Stretch
            dlg.lstStyles.Items.Add(item)
            etat[u'indices'].append(i)
            if noms_a_selectionner and e[u'nom'] in noms_a_selectionner:
                a_reselectionner.append(item)

        for item in a_reselectionner:
            item.IsSelected = True

        _appliquer_decalage(etat[u'decalage'])
        # ActualWidth n'a de valeur qu'apres une passe de mise en page : le
        # reglage de l'ascenseur est donc renvoye en fin de file.
        try:
            from System import Action
            from System.Windows.Threading import DispatcherPriority
            dlg.Dispatcher.BeginInvoke(DispatcherPriority.Loaded,
                                       Action(_maj_ascenseur))
        except Exception:
            _maj_ascenseur()

    def _positions_selectionnees():
        """Positions AFFICHEES des lignes selectionnees, en ordre croissant."""
        positions = []
        for item in dlg.lstStyles.SelectedItems:
            p = dlg.lstStyles.Items.IndexOf(item)
            if p >= 0:
                positions.append(p)
        positions.sort()
        return positions

    def _noms_selectionnes():
        return set(entrees[etat[u'indices'][p]][u'nom']
                   for p in _positions_selectionnees())

    def _deplacer(delta):
        """
        Deplace d'un cran toutes les lignes selectionnees.

        Les echanges portent sur la liste COMPLETE, aux index correspondant aux
        lignes voisines A L'ECRAN : un deplacement fait sous filtre ne perturbe
        donc jamais le classement des autres types de calcul.

        L'ordre de parcours n'est pas un detail — croissant vers le haut,
        decroissant vers le bas — et une ligne dont le voisin est lui-meme
        selectionne est sautee. C'est ce qui fait qu'un bloc, meme discontinu,
        se deplace d'un seul tenant au lieu de se tasser contre la butee.
        """
        positions = _positions_selectionnees()
        if not positions:
            return
        total = len(etat[u'indices'])
        restants = set(positions)
        ordre = positions if delta < 0 else list(reversed(positions))

        for p in ordre:
            voisin = p + delta
            if voisin < 0 or voisin >= total:
                continue
            if voisin in restants:
                continue          # bloc en butee : ce voisin bouge aussi
            i, j = etat[u'indices'][p], etat[u'indices'][voisin]
            entrees[i], entrees[j] = entrees[j], entrees[i]
            restants.discard(p)
            restants.add(voisin)

        _rafraichir_liste(set(entrees[etat[u'indices'][p]][u'nom']
                              for p in restants))

    def _on_monter(s, e):
        _deplacer(-1)

    def _on_descendre(s, e):
        _deplacer(1)

    def _on_alpha(s, e):
        """Reordonne alphabetiquement les seules lignes actuellement visibles."""
        indices = list(etat[u'indices'])
        if not indices:
            return
        tries = sorted((entrees[i] for i in indices),
                       key=lambda x: x[u'nom'].lower())
        for place, i in enumerate(indices):
            entrees[i] = tries[place]
        _rafraichir_liste()

    def _appliquer_couleur(hexa, positions=None):
        """
        Affecte le REPERE du bouton aux lignes selectionnees.

        La couleur de surface, elle, se regle pastille par pastille : elle va de
        pair avec un motif de remplissage, et doit se distinguer de ses
        voisines plutot que se poser en lot.

        `positions` permet de fournir une selection CAPTUREE PLUS TOT. C'est
        indispensable pour le selecteur libre : entre le clic sur le bouton et
        le retour de la boite modale, la selection de la ListBox peut avoir
        ete perdue, et relire SelectedItems a ce moment-la ne rendait plus
        rien — la couleur choisie n'etait alors appliquee a personne, sans le
        moindre message.

        Returns:
            int: nombre de lignes effectivement modifiees.
        """
        if positions is None:
            positions = _positions_selectionnees()
        if not positions:
            return 0
        cle = u'couleur'
        noms = set()
        for p in positions:
            if p < 0 or p >= len(etat[u'indices']):
                continue
            e = entrees[etat[u'indices'][p]]
            e[cle] = hexa
            noms.add(e[u'nom'])
        if noms:
            _rafraichir_liste(noms)
        return len(noms)

    def _on_generer_plan(s, e):
        """
        Attribue des teintes distinctes aux styles AFFICHES, par type de calcul.

        Deux regles qui se combinent :
          - la portee suit le filtre, pour pouvoir refaire une seule famille
            sans deranger les autres ;
          - le regroupement par type de calcul est maintenu meme sans filtre,
            de sorte qu'afficher tout ne dilue pas les teintes sur l'ensemble.

        Sans ce regroupement, repartir 54 styles sur le cercle chromatique
        donnerait des nuances voisines indiscernables, alors que seuls les
        styles d'une meme famille se cotoient sur un plan.
        """
        from dialogs.dialogs_styles_loader import show_confirm

        # Portee : les lignes AFFICHEES. Filtrer sur un type de calcul limite
        # donc la regeneration a celui-ci, sans toucher aux autres familles.
        #
        # Mais meme sans filtre, le regroupement PAR TYPE DE CALCUL est
        # conserve : sur un plan, seuls les styles d'une meme famille
        # s'affichent ensemble. Chacune repart du debut du cercle chromatique,
        # et deux familles peuvent porter la meme teinte sans jamais se
        # rencontrer — ce qui laisse bien plus d'ecart entre voisins qu'une
        # repartition sur l'ensemble.
        groupes = {}
        for i in etat[u'indices']:
            famille = calcul_par_nom.get(entrees[i][u'nom']) or u''
            groupes.setdefault(famille, []).append(i)
        if not groupes:
            return

        # Motif plein retrouve par sa NATURE et non par son nom : celui-ci est
        # traduit — « <Remplissage de solide> » en francais, « <Solid fill> »
        # ailleurs — et le coder en dur casserait sur une autre langue de Revit.
        solides = sorted([n for n, info in infos_motifs.items() if info[0]],
                         key=lambda n: n.lower())
        nom_solide = solides[0] if solides else u''

        total = sum(len(v) for v in groupes.values())
        nb_familles = len([k for k in groupes if k])
        hors = len(groupes.get(u'', []))
        message = (u"Attribuer des teintes distinctes aux {0} style(s) "
                   u"affiché(s) ?\n\n".format(total))
        if nb_familles > 1:
            message += (u"{0} types de calcul, traités séparément : deux "
                        u"familles peuvent porter la même teinte, elles ne "
                        u"s'affichent jamais sur le même plan".format(
                            nb_familles))
        elif nb_familles == 1:
            message += u"Un seul type de calcul concerné"
        else:
            message += u"Aucun type de calcul connu pour ces styles"
        if hors and nb_familles:
            message += (u", plus {0} style(s) sans type de calcul connu, "
                        u"regroupés à part".format(hors))
        message += u".\n\nLes couleurs de surface actuelles seront remplacées"
        if nom_solide:
            message += (u", et les motifs de remplissage ramenés à "
                        u"« {0} »".format(nom_solide))
        message += u".\n\nLes repères des boutons ne sont pas touchés."
        if not show_confirm(u"NM-BATII — Couleurs de surface", message):
            return

        for _famille, indices in groupes.items():
            teintes = _teintes_distinctes(len(indices))
            for place, i in enumerate(indices):
                entrees[i][u'couleur_plan'] = teintes[place]
                # Remise a plat : une teinte fraiche sur un motif hachure
                # herite d'un reglage precedent donnerait un rendu incoherent
                # avec ce que le bouton annonce.
                entrees[i][u'motif_plan'] = nom_solide
        _rafraichir_liste()

    def _on_autre_couleur(s, e):
        """Selecteur libre, amorce sur la couleur de la premiere ligne choisie."""
        from dialogs.dialogs_styles_loader import show_alert

        positions = _positions_selectionnees()
        if not positions:
            return
        depart = entrees[etat[u'indices'][positions[0]]][u'couleur']
        try:
            hexa = _choisir_couleur_libre(depart, dlg)
        except Exception as ex:
            # Un selecteur qui ne s'ouvre pas doit le dire : sans cela, le
            # bouton parait simplement mort.
            show_alert(u"NM-BATII — Couleur",
                       u"Le sélecteur de couleur n'a pas pu s'ouvrir :\n\n{0}"
                       .format(ex))
            return
        if not hexa:
            return                       # annule par l'utilisateur
        # Selection capturee AVANT l'ouverture de la boite : voir
        # _appliquer_couleur.
        if _appliquer_couleur(hexa, positions) == 0:
            show_alert(u"NM-BATII — Couleur",
                       u"La couleur {0} n'a pu être appliquée à aucune ligne : "
                       u"la sélection a été perdue pendant l'ouverture du "
                       u"sélecteur.".format(hexa))

    def _poser_repere(hexa):
        """
        Applique un repere, et DIT ce qui se passe quand rien ne se passe.

        Le clic sur une pastille traversait jusqu'ici WPF sans un mot : une
        selection vide, ou la moindre exception dans la reconstruction de la
        liste, se soldait par un bouton apparemment mort. Un echec muet est
        indebogable — la regle vaut ici comme ailleurs dans l'extension.
        """
        from dialogs.dialogs_styles_loader import show_alert
        try:
            if _appliquer_couleur(hexa) == 0:
                show_alert(
                    u"NM-BATII — Repère du bouton",
                    u"Aucun style sélectionné.\n\nSélectionnez d'abord une ou "
                    u"plusieurs lignes dans la liste, puis cliquez la teinte.")
        except Exception:
            import traceback
            show_alert(u"NM-BATII — Repère du bouton",
                       u"L'application a échoué :\n\n{0}".format(
                           traceback.format_exc()))

    def _faire_pastille(nom_couleur, hexa):
        b = Button()
        b.Width = 26
        b.Height = 26
        b.Margin = Thickness(0, 0, 4, 4)
        b.MinWidth = 0
        b.MinHeight = 0
        b.Padding = Thickness(0)
        b.Background = _brosse(hexa) or Brushes.Transparent
        b.ToolTip = nom_couleur
        b.Click += (lambda s, e, _h=hexa: _poser_repere(_h))
        return b

    for _nom_c, _hexa in _PALETTE_COULEURS:
        dlg.pnlCouleurs.Children.Add(_faire_pastille(_nom_c, _hexa))

    def _on_retirer(s, e):
        """
        Remet a zero le reglage des styles selectionnes.

        DEUX SORTS, selon que le style existe ou non dans le projet ouvert :

        - PRESENT dans le projet : son reglage est efface — repere, couleur de
          surface, motif — mais la ligne RESTE A SA PLACE. Le rang est un
          classement de travail, penible a refaire ; il n'y a aucune raison de
          le perdre en meme temps que les couleurs. Une version precedente
          retirait la ligne, qui revenait en fin de liste a la reouverture :
          nettoyer une couleur coutait alors tout le classement.

        - ABSENT du projet : la ligne est retiree pour de bon. C'est le menage
          des orphelins, la seule raison d'etre de ce bouton — les styles
          abandonnes s'accumulent au fil des projets.
        """
        from dialogs.dialogs_styles_loader import show_confirm

        positions = _positions_selectionnees()
        if not positions:
            return
        cibles = [entrees[etat[u'indices'][p]] for p in positions]
        presents = [c for c in cibles
                    if calcul_par_nom.get(c[u'nom']) is not None]
        absents_sel = [c for c in cibles
                       if calcul_par_nom.get(c[u'nom']) is None]

        message = u"Réinitialiser {0} style(s) ?\n\n".format(len(cibles))
        if len(cibles) <= 12:
            message += u"\n".join(u"• " + c[u'nom'] for c in cibles) + u"\n\n"
        if presents:
            message += (u"{0} présent(s) dans le projet actif : repère, couleur "
                        u"de surface et motif seront effacés, mais ils gardent "
                        u"leur position dans la liste.".format(len(presents)))
        if absents_sel:
            if presents:
                message += u"\n\n"
            message += (u"{0} absent(s) du projet actif : ceux-là seront "
                        u"retirés de la liste.".format(len(absents_sel)))
        if not show_confirm(u"NM-BATII — Réinitialiser des styles", message):
            return

        for c in presents:
            c[u'couleur']      = u''
            c[u'couleur_plan'] = u''
            c[u'motif_plan']   = u''

        if absents_sel:
            # Retrait par identite : `entrees` doit rester le MEME objet liste,
            # il est capture par les fermetures et renvoye a l'appelant.
            a_retirer = set(id(c) for c in absents_sel)
            restants = [x for x in entrees if id(x) not in a_retirer]
            del entrees[:]
            entrees.extend(restants)

        _rafraichir_liste(set(c[u'nom'] for c in presents))
        _maj_disponibilite()

    # Reglages d'etiquettes du dialogue : une liste d'un element, faute de
    # `nonlocal` en IronPython 2.7. Ils sont modifies par le sous-dialogue,
    # emportes par l'export, remplaces par l'import, et rendus a l'appelant.
    etiquettes = [etiquettes_actuelles or {u'defaut': {u'etiquette': u'',
                                                      u'repere': False},
                                           u'par_calcul': {}}]

    def _on_etiquettes(s, e):
        # try/except OBLIGATOIRE : WPF avale les exceptions levees dans un
        # gestionnaire de clic. Sans lui, un echec survenu APRES la fermeture du
        # sous-dialogue — au moment de relire les controles — passait pour un
        # reglage « qui ne s'enregistre pas », sans le moindre message.
        try:
            resultat = _dialogue_etiquettes(dlg, etiquettes[0], nom_table,
                                            col_calcul)
        except Exception:
            import traceback
            from dialogs.dialogs_styles_loader import show_alert
            show_alert(u"NM-BATII — Étiquettes",
                       u"Réglage des étiquettes interrompu :\n\n{0}".format(
                           traceback.format_exc()))
            return
        if resultat is None:
            return
        etiquettes[0] = resultat
        # Le bouton porte la marque du réglage en attente : « Appliquer » dans
        # le sous-dialogue ne grave rien, c'est CETTE fenêtre puis les
        # paramètres qui enregistrent. Sans ce rappel, fermer ici par Annuler ou
        # par la croix jette les étiquettes sans que rien ne l'ait annoncé.
        dlg.btnEtiquettes.Content = u"Étiquettes…   ●"
        dlg.btnEtiquettes.ToolTip = (
            u"Étiquettes modifiées, pas encore enregistrées. Validez cette "
            u"fenêtre par « Appliquer », puis enregistrez les paramètres.")

    def _on_exporter(s, e):
        _exporter_reglages(dlg, entrees, etiquettes[0])

    def _on_importer(s, e):
        """
        Remplace les reglages courants par ceux d'un fichier.

        Les styles du PROJET absents du fichier ne disparaissent pas : ils sont
        rajoutes en fin de liste, sans reglage. Un fichier venu d'un poste qui
        ne connait pas encore un style ne doit pas le faire disparaitre de la
        vue de celui qui l'a.
        """
        from dialogs.dialogs_styles_loader import show_confirm, show_alert

        lu = _importer_reglages(dlg)
        if lu is None:
            return
        reglages, etiq_fichier = lu

        connus = set(r[u'nom'] for r in reglages)
        manquants = [s2[u'nom'] for s2 in styles_projet
                     if s2[u'nom'] not in connus]
        message = (u"Remplacer les réglages courants par les {0} style(s) du "
                   u"fichier ?\n\nOrdre, repères, couleurs de surface et motifs "
                   u"seront écrasés.".format(len(reglages)))
        if etiq_fichier is not None:
            message += (u"\n\nLes étiquettes seront elles aussi remplacées : "
                        u"{0} type(s) de calcul dans le "
                        u"fichier.".format(len(etiq_fichier[u'par_calcul'])))
        else:
            # Fichier anterieur aux etiquettes : le dire, sans quoi on croirait
            # avoir importe un referentiel complet.
            message += (u"\n\nCe fichier ne contient pas d'étiquettes : le "
                        u"mappage actuel est conservé tel quel.")
        if manquants:
            message += (u"\n\n{0} style(s) du projet actif ne figurent pas dans "
                        u"le fichier : ils seront placés en fin de liste, sans "
                        u"réglage.".format(len(manquants)))
        if not show_confirm(u"NM-BATII — Import", message):
            return

        nouvelles = list(reglages)
        for s2 in styles_projet:
            if s2[u'nom'] not in connus:
                nouvelles.append({u'nom': s2[u'nom'], u'couleur': u'',
                                  u'couleur_plan': u'', u'motif_plan': u''})
        # `entrees` doit rester le MEME objet : les fermetures le capturent, et
        # c'est lui qui est renvoye a l'appelant.
        del entrees[:]
        entrees.extend(nouvelles)
        if etiq_fichier is not None:
            etiquettes[0] = etiq_fichier

        etat[u'decalage'] = 0.0
        _rafraichir_liste()
        _maj_disponibilite()
        show_alert(u"NM-BATII — Import",
                   u"{0} style(s) importé(s){1}.\n\nRien n'est enregistré tant "
                   u"que vous n'avez pas validé cette fenêtre, puis les "
                   u"paramètres.".format(
                       len(reglages),
                       u"" if etiq_fichier is None
                       else u", et {0} étiquette(s) par type de calcul".format(
                           len(etiq_fichier[u'par_calcul']))))

    def _maj_disponibilite(s=None, e=None):
        """
        Grise ce qui exige une selection.

        Un bouton qui ne fait rien parce que rien n'est selectionne passe pour
        un bouton casse. Le grisage repond a la question avant qu'elle ne se
        pose, sans imposer de boite de dialogue a chaque clic a vide.
        """
        actif = len(dlg.lstStyles.SelectedItems) > 0
        for b in (dlg.btnMonter, dlg.btnDescendre, dlg.btnAutreCouleur,
                  dlg.btnSansCouleur, dlg.btnRetirer):
            b.IsEnabled = actif
        for pastille in dlg.pnlCouleurs.Children:
            pastille.IsEnabled = actif

    dlg.btnMonter.Click        += _on_monter
    dlg.btnDescendre.Click     += _on_descendre
    dlg.btnAlpha.Click         += _on_alpha
    dlg.btnAutreCouleur.Click  += _on_autre_couleur
    dlg.btnSansCouleur.Click   += (lambda s, e: _poser_repere(u''))
    dlg.btnRetirer.Click       += _on_retirer
    dlg.btnEtiquettes.Click    += _on_etiquettes
    dlg.btnExporter.Click      += _on_exporter
    dlg.btnImporter.Click      += _on_importer
    dlg.btnGenererPlan.Click   += _on_generer_plan
    dlg.lstStyles.SelectionChanged += _maj_disponibilite
    dlg.cboCalcul.SelectionChanged += (lambda s, e: _rafraichir_liste())
    dlg.sbTexte.ValueChanged += (lambda s, e: _appliquer_decalage(e.NewValue))
    # La fenetre est redimensionnable : la place offerte au texte change avec
    # elle, donc le besoin d'ascenseur aussi.
    dlg.lstStyles.SizeChanged += (lambda s, e: _maj_ascenseur())
    dlg.btnOk.Click     += lambda s, e: setattr(dlg, 'DialogResult', True)
    dlg.btnCancel.Click += lambda s, e: setattr(dlg, 'DialogResult', False)

    _rafraichir_liste()
    _maj_disponibilite()

    try:
        dlg.Owner = parent
    except Exception:
        pass

    if not dlg.show_dialog():
        return None
    return entrees, etiquettes[0]


# ---------------------------------------------------------------------------
# Etiquettes des surfaces par type de calcul
# ---------------------------------------------------------------------------

# Entree de liste deroulante signifiant « ne pas etiqueter ce type de calcul ».
# Une chaine vide serait indistinguable d'un reglage jamais fait ; ici le choix
# est explicite, et il se lit.
_ETIQ_AUCUNE = u'< Aucune étiquette >'

# Ligne du mappage qui s'applique aux types de calcul absents de la liste —
# ceux qu'un AUTRE projet apportera. Le nom de cle vide la designe dans
# config.json.
_ETIQ_DEFAUT = u'< Autres types de calcul >'

# Largeurs reprises telles quelles de l'en-tete d'EtiquettesDialog.xaml. Les
# lignes etant construites ici, une seule des deux ne suffit pas : les deux
# doivent bouger ensemble. Le type de calcul tient en 170 px, tout le reste va
# a l'etiquette — les noms complets « Famille : Type » depassent 70 caracteres,
# et un nom tronque en milieu de chaine ne se distingue plus de son voisin.
_LARGEUR_CALCUL = 170
_LARGEUR_REPERE = 110


def _types_etiquettes_du_projet():
    """
    Noms « Famille : Type » des etiquettes de surface du projet actif.

    Returns:
        tuple: (liste de noms, message d'anomalie ou u'')
    """
    try:
        from pyrevit import HOST_APP
        import utils.surfaces_etiquettes as _m
        reload(_m)
        return [n for n, _id in _m.types_etiquettes(HOST_APP.doc)], u''
    except Exception as ex:
        return [], u"Lecture des types d'étiquette impossible : {0}".format(ex)


def _dialogue_etiquettes(parent, reglages, nom_table, col_calcul):
    """
    Ouvre le dialogue de mappage « type de calcul -> etiquette ».

    Args:
        parent: fenetre proprietaire.
        reglages (dict): {'defaut': {...}, 'par_calcul': {calcul: {...}}}, ou
            chaque valeur vaut {'etiquette': u'Famille : Type', 'repere': bool}.
        nom_table (str): nomenclature de cles, telle que saisie dans le
            formulaire — l'utilisateur vient peut-etre de la corriger.
        col_calcul (str): colonne du type de calcul, meme remarque.

    Returns:
        dict: nouveaux reglages, meme forme qu'en entree, ou None si annule.
    """
    from System.Windows import (Thickness, VerticalAlignment,
                                HorizontalAlignment, GridLength, TextWrapping)
    from System.Windows.Controls import (Grid, ColumnDefinition, TextBlock,
                                         ComboBox, CheckBox)

    xaml = os.path.join(os.path.dirname(__file__), 'EtiquettesDialog.xaml')
    dlg  = forms.WPFWindow(xaml)

    styles_projet, anomalie_table = _lire_styles_du_projet(nom_table, col_calcul)
    etiquettes, anomalie_etiq = _types_etiquettes_du_projet()

    # Types de calcul du projet, puis ceux que la configuration connait sans
    # que le projet actif les emploie : ils servent aux autres projets, les
    # oublier ici reviendrait a perdre leur reglage au premier enregistrement.
    calculs = []
    for s in styles_projet:
        if s[u'calcul'] and s[u'calcul'] not in calculs:
            calculs.append(s[u'calcul'])
    calculs.sort(key=lambda v: v.lower())
    absents = sorted((c for c in (reglages.get(u'par_calcul') or {})
                      if c and c not in calculs), key=lambda v: v.lower())
    calculs.extend(absents)

    messages = []
    if anomalie_table:
        messages.append(anomalie_table)
    else:
        messages.append(u"{0} type(s) de calcul lu(s) dans « {1} ».".format(
            len(calculs) - len(absents), nom_table))
    if absents:
        messages.append(u"{0} type(s) connu(s) de la configuration mais absent(s) "
                        u"du projet actif, conservé(s) pour les autres "
                        u"projets.".format(len(absents)))
    if anomalie_etiq:
        messages.append(anomalie_etiq)
    elif not etiquettes:
        messages.append(u"Aucune étiquette de surface n'est chargée dans ce "
                        u"projet : chargez-en une famille avant de régler le "
                        u"mappage.")
    dlg.txtInfo.Text = u"\n".join(messages)

    # Une ligne = (clef de reglage, ComboBox, CheckBox). La clef vide designe le
    # repli « autres types de calcul ».
    lignes = []
    # Reglages qu'on n'a PAS pu reafficher : leur etiquette n'est ni chargee
    # dans le projet, ni retrouvee dans la liste. Signales avant que « Appliquer »
    # ne les efface.
    introuvables = []

    def _ajouter_ligne(clef, libelle, absent):
        grille = Grid()
        grille.Margin = Thickness(0, 1, 0, 1)
        for largeur in (_LARGEUR_CALCUL, -1, _LARGEUR_REPERE):
            c = ColumnDefinition()
            if largeur > 0:
                c.Width = GridLength(largeur)
            grille.ColumnDefinitions.Add(c)

        etiq = TextBlock()
        etiq.Text = libelle
        etiq.TextWrapping = TextWrapping.Wrap
        etiq.VerticalAlignment = VerticalAlignment.Center
        etiq.Margin = Thickness(2, 0, 4, 0)
        etiq.ToolTip = libelle
        if absent:
            grise = _brosse(u'#999999')
            if grise is not None:
                etiq.Foreground = grise
            etiq.ToolTip = (u"Ce type de calcul n'existe pas dans le projet "
                            u"actif. Son réglage est conservé pour les projets "
                            u"qui l'emploient.")
        Grid.SetColumn(etiq, 0)
        grille.Children.Add(etiq)

        combo = ComboBox()
        combo.Padding = Thickness(6, 3, 6, 3)
        combo.Margin = Thickness(4, 0, 4, 0)
        combo.Items.Add(_ETIQ_AUCUNE)
        for nom in etiquettes:
            combo.Items.Add(nom)
        # Une etiquette enregistree mais absente du projet reste proposee, et
        # signalee : la retirer en silence ferait perdre le reglage au premier
        # enregistrement, sur un poste ou la famille n'est pas chargee.
        voulue = (reglages.get(u'par_calcul', {}).get(clef, {}) or {}) \
            if clef else (reglages.get(u'defaut') or {})
        nom_voulu = (voulue.get(u'etiquette') or u'').strip()
        if nom_voulu and nom_voulu not in etiquettes:
            combo.Items.Add(nom_voulu)
            combo.ToolTip = (u"« {0} » n'est pas chargée dans ce projet. Le "
                             u"réglage est conservé.".format(nom_voulu))
        # Selection par INDEX, apres recherche explicite. `SelectedItem = nom`
        # ne signale rien quand la valeur n'est pas dans la liste : la ligne
        # retombait sur « Aucune étiquette », et l'enregistrement suivant
        # effacait le reglage sans que personne ne l'ait demande. Ici, un echec
        # de selection se voit et se compte.
        cible = nom_voulu if nom_voulu else _ETIQ_AUCUNE
        indice = combo.Items.IndexOf(cible)
        if indice < 0:
            indice = 0
            if nom_voulu:
                introuvables.append((libelle, nom_voulu))
        combo.SelectedIndex = indice
        Grid.SetColumn(combo, 1)
        grille.Children.Add(combo)

        coche = CheckBox()
        coche.IsChecked = bool(voulue.get(u'repere'))
        coche.VerticalAlignment = VerticalAlignment.Center
        # Centree dans sa colonne, comme son en-tete : callee a gauche, elle
        # flottait loin de son intitule et se rattachait visuellement a la
        # liste deroulante voisine.
        coche.HorizontalAlignment = HorizontalAlignment.Center
        coche.Margin = Thickness(0)
        coche.ToolTip = u"Pose l'étiquette avec sa ligne de repère."
        Grid.SetColumn(coche, 2)
        grille.Children.Add(coche)

        dlg.pnlLignes.Children.Add(grille)
        lignes.append((clef, combo, coche))

    for c in calculs:
        _ajouter_ligne(c, c, c in absents)
    # Le repli en dernier : c'est une exception, pas la regle a lire d'abord.
    _ajouter_ligne(u'', _ETIQ_DEFAUT, False)

    if introuvables:
        dlg.txtInfo.Text += (
            u"\n⚠ {0} réglage(s) n'ont pas pu être réaffichés, leur étiquette "
            u"étant introuvable : {1}. Valider maintenant les effacerait — "
            u"annulez si vous ne vouliez pas les perdre.".format(
                len(introuvables),
                u" ; ".join(u"« {0} » → {1}".format(l, n)
                            for l, n in introuvables[:3])))
        dlg.txtInfo.Foreground = _brosse(u'#B00020') or dlg.txtInfo.Foreground

    dlg.btnOk.Click     += lambda s, e: setattr(dlg, 'DialogResult', True)
    dlg.btnCancel.Click += lambda s, e: setattr(dlg, 'DialogResult', False)

    try:
        dlg.Owner = parent
    except Exception:
        pass

    if not dlg.show_dialog():
        return None

    resultat = {u'defaut': {u'etiquette': u'', u'repere': False},
                u'par_calcul': {}}
    perdus = []
    for clef, combo, coche in lignes:
        nom = combo.SelectedItem
        nom = u'' if (nom is None or nom == _ETIQ_AUCUNE) else unicode(nom)
        valeur = {u'etiquette': nom, u'repere': bool(coche.IsChecked)}
        if not clef:
            resultat[u'defaut'] = valeur
            continue

        # Une ligne compte des qu'elle porte QUELQUE CHOSE — une étiquette ou
        # une ligne de repère. Elle n'etait retenue qu'avec une etiquette :
        # cocher le repere sur un type de calcul pas encore associe a une
        # etiquette ne laissait donc aucune trace, alors que la ligne « autres
        # types de calcul », enregistree sans condition, gardait la sienne.
        # Deux comportements pour une meme case, d'ou l'impression qu'elle ne
        # s'enregistrait pas.
        if nom or valeur[u'repere']:
            resultat[u'par_calcul'][clef] = valeur

        avant = (reglages.get(u'par_calcul') or {}).get(clef) or {}
        if avant.get(u'etiquette') and not nom:
            # L'etiquette qui etait la n'y est plus. L'effacement est peut-etre
            # voulu ; il ne doit pas se produire sans qu'on l'ait dit.
            perdus.append(clef)

    if perdus:
        from dialogs.dialogs_styles_loader import show_confirm
        if not show_confirm(
                u"NM-BATII — Étiquettes",
                u"{0} type(s) de calcul n'ont plus d'étiquette et vont perdre "
                u"leur réglage :\n\n{1}\n\nContinuer ?".format(
                    len(perdus), u"\n".join(u"• " + p for p in perdus))):
            return None
    return resultat


def _etiquettes_depuis_config(sf):
    """Section « étiquettes » de config.json -> reglages exploitables."""
    reglages = {u'defaut': {u'etiquette': u'', u'repere': False},
                u'par_calcul': {}}
    d = sf.get('etiquette_defaut')
    if isinstance(d, dict):
        reglages[u'defaut'] = {
            u'etiquette': (d.get('etiquette') or u'').strip(),
            u'repere':    bool(d.get('repere')),
        }
    for e in (sf.get('etiquettes_par_calcul', []) or []):
        if not isinstance(e, dict):
            continue
        calcul = (e.get('calcul') or u'').strip()
        nom    = (e.get('etiquette') or u'').strip()
        repere = bool(e.get('repere'))
        # Une ligne de repere SANS etiquette est un reglage valable : elle dit
        # comment poser l'etiquette le jour ou elle sera choisie. L'exiger avec
        # une etiquette revenait a jeter la case a la relecture.
        if calcul and (nom or repere):
            reglages[u'par_calcul'][calcul] = {u'etiquette': nom,
                                               u'repere': repere}
    return reglages


def _etiquettes_vers_config(reglages):
    """Reglages -> (valeur de 'etiquette_defaut', valeur de 'etiquettes_par_calcul')."""
    defaut = reglages.get(u'defaut') or {}
    par_calcul = []
    for calcul in sorted(reglages.get(u'par_calcul', {}), key=lambda v: v.lower()):
        v = reglages[u'par_calcul'][calcul]
        par_calcul.append({'calcul':    calcul,
                           'etiquette': v.get(u'etiquette', u''),
                           'repere':    bool(v.get(u'repere'))})
    return ({'etiquette': (defaut.get(u'etiquette') or u''),
             'repere':    bool(defaut.get(u'repere'))},
            par_calcul)


# ---------------------------------------------------------------------------
# Format du referentiel des disciplines
# ---------------------------------------------------------------------------
# Fonctions de MODULE et non de _init_disciplines : voir la docstring de
# _init_disciplines pour la raison, qui tient a IronPython et non au decoupage.

# Deux familles de teintes, du plus fonce au plus clair. Les quatre premiers
# bleus et les deux premiers oranges sont ceux de la mise en forme
# conditionnelle du classeur de reference ; les suivants prolongent la rampe
# pour les decoupages plus profonds.
# Le BLEU couvre les niveaux du Code (disciplines et sous-disciplines),
# l'ORANGE ceux qui vont au-dela : classement d'ouvrage. La frontiere etant
# reglable, la couleur d'un niveau se calcule, elle n'est pas figee en XAML.
_DISC_BLEUS = (u'#366092', u'#538DD5', u'#8DB4E2',
               u'#C5D9F1', u'#DDEBF7', u'#EFF6FC')
_DISC_ORANGES = (u'#E36C09', u'#F79646', u'#FAC090',
                 u'#FBD5B5', u'#FDE9D9', u'#FEF4EC')
# Code illisible : le niveau n'a pas pu etre deduit, la ligne doit trancher.
_DISC_COULEUR_ERREUR = u'#FFF0F0'


def _disc_couleur_niveau(niveau, niveaux_code, niveaux_total):
    """
    Teinte de fond d'une ligne. Bleu dans le Code, orange au-dela.

    La rampe est etiree sur le nombre de niveaux REELLEMENT utilises de chaque
    cote : avec trois niveaux de Code on prend les trois bleus les plus fonces,
    pas un sur deux — le degrade doit rester lisible quel que soit le reglage.
    """
    if not niveau:
        return _DISC_COULEUR_ERREUR
    if niveau <= niveaux_code:
        rampe, rang, total = _DISC_BLEUS, niveau - 1, max(1, niveaux_code)
    else:
        rampe = _DISC_ORANGES
        rang = niveau - niveaux_code - 1
        total = max(1, niveaux_total - niveaux_code)
    if total <= len(rampe):
        return rampe[min(rang, len(rampe) - 1)]
    # Plus de niveaux que de teintes : on repartit sur toute la rampe.
    return rampe[min(int(rang * len(rampe) / total), len(rampe) - 1)]


def _disc_texte_sur(hexa):
    """
    Noir ou blanc, selon celui qui contraste le mieux avec le fond (WCAG).

    Calcule plutot que choisi a l'oeil : sur le bleu moyen du classeur, le
    blanc tombe a 3,4 — sous le seuil AA — la ou le noir donne 6,1.
    """
    rvb = _hex_vers_rvb(hexa)
    if rvb is None:
        return u'#000000'

    def _canal(v):
        v = v / 255.0
        return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4

    lum = (0.2126 * _canal(rvb[0]) + 0.7152 * _canal(rvb[1])
           + 0.0722 * _canal(rvb[2]))
    contraste_blanc = 1.05 / (lum + 0.05)
    contraste_noir = (lum + 0.05) / 0.05
    return u'#FFFFFF' if contraste_blanc > contraste_noir else u'#000000'




def _disc_resume_format(nb, niveaux_code, digits, lg_disc, lg_ouv, sep,
                        majuscules):
    """
    Resume d'une ligne du format, affiche en tete de la fenetre d'aide.

    Le seul bloc VARIABLE de cette aide : le reste y est une regle, pas un
    etat. Le lire sans ouvrir « Structure de la table… » evite d'avoir a
    naviguer dans deux fenetres pour verifier un decoupage.
    """
    return (u"Code Discipline : {} chiffres sur {} niveau(x)  ·  "
            u"Code Ouvrage : {} chiffres sur {} niveau(x)  ·  "
            u"tranches {}  ·  abrév. disciplines {}  ·  "
            u"abrév. ouvrages {}  ·  séparateur {}  ·  {}".format(
                sum(digits[:niveaux_code]), niveaux_code,
                sum(digits), nb,
                u"-".join(str(_d) for _d in digits),
                # Toutes deux couvrent tous les niveaux : les deux colonnes
                # d'abreviation se saisissent sur toutes les lignes.
                u"-".join(str(_a) for _a in lg_disc[:nb]) or u"—",
                u"-".join(str(_a) for _a in lg_ouv[:nb]) or u"—",
                (u"« {} »".format(sep) if sep else u"aucun"),
                u"majuscules forcées" if majuscules else u"casse libre"))


# Jetons d'HERITAGE des deux colonnes de gabarit — « Abrév. Discipline » et
# « Abrév. Ouvrage ». {sup1} vaut l'abreviation RESOLUE du niveau juste
# au-dessus DANS LA MEME CHAINE, {sup2} celle d'encore au-dessus, et ainsi de
# suite sans limite. Ecrits tels quels dans la cellule, l'heritage se lit a
# l'ecran au lieu de se deduire de reglages.
#
# Le rang compte les ANCETRES PRESENTS dans la table, pas les niveaux du code :
# une branche a trous se numerote comme elle s'affiche, et aucun jeton ne peut
# viser une ligne inexistante. Prendre {sup2} plutot que {sup1} revient donc a
# SAUTER un niveau en reprenant tout ce qui le domine.
_DISC_SUP_MODELE = u'{sup%d}'
_DISC_SUP1 = _DISC_SUP_MODELE % 1
_DISC_RE_SUP = re.compile(ur'\{sup(\d+)\}', re.I)
# « {sup} » sans rang : forme d'avant la numerotation, relue comme {sup1}.
_DISC_RE_SUP_ANCIEN = re.compile(ur'\{sup\}', re.I)

# Jeton de RENVOI, propre a « Abrév. Ouvrage » : il vaut l'abreviation de
# discipline resolue DE LA MEME LIGNE. C'est la valeur forcee du niveau 1 —
# une chaine d'abreviation d'ouvrage part toujours de sa discipline — et il
# reste disponible plus bas pour rebaser la chaine sur la discipline courante.
_DISC_DIS = u'{dis}'

# Separateurs de LISIBILITE qu'un Code Ouvrage peut trainer : espaces (dont
# l'insecable et le fin, qu'Excel et Word posent comme separateurs de milliers),
# point, tiret, tiret long, souligne, apostrophe. Un code colle depuis un
# tableur arrive regulierement en « 5 111 00 » ou « 511-100 » ; le refuser d'un
# « chiffres uniquement » ferait retaper une valeur pourtant juste.
# On ne retire QUE du formatage : `isdigit()` reste seul juge de la validite.
_DISC_RE_SEP_CODE = re.compile(ur"[\s   .\-–—_']+")


def _disc_nettoyer_code(brut):
    """Code debarrasse de son formatage de lisibilite, sans rien valider."""
    return _DISC_RE_SEP_CODE.sub(u'', (brut or u'').strip())


def _disc_rangs_dispo(nb_ancetres):
    """
    Phrase de RECUPERATION pour un jeton hors portee.

    « qui compte 2 niveau(x) au-dessus » nommait le probleme et laissait
    l'utilisateur en deduire le rang utilisable ; autant l'ecrire.
    """
    if nb_ancetres <= 0:
        return (u"Cette ligne n'a aucun niveau au-dessus : donnez-lui son "
                u"propre texte.")
    if nb_ancetres == 1:
        return u"Seul {sup1} est disponible ici."
    return u"Rangs disponibles ici : {} à {}.".format(
        _DISC_SUP_MODELE % 1, _DISC_SUP_MODELE % nb_ancetres)

# Tous les jetons reconnus, pour les mettre a l'ecart des majuscules et du
# comptage de longueur.
_DISC_RE_JETON = re.compile(ur'\{sup\d+\}|\{dis\}', re.I)


def _disc_canoniser_jetons(txt):
    """Ramene les jetons a leur forme canonique : « {SUP2} » et « {Sup} »
    deviennent « {sup2} » et « {sup1} »."""
    return _DISC_RE_JETON.sub(
        lambda m: m.group(0).lower(),
        _DISC_RE_SUP_ANCIEN.sub(_DISC_SUP1, txt))


# Le NFKD de l'IronPython embarque ne DECOMPOSE PAS ces ligatures — verifie
# sur le moteur reel, pas suppose. Sans ce correctif, « SECOND-ŒUVRE » (une
# discipline reelle du referentiel) resterait accentuee malgre l'appel a
# _disc_sans_accents.
_DISC_LIGATURES = {u'Œ': u'OE', u'œ': u'oe',
                   u'Æ': u'AE', u'æ': u'ae'}


def _disc_sans_accents(txt):
    """
    Diacritiques retires : « ÉLECTRICITÉ » devient « ELECTRICITE », « ŒUVRE »
    devient « OEUVRE ». Ce qui n'est pas un accent (espaces, tirets,
    esperluette) ne bouge pas.

    Le referentiel est une nomenclature technique : l'accent n'y porte
    aucune information qu'une lettre nue ne porterait deja, et il complique
    la recherche, le tri, et la reprise dans des systemes qui ne l'attendent
    pas (noms de fichiers, cartouches). Sans effet sur un jeton — {sup1},
    {dis} — qui ne contient aucun caractere accentuable.
    """
    if not txt:
        return txt
    for _lig, _depl in _DISC_LIGATURES.items():
        if _lig in txt:
            txt = txt.replace(_lig, _depl)
    try:
        import unicodedata
        _plat = unicodedata.normalize('NFKD', txt)
        return u''.join(_c for _c in _plat if not unicodedata.combining(_c))
    except Exception:
        # Module absent d'un moteur inhabituel : le texte accentue vaut
        # mieux qu'une exception qui bloquerait tout le recalcul.
        return txt


def _dialogue_format_disciplines(parent, fmt, nb_lignes):
    """
    Fenetre « Structure de la table » : profondeur, decoupage du code et
    longueur des deux chaines d'abreviation.

    `fmt` est une COPIE de l'etat courant : on la modifie librement, et c'est
    seulement le dict RETOURNE qui est applique. Annuler laisse donc le
    referentiel exactement dans l'etat ou il etait, y compris quand on a joue
    avec le nombre de niveaux avant de se raviser. Retourne None sur annulation.
    """
    import clr as _clr_fmt
    _clr_fmt.AddReference('System.Data')
    from System.Data import DataTable as _FmtDataTable
    from System import Action as _FmtAction
    from System.Windows import Visibility as _FmtVisibility
    from System.Windows.Threading import DispatcherPriority as _FmtPriority
    from System.Windows.Input import Key as _FmtKey

    _xaml = os.path.join(os.path.dirname(__file__),
                         'FormatDisciplinesDialog.xaml')
    _dlg = forms.WPFWindow(_xaml)
    try:
        _dlg.Owner = parent
    except Exception:
        pass

    def _ent(val, defaut):
        try:
            return int(str(val).strip())
        except Exception:
            return defaut

    _dt = _FmtDataTable()
    _dt.Columns.Add('niveau')
    _dt.Columns.Add('portee')
    _dt.Columns.Add('digits')
    # DEUX longueurs, une par chaine d'abreviation, reglables l'une comme
    # l'autre a tous les niveaux : les deux colonnes de gabarit se saisissent
    # sur toutes les lignes du referentiel. La colonne « Portée » situe la
    # frontiere du Code, elle ne restreint pas la saisie.
    _dt.Columns.Add('long_disc')
    _dt.Columns.Add('long_ouv')

    def _remplir(nb, nb_code, digits, lg_disc, lg_ouv):
        _dt.Rows.Clear()
        for _i in range(nb):
            _r = _dt.NewRow()
            _r['niveau']   = str(_i + 1)
            _r['portee']   = (u'Code Discipline' if _i < nb_code
                              else u'Code Ouvrage')
            _r['digits']   = str(digits[_i] if _i < len(digits) else 1)
            # Forme canonique a l'affichage : un « 05 » ou un « 5 ; 2 » saisi
            # se relit « 5 » et « 2;5 », plutot que de rester tel quel dans
            # une cellule dont on ne saurait plus si elle a ete comprise.
            _r['long_disc'] = _disc_texte_longueur(
                lg_disc[_i] if _i < len(lg_disc) else 3, 3)
            _r['long_ouv'] = _disc_texte_longueur(
                lg_ouv[_i] if _i < len(lg_ouv) else 3, 3)
            _dt.Rows.Add(_r)

    _remplir(fmt['niveaux'], fmt['niveaux_code'], fmt['digits'],
             fmt['long_disc'], fmt['long_ouv'])
    _dlg.dgFormat.ItemsSource = _dt.DefaultView
    _dlg.txtNivTotal.Text = str(fmt['niveaux'])
    _dlg.txtNivDiscipline.Text = str(fmt['niveaux_code'])
    _dlg.txtSep.Text = fmt['separateur'] or u''
    _dlg.chkMajuscules.IsChecked = bool(fmt['majuscules'])

    _garde = [False]
    _lg_code_avant = sum(fmt['digits'][:fmt['niveaux_code']])
    _lg_ouv_avant = sum(fmt['digits'][:fmt['niveaux']])

    def _lire():
        _digits, _lg_d, _lg_o = [], [], []
        for _r in _dt.DefaultView:
            _digits.append(max(1, min(_ent(_r['digits'], 1), 4)))
            # Ni _ent() ni bornage a 1 : la cellule accepte « 0 » et
            # « 2;5 » autant qu'un nombre. _disc_texte_longueur valide et
            # normalise, et retombe sur 3 si la saisie est incomprise.
            _lg_d.append(_disc_texte_longueur(_r['long_disc'], 3))
            _lg_o.append(_disc_texte_longueur(_r['long_ouv'], 3))
        return _digits, _lg_d, _lg_o

    def _profondeur():
        """
        (niveaux de discipline, niveaux d'ouvrage, total).

        Le TOTAL est saisi, la frontiere du Code Discipline aussi ; les niveaux
        d'ouvrage sont ce qui reste. La frontiere ne peut pas depasser le
        total — sans quoi il n'y aurait plus de code du tout au-dela.

        AUCUN plafond sur le total : la profondeur est une decision metier, pas
        une limite d'affichage. Seul plancher, un niveau — un referentiel sans
        aucun niveau ne veut rien dire.
        """
        _nb = max(1, _ent(_dlg.txtNivTotal.Text, 1))
        _nc = max(1, min(_ent(_dlg.txtNivDiscipline.Text, 1), _nb))
        return _nc, _nb - _nc, _nb

    def _nb_code():
        return _profondeur()[0]

    def _rafraichir(*_a):
        if _garde[0]:
            return
        _garde[0] = True
        try:
            _digits, _lg_d, _lg_o = _lire()
            _nc = _nb_code()

            # La colonne « Portée » suit le champ « Nbr Niveaux Discipline » :
            # la frontiere se voit dans la table, pas seulement dans un chiffre
            # au-dessus.
            for _i, _r in enumerate(_dt.DefaultView):
                _p = u'Code Discipline' if _i < _nc else u'Code Ouvrage'
                if str(_r['portee'] or u'') != _p:
                    _r['portee'] = _p

            # Changer une longueur REINTERPRETE tous les codes deja saisis :
            # le dire avant de valider, pas apres.
            _lg_code = sum(_digits[:_nc])
            _lg_ouv = sum(_digits)
            _alertes = []
            if nb_lignes and _lg_code != _lg_code_avant:
                _alertes.append(
                    u"Le Code Discipline passe de {} à {} chiffres.".format(
                        _lg_code_avant, _lg_code))
            if nb_lignes and _lg_ouv != _lg_ouv_avant:
                _alertes.append(
                    u"Le Code Ouvrage passe de {} à {} chiffres.".format(
                        _lg_ouv_avant, _lg_ouv))
            if _alertes:
                _dlg.txtAlerte.Text = (
                    u"⚠  " + u"  ".join(_alertes)
                    + u"  Les {} ligne(s) du référentiel seront relues avec ce "
                      u"découpage : leur niveau peut changer.".format(nb_lignes))
                _dlg.txtAlerte.Visibility = _FmtVisibility.Visible
            else:
                _dlg.txtAlerte.Visibility = _FmtVisibility.Collapsed
        finally:
            _garde[0] = False

    def _differer(*_a):
        # Les evenements d'edition du DataGrid se declenchent AVANT que la
        # saisie n'atteigne la DataRow : recalculer sur-le-champ travaillerait
        # sur l'ancienne valeur.
        try:
            _dlg.Dispatcher.BeginInvoke(_FmtPriority.Background,
                                        _FmtAction(_rafraichir))
        except Exception:
            _rafraichir()

    def _reconstruire_lignes(*_a):
        """
        Ajuste le NOMBRE de lignes de la table sur le total saisi, sans
        perdre les largeurs deja saisies pour les niveaux conserves.

        Sur LostFocus/Entree, PAS sur TextChanged : vider le champ pour le
        retaper est un reflexe de saisie normal, et lu a chaque frappe le
        champ vide valait 1 (voir _profondeur) — la table s'effondrait a une
        ligne avant meme la fin de la frappe, puis regrossissait avec des
        valeurs par defaut qui effacaient les reglages deja faits pour les
        niveaux intermediaires.
        """
        if _garde[0]:
            return
        _nc, _no, _nb = _profondeur()
        if _nb == _dt.Rows.Count:
            # Meme profondeur, mais la frontiere a pu bouger : la colonne
            # « Portée » et le résumé suffisent, inutile de reconstruire.
            _differer()
            return
        _digits, _lg_d, _lg_o = _lire()
        while len(_digits) < _nb:
            _digits.append(1)
            _lg_d.append(3)
            _lg_o.append(3)
        _garde[0] = True
        try:
            _remplir(_nb, _nc, _digits, _lg_d, _lg_o)
        finally:
            _garde[0] = False
        _differer()

    def _touche_niv_total(sender, e):
        if e.Key == _FmtKey.Enter:
            _reconstruire_lignes()
            e.Handled = True

    # AUCUNE cellule bloquee ici : les deux colonnes d'abreviation se
    # saisissent sur toutes les lignes du referentiel, leurs longueurs se
    # reglent donc a tous les niveaux. La colonne « Portée » situe la frontiere
    # du Code, elle ne restreint pas la saisie.
    #
    # txtNivDiscipline ne fait jamais varier le NOMBRE de lignes (la frontiere
    # est plafonnee au total, voir _profondeur) : _differer() lui suffit sur
    # CHAQUE frappe, live. Seul txtNivTotal peut changer le compte de lignes,
    # et c'est le seul a differer sa reconstruction.
    _dlg.dgFormat.CellEditEnding      += _differer
    _dlg.txtNivTotal.TextChanged      += _differer
    _dlg.txtNivTotal.LostFocus        += _reconstruire_lignes
    _dlg.txtNivTotal.PreviewKeyDown   += _touche_niv_total
    _dlg.txtNivDiscipline.TextChanged += _differer
    _dlg.txtSep.TextChanged           += _differer
    _dlg.chkMajuscules.Checked        += _differer
    _dlg.chkMajuscules.Unchecked      += _differer

    _resultat = [None]

    def _on_ok(s, e):
        # La derniere frappe dans txtNivTotal peut ne pas avoir quitte le
        # champ (LostFocus non declenche) : _on_ok lit len(_digits), qui
        # vient de la table, pas du champ. Sans reconstruire ici, valider
        # juste apres avoir tape un nouveau total appliquerait l'ANCIEN
        # nombre de lignes.
        _reconstruire_lignes()
        _commit_datagrid_edit(_dlg.dgFormat)
        _digits, _lg_d, _lg_o = _lire()
        _resultat[0] = {
            'niveaux':      len(_digits),
            'niveaux_code': _nb_code(),
            'digits':       _digits,
            'long_disc':    _lg_d,
            'long_ouv':     _lg_o,
            'separateur':   _dlg.txtSep.Text,
            'majuscules':   bool(_dlg.chkMajuscules.IsChecked),
        }
        setattr(_dlg, 'DialogResult', True)

    def _on_aide(s, e):
        """
        La MEME page d'aide que l'onglet, avec le format tel qu'il est saisi
        ici et maintenant — pas celui enregistre : on regle justement ces
        valeurs, les lire figees n'aiderait pas.
        """
        _commit_datagrid_edit(_dlg.dgFormat)
        _d, _a, _o = _lire()
        _dialogue_aide_disciplines(
            _dlg,
            _disc_resume_format(len(_d), _nb_code(), _d, _a, _o,
                                _dlg.txtSep.Text,
                                bool(_dlg.chkMajuscules.IsChecked)))

    _dlg.btnAide.Click   += _on_aide
    _dlg.btnOk.Click     += _on_ok
    _dlg.btnCancel.Click += lambda s, e: setattr(_dlg, 'DialogResult', False)

    _rafraichir()
    if not _dlg.show_dialog():
        return None
    return _resultat[0]


def _dialogue_aide_disciplines(parent, resume):
    """
    Fenetre d'aide de l'onglet, ouverte par le bouton « ? ».

    Tout le contenu est fige en XAML — c'est la regle du referentiel, pas un
    etat — sauf `resume`, le format en vigueur, qui change d'un referentiel a
    l'autre et se lit en tete.
    """
    _xaml = os.path.join(os.path.dirname(__file__),
                         'AideDisciplinesDialog.xaml')
    _dlg = forms.WPFWindow(_xaml)
    try:
        _dlg.Owner = parent
    except Exception:
        pass
    _dlg.txtFormat.Text = resume
    _dlg.btnClose.Click += lambda s, e: setattr(_dlg, 'DialogResult', True)
    _dlg.show_dialog()


def _disc_entier(val, defaut):
    try:
        return int(str(val).strip())
    except Exception:
        return defaut


# ---------------------------------------------------------------------------
# Longueur d'abreviation : fixe, bornee, ou nulle
# ---------------------------------------------------------------------------
# Le reglage de longueur des deux colonnes de gabarit accepte TROIS formes,
# saisies dans « Structure de la table… » :
#
#     0      aucun caractere significatif : la cellule ne peut porter que des
#            jetons ({supN}, {dis}) et des separateurs. Sert aux niveaux qui
#            n'ajoutent rien d'eux-memes et se contentent d'heriter ;
#     3      longueur FIXE de 3 caracteres significatifs ;
#     2;5    BORNES, de 2 a 5 caracteres. Le mini peut valoir 0, ce qui rend
#            l'abreviation facultative sans la plafonner a rien.
#
# Dans les trois cas les jetons et les separateurs restent autorises et ne
# comptent jamais dans la longueur : c'est la regle d'origine, inchangee.
_DISC_LG_SEP = u';'
_DISC_LG_MAX = 12


def _disc_bornes_longueur(valeur, defaut=3):
    """
    (mini, maxi) de longueur significative, depuis une valeur de reglage.

    Accepte un entier (ancien format stocke) comme un texte. Toute saisie
    incomprise retombe sur `defaut` en longueur fixe plutot que de lever :
    un reglage illisible ne doit pas empecher la table de s'afficher, il se
    corrige dans la fenetre de structure.
    """
    _t = u'' if valeur is None else unicode(valeur).strip()
    if not _t:
        return (defaut, defaut)
    if _DISC_LG_SEP in _t:
        _g, _sep, _d = _t.partition(_DISC_LG_SEP)
        _mini = _disc_entier(_g.strip(), None)
        _maxi = _disc_entier(_d.strip(), None)
        if _mini is None or _maxi is None:
            return (defaut, defaut)
        # Bornes inversees : les remettre d'aplomb vaut mieux que de rendre
        # un intervalle vide, qui signalerait toutes les lignes en anomalie.
        if _mini > _maxi:
            _mini, _maxi = _maxi, _mini
        return (max(0, min(_mini, _DISC_LG_MAX)),
                max(0, min(_maxi, _DISC_LG_MAX)))
    _n = _disc_entier(_t, None)
    if _n is None:
        return (defaut, defaut)
    _n = max(0, min(_n, _DISC_LG_MAX))
    return (_n, _n)


def _disc_texte_longueur(valeur, defaut=3):
    """
    Forme canonique du reglage : « 0 », « 3 » ou « 2;5 ».

    Ce qui est STOCKE est du texte, pas un entier : « 2;5 » n'en est pas un.
    Repasser par cette fonction a chaque lecture garde config.json, le
    fichier de configuration et la grille sur la meme ecriture.
    """
    _mini, _maxi = _disc_bornes_longueur(valeur, defaut)
    if _mini == _maxi:
        return u'{}'.format(_mini)
    return u'{}{}{}'.format(_mini, _DISC_LG_SEP, _maxi)


def _disc_longueur_conforme(utile, valeur, defaut=3):
    """
    (conforme, message) pour une longueur significative donnee.

    `utile` est la chaine reduite a ses caracteres significatifs. Un gabarit
    qui n'en a AUCUN — reduit a « {sup1} » — reste dispense quel que soit le
    reglage : il dit « rien de plus que le niveau vise », ce qui est une
    reponse legitime et non une abreviation trop courte.
    """
    if not utile:
        return (True, u'')
    _mini, _maxi = _disc_bornes_longueur(valeur, defaut)
    if _mini <= len(utile) <= _maxi:
        return (True, u'')
    if _maxi == 0:
        _attendu = u"aucun caractère attendu"
    elif _mini == _maxi:
        _attendu = u"{} caractère(s) attendu(s)".format(_maxi)
    else:
        _attendu = u"entre {} et {} caractère(s) attendu(s)".format(
            _mini, _maxi)
    return (False, u"{} hors jetons et séparateurs, {} trouvé(s)".format(
        _attendu, len(utile)))


def _disc_format_stocke(brut):
    """
    Lit un bloc `format` STOCKE (config.json ou fichier de configuration) et
    rend (niveaux, niveaux_code, [digits], [long. disc.], [long. ouvrage]).

    Trois migrations possibles : l'ancien schema a deux niveaux (longueur_code /
    digits_discipline / longueur_acronyme / longueur_acronyme_sous), le schema a
    N niveaux sans frontiere de Code, et `acronyme_par_niveau` — la longueur
    unique d'avant la separation des deux chaines d'abreviation, reprise pour
    les deux. Dans tous les cas la conversion est exacte : sans frontiere
    declaree, tous les niveaux appartiennent au Code, ce qui reproduit le
    comportement d'avant.

    De MODULE et non locale a _init_disciplines : le chargement d'un fichier
    .NM-DisciplinesConfig doit passer par la meme conversion que config.json,
    sans quoi un fichier d'une version anterieure se relirait autrement.
    """
    brut = brut if isinstance(brut, dict) else {}
    _nb = _disc_entier(brut.get('niveaux'), 0)
    _dig = brut.get('digits_par_niveau')
    # `acronyme_par_niveau` : nom de la cle avant la separation.
    _ld = (brut.get('longueur_abrev_discipline')
           or brut.get('acronyme_par_niveau'))
    _lo = (brut.get('longueur_abrev_ouvrage')
           or brut.get('acronyme_par_niveau'))
    if _nb and isinstance(_dig, list) and isinstance(_ld, list):
        _nb = max(1, _nb)
        _dig = [_disc_entier(_v, 1) for _v in _dig][:_nb]
        # Les longueurs restent du TEXTE : « 2;5 » n'est pas un entier, et
        # le coercer en perdrait la borne haute.
        _ld = [_disc_texte_longueur(_v, 3) for _v in _ld][:_nb]
        _lo = [_disc_texte_longueur(_v, 3)
               for _v in (_lo if isinstance(_lo, list) else [])][:_nb]
    else:
        _lc = _disc_entier(brut.get('longueur_code'), 3)
        _dd = _disc_entier(brut.get('digits_discipline'), 1)
        _dd = max(1, min(_dd, _lc - 1))
        _nb = 2
        _dig = [_dd, max(1, _lc - _dd)]
        _ld = [_disc_texte_longueur(brut.get('longueur_acronyme'), 4),
               _disc_texte_longueur(brut.get('longueur_acronyme_sous'), 3)]
        _lo = list(_ld)
    while len(_dig) < _nb:
        _dig.append(1)
    while len(_ld) < _nb:
        _ld.append(u'3')
    while len(_lo) < _nb:
        _lo.append(u'3')

    # Sans frontiere declaree, tout le code est du Code Discipline.
    _nc = _disc_entier(brut.get('niveaux_code'), 0) or _nb
    return _nb, max(1, min(_nc, _nb)), _dig, _ld, _lo


# ---------------------------------------------------------------------------
# Disciplines : fichier de configuration
# ---------------------------------------------------------------------------
# Extension DEDIEE plutot que « .json » : un double-clic ne doit pas ouvrir
# n'importe quel json comme un referentiel, et le filtre du selecteur de
# fichiers ne montre que ce qui se charge vraiment. Meme principe que le
# .NM-Map-Infos-Proj du mappage des infos projet.
_DISC_CFG_EXT = u'NM-DisciplinesConfig'
_DISC_CFG_FILTRE = (u'Configuration Disciplines (*.{0})|*.{0}'
                    .format(_DISC_CFG_EXT))
# Le fichier porte la table ET la structure : recharger l'une sans l'autre
# reinterpreterait tous les codes avec le mauvais decoupage.
_DISC_CFG_DEFAUT = u'disciplines.' + _DISC_CFG_EXT


def _disc_section(fmt, lignes, txt):
    """
    Assemble le dict {format, table} du referentiel, dans la forme EXACTE ou il
    part dans config.json.

    Un seul assembleur pour l'enregistrement des parametres et pour le fichier
    .NM-DisciplinesConfig : les deux doivent produire le meme document, sans
    quoi un aller-retour par fichier perdrait une cle en chemin.

    `fmt` est le tuple rendu par _disc_format(), `txt` le lecteur de cellule.
    """
    _nb, _nc, _dig, _ld, _lo, _sep, _maj = fmt
    _table = []
    for _row in lignes:
        _code = txt(_row['code']).strip()
        if not _code:
            continue
        _table.append({
            'code':             _code,
            'code_ouvrage':     txt(_row['code_ouvrage']).strip(),
            'niveau':           _disc_entier(txt(_row['niveau']), 1),
            'discipline':       txt(_row['discipline']).strip(),
            'sous_discipline':  txt(_row['sous_discipline']).strip(),
            'abrev_discipline': txt(_row['abrev_discipline']).strip(),
            'abrev_resolue':    txt(_row['abrev_resolue']).strip(),
            'abrev_ouvrage':    txt(_row['abrev_ouvrage']).strip(),
            'abrev_ouvrage_resolue':
                txt(_row['abrev_ouvrage_resolue']).strip(),
        })
    return {
        'format': {
            'niveaux':                    _nb,
            'niveaux_code':               _nc,
            'digits_par_niveau':          _dig,
            'longueur_abrev_discipline':  _ld,
            'longueur_abrev_ouvrage':     _lo,
            'separateur':                 _sep,
            'majuscules':                 bool(_maj),
        },
        'table': _table,
    }


def _disc_cfg_enregistrer(parent, section):
    """
    Ecrit `section` — le dict {format, table} tel qu'il part dans config.json —
    dans un fichier .NM-DisciplinesConfig. Retourne le chemin, ou None.
    """
    from dialogs.dialogs_styles_loader import show_alert
    import System.Windows.Forms as _WinForms

    _dlg = _WinForms.SaveFileDialog()
    _dlg.Title = u"Exporter la configuration des disciplines"
    _dlg.Filter = _DISC_CFG_FILTRE
    _dlg.DefaultExt = _DISC_CFG_EXT
    _dlg.FileName = _DISC_CFG_DEFAUT
    if _dlg.ShowDialog() != _WinForms.DialogResult.OK:
        return None

    _chemin = _dlg.FileName
    if not _chemin.lower().endswith(u'.' + _DISC_CFG_EXT.lower()):
        # Le dialogue n'impose pas l'extension si l'utilisateur la retire.
        _chemin += u'.' + _DISC_CFG_EXT
    try:
        with codecs.open(_chemin, 'w', 'utf-8') as _f:
            json.dump(section, _f, indent=2, ensure_ascii=False)
    except Exception as _exc:
        show_alert(u"Exporter la configuration", u"{}".format(_exc),
                   close_label=u"Retour")
        return None

    show_alert(
        u"Exporter la configuration",
        u"{} ligne(s) et la structure de la table écrites dans :\n\n{}".format(
            len(section.get('table') or []), _chemin),
        close_label=u"Fermer")
    return _chemin


def _disc_cfg_charger(parent):
    """
    Lit un .NM-DisciplinesConfig et rend (format interne, entrees), ou None.

    Le `format` du fichier passe par _disc_format_stocke : un fichier ecrit par
    une version anterieure se relit donc exactement comme le ferait config.json.
    """
    from dialogs.dialogs_styles_loader import show_alert
    import System.Windows.Forms as _WinForms

    _dlg = _WinForms.OpenFileDialog()
    _dlg.Title = u"Importer une configuration de disciplines"
    _dlg.Filter = _DISC_CFG_FILTRE
    _dlg.DefaultExt = _DISC_CFG_EXT
    if _dlg.ShowDialog() != _WinForms.DialogResult.OK:
        return None
    if not _dlg.FileName.lower().endswith(u'.' + _DISC_CFG_EXT.lower()):
        show_alert(
            u"Format incorrect",
            u"Fichier non valide.\n\nSeuls les fichiers "
            u"« .{} » sont acceptés.".format(_DISC_CFG_EXT),
            close_label=u"Retour")
        return None

    try:
        with codecs.open(_dlg.FileName, 'r', 'utf-8') as _f:
            _data = json.load(_f)
    except Exception as _exc:
        show_alert(u"Importer une configuration",
                   u"Erreur de lecture :\n\n{}".format(_exc),
                   close_label=u"Retour")
        return None

    _table = _data.get('table') if isinstance(_data, dict) else None
    if not isinstance(_table, list):
        show_alert(
            u"Importer une configuration",
            u"Ce fichier ne contient pas de table de disciplines.\n\n"
            u"Attendu un fichier produit par « Exporter la configuration… ».",
            close_label=u"Retour")
        return None

    _nb, _nc, _dig, _ld, _lo = _disc_format_stocke(_data.get('format'))
    _fmt = {
        'niveaux':      _nb,
        'niveaux_code': _nc,
        'digits':       _dig,
        'long_disc':    _ld,
        'long_ouv':     _lo,
        'separateur':   (_data.get('format') or {}).get('separateur', u'-')
                        or u'',
        'majuscules':   bool((_data.get('format') or {})
                             .get('majuscules', True)),
    }
    return _fmt, [_e for _e in _table if isinstance(_e, dict)]


# ---------------------------------------------------------------------------
# Vues personnalisees : fichier de configuration
# ---------------------------------------------------------------------------
# Meme principe que le .NM-DisciplinesConfig ci-dessus : extension DEDIEE, et
# le fichier porte TOUT ce qui fait une vue personnalisee.
#
# « Tout », ici, ce n'est pas seulement la table affichee : chacune de ses
# colonnes « Configurer… » ecrit dans une table SATELLITE de config.json,
# indexee par le meme label. N'exporter que la grille rendrait un fichier qui
# perd, au retour, les familles de vues, les disciplines, les types et
# gabarits Revit, les types de niveaux par defaut et la disponibilite par
# outil — soit l'essentiel du reglage. Les sept tables voyagent donc
# ensemble, exactement comme le format accompagne la table des disciplines.
_TVP_CFG_EXT = u'NM-VuesPersConfig'
_TVP_CFG_FILTRE = (u'Configuration Vues personnalisées (*.{0})|*.{0}'
                   .format(_TVP_CFG_EXT))
_TVP_CFG_DEFAUT = u'vues_personnalisees.' + _TVP_CFG_EXT

# Cles du fichier = cles de config.json, a l'identique : un aller-retour ne
# doit rien renommer en chemin.
_TVP_CFG_TABLES = (
    'types_vues_personnalises',
    'types_vues',
    'gabarits_vues',
    'dispo_types_pers_familles',
    'dispo_types_pers_disciplines',
    'dispo_types_pers_lier_cao',
    'niveaux_defaut_types_pers',
)


# Libelles des lignes SYSTEME. Constante de MODULE : ils servent de CONTRAT
# entre cette fenetre et les outils qui les designent — « Vues + », « Lier
# CAO » et « Pieces 3D » les reconnaissent en comparant ces chaines exactes.
_TVP_LABELS_SYSTEME = (u'PIECES 3D', u'TEMPORAIRE', u'FM')

# Tout ce qui se DERIVE de cette constante, au niveau module lui aussi. Ce sont
# des constantes : elles ne dependent ni de config.json ni de la fenetre. Les
# calculer dans main() les faisait capturer par une dizaine de fonctions
# imbriquees, donc occuper cinq places dans le tuple de scope IronPython — voir
# la note de _tvp_lignes.
#
# "PIECES 3D" est la ligne reservee au bouton 05_Pieces > Pieces 3D : elle est
# la seule a pouvoir porter la case "Pieces 3D" de la colonne "Disponibilite".
_TVP_LABEL_PIECES_3D = u'PIECES 3D'
# Lignes SYSTEME : toujours presentes, toujours en tete, dans cet ordre
# (Ord. = index, donc "PIECES 3D" = 0). Leur label, leur ordre et leur usage ne
# sont pas editables et elles ne peuvent pas etre supprimees.
_TVP_LOCKED_ORDER = list(_TVP_LABELS_SYSTEME)
_TVP_LOCKED_ORDRE = dict((_l, _i) for _i, _l in enumerate(_TVP_LOCKED_ORDER))
# Labels non supprimables / non renommables.
_LOCKED_TVP_LABELS = set(_TVP_LOCKED_ORDER)
# Usage des lignes systeme : impose par le code, pas par config.json. La colonne
# Usage y est verrouillee, une valeur venue du fichier ne pourrait plus etre
# corrigee dans l'interface. La CLE est le Label (en majuscules), la VALEUR est
# l'usage — un des deux choix de la liste deroulante, qui garde sa casse.
_TVP_LOCKED_USAGE = {
    _TVP_LABEL_PIECES_3D: u'Livrable',
    u'TEMPORAIRE':        u'Temporaire',
    u'FM':                u'Livrable',
}


def _tvp_maj_label(val):
    """
    « Label » en majuscules.

    Les libelles systeme sont eux-memes en majuscules : la clause
    d'exemption ne sert donc plus qu'a un libelle systeme qui en
    contiendrait un jour d'autres caracteres. Elle est gardee comme garde-fou
    — ces libelles sont un CONTRAT, compare tel quel par « Vues + », « Lier
    CAO » et « Pieces 3D ».

    MIGRATION : « Temporaire » n'etant plus exempte, une configuration
    anterieure le voit passer en « TEMPORAIRE » a la lecture. Comme
    _tvp_normaliser_cfg applique la meme regle aux SEPT tables d'un coup, la
    ligne et ses index restent alignes — rien a reparer a la main.
    """
    _t = val if isinstance(val, unicode) else unicode(val or u'')
    return _t if _t in _TVP_LABELS_SYSTEME else _t.upper()


def _tvp_maj_titre(val):
    """« Titre » en majuscules, sans exception : c'est du texte libre."""
    return (val if isinstance(val, unicode) else unicode(val or u'')).upper()


def _tvp_normaliser_cfg(cfg):
    """
    Passe les Label en majuscules dans les SEPT tables d'un coup, avant que
    quoi que ce soit ne les lise.

    En un seul endroit et non a chaque chargement : les six tables satellites
    sont INDEXEES par ce label. Le changer dans la grille sans le changer
    dans les index romprait le lien, et les familles de vues, disciplines,
    types, gabarits et disponibilites d'une ligne deviendraient
    silencieusement introuvables.
    """
    for _cle in _TVP_CFG_TABLES:
        for _e in (cfg.get(_cle) or []):
            if isinstance(_e, dict) and _e.get(u'label') is not None:
                _e[u'label'] = _tvp_maj_label(_e[u'label'])
    for _e in (cfg.get(u'types_vues_personnalises') or []):
        if isinstance(_e, dict) and _e.get(u'titre') is not None:
            _e[u'titre'] = _tvp_maj_titre(_e[u'titre'])


def _tvp_cle_ordre(val):
    """
    Cle de tri naturelle de la colonne « Ord. ». Delegue au module partage :
    les trois scripts qui trient cette table doivent le faire pareil.
    """
    from utils.types_vues_personnalises import cle_ordre as _cle
    return _cle(val)


# Label de facade du dialogue qui regle les valeurs par defaut des types de
# vues. Il ne designe AUCUNE ligne de la table : c'est une cle de dict local,
# jamais enregistree. Au niveau module et non dans main() — voir la note sur le
# tuple de scope dans _tvp_lignes.
_TVP_CLE_DEFAUT = u'< Valeurs par défaut >'


# ---------------------------------------------------------------------------
# Table « Vues personnalisees » : acces hors interface
# ---------------------------------------------------------------------------
# Fonctions de MODULE prenant la DataTable en parametre, et non des fonctions
# imbriquees dans main(). Motif IronPython, pas esthetique : chaque nom local
# de main() capture par une fonction imbriquee occupe une place dans le tuple
# de scope, et le depassement se manifeste par un « SystemError: Sequence
# contains no elements » pointant une ligne sans rapport, a l'ouverture de la
# fenetre. Meme remede que _init_disciplines et _init_tvp_recherche.


def _tvp_lignes(dt):
    """
    TOUTES les lignes de la table, y compris celles que la recherche ou un
    filtre d'en-tete masque, triees comme la grille.

    Jamais `dg.ItemsSource` pour enregistrer, compter ou controler : la vue est
    filtree, et tout ce qu'elle ne montre pas serait purement et simplement
    absent du fichier ecrit — chercher « FM » puis enregistrer supprimait
    toutes les autres vues personnalisees et leurs six tables satellites.
    Meme regle que _disc_api['lignes']() cote Disciplines.

    Les lignes supprimees sont ecartees ici : leurs cellules ne sont plus
    lisibles (DeletedRowInaccessibleException) tant que la table n'a pas
    accepte les changements.
    """
    from System.Data import DataRowState as _RowState
    return sorted(
        [_r for _r in dt.Rows if _r.RowState != _RowState.Deleted],
        key=lambda _r: _tvp_cle_ordre(_r['ordre']))


def _tvp_montrer_ligne(grille, dt, reset_filtres, data_row):
    """
    Amene `data_row` (une DataRow) sous les yeux dans `grille`.

    Une ligne masquee par un filtre n'a PAS de DataRowView dans la vue : on la
    cherche donc une premiere fois, et les filtres ne sont leves que si elle
    est introuvable — sans quoi l'utilisateur serait renvoye vers une ligne
    qu'il ne peut pas voir.
    """
    def _poser():
        for _rv in dt.DefaultView:
            if _rv.Row is data_row:
                grille.SelectedItem = _rv
                try:
                    grille.ScrollIntoView(_rv)
                except Exception:
                    pass
                return True
        return False

    if not _poser():
        reset_filtres()
        _poser()


def _tvp_init_ligne_neuve(label, types_store, types_defaut,
                          disc_store, items_disc):
    """
    Pose les reglages d'une vue personnalisee creee DE ZERO (« + Ajouter »), au
    moment ou son Label est saisi — avant, elle n'a pas de cle sous laquelle
    etre rangee.

    Deux reglages seulement, les autres gardent leur defaut implicite :

    - « Types de vues » herite du referentiel des valeurs par defaut ;
    - « Discipline » part VIDE, aucune case cochee. La convention des tables
      satellites est « absent = tout actif » ; pour obtenir l'inverse il faut
      donc ecrire explicitement chaque code a False, un dict vide serait relu
      comme « tout actif ».

    CONSEQUENCE ASSUMEE : tant qu'aucune discipline n'est cochee, la vue n'est
    proposee dans « Vues + » et « Lier CAO » pour aucune discipline. C'est le
    comportement demande — a l'oppose d'une ligne dupliquee, qui garde les
    disciplines de sa source.
    """
    if types_defaut[0] and label not in types_store:
        types_store[label] = dict(types_defaut[0])
    if label not in disc_store:
        _codes = [_code for _code, _lib in items_disc()]
        # Rien a decocher s'il n'y a pas de referentiel : laisser la cle absente
        # plutot que d'ecrire un dict vide, qui vaudrait « tout actif » et
        # donnerait donc l'inverse de ce qu'on cherche.
        if _codes:
            disc_store[label] = dict((_code, False) for _code in _codes)


def _tvp_renommer_stores(row, dt, stores, init_ligne_neuve):
    """
    Reporte le nouveau Label de `row` dans les tables satellites, et initialise
    une ligne creee de zero.

    Les tables de reglages s'indexent sur le Label, qui est EDITABLE. Sans ce
    report, renommer une ligne — le geste normal apres « Dupliquer » — laissait
    ses reglages sous l'ancienne cle : ils devenaient introuvables et la ligne
    repartait sur les valeurs par defaut de chaque table, ce qui se lit
    exactement comme une reinitialisation.

    row              : DataRowView de la ligne dont l'edition vient d'etre
                       validee. La comparaison se fait avec la colonne
                       `label_prec`, seule memoire de son nom d'avant.
    stores           : les dicts {label: reglages} a suivre.
    init_ligne_neuve : fonction (label) appelee pour une ligne creee de zero
                       — voir _tvp_init_ligne_neuve.
    """
    _ancien  = unicode(row['label_prec'] or u'')
    _nouveau = unicode(row['label'] or u'')
    if _ancien == _nouveau:
        return
    row['label_prec'] = _nouveau
    if not _nouveau:
        # Label efface : les reglages restent sous l'ancienne cle. Ils sont
        # ignores a l'enregistrement (une ligne sans label ne part pas), et
        # retrouves tels quels si le label est ressaisi.
        return
    if not _ancien:
        # Ligne creee par « + Ajouter ». Une duplication, elle, arrive ici avec
        # son label deja pose et n'y passe jamais : elle garde la copie faite
        # par _tvp_dupliquer.
        init_ligne_neuve(_nouveau)
        return
    # Le nouveau label est deja porte par une AUTRE ligne : ne rien deplacer,
    # sans quoi le renommage ecraserait les reglages de cette ligne-la. La
    # collision est deja visible dans la table, on ne la double pas d'une
    # perte silencieuse.
    for _autre in _tvp_lignes(dt):
        if _autre is not row.Row and unicode(_autre['label'] or u'') == _nouveau:
            return
    for _store in stores:
        if _ancien in _store:
            _store[_nouveau] = _store.pop(_ancien)


# ---------------------------------------------------------------------------
# Fichier d'echange .NM-VuesPersConfig : une forme GROUPEE PAR VUE
# ---------------------------------------------------------------------------
# config.json range les vues personnalisees en SEPT tables paralleles, chacune
# indexee par label. C'est pratique pour les scripts qui n'en lisent qu'une, et
# illisible pour un humain : les reglages d'une meme vue sont eparpilles dans
# sept blocs eloignes, et il faut suivre le label a la main pour les rassembler.
#
# Le fichier d'ECHANGE, lui, se lit dans le Bloc-notes : un bloc par vue, avec
# TOUS ses reglages dedans. La conversion se fait aux deux extremites (export /
# import), config.json et l'interface ne changent pas de forme.
#
# La version est ECRITE dans le fichier pour que la relecture sache a quoi elle
# a affaire ; les fichiers deja exportes au format « sept tables » restent
# acceptes a l'import, sans quoi ceux qui en ont deja seraient bloques.
_TVP_FIC_VERSION = 2


def _tvp_vers_fichier(section):
    """Les sept tables -> la forme groupee par vue, prete a ecrire."""
    from collections import OrderedDict as _OD

    def _index(cle_table, cle_valeurs):
        return dict((_e.get(u'label', u''), _e.get(cle_valeurs) or {})
                    for _e in (section.get(cle_table) or [])
                    if isinstance(_e, dict))

    _fam   = _index('dispo_types_pers_familles',    'familles')
    _disc  = _index('dispo_types_pers_disciplines', 'disciplines')
    _typ   = _index('types_vues',                   'types')
    _gab   = _index('gabarits_vues',                'gabarits')
    _niv   = _index('niveaux_defaut_types_pers',    'niveaux')
    _dispo = dict((_e.get(u'label', u''), _e)
                  for _e in (section.get('dispo_types_pers_lier_cao') or [])
                  if isinstance(_e, dict))

    def _trie(d):
        """Sous-dicts tries : sans cela leur ordre change a chaque export et
        deux fichiers identiques se comparent mal."""
        return _OD(sorted((d or {}).items()))

    _vues = []
    for _e in (section.get('types_vues_personnalises') or []):
        if not isinstance(_e, dict):
            continue
        _lbl = _e.get(u'label', u'')
        if not _lbl:
            continue
        _d = _dispo.get(_lbl, {})
        _bloc = _OD()
        # Identite d'abord, reglages ensuite : c'est l'ordre dans lequel on lit
        # un bloc pour savoir de quelle vue il parle.
        _bloc[u'ordre']    = _e.get(u'ordre', u'')
        _bloc[u'label']    = _lbl
        _bloc[u'titre']    = _e.get(u'titre', u'')
        _bloc[u'valeur_1'] = _e.get(u'valeur_1', u'')
        _bloc[u'valeur_2'] = _e.get(u'valeur_2', u'')
        _bloc[u'usage']    = _e.get(u'usage', u'Temporaire')
        _bloc[u'systeme']  = bool(_e.get(u'systeme', False))
        _bloc[u'disponibilite'] = _OD([
            (u'lier_cao',  bool(_d.get(u'lier_cao', True))),
            (u'vues_plus', bool(_d.get(u'vues_plus', True))),
            (u'pieces_3d', bool(_d.get(u'pieces_3d', False))),
        ])
        _bloc[u'familles_de_vues']         = _trie(_fam.get(_lbl))
        _bloc[u'disciplines']              = _trie(_disc.get(_lbl))
        _bloc[u'types_de_vues']            = _trie(_typ.get(_lbl))
        _bloc[u'gabarits_de_vues']         = _trie(_gab.get(_lbl))
        _bloc[u'types_niveaux_par_defaut'] = _trie(_niv.get(_lbl))
        _vues.append(_bloc)

    _out = _OD()
    # Tiret simple et non cadratin : ce fichier se lit dans le Bloc-notes, on
    # n'y met aucun caractere plus exotique que les accents deja presents dans
    # les libelles.
    _out[u'format']  = u'NM-BATII - vues personnalisées'
    _out[u'version'] = _TVP_FIC_VERSION
    _out[u'types_vues_defaut'] = _trie(section.get('types_vues_defaut'))
    _out[u'vues_personnalisees'] = _vues
    return _out


def _tvp_depuis_fichier(data):
    """
    L'inverse : la forme du fichier -> les sept tables attendues par
    _tvp_charger_config. Rend None si `data` n'est ni l'une ni l'autre forme.

    Les fichiers au format « sept tables » (avant v2) restent acceptes tels
    quels : ils sont deja dans la forme de sortie.
    """
    if not isinstance(data, dict):
        return None

    _vues = data.get(u'vues_personnalisees')
    if not isinstance(_vues, list):
        # Ancien format, ou fichier etranger.
        if not isinstance(data.get('types_vues_personnalises'), list):
            return None
        _out = {}
        for _cle in _TVP_CFG_TABLES:
            _val = data.get(_cle)
            _out[_cle] = [_e for _e in _val if isinstance(_e, dict)] \
                if isinstance(_val, list) else []
        _def = data.get('types_vues_defaut')
        _out['types_vues_defaut'] = dict(_def) if isinstance(_def, dict) else {}
        return _out

    def _sd(bloc, cle):
        """Sous-dict d'un bloc, tolerant a l'absence et au mauvais type : un
        fichier edite a la main ne doit pas faire echouer tout l'import."""
        _v = bloc.get(cle)
        return dict(_v) if isinstance(_v, dict) else {}

    _tvp, _fam, _disc, _typ, _gab, _niv, _dsp = [], [], [], [], [], [], []
    for _b in _vues:
        if not isinstance(_b, dict):
            continue
        _lbl = _b.get(u'label', u'')
        if not _lbl:
            continue
        _tvp.append({
            u'ordre':    _b.get(u'ordre', u''),
            u'label':    _lbl,
            u'titre':    _b.get(u'titre', u''),
            u'valeur_1': _b.get(u'valeur_1', u''),
            u'valeur_2': _b.get(u'valeur_2', u''),
            u'usage':    _b.get(u'usage', u'Temporaire'),
            u'systeme':  bool(_b.get(u'systeme', False)),
        })
        _d = _sd(_b, u'disponibilite')
        _dsp.append({u'label':     _lbl,
                     u'lier_cao':  bool(_d.get(u'lier_cao', True)),
                     u'vues_plus': bool(_d.get(u'vues_plus', True)),
                     u'pieces_3d': bool(_d.get(u'pieces_3d', False))})
        _fam.append({u'label': _lbl, u'familles':    _sd(_b, u'familles_de_vues')})
        _disc.append({u'label': _lbl, u'disciplines': _sd(_b, u'disciplines')})
        _typ.append({u'label': _lbl, u'types':       _sd(_b, u'types_de_vues')})
        _gab.append({u'label': _lbl, u'gabarits':    _sd(_b, u'gabarits_de_vues')})
        _niv.append({u'label': _lbl,
                     u'niveaux': _sd(_b, u'types_niveaux_par_defaut')})

    _def = data.get('types_vues_defaut')
    return {
        'types_vues_personnalises':     _tvp,
        'types_vues':                   _typ,
        'gabarits_vues':                _gab,
        'dispo_types_pers_familles':    _fam,
        'dispo_types_pers_disciplines': _disc,
        'dispo_types_pers_lier_cao':    _dsp,
        'niveaux_defaut_types_pers':    _niv,
        'types_vues_defaut': dict(_def) if isinstance(_def, dict) else {},
    }


def _ecrire_json_bloc_notes(chemin, data):
    """
    Ecrit du JSON destine a etre OUVERT DANS LE BLOC-NOTES : fins de ligne
    CRLF et BOM UTF-8.

    Les deux sont necessaires sur un poste ancien (Bloc-notes d'avant
    Windows 10 1809, encore courant sur les postes d'agence) : sans CRLF le
    fichier s'affiche sur UNE SEULE ligne, sans BOM les accents sortent en
    mojibake. Les editeurs modernes s'accommodent des deux sans rien montrer.

    La relecture doit se faire en 'utf-8-sig' — 'utf-8' laisserait le BOM en
    tete de chaine et json.load echouerait dessus.

    DEUX PASSES, et non un json.dumps suivi d'un replace : sous IronPython,
    `json.dumps(..., ensure_ascii=False)` rend une `str` dont l'encodage n'est
    pas garanti, et la decoder en UTF-8 leve « Impossible de traduire les
    octets » des qu'une valeur porte un tiret cadratin ou une apostrophe
    typographique. On laisse donc json ecrire par le writer codecs, qui sait
    encoder, puis on convertit les fins de ligne SUR LES OCTETS — sans jamais
    decoder quoi que ce soit. Le BOM, en tete, n'est pas touche par le
    remplacement.
    """
    with codecs.open(chemin, 'w', 'utf-8-sig') as _f:
        json.dump(data, _f, indent=2, ensure_ascii=False)
    with open(chemin, 'rb') as _f:
        _octets = _f.read()
    # Normalise d'abord : sans cela un CRLF deja present serait double.
    _octets = _octets.replace('\r\n', '\n').replace('\n', '\r\n')
    with open(chemin, 'wb') as _f:
        _f.write(_octets)


def _tvp_cfg_enregistrer(parent, section):
    """
    Ecrit `section` — les sept tables telles qu'elles partent dans
    config.json — dans un .NM-VuesPersConfig, sous la forme GROUPEE PAR VUE
    (voir _tvp_vers_fichier). Retourne le chemin, ou None.
    """
    from dialogs.dialogs_styles_loader import show_alert
    import System.Windows.Forms as _WinForms

    _dlg = _WinForms.SaveFileDialog()
    _dlg.Title = u"Exporter la configuration des vues personnalisées"
    _dlg.Filter = _TVP_CFG_FILTRE
    _dlg.DefaultExt = _TVP_CFG_EXT
    _dlg.FileName = _TVP_CFG_DEFAUT
    if _dlg.ShowDialog() != _WinForms.DialogResult.OK:
        return None

    _chemin = _dlg.FileName
    if not _chemin.lower().endswith(u'.' + _TVP_CFG_EXT.lower()):
        # Le dialogue n'impose pas l'extension si l'utilisateur la retire.
        _chemin += u'.' + _TVP_CFG_EXT
    try:
        # PAS de sort_keys, contrairement a config.json : l'ordre des cles
        # porte ici du sens (l'identite de la vue, puis ses reglages) et il est
        # deja fixe par les OrderedDict de _tvp_vers_fichier.
        _ecrire_json_bloc_notes(_chemin, _tvp_vers_fichier(section))
    except Exception as _exc:
        show_alert(u"Exporter la configuration", u"{}".format(_exc),
                   close_label=u"Retour")
        return None

    show_alert(
        u"Exporter la configuration",
        u"{} vue(s) personnalisée(s) et leurs réglages écrits dans :"
        u"\n\n{}".format(
            len(section.get('types_vues_personnalises') or []), _chemin),
        close_label=u"Fermer")
    return _chemin


def _tvp_cfg_charger(parent):
    """
    Lit un .NM-VuesPersConfig et rend le dict des sept tables, ou None.

    Une table absente du fichier est rendue vide plutot qu'omise : l'import
    remplace, il ne fusionne pas — laisser survivre l'ancienne valeur d'une
    table manquante melangerait deux configurations.
    """
    from dialogs.dialogs_styles_loader import show_alert
    import System.Windows.Forms as _WinForms

    _dlg = _WinForms.OpenFileDialog()
    _dlg.Title = u"Importer une configuration de vues personnalisées"
    _dlg.Filter = _TVP_CFG_FILTRE
    _dlg.DefaultExt = _TVP_CFG_EXT
    if _dlg.ShowDialog() != _WinForms.DialogResult.OK:
        return None
    if not _dlg.FileName.lower().endswith(u'.' + _TVP_CFG_EXT.lower()):
        show_alert(
            u"Format incorrect",
            u"Fichier non valide.\n\nSeuls les fichiers "
            u"« .{} » sont acceptés.".format(_TVP_CFG_EXT),
            close_label=u"Retour")
        return None

    try:
        # 'utf-8-sig' et non 'utf-8' : l'export pose un BOM (voir
        # _ecrire_json_bloc_notes), qui resterait sinon en tete de la chaine et
        # ferait echouer json.load. Cet encodage lit aussi les fichiers SANS
        # BOM — les exports anterieurs continuent donc de se relire.
        with codecs.open(_dlg.FileName, 'r', 'utf-8-sig') as _f:
            _data = json.load(_f)
    except Exception as _exc:
        show_alert(u"Importer une configuration",
                   u"Erreur de lecture :\n\n{}".format(_exc),
                   close_label=u"Retour")
        return None

    # Accepte la forme groupee par vue (celle qu'ecrit l'export) ET l'ancienne
    # forme a sept tables separees — voir _tvp_depuis_fichier.
    _out = _tvp_depuis_fichier(_data)
    if _out is None:
        show_alert(
            u"Importer une configuration",
            u"Ce fichier ne contient pas de vues personnalisées.\n\n"
            u"Attendu un fichier produit par « Exporter la configuration… ».",
            close_label=u"Retour")
        return None
    return _out


# ---------------------------------------------------------------------------
# Disciplines : echange Excel
# ---------------------------------------------------------------------------
# Fonctions de MODULE, comme le reste du referentiel : voir la docstring de
# _init_disciplines. Elles s'appuient sur utils/surfaces_xlsx, deja utilise par
# les outils de surfaces — xlsxwriter et xlrd sont livres avec pyRevit, il n'y
# a ni Excel ni COM a prevoir sur le poste.

# Le fichier ne porte QUE les colonnes saisissables : c'est un support de
# travail, pas une photographie de la table. Y ajouter le Code Discipline, le
# niveau ou le Resultat donnerait des colonnes qu'on peut modifier sans effet
# — elles se recalculent a l'import — et qui deviendraient fausses des la
# premiere ligne ajoutee dans Excel.
# Libelle ECRIT en premier, puis les variantes ACCEPTEES a la relecture : forme
# courte des en-tetes de la table, et noms des versions precedentes, pour qu'un
# fichier deja exporte continue de se relire.
_DISC_XLSX_COLONNES = (
    (u'Code Ouv.',         (u'Code Ouvrage', u'Code BIM'), 'code_ouvrage'),
    (u'Discipline',        (),                        'discipline'),
    (u'Sous-discipline / Ouvrage', (u'Sous-discipline',), 'sous_discipline'),
    (u'Abrév. Discipline', (u'Abrev. Discipline', u'Acronyme'),
                                                      'abrev_discipline'),
    (u'Abrév. Ouvrage',    (u'Abréviation',),         'abrev_ouvrage'),
)

# Colonnes CALCULEES de l'export : elles ne se saisissent pas, une FORMULE les
# derive du Code Ouvrage. C'est ce qui leve l'objection qui les avait d'abord
# ecartees du fichier — une valeur figee devenait fausse des la premiere ligne
# ajoutee dans Excel, une formule suit. Elles restent ignorees a l'import : le
# referentiel les recalcule lui-meme, la formule n'est la que pour le travail
# dans le tableur.
_DISC_XLSX_CALCULEES = (u'Code Dis.', u'Niv.')


def _disc_xlsx_formule_code(nb_car_code):
    """
    Code Discipline : la troncature du Code Ouvrage aux `nb_car_code`
    premiers caracteres (meme regle que _disc_recalculer).
    """
    return (u'=IF([@[Code Ouv.]]="","",'
            u'LEFT([@[Code Ouv.]],{}))'.format(nb_car_code))


def _disc_xlsx_formule_niveau(digits):
    """
    Niveau : rang de la DERNIERE tranche non nulle, 1 au minimum — meme regle
    que _disc_niveau_de.

    Des IF imbriques du niveau le plus profond au plus haut : le premier qui
    trouve une tranche non nulle gagne, le repli est le niveau 1 (un code tout
    a zero est un niveau 1, comme « 000000 » pour COMMUN).

    Le code est COMPLETE par des zeros avant decoupage. Sans cela une saisie
    trop courte donnerait des tranches vides, que Excel jugerait differentes
    de « 0 » et qui feraient repondre le niveau le plus profond — l'inverse du
    resultat attendu.
    """
    _total = sum(digits)
    _plein = u'([@[Code Ouv.]]&REPT("0",{}))'.format(_total)
    _formule = u'1'
    _debut = 1
    _bornes = []
    for _d in digits:
        _bornes.append((_debut, _d))
        _debut += _d
    # L'imbrication se construit de l'INTERIEUR : on part du repli (niveau 1)
    # et on enveloppe par rangs CROISSANTS, si bien que le dernier enveloppe —
    # le niveau le plus profond — se retrouve en TETE. Le premier IF evalue est
    # donc le plus profond, et il gagne des qu'il trouve une tranche non nulle.
    # Enrouler dans l'autre sens mettrait le niveau 2 en tete : « 511100 »
    # repondrait 2 au lieu de 4, sa tranche 2 etant non nulle elle aussi.
    for _rang in range(2, len(digits) + 1):
        _pos, _larg = _bornes[_rang - 1]
        _formule = u'IF(MID({},{},{})<>"{}",{},{})'.format(
            _plein, _pos, _larg, u'0' * _larg, _rang, _formule)
    return u'=IF([@[Code Ouv.]]="","",{})'.format(_formule)
_DISC_XLSX_FEUILLE = u"Disciplines"


def _disc_exporter_xlsx(parent, lignes, lecteur, fmt):
    """
    Ecrit le referentiel dans un .xlsx. Retourne le chemin, ou None si annule.

    `lignes` est la table COMPLETE, pas la vue filtree : un export partiel
    reimporte ecraserait le reste sans prevenir.

    `fmt` est le tuple rendu par _disc_format() : le decoupage du code y
    determine les formules de « Code Dis. » et « Niv. », et le nombre de
    niveaux le nombre de teintes a poser.
    """
    from dialogs.dialogs_styles_loader import show_alert
    import utils.surfaces_xlsx as _mod_xlsx
    reload(_mod_xlsx)

    _chemin = forms.save_file(file_ext='xlsx',
                              default_name=u'NM-BATII_Disciplines')
    if not _chemin:
        return None
    if not _chemin.lower().endswith('.xlsx'):
        # save_file ne reimpose pas l'extension si l'utilisateur la retire.
        _chemin += '.xlsx'

    _nb, _nc, _digits, _ld, _lo, _sep, _maj = fmt
    _lg_code = sum(_digits[:_nc])

    # Ordre d'affichage de la table : le code d'abord, ses deux derives
    # ensuite, puis les libelles et les abreviations.
    _saisies = dict((_cle, (_lib, _alias))
                    for _lib, _alias, _cle in _DISC_XLSX_COLONNES)
    _colonnes = [
        {'entete': _saisies['code_ouvrage'][0], 'cle': 'code_ouvrage',
         'largeur': 14},
        {'entete': u'Code Dis.', 'cle': None, 'largeur': 12,
         'formule': _disc_xlsx_formule_code(_lg_code)},
        {'entete': u'Niv.', 'cle': None, 'largeur': 7,
         'formule': _disc_xlsx_formule_niveau(_digits)},
        {'entete': _saisies['discipline'][0], 'cle': 'discipline',
         'largeur': 26},
        {'entete': _saisies['sous_discipline'][0], 'cle': 'sous_discipline',
         'largeur': 30},
        {'entete': _saisies['abrev_discipline'][0], 'cle': 'abrev_discipline',
         'largeur': 20},
        {'entete': _saisies['abrev_ouvrage'][0], 'cle': 'abrev_ouvrage',
         'largeur': 20},
    ]
    _donnees = [[(lecteur(_ligne, _c['cle']) if _c['cle'] else None)
                 for _c in _colonnes]
                for _ligne in lignes]

    # Meme charte que la table : bleu dans le Code, orange au-dela, et le
    # texte noir ou blanc selon le contraste. La regle porte sur « Niv. »,
    # colonne C — donc sur la valeur CALCULEE : une ligne ajoutee dans Excel
    # prend sa couleur toute seule.
    _regles = []
    for _niv in range(1, _nb + 1):
        _fond = _disc_couleur_niveau(_niv, _nc, _nb)
        _regles.append({
            'critere': u'=$C2={}'.format(_niv),
            'fond':    _fond,
            'texte':   _disc_texte_sur(_fond),
        })

    try:
        _mod_xlsx.ecrire_tableau(
            _chemin, _colonnes, _donnees,
            nom_feuille=_DISC_XLSX_FEUILLE,
            nom_tableau=u'Disciplines',
            regles=_regles)
    except Exception as _exc:
        show_alert(u"Exporter en .XLSX", u"{}".format(_exc), close_label=u"Retour")
        return None

    # Message AVANT l'ouverture : le tableur passe au premier plan et
    # masquerait une boite restee derriere lui.
    show_alert(
        u"Exporter en .XLSX",
        u"{} ligne(s) écrites dans :\n\n{}\n\n"
        u"Le fichier va s'ouvrir dans votre tableur, en tableau filtrable.\n\n"
        u"« Code Dis. » et « Niv. » sont des FORMULES calculées depuis le "
        u"Code Ouvrage, et la couleur de ligne suit le niveau : une ligne "
        u"ajoutée se complète et se colore d'elle-même. Ces deux colonnes "
        u"sont ignorées à l'import, où tout est recalculé — seules les autres "
        u"se saisissent.".format(len(_donnees), _chemin),
        close_label=u"Fermer")
    _disc_ouvrir_fichier(_chemin, parent)
    return _chemin


def _disc_ouvrir_fichier(chemin, parent=None):
    """
    Ouvre un fichier avec l'application par defaut du poste.

    UseShellExecute est pose EXPLICITEMENT : sous .NET 8 — celui de Revit 2025
    — il vaut False par defaut, et Process.Start refuse alors tout ce qui n'est
    pas un executable. Sans lui, l'export s'ecrirait bien mais ne s'ouvrirait
    jamais.

    Un echec d'ouverture ne remet pas l'export en cause : le fichier est ecrit,
    on le signale et on s'arrete la.
    """
    from System.Diagnostics import Process, ProcessStartInfo
    try:
        _psi = ProcessStartInfo(chemin)
        _psi.UseShellExecute = True
        Process.Start(_psi)
        return True
    except Exception as _exc:
        from dialogs.dialogs_styles_loader import show_alert
        show_alert(
            u"Ouverture du fichier",
            u"Le fichier est bien enregistré, mais n'a pas pu être "
            u"ouvert :\n\n{}\n\n{}".format(chemin, _exc),
            close_label=u"Fermer")
        return False


def _disc_importer_xlsx(parent):
    """
    Lit un .xlsx et retourne la liste d'entrees a charger, ou None.

    Le fichier ne porte que les colonnes saisissables ; le Code Discipline, le
    niveau et le Resultat sont recalcules depuis le format courant. Une
    ligne ajoutee dans Excel arrive donc complete, sans avoir a en deviner les
    colonnes derivees.
    """
    from dialogs.dialogs_styles_loader import show_alert
    import utils.surfaces_xlsx as _mod_xlsx
    reload(_mod_xlsx)

    _chemin = forms.pick_file(file_ext='xlsx')
    if not _chemin:
        return None

    try:
        _entetes, _lignes = _mod_xlsx.lire_tableur(_chemin)
    except Exception as _exc:
        show_alert(u"Importer un .XLSX", u"{}".format(_exc), close_label=u"Retour")
        return None

    # Rapprochement par NOM de colonne et non par position : l'utilisateur
    # reorganise ses colonnes dans Excel sans y penser. Le libelle courant est
    # essaye d'abord, puis ses variantes — formes courtes de la table, et noms
    # d'une version precedente.
    _index = {}
    _manquantes = []
    for _lib, _alias, _cle in _DISC_XLSX_COLONNES:
        _idx = None
        for _candidat in (_lib,) + tuple(_alias):
            _idx = _mod_xlsx.index_colonne(_entetes, _candidat)
            if _idx is not None:
                break
        if _idx is None:
            _manquantes.append(_lib)
        else:
            _index[_cle] = _idx
    if _manquantes:
        show_alert(
            u"Importer un .XLSX",
            u"Colonne(s) introuvable(s) dans le fichier :\n\n  • {}\n\n"
            u"Colonnes lues : {}\n\nAttendu un fichier produit par "
            u"« Exporter en .XLSX… », ou reprenant ses en-têtes.".format(
                u"\n  • ".join(_manquantes),
                u", ".join(_e for _e in _entetes if _e) or u"(aucune)"),
            close_label=u"Retour")
        return None

    def _texte(valeur):
        """Cellule en texte. Un code numerique revient en float chez xlrd :
        1.0 doit redevenir « 1 », pas « 1.0 »."""
        if valeur is None:
            return u''
        if isinstance(valeur, float):
            if valeur == int(valeur):
                return u'{}'.format(int(valeur))
            return u'{}'.format(valeur)
        return u'{}'.format(valeur).strip()

    _entrees = []
    for _ligne in _lignes:
        _e = {}
        for _cle, _idx in _index.items():
            _e[_cle] = _texte(_ligne[_idx]) if _idx < len(_ligne) else u''
        if not _e.get('code_ouvrage'):
            continue          # ligne sans code : rien a en tirer
        _entrees.append(_e)

    if not _entrees:
        show_alert(u"Importer un .XLSX",
                   u"Aucune ligne exploitable : la colonne « Code Ouvrage » "
                   u"est vide partout.", close_label=u"Retour")
        return None
    return _entrees


# ---------------------------------------------------------------------------
# Onglet Disciplines
# ---------------------------------------------------------------------------
def _init_disciplines(wpf, cfg):
    """
    Cable l'onglet « Disciplines » et rend les accesseurs dont
    l'enregistrement a besoin.

    Fonction de MODULE et non bloc de main(), volontairement : IronPython
    range les variables d'un scope portant des fermetures dans un
    MutableTuple, et au-dela d'un certain nombre il ne sait plus en
    construire le chemin d'acces. Le symptome n'a rien d'evocateur — un
    « SystemError: Sequence contains no elements » leve a la COMPILATION de
    la premiere fonction imbriquee de main(), donc sur une ligne sans aucun
    rapport avec la cause. main() etant deja tres fournie, tout bloc un peu
    consequent doit vivre dans son propre scope.
    """
    import clr as _clr_disc
    _clr_disc.AddReference('System.Data')
    from System.Data import DataTable as _DiscDataTable
    from System.Data import DataRowState as _DiscRowState
    from System import Action as _DiscAction
    from System.Windows import Visibility as _DiscVisibility
    from System.Windows import Thickness as _DiscThickness
    from System.Windows.Controls import DataGridCellInfo as _DiscCellInfo
    from System.Windows.Controls.Primitives import PlacementMode as _DiscPlacement
    from System.Windows.Input import Key as _DiscKey
    from System.Windows.Input import Keyboard as _DiscKeyboard
    from System.Windows.Input import ModifierKeys as _DiscModifierKeys
    from System.Windows.Media import Brush as _DiscBrush
    from System.Windows.Media import VisualTreeHelper as _DiscVTH
    from System.Windows.Threading import DispatcherPriority as _DiscPriority
    from dialogs.dialogs_styles_loader import show_alert as _disc_alert
    from dialogs.dialogs_styles_loader import show_confirm as _disc_confirm

    # AUCUN plafond de profondeur : ni ici, ni dans le dialogue, ni dans
    # utils/disciplines. Le decalage par niveau et les teintes sont calcules en
    # Python et poses dans la ligne, jamais declares palier par palier en XAML —
    # c'est cette decision-la qui rend la profondeur libre.
    _disc     = cfg.setdefault('disciplines', {})
    _disc_fmt = _disc.setdefault('format', {})

    def _disc_int(val, defaut):
        try:
            return int(str(val).strip())
        except Exception:
            return defaut

    _nb_i, _nc_i, _dig_i, _ld_i, _lo_i = _disc_format_stocke(_disc_fmt)

    def _disc_txt(val):
        """
        Cellule de grille en texte. Couvre System.DBNull (cellule jamais
        saisie), qui n'est pas None mais dont le ToString() est vide.
        """
        return str(val) if val is not None else u''

    # ── Etat du format ────────────────────────────────────────────────────────
    # Tenu en Python et non dans des controles : les champs de reglage vivent
    # dans une fenetre separee, qui n'existe que le temps de son ouverture,
    # alors que le recalcul et l'enregistrement ont besoin du format a tout
    # moment. La fenetre lit cet etat et le reecrit ; personne d'autre n'y
    # touche.
    _fmt = {
        'niveaux':      _nb_i,
        'niveaux_code': _nc_i,
        'digits':       list(_dig_i),
        'long_disc':    list(_ld_i),
        'long_ouv':     list(_lo_i),
        # Une valeur vide est un defaut legitime (abreviations collees).
        'separateur':   _disc_fmt.get('separateur', u'-') or u'',
        'majuscules':   bool(_disc_fmt.get('majuscules', True)),
    }

    def _disc_format():
        """
        Regles de format courantes, bornees pour rester calculables.
        Retourne (niveaux, niveaux_code, [digits], [long. abrev. discipline],
        [long. abrev. ouvrage], separateur, majuscules).
        """
        _digits = [max(1, min(_disc_int(_d, 1), 4)) for _d in _fmt['digits']]
        # Longueurs rendues en TEXTE canonique (« 0 », « 3 », « 2;5 ») : ce
        # sont des bornes, pas des nombres. Les consommateurs passent par
        # _disc_bornes_longueur pour les interpreter.
        _lg_d = [_disc_texte_longueur(_a, 3) for _a in _fmt['long_disc']]
        _lg_o = [_disc_texte_longueur(_a, 3) for _a in _fmt['long_ouv']]
        _nb = len(_digits)
        _nc = max(1, min(_disc_int(_fmt['niveaux_code'], _nb), _nb))
        return (_nb, _nc, _digits, _lg_d, _lg_o,
                _fmt['separateur'], bool(_fmt['majuscules']))

    # ── Lecture d'un Code Ouvrage ─────────────────────────────────────────────
    # Le CODE OUVRAGE est de LONGUEUR FIXE : la somme des tranches de tous les
    # niveaux declares. Avec 6 niveaux d'un chiffre, il fait 6 caracteres.
    # C'est lui qu'on saisit, et le CODE DISCIPLINE en est la troncature aux
    # niveaux de discipline — 3 caracteres pour 3 niveaux d'un chiffre.
    # Le niveau se lit au rang de la DERNIERE TRANCHE NON NULLE :
    #     500000 → 1     511000 → 3     511110 → 5
    #     510000 → 2     511100 → 4     511111 → 6
    # Une saisie plus courte est completee par des zeros : taper « 5111 » vaut
    # « 511100 », soit un niveau 4.

    def _disc_normaliser(code, digits):
        """Code complete par des zeros jusqu'a la longueur du Code Ouvrage."""
        if not code:
            return u''
        return code + u'0' * max(0, sum(digits) - len(code))

    def _disc_niveau_de(code, digits):
        """
        Niveau d'une ligne : rang de la DERNIERE tranche non nulle. Une ligne
        dont toutes les tranches sont a zero est un niveau 1 (le code 000000 de
        « COMMUN » en est un).
        """
        _niv, _i = 1, 0
        for _k, _d in enumerate(digits):
            if code[_i:_i + _d].strip(u'0'):
                _niv = _k + 1
            _i += _d
        return _niv

    def _disc_code_parent(code, digits):
        """
        Code Ouvrage du parent, ou None au niveau 1.

        Remet a zero la tranche du niveau courant, ce qui remonte d'un cran
        sans toucher au reste de la branche.
        """
        _niv = _disc_niveau_de(code, digits)
        if _niv <= 1:
            return None
        _out, _i = [], 0
        for _k, _d in enumerate(digits):
            _t = code[_i:_i + _d]
            _i += _d
            _out.append(_t if _k < _niv - 1 else u'0' * _d)
        return u''.join(_out)

    def _disc_prefixe(code, digits):
        """
        Partie SIGNIFIANTE du code : ce dont tout descendant doit heriter,
        c.-a-d. les tranches jusqu'au niveau de la ligne. Les zeros de queue ne
        distinguent rien.
        """
        return code[:sum(digits[:_disc_niveau_de(code, digits)])]

    # ── Table du referentiel ──────────────────────────────────────────────────
    _dt_disc = _DiscDataTable()
    _dt_disc.Columns.Add('code')
    _dt_disc.Columns.Add('code_ouvrage')
    _dt_disc.Columns.Add('niveau')
    _dt_disc.Columns.Add('discipline')
    _dt_disc.Columns.Add('sous_discipline')
    # DEUX chaines d'abreviation, chacune avec son gabarit saisi et son
    # resultat calcule, toutes deux sur TOUTES les lignes :
    #   • « Abrév. Discipline » dit de quelle discipline la ligne releve ;
    #   • « Abrév. Ouvrage » nomme l'ouvrage. Elle accepte en plus le jeton
    #     {dis}, qui vaut l'abreviation de discipline resolue de la meme
    #     ligne — et qui est sa valeur imposee au niveau 1.
    _dt_disc.Columns.Add('abrev_discipline')
    _dt_disc.Columns.Add('abrev_resolue')
    _dt_disc.Columns.Add('abrev_ouvrage')
    _dt_disc.Columns.Add('abrev_ouvrage_resolue')
    # Frontiere discipline / ouvrage, recalculee a chaque passage. Relue par
    # les scripts consommateurs via `niveau`, pas par un binding.
    _dt_disc.Columns.Add('est_ouvrage', bool)
    # Porte le filtre « Anomalies seules ». Une ligne fautive sans code n'est
    # atteignable par aucun autre moyen : ni recherche, ni tri.
    _dt_disc.Columns.Add('en_anomalie', bool)
    # Colonnes de travail, jamais affichees.
    # `visible` porte le RowFilter de la vue : filtrer par une expression
    # constante plutot que par un RowFilter construit a partir du texte saisi
    # evite d'avoir a echapper les quotes et les caracteres reserves de la
    # syntaxe d'expression ADO.NET.
    _dt_disc.Columns.Add('visible', bool)
    # `aspect` sert de temoin pour ne reecrire couleurs et marge que lorsque le
    # niveau ou la teinte change vraiment. Les pinceaux alimentent le RowStyle,
    # la marge le decalage de la colonne « Code Dis. » : calculer plutot que
    # declarer en XAML, c'est ce qui permet un nombre de niveaux illimite.
    _dt_disc.Columns.Add('aspect')
    _dt_disc.Columns.Add('brosse_fond', _DiscBrush)
    _dt_disc.Columns.Add('brosse_texte', _DiscBrush)
    _dt_disc.Columns.Add('marge', _DiscThickness)

    # Instantane de la DERNIERE suppression (une seule portee, pas un
    # historique) : les valeurs des lignes retirees, pas les DataRow
    # elles-memes (mortes des l'appel a .Delete()). Vide des qu'un
    # rechargement complet de la table le rendrait sans objet.
    _disc_dernier_supprime = []

    def _disc_charger_table(entrees):
        """Remplit la grille depuis une liste d'entrees de config.json."""
        del _disc_dernier_supprime[:]
        _dt_disc.Rows.Clear()
        for _d in (entrees or []):
            _rd = _dt_disc.NewRow()
            # Le Code Ouvrage porte tout ; le Code Discipline se recalcule. Un
            # import Excel n'apporte donc que le premier, et une config d'une
            # version anterieure qui n'aurait que `code` se rattrape par lui.
            _rd['code_ouvrage']    = (_d.get('code_ouvrage')
                                      or _d.get('code', u''))
            _rd['code']            = u''
            _rd['niveau']          = u''
            _rd['discipline']       = _d.get('discipline', u'')
            _rd['sous_discipline']  = _d.get('sous_discipline', u'')
            # `acronyme_propre` : nom de la colonne avant le passage au modele
            # {supN}. Une valeur litterale reste valide telle quelle — elle
            # remplace simplement l'heritage au lieu de le completer.
            _rd['abrev_discipline'] = (_d.get('abrev_discipline')
                                       or _d.get('acronyme_propre', u''))
            _rd['abrev_resolue']    = _d.get('abrev_resolue', u'')
            # `abreviation` : nom de la cle avant que l'abreviation d'ouvrage
            # ne devienne elle aussi un gabarit.
            _rd['abrev_ouvrage']    = (_d.get('abrev_ouvrage')
                                       or _d.get('abreviation', u''))
            _rd['abrev_ouvrage_resolue'] = _d.get('abrev_ouvrage_resolue', u'')
            _rd['est_ouvrage']      = False
            _rd['visible']          = True
            _rd['aspect']           = u''
            _dt_disc.Rows.Add(_rd)

    _disc_charger_table(_disc.get('table'))

    # Tri par CODE OUVRAGE et non par Code : le Code est partage par toute une
    # branche, il ne classe rien en dessous de son dernier niveau. Le tri est
    # porte par la VUE, la hierarchie reste donc juste apres n'importe quelle
    # correction, sans avoir a retrier quoi que ce soit. Les codes Ouvrage etant de
    # longueur fixe, l'ordre alphabetique EST l'ordre hierarchique.
    _dt_disc.DefaultView.Sort = 'code_ouvrage ASC'
    _dt_disc.DefaultView.RowFilter = 'visible = true'
    wpf.dgDisciplines.ItemsSource = _dt_disc.DefaultView

    def _disc_lignes():
        """
        Toutes les lignes du referentiel, triees par Code Ouvrage — y compris
        celles que le filtre d'affichage masque.

        Passe par DataTable.Rows et non par la vue : la vue est filtree, et
        recalculer sur les seules lignes visibles perdrait les parents, donc
        la resolution des jetons {supN}.
        """
        _out = [_r for _r in _dt_disc.Rows
                if _r.RowState != _DiscRowState.Deleted]
        _out.sort(key=lambda _r: _disc_txt(_r['code_ouvrage']).strip()
                  or _disc_txt(_r['code']).strip())
        return _out

    def _disc_items_pour_filtre():
        """
        [(code_ouvrage, libelle)] des lignes DISCIPLINE (hors ouvrage),
        dédoublonnées — même forme que disciplines.get_disciplines_et_sous(),
        mais relue en DIRECT sur _dt_disc plutôt que sur cfg : reflète les
        modifications de cet onglet non encore enregistrées, dans la même
        session. Alimente la colonne « Discipline » de « Vues personnalisées »
        (_open_discipline_dialog).
        """
        _vus, _out = set(), []
        for _r in _disc_lignes():
            if bool(_r['est_ouvrage']):
                continue
            _code = _disc_txt(_r['code_ouvrage']).strip()
            if not _code or _code in _vus:
                continue
            _vus.add(_code)
            _nom  = _disc_txt(_r['discipline']).strip()
            _sous = _disc_txt(_r['sous_discipline']).strip()
            _lib  = (u"{} — {}".format(_nom, _sous) if (_nom and _sous)
                     else (_nom or _sous))
            _out.append((_code, _lib))
        return _out

    # Anomalies du dernier recalcul, en (texte, ligne). Relues par
    # _on_save_click pour AVERTIR avant d'enregistrer un referentiel
    # incoherent — sans le refuser.
    _disc_anomalies = []
    # Lignes visees, dans l'ordre des entrees de la liste affichee : la
    # selection s'y retrouve par son index.
    _disc_anos_lignes = []
    _disc_en_cours  = [False]

    def _disc_set(row, col, valeur):
        """
        Ecrit une cellule calculee seulement si elle change. Reecrire la meme
        valeur redeclencherait un rendu de la grille a chaque recalcul, pour
        rien.
        """
        if _disc_txt(row[col]) != valeur:
            row[col] = valeur

    # Decalage horizontal d'un cran de hierarchie, en pixels. Calibre sur la
    # LARGEUR de la colonne « Code Ouv. » : le decalage est une marge interne a
    # la cellule, un cran trop large rognerait le code des niveaux profonds. A
    # 9 px, un code de 6 chiffres reste entier jusqu'au niveau 6.
    _DISC_INDENT = 9

    def _disc_peindre(row, niveau, nb_code, nb):
        """
        Pose les couleurs et le decalage de la ligne, seulement s'ils changent.

        La marge est calculee et non declaree en XAML : c'est ce qui permet de
        descendre aussi bas qu'on veut sans plafond de niveaux.
        """
        _hex = _disc_couleur_niveau(niveau, nb_code, nb)
        _temoin = u"{}|{}".format(niveau, _hex)
        if _disc_txt(row['aspect']) == _temoin:
            return
        row['aspect'] = _temoin
        row['brosse_fond'] = _brosse(_hex)
        row['brosse_texte'] = _brosse(_disc_texte_sur(_hex))
        row['marge'] = _DiscThickness(
            _DISC_INDENT * max(0, niveau - 1), 0, 0, 0)

    def _disc_recalculer(*_args):
        """
        Recalcule les colonnes derivees, les couleurs, la visibilite et les
        anomalies.

        Un seul passage, dans l'ordre des codes Ouvrage : un parent est donc
        toujours vu avant ses descendants, et son libelle comme son
        abreviation resolue sont deja a jour au moment d'en heriter.
        """
        if _disc_en_cours[0]:
            return
        _disc_en_cours[0] = True
        try:
            _nb, _nc, _digits, _lg_d, _lg_o, _sep, _maj = _disc_format()
            _lg_code = sum(_digits[:_nc])
            _lg_ouv  = sum(_digits)
            _lignes = _disc_lignes()

            # (texte, ligne) : la ligne rend l'anomalie ATTEIGNABLE. Sans elle,
            # « Une ligne n'a pas de Code Ouvrage » designe une ligne qui, par
            # definition, n'a aucun code permettant de la retrouver.
            _anos     = []

            def _ano(row, msg):
                _anos.append((msg, row))

            _ouvs_vus = {}
            # code Ouvrage → (libelle du niveau 1, niveau,
            #                 chaine d'abrev. discipline resolues,
            #                 chaine d'abrev. ouvrage resolues)
            # Les CHAINES listent la ligne puis ses ancetres, du plus proche au
            # plus lointain : c'est exactement ce que {supN} indexe, et la
            # construire de proche en proche evite de remonter la branche a
            # chaque cellule.
            _infos = {}

            def _invalide(row, msg):
                """Ligne dont le code ne se lit pas : rien de derive, et une
                teinte d'alerte pour qu'elle tranche."""
                _ano(row, msg)
                _disc_set(row, 'code', u'')
                _disc_set(row, 'niveau', u'')
                _disc_set(row, 'abrev_resolue', u'')
                _disc_set(row, 'abrev_ouvrage_resolue', u'')
                _disc_peindre(row, 0, _nc, _nb)

            def _majuscule_jeton(txt):
                """Passe en majuscules et retire les accents, SAUF les
                jetons : les remettre en capitales les rendrait
                meconnaissables a la resolution — et un jeton n'a de toute
                facon aucun caractere accentuable."""
                _out, _pos = [], 0
                for _m in _DISC_RE_JETON.finditer(txt):
                    _out.append(_disc_sans_accents(txt[_pos:_m.start()].upper()))
                    _out.append(_m.group(0))
                    _pos = _m.end()
                _out.append(_disc_sans_accents(txt[_pos:].upper()))
                return u''.join(_out)

            def _longueur_utile(gabarit):
                """Caracteres qui comptent : ni les jetons, ni les
                separateurs."""
                _u = _DISC_RE_JETON.sub(u'', gabarit)
                return _u.replace(_sep, u'') if _sep else _u

            def _resoudre_sup(gabarit, chaine):
                """
                Remplace chaque {supN} par le N-ieme element de `chaine`, qui
                liste les ancetres du plus proche au plus lointain.

                Retourne (texte resolu, [jetons hors portee]) : un rang plus
                grand que la branche ne se resout pas silencieusement en vide,
                il se signale.
                """
                _hors = []

                def _un(_m):
                    _rang = int(_m.group(1))
                    if _rang < 1 or _rang > len(chaine):
                        _hors.append(_m.group(0))
                        return u''
                    return chaine[_rang - 1]

                return _DISC_RE_SUP.sub(_un, gabarit), _hors

            # C'est le CODE OUVRAGE qui se saisit : c'est lui qui identifie la
            # ligne et qui porte toute la profondeur. Le Code Discipline s'en
            # deduit par simple troncature — l'inverse obligerait a deviner les
            # chiffres manquants des qu'on descend sous la frontiere.
            for _r in _lignes:
                # Un code colle depuis un tableur arrive avec ses separateurs
                # de milliers : on les retire AVANT de juger, et on reecrit la
                # cellule pour que l'utilisateur voie ce qui a ete retenu.
                _saisi = _disc_nettoyer_code(_disc_txt(_r['code_ouvrage']))
                _disc_set(_r, 'code_ouvrage', _saisi)
                # Jetons ramenes a leur forme canonique AVANT tout : « {SUP2} »
                # et « {sup} » (forme d'avant la numerotation) doivent se
                # resoudre comme « {sup2} » et « {sup1} ».
                _abrev = _disc_canoniser_jetons(
                    _disc_txt(_r['abrev_discipline']).strip())
                _abr = _disc_canoniser_jetons(
                    _disc_txt(_r['abrev_ouvrage']).strip())
                if _maj:
                    _abrev = _majuscule_jeton(_abrev)
                    _abr   = _majuscule_jeton(_abr)
                _disc_set(_r, 'abrev_discipline', _abrev)
                _disc_set(_r, 'abrev_ouvrage', _abr)

                if not _saisi:
                    _invalide(_r, u"Une ligne n'a pas de Code Ouvrage.")
                    continue
                if not _saisi.isdigit():
                    # Les separateurs de lisibilite ont deja ete retires : ce
                    # qui reste est un vrai caractere etranger, et le nommer
                    # evite de chercher lequel dans un code de six chiffres.
                    _fautifs = u''.join(sorted(set(
                        _c for _c in _saisi if not _c.isdigit())))
                    _invalide(
                        _r, u"Code Ouvrage « {} » : des chiffres uniquement. "
                            u"À retirer : {}".format(
                                _saisi, u' '.join(_fautifs)))
                    continue
                if len(_saisi) > _lg_ouv:
                    _invalide(
                        _r, u"Code Ouvrage « {} » : {} chiffres attendus, {} "
                            u"saisis. Une saisie plus COURTE est complétée par "
                            u"des zéros.".format(
                                _saisi, _lg_ouv, len(_saisi)))
                    continue
                # Saisie plus courte : completee par des zeros. Taper « 5111 »
                # vaut donc « 511100 », soit un niveau 4.
                _bim = _disc_normaliser(_saisi, _digits)

                _disc_set(_r, 'code_ouvrage', _bim)
                _disc_set(_r, 'code', _bim[:_lg_code])
                if _bim in _ouvs_vus:
                    _ano(_r, 
                        u"Code Ouvrage « {} » en double.".format(_bim))
                _ouvs_vus[_bim] = _bim

                _niv = _disc_niveau_de(_bim, _digits)
                _disc_set(_r, 'niveau', str(_niv))
                _disc_peindre(_r, _niv, _nc, _nb)

                _est_ouv = (_niv > _nc)
                if _disc_txt(_r['est_ouvrage']) != str(_est_ouv):
                    _r['est_ouvrage'] = _est_ouv

                if _niv == 1:
                    # Le nom de discipline est TOUJOURS en majuscules et sans
                    # accent : c'est une nomenclature, elle ne se saisit pas a
                    # la casse ni a l'orthographe du moment. Les descendants
                    # en heritent tel quel.
                    _nom_disc = _disc_sans_accents(
                        _disc_txt(_r['discipline']).strip().upper())
                    _disc_set(_r, 'discipline', _nom_disc)
                    _chaine_d, _chaine_o = [], []
                    _niv_par  = 0
                    _orphelin = False
                    _disc_set(_r, 'sous_discipline', u'')
                    if not _nom_disc:
                        _ano(_r, 
                            u"Code Ouvrage « {} » : discipline sans "
                            u"nom.".format(_bim))
                else:
                    _code_par = _disc_code_parent(_bim, _digits)
                    _parent   = _infos.get(_code_par)
                    _orphelin = (_parent is None)
                    if _orphelin:
                        _ano(_r, 
                            u"Code Ouvrage « {} » : le parent « {} » est "
                            u"absent.".format(_bim, _code_par))
                        _nom_disc, _niv_par = u'', 0
                        _chaine_d, _chaine_o = [], []
                    else:
                        (_nom_disc, _niv_par,
                         _chaine_d, _chaine_o) = _parent
                    _disc_set(_r, 'discipline', _nom_disc)
                    # Un OUVRAGE ne se raccroche qu'a une branche descendue
                    # jusqu'au DERNIER niveau de discipline. Sauter un niveau de
                    # discipline pour classer un ouvrage plus haut donnerait une
                    # ligne sans sous-discipline reelle, alors que tout ouvrage
                    # releve d'une discipline ET d'une sous-discipline.
                    if _est_ouv and not _orphelin and _niv_par < _nc:
                        _ano(_r, 
                            u"Code Ouvrage « {} » : un ouvrage ne peut venir "
                            u"qu'après le niveau {}, or son parent « {} » est "
                            u"au niveau {}.".format(
                                _bim, _nc, _code_par, _niv_par))
                    # Sous-discipline en majuscules et sans accent tant qu'on
                    # nomme une DISCIPLINE ; sur une ligne d'ouvrage le
                    # libelle designe un ouvrage reel (« Eau chaude
                    # sanitaire »), la saisie est laissee telle quelle — meme
                    # exception que pour la casse, et pour la meme raison.
                    _sous = _disc_txt(_r['sous_discipline']).strip()
                    if not _est_ouv:
                        _disc_set(_r, 'sous_discipline',
                                  _disc_sans_accents(_sous.upper()))
                    if not _sous:
                        _ano(_r, 
                            u"Code Ouvrage « {} » : {} sans nom.".format(
                                _bim,
                                u"sous-discipline" if not _est_ouv
                                else u"classement d'ouvrage"))

                # ── Chaine 1 : « Abrév. Discipline », sur toutes les lignes ──
                # PREREMPLISSAGE : une ligne qui a un parent et dont la cellule
                # est vide recoit {sup1}, le cas le plus courant. Une racine
                # reste vide, donc signalee, jusqu'a ce qu'on lui donne sa
                # propre abreviation.
                if not _abrev and _niv > 1:
                    _abrev = _DISC_SUP1
                    _disc_set(_r, 'abrev_discipline', _abrev)

                if not _abrev:
                    _ano(_r, 
                        u"Code Ouvrage « {} » : « Abrév. Discipline » "
                        u"vide.".format(_bim))
                if _DISC_DIS in _abrev:
                    # Le renvoi n'a de sens que dans l'autre sens : il pointe
                    # vers cette colonne-ci, il ne s'y emploie pas.
                    _ano(_r, 
                        u"Code Ouvrage « {} » : {} ne vaut que dans "
                        u"« Abrév. Ouvrage ».".format(_bim, _DISC_DIS))

                # LONGUEUR : on compte les seuls caracteres significatifs —
                # ni les jetons, ni les separateurs. Un gabarit reduit a un
                # jeton en est donc dispense : il dit « rien de plus que le
                # niveau vise ». Reglee a TOUS les niveaux, comme la colonne du
                # meme nom : « Abrév. Discipline » se saisit sur toutes les
                # lignes, ouvrages compris.
                _utile = _longueur_utile(_abrev)
                _ok_lg, _msg_lg = _disc_longueur_conforme(
                    _utile, _lg_d[_niv - 1])
                if not _ok_lg:
                    _ano(_r,
                        u"« {} » (code {}, niveau {}) : {}.".format(
                            _abrev, _bim, _niv, _msg_lg))

                # RESOLUTION : {supN} devient l'abreviation resolue du N-ieme
                # ancetre. Tout est explicite dans la cellule — plus aucune
                # regle de transmission ni de non-repetition a deviner.
                _resolue, _hors = _resoudre_sup(_abrev, _chaine_d)
                # Sur une ligne orpheline la chaine est vide POUR CETTE RAISON,
                # deja signalee : ne pas la reprocher une seconde fois.
                if not _orphelin:
                    for _j in _hors:
                        _ano(_r, 
                            u"Code Ouvrage « {} » : {} vise au-delà de la "
                            u"branche. {}".format(
                                _bim, _j, _disc_rangs_dispo(len(_chaine_d))))
                _disc_set(_r, 'abrev_resolue', _resolue)

                # ── Chaine 2 : « Abrév. Ouvrage », sur toutes les lignes ────
                # Une chaine d'abreviation d'ouvrage part TOUJOURS de sa
                # discipline : le niveau 1 vaut {dis}, sans discussion, et la
                # cellule y est bloquee a la saisie. Plus bas, {dis} reste
                # disponible pour rebaser la chaine sur la discipline de la
                # ligne courante.
                if _niv == 1:
                    if _abr != _DISC_DIS:
                        _abr = _DISC_DIS
                        _disc_set(_r, 'abrev_ouvrage', _abr)
                elif not _abr:
                    _abr = _DISC_SUP1
                    _disc_set(_r, 'abrev_ouvrage', _abr)

                if not _abr:
                    _ano(_r, 
                        u"Code Ouvrage « {} » : « Abrév. Ouvrage » "
                        u"vide.".format(_bim))

                _utile_o = _longueur_utile(_abr)
                _ok_lo, _msg_lo = _disc_longueur_conforme(
                    _utile_o, _lg_o[_niv - 1])
                if not _ok_lo:
                    _ano(_r,
                        u"« {} » (code {}, niveau {}) : {}.".format(
                            _abr, _bim, _niv, _msg_lo))

                _res_ouv, _hors_o = _resoudre_sup(_abr, _chaine_o)
                if not _orphelin:
                    for _j in _hors_o:
                        _ano(_r, 
                            u"Code Ouvrage « {} » : {} vise au-delà de la "
                            u"branche. {}".format(
                                _bim, _j, _disc_rangs_dispo(len(_chaine_o))))
                _res_ouv = _res_ouv.replace(_DISC_DIS, _resolue)
                _disc_set(_r, 'abrev_ouvrage_resolue', _res_ouv)

                # La ligne prend la tete de la chaine que liront ses enfants.
                _infos[_bim] = (_nom_disc, _niv,
                                [_resolue] + _chaine_d,
                                [_res_ouv] + _chaine_o)

            # AUCUN controle d'unicite sur les acronymes ni sur les
            # abreviations : deux lignes peuvent porter le meme, c'est un choix
            # de referentiel. La cle d'une ligne reste son Code Ouvrage, seul
            # unique — les fonctions de recherche par acronyme de
            # utils/disciplines en tiennent compte et peuvent rendre plusieurs
            # resultats.

            # Doublons de libelle de discipline : deux disciplines de meme nom
            # rendraient toute recherche par nom ambigue dans les scripts.
            _noms_vus = {}
            for _r in _lignes:
                if _disc_txt(_r['niveau']).strip() != '1':
                    continue
                _n = _disc_txt(_r['discipline']).strip().lower()
                if not _n:
                    continue
                if _n in _noms_vus:
                    _ano(_r, 
                        u"Discipline « {} » en double.".format(
                            _disc_txt(_r['discipline']).strip()))
                _noms_vus[_n] = True

            # PLUS DE DEDOUBLONNAGE par texte : trois lignes sans code
            # produisaient trois fois le meme message, reduit a un seul, et les
            # trois restaient introuvables. Une entree par ligne fautive, meme
            # si le texte se repete — c'est le clic qui les distingue.
            del _disc_anomalies[:]
            _disc_anomalies.extend(_anos)
            del _disc_anos_lignes[:]

            # Temoin par ligne, lu par le filtre « Anomalies seules ».
            _fautives = set(id(_a_row) for _txt, _a_row in _anos
                            if _a_row is not None)
            for _r in _lignes:
                _mauvaise = (id(_r) in _fautives)
                if _disc_txt(_r['en_anomalie']) != str(_mauvaise):
                    _r['en_anomalie'] = _mauvaise

            if _anos:
                _items = []
                for _txt, _a_row in _anos:
                    _items.append(u"⚠  " + _txt)
                    _disc_anos_lignes.append(_a_row)
                wpf.disc_anomalies.ItemsSource = _items
                wpf.disc_anomalies_titre.Text = (
                    u"{} anomalie{} — sélectionnez-en une pour aller à la "
                    u"ligne".format(len(_anos),
                                    u"s" if len(_anos) > 1 else u""))
                wpf.disc_anomalies_cadre.Visibility = _DiscVisibility.Visible
                wpf.disc_anomalies_seules.Visibility = _DiscVisibility.Visible
            else:
                wpf.disc_anomalies.ItemsSource = None
                wpf.disc_anomalies_cadre.Visibility = _DiscVisibility.Collapsed
                # La case se decoche en meme temps qu'elle disparait : la
                # laisser active masquerait toute la table une fois la
                # derniere anomalie corrigee.
                if bool(wpf.disc_anomalies_seules.IsChecked):
                    wpf.disc_anomalies_seules.IsChecked = False
                wpf.disc_anomalies_seules.Visibility = _DiscVisibility.Collapsed

            _disc_appliquer_filtre(_lignes)

            # La vue est triee par Code Ouvrage : saisir le code d'une ligne
            # neuve la fait quitter la tete du tableau pour aller se ranger
            # a sa place, parfois des centaines de lignes plus bas. Sans ce
            # rappel, l'utilisateur perd de vue la ligne qu'il est en train
            # de remplir, a chaque creation. C'est la boucle centrale de
            # l'onglet : elle doit rester continue.
            _selection = wpf.dgDisciplines.SelectedItem
            if _selection is not None and hasattr(_selection, 'Row'):
                try:
                    wpf.dgDisciplines.ScrollIntoView(_selection)
                except Exception:
                    pass
        finally:
            _disc_en_cours[0] = False

    # ── Filtre d'affichage ────────────────────────────────────────────────────
    def _disc_appliquer_filtre(lignes=None):
        """
        Calcule la colonne `visible` : le RowFilter de la vue s'y adosse.

        Une ligne est visible si elle est a un niveau autorise ET qu'elle
        correspond au texte cherche. Les ANCETRES d'un resultat restent
        affiches meme s'ils ne correspondent pas : sans eux, on verrait des
        sous-disciplines flotter sans savoir de quelle discipline elles
        relevent.
        """
        if lignes is None:
            lignes = _disc_lignes()
        _txt_f = wpf.disc_filtre.Text.strip().lower()
        _sel   = wpf.disc_niveau_max.SelectedItem
        _nivmax = _disc_int(_sel, 0) if _sel is not None else 0
        _nb, _nc, _digits, _lg_d, _lg_o, _sep, _maj = _disc_format()
        _anos_seules = bool(wpf.disc_anomalies_seules.IsChecked)

        _retenus = set()
        for _r in lignes:
            _bim = _disc_txt(_r['code_ouvrage']).strip()
            if _txt_f:
                _ok = any(_txt_f in _disc_txt(_r[_c]).lower()
                          for _c in ('code', 'code_ouvrage', 'discipline',
                                     'sous_discipline', 'abrev_discipline',
                                     'abrev_resolue', 'abrev_ouvrage',
                                     'abrev_ouvrage_resolue'))
                if not _ok:
                    continue
            _retenus.add(_bim)
            # Remonter la branche pour garder le contexte du resultat, de
            # parent en parent jusqu'a la racine.
            _courant = _bim
            while True:
                _courant = _disc_code_parent(_courant, _digits)
                if not _courant:
                    break
                _retenus.add(_courant)

        _nb_vis = 0
        for _r in lignes:
            _bim = _disc_txt(_r['code_ouvrage']).strip()
            _niv = _disc_int(_disc_txt(_r['niveau']), 0)
            # Une ligne en anomalie n'a ni code Ouvrage ni niveau : elle reste
            # visible, c'est justement elle qu'il faut corriger.
            _vis = ((not _bim) or
                    ((_bim in _retenus) and (not _nivmax or _niv <= _nivmax)))
            # Les filtres de colonne s'appliquent EN DERNIER, et sans rattraper
            # les ancetres : filtrer « Niveau = 3 » doit donner les seules
            # lignes de niveau 3, pas leur branche complete. La recherche
            # libre, elle, garde le contexte — les deux ne servent pas a la
            # meme chose.
            if _vis and _bim and not _fc.ligne_visible(_r):
                _vis = False
            # « Anomalies seules » passe APRES tout le reste et ne rattrape
            # aucun ancetre : on veut la liste des lignes a corriger, pas leur
            # contexte. C'est le seul filtre qui atteint une ligne sans code.
            if _vis and _anos_seules and _disc_txt(_r['en_anomalie']) != 'True':
                _vis = False
            if _disc_txt(_r['visible']) != str(_vis):
                _r['visible'] = _vis
            if _vis:
                _nb_vis += 1

        _total = len(lignes)
        wpf.disc_compte.Text = (
            u"{} ligne(s)".format(_total) if _nb_vis == _total
            else u"{} / {} ligne(s)".format(_nb_vis, _total))

    def _disc_remplir_niveau_max(nb):
        """Alimente le selecteur de repli, en conservant le choix courant."""
        _avant = wpf.disc_niveau_max.SelectedItem
        _items = [u'Tous'] + [str(_i) for _i in range(1, nb + 1)]
        wpf.disc_niveau_max.ItemsSource = _items
        wpf.disc_niveau_max.SelectedItem = (
            _avant if _avant in _items else u'Tous')

    _disc_remplir_niveau_max(_nb_i)

    # ── Temoin « modifications non enregistrees » ─────────────────────────────
    # Le referentiel que lisent les autres scripts n'est ecrit que par le
    # bouton « Enregistrer » du pied de fenetre. Tout le reste — export de
    # configuration compris — laisse le travail en attente, sans que rien ne le
    # dise. Le drapeau est pose par les chemins qui MODIFIENT, jamais par le
    # recalcul d'ouverture, qui n'est pas une modification.
    _disc_modifie = [False]

    def _disc_marquer_modifie(*_a):
        if not _disc_modifie[0]:
            _disc_modifie[0] = True
            wpf.disc_modifie.Visibility = _DiscVisibility.Visible

    def _disc_oublier_modifie():
        """Le travail est ecrit : le temoin s'efface."""
        _disc_modifie[0] = False
        wpf.disc_modifie.Visibility = _DiscVisibility.Collapsed

    def _disc_est_modifie():
        return bool(_disc_modifie[0])

    def _disc_planifier(*_args):
        """
        Recalcul APRES le commit de la cellule. Les evenements d'edition du
        DataGrid se declenchent avant que la saisie n'atteigne la DataRow :
        recalculer sur-le-champ travaillerait sur l'ancienne valeur.

        Branche sur les evenements d'edition et de suppression : y poser le
        drapeau couvre toute saisie sans avoir a l'ajouter cellule par cellule.

        Une edition ANNULEE (Echap dans la cellule) declenche quand meme
        CellEditEnding. Marquer la table modifiee la-dessus allumerait le
        temoin — et, une fois le garde-fou de fermeture en place, ferait
        reclamer une confirmation pour un travail que personne n'a change.
        """
        _annule = False
        for _a in _args:
            _act = getattr(_a, 'EditAction', None)
            if _act is not None:
                _annule = (str(_act) == 'Cancel')
        if not _annule:
            _disc_marquer_modifie()
        try:
            wpf.Dispatcher.BeginInvoke(
                _DiscPriority.Background, _DiscAction(_disc_recalculer))
        except Exception:
            _disc_recalculer()

    def _disc_planifier_filtre(*_args):
        try:
            wpf.Dispatcher.BeginInvoke(
                _DiscPriority.Background, _DiscAction(_disc_appliquer_filtre))
        except Exception:
            _disc_appliquer_filtre()

    def _disc_ouvrir_format(sender, e):
        """
        Ouvre la fenetre de format et applique le resultat.

        Le dialogue travaille sur une COPIE : annuler doit laisser le
        referentiel exactement dans l'etat ou il etait, y compris quand on a
        joue avec le nombre de niveaux avant de se raviser.
        """
        _nouveau = _dialogue_format_disciplines(
            wpf, dict(_fmt), _dt_disc.Rows.Count)
        if _nouveau is None:
            return
        _fmt.update(_nouveau)
        _disc_marquer_modifie()
        _disc_remplir_niveau_max(_fmt['niveaux'])
        # Teintes et decalages dependent de la frontiere Code / ouvrage : les
        # forcer a se recalculer, sans quoi le temoin `aspect` les figerait.
        for _r in _disc_lignes():
            _r['aspect'] = u''
        _disc_recalculer()

    wpf.dgDisciplines.CellEditEnding += _disc_planifier
    wpf.dgDisciplines.RowEditEnding  += _disc_planifier
    _dt_disc.RowDeleted              += _disc_planifier

    # Les boutons de la barre d'actions sont branches en bloc plus bas, avec le
    # menu « Fichier » et le clic droit de la grille.
    wpf.disc_filtre.TextChanged      += _disc_planifier_filtre
    wpf.disc_niveau_max.SelectionChanged += _disc_planifier_filtre

    def _disc_beginning_edit(s, e):
        """
        Interdit la saisie des colonnes sans objet sur la ligne visee :
        « Discipline » hors du niveau 1 (heritee du parent), « Sous-discipline »
        au niveau 1 (le nom de la discipline tient deja ce role) et
        « Abrév. Ouvrage » au niveau 1, ou elle vaut {dis} sans discussion —
        une chaine d'abreviation d'ouvrage part toujours de sa discipline.

        Les deux colonnes de gabarit restent ouvertes partout ailleurs, y
        compris « Abrév. Ouvrage » sur une ligne de discipline.
        """
        _item = e.Row.Item
        if not hasattr(_item, 'Row'):
            return
        _niv = _disc_txt(_item['niveau']).strip()
        # Indices de l'ordre des colonnes du XAML :
        # 0 Code Ouv. · 1 Code Dis. · 2 Niv. · 3 Discipline
        # · 4 Sous-discipline · 5 Abrév. Discipline · 6 Rés. Discipline
        # · 7 Abrév. Ouvrage · 8 Rés. Ouvrage.
        _col = e.Column.DisplayIndex
        if _col == 3 and _niv != '1':
            e.Cancel = True
        elif _col == 4 and _niv == '1':
            e.Cancel = True
        elif _col == 7 and _niv == '1':
            e.Cancel = True
        _disc_en_edition[0] = not bool(e.Cancel)

    # Le DataGrid n'expose pas son etat d'edition : on le suit ici pour que la
    # touche Suppr efface du TEXTE dans une cellule ouverte, et une LIGNE
    # ailleurs.
    _disc_en_edition = [False]

    def _disc_fin_edition(*_a):
        _disc_en_edition[0] = False

    wpf.dgDisciplines.BeginningEdit  += _disc_beginning_edit
    wpf.dgDisciplines.CellEditEnding += _disc_fin_edition
    wpf.dgDisciplines.RowEditEnding  += _disc_fin_edition

    def _disc_ajouter(sender, e):
        """
        Ajoute une ligne VIDE.

        Aucun code n'est propose : le niveau d'une ligne se lit dans son code,
        c'est donc la saisie qui decide, et pre-remplir reviendrait a choisir a
        la place de l'utilisateur.
        """
        _rd = _dt_disc.NewRow()
        for _c in ('code', 'code_ouvrage', 'niveau', 'discipline',
                   'sous_discipline', 'abrev_discipline', 'abrev_resolue',
                   'abrev_ouvrage', 'abrev_ouvrage_resolue', 'aspect'):
            _rd[_c] = u''
        _rd['est_ouvrage'] = False
        _rd['visible'] = True
        _dt_disc.Rows.Add(_rd)
        _disc_marquer_modifie()
        _disc_recalculer()
        for _rv in _dt_disc.DefaultView:
            if _rv.Row is _rd:
                wpf.dgDisciplines.SelectedItem = _rv
                try:
                    wpf.dgDisciplines.ScrollIntoView(_rv)
                    wpf.dgDisciplines.CurrentCell = _DiscCellInfo(
                        _rv, wpf.dgDisciplines.Columns[0])
                    wpf.dgDisciplines.BeginEdit()
                except Exception:
                    pass
                break

    def _disc_descendance(code_ouvrage, digits):
        """Lignes situees sous `code_ouvrage` dans la hierarchie, a tout niveau."""
        if not code_ouvrage:
            return []
        _tete = _disc_prefixe(code_ouvrage, digits)
        _niv = _disc_niveau_de(code_ouvrage, digits)
        _out = []
        for _r in _disc_lignes():
            _c = _disc_txt(_r['code_ouvrage']).strip()
            if _c == code_ouvrage or not _c.startswith(_tete):
                continue
            if _disc_niveau_de(_c, digits) > _niv:
                _out.append(_r)
        return _out

    def _disc_libelle_de(ligne):
        """Le nom le plus parlant d'une ligne, pour une confirmation."""
        return (_disc_txt(ligne['sous_discipline']).strip()
                or _disc_txt(ligne['discipline']).strip()
                or _disc_txt(ligne['code_ouvrage']).strip()
                or u'(sans code)')

    def _disc_supprimer(sender, e):
        """
        Supprime TOUTE la selection, descendance comprise, apres une seule
        confirmation.

        La grille est en selection multiple : ne traiter que SelectedItem
        supprimerait une ligne sur vingt sans rien dire, alors que l'ecran en
        montre vingt en surbrillance. Une action destructive ne peut pas faire
        autre chose que ce qu'elle affiche.
        """
        _nb, _nc, _digits, _lg_d, _lg_o, _sep, _maj = _disc_format()
        _choisies = [_v for _v in wpf.dgDisciplines.SelectedItems
                     if _v is not None and hasattr(_v, 'Row')]
        if not _choisies:
            return

        # Une ligne privee de son parent n'herite plus de rien et devient une
        # anomalie permanente : toute la branche part ensemble. Les branches
        # se recouvrent des qu'on selectionne un parent ET son enfant — d'ou
        # le dedoublonnage par DataRow avant de compter quoi que ce soit.
        _a_oter, _vues = [], set()
        for _v in _choisies:
            for _r in [_v.Row] + [_d.Row if hasattr(_d, 'Row') else _d
                                  for _d in _disc_descendance(
                                      _disc_txt(_v['code_ouvrage']).strip(),
                                      _digits)]:
                _cle = id(_r)
                if _cle not in _vues:
                    _vues.add(_cle)
                    _a_oter.append(_r)

        _en_plus = len(_a_oter) - len(_choisies)
        if _en_plus > 0:
            if len(_choisies) == 1:
                _quoi = u"« {} » compte {} ligne(s) sous elle, qui seront " \
                        u"supprimées avec elle.".format(
                            _disc_libelle_de(_choisies[0]), _en_plus)
            else:
                _quoi = u"{} lignes sélectionnées, {} lignes supprimées au " \
                        u"total en comptant leur descendance.".format(
                            len(_choisies), len(_a_oter))
            if not _disc_confirm(u"Supprimer la branche",
                                 _quoi + u"\n\nContinuer ?",
                                 yes_label=u"Supprimer"):
                return
        elif len(_choisies) > 1:
            # Pas de descendance, mais plusieurs lignes : le nombre seul suffit
            # a lever le doute sur ce qui va partir.
            if not _disc_confirm(
                    u"Supprimer",
                    u"{} lignes seront supprimées.\n\nContinuer ?".format(
                        len(_choisies)),
                    yes_label=u"Supprimer"):
                return

        # Instantane AVANT suppression : une DataRow supprimee ('Deleted') ne
        # redonne plus ses valeurs, seul le moment juste avant .Delete() les
        # a encore. Une portee remplace la precedente : Ctrl+Z ne remonte
        # qu'un cran, pas un historique complet.
        del _disc_dernier_supprime[:]
        _cols = [_c.ColumnName for _c in _dt_disc.Columns]
        for _r in _a_oter:
            _disc_dernier_supprime.append(
                dict((_c, _r[_c]) for _c in _cols))

        # RowDeleted est deja branche sur _disc_planifier : le temoin
        # « modifications » s'allume tout seul, inutile de le repeter ici.
        for _r in _a_oter:
            _r.Delete()
        _disc_recalculer()

    def _disc_annuler_suppression():
        """
        Ctrl+Z : redonne la derniere portee supprimee. Pas un historique —
        une seule reprise, ecrasee par la suppression suivante. Confirmer
        une suppression protege l'erreur qu'on remarque tout de suite ;
        ceci protege celle qu'on remarque trente secondes plus tard, sans
        repasser par « Annuler » qui aurait aussi jete le reste de la saisie.
        """
        if not _disc_dernier_supprime:
            return
        _premier_code = None
        for _snap in _disc_dernier_supprime:
            _r = _dt_disc.NewRow()
            for _c, _v in _snap.items():
                _r[_c] = _v
            _dt_disc.Rows.Add(_r)
            if _premier_code is None:
                _premier_code = _disc_txt(_snap.get('code_ouvrage'))
        del _disc_dernier_supprime[:]
        _disc_marquer_modifie()
        _disc_recalculer()
        if _premier_code:
            for _rv in _dt_disc.DefaultView:
                if _disc_txt(_rv['code_ouvrage']).strip() == _premier_code:
                    wpf.dgDisciplines.SelectedItem = _rv
                    try:
                        wpf.dgDisciplines.ScrollIntoView(_rv)
                    except Exception:
                        pass
                    break

    def _disc_exporter(sender, e):
        _disc_exporter_xlsx(wpf, _disc_lignes(),
                            lambda _l, _c: _disc_txt(_l[_c]),
                            _disc_format())

    def _disc_importer(sender, e):
        _entrees = _disc_importer_xlsx(wpf)
        if not _entrees:
            return
        if _dt_disc.Rows.Count and not _disc_confirm(
                u"Importer un .XLSX",
                u"La table contient {} ligne(s), qui seront remplacées par "
                u"les {} ligne(s) du fichier.\n\nContinuer ?".format(
                    _dt_disc.Rows.Count, len(_entrees)),
                yes_label=u"Remplacer"):
            return
        _disc_charger_table(_entrees)
        _disc_marquer_modifie()
        _fc.reinitialiser_tout()
        _disc_recalculer()

    def _disc_cfg_ecrire(sender, e):
        _disc_cfg_enregistrer(
            wpf, _disc_section(_disc_format(), _disc_lignes(), _disc_txt))

    def _disc_cfg_lire(sender, e):
        """
        Remplace la table ET la structure. Les deux vont ensemble : recharger
        la table sans son decoupage relirait tous les codes de travers.
        """
        _res = _disc_cfg_charger(wpf)
        if not _res:
            return
        _nouveau_fmt, _entrees = _res
        if _dt_disc.Rows.Count and not _disc_confirm(
                u"Importer une configuration",
                u"La table contient {} ligne(s), qui seront remplacées par "
                u"les {} ligne(s) du fichier — la structure de la table "
                u"aussi.\n\nContinuer ?".format(
                    _dt_disc.Rows.Count, len(_entrees)),
                yes_label=u"Remplacer"):
            return
        _fmt.update(_nouveau_fmt)
        _disc_marquer_modifie()
        _disc_remplir_niveau_max(_fmt['niveaux'])
        _disc_charger_table(_entrees)
        # Teintes et decalages dependent de la frontiere : les forcer a se
        # recalculer, sans quoi le temoin `aspect` les figerait.
        for _r in _disc_lignes():
            _r['aspect'] = u''
        _fc.reinitialiser_tout()
        _disc_recalculer()

    def _disc_aide(sender, e):
        _dialogue_aide_disciplines(wpf, _disc_resume_format(*_disc_format()))

    def _disc_code_libre(code, digits):
        """
        Prochain code libre au MEME niveau et sous le MEME parent que `code`.

        Duplique-t-on une ligne, il lui faut un code : le reprendre tel quel
        creerait un doublon instantane, et le laisser vide ferait remonter la
        nouvelle ligne en tete de la vue (tri par code) avant de la faire
        redescendre a la saisie. Le prochain code libre de la fratrie evite les
        deux.

        Retourne None si la tranche du niveau est saturee.
        """
        _niv = _disc_niveau_de(code, digits)
        _tete = sum(digits[:_niv - 1])
        _larg = digits[_niv - 1]
        _prefixe = code[:_tete]
        _queue = u'0' * sum(digits[_niv:])
        _pris = set()
        for _r in _disc_lignes():
            _c = _disc_txt(_r['code_ouvrage']).strip()
            if len(_c) == len(code) and _c[:_tete] == _prefixe:
                _pris.add(_c[_tete:_tete + _larg])
        # La tranche part a 1 : une tranche nulle designerait le niveau du
        # dessus, pas une ligne de cette fratrie.
        for _v in range(1, 10 ** _larg):
            _tr = str(_v).zfill(_larg)
            if _tr not in _pris:
                return _prefixe + _tr + _queue
        return None

    def _disc_dupliquer(sender, e):
        """
        Copie les colonnes SAISISSABLES de la ligne selectionnee sous le
        prochain code libre de sa fratrie. Les colonnes calculees ne sont pas
        reprises : le recalcul les repose immediatement.
        """
        _sel = wpf.dgDisciplines.SelectedItem
        if _sel is None or not hasattr(_sel, 'Row'):
            return
        _nb, _nc, _digits, _lg_d, _lg_o, _sep, _maj = _disc_format()
        _code = _disc_txt(_sel['code_ouvrage']).strip()
        if not _code:
            return
        _neuf = _disc_code_libre(_code, _digits)
        if _neuf is None:
            _disc_alert(
                u"Dupliquer",
                u"Aucun code libre à ce niveau : la tranche du niveau {} est "
                u"saturée sous ce parent.".format(
                    _disc_niveau_de(_code, _digits)),
                close_label=u"Fermer")
            return

        _rd = _dt_disc.NewRow()
        for _c in ('code', 'niveau', 'abrev_resolue', 'abrev_ouvrage_resolue',
                   'aspect'):
            _rd[_c] = u''
        _rd['code_ouvrage'] = _neuf
        for _c in ('discipline', 'sous_discipline', 'abrev_discipline',
                   'abrev_ouvrage'):
            _rd[_c] = _disc_txt(_sel[_c])
        _rd['est_ouvrage'] = False
        _rd['visible'] = True
        _dt_disc.Rows.Add(_rd)
        _disc_marquer_modifie()
        _disc_recalculer()
        for _rv in _dt_disc.DefaultView:
            if _rv.Row is _rd:
                wpf.dgDisciplines.SelectedItem = _rv
                try:
                    wpf.dgDisciplines.ScrollIntoView(_rv)
                except Exception:
                    pass
                break

    # ── Menu « Fichier » ──────────────────────────────────────────────────────
    # Un ContextMenu ouvert au clic GAUCHE : les quatre actions de fichier sont
    # rares, les garder en boutons faisait deborder la barre de 450 px.
    def _disc_menu_fichier(sender, e):
        _m = wpf.btnDiscFichier.ContextMenu
        _m.PlacementTarget = wpf.btnDiscFichier
        _m.Placement = _DiscPlacement.Bottom
        _m.IsOpen = True

    wpf.btnDiscFichier.Click        += _disc_menu_fichier
    wpf.miDiscCfgCharger.Click      += _disc_cfg_lire
    wpf.miDiscCfgEnregistrer.Click  += _disc_cfg_ecrire
    wpf.miDiscExport.Click          += _disc_exporter
    wpf.miDiscImport.Click          += _disc_importer

    wpf.btnDiscAjout.Click     += _disc_ajouter
    wpf.btnDiscSupprimer.Click += _disc_supprimer
    wpf.btnDiscFormat.Click    += _disc_ouvrir_format
    wpf.btnDiscAide.Click      += _disc_aide

    # ── Clic droit sur la grille ──────────────────────────────────────────────
    # Meme menu que dgTypesVues, dgProfilsLiaison et dgTypesNomenclatures :
    # cette grille etait la seule des quatre a en etre privee. La ligne visee
    # est capturee AVANT l'ouverture — SelectedItem n'est pas encore a jour au
    # moment ou le menu s'ouvre.
    _disc_ctx_item = [None]

    def _disc_clic_droit(sender, e):
        _obj = e.OriginalSource
        while _obj is not None:
            _dc = getattr(_obj, 'DataContext', None)
            if _dc is not None and hasattr(_dc, 'Row'):
                _disc_ctx_item[0] = _dc
                wpf.dgDisciplines.SelectedItem = _dc
                return
            try:
                _obj = _DiscVTH.GetParent(_obj)
            except Exception:
                break
        _disc_ctx_item[0] = None

    wpf.dgDisciplines.PreviewMouseRightButtonDown += _disc_clic_droit

    _ctx_disc = wpf.dgDisciplines.ContextMenu
    _ctx_disc_nouvelle  = _ctx_disc.Items[0]
    _ctx_disc_dupliquer = _ctx_disc.Items[1]
    # Items[2] = Separator
    _ctx_disc_supprimer = _ctx_disc.Items[3]

    def _disc_nb_selection():
        return len([_v for _v in wpf.dgDisciplines.SelectedItems
                    if _v is not None and hasattr(_v, 'Row')])

    def _disc_ctx_ouvert(sender, e):
        # « Dupliquer » reste une action a UNE ligne : dupliquer vingt lignes
        # d'un coup n'a pas de sens sur un referentiel ou chaque code est
        # unique. « Supprimer », lui, suit la selection entiere.
        _n = _disc_nb_selection()
        _ctx_disc_dupliquer.IsEnabled = (_n == 1)
        _ctx_disc_supprimer.IsEnabled = (_n > 0)
        _ctx_disc_supprimer.Header = (
            u"Supprimer" if _n <= 1
            else u"Supprimer les {} lignes".format(_n))

    _ctx_disc.Opened          += _disc_ctx_ouvert
    _ctx_disc_nouvelle.Click  += _disc_ajouter
    _ctx_disc_dupliquer.Click += _disc_dupliquer
    _ctx_disc_supprimer.Click += _disc_supprimer

    # Le bouton suit la meme regle que l'entree de menu : rien de selectionne,
    # rien a supprimer.
    def _disc_maj_supprimer(*_a):
        wpf.btnDiscSupprimer.IsEnabled = (_disc_nb_selection() > 0)

    wpf.dgDisciplines.SelectionChanged += _disc_maj_supprimer
    _disc_maj_supprimer()

    # ── Touche Suppr ──────────────────────────────────────────────────────────
    # Troisieme chemin vers la MEME confirmation. La suppression native du
    # DataGrid est coupee (CanUserDeleteRows=False) : elle effacait la ligne
    # sans emporter sa descendance, laissant une branche orpheline en silence.
    def _disc_touche(sender, e):
        # Ctrl+Z : reprend la derniere suppression, meme reflexe que partout
        # ailleurs. En cours d'edition, laisser la cellule geree le sien
        # (annuler la frappe en cours), pas la table.
        if (e.Key == _DiscKey.Z
                and (_DiscKeyboard.Modifiers & _DiscModifierKeys.Control)
                and not _disc_en_edition[0]):
            e.Handled = True
            _disc_annuler_suppression()
            return
        if e.Key != _DiscKey.Delete:
            return
        # En cours d'edition, Suppr efface du TEXTE : ne pas le detourner.
        if _disc_en_edition[0]:
            return
        e.Handled = True
        _disc_supprimer(sender, e)

    wpf.dgDisciplines.PreviewKeyDown += _disc_touche

    # ── Touches dans la zone « Rechercher » ───────────────────────────────────
    # Le bouton « Enregistrer » du pied de fenetre porte IsDefault, « Annuler »
    # porte IsCancel : leur portee est la FENETRE. Un TextBox mono-ligne ne
    # consomme ni Entree ni Echap, donc valider un terme de recherche
    # enregistrait tout et fermait, et Echap jetait la session. Deux reflexes
    # universels, deux issues destructrices.
    def _disc_touche_filtre(sender, e):
        if e.Key == _DiscKey.Enter:
            # La recherche est deja appliquee a la frappe : Entree n'a rien a
            # declencher, elle doit seulement ne pas remonter.
            e.Handled = True
        elif e.Key == _DiscKey.Escape:
            if wpf.disc_filtre.Text:
                wpf.disc_filtre.Text = u''
                e.Handled = True

    wpf.disc_filtre.PreviewKeyDown += _disc_touche_filtre

    # ── De l'anomalie a la ligne ──────────────────────────────────────────────
    # Le chainon qui manquait : le message nommait le probleme, il emmene
    # maintenant dessus. Sans ce saut, corriger 40 anomalies imposait 40
    # aller-retours « lire le code, le retaper dans Rechercher, corriger,
    # vider le champ ».
    def _disc_activer_anomalie():
        _i = wpf.disc_anomalies.SelectedIndex
        if _i < 0 or _i >= len(_disc_anos_lignes):
            return
        _cible = _disc_anos_lignes[_i]
        if _cible is None:
            return
        for _rv in _dt_disc.DefaultView:
            if _rv.Row is _cible:
                wpf.dgDisciplines.SelectedItem = _rv
                try:
                    wpf.dgDisciplines.ScrollIntoView(_rv)
                    wpf.dgDisciplines.CurrentCell = _DiscCellInfo(
                        _rv, wpf.dgDisciplines.Columns[0])
                except Exception:
                    pass
                return
        # La ligne existe mais le filtre la masque : le dire plutot que de
        # laisser un clic sans effet.
        _disc_alert(
            u"Anomalie masquée",
            u"La ligne concernée est masquée par le filtre d'affichage en "
            u"cours. Cochez « Anomalies seules » ou videz la recherche pour "
            u"l'atteindre.",
            close_label=u"Fermer")

    def _disc_aller_anomalie(sender, e):
        _disc_activer_anomalie()

    # btnSave porte IsDefault en portee fenetre : sans interception, Entree
    # depuis cette liste l'active au lieu d'aller a la ligne visee — le
    # controle qui existe pour REPARER une anomalie declenchait l'enregistrement
    # a sa place. Un deuxieme clic sur une entree deja selectionnee ne
    # redeclenche pas SelectionChanged ; PreviewMouseLeftButtonDown le fait.
    def _disc_touche_anomalies(sender, e):
        if e.Key == _DiscKey.Enter:
            _disc_activer_anomalie()
            e.Handled = True

    def _disc_reclic_anomalie(sender, e):
        # MouseLeftButtonUp, pas Preview...Down : la selection de l'item doit
        # deja etre posee quand on lit SelectedIndex, sinon un clic qui
        # CHANGE la selection relirait encore l'ancien index.
        _disc_activer_anomalie()

    wpf.disc_anomalies.SelectionChanged += _disc_aller_anomalie
    wpf.disc_anomalies.PreviewKeyDown += _disc_touche_anomalies
    wpf.disc_anomalies.MouseLeftButtonUp += _disc_reclic_anomalie
    wpf.disc_anomalies_seules.Checked    += _disc_planifier_filtre
    wpf.disc_anomalies_seules.Unchecked  += _disc_planifier_filtre

    # Meme piege que disc_filtre : disc_niveau_max n'a pas de sens propre pour
    # Entree (la selection s'applique deja au choix), et sans interception il
    # remonte jusqu'a btnSave.
    def _disc_touche_niveau_max(sender, e):
        if e.Key == _DiscKey.Enter:
            e.Handled = True

    wpf.disc_niveau_max.PreviewKeyDown += _disc_touche_niveau_max

    # ── Filtres en en-tete de colonne ─────────────────────────────────────────
    # Meme ergonomie que les autres tables de l'extension, MOINS le bouton de
    # tri : l'ordre de cette table porte la hierarchie, la reorganiser la
    # rendrait illisible. Le reload() n'est pas decoratif — pyRevit garde les
    # modules de lib/ en cache, et `avec_tri` vient d'y etre ajoute.
    import dialogs.filtres_colonnes as _mod_fc
    reload(_mod_fc)
    _fc = _mod_fc.FiltresColonnes(
        _disc_lignes,
        on_change=_disc_planifier_filtre,
        lecteur=lambda _l, _c: _disc_txt(_l[_c]),
        owner=wpf)
    # Cinq de ces neuf en-tetes sont ABREGES faute de largeur. Leur infobulle
    # developpe l'abreviation et dit ce que la colonne contient : la reprendre
    # telle quelle — « Niv. » au survol de « Niv. » — n'apprendrait rien.
    for _idx, (_lib, _cle, _bulle) in enumerate((
            (u"Code Ouv.", 'code_ouvrage',
             u"Code Ouvrage : la seule colonne de code qui se saisit. Ses "
             u"chiffres situent la ligne dans la hiérarchie."),
            (u"Code Dis.", 'code',
             u"Code Discipline : les premiers chiffres du Code Ouvrage, "
             u"partagés par toute une branche. Calculé."),
            (u"Niv.", 'niveau',
             u"Niveau hiérarchique, déduit du Code Ouvrage. Calculé."),
            (u"Discipline", 'discipline', None),
            (u"Sous-discipline / Ouvrage", 'sous_discipline', None),
            (u"Abrév. Discipline", 'abrev_discipline',
             u"Abréviation de discipline : le gabarit saisi, avec ses jetons."),
            (u"Rés. Discipline", 'abrev_resolue',
             u"Résultat : le gabarit « Abrév. Discipline » une fois ses "
             u"jetons remplacés. Calculé."),
            (u"Abrév. Ouvrage", 'abrev_ouvrage',
             u"Abréviation d'ouvrage : le gabarit saisi, avec ses jetons."),
            (u"Rés. Ouvrage", 'abrev_ouvrage_resolue',
             u"Résultat : le gabarit « Abrév. Ouvrage » une fois ses jetons "
             u"remplacés. Calculé."))):
        wpf.dgDisciplines.Columns[_idx].Header = _fc.entete(
            _lib, _cle, filtrable=True, avec_tri=False, infobulle=_bulle)

    _disc_recalculer()

    # Accesseurs plutot que variables remontees une par une : une seule
    # variable de plus dans main(), pour la meme raison que ci-dessus.
    return {
        'anomalies':   _disc_anomalies,
        'recalculer':  _disc_recalculer,
        'lignes':      _disc_lignes,
        'format':      _disc_format,
        'txt':         _disc_txt,
        'entier':      _disc_int,
        # Colonne « Discipline » de « Vues personnalisées », en direct sur
        # cette session (voir _disc_items_pour_filtre).
        'items_disciplines': _disc_items_pour_filtre,
        # Appele par l'enregistrement : c'est lui, et lui seul, qui met le
        # referentiel a jour pour les autres scripts.
        'oublier_modifie': _disc_oublier_modifie,
        # Relu par le garde-fou de fermeture de la fenetre.
        'est_modifie':     _disc_est_modifie,
    }




def _init_tvp_recherche(wpf, ctx):
    """
    Recherche, filtres et tri d'en-tete, Dupliquer et aide de la table
    « Vues personnalisees » (onglet « Vues »).

    Fonction de MODULE et non un bloc de main(), pour la meme raison que
    _init_disciplines : IronPython 2.7 plafonne le nombre de variables
    locales d'une fonction, et le depassement se manifeste par un
    « Sequence contains no elements » pointant une ligne sans rapport.

    `ctx` porte tout ce que la fenetre a deja construit — la table, les
    stores des dialogues « Configurer… », les lecteurs de libelles. Un dict
    plutot que quinze parametres positionnels : l'appel reste lisible.

    Retourne {maj_derivees, appliquer_filtre}, que l'appelant rappelle apres
    toute action qui change un reglage.
    """
    from System.Data import DataRowState as _RowState
    from System.Windows.Threading import DispatcherPriority as _Prio
    from System.Windows.Input import Key as _K
    from System import Action as _Act

    _dt = ctx['dt']

    def _txt(val):
        return u'' if val is None else unicode(val)

    def _lignes():
        """Toutes les lignes, y compris celles que le filtre masque."""
        return [_r for _r in _dt.Rows if _r.RowState != _RowState.Deleted]

    _DERIVEES = ('f_familles', 'f_discipline', 'f_types', 'f_gabarits',
                 'f_niveaux', 'f_dispo')
    # Separateur des colonnes derivees MULTI-VALEURS. U+001F (separateur
    # d'unite) et non « , » : un nom de gabarit ou de type de vue peut
    # parfaitement contenir une virgule, et la cellule se decouperait alors au
    # mauvais endroit. Ce caractere ne peut pas etre saisi dans Revit, et ces
    # colonnes ne sont jamais affichees — l'invisibilite ne coute rien.
    _SEP = unichr(0x1f)

    def _maj_derivees():
        """
        Recopie en texte, dans les colonnes derivees, ce que chaque bouton
        « Configurer… » a regle.

        Sans elles la recherche et les filtres d'en-tete n'auraient rien a
        lire sur ces six colonnes : un bouton n'a pas de contenu. Recalcule
        apres chaque dialogue plutot que lu a la volee — le RowFilter
        d'ADO.NET travaille sur des colonnes, pas sur des fonctions.
        """
        _lib_vue  = dict((_iv, _lv) for _lv, _iv, _kv in ctx['vue_noms']())
        _lib_disc = dict(ctx['items_disc']())
        _lib_niv  = dict(ctx['items_niveaux']())
        for _r in _lignes():
            _lbl = _txt(_r['label'])
            if not _lbl:
                for _c in _DERIVEES:
                    _r[_c] = u''
                continue
            _r['f_familles'] = _SEP.join(sorted(
                _lib_vue.get(_iv, _iv) for _iv in ctx['familles_actives'](_lbl)))
            _r['f_discipline'] = _SEP.join(sorted(
                _lib_disc.get(_c, _c) for _c in ctx['disciplines_actives'](_lbl)))
            _r['f_types'] = _SEP.join(sorted(set(
                _v for _v in (ctx['types_store'].get(_lbl, {}) or {}).values() if _v)))
            _r['f_gabarits'] = _SEP.join(sorted(set(
                _v for _v in (ctx['gabarits_store'].get(_lbl, {}) or {}).values() if _v)))
            _niv = ctx['niveaux_defaut'].get(_lbl)
            if _niv is None:
                _niv = dict((_k, bool(_v)) for _k, _v in ctx['niveaux_global'].items())
            _r['f_niveaux'] = _SEP.join(sorted(
                _lib_niv.get(_k, _k) for _k, _v in _niv.items() if _v))
            _p3d = (_lbl == ctx['label_p3d'])
            _outils = []
            if (not _p3d) and ctx['dispo_cao'].get(_lbl, True):
                _outils.append(u"Lier CAO → Vues")
            if (not _p3d) and ctx['dispo_vp'].get(_lbl, True):
                _outils.append(u"Vues +")
            if _p3d:
                _outils.append(u"Pièces 3D")
            _r['f_dispo'] = _SEP.join(_outils)

    _COLS = (
        (u"Ord.", 'ordre',
         u"Ordre d'affichage. Texte libre : « 10bis » ou « A1 » sont acceptés, "
         u"et se rangent naturellement (2 avant 10)."),
        (u"Label", 'label',
         u"Identifiant de la vue personnalisée : c'est lui qui la désigne "
         u"partout ailleurs, et la valeur de {vue-pers-label}."),
        (u"Titre", 'titre', u"Valeur de {vue-pers-titre} dans les nommages."),
        (u"Valeur-1", 'valeur_1', u"Valeur de {vue-pers-valeur-1}."),
        (u"Valeur-2", 'valeur_2', u"Valeur de {vue-pers-valeur-2}."),
        (u"Usage", 'usage',
         u"Temporaire ou Livrable. Valeur de {vue-pers-usage}."),
        (u"Familles de vues", 'f_familles',
         u"Familles de vues cochées pour cette ligne. Le filtre porte sur "
         u"leur contenu, pas sur le bouton, et propose chaque famille "
         u"séparément."),
        (u"Discipline", 'f_discipline',
         u"Disciplines cochées pour cette ligne. Le filtre propose chaque "
         u"discipline séparément."),
        (u"Types de vues", 'f_types',
         u"Types de vues Revit renseignés pour cette ligne. Le filtre "
         u"propose chaque type séparément."),
        (u"Gabarits de vues", 'f_gabarits',
         u"Gabarits de vues renseignés pour cette ligne. Le filtre propose "
         u"chaque gabarit séparément."),
        (u"Types niv. par défaut", 'f_niveaux',
         u"Types de niveaux cochés par défaut pour cette ligne. Le filtre "
         u"propose chaque type de niveau séparément."),
        (u"Disponibilité", 'f_dispo',
         u"Outils NM-BATII dans lesquels cette ligne est proposée."),
    )
    _CLES = [_c for _lib, _c, _b in _COLS]
    # Colonnes dont une cellule porte PLUSIEURS valeurs : le filtre doit les
    # proposer une par une et garder la ligne des qu'une est cochee. Sans
    # cela il n'offrirait que des combinaisons entieres — « Plan d'étage,
    # Vue 3D » comme un seul choix — inutilisables des que deux lignes ne
    # portent pas exactement le meme jeu.
    _MULTI = ('f_familles', 'f_discipline', 'f_types', 'f_gabarits',
              'f_niveaux', 'f_dispo')

    def _appliquer_filtre(*_a):
        """
        Recherche libre ET filtres d'en-tete, ecrits dans la colonne
        `visible` que porte le RowFilter de la vue.

        La recherche balaie toutes les colonnes lisibles, derivees comprises.
        """
        _texte = (wpf.tvp_filtre.Text or u'').strip().lower()
        _vus = _lignes()
        _nb = 0
        for _r in _vus:
            _vis = _fc.ligne_visible(_r)
            if _vis and _texte:
                _vis = any(_texte in _txt(_r[_c]).lower() for _c in _CLES)
            if _txt(_r['visible']) != unicode(_vis):
                _r['visible'] = _vis
            if _vis:
                _nb += 1
        _restreint = bool(_texte) or _fc.actif()
        wpf.tvp_compte.Text = (
            u"{} / {} ligne(s)".format(_nb, len(_vus))
            if _restreint else u"{} ligne(s)".format(len(_vus)))
        # Grise quand il n'y a rien a effacer : le bouton repond ainsi a
        # « reste-t-il un filtre quelque part ? », question que la table
        # seule ne permet pas de trancher.
        wpf.btnTvpResetFiltres.IsEnabled = _restreint
        # Le tri des en-tetes passe par la VUE : trier une liste Python ne
        # reordonnerait rien, c'est le DataView qui decide de l'affichage.
        if _fc.tri:
            _cle_tri, _sens = _fc.tri
            # « Ord. » se trie sur sa cle naturelle, pas sur son texte brut.
            _col = 'ordre_cle' if _cle_tri == 'ordre' else _cle_tri
            _dt.DefaultView.Sort = u"{} {}".format(
                _col, u'DESC' if _sens == 'desc' else u'ASC')
        else:
            _dt.DefaultView.Sort = ctx['tri_defaut']

    import dialogs.filtres_colonnes as _mod_fc
    reload(_mod_fc)
    _fc = _mod_fc.FiltresColonnes(
        _lignes, on_change=_appliquer_filtre,
        lecteur=lambda _l, _c: _txt(_l[_c]), owner=wpf)
    # avec_tri=True, contrairement aux disciplines : ici l'ordre d'affichage
    # ne porte aucune hierarchie, le reclasser de A a Z est sans consequence.
    for _i, (_lib_c, _cle_c, _bulle_c) in enumerate(_COLS):
        wpf.dgTypesVues.Columns[_i].Header = _fc.entete(
            _lib_c, _cle_c, filtrable=True, avec_tri=True, infobulle=_bulle_c,
            separateur=(_SEP if _cle_c in _MULTI else None))

    wpf.tvp_filtre.TextChanged += _appliquer_filtre

    def _reset_filtres(sender, e):
        """Un seul geste : la recherche ET tous les filtres de colonnes."""
        if wpf.tvp_filtre.Text:
            wpf.tvp_filtre.Text = u''   # declenche _appliquer_filtre
        _fc.reinitialiser_tout()        # idem, s'il y avait un filtre
        _appliquer_filtre()             # cas ou ni l'un ni l'autre n'a bouge

    wpf.btnTvpResetFiltres.Click += _reset_filtres

    def _touche_filtre(sender, e):
        # btnSave porte IsDefault en portee fenetre : sans interception,
        # Entree depuis la recherche enregistrerait tout et fermerait.
        if e.Key == _K.Enter:
            e.Handled = True
        elif e.Key == _K.Escape and wpf.tvp_filtre.Text:
            wpf.tvp_filtre.Text = u''
            e.Handled = True

    wpf.tvp_filtre.PreviewKeyDown += _touche_filtre

    def _fin_edition(sender, e):
        """Une edition peut changer « Ord. » : sa cle de tri doit suivre."""
        if str(getattr(e, 'EditAction', u'')) == 'Cancel':
            return
        _row = getattr(e.Row, 'Item', None)
        if _row is None or not hasattr(_row, 'Row'):
            return

        def _apres():
            # Label et Titre en majuscules a la validation de la cellule.
            # Ecrit seulement si cela change : reecrire la meme valeur
            # relancerait un rendu de la grille a chaque frappe.
            _maj_l = ctx['maj_label'](_row['label'])
            if unicode(_row['label'] or u'') != _maj_l:
                _row['label'] = _maj_l
            _maj_t = ctx['maj_titre'](_row['titre'])
            if unicode(_row['titre'] or u'') != _maj_t:
                _row['titre'] = _maj_t
            _row['ordre_cle'] = ctx['cle_ordre'](_row['ordre'])
            # APRES la mise en majuscules et AVANT le recalcul des colonnes
            # derivees : les tables de reglages s'indexent sur le Label
            # definitif, et les colonnes derivees les relisent juste apres.
            ctx['renommer'](_row)
            _maj_derivees()
            _appliquer_filtre()

        # Les evenements d'edition se declenchent AVANT que la saisie
        # n'atteigne la DataRow : recalculer sur-le-champ travaillerait sur
        # l'ancienne valeur.
        try:
            wpf.Dispatcher.BeginInvoke(_Prio.Background, _Act(_apres))
        except Exception:
            _apres()

    wpf.dgTypesVues.CellEditEnding += _fin_edition

    def _dupliquer_bouton(sender, e):
        """
        « Dupliquer » agit sur la SELECTION de la grille ; le menu contextuel,
        lui, vise la ligne du clic droit. Les deux passent par le meme code,
        en posant simplement la cible avant.
        """
        _sel = wpf.dgTypesVues.SelectedItem
        if _sel is None or not hasattr(_sel, 'Row'):
            from dialogs.dialogs_styles_loader import show_alert
            show_alert(u"Dupliquer",
                       u"Sélectionnez d'abord la vue personnalisée à "
                       u"dupliquer.", close_label=u"Retour")
            return
        ctx['ctx_item'][0] = _sel
        ctx['dupliquer'](sender, e)
        _maj_derivees()
        _appliquer_filtre()

    def _maj_dupliquer(sender=None, args=None):
        _sel = wpf.dgTypesVues.SelectedItem
        wpf.btnTvpDupliquer.IsEnabled = (_sel is not None
                                         and hasattr(_sel, 'Row'))

    def _aide(sender, e):
        _xaml = os.path.join(os.path.dirname(__file__), 'AideVuesDialog.xaml')
        _dlg = forms.WPFWindow(_xaml)
        try:
            _dlg.Owner = wpf
        except Exception:
            pass
        _dlg.btnClose.Click += lambda s, e2: setattr(_dlg, 'DialogResult', True)
        _dlg.show_dialog()

    wpf.btnTvpDupliquer.Click += _dupliquer_bouton
    wpf.dgTypesVues.SelectionChanged += _maj_dupliquer
    wpf.btnTvpAide.Click += _aide
    _maj_dupliquer()

    return {'maj_derivees': _maj_derivees,
            'appliquer_filtre': _appliquer_filtre,
            # Appele par l'appelant quand il doit AMENER une ligne sous les
            # yeux : un filtre actif la rendrait sinon introuvable.
            'reset_filtres': lambda: _reset_filtres(None, None)}


# ---------------------------------------------------------------------------
# « Options de vues » d'un profil de liaison CAO
# ---------------------------------------------------------------------------
# Ce dialogue enregistre exactement les cinq reglages du groupe « Vues » de
# « Lier CAO → Vues », dans le meme ordre de cascade et avec les memes regles de
# disponibilite : Famille -> Discipline -> Type personnalise -> Phase, puis
# « Une vue par niveau ». Un profil ne doit pas pouvoir retenir une combinaison
# que le script refuserait ensuite de proposer.
#
# Rien n'est ecrit en dur : les familles viennent de `nommage_vues`, les
# disciplines du referentiel, les types des tables de disponibilite. La version
# precedente figeait quatre libelles de familles, qui ne correspondaient deja
# plus a ceux de la configuration.
#
# AU NIVEAU MODULE, et non dans main() : celle-ci est deja saturee (voir
# _init_disciplines pour le meme motif). Y loger ces fonctions imbriquees
# declenche « SystemError: Sequence contains no elements » a la compilation
# paresseuse d'un scope sans rapport, des l'ouverture de la fenetre.
_PROFIL_AUCUNE_VALEUR = u"< Aucune valeur disponible >"


def _profil_vues_valeur(cmb):
    """SelectedItem du menu, ou None s'il ne porte que le marqueur vide."""
    _v = cmb.SelectedItem
    return None if (_v is None or _v == _PROFIL_AUCUNE_VALEUR) else _v


def _profil_vues_familles(cfg):
    """[(label, vue_id)] des familles cochees « Lier CAO → Vues »."""
    _out = []
    for _nv in (cfg.get(u'conventions_nommage') or {}).get(u'nommage_vues', []):
        if _nv.get(u'vues_et_dwg', False):
            _out.append((_nv.get(u'label', u''), _nv.get(u'id', u'')))
    return _out


def _profil_vues_phases():
    """Noms des phases du projet courant, ou [] hors document."""
    try:
        from pyrevit import revit as _revit_ph
        from Autodesk.Revit.DB import Element as _ElemPh
        return [_ElemPh.Name.__get__(_ph) for _ph in _revit_ph.doc.Phases]
    except Exception:
        # Les parametres doivent rester ouvrables meme sans projet charge.
        return []


def _profil_vues_remplir(cfg, dlg, vues_p):
    """
    Pre-remplit le dialogue depuis l'entree `vues` d'un profil.

    Retourne la table (code_ouvrage, libelle) des disciplines telle
    qu'affichee : _profil_vues_lire en a besoin pour retrouver le code depuis
    l'index selectionne.
    """
    from utils.types_vues_personnalises import (
        get_types_vues as _get_tvp2,
        filtrer_labels_pour_famille as _filtre_fam,
        filtrer_labels_pour_discipline as _filtre_disc,
        get_dispo_disciplines as _get_dispo_disc,
        is_type_dispo_pour_discipline as _est_dispo_disc,
    )
    from utils.disciplines import get_disciplines_et_sous as _get_disc

    _familles = _profil_vues_familles(cfg)
    _disc_toutes = _get_disc(cfg)
    _phases = _profil_vues_phases()
    # Disponibilite par SCRIPT (colonne « Lier CAO → Vues »), premier tamis,
    # exactement comme dans le script appelant.
    _dispo_script = dict((_d.get(u'label', u''), _d.get(u'lier_cao', True))
                         for _d in cfg.get(u'dispo_types_pers_lier_cao', []))
    _tvp_labels = [_t.get(u'label', u'') for _t in _get_tvp2(cfg)
                   if _dispo_script.get(_t.get(u'label', u''), True)]
    # Etat partage entre les handlers : liste (code, libelle) en cours.
    _disc_opts = []
    _garde = {u'v': False}

    def _labels_famille():
        _lbl = dlg.cmbFamille.SelectedItem or u''
        _vid = dict(_familles).get(_lbl, u'')
        return _filtre_fam(cfg, _tvp_labels, _vid)

    def _maj_disc():
        _labels_fam = _labels_famille()
        _dd = _get_dispo_disc(cfg)
        _opts = []
        if _labels_fam:
            for _code, _lbl in _disc_toutes:
                for _l in _labels_fam:
                    if _est_dispo_disc(cfg, _l, _code, _dispo=_dd):
                        _opts.append((_code, _lbl))
                        break
        _idx = dlg.cmbDiscipline.SelectedIndex
        _prec = (_disc_opts[_idx][0] if 0 <= _idx < len(_disc_opts) else u'')
        _disc_opts[:] = _opts
        if _opts:
            dlg.cmbDiscipline.ItemsSource = [_l for _c, _l in _opts]
            _codes = [_c for _c, _l in _opts]
            dlg.cmbDiscipline.SelectedIndex = (
                _codes.index(_prec) if _prec in _codes else -1)
        else:
            dlg.cmbDiscipline.ItemsSource   = [_PROFIL_AUCUNE_VALEUR]
            dlg.cmbDiscipline.SelectedIndex = 0
        dlg.cmbDiscipline.IsEnabled = bool(_opts)

    def _maj_types(sender=None, args=None):
        if _garde[u'v']:
            return
        _idx = dlg.cmbDiscipline.SelectedIndex
        _code = (_disc_opts[_idx][0] if 0 <= _idx < len(_disc_opts) else u'')
        _prec = _profil_vues_valeur(dlg.cmbTypePerso)
        _dispo = _filtre_disc(cfg, _labels_famille(), _code) if _code else []
        if _dispo:
            dlg.cmbTypePerso.ItemsSource = _dispo
            dlg.cmbTypePerso.SelectedIndex = (
                _dispo.index(_prec) if _prec in _dispo else 0)
        else:
            dlg.cmbTypePerso.ItemsSource   = [_PROFIL_AUCUNE_VALEUR]
            dlg.cmbTypePerso.SelectedIndex = 0
        dlg.cmbTypePerso.IsEnabled = bool(_dispo)
        dlg.cmbTypePerso.ToolTip = (
            None if _dispo
            else u"Choisissez d'abord une discipline." if not _code
            else u"Aucun type personnalis\xe9 ne correspond \xe0 cette "
                 u"combinaison (01_Param\xe8tres > Vues > Vues "
                 u"personnalis\xe9es).")
        _maj_phase()

    def _maj_phase(sender=None, args=None):
        if _garde[u'v']:
            return
        _amont = all(_profil_vues_valeur(_c) is not None
                     for _c in (dlg.cmbFamille, dlg.cmbDiscipline,
                                dlg.cmbTypePerso))
        _prec = _profil_vues_valeur(dlg.cmbPhase)
        if _amont and _phases:
            dlg.cmbPhase.ItemsSource = _phases
            dlg.cmbPhase.SelectedIndex = (
                _phases.index(_prec) if _prec in _phases else len(_phases) - 1)
            dlg.cmbPhase.IsEnabled = True
            dlg.cmbPhase.ToolTip   = None
        else:
            dlg.cmbPhase.ItemsSource   = [_PROFIL_AUCUNE_VALEUR]
            dlg.cmbPhase.SelectedIndex = 0
            dlg.cmbPhase.IsEnabled     = False
            dlg.cmbPhase.ToolTip = (
                u"Aucune phase dans le projet courant." if not _phases
                else u"Renseignez d'abord la famille de vue, la discipline "
                     u"et le type personnalis\xe9.")

    def _maj_cascade(sender=None, args=None):
        if _garde[u'v']:
            return
        _garde[u'v'] = True
        try:
            _maj_disc()
        finally:
            _garde[u'v'] = False
        _maj_types()

    dlg.cmbFamille.SelectionChanged    += _maj_cascade
    dlg.cmbDiscipline.SelectionChanged += _maj_types

    # Remplissage initial, puis rappel du profil dans l'ordre de la cascade.
    _fam_labels = [_l for _l, _v in _familles]
    dlg.cmbFamille.ItemsSource = _fam_labels
    _fam_cur = vues_p.get(u'famille', u'')
    dlg.cmbFamille.SelectedIndex = (
        _fam_labels.index(_fam_cur) if _fam_cur in _fam_labels
        else (0 if _fam_labels else -1))
    _maj_cascade()

    _dc = vues_p.get(u'discipline', u'')
    if _dc:
        _codes = [_c for _c, _l in _disc_opts]
        if _dc in _codes:
            dlg.cmbDiscipline.SelectedIndex = _codes.index(_dc)
    _tp = vues_p.get(u'type_personnalise', u'')
    _tp_items = list(dlg.cmbTypePerso.ItemsSource or [])
    if _tp in _tp_items:
        dlg.cmbTypePerso.SelectedIndex = _tp_items.index(_tp)
    _ph = vues_p.get(u'phase', u'')
    _ph_items = list(dlg.cmbPhase.ItemsSource or [])
    if _ph and _ph in _ph_items:
        dlg.cmbPhase.SelectedIndex = _ph_items.index(_ph)
    dlg.chkVueParNiveau.IsChecked = bool(vues_p.get(u'vue_par_niveau', True))

    return _disc_opts


def _profil_vues_lire(dlg, _opts):
    """Entree `vues` du profil, depuis le dialogue valide."""
    _idx = dlg.cmbDiscipline.SelectedIndex
    # Code ouvrage et non libelle : un renommage dans le referentiel ne doit pas
    # invalider les profils.
    _code = (_opts[_idx][0] if 0 <= _idx < len(_opts) else u'')
    _fam = _profil_vues_valeur(dlg.cmbFamille)
    _tp  = _profil_vues_valeur(dlg.cmbTypePerso)
    _ph  = _profil_vues_valeur(dlg.cmbPhase)
    return {
        u'famille':           unicode(_fam) if _fam is not None else u'',
        u'discipline':        _code,
        u'type_personnalise': unicode(_tp) if _tp is not None else u'',
        u'phase':             unicode(_ph) if _ph is not None else u'',
        u'vue_par_niveau':    bool(dlg.chkVueParNiveau.IsChecked),
    }


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
    # `discipline` porte un CODE OUVRAGE, `phase` un NOM de phase de projet.
    # Vides par defaut : aucune valeur n'a de sens tant que l'utilisateur n'a
    # pas ouvert « Configurer... ». Un profil ecrit avant l'ajout de ces deux
    # cles se comporte donc comme un profil neuf sur ces deux points — c'est
    # « Lier CAO → Vues » qui demandera de choisir.
    _DEFAULT_PROFIL_VUES = {
        u'famille': u"Plan d'etage", u'discipline': u'',
        u'type_personnalise': u'FM', u'phase': u'',
        u'vue_par_niveau': True,
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
    # Table de style (nomenclature de clés) exploitée par 13_SURF_Styles.
    # « Commentaires » est le nom français du paramètre natif de commentaire
    # d'occurrence : c'est le défaut, mais la colonne reste configurable, un
    # projet pouvant réserver ce paramètre à un autre usage.
    set_txt(wpf, 'sf_table_styles',          sf.get('table_styles_schedule', ''))
    set_txt(wpf, 'sf_param_style',           sf.get('param_style', ''))
    set_txt(wpf, 'sf_col_calcul_style',      sf.get('col_calcul_style', ''))
    set_txt(wpf, 'sf_col_commentaire_style', sf.get('col_commentaire_style', u'Commentaires'))
    set_txt(wpf, 'sf_param_shon',      sf.get('param_shon', ''))
    set_txt(wpf, 'sf_param_shob',      sf.get('param_shob', ''))
    set_txt(wpf, 'sf_param_s_plancher',sf.get('param_s_plancher', ''))
    # Auteur des calculs de surfaces (cf. 02_SURF_SP-SHON-SHOB). Laissés vides
    # tant que l'utilisateur n'a pas déclaré les paramètres partagés
    # correspondants : la traçabilité est alors simplement inactive.
    set_txt(wpf, 'sf_param_shon_auteur',       sf.get('param_shon_auteur', ''))
    set_txt(wpf, 'sf_param_shob_auteur',       sf.get('param_shob_auteur', ''))
    set_txt(wpf, 'sf_param_s_plancher_auteur', sf.get('param_s_plancher_auteur', ''))
    # Qualifications proposées dans la liste déroulante de l'auteur : une par
    # ligne dans la zone de saisie, une liste de chaînes dans config.json.
    set_txt(wpf, 'sf_qualifications',
            u'\r\n'.join(sf.get('qualifications_auteur',
                                QUALIFICATIONS_AUTEUR_DEFAUT)))
    set_txt(wpf, 'sf_col_shon',        sf.get('col_shon', ''))
    set_txt(wpf, 'sf_col_shob',        sf.get('col_shob', ''))
    set_txt(wpf, 'sf_col_plancher',    sf.get('col_plancher', ''))
    set_txt(wpf, 'sf_col_filter',      sf.get('col_filter', ''))
    set_txt(wpf, 'sf_default_shon',    sf.get('default_shon_schedule', ''))
    set_txt(wpf, 'sf_default_plancher',sf.get('default_plancher_schedule', ''))

    # ── Référentiel des styles de surfaces ───────────────────────────────────
    # Liste ORDONNÉE : la position dans la liste EST l'ordre d'affichage des
    # boutons. Chaque entrée : {'nom': <clé de style>, 'couleur': '#RRGGBB'}.
    #
    # Volontairement dans config.json et non dans la nomenclature Revit : des
    # milliers de projets existants n'ont pas de colonne d'ordre, et leur en
    # ajouter une serait irréaliste. L'identification se fait donc sur le seul
    # NOM DE CLÉ, ce qui rend un réglage valable pour tous les projets suivant
    # la même convention de nommage.
    # Deux couleurs par style, deux usages distincts :
    #   'couleur'      -> bande du bouton dans la palette (codage sémantique) ;
    #   'couleur_plan' -> choix de couleurs Revit (lisibilité en plan).
    # Les confondre donnerait des plans à trois couleurs, toutes les déductions
    # se ressemblant.
    _styles_ordre = []
    for _e in sf.get('styles_palette', []) or []:
        _nom_st = (_e.get('nom') or u'').strip() if isinstance(_e, dict) else u''
        if _nom_st:
            _styles_ordre.append({
                u'nom':          _nom_st,
                u'couleur':      (_e.get('couleur') or u'').strip(),
                u'couleur_plan': (_e.get('couleur_plan') or u'').strip(),
                # Motif enregistre par NOM : un identifiant n'a de sens que dans
                # un projet, le referentiel doit valoir pour tous.
                u'motif_plan':   (_e.get('motif_plan') or u'').strip(),
            })

    # Mappage « type de calcul -> étiquette », consommé par la palette
    # « Surfaces ». Il n'a pas de bouton propre dans cet onglet : il se règle
    # depuis le référentiel des styles, qui porte aussi son export et son
    # import. L'interrupteur marche/arrêt, lui, vit dans la palette — la
    # décision d'étiqueter se prend au moment de travailler.
    _etiquettes = [_etiquettes_depuis_config(sf)]

    def _open_styles_ordre(sender, args):
        _resultat = _dialogue_ordre_styles(
            wpf,
            _styles_ordre,
            _etiquettes[0],
            txt(wpf, 'sf_table_styles'),
            txt(wpf, 'sf_col_calcul_style'))
        if _resultat is not None:
            _ordre, _etiq = _resultat
            del _styles_ordre[:]
            _styles_ordre.extend(_ordre)
            _etiquettes[0] = _etiq

    wpf.btnStylesOrdre.Click += _open_styles_ordre

    # ── Disciplines ──────────────────────────────────────────────────────────
    # Tout l'onglet vit dans _init_disciplines (fonction de module) : voir
    # sa docstring pour la raison, qui tient a IronPython et non au decoupage.
    _disc_api = _init_disciplines(wpf, cfg)
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
         'systeme': True, 'template': '{site}_{construction}_{niveau-code}_{demi-niv}_{producteur}_{specialite}_{nom-site-court}_{rest-nom}'},
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
    # « Ord. » est du TEXTE : un classement peut vouloir « A1 », « B-02 » ou
    # « 10bis ». Le tri passe donc par `ordre_cle`, clé naturelle calculée
    # (voir _tvp_cle_ordre) — sans elle, « 10 » se rangerait avant « 2 ».
    _dt_tvp.Columns.Add('ordre')
    _dt_tvp.Columns.Add('label')
    _dt_tvp.Columns.Add('titre')
    _dt_tvp.Columns.Add('valeur_1')
    _dt_tvp.Columns.Add('valeur_2')
    _dt_tvp.Columns.Add('usage')
    _dt_tvp.Columns.Add('systeme')
    _dt_tvp.Columns.Add('ordre_cle')
    # Label de la ligne AVANT la derniere edition validee. Les six tables
    # satellites s'indexent sur le Label : sans memoire de l'ancien, renommer
    # une ligne rendait tous ses reglages introuvables — familles, disciplines,
    # types, gabarits, types de niveaux et disponibilite repartaient a leur
    # valeur par defaut, exactement comme si la ligne venait d'etre creee.
    # Une colonne et non un dict {DataRow: label} : elle suit la ligne partout,
    # y compris a travers un rechargement complet de la table.
    _dt_tvp.Columns.Add('label_prec')
    # Porte le RowFilter de la vue : filtrer par une expression constante
    # plutôt que par un RowFilter construit depuis la saisie évite d'avoir à
    # échapper les caractères réservés d'ADO.NET. Même mécanique que la table
    # des disciplines.
    _dt_tvp.Columns.Add('visible', _SysBool)
    # Colonnes DERIVEES, jamais affichées : elles portent, en texte, ce que
    # chaque bouton « Configurer… » a réglé. Sans elles, ces colonnes-là
    # n'auraient aucune valeur à donner à la recherche ni au filtre d'en-tête
    # — un bouton n'a pas de contenu à filtrer.
    for _c_der in ('f_familles', 'f_discipline', 'f_types', 'f_gabarits',
                   'f_niveaux', 'f_dispo'):
        _dt_tvp.Columns.Add(_c_der)

    # Majuscules AVANT tout chargement : la grille et les six tables
    # satellites lisent cfg chacune de leur cote, et elles s'indexent sur le
    # meme Label. Le normaliser ici, une fois, les garde alignees ; le faire
    # a sept endroits finirait par en oublier un et romprait le lien.
    _tvp_normaliser_cfg(cfg)

    # Les lignes SYSTEME et tout ce qui les decrit sont des constantes de
    # MODULE (_TVP_LABEL_PIECES_3D, _TVP_LOCKED_ORDER, _TVP_LOCKED_ORDRE,
    # _LOCKED_TVP_LABELS, _TVP_LOCKED_USAGE) : voir leur bloc la-haut.
    def _tvp_sort_key(t):
        _lbl = t.get(u'label', u'')
        if _lbl in _TVP_LOCKED_ORDRE:
            # Les lignes systeme passent avant tout : prefixe '0'.
            return (0, _tvp_cle_ordre(_TVP_LOCKED_ORDRE[_lbl]))
        return (1, _tvp_cle_ordre(t.get(u'ordre', u'')))
    # Prochain ordre disponible pour les lignes utilisateur (Ord. systeme
    # partant de 0, le premier ordre libre est len(_TVP_LOCKED_ORDER))
    _tvp_auto_ord = [len(_TVP_LOCKED_ORDER)]

    # Garantir la presence des lignes systeme : une config anterieure (ou dont
    # la ligne a ete supprimee avant qu'elle ne devienne systeme) la retrouve
    # ici, plutot que de laisser un outil sans type personnalise a designer.
    _tvp_charges  = list(_get_tvp(cfg))
    _labels_pres  = set(_t.get(u'label', u'') for _t in _tvp_charges)
    for _lbl_sys in _TVP_LOCKED_ORDER:
        if _lbl_sys not in _labels_pres:
            _tvp_charges.append({
                u'label': _lbl_sys, u'titre': _lbl_sys,
                u'valeur_1': u'', u'valeur_2': u'',
                u'usage': _TVP_LOCKED_USAGE.get(_lbl_sys, u'Temporaire'),
                u'systeme': True,
            })

    for _tvp in sorted(_tvp_charges, key=_tvp_sort_key):
        _r = _dt_tvp.NewRow()
        _lbl_tvp = _tvp.get('label', '')
        _est_sys = _lbl_tvp in _TVP_LOCKED_ORDRE
        _ord_tvp = _TVP_LOCKED_ORDRE.get(_lbl_tvp, _tvp.get('ordre', None))
        if _ord_tvp in (None, u'', ''):
            _ord_tvp = _tvp_auto_ord[0]
        # « Ord. » est libre : il peut ne porter aucun chiffre. Le compteur
        # d'ordres auto ne se cale donc que sur les valeurs qui en ont un.
        _ord_num = _int_or(_ord_tvp, None)
        if _ord_num is not None:
            _tvp_auto_ord[0] = max(_tvp_auto_ord[0], _ord_num) + 1
        _usage_tvp = _tvp.get('usage', 'Temporaire')
        # La colonne Usage est verrouillee sur les lignes systeme : leur usage
        # vient donc du code (_TVP_LOCKED_USAGE) et non de config.json, sans
        # quoi une valeur vide ou erronee du fichier y resterait definitive.
        if _est_sys:
            _usage_tvp = _TVP_LOCKED_USAGE.get(_lbl_tvp, _usage_tvp)
        _r['ordre']     = unicode(_ord_tvp)
        _r['ordre_cle'] = _tvp_cle_ordre(_ord_tvp)
        _r['label']    = _lbl_tvp
        _r['label_prec'] = _lbl_tvp
        _r['titre']    = _tvp.get('titre',    _tvp.get('nom', ''))  # compat
        _r['valeur_1'] = _tvp.get('valeur_1', '')
        _r['valeur_2'] = _tvp.get('valeur_2', '')
        _r['usage']    = _usage_tvp
        _r['systeme']  = bool(_tvp.get('systeme', False)) or _est_sys
        _r['visible']  = True
        _dt_tvp.Rows.Add(_r)
    _TVP_TRI_DEFAUT = 'ordre_cle ASC'
    _dt_tvp.DefaultView.Sort = _TVP_TRI_DEFAUT
    _dt_tvp.DefaultView.RowFilter = 'visible = true'
    wpf.dgTypesVues.ItemsSource = _dt_tvp.DefaultView

    # Dicts disponibilite types personnalises — colonne "Disponibilité" de la
    # table "Vues personnalisées" (bouton par ligne, _open_dispo_scripts_dialog)
    # _dispo_types_pers    : True = disponible dans "Lier CAO → Vues"
    # _dispo_types_pers_vp : True = disponible dans "Vues +"
    # _dispo_types_pers_p3d: True = type utilisé pour les vues "Pièces 3D"
    #                        (un seul label peut être à True à la fois)
    # Les nomenclatures ne sont plus concernees : elles ont leur propre table
    # (onglet "Nomenclatures"), les types de vue personnalises n'entrent plus
    # dans leur creation. L'ancienne cle 'nomenclatures' des entrees existantes
    # de config.json est simplement ignoree, puis supprimee a l'enregistrement.
    _dispo_types_pers    = {}
    _dispo_types_pers_vp = {}
    _dispo_types_pers_p3d = {}
    for _d in cfg.get(u'dispo_types_pers_lier_cao', []):
        _lbl_d = _d.get(u'label', u'')
        # La ligne systeme "PIECES 3D" a une disponibilite figee : elle sert
        # uniquement a 05_Pieces > Pièces 3D. On assainit ici plutot que dans
        # le dialogue, pour que l'invariant tienne meme si l'utilisateur
        # n'ouvre jamais la colonne "Disponibilité" (ancienne config, ou
        # fichier edite a la main).
        _est_p3d_d = (_lbl_d == _TVP_LABEL_PIECES_3D)
        _dispo_types_pers[_lbl_d]     = (not _est_p3d_d) and bool(_d.get(u'lier_cao',  True))
        _dispo_types_pers_vp[_lbl_d]  = (not _est_p3d_d) and bool(_d.get(u'vues_plus', True))
        _dispo_types_pers_p3d[_lbl_d] = _est_p3d_d

    # Familles de vues : {label: {vue_id: bool}} — colonne "Familles de vues"
    # de la table "Vues personnalisées" (_open_familles_vues_dialog).
    # Axe INDEPENDANT de la disponibilite par script ci-dessus : celle-ci dit
    # dans quel OUTIL le type est propose, celle-la sur quelles FAMILLES DE
    # VUES il s'applique. Un type n'est propose que si les deux l'autorisent.
    # Toute combinaison absente vaut True : une config.json anterieure a cette
    # table (cle absente) conserve exactement le comportement d'avant.
    _dispo_types_pers_fam = {}
    for _df in cfg.get(u'dispo_types_pers_familles', []) or []:
        _lbl_df = _df.get(u'label', u'')
        if not _lbl_df:
            continue
        _dispo_types_pers_fam[_lbl_df] = dict(
            (_k, bool(_v)) for _k, _v in (_df.get(u'familles', {}) or {}).items())

    # Disciplines : {label: {code_ouvrage: bool}} — colonne "Discipline" de
    # la table "Vues personnalisées" (_open_discipline_dialog). Meme
    # convention que les familles : axe independant et cumulatif, absent =
    # actif. La cle est le code_ouvrage d'une ligne de l'onglet Disciplines,
    # pas son libelle affiche.
    _dispo_types_pers_disc = {}
    for _dd in cfg.get(u'dispo_types_pers_disciplines', []) or []:
        _lbl_dd = _dd.get(u'label', u'')
        if not _lbl_dd:
            continue
        _dispo_types_pers_disc[_lbl_dd] = dict(
            (_k, bool(_v)) for _k, _v in (_dd.get(u'disciplines', {}) or {}).items())

    # Types de niveaux coches par defaut, PAR vue personnalisee :
    # {label: {cle_definition: bool}} — colonne "Types de niveaux par défaut".
    # Remplace l'ancien reglage global vues_en_masse.filtres_types_niveaux_defaut,
    # qui reste ecrit dans config.json et sert de valeur de reprise pour les
    # labels pas encore configures (migration transparente : au premier
    # enregistrement, chaque label herite du reglage global d'avant).
    _niveaux_defaut_pers = {}
    for _dn in cfg.get(u'niveaux_defaut_types_pers', []) or []:
        _lbl_dn = _dn.get(u'label', u'')
        if not _lbl_dn:
            continue
        _niveaux_defaut_pers[_lbl_dn] = dict(
            (_k, bool(_v)) for _k, _v in (_dn.get(u'niveaux', {}) or {}).items())

    def _is_sys_tvp(item):
        return hasattr(item, 'Row') and str(item['label'] or u'') in _LOCKED_TVP_LABELS

    def _on_beginning_edit_tvp(s, e):
        # Ord.(0) et Label(1) et Usage(5) non éditables pour les lignes système
        # Colonnes : 0=Ord. 1=Label 2=Titre 3=Valeur-1 4=Valeur-2 5=Usage
        #            6=Familles 7=Types 8=Gabarits 9=Disponibilité (boutons)
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
        """
        Prochain « Ord. » proposé, en texte.

        La colonne accepte n'importe quoi : seules les valeurs NUMÉRIQUES
        entrent dans le calcul, une ligne classée « A1 » ne devant pas
        empêcher de proposer un numéro à la suivante.
        """
        _vals = [_v for _v in (_int_or(_row['ordre'], None)
                               for _row in _tvp_lignes(_dt_tvp))
                 if _v is not None]
        return unicode((max(_vals) + 1) if _vals else 3)

    def _tvp_poser_ordre(row, valeur):
        """Écrit « Ord. » et sa clé de tri d'un seul geste : les laisser se
        désynchroniser rangerait la ligne au mauvais endroit."""
        row['ordre']     = unicode(valeur)
        row['ordre_cle'] = _tvp_cle_ordre(valeur)

    def _tvp_nouvelle(sender, e):
        _r = _dt_tvp.NewRow()
        _tvp_poser_ordre(_r, _tvp_next_ordre())
        _r['label']    = u''
        # Label précédent VIDE : c'est ce qui marque une ligne créée de zéro,
        # et c'est à ce signe que _tvp_renommer_stores lui applique les
        # valeurs par défaut des types de vues quand son Label est saisi.
        _r['label_prec'] = u''
        _r['titre']    = u''
        _r['valeur_1'] = u''
        _r['valeur_2'] = u''
        _r['usage']    = u'Temporaire'
        _r['systeme']  = False
        _r['visible']  = True
        _dt_tvp.Rows.Add(_r)

    def _tvp_dupliquer(sender, e):
        _sel = _tvp_ctx_item[0]
        if _sel is None or not hasattr(_sel, 'Row'):
            return
        _base     = str(_sel['label']) if _sel['label'] is not None else u''
        # _tvp_lignes(_dt_tvp) et non DefaultView : un label masqué par un filtre
        # reste pris, la copie prendrait sinon un nom déjà utilisé.
        _existing = {str(_row['label']) for _row in _tvp_lignes(_dt_tvp)
                     if _row['label'] is not None}
        _idx = 2
        while True:
            _new_lbl = _tvp_maj_label(u'{}_{}'.format(_base, _idx))
            if _new_lbl not in _existing:
                break
            _idx += 1
        _r = _dt_tvp.NewRow()
        _tvp_poser_ordre(_r, _tvp_next_ordre())
        _r['label']    = _new_lbl
        # La copie porte déjà son Label : elle n'est PAS une ligne neuve au
        # sens des valeurs par défaut, et garde les réglages copiés ci-dessous.
        _r['label_prec'] = _new_lbl
        _r['titre']    = _tvp_maj_titre(_sel['titre'])
        _r['valeur_1'] = str(_sel['valeur_1']) if _sel['valeur_1'] is not None else u''
        _r['valeur_2'] = str(_sel['valeur_2']) if _sel['valeur_2'] is not None else u''
        _r['usage']    = str(_sel['usage'])    if _sel['usage']    is not None else u'Temporaire'
        _r['systeme']  = False
        _r['visible']  = True
        _dt_tvp.Rows.Add(_r)
        # Dupliquer une vue, c'est aussi dupliquer ses réglages : sans cela la
        # copie repartirait vide et « Dupliquer » ne ferait gagner que la
        # saisie de quatre champs.
        for _store in (_types_vues_store, _gabarits_store,
                       _dispo_types_pers_fam, _dispo_types_pers_disc,
                       _niveaux_defaut_pers):
            if _base in _store:
                _store[_new_lbl] = dict(_store[_base])
        if _base in _dispo_types_pers:
            _dispo_types_pers[_new_lbl] = _dispo_types_pers[_base]
        if _base in _dispo_types_pers_vp:
            _dispo_types_pers_vp[_new_lbl] = _dispo_types_pers_vp[_base]

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

    # Valeurs PAR DEFAUT de la colonne « Types de vues » : {vue_id: valeur}.
    # Deux usages, un seul referentiel : toute vue personnalisee creee par
    # « + Ajouter » en herite, et chaque ligne du dialogue peut le rappeler
    # ensuite (boutons « Défauts » / « Tout aux valeurs par défaut »).
    # Une DUPLICATION n'y touche pas : elle copie la ligne source, c'est tout
    # son interet.
    # Dans une liste : les callbacks des dialogues le remplacent en bloc, et
    # IronPython 2.7 n'a pas de `nonlocal`.
    _types_vues_defaut = [dict(cfg.get(u'types_vues_defaut', {}) or {})]

    _gabarits_store = {}
    for _gab in cfg.get('gabarits_vues', []):
        _gabarits_store[_gab.get('label', '')] = dict(_gab.get('gabarits', {}))

    # Migration : ancienne valeur unique "Gabarit de vue 3D" (avant l'entrée
    # 'vue-3d' par type personnalisé dans la table "Gabarits de vues") —
    # préremplit l'entrée 'vue-3d' de chaque label non encore configuré.
    _legacy_gabarit_vue_3d = (cfg.get('pieces_3d', {}) or {}).get('gabarit_vue_3d', u'')
    if _legacy_gabarit_vue_3d:
        for _row_gab in _dt_tvp.Rows:
            _lbl_gab = str(_row_gab['label']) if _row_gab['label'] is not None else u''
            if not _lbl_gab:
                continue
            _gabarits_store.setdefault(_lbl_gab, {})
            if not _gabarits_store[_lbl_gab].get('vue-3d'):
                _gabarits_store[_lbl_gab]['vue-3d'] = _legacy_gabarit_vue_3d

    # ── Helpers communs aux deux dialogues dynamiques ─────────────────────────
    def _get_vue_noms_from_grid():
        """
        Lit la liste (label, vue_id, col_key) depuis dgNommageVues.

        "Nomenclature" en est exclue : les nomenclatures ne se declinent pas
        par type de vue personnalise et disposent de leur propre table
        (onglet "Nomenclatures"), qui porte deja le type de vue Revit a
        appliquer. Elle n'a donc pas a apparaitre comme colonne dans les
        dialogues "Types de vues" et "Gabarits de vues".
        """
        # La grille "Nommage des vues" est peuplee PLUS BAS dans main() : tout
        # appel anterieur trouverait ItemsSource a None. Rendre une liste vide
        # plutot que de lever — l'appelant affiche alors « aucune famille »,
        # ce qui reste juste tant que la table n'est pas chargee.
        _src_v = wpf.dgNommageVues.ItemsSource
        if _src_v is None:
            return []
        _result = []
        for _r in _src_v:
            _lbl_v = str(_r['label']) if _r['label'] is not None else ''
            _vid_v = str(_r['id'])    if _r['id']    is not None else ''
            if _vid_v == u'vue-nomenclature':
                continue
            if _lbl_v or _vid_v:
                _key_v = 'col_' + _vid_v.replace('-', '_').replace(' ', '_')
                _result.append((_lbl_v, _vid_v, _key_v))
        return _result

    def _vue_id_pieces_3d():
        """
        Identifiant de la famille de vue designee comme "Pièces 3D" dans la
        table "Nommage des vues" (bouton "Disponibilite...", colonne du meme
        nom) — en pratique 'vue-3d'.

        Lu dans la GRILLE et non dans cfg : la table a pu etre modifiee depuis
        l'ouverture des Parametres, sans enregistrement intermediaire.
        Jamais code en dur ailleurs : c'est cette designation qui fait foi,
        pour que la ligne systeme "PIECES 3D" suive automatiquement si la
        famille designee change un jour.

        Repli sur 'vue-3d' si aucune ligne n'est designee — ou si la grille
        n'est pas encore peuplee (elle l'est plus bas dans main()).
        """
        _src_p3 = wpf.dgNommageVues.ItemsSource
        if _src_p3 is None:
            return u'vue-3d'
        for _r in _src_p3:
            _p3 = _r['pieces_3d']
            if _p3 is not None and bool(_p3):
                _vid3 = str(_r['id']) if _r['id'] is not None else u''
                if _vid3:
                    return _vid3
        return u'vue-3d'

    def _familles_actives(tvp_label):
        """
        Ensemble des vue_id sur lesquels la vue personnalisee `tvp_label` est
        active, tel que regle dans la colonne "Familles de vues".

        Source unique de verite pour les trois colonnes qui en dependent :
        "Familles de vues" (ce qu'elle affiche), "Types de vues" et "Gabarits
        de vues" (quelles colonnes y sont modifiables). Renseigner un type ou
        un gabarit pour une famille desactivee n'aurait aucun effet — aucun
        script ne le lirait.

        Non renseigne = actif : la table dispo_types_pers_familles est
        purement restrictive (une config anterieure ouvre donc tout).
        La ligne systeme "PIECES 3D" est forcee sur la seule famille designee
        "Pièces 3D", quel que soit le contenu de la config.
        """
        if tvp_label == _TVP_LABEL_PIECES_3D:
            return set([_vue_id_pieces_3d()])
        _cur_fa = _dispo_types_pers_fam.get(tvp_label, {})
        return set(_iv for _lv, _iv, _kv in _get_vue_noms_from_grid()
                   if _cur_fa.get(_iv, True))

    def _disciplines_actives(tvp_label):
        """
        Ensemble des code_ouvrage (disciplines) sur lesquels la vue
        personnalisée `tvp_label` est active, tel que réglé dans la colonne
        « Discipline ». Non renseigné = actif, même convention que
        _familles_actives — pas de ligne verrouillée ici, un type système
        (FM, TEMPORAIRE, PIECES 3D) n'est pas propre à une discipline.
        """
        _cur_da = _dispo_types_pers_disc.get(tvp_label, {})
        return set(_code for _code, _lbl in _disc_api['items_disciplines']()
                   if _cur_da.get(_code, True))

    def _open_valeurs_par_famille(xaml_name, store, tvp_label, titre, selecteur,
                                  defauts=None, ouvrir_defauts=None):
        """
        Dialogue « une valeur par famille de vues » pour UNE ligne de la table
        "Vues personnalisées" : libellé, valeur saisissable, bouton de
        sélection dans le projet, bouton d'effacement.

        Sert aux colonnes "Types de vues" et "Gabarits de vues", qui ne
        diffèrent que par leur XAML (texte d'aide) et par le sélecteur ouvert
        derrière « Choisir… ».

        xaml_name : XAML exposant pnlLignes, txtNoteFamilles, btnOK, btnCancel
        store     : dict mutable {label: {vue_id: valeur}}
        tvp_label : label de la ligne éditée
        titre     : titre de la fenêtre (le label y est ajouté)
        selecteur : fonction (vue_label, vue_id, valeur_courante) → nom choisi,
                    ou None si l'utilisateur annule (valeur laissée en l'état).
        defauts   : {vue_id: valeur} rappelable par un bouton « Défauts » sur
                    chaque ligne, et en bloc par « Tout aux valeurs par
                    défaut ». None = pas de valeurs par défaut pour cette
                    colonne : la colonne de boutons et la barre du haut
                    disparaissent (cas des Gabarits, et du dialogue qui règle
                    justement ces défauts — il n'a rien au-dessus de lui).
        ouvrir_defauts : callback sans argument ouvrant l'éditeur des valeurs
                    par défaut. Appelé par « Réglages par défaut… ».

        Les familles inactives (colonne "Familles de vues") sont affichées mais
        verrouillées, et leur valeur CONSERVÉE : réactiver la famille la rend
        de nouveau modifiable sans rien avoir perdu.

        La saisie manuelle reste possible à côté du sélecteur : elle permet de
        préparer une configuration pour un élément qui n'existe pas encore dans
        le projet ouvert.
        """
        from System.Windows.Controls import (TextBox as _TxtBox, TextBlock as _TxtBlk,
                                             Button as _Btn, Grid as _GridWpf,
                                             ColumnDefinition as _ColDef)
        from System.Windows import (Thickness as _Thk, GridLength as _GLen,
                                    GridUnitType as _GUnit, Visibility as _VisG,
                                    VerticalAlignment as _VAl,
                                    TextWrapping as _TWrap)
        from System.Windows.Media import Brushes as _BrG

        _vue_noms = _get_vue_noms_from_grid()
        if not _vue_noms:
            forms.alert(
                u"Aucun type de nommage de vue défini dans la table 'Nommage des vues'.",
                title=titre)
            return

        _actives = _familles_actives(tvp_label)
        _cur_g   = dict(store.get(tvp_label, {}))

        _xaml_g = os.path.join(os.path.dirname(__file__), xaml_name)
        _dlg_g  = forms.WPFWindow(_xaml_g)
        _dlg_g.Title = u"{} — {}".format(titre, tvp_label)

        # La barre « valeurs par défaut » n'existe que dans TypesVuesDialog,
        # et seulement quand des défauts sont fournis. getattr plutôt qu'un
        # test sur le XAML : GabaritsDialog n'a pas ce panneau du tout.
        _pnl_def = getattr(_dlg_g, 'pnlDefauts', None)
        if _pnl_def is not None and defauts is None:
            _pnl_def.Visibility = _VisG.Collapsed

        _champs  = []     # (vue_id, TextBox, famille_active)
        _verrous = []     # libellés des familles verrouillées
        _demande_defauts = [False]   # « Réglages par défaut… » a été cliqué
        for _lv, _iv, _kv in _vue_noms:
            _actif_g = _iv in _actives
            if not _actif_g:
                _verrous.append(_lv)

            _ligne = _GridWpf()
            _ligne.Margin = _Thk(0, 2, 0, 2)
            # Cinquieme colonne « Défauts » seulement quand il y a des defauts
            # a rappeler : sinon la ligne garde exactement la mise en page
            # qu'elle avait, sans colonne vide a droite.
            _largeurs = (200, -1, 110, 90) if defauts is None \
                else (200, -1, 110, 90, 80)
            for _w in _largeurs:
                _cd = _ColDef()
                _cd.Width = (_GLen(1, _GUnit.Star) if _w < 0 else _GLen(_w))
                _ligne.ColumnDefinitions.Add(_cd)

            _lbl_g = _TxtBlk()
            _lbl_g.Text = _lv
            _lbl_g.VerticalAlignment = _VAl.Center
            _lbl_g.Margin = _Thk(0, 0, 8, 0)
            _lbl_g.TextWrapping = _TWrap.Wrap
            if not _actif_g:
                _lbl_g.Foreground = _BrG.Gray
            _GridWpf.SetColumn(_lbl_g, 0)
            _ligne.Children.Add(_lbl_g)

            _tb_g = _TxtBox()
            _tb_g.Text = _cur_g.get(_iv, u'')
            _tb_g.Padding = _Thk(3, 2, 3, 2)
            _tb_g.VerticalAlignment = _VAl.Center
            _tb_g.IsReadOnly = not _actif_g
            if not _actif_g:
                _tb_g.Background = _BrG.WhiteSmoke
                _tb_g.Foreground = _BrG.Gray
            _GridWpf.SetColumn(_tb_g, 1)
            _ligne.Children.Add(_tb_g)

            _btn_g = _Btn()
            _btn_g.Content = u"Choisir…"
            _btn_g.Margin  = _Thk(6, 0, 0, 0)
            _btn_g.Padding = _Thk(4, 1, 4, 1)
            _btn_g.IsEnabled = _actif_g
            _GridWpf.SetColumn(_btn_g, 2)
            _ligne.Children.Add(_btn_g)

            _btn_c = _Btn()
            _btn_c.Content = u"Effacer"
            _btn_c.Margin  = _Thk(6, 0, 0, 0)
            _btn_c.Padding = _Thk(4, 1, 4, 1)
            _btn_c.IsEnabled = _actif_g
            _GridWpf.SetColumn(_btn_c, 3)
            _ligne.Children.Add(_btn_c)

            # Valeurs capturées par défaut d'argument : sans cela les handlers
            # partageraient la dernière itération de la boucle.
            def _choisir(s, e, _lv=_lv, _iv=_iv, _tb=_tb_g):
                _sel = selecteur(_lv, _iv, _tb.Text)
                if _sel is not None:
                    _tb.Text = _sel

            def _effacer(s, e, _tb=_tb_g):
                _tb.Text = u''

            _btn_g.Click += _choisir
            _btn_c.Click += _effacer

            if defauts is not None:
                _btn_d = _Btn()
                _btn_d.Content = u"Défauts"
                _btn_d.Margin  = _Thk(6, 0, 0, 0)
                _btn_d.Padding = _Thk(4, 1, 4, 1)
                _btn_d.IsEnabled = _actif_g
                # Un defaut vide EST une valeur : rappeler « rien » efface la
                # ligne, ce qui est bien le reglage par defaut demande.
                _btn_d.ToolTip = (
                    u"Rappelle la valeur par défaut de cette ligne : « {} ».".format(
                        defauts.get(_iv, u''))
                    if defauts.get(_iv) else
                    u"La valeur par défaut de cette ligne est vide : ce bouton "
                    u"efface donc la valeur saisie.")
                _GridWpf.SetColumn(_btn_d, 4)
                _ligne.Children.Add(_btn_d)

                def _rappel_defaut(s, e, _iv=_iv, _tb=_tb_g):
                    _tb.Text = defauts.get(_iv, u'')

                _btn_d.Click += _rappel_defaut

            _dlg_g.pnlLignes.Children.Add(_ligne)
            _champs.append((_iv, _tb_g, _actif_g))

        # Bandeau explicatif : sans lui, une ligne qui refuse la saisie
        # ressemble a un bug plutot qu'a un reglage.
        if _verrous:
            if len(_verrous) == len(_vue_noms):
                _dlg_g.txtNoteFamilles.Text = (
                    u"Toutes les lignes sont verrouillées : la vue "
                    u"personnalisée « {} » n'est active sur aucune famille de "
                    u"vues. Activez-en dans la colonne « Familles de "
                    u"vues ».".format(tvp_label))
            else:
                _dlg_g.txtNoteFamilles.Text = (
                    u"Lignes verrouillées (« {} » n'y est pas active, voir la "
                    u"colonne « Familles de vues ») : {}.".format(
                        tvp_label, u", ".join(_verrous)))
            _dlg_g.txtNoteFamilles.Visibility = _VisG.Visible

        if defauts is not None and _pnl_def is not None:
            def _tout_aux_defauts(s, e):
                """
                Les lignes VERROUILLEES ne bougent pas : leur valeur est
                conservee telle quelle (voir la docstring), l'ecraser depuis un
                bouton reviendrait a modifier ce que le dialogue refuse par
                ailleurs de laisser saisir.
                """
                for _iv_d, _tb_d, _actif_d in _champs:
                    if _actif_d:
                        _tb_d.Text = defauts.get(_iv_d, u'')

            _dlg_g.btnDefautsTout.Click += _tout_aux_defauts

            if ouvrir_defauts is not None:
                def _ouvrir_reglages_defaut(s, e):
                    """
                    Valide et ferme CE dialogue, puis ouvre celui des defauts.
                    Deux raisons de ne pas empiler les deux fenetres : la
                    saisie en cours serait perdue au retour, et les champs
                    deja construits ne reliraient pas les nouveaux defauts.
                    """
                    _demande_defauts[0] = True
                    setattr(_dlg_g, 'DialogResult', True)

                _dlg_g.btnDefautsReglages.Click += _ouvrir_reglages_defaut
            else:
                _dlg_g.btnDefautsReglages.Visibility = _VisG.Collapsed

        _dlg_g.btnCancel.Click += lambda s, e: setattr(_dlg_g, 'DialogResult', False)
        _dlg_g.btnOK.Click     += lambda s, e: setattr(_dlg_g, 'DialogResult', True)

        if not _dlg_g.show_dialog():
            return
        store[tvp_label] = dict(
            (_iv, (_tb_g.Text or u'').strip()) for _iv, _tb_g, _act in _champs)
        # Apres l'ecriture : le passage par l'editeur des defauts ne doit pas
        # coûter la saisie faite ici.
        if _demande_defauts[0] and ouvrir_defauts is not None:
            ouvrir_defauts()

    def _open_checklist_dialog(titre, description, items, note=u'',
                               avec_recherche=False):
        """
        Ouvre une liste de cases a cocher pour UNE ligne de 'Vues personnalisées'.

        titre       : titre de la fenetre (le label de la ligne y est ajoute)
        description : texte d'aide affiche en haut
        items       : liste de tuples
                      (cle, libelle, valeur_initiale, infobulle, actif)
                      actif=False -> case grisee, valeur non modifiable mais
                      toujours retournee (l'utilisateur voit l'option exister
                      et son infobulle dit pourquoi elle est indisponible)
        note        : avertissement affiche sous la liste, ou '' pour le masquer
        avec_recherche : affiche le champ de filtrage. Utile au referentiel des
                      disciplines (des centaines de lignes), inutile aux
                      quelques familles de vues ou aux trois outils de la
                      colonne « Disponibilité » — d'ou le defaut a False.

        La case « Afficher uniquement les valeurs selectionnees », elle, est
        TOUJOURS presente : relire ce qui est coche est utile meme sur une
        liste courte, et elle ne coute qu'une ligne quand on ne s'en sert pas.

        Retourne None si l'utilisateur annule, sinon {cle: bool}.

        Une liste verticale plutot qu'une grille a N colonnes : les deux axes
        (familles de vues, outils) sont des listes de longueur variable, et une
        case a cocher WPF dans un DataGrid demande deux clics (entrer en
        edition, puis cocher) — ici un seul suffit.

        UN SEUL dialogue pour les quatre colonnes. Dupliquer la mecanique de
        surlignage ci-dessous pour la reserver a une colonne aurait garanti que
        les deux divergent.

        MEME MECANIQUE que la case a cocher de ligne de 08_Modifier >
        Selection-Epinglage (_ElementRow / _on_row_checkbox_click) : l'etat
        coche vit sur l'OBJET ligne lui-meme (INotifyPropertyChanged), pas
        sur IsSelected d'une ListBoxItem ni sur un RowFilter de DataView —
        cette derniere approche, essayee ici en premier, ne fonctionnait pas
        de facon fiable dans cet hote WPF (constat deja fait et documente
        dans apply_filter() de Selection-Epinglage pour ICollectionView.
        Filter). Le filtrage reaffecte ItemsSource a une ObservableCollection
        neuve plutot que de filtrer sur place, pour la meme raison.

        Ctrl+Clic, Maj+Clic et Ctrl+Maj+Clic construisent une selection
        surlignee ; cocher une case appartenant a cette selection applique
        son nouvel etat a TOUTE la selection (cochage en masse).
        """
        from System.Windows import Visibility as _VisR
        from System.Windows import RoutedEventHandler as _RoutedEventHandler
        from System.Windows import UIElement as _UIElementR
        from System.Windows.Input import Keyboard as _KeyboardR
        from System.Windows.Input import Key as _WpfKeyR
        from System.Windows.Input import MouseButtonEventHandler as _MouseBtnHandler
        from System.Windows.Controls import CheckBox as _WpfChkR
        from System.Windows.Controls.Primitives import ButtonBase as _ButtonBaseR
        from System.Windows.Media import VisualTreeHelper as _VTHRech
        from System.Windows.Threading import DispatcherPriority as _PrioRech
        from System.Collections.ObjectModel import ObservableCollection as _ObsColl
        import System as _SystemR
        from System import Action as _ActionRech
        from System.ComponentModel import (INotifyPropertyChanged as _INPC,
                                           PropertyChangedEventArgs as _PCEA)

        class _CaseRow(object, _INPC):
            """Ligne du dialogue. 'coche' notifie ses changements pour rester
            synchrone avec la case lors des traitements en masse (Tout
            cocher/decocher, Inverser, plage Maj+Clic)."""

            def __init__(self, cle, libelle, valeur, tip, actif):
                self.cle           = cle
                self.libelle       = libelle
                # None et non u'' quand il n'y a rien a dire : une chaine vide
                # reste un ToolTip NON NUL pour WPF, qui affiche alors une
                # infobulle vide au survol de chaque ligne. La plupart des
                # lignes des colonnes « Familles de vues », « Discipline » et
                # « Types niv. par defaut » n'ont pas d'infobulle.
                self.tip           = tip if tip else None
                self.actif         = bool(actif)
                self._coche        = bool(valeur)
                self._PropertyChanged = None

            def add_PropertyChanged(self, value):
                self._PropertyChanged = _SystemR.Delegate.Combine(
                    self._PropertyChanged, value)

            def remove_PropertyChanged(self, value):
                self._PropertyChanged = _SystemR.Delegate.Remove(
                    self._PropertyChanged, value)

            def _get_coche(self):
                return self._coche

            def _set_coche(self, value):
                if self._coche != value:
                    self._coche = value
                    if self._PropertyChanged is not None:
                        self._PropertyChanged(self, _PCEA(u'coche'))

            coche = property(_get_coche, _set_coche)

        _toutes = [_CaseRow(_cle, _lib, _val, _tip, _act)
                   for _cle, _lib, _val, _tip, _act in items]
        _visibles = []  # sous-ensemble actuellement affiche (filtre de recherche)

        _xaml = os.path.join(os.path.dirname(__file__),
                             'CasesACocherRechercheDialog.xaml')
        _dlg  = forms.WPFWindow(_xaml)
        _dlg.Title = titre
        _dlg.txtDescription.Text = description
        if note:
            _dlg.txtNote.Text       = note
            _dlg.txtNote.Visibility = _VisR.Visible
        if not avec_recherche:
            # Collapsed et non Hidden : la ligne est en hauteur Auto, elle
            # disparait donc au lieu de laisser un blanc.
            _dlg.txtRecherche.Visibility = _VisR.Collapsed

        def _appliquer_visibles(_lignes):
            del _visibles[:]
            _visibles.extend(_lignes)
            _coll = _ObsColl[object]()
            for _r in _lignes:
                _coll.Add(_r)
            _dlg.lstCases.ItemsSource = _coll

        _appliquer_visibles(_toutes)

        def _lignes_a_montrer():
            """
            Recherche ET case « uniquement les valeurs selectionnees »,
            combinees. Les deux ne font que RESTREINDRE l'affichage : l'etat
            coche vit sur la ligne (_CaseRow), rien ne s'y perd.
            """
            _texte = (_dlg.txtRecherche.Text or u'').strip().lower()
            _seules = bool(_dlg.chkSeulesCochees.IsChecked)
            return [_r for _r in _toutes
                    if (not _texte or _texte in _r.libelle.lower())
                    and (not _seules or _r.coche)]

        def _on_filtre_change(sender, e):
            _appliquer_visibles(_lignes_a_montrer())
            # Surlignage et ancre sont des INDICES dans la liste visible :
            # ils ne veulent plus rien dire des qu'elle change de forme. Les
            # cases cochees, elles, ne bougent pas — c'est tout l'interet de
            # porter l'etat sur la ligne et non sur le surlignage.
            del _selection[:]
            _ancre[0] = -1

        _dlg.txtRecherche.TextChanged   += _on_filtre_change
        # Pas de recalcul a chaque case cochee : une ligne qui disparait sous
        # le curseur au moment ou on la coche rend le pointage impossible. La
        # liste ne se resserre qu'au prochain changement de filtre.
        _dlg.chkSeulesCochees.Checked   += _on_filtre_change
        _dlg.chkSeulesCochees.Unchecked += _on_filtre_change

        # ── Selection multiple et cochage en masse ──────────────────────────────
        # La selection surlignee est tenue PAR NOUS, pas laissee a WPF : un
        # clic sur une case a cocher est d'abord un clic sur la case, et
        # l'ordre dans lequel WPF met a jour la selection de la ListBoxItem
        # n'est pas garanti. On la calcule donc soi-meme au tunnel
        # (PreviewMouseLeftButtonDown, avant tout traitement natif), puis on
        # la reimpose en priorite Background — donc APRES que WPF ait fini
        # son propre travail de selection.
        #
        # PIEGE, cause des deux versions precedentes qui ne faisaient RIEN :
        # avec AddHandler pose sur la ListBox, `sender` est la LISTBOX, pas
        # la case cliquee. Il faut remonter depuis e.OriginalSource — meme
        # motif que _on_tvp_button_click plus bas dans ce fichier.
        _selection = []
        _ancre     = [-1]

        def _remonter(_el, _test):
            while _el is not None:
                if _test(_el):
                    return _el
                _suivant = getattr(_el, 'Parent', None)
                if _suivant is None:
                    try:
                        _suivant = _VTHRech.GetParent(_el)
                    except Exception:
                        _suivant = None
                _el = _suivant
            return None

        def _ligne_depuis(_el):
            _trouve = _remonter(
                _el, lambda _x: isinstance(getattr(_x, 'DataContext', None),
                                           _CaseRow))
            return _trouve.DataContext if _trouve is not None else None

        def _reimposer_surlignage():
            _dlg.lstCases.SelectedItems.Clear()
            for _r in _selection:
                _dlg.lstCases.SelectedItems.Add(_r)

        def _plus_tard(_fn):
            try:
                _dlg.Dispatcher.BeginInvoke(_PrioRech.Background,
                                            _ActionRech(_fn))
            except Exception:
                _fn()

        def _avant_clic(sender, e):
            _row = _ligne_depuis(e.OriginalSource)
            if _row is None or _row not in _visibles:
                return
            _idx  = _visibles.index(_row)
            _ctrl = (_KeyboardR.IsKeyDown(_WpfKeyR.LeftCtrl) or
                     _KeyboardR.IsKeyDown(_WpfKeyR.RightCtrl))
            _maj  = (_KeyboardR.IsKeyDown(_WpfKeyR.LeftShift) or
                     _KeyboardR.IsKeyDown(_WpfKeyR.RightShift))
            if _maj and _ancre[0] >= 0:
                _lo = min(_ancre[0], _idx)
                _hi = max(_ancre[0], _idx)
                _plage = [_r for _r in _visibles[_lo:_hi + 1] if _r.actif]
                if not _ctrl:
                    # Maj seul : la plage REMPLACE la selection.
                    del _selection[:]
                # Ctrl+Maj : la plage s'AJOUTE a ce qui est deja selectionne.
                for _r in _plage:
                    if _r not in _selection:
                        _selection.append(_r)
            elif _ctrl:
                if _row in _selection:
                    _selection.remove(_row)
                elif _row.actif:
                    _selection.append(_row)
                _ancre[0] = _idx
            else:
                del _selection[:]
                if _row.actif:
                    _selection.append(_row)
                _ancre[0] = _idx
            # Surtout PAS e.Handled : la case doit quand meme basculer.
            _plus_tard(_reimposer_surlignage)

        def _on_case_click(sender, e):
            _case = _remonter(e.OriginalSource,
                              lambda _x: isinstance(_x, _WpfChkR))
            if _case is None:
                return
            _row = _case.DataContext
            if not isinstance(_row, _CaseRow) or _row not in _visibles:
                return
            _nouvel_etat = bool(_case.IsChecked)
            # Toute la selection prend l'etat de la case qu'on vient de
            # cliquer — c'est le cochage en masse. Hors selection multiple,
            # la ligne cliquee seule.
            _cibles = (_selection if (_row in _selection and len(_selection) > 1)
                       else [_row])
            for _r in _cibles:
                if _r.actif:
                    _r.coche = _nouvel_etat
            _plus_tard(_reimposer_surlignage)

        _dlg.lstCases.AddHandler(
            _UIElementR.PreviewMouseLeftButtonDownEvent,
            _MouseBtnHandler(_avant_clic), True)
        _dlg.lstCases.AddHandler(
            _ButtonBaseR.ClickEvent, _RoutedEventHandler(_on_case_click))

        # Les trois boutons agissent sur TOUTES les lignes affichees, jamais
        # sur le seul surlignage : « Inverser » inverse l'ensemble, c'est ce
        # que son libelle annonce. Meme comportement que les boutons de
        # 08_Modifier > Selection-Epinglage, qui bouclent sur visible_rows.
        # Seule restriction, les deux filtres — recherche et « uniquement les
        # valeurs selectionnees » : ce qu'ils masquent n'est pas touche, sans
        # quoi un bouton modifierait des lignes invisibles.
        def _apres_masse():
            # Le filtre « uniquement les valeurs selectionnees » vient d'etre
            # invalide par le traitement en masse : la liste montrerait des
            # lignes decochees. Elle se resserre donc ici, une seule fois.
            if _dlg.chkSeulesCochees.IsChecked:
                _on_filtre_change(None, None)

        def _tout_cocher(sender, e):
            for _r in _visibles:
                if _r.actif:
                    _r.coche = True
            _apres_masse()

        def _tout_decocher(sender, e):
            for _r in _visibles:
                if _r.actif:
                    _r.coche = False
            _apres_masse()

        def _inverser(sender, e):
            for _r in _visibles:
                if _r.actif:
                    _r.coche = not _r.coche
            _apres_masse()

        _dlg.btnToutSelectionner.Click   += _tout_cocher
        _dlg.btnToutDeselectionner.Click += _tout_decocher
        _dlg.btnInverser.Click           += _inverser

        _dlg.btnOK.Click     += lambda s, e: setattr(_dlg, 'DialogResult', True)
        _dlg.btnCancel.Click += lambda s, e: setattr(_dlg, 'DialogResult', False)

        if not _dlg.show_dialog():
            return None
        # _toutes, pas _visibles : une case cochee puis masquee par la
        # recherche doit garder son etat au retour.
        #
        # Cle rendue TELLE QUELLE, sans str() : les codes de discipline sont de
        # l'ASCII, mais « Types niv. par defaut » tire les siennes de la colonne
        # « Definition » de l'onglet Niveaux, saisie libre — un « Bâtiment »
        # ferait lever UnicodeEncodeError a str() sous IronPython 2.7.
        return dict((_r.cle, bool(_r.coche)) for _r in _toutes)

    def _open_familles_vues_dialog(tvp_label):
        """
        Colonne « Familles de vues » : sur quelles familles de vues cette vue
        personnalisée peut être utilisée. Alimente cfg['dispo_types_pers_familles'].
        """
        _vue_noms = _get_vue_noms_from_grid()
        if not _vue_noms:
            forms.alert(
                u"Aucun type de nommage de vue défini dans la table "
                u"'Nommage des vues'.", title=u"Familles de vues")
            return
        # Ligne systeme "PIECES 3D" : verrouillee sur la seule famille designee
        # comme "Pièces 3D" dans "Nommage des vues". L'outil ne cree qu'une vue
        # 3D, cocher une autre famille n'aurait aucun effet.
        if tvp_label == _TVP_LABEL_PIECES_3D:
            _p3d_vid = _vue_id_pieces_3d()
            _items = [(_iv, _lv, _iv == _p3d_vid,
                       u"Réglage verrouillé : « {} » ne crée que des vues de "
                       u"la famille désignée « Pièces 3D » dans la table "
                       u"« Nommage des vues ».".format(_TVP_LABEL_PIECES_3D),
                       False)
                      for _lv, _iv, _kv in _vue_noms]
            _res = _open_checklist_dialog(
                u"Familles de vues — {}".format(tvp_label),
                u"Réglage verrouillé. La vue personnalisée « {} » est réservée "
                u"à l'outil 05_Pieces > Pièces 3D, qui ne crée que des vues de "
                u"la famille désignée « Pièces 3D » dans la table « Nommage "
                u"des vues ».".format(tvp_label),
                _items)
            if _res is not None:
                _dispo_types_pers_fam[tvp_label] = dict(
                    (_iv, _iv == _p3d_vid) for _lv, _iv, _kv in _vue_noms)
            return

        # Meme source de verite que les colonnes "Types de vues" et "Gabarits
        # de vues" : non renseigne = actif (table purement restrictive).
        _actives = _familles_actives(tvp_label)
        _items = [(_iv, _lv, _iv in _actives, None, True)
                  for _lv, _iv, _kv in _vue_noms]
        _res = _open_checklist_dialog(
            u"Familles de vues — {}".format(tvp_label),
            u"Cochez les familles de vues sur lesquelles la vue personnalisée "
            u"« {} » peut être utilisée. Elle ne sera proposée dans les outils "
            u"NM-BATII que pour les familles cochées, et seules leurs colonnes "
            u"seront modifiables dans « Types de vues » et « Gabarits de "
            u"vues ».".format(tvp_label),
            _items)
        if _res is not None:
            _dispo_types_pers_fam[tvp_label] = _res

    def _open_discipline_dialog(tvp_label):
        """
        Colonne « Discipline » : sur quelles disciplines (Discipline —
        Sous-discipline du référentiel) cette vue personnalisée peut être
        utilisée. Alimente cfg['dispo_types_pers_disciplines'].

        Aucune ligne verrouillée ici, contrairement aux Familles de vues :
        un type système (FM, TEMPORAIRE, PIECES 3D) n'est pas propre à une
        discipline.
        """
        _disc_items = _disc_api['items_disciplines']()
        if not _disc_items:
            forms.alert(
                u"Aucune ligne définie dans l'onglet 'Disciplines'.",
                title=u"Discipline")
            return
        _actives = _disciplines_actives(tvp_label)
        _items = [(_code, _lib, _code in _actives, None, True)
                  for _code, _lib in _disc_items]
        # Seule colonne a demander le champ de recherche : le referentiel peut
        # compter des centaines de lignes, contrairement aux familles de vues.
        _res = _open_checklist_dialog(
            u"Discipline — {}".format(tvp_label),
            u"Cochez les disciplines sur lesquelles la vue personnalisée "
            u"« {} » peut être utilisée. Elle ne sera proposée, dans « Vues + » "
            u"et « Lier CAO », que lorsque le filtre Discipline choisi "
            u"correspond à l'une des cases cochées ici — ou toujours, si "
            u"aucune n'est décochée.".format(tvp_label),
            _items, avec_recherche=True)
        if _res is not None:
            _dispo_types_pers_disc[tvp_label] = _res

    def _types_niveaux_items():
        """
        Liste [(cle, libelle)] des types de niveaux configurables, construite
        depuis les prefixes de niveaux (onglet "Niveaux"), plus "Autres".

        Meme regroupement par 'definition' que construire_filtres() dans
        03_Vues > Vues + : la cle est la definition en minuscules, et c'est
        elle qui sert de cle dans config.json. Lue dans la GRILLE des
        prefixes, pour tenir compte d'un prefixe ajoute dans la meme session.
        """
        _par_def = []
        _vus = {}
        for _rp in wpf.dgPrefixes.ItemsSource:
            _defn_p = str(_rp['definition']) if _rp['definition'] is not None else u''
            _pfx_p  = str(_rp['prefixe'])    if _rp['prefixe']    is not None else u''
            if not _defn_p:
                continue
            if _defn_p not in _vus:
                _vus[_defn_p] = []
                _par_def.append(_defn_p)
            if _pfx_p:
                _vus[_defn_p].append(_pfx_p)
        _items_n = []
        for _defn_p in sorted(_par_def):
            _pfxs_p = _vus[_defn_p]
            _lib_p = (u"{} - {}".format(_defn_p, u", ".join(_pfxs_p))
                      if _pfxs_p else _defn_p)
            _items_n.append((_defn_p.lower(), _lib_p))
        # "Autres" en dernier : niveaux dont le nom ne porte aucun prefixe connu
        _items_n.append((u'autres', u"Autres"))
        return _items_n

    def _open_niveaux_defaut_dialog(tvp_label):
        """
        Colonne « Types de niveaux par défaut » : types de niveaux cochés à
        l'ouverture de Vues + et Lier CAO quand cette vue personnalisée est
        choisie. L'utilisateur reste libre de les modifier dans ces outils —
        il ne s'agit que de l'état initial.
        """
        _items_n = _types_niveaux_items()
        if not _items_n:
            forms.alert(
                u"Aucun préfixe de niveau défini dans l'onglet « Niveaux ».",
                title=u"Types de niveaux par défaut")
            return
        # Reprise de l'ancien reglage global tant que ce label n'a pas ete
        # configure : le comportement d'avant est conserve a l'identique.
        _cur_n = _niveaux_defaut_pers.get(tvp_label)
        if _cur_n is None:
            _cur_n = dict((_k, bool(_v)) for _k, _v in vm_filtres.items())
        _items = [(_cle_n, _lib_n,
                   _cur_n.get(_cle_n, _cle_n == u'batiment'), None, True)
                  for _cle_n, _lib_n in _items_n]
        _res = _open_checklist_dialog(
            u"Types de niveaux par défaut — {}".format(tvp_label),
            u"Cochez les types de niveaux présélectionnés dans « Vues + » et "
            u"« Lier CAO » lorsque la vue personnalisée « {} » est choisie. "
            u"Ce n'est qu'un état initial : il reste modifiable dans ces "
            u"outils.".format(tvp_label),
            _items)
        if _res is not None:
            _niveaux_defaut_pers[tvp_label] = _res

    def _open_dispo_scripts_dialog(tvp_label):
        """
        Colonne « Disponibilité » : dans quels outils NM-BATII créant des vues
        cette vue personnalisée est proposée. Alimente
        cfg['dispo_types_pers_lier_cao'].
        """
        # Ligne systeme "PIECES 3D" : entierement verrouillee — "Pièces 3D"
        # coche, les deux autres decoches. Elle sert uniquement a l'outil
        # 05_Pieces > Pièces 3D et n'a pas a apparaitre dans les menus de
        # Lier CAO ou Vues +.
        # Sur les AUTRES lignes, seule la case "Pièces 3D" est grisee : la voir
        # grisee avec son infobulle renseigne mieux qu'une case absente.
        _est_ligne_p3d = (tvp_label == _TVP_LABEL_PIECES_3D)
        _tip_reserve = (u"Réservé à la vue personnalisée « {} », la ligne "
                        u"système dédiée à cet outil.".format(
                            _TVP_LABEL_PIECES_3D))
        _tip_verrou  = (u"Réglage verrouillé : « {} » est réservée à l'outil "
                        u"05_Pieces > Pièces 3D.".format(_TVP_LABEL_PIECES_3D))
        _items = [
            (u'lier_cao',  u"Lier CAO → Vues",
             False if _est_ligne_p3d else _dispo_types_pers.get(tvp_label, True),
             (_tip_verrou if _est_ligne_p3d else
              u"04_Lier_importer > Lier CAO : menu « Type personnalisé »."),
             not _est_ligne_p3d),
            (u'vues_plus', u"Vues +",
             False if _est_ligne_p3d else _dispo_types_pers_vp.get(tvp_label, True),
             (_tip_verrou if _est_ligne_p3d else
              u"03_Vues > Vues + : menu « Type personnalisé »."),
             not _est_ligne_p3d),
            (u'pieces_3d', u"Pièces 3D",
             _est_ligne_p3d,
             (u"05_Pieces > Pièces 3D : type utilisé pour la vue 3D créée."
              if _est_ligne_p3d else _tip_reserve),
             False),
        ]
        _res = _open_checklist_dialog(
            u"Disponibilité — {}".format(tvp_label),
            (u"Réglage verrouillé. La vue personnalisée « {} » sert uniquement "
             u"à l'outil 05_Pieces > Pièces 3D.".format(tvp_label)
             if _est_ligne_p3d else
             u"Cochez les outils NM-BATII créant des vues dans lesquels la vue "
             u"personnalisée « {} » est proposée.".format(tvp_label)),
            _items,
            note=(u"" if _est_ligne_p3d else
                  u"« Pièces 3D » n'est configurable que sur la vue "
                  u"personnalisée « {} ».".format(_TVP_LABEL_PIECES_3D)))
        if _res is None:
            return
        # Les valeurs verrouillees sont reappliquees en dur : on ne veut
        # dependre d'aucun etat d'interface pour tenir les invariants.
        if _est_ligne_p3d:
            _dispo_types_pers[tvp_label]     = False
            _dispo_types_pers_vp[tvp_label]  = False
            _dispo_types_pers_p3d[tvp_label] = True
            for _autre in list(_dispo_types_pers_p3d.keys()):
                if _autre != tvp_label:
                    _dispo_types_pers_p3d[_autre] = False
            return
        _dispo_types_pers[tvp_label]     = _res[u'lier_cao']
        _dispo_types_pers_vp[tvp_label]  = _res[u'vues_plus']
        _dispo_types_pers_p3d[tvp_label] = False

    # ── Gabarits de vues : sélection dans le projet Revit ────────────────────
    # Un nom de gabarit erroné est ignoré SANS message par
    # utils/vues_creation._apply_view_template : la vue est créée sans gabarit
    # et rien ne le signale. D'où la sélection dans le projet plutôt qu'une
    # saisie libre — qui reste possible pour préparer une config avant que le
    # gabarit n'existe.

    def _tables_enums():
        """
        Correspondances vue_id ↔ énumérations Revit, et traducteurs vers les
        libellés français de « Nommage des vues ». Toutes PARTAGÉES depuis
        utils.vues_creation — les tenir ici en double finirait par diverger
        (la Structure est ViewFamily 'StructuralPlan' mais ViewType
        'EngineeringPlan', la 3D 'ThreeDimensional' / 'ThreeD').

        Repli neutre si le module n'est pas joignable : sans correspondance le
        filtre « compatibles » se désactive, et les libellés restent anglais —
        dégradé, mais jamais bloquant.
        """
        try:
            import utils.vues_creation as _vc_tr
            reload(_vc_tr)
            return {'viewtype':    _vc_tr.VUE_ID_TO_VIEWTYPE,
                    'viewfamily':  _vc_tr.VUE_ID_TO_VIEWFAMILY,
                    'lib_type':    _vc_tr.libelle_view_type,
                    'lib_famille': _vc_tr.libelle_view_family}
        except Exception:
            _identite = lambda _c, _n: _n
            return {'viewtype': {}, 'viewfamily': {},
                    'lib_type': _identite, 'lib_famille': _identite}

    # Un dict garde tel quel, sans deballage en quatre variables : chaque nom
    # local capture par une fonction imbriquee occupe une place dans le tuple
    # de scope de main() (voir _tvp_lignes).
    _enums = _tables_enums()

    # Sélecteur d'un élément du projet : implémentation PARTAGÉE dans
    # lib/dialogs/selection_liste.py, utilisée aussi par « Pièces 3D » pour
    # proposer un gabarit de substitution. Deux copies du même rapprochement
    # de nom finiraient par diverger — c'est exactement ce qui avait fait
    # échouer l'application du gabarit dans « Pièces 3D ».
    from dialogs.selection_liste import choisir_dans_liste as _open_selection_liste

    def _gabarits_du_projet():
        """
        Liste [(nom, nom_du_ViewType)] des gabarits de vues du projet ouvert,
        triee par nom. Retourne None si aucun document Revit n'est accessible
        (l'appelant distingue alors "pas de projet" de "projet sans gabarit").
        """
        try:
            from pyrevit import revit as _revit_gab
            from Autodesk.Revit.DB import (FilteredElementCollector as _FEC_gab,
                                           View as _View_gab)
            _doc_gab = _revit_gab.doc
            if _doc_gab is None:
                return None
            _res_gab = []
            for _v_gab in _FEC_gab(_doc_gab).OfClass(_View_gab):
                if not _v_gab.IsTemplate:
                    continue
                try:
                    _nom_gab = _v_gab.Name
                except Exception:
                    continue
                _res_gab.append((_nom_gab, _v_gab.ViewType.ToString()))
            return sorted(_res_gab, key=lambda _t: (_t[0] or u'').lower())
        except Exception:
            return None

    def _open_selection_gabarit(vue_label, vue_id, valeur_courante):
        """
        Ouvre le sélecteur de gabarit. Retourne le nom choisi, ou None si
        l'utilisateur annule (ou si la sélection est impossible).
        """
        from dialogs.dialogs_styles_loader import show_alert
        _tous = _gabarits_du_projet()
        if _tous is None:
            show_alert(
                u"Projet Revit indisponible",
                u"Impossible de lire les gabarits de vues : aucun projet Revit "
                u"n'est ouvert, ou son accès a échoué.\n\n"
                u"Ouvrez le projet concerné, puis rouvrez les paramètres. En "
                u"attendant, le nom peut être saisi manuellement.",
                close_label=u"Retour")
            return None
        if not _tous:
            show_alert(
                u"Aucun gabarit de vue",
                u"Le projet ouvert ne contient aucun gabarit de vue.\n\n"
                u"Créez-en dans Revit (Vue ▸ Gabarits de vues ▸ Gérer les "
                u"gabarits de vues), puis rouvrez les paramètres.",
                close_label=u"Retour")
            return None

        # Le filtre de compatibilité compare les NOMS D'ENUMERATION Revit ; la
        # traduction n'intervient qu'ensuite, pour l'affichage.
        _vt_attendu  = _enums['viewtype'].get(vue_id)
        _compatibles = ([_t for _t in _tous if _t[1] == _vt_attendu]
                        if _vt_attendu else None)
        _fr = lambda _lst: [(_n, _enums['lib_type'](cfg, _e)) for _n, _e in _lst]
        return _open_selection_liste(
            titre=u"Choisir un gabarit — {}".format(vue_label),
            description=(u"Gabarits de vues du projet ouvert. Sélectionnez "
                         u"celui à appliquer aux vues « {} » créées par "
                         u"NM-BATII.".format(vue_label)),
            entete_nom=u"Gabarit de vue",
            entete_info=u"Type de vue",
            items_tous=_fr(_tous),
            items_compat=(_fr(_compatibles) if _compatibles is not None else None),
            libelle_compat=u"Uniquement les gabarits compatibles avec « {} »".format(vue_label),
            valeur_courante=valeur_courante)

    def _types_vues_du_projet():
        """
        Liste [(nom, nom_de_la_ViewFamily)] des ViewFamilyType du projet
        ouvert, triee par nom. None si aucun document accessible.

        Le nom passe par SYMBOL_NAME_PARAM et non par .Name : sur un
        ElementType, Element.Name est implemente en interface explicite et
        l'acces direct leve AttributeError sous IronPython. C'est aussi ce que
        fait utils/vues_creation._get_vft_name, qui compare ces noms a la
        creation — les deux ne peuvent donc pas diverger.
        """
        try:
            from pyrevit import revit as _revit_tv
            from Autodesk.Revit.DB import (FilteredElementCollector as _FEC_tv,
                                           ViewFamilyType as _VFT_tv,
                                           BuiltInParameter as _BIP_tv)
            _doc_tv = _revit_tv.doc
            if _doc_tv is None:
                return None
            _res_tv = []
            for _vft_tv in _FEC_tv(_doc_tv).OfClass(_VFT_tv):
                _p_tv = _vft_tv.get_Parameter(_BIP_tv.SYMBOL_NAME_PARAM)
                _nom_tv = _p_tv.AsString() if _p_tv else None
                if not _nom_tv:
                    continue
                _res_tv.append((_nom_tv, _vft_tv.ViewFamily.ToString()))
            return sorted(_res_tv, key=lambda _t: (_t[0] or u'').lower())
        except Exception:
            return None

    def _schemas_surface_du_projet():
        """
        Liste [(nom, u'Schéma de surface')] des schemas de surface du projet.
        None si aucun document accessible.

        Passe par utils.vues_creation.get_area_scheme_names : c'est la meme
        lecture que celle utilisee a la creation des plans de surface, le
        selecteur ne peut donc pas proposer un nom qui serait ensuite refuse.
        """
        try:
            from pyrevit import revit as _revit_as
            import utils.vues_creation as _vc_as
            reload(_vc_as)
            _doc_as = _revit_as.doc
            if _doc_as is None:
                return None
            return [(_n_as, u"Schéma de surface")
                    for _n_as in _vc_as.get_area_scheme_names(_doc_as)]
        except Exception:
            return None

    def _open_selection_type_vue(vue_label, vue_id, valeur_courante):
        """
        Ouvre le sélecteur de type de vue. Retourne le nom choisi, ou None si
        l'utilisateur annule (ou si la sélection est impossible).

        Cas « Plan de surface » : ce n'est PAS un ViewFamilyType mais un
        SCHÉMA DE SURFACE (voir utils/vues_creation._get_area_scheme_id) — la
        liste proposée change donc de nature, et le filtre de compatibilité
        n'a pas lieu d'être puisque tous les schémas conviennent.
        """
        from dialogs.dialogs_styles_loader import show_alert
        _est_surface = (vue_id == u'vue-surface')

        if _est_surface:
            _tous_t = _schemas_surface_du_projet()
            _quoi   = u"schéma de surface"
            _ou     = (u"Revit : Architecture ▸ Calculs des surfaces et des "
                       u"volumes ▸ Schémas de surface")
        else:
            _tous_t = _types_vues_du_projet()
            _quoi   = u"type de vue"
            _ou     = u"Revit : arborescence du projet, Familles ▸ Vues"

        if _tous_t is None:
            show_alert(
                u"Projet Revit indisponible",
                u"Impossible de lire les {}s : aucun projet Revit n'est "
                u"ouvert, ou son accès a échoué.\n\n"
                u"Ouvrez le projet concerné, puis rouvrez les paramètres. En "
                u"attendant, le nom peut être saisi manuellement.".format(_quoi),
                close_label=u"Retour")
            return None
        if not _tous_t:
            show_alert(
                u"Aucun {}".format(_quoi),
                u"Le projet ouvert ne contient aucun {}.\n\n"
                u"Créez-en dans Revit ({}), puis rouvrez les "
                u"paramètres.".format(_quoi, _ou),
                close_label=u"Retour")
            return None

        if _est_surface:
            # Tous les schemas conviennent : pas de filtre de compatibilite.
            return _open_selection_liste(
                titre=u"Choisir un schéma de surface — {}".format(vue_label),
                description=(u"Schémas de surface du projet ouvert. Un plan de "
                             u"surface n'a pas de type de vue nommable : son "
                             u"type EST son schéma de surface. Le schéma doit "
                             u"exister, il n'est jamais créé automatiquement."),
                entete_nom=u"Schéma de surface",
                entete_info=u"Nature",
                items_tous=_tous_t,
                items_compat=None,
                libelle_compat=u"",
                valeur_courante=valeur_courante)

        # Comme ci-dessus : filtrage sur l'énumération, traduction à l'affichage.
        _vf_attendue = _enums['viewfamily'].get(vue_id)
        _compat_t = ([_t for _t in _tous_t if _t[1] == _vf_attendue]
                     if _vf_attendue else None)
        _fr = lambda _lst: [(_n, _enums['lib_famille'](cfg, _e)) for _n, _e in _lst]
        return _open_selection_liste(
            titre=u"Choisir un type de vue — {}".format(vue_label),
            description=(u"Types de vues du projet ouvert. Sélectionnez celui "
                         u"à appliquer aux vues « {} » créées par NM-BATII. "
                         u"Un type absent du projet serait créé par "
                         u"duplication.".format(vue_label)),
            entete_nom=u"Type de vue",
            entete_info=u"Famille de vues",
            items_tous=_fr(_tous_t),
            items_compat=(_fr(_compat_t) if _compat_t is not None else None),
            libelle_compat=u"Uniquement les types compatibles avec « {} »".format(vue_label),
            valeur_courante=valeur_courante)

    def _on_tvp_button_click(sender, e):
        """
        Handler de clic bubble depuis les boutons du DataGrid 'Vues personnalisées'.
        Dispatche selon le Tag du bouton : 'familles', 'discipline', 'types',
        'gabarits' ou 'dispo'.
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
        if _tag == 'familles':
            _open_familles_vues_dialog(_tvp_label)
        elif _tag == 'discipline':
            _open_discipline_dialog(_tvp_label)
        elif _tag == 'niveaux':
            _open_niveaux_defaut_dialog(_tvp_label)
        elif _tag == 'dispo':
            _open_dispo_scripts_dialog(_tvp_label)
        elif _tag == 'types':
            # Une ligne par famille, avec sélection dans le projet ouvert.
            # Seules les familles ACTIVES sont modifiables : renseigner un
            # type pour une famille désactivée n'aurait aucun effet. Le cas
            # "PIECES 3D" (verrouillée sur la seule famille désignée
            # « Pièces 3D ») en découle, sans traitement particulier ici.
            def _ouvrir_defauts_tv():
                """
                Éditeur des valeurs par défaut de la colonne « Types de vues ».

                Le MÊME dialogue que celui d'une ligne, sur un store de façade
                d'une seule entrée : les deux doivent proposer les mêmes
                familles, le même sélecteur de type et le même cas particulier
                du plan de surface. Deux implémentations auraient divergé au
                premier ajout de famille.

                `defauts` non fourni y coupe la barre du haut et la colonne
                « Défauts » : ces valeurs-ci n'ont rien au-dessus d'elles à
                rappeler. Aucune famille n'y est verrouillée non plus — ces
                défauts ne dépendent d'aucune ligne.

                Définie ICI, dans le handler, et non dans main() : un nom de
                plus dans main() capturé par une fonction imbriquée, c'est une
                place de plus dans le tuple de scope IronPython.
                """
                _facade = {_TVP_CLE_DEFAUT: dict(_types_vues_defaut[0])}
                _open_valeurs_par_famille(
                    'TypesVuesDialog.xaml', _facade, _TVP_CLE_DEFAUT,
                    u'Types de vues par défaut', _open_selection_type_vue)
                # Annulation : _open_valeurs_par_famille sort sans écrire, la
                # façade rend donc la copie inchangée. Rien à distinguer ici.
                _types_vues_defaut[0] = dict(_facade.get(_TVP_CLE_DEFAUT, {}))

            _open_valeurs_par_famille(
                'TypesVuesDialog.xaml', _types_vues_store, _tvp_label,
                u'Types de vues', _open_selection_type_vue,
                defauts=_types_vues_defaut[0],
                ouvrir_defauts=_ouvrir_defauts_tv)
        elif _tag == 'gabarits':
            _open_valeurs_par_famille(
                'GabaritsDialog.xaml', _gabarits_store, _tvp_label,
                u'Gabarits de vues', _open_selection_gabarit)
        # Le dialogue vient de modifier un store : les colonnes dérivées qui
        # le recopient en texte doivent suivre, sinon la recherche et les
        # filtres d'en-tête continueraient de lire l'ancien réglage.
        _tvp_api['maj_derivees']()
        _tvp_api['appliquer_filtre']()
        e.Handled = True

    wpf.dgTypesVues.AddHandler(ButtonBase.ClickEvent, RoutedEventHandler(_on_tvp_button_click))

    # ── Vues personnalisées : barre de boutons ────────────────────────────────
    # Mêmes actions que l'onglet « Disciplines », au même endroit et dans le
    # même ordre : le fichier à gauche (action de cadre, rare), l'ajout et la
    # suppression à droite (le quotidien).

    def _tvp_section():
        """
        Les SEPT tables de config.json qui décrivent les vues personnalisées,
        dans leur forme exacte d'enregistrement.

        Un seul assembleur pour le bouton « Enregistrer » de la fenêtre et
        pour le fichier .NM-VuesPersConfig — même raison que _disc_section :
        deux assembleurs finiraient par diverger, et un aller-retour par
        fichier perdrait une clé en chemin.

        La grille est la SOURCE : une table satellite n'est écrite que pour
        les labels qui y figurent encore. Supprimer une ligne suffit donc à
        purger ses réglages, sans ménage à faire ailleurs.

        _tvp_lignes(_dt_tvp) et NON ItemsSource : voir sa docstring — la vue est
        filtrée par la recherche et par les filtres d'en-tête, et enregistrer
        depuis elle supprimait tout ce qu'elles masquaient.
        """
        _labels = []
        for _row in _tvp_lignes(_dt_tvp):
            _lbl = str(_row['label']) if _row['label'] is not None else ''
            if _lbl:
                _labels.append((_lbl, _row))

        _p3d_vid = _vue_id_pieces_3d()
        _vue_noms = _get_vue_noms_from_grid()

        _tvp_out = []
        for _lbl, _row in _labels:
            _sys = _row['systeme']
            _tvp_out.append({
                # Texte, pas un entier : la colonne accepte « A1 » ou
                # « 10bis ». Les consommateurs trient dessus par clé
                # naturelle (voir _tvp_ord_key dans « Vues + » / « Lier CAO »).
                'ordre':    str(_row['ordre']) if _row['ordre'] is not None else '',
                'label':    _lbl,
                'titre':    str(_row['titre'])    if _row['titre']    is not None else '',
                'valeur_1': str(_row['valeur_1']) if _row['valeur_1'] is not None else '',
                'valeur_2': str(_row['valeur_2']) if _row['valeur_2'] is not None else '',
                'usage':    str(_row['usage'])    if _row['usage']    is not None else 'Temporaire',
                'systeme':  bool(_sys) if _sys is not None else False,
            })

        _fam_out = []
        for _lbl, _row in _labels:
            if _lbl == _TVP_LABEL_PIECES_3D:
                # Ligne figée sur la seule famille désignée « Pièces 3D »,
                # écrite explicitement même si son dialogue n'a jamais été
                # ouvert (voir _open_familles_vues_dialog).
                _fam = dict((_iv, _iv == _p3d_vid)
                            for _lv, _iv, _kv in _vue_noms)
            else:
                _fam = _dispo_types_pers_fam.get(_lbl, {})
            _fam_out.append({'label': _lbl, 'familles': _fam})

        _tpd_out = []
        for _lbl, _row in _labels:
            _est_p3d = (_lbl == _TVP_LABEL_PIECES_3D)
            _tpd_out.append({
                'label':     _lbl,
                'lier_cao':  (not _est_p3d) and _dispo_types_pers.get(_lbl, True),
                'vues_plus': (not _est_p3d) and _dispo_types_pers_vp.get(_lbl, True),
                'pieces_3d': _est_p3d,
            })

        _niv_out = []
        for _lbl, _row in _labels:
            _niv = _niveaux_defaut_pers.get(_lbl)
            if _niv is None:
                _niv = dict((_k, bool(_v)) for _k, _v in vm_filtres.items())
            _niv_out.append({'label': _lbl, 'niveaux': _niv})

        return {
            'types_vues_personnalises': _tvp_out,
            'types_vues': [{'label': _l, 'types': _types_vues_store.get(_l, {})}
                           for _l, _r in _labels],
            'gabarits_vues': [{'label': _l,
                               'gabarits': _gabarits_store.get(_l, {})}
                              for _l, _r in _labels],
            'dispo_types_pers_familles':    _fam_out,
            'dispo_types_pers_disciplines':
                [{'label': _l, 'disciplines': _dispo_types_pers_disc.get(_l, {})}
                 for _l, _r in _labels],
            'dispo_types_pers_lier_cao':    _tpd_out,
            'niveaux_defaut_types_pers':    _niv_out,
            # Pas une table par label : un seul jeu de valeurs, celui dont
            # hérite toute nouvelle vue personnalisée.
            'types_vues_defaut':            dict(_types_vues_defaut[0]),
        }

    def _tvp_charger_config(section):
        """
        Remplace la grille ET les six tables satellites par celles du
        fichier. Les lignes système absentes du fichier sont recréées : un
        outil sans son type personnalisé réservé n'aurait plus rien à
        désigner.
        """
        # Le fichier peut venir d'une version anterieure aux majuscules, ou
        # avoir ete edite a la main. Meme forme que cfg — les sept memes
        # tables — donc le meme normaliseur s'y applique tel quel.
        _tvp_normaliser_cfg(section)
        _entrees = list(section.get('types_vues_personnalises') or [])
        _presents = set(_e.get(u'label', u'') for _e in _entrees)
        for _lbl_sys in _TVP_LOCKED_ORDER:
            if _lbl_sys not in _presents:
                _entrees.append({
                    u'label': _lbl_sys, u'titre': _lbl_sys,
                    u'valeur_1': u'', u'valeur_2': u'',
                    u'usage': _TVP_LOCKED_USAGE.get(_lbl_sys, u'Temporaire'),
                    u'systeme': True,
                })

        _dt_tvp.Rows.Clear()
        _ord_auto = [len(_TVP_LOCKED_ORDER)]
        for _e in sorted(_entrees, key=_tvp_sort_key):
            _lbl = _e.get('label', '')
            if not _lbl:
                continue
            _est_sys = _lbl in _TVP_LOCKED_ORDRE
            _ord = _TVP_LOCKED_ORDRE.get(_lbl, _e.get('ordre', None))
            if _ord in (None, u'', ''):
                _ord = _ord_auto[0]
            _ord_num = _int_or(_ord, None)
            if _ord_num is not None:
                _ord_auto[0] = max(_ord_auto[0], _ord_num) + 1
            _r = _dt_tvp.NewRow()
            _tvp_poser_ordre(_r, _ord)
            _r['visible']  = True
            _r['label']    = _lbl
            _r['label_prec'] = _lbl
            _r['titre']    = _e.get('titre', _e.get('nom', ''))
            _r['valeur_1'] = _e.get('valeur_1', '')
            _r['valeur_2'] = _e.get('valeur_2', '')
            # Usage des lignes système imposé par le code, jamais par le
            # fichier : la colonne y est verrouillée, une valeur erronée
            # venue du fichier ne pourrait plus être corrigée.
            _r['usage']    = (_TVP_LOCKED_USAGE.get(_lbl)
                              if _est_sys else _e.get('usage', 'Temporaire'))
            _r['systeme']  = bool(_e.get('systeme', False)) or _est_sys
            _dt_tvp.Rows.Add(_r)

        def _recharger(store, cle_table, cle_valeurs, booleen=False):
            store.clear()
            for _e in (section.get(cle_table) or []):
                _lbl = _e.get(u'label', u'')
                if not _lbl:
                    continue
                _vals = _e.get(cle_valeurs, {}) or {}
                store[_lbl] = (dict((_k, bool(_v)) for _k, _v in _vals.items())
                               if booleen else dict(_vals))

        _recharger(_types_vues_store,       'types_vues',        'types')
        _recharger(_gabarits_store,         'gabarits_vues',     'gabarits')
        _recharger(_dispo_types_pers_fam,   'dispo_types_pers_familles',
                   'familles', booleen=True)
        _recharger(_dispo_types_pers_disc,  'dispo_types_pers_disciplines',
                   'disciplines', booleen=True)
        _recharger(_niveaux_defaut_pers,    'niveaux_defaut_types_pers',
                   'niveaux', booleen=True)

        # Disponibilité par outil : deux dicts distincts, une seule table.
        _dispo_types_pers.clear()
        _dispo_types_pers_vp.clear()
        for _e in (section.get('dispo_types_pers_lier_cao') or []):
            _lbl = _e.get(u'label', u'')
            if not _lbl:
                continue
            _dispo_types_pers[_lbl]    = bool(_e.get(u'lier_cao', True))
            _dispo_types_pers_vp[_lbl] = bool(_e.get(u'vues_plus', True))

        _types_vues_defaut[0] = dict(section.get('types_vues_defaut') or {})

    def _tvp_cfg_ecrire(sender, e):
        _commit_datagrid_edit(wpf.dgTypesVues)
        _tvp_cfg_enregistrer(wpf, _tvp_section())

    def _tvp_cfg_lire(sender, e):
        _section = _tvp_cfg_charger(wpf)
        if not _section:
            return
        from dialogs.dialogs_styles_loader import show_confirm as _confirm_tvp
        _nb_avant = len([_r for _r in _tvp_lignes(_dt_tvp)
                         if _r['label'] is not None and str(_r['label'])])
        _nb_apres = len(_section.get('types_vues_personnalises') or [])
        if _nb_avant and not _confirm_tvp(
                u"Importer une configuration",
                u"La table contient {} vue(s) personnalisée(s), qui seront "
                u"remplacées par les {} du fichier — leurs familles de vues, "
                u"disciplines, types, gabarits, types de niveaux et "
                u"disponibilités aussi.\n\nContinuer ?".format(
                    _nb_avant, _nb_apres),
                yes_label=u"Remplacer"):
            return
        _tvp_charger_config(_section)

    def _tvp_ajouter(sender, e):
        _tvp_nouvelle(sender, e)
        # Amener la ligne créée sous les yeux : la vue est triée par « Ord. »,
        # elle se pose donc en fin de table, souvent hors écran.
        for _rv in _dt_tvp.DefaultView:
            if _rv.Row is _dt_tvp.Rows[_dt_tvp.Rows.Count - 1]:
                wpf.dgTypesVues.SelectedItem = _rv
                try:
                    wpf.dgTypesVues.ScrollIntoView(_rv)
                except Exception:
                    pass
                break

    def _tvp_supprimer_bouton(sender, e):
        """
        Supprime TOUTE la sélection, après une seule confirmation — même
        principe que « Supprimer » de l'onglet Disciplines. Les lignes
        système sont écartées en silence : elles ne sont jamais supprimables,
        le dire à chaque fois n'apprendrait rien de plus que leur grisé.
        """
        _choisies = [_v for _v in wpf.dgTypesVues.SelectedItems
                     if _v is not None and hasattr(_v, 'Row')]
        _a_oter = [_v for _v in _choisies if not _is_sys_tvp(_v)]
        if not _a_oter:
            if _choisies:
                from dialogs.dialogs_styles_loader import show_alert
                show_alert(
                    u"Supprimer",
                    u"Les lignes système (« {} ») ne peuvent pas être "
                    u"supprimées : chacune est réservée à un outil "
                    u"NM-BATII.".format(u" », « ".join(_TVP_LOCKED_ORDER)),
                    close_label=u"Retour")
            return
        if len(_a_oter) > 1:
            from dialogs.dialogs_styles_loader import show_confirm as _confirm_sup
            if not _confirm_sup(
                    u"Supprimer",
                    u"{} vues personnalisées seront supprimées, avec tous "
                    u"leurs réglages.\n\nContinuer ?".format(len(_a_oter)),
                    yes_label=u"Supprimer"):
                return
        for _v in _a_oter:
            _v.Row.Delete()

    wpf.miTvpCfgExport.Click   += _tvp_cfg_ecrire
    wpf.miTvpCfgImport.Click   += _tvp_cfg_lire
    wpf.btnTvpAjout.Click      += _tvp_ajouter
    wpf.btnTvpSupprimer.Click  += _tvp_supprimer_bouton

    # Le ContextMenu s'ouvre au clic GAUCHE : sans cela il faudrait un clic
    # droit sur un bouton, ce que personne ne tente. Même mécanique que
    # btnDiscFichier.
    def _tvp_ouvrir_fichier(sender, e):
        _menu = wpf.btnTvpFichier.ContextMenu
        _menu.PlacementTarget = wpf.btnTvpFichier
        _menu.Placement = _PlacementMode.Bottom
        _menu.IsOpen = True

    wpf.btnTvpFichier.Click += _tvp_ouvrir_fichier

    def _tvp_maj_supprimer(sender=None, args=None):
        _sel = [_v for _v in wpf.dgTypesVues.SelectedItems
                if _v is not None and hasattr(_v, 'Row')]
        _oter = [_v for _v in _sel if not _is_sys_tvp(_v)]
        wpf.btnTvpSupprimer.IsEnabled = bool(_oter)
        wpf.btnTvpSupprimer.Content = (
            u"−  Su_pprimer les {} lignes".format(len(_oter))
            if len(_oter) > 1 else u"−  Su_pprimer")

    wpf.dgTypesVues.SelectionChanged += _tvp_maj_supprimer
    _tvp_maj_supprimer()

    # ── Renommage d'une ligne : suivre le Label dans les tables satellites ────
    # Les SIX tables de réglages (familles, disciplines, types, gabarits, types
    # de niveaux, disponibilité) s'indexent sur le Label, qui est éditable.
    # Sans ce report, renommer une ligne — le geste normal après « Dupliquer »
    # — laissait ses réglages sous l'ancienne clé : ils devenaient introuvables
    # et la ligne repartait sur les valeurs par défaut de chaque table, ce qui
    # se lit exactement comme une réinitialisation.
    # Le corps est une fonction de MODULE (_tvp_renommer_stores) ; ce qu'elle
    # doit suivre est passe ici, dans un lambda ANONYME. Nommer la fonction ou
    # le tuple de stores en ferait deux noms locaux de plus captures par une
    # imbriquee, donc deux places de plus dans le tuple de scope de main().

    # Recherche, filtres d'en-tete, tri, Dupliquer et aide : sortis en
    # fonction de MODULE. Le corps de main() etait sature — IronPython 2.7
    # plafonne le nombre de variables locales d'une fonction et signale le
    # depassement par un « Sequence contains no elements » qui designe une
    # ligne sans rapport. Meme remede que _init_disciplines.
    _tvp_api = _init_tvp_recherche(wpf, {
        'dt':              _dt_tvp,
        'tri_defaut':      _TVP_TRI_DEFAUT,
        'ctx_item':        _tvp_ctx_item,
        'dupliquer':       _tvp_dupliquer,
        'cle_ordre':       _tvp_cle_ordre,
        'maj_label':       _tvp_maj_label,
        'maj_titre':       _tvp_maj_titre,
        'vue_noms':        _get_vue_noms_from_grid,
        'items_disc':      _disc_api['items_disciplines'],
        'items_niveaux':   _types_niveaux_items,
        'familles_actives':    _familles_actives,
        'disciplines_actives': _disciplines_actives,
        'types_store':     _types_vues_store,
        'gabarits_store':  _gabarits_store,
        'niveaux_defaut':  _niveaux_defaut_pers,
        'niveaux_global':  vm_filtres,
        'dispo_cao':       _dispo_types_pers,
        'dispo_vp':        _dispo_types_pers_vp,
        'label_p3d':       _TVP_LABEL_PIECES_3D,
        'renommer':        lambda _r: _tvp_renommer_stores(
            _r, _dt_tvp,
            (_types_vues_store, _gabarits_store, _dispo_types_pers_fam,
             _dispo_types_pers_disc, _niveaux_defaut_pers,
             _dispo_types_pers, _dispo_types_pers_vp, _dispo_types_pers_p3d),
            lambda _lbl: _tvp_init_ligne_neuve(
                _lbl, _types_vues_store, _types_vues_defaut,
                _dispo_types_pers_disc, _disc_api['items_disciplines'])),
    })
    # Le dict est garde TEL QUEL, sans deballer ses entrees dans des variables
    # locales : chaque nom capture par une fonction imbriquee occupe une place
    # dans le tuple de scope de main(), et le depassement se manifeste par un
    # « Sequence contains no elements » pointant une ligne sans rapport (voir
    # _init_disciplines). Un seul nom capture au lieu de trois.
    # PAS de premier calcul ici : les colonnes derivees lisent la grille
    # « Nommage des vues », peuplee plus bas dans main(). L'appeler
    # maintenant les remplirait avec une liste de familles vide. Il a lieu
    # juste apres, voir « Premier calcul des colonnes derivees ».

    # ══════════════════════════════════════════════════════════════════════════
    # Panneau de composition des conventions de nommage
    # ══════════════════════════════════════════════════════════════════════════
    # Un clic dans une cellule "Template" ouvre TemplateBuilderDialog.xaml, qui
    # ne propose que les variables réellement applicables à la ligne éditée.

    # -- Variables des lignes de "Nommage des vues" ---------------------------
    # Communes à toutes les familles de vues.
    # {phase} est isolée : c'est la seule de cette liste que la ligne
    # "Nomenclature" partage (elle n'a pas de type de vue personnalisé).
    _VAR_PHASE = (u'phase', u'Phase de projet choisie à l\'exécution')
    _VARS_VUE_COMMUNES = [
        (u'vue-pers-titre',    u'Titre du type personnalisé (ex. FM, TEMP)'),
        (u'vue-pers-label',    u'Label du type personnalisé'),
        (u'vue-pers-valeur-1', u'Valeur-1 du type personnalisé'),
        (u'vue-pers-valeur-2', u'Valeur-2 du type personnalisé'),
        (u'vue-pers-usage',    u'Usage : Temporaire ou Livrable'),
        _VAR_PHASE,
    ]
    # Familles pouvant être déclinées par niveau. "Vue 3D" en fait partie même
    # si Vues + ne gère pas les niveaux pour les vues 3D : la variable reste
    # disponible pour de futurs scripts créant des vues 3D par niveau. Un
    # script qui ne fournit pas {niveau} le laisse vide et le segment est
    # supprimé (voir _VARIABLES_CANONIQUES dans lib/utils/vues_creation.py).
    # Nomenclature en est exclue : une nomenclature n'a pas de niveau.
    _IDS_VUE_AVEC_NIVEAU = (u'vue-plan', u'vue-plaf', u'vue-structure',
                            u'vue-surface', u'vue-dessin', u'vue-legende',
                            u'vue-3d', u'vue-coupe', u'vue-elevation')
    _VAR_NIVEAU = (u'niveau', u'Nom du niveau Revit (toujours la valeur exacte)')
    # Variables dont la valeur n'est jamais transformee par le moteur de
    # nommage (_CASSE_EXEMPT dans lib/utils/vues_creation.py) : proposer un
    # choix de casse serait trompeur, le clic insere directement {niveau}.
    _VARS_SANS_CASSE = (u'niveau',)
    _VARS_NOMENCLATURE = [
        (u'categorie',         u'Catégorie Revit (ex. Portes)'),
        (u'type-nomenclature', u'Type de nomenclature (ex. 2a - Saisie...)'),
    ]

    # -- Casses proposées au clic sur un bouton de variable --------------------
    # (description, fonction produisant le jeton pour un identifiant donné)
    _CASSES = [
        (u'valeur brute, inchangée', lambda i: u'{%s:val}' % i),
        (u'MAJUSCULES',              lambda i: u'{%s}' % i.upper()),
        (u'minuscules',              lambda i: u'{%s}' % i.lower()),
        (u'1re lettre en majuscule', lambda i: u'{%s}' % (i[0].upper() + i[1:].lower() if i else i)),
        (u'Chaque Mot Capitalisé',   lambda i: u'{%s:cap}' % i),
    ]

    def _groupes_atomiques_courants():
        """Identifiants de la table 'Groupes atomiques', lus en direct."""
        _res = []
        for _r in _dt_grp.Rows:
            _gid = str(_r['id']) if _r['id'] is not None else u''
            _lbl = str(_r['label']) if _r['label'] is not None else u''
            if _gid:
                _res.append((_gid, _lbl or _gid))
        return _res

    def _variables_pour(cle_table, row_id):
        """
        Retourne (liste_de_variables, casse_autorisee) pour la ligne editee.
        liste_de_variables : [(identifiant, description), ...]
        """
        if cle_table == u'vues':
            # "Nomenclature" ne passe pas par les types de vue personnalisés :
            # proposer les {vue-pers-*} produirait un jeton que le script de
            # création ne sait pas alimenter, donc un segment vide dans le nom.
            if row_id == u'vue-nomenclature':
                return list(_VARS_NOMENCLATURE) + [_VAR_PHASE], True
            _vars = list(_VARS_VUE_COMMUNES)
            if row_id in _IDS_VUE_AVEC_NIVEAU:
                _vars.insert(0, _VAR_NIVEAU)
            return _vars, True

        # "Nommage des presentations" combine les groupes atomiques et la
        # variable {niveau} (nom du niveau Revit), comme les vues.
        _vars = list(_groupes_atomiques_courants())
        # Regex calculees automatiquement, absentes de dgGroupes mais utilisables.
        _vars.append((u'pref-niv', u'Préfixe niveau (calculé depuis les préfixes)'))
        _vars.append((u'sens-niv', u'Sens niveau (calculé depuis les signes)'))
        if cle_table in (u'fichiers', u'niveau-revit'):
            _vars.append((u'niveau-code', u'Sous-template « Niveau (code) »'))
        if cle_table == u'present':
            _vars.append(_VAR_NIVEAU)
        # "Nommage de fichiers" et "Niveau (code)" alimentent build_regex(), qui
        # resout les identifiants a l'identique : aucune variante de casse.
        _casse_ok = cle_table not in (u'fichiers', u'niveau-code')
        return _vars, _casse_ok

    _LIBELLES_TABLE = {
        u'fichiers':     u'Nommage de fichiers',
        u'niveau-code':  u'Nommage des niveaux (code)',
        u'niveau-revit': u'Nommage des niveaux du modèle Revit',
        u'vues':         u'Nommage des vues',
        u'present':      u'Nommage des présentations',
    }

    from System.Windows.Controls import DataGridCell as _DGCellTpl
    from System.Windows.Media import VisualTreeHelper as _VTHTpl
    from System.Windows import Thickness as _Thickness
    from System.Windows.Controls import ContextMenu as _CtxMenu
    from System.Windows.Controls import MenuItem as _MenuItem
    from System.Windows.Controls.Primitives import PlacementMode as _PlacementMode
    from System.Windows.Media import Brushes as _Brushes

    # Jetons {xxx} d'un template, pour reperer une variable mal orthographiee.
    _TOKEN_RE_TPL = re.compile(u'\\{([^{}]*)\\}')
    _BrushAide   = _Brushes.SlateGray
    _BrushErreur = _Brushes.Firebrick

    def _cellule_parente(source):
        """Remonte l'arbre visuel jusqu'a la DataGridCell contenant 'source'."""
        _o = source
        while _o is not None and not isinstance(_o, _DGCellTpl):
            try:
                _o = _VTHTpl.GetParent(_o)
            except Exception:
                return None
        return _o

    def _ouvrir_panneau_template(row_view, cle_table):
        """Ouvre le panneau et ecrit le resultat dans la cellule 'template'."""
        _row_id = str(row_view['id']) if row_view['id'] is not None else u''
        _row_lbl = str(row_view['label']) if row_view['label'] is not None else u''
        _vars, _casse_ok = _variables_pour(cle_table, _row_id)

        _xaml = os.path.join(os.path.dirname(__file__), 'TemplateBuilderDialog.xaml')
        _dlg = forms.WPFWindow(_xaml)
        _dlg.Title = u"Composer — {}".format(_row_lbl or _row_id)
        _dlg.txtContexte.Text = (
            u"Table « {} »  •  ligne « {} »  (identifiant : {})".format(
                _LIBELLES_TABLE.get(cle_table, cle_table), _row_lbl, _row_id))
        _dlg.txtTemplate.Text = (
            str(row_view['template']) if row_view['template'] is not None else u'')

        _AIDE = (
            u"Cliquez sur une variable pour choisir sa casse, puis l'insérer "
            u"à la position du curseur. Les variables vides sont retirées "
            u"avec leur séparateur « - »."
            if _casse_ok else
            u"Cette table sert à analyser des noms existants : les variantes "
            u"de casse n'y sont pas applicables, la variable est insérée telle "
            u"quelle.")
        _dlg.txtApercu.Foreground = _BrushAide
        _dlg.txtApercu.Text = _AIDE

        def _inserer_jeton(_jeton):
            """Insere le jeton a la position du curseur."""
            _txt = _dlg.txtTemplate.Text or u''
            _pos = _dlg.txtTemplate.SelectionStart
            _len = _dlg.txtTemplate.SelectionLength
            _dlg.txtTemplate.Text = _txt[:_pos] + _jeton + _txt[_pos + _len:]
            _dlg.txtTemplate.SelectionStart = _pos + len(_jeton)
            _dlg.txtTemplate.SelectionLength = 0
            _dlg.txtTemplate.Focus()

        def _menu_casse(_btn, _ident):
            """Menu deroulant sous le bouton : une entree par casse."""
            _menu = _CtxMenu()
            _menu.PlacementTarget = _btn
            _menu.Placement = _PlacementMode.Bottom
            for _desc_c, _fn in _CASSES:
                _jeton = _fn(_ident)
                _mi = _MenuItem()
                _mi.Header = u'{}      {}'.format(_jeton, _desc_c)
                _mi.Click += (lambda _j: (lambda s, e: _inserer_jeton(_j)))(_jeton)
                _menu.Items.Add(_mi)
            _menu.IsOpen = True

        # Style "pilule" (bords totalement arrondis) defini dans les
        # ressources du XAML — voir NMPillVarButton pour le detail (forme
        # uniquement, couleurs neutres deja utilisees dans l'application).
        _style_pilule = _dlg.Resources[u'NMPillVarButton']

        for _ident, _desc in _vars:
            _btn = _WpfButton()
            _btn.Content = u'{%s}' % _ident
            _btn.Style = _style_pilule
            _btn.Margin = _Thickness(0, 0, 6, 6)
            # Capture de _ident / _btn par application immediate : sinon toutes
            # les lambdas partageraient la derniere valeur de la boucle.
            if _casse_ok and _ident not in _VARS_SANS_CASSE:
                _btn.ToolTip = u'{}\nCliquez pour choisir la casse.'.format(_desc)
                _btn.Click += (lambda _i, _b: (
                    lambda s, e: _menu_casse(_b, _i)))(_ident, _btn)
            else:
                if _ident in _VARS_SANS_CASSE:
                    _btn.ToolTip = (u'{}\nDisponible en valeur brute '
                                    u'uniquement.'.format(_desc))
                else:
                    _btn.ToolTip = _desc
                _btn.Click += (lambda _i: (
                    lambda s, e: _inserer_jeton(u'{%s}' % _i)))(_ident)
            _dlg.pnlVariables.Children.Add(_btn)

        def _effacer(s, e):
            _dlg.txtTemplate.Text = u''
            _dlg.txtApercu.Foreground = _BrushAide
            _dlg.txtApercu.Text = _AIDE
            _dlg.txtTemplate.Focus()

        _admis = set(_i.lower() for _i, _ in _vars)

        def _jetons_inconnus(_tpl):
            """Jetons {xxx} du template ne figurant pas parmi les variables."""
            _res = []
            for _brut in _TOKEN_RE_TPL.findall(_tpl or u''):
                _nom = _brut.split(u':')[0] if u':' in _brut else _brut
                if not _nom.strip():
                    continue
                if _nom.lower() not in _admis and _nom not in _res:
                    _res.append(_nom)
            return _res

        def _appliquer(s, e):
            # Un jeton inconnu serait recopie tel quel dans le nom de
            # l'element Revit : on refuse l'enregistrement.
            _mauvais = _jetons_inconnus(_dlg.txtTemplate.Text)
            if _mauvais:
                _dlg.txtApercu.Foreground = _BrushErreur
                _dlg.txtApercu.Text = (
                    u"Variable inconnue : {}  —  elle serait recopiée telle "
                    u"quelle dans le nom. Utilisez les boutons ci-dessous ou "
                    u"corrigez l'orthographe.".format(
                        u", ".join(u"{%s}" % _m for _m in _mauvais)))
                _dlg.txtTemplate.Focus()
                return
            setattr(_dlg, 'DialogResult', True)

        _dlg.btnEffacer.Click   += _effacer
        _dlg.btnAppliquer.Click += _appliquer
        _dlg.btnAnnuler.Click   += lambda s, e: setattr(_dlg, 'DialogResult', False)

        if _dlg.show_dialog():
            row_view.Row['template'] = _dlg.txtTemplate.Text or u''

    def _brancher_panneau_template(grid, cle_table):
        """
        Ouvre le panneau au clic sur une cellule "Template" de 'grid' et
        empeche l'edition en place de cette colonne.
        """
        def _on_click(s, e):
            try:
                _cell = _cellule_parente(e.OriginalSource)
                if _cell is None:
                    return
                if str(_cell.Column.Header or u'') != u'Template':
                    return
                _ctx = getattr(_cell, 'DataContext', None)
                if _ctx is None or not hasattr(_ctx, 'Row'):
                    return
                e.Handled = True
                _ouvrir_panneau_template(_ctx, cle_table)
            except Exception:
                # En cas d'echec, on laisse le comportement standard du
                # DataGrid reprendre la main plutot que de bloquer l'edition.
                pass

        def _on_begin_edit(s, e):
            # Filet pour le clavier (F2, saisie directe) : on annule l'edition
            # en place, la colonne se modifie uniquement via le panneau.
            try:
                if str(e.Column.Header or u'') == u'Template':
                    e.Cancel = True
                    _ouvrir_panneau_template(e.Row.Item, cle_table)
            except Exception:
                pass

        grid.PreviewMouseLeftButtonDown += _on_click
        grid.BeginningEdit += _on_begin_edit

    _dt_vue_nm = SysDataTable()
    _dt_vue_nm.Columns.Add('label')
    _dt_vue_nm.Columns.Add('id')
    _dt_vue_nm.Columns.Add('template')
    _dt_vue_nm.Columns.Add('vues_et_dwg', _SysBool)
    _dt_vue_nm.Columns.Add('vues_plus',   _SysBool)
    _dt_vue_nm.Columns.Add('pieces_3d',   _SysBool)
    # Casse : un jeton tout en minuscules force les minuscules. Les valeurs qui
    # doivent rester telles quelles portent donc ':val' (voir l'infobulle de la
    # table "Nommage des vues").
    _defaut_nommage_vues = [
        {'label': u"Plan d'\xe9tage",           'id': u'vue-plan',       'template': u'{vue-pers-titre:val} - {niveau}',                              'vues_et_dwg': True,  'vues_plus': True},
        {'label': u"Plan de faux plafond",      'id': u'vue-plaf',       'template': u'{vue-pers-titre:val} - {niveau}',                              'vues_et_dwg': True,  'vues_plus': True},
        {'label': u"Vue en plan (Structure)",   'id': u'vue-structure',  'template': u'{vue-pers-titre:val} - {niveau}',                              'vues_et_dwg': True,  'vues_plus': True},
        {'label': u"Plan de surface",           'id': u'vue-surface',    'template': u'{vue-pers-titre:val} - {niveau}',                              'vues_et_dwg': False, 'vues_plus': False},
        {'label': u"Coupe",                     'id': u'vue-coupe',      'template': u'{vue-pers-titre:val} - COUPE',                                 'vues_et_dwg': False, 'vues_plus': False},
        {'label': u"\xc9l\xe9vation",           'id': u'vue-elevation',  'template': u'{vue-pers-titre:val} - ELEVATION',                             'vues_et_dwg': False, 'vues_plus': False},
        {'label': u"Vue 3D",                    'id': u'vue-3d',         'template': u'{vue-pers-titre:val} - 3D',                                    'vues_et_dwg': False, 'vues_plus': False, 'pieces_3d': True},
        {'label': u"Vue de dessin",             'id': u'vue-dessin',     'template': u'{vue-pers-titre:val} - {vue-pers-valeur-1:val} - {vue-pers-valeur-2:val}', 'vues_et_dwg': True,  'vues_plus': True},
        {'label': u"L\xe9gende",               'id': u'vue-legende',    'template': u'{vue-pers-titre:val} - {vue-pers-valeur-1:val} - {vue-pers-valeur-2:val}', 'vues_et_dwg': True,  'vues_plus': True},
        # Nomenclature : famille a part, non creable par Vues + / Lier CAO /
        # Pieces 3D, et sans type de vue personnalise (table dediee dans
        # l'onglet "Nomenclatures"). Seules variables : {categorie}, {phase}
        # et {type-nomenclature}.
        {'label': u"Nomenclature",              'id': u'vue-nomenclature', 'template': u'{CATEGORIE} - {phase:val} - {type-nomenclature:val}', 'vues_et_dwg': False, 'vues_plus': False},
    ]
    for _v in (cnv.get('nommage_vues') or _defaut_nommage_vues):
        _rv = _dt_vue_nm.NewRow()
        _rv['label']      = _v.get('label', _v.get('famille', ''))
        _rv['id']         = _v.get('id', '')
        _rv['template']   = _v.get('template', '')
        _rv['vues_et_dwg'] = bool(_v.get('vues_et_dwg', False))
        _rv['vues_plus']   = bool(_v.get('vues_plus',   _v.get('vues_et_dwg', False)))
        # Seule la ligne "Vue 3D" peut porter ce flag (imposé côté dialogue
        # de disponibilité) ; les autres restent forcées à False par sécurité.
        _rv['pieces_3d']   = bool(_v.get('pieces_3d', False)) and _rv['id'] == u'vue-3d'
        _dt_vue_nm.Rows.Add(_rv)
    # Migration : les config.json anterieurs a l'ajout des nomenclatures n'ont
    # pas la ligne "Nomenclature". On l'injecte depuis les valeurs par defaut
    # pour qu'elle apparaisse sans avoir a reinitialiser la configuration.
    if not any(str(_r['id']) == u'vue-nomenclature' for _r in _dt_vue_nm.Rows):
        _v_nom = next(_d for _d in _defaut_nommage_vues
                      if _d['id'] == u'vue-nomenclature')
        _rv = _dt_vue_nm.NewRow()
        _rv['label']         = _v_nom['label']
        _rv['id']            = _v_nom['id']
        _rv['template']      = _v_nom['template']
        _rv['vues_et_dwg']   = False
        _rv['vues_plus']     = False
        _rv['pieces_3d']     = False
        _dt_vue_nm.Rows.Add(_rv)
    wpf.dgNommageVues.ItemsSource = _dt_vue_nm.DefaultView

    # ── Premier calcul des colonnes dérivées de « Vues personnalisées » ───────
    # ICI et pas plus haut : ces colonnes recopient en texte les familles de
    # vues, qui se lisent dans la grille ci-dessus. Les calculer avant qu'elle
    # ne soit peuplée les remplirait de vide — la recherche et les filtres
    # d'en-tête ne trouveraient alors plus rien sur ces six colonnes.
    _tvp_api['maj_derivees']()
    _tvp_api['appliquer_filtre']()

    # Les handlers Checked/Unchecked des dialogues de disponibilite sont poses
    # sur la grille entiere : ce helper permet de savoir a quelle colonne
    # appartient la case cochee, sinon un clic sur n'importe quelle colonne
    # declencherait la logique de toutes les autres.
    from System.Windows.Controls.Primitives import ToggleButton as _ToggleBtnCommon

    def _binding_path(_cb):
        """Nom de la colonne liee a la case a cocher, ou '' si indeterminable."""
        try:
            _be = _cb.GetBindingExpression(_ToggleBtnCommon.IsCheckedProperty)
            return _be.ParentBinding.Path.Path if _be is not None else u''
        except Exception:
            return u''

    # ── Bouton Disponibilite Vues + DWG ───────────────────────────────────────
    def _open_vues_et_dwg_dispo(sender, args):
        _dlg_xaml = os.path.join(os.path.dirname(__file__), 'VuesEtDWGDispoDialog.xaml')
        _dlg = forms.WPFWindow(_dlg_xaml)
        _dlg.Title = u"Disponibilit\xe9s familles de vues"
        from System.Data import DataTable as _DT_dispo
        from System import Boolean as _SysBoolDlg
        _dt_dispo = _DT_dispo()
        _dt_dispo.Columns.Add('label')
        # Colonne non affichee : sert de cle stable aux DataTriggers du XAML
        # (plus fiable que 'label', qui porte des accents et peut etre renomme).
        _dt_dispo.Columns.Add('id')
        _dt_dispo.Columns.Add('vues_et_dwg', _SysBoolDlg)
        _dt_dispo.Columns.Add('vues_plus',   _SysBoolDlg)
        _dt_dispo.Columns.Add('pieces_3d',   _SysBoolDlg)
        for _r in _dt_vue_nm.Rows:
            _dr = _dt_dispo.NewRow()
            _dr['label']      = str(_r['label']) if _r['label'] is not None else u''
            _dr['id']         = str(_r['id'])    if _r['id']    is not None else u''
            _dr['vues_et_dwg'] = bool(_r['vues_et_dwg']) if _r['vues_et_dwg'] is not None else False
            _dr['vues_plus']   = bool(_r['vues_plus'])   if _r['vues_plus']   is not None else False
            _dr['pieces_3d']   = bool(_r['pieces_3d'])   if _r['pieces_3d']   is not None else False
            _dt_dispo.Rows.Add(_dr)
        _dlg.dgDispo.ItemsSource = _dt_dispo.DefaultView

        # Écriture explicite des cases à cocher dans la DataRow lors du
        # (dé)cochage : les trois colonnes portent un ElementStyle/
        # EditingElementStyle personnalisé (grisage de certaines lignes) qui,
        # en pratique, empêche le binding TwoWay standard de committer
        # correctement la valeur — on ne se fie donc pas qu'au binding, on
        # écrit aussi en dur depuis le code, comme pour l'exclusivité de
        # "Vues personnalisées".
        from System.Windows.Controls import CheckBox as _WpfCheckBox2
        from System.Windows.Controls.Primitives import ToggleButton as _ToggleBtn2

        # Familles non prises en charge par 03_Vues.panel/01_Vues_+ : leur case
        # "Vues +" est grisee dans le XAML et forcee a False ici.
        _VP_NON_GEREES = (u'vue-coupe', u'vue-elevation', u'vue-nomenclature')
        # Idem pour 04_Lier_importer.panel/01_Lier_CAO, colonne "Lier CAO → Vues".
        _VED_NON_GEREES = (u'vue-coupe', u'vue-elevation', u'vue-3d',
                           u'vue-nomenclature')

        def _on_dispo_vue_toggled(sender, e, _val):
            _cb = e.OriginalSource
            if not isinstance(_cb, _WpfCheckBox2):
                return
            # Le handler est pose sur la grille entiere : on aiguille selon la
            # colonne, sinon un clic sur "Lier CAO" ou "Vues +" ecraserait
            # pieces_3d.
            _col = _binding_path(_cb)
            _row_ctx = getattr(_cb, 'DataContext', None)
            if _row_ctx is None or not hasattr(_row_ctx, 'Row'):
                return

            if _col == u'vues_plus':
                # Cette colonne porte elle aussi un ElementStyle personnalise :
                # meme precaution que pour pieces_3d, on ecrit en dur.
                _row_ctx.Row['vues_plus'] = (
                    _val and str(_row_ctx['id']) not in _VP_NON_GEREES)
                return

            if _col == u'vues_et_dwg':
                _row_ctx.Row['vues_et_dwg'] = (
                    _val and str(_row_ctx['id']) not in _VED_NON_GEREES)
                return

            if _col != u'pieces_3d':
                return
            if str(_row_ctx['label']) != u'Vue 3D':
                _row_ctx.Row['pieces_3d'] = False
                return
            _row_ctx.Row['pieces_3d'] = _val

        _dlg.dgDispo.AddHandler(
            _ToggleBtn2.CheckedEvent,
            RoutedEventHandler(lambda s, e: _on_dispo_vue_toggled(s, e, True)))
        _dlg.dgDispo.AddHandler(
            _ToggleBtn2.UncheckedEvent,
            RoutedEventHandler(lambda s, e: _on_dispo_vue_toggled(s, e, False)))

        def _on_ok_dispo_vue(s, e):
            # Force la validation de la cellule/ligne en cours d'édition avant
            # de refermer : un clic direct sur "OK" (hors de la grille) ne
            # déclenche pas toujours le commit des autres colonnes éditées.
            _commit_datagrid_edit(_dlg.dgDispo)
            setattr(_dlg, 'DialogResult', True)

        _dlg.btnOk.Click     += _on_ok_dispo_vue
        _dlg.btnCancel.Click += lambda s, e: setattr(_dlg, 'DialogResult', False)
        if _dlg.show_dialog():
            _dispo_rows = list(_dt_dispo.Rows)
            _nm_rows    = list(_dt_vue_nm.Rows)
            for _i, _dr in enumerate(_dispo_rows):
                if _i < len(_nm_rows):
                    # Meme logique que "Vues +" ci-dessous : le XAML grise
                    # Coupe / Elevation / Vue 3D, on force aussi la valeur ici
                    # pour assainir une config existante.
                    _nm_rows[_i]['vues_et_dwg'] = (
                        bool(_dr['vues_et_dwg'])
                        and str(_nm_rows[_i]['id']) not in _VED_NON_GEREES)
                    # Le XAML grise "Vues +" pour Coupe et Elevation ; on force
                    # aussi la valeur ici, au cas ou une config existante les
                    # aurait deja a True (elles seraient sinon conservees).
                    _nm_rows[_i]['vues_plus']   = (
                        bool(_dr['vues_plus'])
                        and str(_nm_rows[_i]['id']) not in _VP_NON_GEREES)
                    # Le XAML grise/désactive la case pour toutes les lignes
                    # sauf "Vue 3D" ; on retranscrit tel quel (ce sera False
                    # pour les lignes désactivées).
                    _nm_rows[_i]['pieces_3d']   = bool(_dr['pieces_3d']) and str(_nm_rows[_i]['label']) == u'Vue 3D'

    wpf.btnNommageVuesDispo.Click += _open_vues_et_dwg_dispo

    # ── Nommage niveaux (code) ────────────────────────────────────────────────
    _dt_niv_code_nm = SysDataTable()
    _dt_niv_code_nm.Columns.Add('label')
    _dt_niv_code_nm.Columns.Add('id')
    _dt_niv_code_nm.Columns.Add('template')
    # Identifiant 'niveau-code' (et non 'niveau') pour ne pas preter a confusion
    # avec la variable {niveau} des tables "Nommage des vues" et "des
    # presentations", qui designe le nom du niveau Revit.
    _defaut_nommage_niveaux_code = [
        {'label': 'Niveau (code)', 'id': 'niveau-code',
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
        {'label': 'Niveau Revit', 'id': 'niveau-revit',
         'template': '{construction}_{niveau-code}_{demi-niv}'},
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

    # ── Panneau de composition sur les 5 tables de nommage ────────────────────
    # Branché ici, une fois toutes les ItemsSource affectées.
    _brancher_panneau_template(wpf.dgTemplates,           u'fichiers')
    _brancher_panneau_template(wpf.dgNommageNiveauxCode,  u'niveau-code')
    _brancher_panneau_template(wpf.dgNommageNiveaux,      u'niveau-revit')
    _brancher_panneau_template(wpf.dgNommageVues,         u'vues')
    _brancher_panneau_template(wpf.dgNommagePresent,      u'present')

    # ── Nommage exports ────────────────────────────────────────────────────────

    # Les "Types de niveaux par défaut" ne sont plus un réglage global : ils se
    # configurent par vue personnalisée (colonne du même nom de la table "Vues
    # personnalisées", voir _open_niveaux_defaut_dialog). Les libellés y sont
    # construits dynamiquement depuis la grille des préfixes, ce qui remplace
    # les quatre cases fixes Batiment / Toiture / Fondations / Origine.

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
        _vals = [_v for _v in (_int_or(_row[u'ordre'], None) for _row in _dt_profils.Rows)
                 if _v is not None]
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
            _disc_opts_pv = _profil_vues_remplir(cfg, _dlg_pv, _vues_p)
            _dlg_pv.btnOK.Click     += lambda s2, e2: setattr(_dlg_pv, u'DialogResult', True)
            _dlg_pv.btnCancel.Click += lambda s2, e2: setattr(_dlg_pv, u'DialogResult', False)
            if _dlg_pv.show_dialog():
                _store_p[u'vues'] = _profil_vues_lire(_dlg_pv, _disc_opts_pv)
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

    # ── Types de nomenclatures ────────────────────────────────────────────────
    # Table propre aux nomenclatures : leur axe de declinaison est
    # (categorie x phase x type de nomenclature) et non (niveau x type de vue
    # personnalise). Elle ne passe donc pas par types_vues_personnalises.
    from utils.nomenclatures_types import (
        get_types_nomenclatures as _get_types_nom,
    )
    _dt_types_nom = SysDataTable()
    _dt_types_nom.Columns.Add('label')
    _dt_types_nom.Columns.Add('type_vue')
    for _tn in _get_types_nom(cfg):
        _rtn = _dt_types_nom.NewRow()
        _rtn['label']    = _tn.get(u'label', u'')
        _rtn['type_vue'] = _tn.get(u'type_vue', u'')
        _dt_types_nom.Rows.Add(_rtn)
    wpf.dgTypesNomenclatures.ItemsSource = _dt_types_nom.DefaultView

    # ── Menu contextuel Types de nomenclatures ────────────────────────────────
    # Meme mecanique que "Vues personnalisées" : SelectedItem n'est pas fiable
    # au moment de l'ouverture du menu, on retient l'item vise par le clic droit.
    _tnom_ctx_item = [None]

    def _tnom_right_click(sender, e):
        _obj = e.OriginalSource
        while _obj is not None:
            _dc = getattr(_obj, 'DataContext', None)
            if _dc is not None and hasattr(_dc, 'Row'):
                _tnom_ctx_item[0] = _dc
                wpf.dgTypesNomenclatures.SelectedItem = _dc
                return
            try:
                _obj = _VTH.GetParent(_obj)
            except Exception:
                break
        _tnom_ctx_item[0] = None

    wpf.dgTypesNomenclatures.PreviewMouseRightButtonDown += _tnom_right_click

    _ctx_tnom           = wpf.dgTypesNomenclatures.ContextMenu
    _ctx_tnom_nouvelle  = _ctx_tnom.Items[0]
    _ctx_tnom_dupliquer = _ctx_tnom.Items[1]
    # Items[2] = Separator
    _ctx_tnom_supprimer = _ctx_tnom.Items[3]

    def _tnom_ctx_opened(sender, e):
        _sel = _tnom_ctx_item[0]
        _has_sel = _sel is not None and hasattr(_sel, 'Row')
        _ctx_tnom_dupliquer.IsEnabled = _has_sel
        _ctx_tnom_supprimer.IsEnabled = _has_sel

    _ctx_tnom.Opened += _tnom_ctx_opened

    def _tnom_nouvelle(sender, e):
        _r = _dt_types_nom.NewRow()
        _r['label']    = u''
        _r['type_vue'] = u''
        _dt_types_nom.Rows.Add(_r)

    def _tnom_dupliquer(sender, e):
        _sel = _tnom_ctx_item[0]
        if _sel is None or not hasattr(_sel, 'Row'):
            return
        _base = str(_sel['label']) if _sel['label'] is not None else u''
        _existing = {str(_row['label']) for _row in _dt_types_nom.DefaultView
                     if _row['label'] is not None}
        _idx = 2
        while True:
            _new_lbl = u'{}_{}'.format(_base, _idx)
            if _new_lbl not in _existing:
                break
            _idx += 1
        _r = _dt_types_nom.NewRow()
        _r['label']    = _new_lbl
        _r['type_vue'] = str(_sel['type_vue']) if _sel['type_vue'] is not None else u''
        _dt_types_nom.Rows.Add(_r)

    def _tnom_supprimer(sender, e):
        _sel = _tnom_ctx_item[0]
        if _sel is None or not hasattr(_sel, 'Row'):
            return
        _sel.Row.Delete()

    _ctx_tnom_nouvelle.Click  += _tnom_nouvelle
    _ctx_tnom_dupliquer.Click += _tnom_dupliquer
    _ctx_tnom_supprimer.Click += _tnom_supprimer

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
    def _tvp_usages_manquants():
        """
        Lignes de "Vues personnalisées" enregistrables (label renseigné) dont
        la colonne Usage est vide. Retourne [(label, DataRow)].

        L'usage alimente la variable de nommage {vue-pers-usage} et distingue
        les vues de travail des livrables : le laisser vide produirait des
        noms de vues tronqués sans que rien ne le signale. Le menu déroulant
        ne permet pas de vider la cellule ; le cas vient d'une config.json
        antérieure ou éditée à la main.

        _tvp_lignes(_dt_tvp) et non ItemsSource : une ligne masquée par un filtre
        part quand même dans config.json, elle doit donc être contrôlée comme
        les autres.
        """
        _manquants = []
        for _row_u in _tvp_lignes(_dt_tvp):
            _lbl_u = str(_row_u['label']) if _row_u['label'] is not None else u''
            if not _lbl_u.strip():
                continue          # ligne sans label : ignorée à l'enregistrement
            _usg_u = str(_row_u['usage']) if _row_u['usage'] is not None else u''
            if not _usg_u.strip():
                _manquants.append((_lbl_u, _row_u))
        return _manquants

    def _on_save_click(s, e):
        # "Types de nomenclatures" est une grille librement éditable : un clic
        # direct sur Enregistrer alors qu'une cellule est encore en édition ne
        # déclenche pas son commit, et la saisie serait perdue.
        _commit_datagrid_edit(wpf.dgTypesNomenclatures)
        # Idem pour "Vues personnalisées" : un Usage choisi juste avant le clic
        # doit être committé AVANT d'être contrôlé, sinon on refuserait un
        # enregistrement pourtant valide.
        _commit_datagrid_edit(wpf.dgTypesVues)

        # Usage obligatoire sur chaque vue personnalisée. Ne pas affecter
        # DialogResult laisse la fenêtre ouverte, donc toutes les autres
        # saisies intactes.
        _manque_usage = _tvp_usages_manquants()
        if _manque_usage:
            from dialogs.dialogs_styles_loader import show_alert
            wpf.tabPrincipal.SelectedItem = wpf.tabVues
            _tvp_montrer_ligne(wpf.dgTypesVues, _dt_tvp,
                               _tvp_api['reset_filtres'], _manque_usage[0][1])
            show_alert(
                u"Usage obligatoire",
                u"La colonne « Usage » doit être renseignée pour chaque vue "
                u"personnalisée. Elle est vide pour :\n\n  • {}\n\n"
                u"Choisissez « Temporaire » ou « Livrable » pour "
                u"{}, puis enregistrez à nouveau.".format(
                    u"\n  • ".join(_l for _l, _i in _manque_usage),
                    u"cette ligne" if len(_manque_usage) == 1
                    else u"ces lignes"),
                close_label=u"Retour")
            return

        # Disciplines : le référentiel est relu par d'autres scripts, un code
        # en double ou une sous-discipline orpheline y produirait des résultats
        # silencieusement faux. Le bandeau de l'onglet les signale en continu ;
        # ici, elles AVERTISSENT sans bloquer.
        #
        # Le refus pur laissait l'utilisateur sans issue : changer la structure
        # de la table peut invalider toutes les lignes d'un coup, et il ne
        # restait alors que « Annuler », qui jette le travail. Une heure de
        # saisie perdue pour se protéger d'un état incohérent est un mauvais
        # échange — d'autant que l'état incohérent, lui, se corrige.
        _commit_datagrid_edit(wpf.dgDisciplines)
        _disc_api['recalculer']()
        # Les anomalies sont des (texte, ligne) : seul le texte se lit ici, la
        # ligne sert au saut depuis le bandeau de l'onglet.
        _anos_disc = [_t for _t, _l in _disc_api['anomalies']]
        if _anos_disc:
            from dialogs.dialogs_styles_loader import show_confirm
            wpf.tabPrincipal.SelectedItem = wpf.tabDisciplines
            # Liste tronquée : un référentiel dont le format vient de changer
            # produit autant d'anomalies que de lignes, et la boîte deviendrait
            # plus longue que l'écran. Le bandeau de l'onglet, lui, reste
            # consultable en entier.
            _extrait = _anos_disc[:10]
            _reste = len(_anos_disc) - len(_extrait)
            # "yes" porte le bouton large et accentue (NMButtonAppliquer),
            # "no" le bouton etroit et neutre (NMButtonAnnuler) — c'est le
            # pied de dialogue standard de show_confirm, inchange. Ce qui
            # change ICI : quelle action porte lequel des deux labels. Le
            # choix SUR sera desormais toujours le grand bouton bleu ; le
            # choix qui ecrit un referentiel connu casse reste le petit
            # bouton gris, jamais l'inverse.
            if show_confirm(
                    u"Disciplines : {} anomalie(s)".format(len(_anos_disc)),
                    u"Le référentiel sera enregistré TEL QUEL, anomalies "
                    u"comprises. Les outils qui le relisent — étiquetage, "
                    u"nomenclatures, export PLANON — donneront des résultats "
                    u"faux sur les lignes concernées jusqu'à leur "
                    u"correction.\n\n"
                    u"  • {}{}\n\n"
                    u"Corriger avant d'enregistrer ?".format(
                        u"\n  • ".join(_extrait),
                        (u"\n  • … et {} autre(s).".format(_reste)
                         if _reste else u"")),
                    yes_label=u"Corriger d'abord",
                    no_label=u"Enregistrer malgré tout"):
                return

        # Ecriture reelle. La fenetre RESTE OUVERTE : une session de reglages
        # se mene en plusieurs passes, et la fermer a chaque enregistrement
        # faisait reprendre a zero l'onglet, le defilement et les filtres.
        _enregistrer_parametres(wpf, cfg, cfg_path, {
            'etiquettes':             _etiquettes,
            'styles_ordre':           _styles_ordre,
            'disc_api':               _disc_api,
            'tvp_section':            _tvp_section,
            'vm_filtres':             vm_filtres,
            'profils_store':          _profils_store,
            'profil_label_systeme':   _LOCKED_PROFIL_LABEL,
            'profil_defaut_vues':     _DEFAULT_PROFIL_VUES,
            'profil_defaut_options':  _DEFAULT_PROFIL_OPTIONS,
        })

        # Nouvelle reference du garde-fou de fermeture : sans cette remise a
        # jour, « Fermer » reclamerait une confirmation pour des modifications
        # qui viennent precisement d'etre ecrites.
        _win_etat_initial[0] = _win_capturer_etat()

        # Temoin du pied de fenetre. Pose APRES l'ecriture, jamais avant : une
        # erreur d'ecriture remonte depuis save_config et n'arrive donc jamais
        # ici — le temoin ne peut pas annoncer un enregistrement qui a echoue.
        from System import DateTime as _DtNow
        wpf.txtEtatEnregistrement.Text = u"✓  Enregistré à {}".format(
            _DtNow.Now.ToString(u"HH:mm:ss"))

    wpf.btnCancel.Click += lambda s, e: setattr(wpf, 'DialogResult', False)
    wpf.btnSave.Click   += _on_save_click

    # ── Garde-fou de fermeture ────────────────────────────────────────────────
    # Le référentiel des disciplines représente parfois une heure de saisie, et
    # rien ne l'écrit tant qu'on n'a pas cliqué « Enregistrer ». Or « Annuler »
    # porte IsCancel : la touche Échap — réflexe pour vider un champ ou sortir
    # d'une cellule — fermait la fenêtre et jetait tout sans un mot. La croix de
    # la barre de titre faisait de même.
    #
    # Closing est le SEUL point de passage commun aux trois sorties. Le brancher
    # ici couvre Échap, « Annuler » et la croix d'un coup ; le poser sur chacune
    # en aurait forcément oublié une.
    #
    # _disc_api['est_modifie']() ne couvre que Disciplines. Les 9 autres onglets
    # n'écrivent JAMAIS cfg avant l'enregistrement (voir « Lecture et sauvegarde »
    # ci-dessous) : taper dans un champ puis fermer sans enregistrer les perd
    # tout aussi silencieusement, juste sans témoin pour le dire. Plutôt qu'un
    # témoin par contrôle (~50 champs, 11 grilles), un instantané pris à
    # l'ouverture et comparé à la fermeture — une seule fonction couvre les
    # ajouts/suppressions de lignes des grilles aussi bien que le texte saisi.
    _WIN_TXT_NOMS = (
        'el_nb_rep_parents', 'nc_val_nul', 'nc_val_bim2d',
        'cn_eleva_rdc', 'cn_eleva_origine', 'cn_espacement',
        'tc_styles_r', 'tc_styles_g', 'tc_styles_b',
        'tc_types_r', 'tc_types_g', 'tc_types_b',
        'tc_occur_r', 'tc_occur_g', 'tc_occur_b',
        'tc_pres_r', 'tc_pres_g', 'tc_pres_b',
        'cc_readonly_r', 'cc_readonly_g', 'cc_readonly_b',
        'cc_types_r', 'cc_types_g', 'cc_types_b',
        'cc_occur_r', 'cc_occur_g', 'cc_occur_b',
        'dwg_layers', 'dwg_color_mode', 'dwg_unit', 'dwg_placement',
        'sf_table_styles', 'sf_param_style', 'sf_col_calcul_style',
        'sf_col_commentaire_style', 'sf_default_shon', 'sf_col_shon',
        'sf_param_shon', 'sf_param_shon_auteur', 'sf_col_shob', 'sf_param_shob',
        'sf_param_shob_auteur', 'sf_default_plancher', 'sf_col_plancher',
        'sf_param_s_plancher', 'sf_param_s_plancher_auteur',
        'sf_qualifications', 'sf_col_filter', 'maj_source_url',
    )
    _WIN_CHK_NOMS = (
        'dwg_include_sub', 'dwg_correct_lines', 'dwg_view_only',
        'net_dwg_imports', 'net_dwg_liens', 'net_lignes', 'net_texts',
        'net_pieces', 'net_zones', 'log_activer',
    )
    _WIN_GRILLE_NOMS = (
        'dgGroupes', 'dgPrefixes', 'dgSensNiveaux', 'dgTemplates',
        'dgNommageNiveauxCode', 'dgNommageNiveaux', 'dgNommageVues',
        'dgNommagePresent', 'dgTypesVues', 'dgTypesNomenclatures',
        'dgProfilsLiaison',
    )

    # Colonnes de TRAVAIL, jamais enregistrees : elles changent sans qu'aucune
    # donnee ne soit modifiee, et les compter ferait reclamer une confirmation
    # de fermeture a qui n'a fait que chercher ou filtrer.
    #   `visible` : porte le RowFilter de la vue, reecrite a chaque frappe
    #               dans la recherche et a chaque filtre d'en-tete ;
    #   `ordre_cle` : cle de tri derivee de `ordre`, qui est deja compare —
    #               une vraie modification de « Ord. » reste donc detectee.
    # Les colonnes derivees f_* RESTENT comparees : elles recopient ce que
    # reglent les boutons « Configurer… », dont les stores ne sont pas
    # photographies autrement. Sans elles, changer une famille de vues puis
    # fermer ne demanderait rien et perdrait le reglage en silence.
    #   `label_prec` : memoire du Label d'avant la derniere edition, qui sert
    #               a suivre la ligne dans les tables satellites. Elle vaut
    #               toujours le Label courant hors edition — la comparer
    #               reviendrait a compter deux fois la meme colonne.
    _WIN_COLS_TRAVAIL = ('visible', 'ordre_cle', 'label_prec')

    def _win_capturer_etat():
        # Import LOCAL : un nom de plus dans main() capturé par une fonction
        # imbriquée, c'est une place de plus dans le tuple de scope IronPython.
        from System.Data import DataRowState as _WinRowState
        _etat = [getattr(wpf, _n).Text for _n in _WIN_TXT_NOMS]
        _etat += [bool(getattr(wpf, _n).IsChecked) for _n in _WIN_CHK_NOMS]
        for _n in _WIN_GRILLE_NOMS:
            _tbl = getattr(wpf, _n).ItemsSource.Table
            _cols = [_c.ColumnName for _c in _tbl.Columns
                     if _c.ColumnName not in _WIN_COLS_TRAVAIL]
            # Les lignes supprimees restent dans Rows tant que la table n'a
            # pas accepte les changements, et lire une de leurs cellules leve
            # DeletedRowInaccessibleException. Elles comptent quand meme comme
            # une modification : la table en a une de moins qu'a l'ouverture,
            # et le tuple resultant differe donc bien de l'etat initial.
            _etat.append(tuple(
                tuple(str(_r[_c]) for _c in _cols) for _r in _tbl.Rows
                if _r.RowState != _WinRowState.Deleted))
        # Valeurs par defaut des types de vues : elles ne vivent dans aucune
        # grille ni aucun controle, les regler puis fermer ne demanderait rien
        # sans cette ligne.
        _etat.append(tuple(sorted(_types_vues_defaut[0].items())))
        return tuple(_etat)

    # Pris ICI : tous les onglets sont deja peuples (le code au-dessus les
    # remplit tour a tour), et rien n'a encore ete propose a la saisie.
    # Dans une liste : « Enregistrer » le remplace desormais a chaque
    # ecriture, et IronPython 2.7 n'a pas de `nonlocal`.
    _win_etat_initial = [_win_capturer_etat()]

    def _on_closing(s, e):
        # DialogResult vrai = fermeture demandee par le code, pas par
        # l'utilisateur. Ce n'est plus le cas de « Enregistrer », qui ne ferme
        # plus rien : la comparaison ci-dessous suffit desormais a trancher.
        if getattr(wpf, 'DialogResult', None):
            return
        _dirty_disc   = _disc_api['est_modifie']()
        _dirty_autres = (_win_capturer_etat() != _win_etat_initial[0])
        if not (_dirty_disc or _dirty_autres):
            return
        from dialogs.dialogs_styles_loader import show_confirm as _confirm_fin
        if _dirty_disc and _dirty_autres:
            _msg = (u"Cette fenêtre contient des modifications qui n'ont pas "
                    u"été enregistrées, dans l'onglet « Disciplines » et "
                    u"ailleurs.\n\nElles seront perdues.")
        elif _dirty_disc:
            _msg = (u"L'onglet « Disciplines » contient des modifications qui "
                    u"n'ont pas été enregistrées.\n\nElles seront perdues.")
        else:
            _msg = (u"Cette fenêtre contient des modifications qui n'ont pas "
                    u"été enregistrées.\n\nElles seront perdues.")
        # Meme inversion que la boite d'enregistrement : le grand bouton bleu
        # est toujours le choix SUR (revenir saisir), jamais celui qui perd
        # du travail.
        if _confirm_fin(
                u"Fermer sans enregistrer", _msg,
                yes_label=u"Revenir à la saisie",
                no_label=u"Abandonner les modifications"):
            e.Cancel = True

    wpf.Closing += _on_closing

    # Le resultat n'est plus lu : « Enregistrer » ecrit sans fermer, et
    # « Fermer » n'ecrit rien. Tout ce qui suivait cet appel vit desormais
    # dans _enregistrer_parametres, appelee par le bouton.
    wpf.show_dialog()


def _enregistrer_parametres(wpf, cfg, cfg_path, ctx):
    """
    Relit les onze onglets et ecrit config.json. Appelable AUTANT DE FOIS
    qu'on veut sur la meme fenetre : c'est ce qui permet a « Enregistrer » de
    ne plus fermer les Parametres.

    Fonction de MODULE et non un bloc de main(), pour la meme raison que
    _init_disciplines et _init_tvp_recherche : IronPython 2.7 plafonne le
    nombre de variables locales d'une fonction, et main() etait deja au bord —
    le depassement se manifeste par un « Sequence contains no elements »
    pointant une ligne sans rapport.

    `ctx` porte ce que la fenetre tient hors des controles WPF : les stores
    des dialogues, le referentiel des disciplines, les valeurs par defaut des
    profils.

    IDEMPOTENCE : chaque section reconstruit cfg en entier a partir de
    l'interface, et rien ici ne consomme un etat a usage unique. Deux
    enregistrements de suite ecrivent donc exactement le meme fichier.
    """
    _etiquettes    = ctx['etiquettes']
    _styles_ordre  = ctx['styles_ordre']
    _disc_api      = ctx['disc_api']
    _tvp_section   = ctx['tvp_section']
    vm_filtres     = ctx['vm_filtres']
    _profils_store = ctx['profils_store']
    _LOCKED_PROFIL_LABEL    = ctx['profil_label_systeme']
    _DEFAULT_PROFIL_VUES    = ctx['profil_defaut_vues']
    _DEFAULT_PROFIL_OPTIONS = ctx['profil_defaut_options']

    # ── Lecture et sauvegarde ─────────────────────────────────────────────────

    # Surfaces
    # L'interrupteur d'etiquetage n'a AUCUN controle ici : il vit dans la
    # palette « Surfaces », qui l'ecrit directement dans config.json. Comme
    # cette section est reconstruite en entier, il faut le recopier — et le
    # relire SUR LE DISQUE pour ne pas ecraser un basculement fait dans la
    # palette pendant que cette fenetre etait ouverte. Voir _lire_cle_disque.
    _etiq_actif = bool(_lire_cle_disque(
        cfg_path, 'surface', 'etiquettes_actif',
        (cfg.get('surface') or {}).get('etiquettes_actif', False)))
    _etiq_defaut, _etiq_par_calcul = _etiquettes_vers_config(_etiquettes[0])
    cfg['surface'] = {
        'table_styles_schedule':    txt(wpf, 'sf_table_styles'),
        'etiquettes_actif':         _etiq_actif,
        'etiquette_defaut':         _etiq_defaut,
        'etiquettes_par_calcul':    _etiq_par_calcul,
        'param_style':              txt(wpf, 'sf_param_style'),
        'col_calcul_style':         txt(wpf, 'sf_col_calcul_style'),
        # Liste ORDONNÉE : la position vaut l'ordre d'affichage dans la palette.
        # Liste ORDONNÉE, deux couleurs par style : 'couleur' pour la bande du
        # bouton dans la palette, 'couleur_plan' pour le choix de couleurs Revit.
        'styles_palette':           list(_styles_ordre),
        'col_commentaire_style':    txt(wpf, 'sf_col_commentaire_style'),
        'param_shon':               txt(wpf, 'sf_param_shon'),
        'param_shob':               txt(wpf, 'sf_param_shob'),
        'param_s_plancher':         txt(wpf, 'sf_param_s_plancher'),
        'param_shon_auteur':        txt(wpf, 'sf_param_shon_auteur'),
        'param_shob_auteur':        txt(wpf, 'sf_param_shob_auteur'),
        'param_s_plancher_auteur':  txt(wpf, 'sf_param_s_plancher_auteur'),
        'qualifications_auteur':    lignes_non_vides(txt(wpf, 'sf_qualifications')),
        'col_shon':                 txt(wpf, 'sf_col_shon'),
        'col_shob':                 txt(wpf, 'sf_col_shob'),
        'col_plancher':             txt(wpf, 'sf_col_plancher'),
        'col_filter':               txt(wpf, 'sf_col_filter'),
        'default_shon_schedule':    txt(wpf, 'sf_default_shon'),
        'default_plancher_schedule':txt(wpf, 'sf_default_plancher'),
    }

    # Disciplines
    # _disc_api['lignes']() et NON ItemsSource : la vue est filtrée par la recherche
    # et par le repli de niveau, enregistrer depuis elle perdrait toutes les
    # lignes masquées à l'écran. Elle est déjà triée par Code Ouvrage, la table part
    # donc dans l'ordre hiérarchique, lisible telle quelle dans config.json.
    # 'code_ouvrage', 'niveau' et les deux abréviations résolues sont écrits À
    # CÔTÉ des colonnes dont ils dérivent : les scripts consommateurs lisent une
    # seule clé, sans avoir à redécouper le code ni à remonter la branche. C'est
    # 'code_ouvrage' qui identifie une ligne — 'code' est partagé par toute une
    # branche dès qu'on descend sous le dernier niveau du Code.
    # Le MEME assembleur que le bouton « Enregistrer » de l'onglet : un
    # aller-retour par fichier .NM-DisciplinesConfig doit rendre exactement ce
    # que config.json contient.
    cfg['disciplines'] = _disc_section(
        _disc_api['format'](), _disc_api['lignes'](), _disc_api['txt'])
    # Le travail est desormais dans config.json : le temoin n'a plus lieu
    # d'etre. La fenetre se ferme juste apres, mais un enregistrement refuse
    # plus loin la laisserait ouverte avec un temoin devenu faux.
    _disc_api['oublier_modifie']()

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

    # Vues personnalisées : les SEPT tables d'un coup.
    # Le MEME assembleur que « Fichier > Exporter la configuration… » de
    # l'onglet, pour la même raison que les disciplines : un aller-retour par
    # fichier .NM-VuesPersConfig doit rendre exactement ce que config.json
    # contient. Les invariants qui s'y tiennent (ligne système « PIECES 3D »
    # figée sur sa famille et seule à porter la case du même nom, table
    # satellite vide = « tout disponible », types de niveaux hérités de
    # l'ancien réglage global tant qu'un label n'a pas été configuré) sont
    # décrits dans _tvp_section.
    for _cle_tvp, _val_tvp in _tvp_section().items():
        cfg[_cle_tvp] = _val_tvp

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
        _p3d = bool(_row['pieces_3d'])   if _row['pieces_3d']   is not None else False
        if _lbl or _id:
            nommage_vues_out.append({
                'label': _lbl, 'id': _id, 'template': _tpl,
                'vues_et_dwg': _ved, 'vues_plus': _vp, 'pieces_3d': _p3d,
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

    # Vues en masse : ancien reglage GLOBAL des filtres de types de niveaux.
    # Il n'a plus d'interface — le reglage est desormais par vue personnalisee
    # (cle 'niveaux_defaut_types_pers' ci-dessus). On le recopie inchange :
    # il reste la valeur de reprise d'un label absent de la nouvelle table
    # (config editee a la main, label cree hors interface).
    cfg.setdefault('vues_en_masse', {})['filtres_types_niveaux_defaut'] = dict(
        (_k, bool(_v)) for _k, _v in vm_filtres.items())

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
        # Completer par les defauts plutot que recopier tel quel : un profil
        # ecrit avant l'ajout de `discipline` / `phase` ressort avec le schema
        # complet, sans perdre ce qu'il portait deja.
        _vues_entry = dict(_DEFAULT_PROFIL_VUES)
        _vues_entry.update(_store_entry.get(u'vues', {}))
        _opts_entry = dict(_DEFAULT_PROFIL_OPTIONS)
        _opts_entry.update(_store_entry.get(u'options_liaisons', {}))
        profils_out.append({
            u'ordre':   _int_or(_ord_p, 999),
            u'label':   _lbl_p,
            u'systeme': _sys_p,
            u'options_liaisons': _opts_entry,
            u'vues':             _vues_entry,
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
    # Types de nomenclatures (onglet Nomenclatures)
    # Les lignes sans label sont ignorées : la grille autorise l'ajout de
    # lignes vides et le label est la clé de la case à cocher côté script de
    # création. Les doublons de label le seraient aussi, on ne garde que le
    # premier.
    types_nom_out = []
    _labels_nom_vus = set()
    for _row in wpf.dgTypesNomenclatures.ItemsSource:
        _lbl_n = str(_row['label']).strip() if _row['label'] is not None else ''
        _tv_n  = str(_row['type_vue']).strip() if _row['type_vue'] is not None else ''
        if _lbl_n and _lbl_n not in _labels_nom_vus:
            _labels_nom_vus.add(_lbl_n)
            types_nom_out.append({'label': _lbl_n, 'type_vue': _tv_n})
    cfg['nomenclatures_types'] = types_nom_out

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

    # Plus de reordonnancement manuel : save_config trie les cles, ce qui
    # place « emplacements » a son rang alphabetique quoi qu'on fasse ici.
    # L'ancien bricolage (pop + dict neuf) etait devenu sans effet, et il
    # retirait la cle de cfg — ce qu'un deuxieme enregistrement dans la meme
    # session n'aurait pas apprecie.
    save_config(cfg_path, cfg)


if __name__ == '__main__':
    main()
