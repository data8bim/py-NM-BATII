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


#__title__ = 'Couleurs'
#__author__ = 'data8bim (d8b)'


"""
NM-BATII — Remise a plat des couleurs des surfaces.

La palette « Surfaces » applique deja les couleurs a chaque attribution de
style : en usage courant, ce bouton n'a pas a etre lance.

Il reste utile quand AUCUNE surface n'est touchee et qu'il faut malgre tout
reecrire les couleurs du projet :
  - le referentiel a change dans les parametres, et il faut le repercuter ;
  - un projet ancien doit etre mis a la norme sans y modifier quoi que ce soit ;
  - quelqu'un a modifie des couleurs a la main dans Revit.

Toute la logique de rapprochement vit dans lib/utils/surfaces_couleurs.py,
partagee avec la palette : une seule regle, pas deux implementations a tenir en
phase. Voir ce module pour le principe — c'est le SCHEMA qui commande, on lit
le parametre qu'il utilise.
"""

import os
import sys

from pyrevit import HOST_APP, script
from Autodesk.Revit.DB import Transaction

_HERE = os.path.dirname(__file__)

# QUATRE niveaux : pushbutton -> pulldown -> panel -> tab -> .extension. Le
# bouton a gagne un cran d'imbrication en rejoignant « Donnees des surfaces » ;
# trois « .. » s'arretaient sur NM-BATII.tab, ou il n'y a pas de lib/.
_lib = os.path.join(_HERE, '..', '..', '..', '..', 'lib')
if _lib not in sys.path:
    sys.path.insert(0, _lib)
from dialogs.dialogs_styles_loader import load as _charger_styles, show_alert
_charger_styles()

# reload() explicite : le moteur IronPython de pyRevit est partage et garde en
# cache la version de surfaces_couleurs chargee au premier lancement. Sans cela,
# une correction apportee au module ne serait vue qu'apres redemarrage complet
# de Revit.
import utils.surfaces_couleurs as _mod_couleurs
reload(_mod_couleurs)
from utils.surfaces_couleurs import lire_lignes_de_style, appliquer_couleurs

doc = HOST_APP.doc

# Convention de l'extension : rien ne s'affiche si « Activer les logs des
# scripts » est decoche dans 01_Parametres.
output = script.get_output()
try:
    from utils.config_loader import load_config
    _LOG_ACTIF = bool(load_config().get('activer_logs_scripts', False))
except Exception:
    _LOG_ACTIF = False
if not _LOG_ACTIF:
    try:
        output.close()
    except Exception:
        pass


def _log(message):
    if _LOG_ACTIF and message:
        try:
            output.print_md(message)
        except Exception:
            pass


def lire_referentiel():
    """(table de style, colonne du type de calcul, { nom de cle: '#RRGGBB' })."""
    from utils.config_loader import load_config
    sf = load_config().get('surface', {}) or {}
    couleurs = {}
    motifs = {}
    for e in (sf.get('styles_palette', []) or []):
        try:
            nom = (e.get('nom') or u'').strip()
            hexa = (e.get('couleur_plan') or u'').strip()
            motif = (e.get('motif_plan') or u'').strip()
        except Exception:
            continue
        if nom and hexa:
            couleurs[nom] = hexa
            if motif:
                motifs[nom] = motif
    return ((sf.get('table_styles_schedule', u'') or u''),
            (sf.get('col_calcul_style', u'') or u''),
            (sf.get('param_style', u'') or u''),
            couleurs, motifs)


def main():
    nom_table, col_calcul, param_style, couleurs, motifs = lire_referentiel()

    if not nom_table:
        show_alert(u"NM-BATII — Couleurs des surfaces",
                   u"La table de style n'est pas déclarée.\n\nRenseignez-la "
                   u"dans « Paramètres > Surfaces > Table de style des "
                   u"surfaces ».")
        return
    if not couleurs:
        show_alert(u"NM-BATII — Couleurs des surfaces",
                   u"Aucune couleur de surface n'est définie dans le "
                   u"référentiel.\n\nOuvrez « Paramètres > Surfaces > Ordre et "
                   u"couleurs des styles… », puis cliquez la pastille à droite "
                   u"d'un style pour lui donner sa couleur — ou utilisez "
                   u"« Teintes distinctes » pour les attribuer d'un coup.")
        return

    lignes = lire_lignes_de_style(doc, nom_table)
    if lignes is None:
        show_alert(u"NM-BATII — Couleurs des surfaces",
                   u"Nomenclature de clés introuvable dans ce projet :\n"
                   u"« {0} ».".format(nom_table))
        return

    t = Transaction(doc, u"NM-BATII — Couleurs standard des surfaces")
    t.Start()
    try:
        total, details = appliquer_couleurs(doc, lignes, couleurs,
                                            col_calcul, param_style, motifs)
        t.Commit()
    except Exception:
        try:
            t.RollBack()
        except Exception:
            pass
        raise

    if not details:
        show_alert(u"NM-BATII — Couleurs des surfaces",
                   u"Aucun choix de couleurs de surfaces dans ce projet.")
        return

    rapport = [u"{0} style(s) coloré(s) au référentiel, {1} ligne(s) dans la "
               u"table, {2} entrée(s) colorée(s).".format(
                   len(couleurs), len(lignes), total),
               u""]
    for d in details:
        rapport.append(u"■ « {0} »".format(d['titre']))
        rapport.append(u"   schéma : {0}   •   basé sur : {1}".format(
            d['schema'], d['parametre']))
        rapport.append(u"   {0} entrée(s) — {1} colorée(s)".format(
            d['entrees'], d['maj']))
        rapport.append(u"   rapprochement : {0} par les surfaces, {1} valeur(s) "
                       u"au total{2}".format(
                           d['par_surfaces'], d['table'],
                           u"" if d['filtre'] else u" (repli SANS filtre de "
                                                   u"type de calcul)"))
        if d['collisions']:
            rapport.append(u"   deux clés pour une même valeur, dans ce "
                           u"schéma : " + u" ; ".join(d['collisions'][:3]))
        if d['motifs_absents']:
            rapport.append(u"   motifs inconnus du projet, entrées inchangées "
                           u"sur ce point : "
                           + u", ".join(d['motifs_absents'][:3]))
        if d['sans_corr']:
            rapport.append(u"   sans correspondance : "
                           + u", ".join(d['sans_corr'][:5])
                           + (u"…" if len(d['sans_corr']) > 5 else u""))
        if d['echecs']:
            rapport.append(u"   échecs : " + u", ".join(d['echecs'][:3]))
        rapport.append(u"")

    rapport.append(u"Une entrée n'apparaît dans un choix de couleurs que "
                   u"lorsque la valeur est employée par une surface. La palette "
                   u"« Surfaces » applique désormais les couleurs à chaque "
                   u"attribution de style ; ce bouton ne sert qu'à repasser sur "
                   u"un projet sans y toucher aux surfaces.")

    resume = u"\n".join(rapport)
    _log(resume)
    show_alert(u"NM-BATII — Couleurs des surfaces", resume)


try:
    main()
except Exception as e:
    import traceback
    _log(u"```\n{0}\n```".format(traceback.format_exc()))
    show_alert(u"NM-BATII — Échec", u"Erreur : {0}".format(e))
