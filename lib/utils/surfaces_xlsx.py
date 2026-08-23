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
u"""
Lecture / ecriture de tableurs Excel (.xlsx) pour l'echange de surfaces
reglementaires par niveau (SHON / SHOB / Surface Plancher).

S'appuie sur les deux paquets **livres par pyRevit** dans
``%APPDATA%\\pyRevit-Master\\site-packages`` (deja sur le sys.path du moteur
IronPython, aucune installation a prevoir) :
  - ``xlsxwriter`` 2.0.0 → ecriture
  - ``xlrd``       1.1.0 → lecture (cette version lit encore le .xlsx,
                                    contrairement a xlrd >= 2.0)

Aucun import Revit ici : le module est volontairement testable hors Revit.
"""
import os
import re


# ---------------------------------------------------------------------------
# Ecriture
# ---------------------------------------------------------------------------
def ecrire_tableur(chemin, entetes, lignes, nom_feuille=u"Surfaces niveaux",
                   cellules_verrouillees=None):
    u"""
    Ecrit un tableur .xlsx d'une seule feuille : une ligne d'entete puis les
    donnees.

    Parameters:
        chemin (str): chemin complet du .xlsx a creer (ecrase s'il existe).
        entetes (list): libelles des colonnes. La premiere colonne est celle
            des niveaux (verrouillee visuellement en gris, non destinee a
            etre modifiee par l'utilisateur).
        lignes (list): liste de listes de meme longueur que `entetes`. Les
            valeurs `None` produisent une cellule vide, les nombres une
            cellule numerique, le reste une cellule texte.
        nom_feuille (unicode): nom de l'onglet.
        cellules_verrouillees (set): couples `(index_ligne, index_colonne)`
            — index_ligne etant la position dans `lignes` — a presenter en
            lecture seule : fond gris, texte attenue, et cellule reellement
            verrouillee si la protection de feuille est disponible. Sert aux
            valeurs que l'utilisateur ne doit pas modifier parce qu'elles sont
            calculees ailleurs (nomenclatures).

    Returns:
        str: le chemin ecrit.

    Raises:
        IOError: si le fichier ne peut pas etre cree (typiquement deja ouvert
            dans Excel).
    """
    import xlsxwriter

    verrous = cellules_verrouillees or set()

    try:
        classeur = xlsxwriter.Workbook(chemin, {'default_date_format': 'dd/mm/yyyy'})
    except Exception as exc:
        raise IOError(
            u"Impossible de creer le fichier :\n{0}\n\n{1}\n\n"
            u"Le fichier est peut-etre deja ouvert dans Excel.".format(
                chemin, exc)
        )

    try:
        feuille = classeur.add_worksheet(nom_feuille[:31])

        f_entete = classeur.add_format({
            'bold':      True,
            'bg_color':  '#1E90FF',
            'font_color': '#FFFFFF',
            'border':    1,
            'align':     'center',
            'valign':    'vcenter',
            'text_wrap': True,
        })
        f_niveau = classeur.add_format({
            'bg_color': '#EFEFEF',
            'border':   1,
            'locked':   True,
        })
        # 'locked': False est indispensable — sous Excel toutes les cellules
        # sont verrouillees par defaut, et la protection de feuille posee plus
        # bas rendrait le tableur entierement non saisissable.
        f_valeur = classeur.add_format({
            'num_format': '0.00',
            'border':     1,
            'locked':     False,
        })
        f_verrou = classeur.add_format({
            'num_format': '0.00',
            'bg_color':   '#EFEFEF',
            'font_color': '#777777',
            'border':     1,
            'locked':     True,
        })

        feuille.set_row(0, 32)
        for col, libelle in enumerate(entetes):
            feuille.write_string(0, col, libelle, f_entete)

        for i, ligne in enumerate(lignes):
            rang = i + 1
            for col, valeur in enumerate(ligne):
                if col == 0:
                    fmt = f_niveau
                elif (i, col) in verrous:
                    fmt = f_verrou
                else:
                    fmt = f_valeur
                if valeur is None or valeur == u"":
                    feuille.write_blank(rang, col, None, fmt)
                elif col == 0:
                    feuille.write_string(rang, col, u"{0}".format(valeur), fmt)
                elif isinstance(valeur, (int, long, float)):
                    feuille.write_number(rang, col, float(valeur), fmt)
                else:
                    feuille.write_string(rang, col, u"{0}".format(valeur), fmt)

        # Largeurs : colonne des niveaux large, colonnes de saisie moyennes.
        largeur_niveau = 20
        for ligne in lignes:
            if ligne and ligne[0]:
                largeur_niveau = max(largeur_niveau, len(u"{0}".format(ligne[0])) + 2)
        feuille.set_column(0, 0, min(largeur_niveau, 60))
        if len(entetes) > 1:
            feuille.set_column(1, len(entetes) - 1, 22)

        feuille.freeze_panes(1, 1)

        # Protection de feuille : c'est elle qui donne son effet au 'locked'
        # des formats. Sans mot de passe — il s'agit d'eviter une saisie par
        # megarde, pas de verrouiller le fichier. Enveloppee car la version
        # d'xlsxwriter livree par pyRevit peut ne pas exposer protect().
        if verrous:
            try:
                feuille.protect()
            except Exception:
                pass

        classeur.close()
    except Exception:
        try:
            classeur.close()
        except Exception:
            pass
        raise

    return chemin


