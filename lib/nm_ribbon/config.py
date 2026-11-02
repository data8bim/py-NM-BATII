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

"""
NM-BATII — Onglets ruban personnalises, persistence de la configuration

Stockage par utilisateur (%APPDATA%), pas dans config.json de l'extension :
un onglet personnalise est un reglage de poste, pas un reglage de projet
BIM versionne avec l'extension. Chaque utilisateur du parc MOA garde donc
son propre decoupage, sans ecrasement au partage de config.json ni conflit
Git.

Schema (liste = ordre d'affichage, pas de champ "ordre" separe a tenir a
jour) :
    {
        "profils": [
            {"id": "profil_...", "nom_onglet": "...",
             "panneaux": [["TabId", "PanelId"], ...]},
            ...
        ],
        "onglets_masques": ["TabId", ...]
    }
"""

import os
import io
import json
import codecs
import time

DOSSIER_APPDATA = os.path.join(os.environ.get(u"APPDATA", u""), u"PyNM-BATII")
FICHIER_CONFIG = os.path.join(DOSSIER_APPDATA, u"custom_tabs.json")

CONFIG_DEFAUT = {
    u"profils": [],
    u"onglets_masques": [],
}


def _assurer_dossier():
    if not os.path.isdir(DOSSIER_APPDATA):
        os.makedirs(DOSSIER_APPDATA)


def nouvel_id_profil():
    """Id de profil unique dans la session : horodatage milliseconde, prefixe."""
    return u"profil_{0}".format(int(time.time() * 1000))


def _normaliser_profil(brut):
    panneaux = [
        list(p) for p in brut.get(u"panneaux", [])
        if isinstance(p, (list, tuple)) and len(p) == 2
    ]
    return {
        u"id": brut.get(u"id") or nouvel_id_profil(),
        u"nom_onglet": brut.get(u"nom_onglet") or u"Custom Tab",
        u"panneaux": panneaux,
    }


def charger():
    """Charge custom_tabs.json, ou renvoie la config par defaut si absent/invalide."""
    if not os.path.isfile(FICHIER_CONFIG):
        return {u"profils": [], u"onglets_masques": []}
    try:
        with codecs.open(FICHIER_CONFIG, u"r", u"utf-8") as f:
            cfg = json.load(f)
    except Exception:
        return {u"profils": [], u"onglets_masques": []}

    profils = [_normaliser_profil(p) for p in cfg.get(u"profils", []) if isinstance(p, dict)]
    onglets_masques = list(cfg.get(u"onglets_masques", []))
    return {u"profils": profils, u"onglets_masques": onglets_masques}


def enregistrer(cfg):
    """Ecrit custom_tabs.json. Retourne True si l'ecriture a abouti."""
    try:
        _assurer_dossier()
        with codecs.open(FICHIER_CONFIG, u"w", u"utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2,
                      separators=(u", ", u": "))
        return True
    except Exception:
        return False


def reinitialiser():
    """Supprime custom_tabs.json. Retourne la config par defaut."""
    try:
        if os.path.isfile(FICHIER_CONFIG):
            os.remove(FICHIER_CONFIG)
    except Exception:
        pass
    return {u"profils": [], u"onglets_masques": []}


# ---------------------------------------------------------------------------
# Export/import texte (Bloc-notes), format ligne par ligne :
#   profil=<id>|<nom_onglet>
#   panneau=<id_profil>|<tab_id>|<panel_id>
#   masque=<tab_id>
# L'ordre des lignes "profil=" donne l'ordre des onglets, l'ordre des lignes
# "panneau=" qui suivent donne l'ordre des panneaux dans ce profil.
# ---------------------------------------------------------------------------

def exporter_txt(chemin, cfg):
    """
    Exporte la config en .txt lisible/modifiable dans le Bloc-notes.

    BOM + CRLF : fichier destine a etre rouvert hors de l'extension (echange
    entre postes), pas uniquement relu par Python — cf. gotcha IronPython/JSON
    sur l'encodage des fichiers d'echange.
    """
    lignes = []
    for profil in cfg.get(u"profils", []):
        lignes.append(u"profil={0}|{1}".format(profil[u"id"], profil[u"nom_onglet"]))
        for tab_id, panel_id in profil.get(u"panneaux", []):
            lignes.append(u"panneau={0}|{1}|{2}".format(profil[u"id"], tab_id, panel_id))
    for tid in cfg.get(u"onglets_masques", []):
        lignes.append(u"masque={0}".format(tid))

    with io.open(chemin, u"w", encoding=u"utf-8-sig", newline=u"\r\n") as f:
        f.write(u"\r\n".join(lignes))


def importer_txt(chemin):
    """Lit un .txt exporte par exporter_txt() et retourne un dict config."""
    with io.open(chemin, u"r", encoding=u"utf-8-sig") as f:
        brut = f.read()

    profils_par_id = {}
    ordre_profils = []
    onglets_masques = []

    for ligne in brut.splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        if ligne.startswith(u"profil="):
            reste = ligne[len(u"profil="):]
            pid, _sep, nom = reste.partition(u"|")
            if pid not in profils_par_id:
                profils_par_id[pid] = {u"id": pid, u"nom_onglet": nom or u"Custom Tab",
                                        u"panneaux": []}
                ordre_profils.append(pid)
        elif ligne.startswith(u"panneau="):
            reste = ligne[len(u"panneau="):]
            parts = reste.split(u"|")
            if len(parts) != 3:
                continue
            pid, tab_id, panel_id = parts
            if pid not in profils_par_id:
                # Ligne orpheline (fichier modifie a la main) : cree un profil
                # minimal plutot que de perdre l'entree.
                profils_par_id[pid] = {u"id": pid, u"nom_onglet": u"Custom Tab", u"panneaux": []}
                ordre_profils.append(pid)
            profils_par_id[pid][u"panneaux"].append([tab_id, panel_id])
        elif ligne.startswith(u"masque="):
            onglets_masques.append(ligne[len(u"masque="):])

    return {
        u"profils": [profils_par_id[pid] for pid in ordre_profils],
        u"onglets_masques": onglets_masques,
    }