def ecrire_tableau(chemin, colonnes, lignes, nom_feuille=u"Feuille1",
                   nom_tableau=u"Tableau1", regles=None,
                   style=u"TableStyleMedium9"):
    u"""
    Ecrit un .xlsx dont les donnees sont un vrai TABLEAU Excel (ListObject) :
    en-tetes filtrantes, lignes alternees, et colonnes calculees par formule.

    A cote de `ecrire_tableur`, qui produit une simple plage : un tableau se
    filtre et se trie sans rien selectionner, et une colonne a formule s'etend
    d'elle-meme aux lignes ajoutees — ce qu'une plage ne sait pas faire.

    Parameters:
        colonnes (list): dicts {'entete', 'formule' (optionnel),
            'largeur' (optionnel)}. Une colonne portant 'formule' est
            CALCULEE : sa valeur dans `lignes` est ignoree, Excel la
            recalcule. Y ecrire la formule en references structurees
            (« [@[Code Ouv.]] ») la rend lisible et robuste au reordonnancement.
        lignes (list): listes de meme longueur que `colonnes`.
        regles (list): mises en forme conditionnelles, dicts
            {'critere', 'fond', 'texte'} — `critere` etant une formule Excel
            evaluee sur la premiere ligne de donnees (« =$C2=1 »), que Excel
            recopie ensuite sur toute la plage.

    Returns:
        str: le chemin ecrit.

    Raises:
        IOError: si le fichier ne peut pas etre cree (deja ouvert dans Excel).
    """
    import xlsxwriter

    try:
        classeur = xlsxwriter.Workbook(chemin)
    except Exception as exc:
        raise IOError(
            u"Impossible de creer le fichier :\n{0}\n\n{1}\n\n"
            u"Le fichier est peut-etre deja ouvert dans Excel.".format(
                chemin, exc))

    try:
        feuille = classeur.add_worksheet(nom_feuille[:31])
        nb_col = len(colonnes)
        # Au moins une ligne de donnees : un tableau Excel sans aucune ligne
        # n'a pas de plage valide, et le fichier serait refuse a l'ouverture.
        nb_lig = max(1, len(lignes))

        for i, col in enumerate(colonnes):
            if col.get('largeur'):
                feuille.set_column(i, i, col['largeur'])

        # Donnees ecrites AVANT add_table : celui-ci pose ensuite les formules
        # par-dessus les colonnes calculees. L'ordre inverse les effacerait —
        # add_table ecrit ses formules puis son option `data`, qui gagnerait.
        for r, ligne in enumerate(lignes):
            for c, col in enumerate(colonnes):
                if col.get('formule'):
                    continue
                val = ligne[c] if c < len(ligne) else None
                if val is None:
                    continue
                feuille.write(r + 1, c, val)

        spec = []
        for col in colonnes:
            entree = {'header': col['entete']}
            if col.get('formule'):
                entree['formula'] = col['formule']
            spec.append(entree)

        feuille.add_table(0, 0, nb_lig, nb_col - 1, {
            'name':      nom_tableau,
            'style':     style,
            'columns':   spec,
            'autofilter': True,
            'banded_rows': True,
        })

        # Sous l'en-tete : les colonnes de tete restent lisibles au defilement.
        feuille.freeze_panes(1, 0)

        for regle in (regles or []):
            fmt = {}
            if regle.get('fond'):
                fmt['bg_color'] = regle['fond']
            if regle.get('texte'):
                fmt['font_color'] = regle['texte']
            feuille.conditional_format(1, 0, nb_lig, nb_col - 1, {
                'type':     'formula',
                'criteria': regle['critere'],
                'format':   classeur.add_format(fmt),
            })

        classeur.close()
    except Exception:
        try:
            classeur.close()
        except Exception:
            pass
        raise

    return chemin


# ---------------------------------------------------------------------------
# Lecture
# ---------------------------------------------------------------------------
def lire_tableur(chemin, index_feuille=0):
    u"""
    Lit la premiere feuille d'un .xlsx et renvoie `(entetes, lignes)`.

    - `entetes` : liste des libelles de la ligne 1, en unicode, nettoyes.
    - `lignes`  : liste de listes de meme longueur que `entetes`. Chaque
      valeur est `None` (cellule vide), un `float` (cellule numerique) ou
      une chaine unicode (cellule texte).

    Les lignes entierement vides sont ignorees.

    Raises:
        IOError: fichier introuvable.
        ValueError: fichier illisible ou feuille vide.
    """
    if not chemin or not os.path.isfile(chemin):
        raise IOError(u"Fichier introuvable :\n{0}".format(chemin))

    import xlrd

    try:
        classeur = xlrd.open_workbook(chemin)
    except Exception as exc:
        raise ValueError(
            u"Fichier illisible :\n{0}\n\n{1}\n\n"
            u"Attendu : un classeur Excel .xlsx.".format(chemin, exc)
        )

    if classeur.nsheets <= index_feuille:
        raise ValueError(u"Le classeur ne contient aucune feuille exploitable.")

    feuille = classeur.sheet_by_index(index_feuille)
    if feuille.nrows < 1:
        raise ValueError(u"La feuille '{0}' est vide.".format(feuille.name))

    entetes = [_valeur_cellule(feuille, 0, c) for c in range(feuille.ncols)]
    entetes = [u"" if e is None else u"{0}".format(e).strip() for e in entetes]

    lignes = []
    for r in range(1, feuille.nrows):
        ligne = [_valeur_cellule(feuille, r, c) for c in range(feuille.ncols)]
        if all(v is None for v in ligne):
            continue
        lignes.append(ligne)

    return entetes, lignes


def _valeur_cellule(feuille, rang, col):
    u"""Convertit une cellule xlrd en None / float / unicode."""
    import xlrd

    cellule = feuille.cell(rang, col)
    ctype = cellule.ctype

    if ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
        return None
    if ctype == xlrd.XL_CELL_NUMBER:
        return float(cellule.value)
    if ctype == xlrd.XL_CELL_ERROR:
        return None

    texte = u"{0}".format(cellule.value).strip()
    return texte if texte else None


# ---------------------------------------------------------------------------
# Utilitaires de rapprochement
# ---------------------------------------------------------------------------
def normaliser_entete(libelle):
    u"""
    Cle de comparaison d'un libelle de colonne : minuscules, espaces
    (y compris insecables) reduits, ponctuation d'espacement normalisee.
    Permet de retrouver une colonne meme si Excel a laisse trainer un espace
    ou si l'utilisateur a change la casse.
    """
    if libelle is None:
        return u""
    texte = u"{0}".format(libelle).replace(u" ", u" ")
    texte = re.sub(u"\\s+", u" ", texte).strip().lower()
    return texte


def index_colonne(entetes, libelle_cherche):
    u"""
    Renvoie l'index de la colonne dont l'entete correspond a
    `libelle_cherche` (comparaison via `normaliser_entete`), ou None.
    """
    cible = normaliser_entete(libelle_cherche)
    if not cible:
        return None
    for i, entete in enumerate(entetes):
        if normaliser_entete(entete) == cible:
            return i
    return None


def parse_nombre(valeur):
    u"""
    Convertit une valeur de cellule en float.

    Accepte un nombre, ou un texte du type ``"123,45"``, ``"123.45 m2"``,
    ``"1 234,50 m²"``. Renvoie `None` si la cellule est vide, et leve
    `ValueError` si le contenu n'est pas interpretable comme un nombre.
    """
    if valeur is None:
        return None
    if isinstance(valeur, bool):
        raise ValueError(u"valeur booleenne")
    if isinstance(valeur, (int, long, float)):
        return float(valeur)

    texte = u"{0}".format(valeur).replace(u" ", u" ").strip()
    if not texte:
        return None

    # On isole le premier nombre : "1 234,50 m²" → "1234.50"
    trouve = re.search(u"-?\\d[\\d \\.,]*", texte)
    if not trouve:
        raise ValueError(texte)

    brut = trouve.group().replace(u" ", u"")
    # Separateur decimal : la derniere virgule ou le dernier point.
    if u"," in brut and u"." in brut:
        if brut.rfind(u",") > brut.rfind(u"."):
            brut = brut.replace(u".", u"").replace(u",", u".")
        else:
            brut = brut.replace(u",", u"")
    else:
        brut = brut.replace(u",", u".")

    try:
        return float(brut)
    except ValueError:
        raise ValueError(texte)
