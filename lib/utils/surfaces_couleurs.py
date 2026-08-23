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
NM-BATII — Couleurs standard des surfaces, logique partagee.

Revit ne sait pas transporter les couleurs d'un « Choix de couleurs » d'un
projet a l'autre : un gabarit de vue porte la REFERENCE au schema, mais les
entrees et leurs couleurs appartiennent au document. Il faut donc les ECRIRE.

PRINCIPE — LE SCHEMA COMMANDE. Un choix de couleurs peut etre bati sur
n'importe quel parametre : la cle de style elle-meme (stockee en ElementId),
mais aussi bien une COLONNE de la table de style (« Nom », stockee en texte),
ce qui est le cas courant. Rien n'est donc suppose : pour chaque schema on lit
LE PARAMETRE QU'IL UTILISE, on va chercher la valeur du meme parametre sur
chaque ligne de la table de style, et on rapproche les deux.

Le parametre est cible par son ID et non par son nom : cela vaut aussi bien
pour un parametre integre que pour un parametre partage, sans traduction.

Ce module est appele depuis deux endroits — la palette « Surfaces », juste
apres l'ecriture des cles de style, et le bouton « Couleurs » pour une remise a
plat complete. D'ou son extraction ici : une seule regle de rapprochement, pas
deux implementations a maintenir en phase.

Aucune transaction n'est ouverte ici : l'appelant en fournit une. Les entrees
d'un choix de couleurs n'existent que pour les valeurs REELLEMENT employees,
c'est Revit qui les cree ; ce module ne fait que les colorer.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    ColorFillScheme,
    Element,
    ElementId,
    StorageType,
    Color,
    ViewSchedule,
    BuiltInCategory,
)


def hex_vers_couleur(hexa):
    """'#RRGGBB' -> Autodesk.Revit.DB.Color, ou None si inexploitable."""
    t = (hexa or u'').strip().lstrip(u'#')
    if len(t) != 6:
        return None
    try:
        return Color(int(t[0:2], 16), int(t[2:4], 16), int(t[4:6], 16))
    except ValueError:
        return None


def motifs_par_nom(doc):
    """
    { nom du motif de remplissage : ElementId } pour le document ouvert.

    Le referentiel enregistre les motifs par NOM : un identifiant n'aurait de
    sens que dans un projet, alors qu'il doit valoir pour tous. Un projet qui
    ne connait pas un motif garde simplement le sien.
    """
    from Autodesk.Revit.DB import FillPatternElement
    table = {}
    for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
        try:
            table[fp.GetFillPattern().Name] = fp.Id
        except Exception:
            continue
    return table


def lire_lignes_de_style(doc, nom_table):
    """
    Lignes de la nomenclature de cles : [(element, nom de cle), ...], ou None.

    Les lignes d'une nomenclature de CLES sont de vrais elements ; seul un
    collecteur borne a la vue de la nomenclature les rend. Chacune porte toutes
    les colonnes de la table — dont celle sur laquelle un schema peut etre bati.
    """
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
        return None

    lignes = []
    for elem in FilteredElementCollector(doc, vue.Id).ToElements():
        try:
            nom = Element.Name.__get__(elem)
        except Exception:
            continue
        if nom:
            lignes.append((elem, nom))
    return lignes


def schemas_surfaces(doc):
    """Tous les choix de couleurs de la categorie Surfaces."""
    cibles = []
    for sch in FilteredElementCollector(doc).OfClass(ColorFillScheme):
        try:
            if sch.CategoryId == ElementId(BuiltInCategory.OST_Areas):
                cibles.append(sch)
        except Exception:
            continue
    return cibles


# ── Rapprochement schema <-> table de style ─────────────────────────────────
#
# Les valeurs des deux cotes sont ramenees a la MEME forme comparable. Le
# prefixe distingue une reference d'element d'un texte, pour qu'un identifiant
# ne puisse jamais etre confondu avec une chaine qui lui ressemblerait.

def normaliser(texte):
    """Clef de comparaison souple : casse, espaces et accents ecartes."""
    if not texte:
        return u""
    try:
        import unicodedata
        plat = unicodedata.normalize('NFKD', texte)
        plat = u"".join(c for c in plat if not unicodedata.combining(c))
    except Exception:
        plat = texte
    return u" ".join(plat.split()).strip().lower()


def _valeur_texte(elem, nom_param):
    """Valeur texte d'un parametre designe par son NOM, ou u''."""
    if not nom_param:
        return u""
    try:
        p = elem.LookupParameter(nom_param)
        if p is None:
            return u""
        if p.StorageType == StorageType.String:
            return p.AsString() or u""
        return p.AsValueString() or u""
    except Exception:
        return u""


def lignes_du_schema(doc, sch, lignes, col_calcul):
    """
    Lignes de la table de style qui concernent CE schema de surfaces.

    Indispensable des lors qu'un choix de couleurs est bati sur une colonne
    comme « Nom » : deux clefs de familles differentes peuvent porter le meme
    nom — « SHON/SHOB - Surfaces planchers HSP<1,8m » et
    « SP - Surfaces planchers HSP<1,8m » ont tous deux pour nom « Surfaces
    planchers HSP<1,8m ». Sans ce filtrage, la derniere lue ecrasait l'autre et
    une famille recevait la couleur de sa voisine.

    Le rapprochement se fait entre le nom du SCHEMA DE SURFACES et la colonne
    du type de calcul. Si aucune ligne ne correspond, le filtre est abandonne :
    mieux vaut colorer avec le risque d'une collision que ne rien colorer du
    tout, et le compte rendu signale le cas.
    """
    if not col_calcul:
        return lignes, False
    cible = normaliser(nom_schema_surfaces(doc, sch))
    if not cible:
        return lignes, False
    retenues = [(e, n) for (e, n) in lignes
                if normaliser(_valeur_texte(e, col_calcul)) == cible]
    if not retenues:
        return lignes, False
    return retenues, True


def relation_depuis_surfaces(doc, sch, param_style):
    """
    { valeur comparable : nom de cle de style }, observee sur les SURFACES.

    C'est la voie de rapprochement la plus sure, et de loin. Une surface porte
    a la fois la valeur du parametre sur lequel le schema est bati (« Nom »,
    par exemple) ET sa cle de style, qui est unique. Chaque surface etablit
    donc elle-meme la correspondance, sans qu'on ait rien a supposer.

    Elle est en outre exhaustive par construction : une entree n'existe dans un
    choix de couleurs que pour une valeur REELLEMENT employee, donc portee par
    au moins une surface du schema.

    Le rapprochement par la table de style, lui, passe par le nom : deux cles
    de familles differentes peuvent porter le meme — « SHON/SHOB - Surfaces
    planchers HSP<1,8m » et « SP - Surfaces planchers HSP<1,8m » ont tous deux
    pour nom « Surfaces planchers HSP<1,8m » — et l'une volait alors sa couleur
    a l'autre. Il ne sert plus que de repli.

    Returns:
        tuple: ({ valeur: nom de cle }, [collisions constatees])
    """
    from Autodesk.Revit.DB import Area

    relation = {}
    collisions = []
    if not param_style:
        return relation, collisions

    pid = sch.ParameterDefinition
    try:
        id_schema = sch.AreaSchemeId
    except Exception:
        return relation, collisions

    col = FilteredElementCollector(doc) \
        .OfCategory(BuiltInCategory.OST_Areas) \
        .WhereElementIsNotElementType()
    for surface in col:
        if not isinstance(surface, Area):
            continue
        try:
            if surface.AreaScheme.Id != id_schema:
                continue
        except Exception:
            continue

        # Cle de style portee par la surface.
        try:
            p_style = surface.LookupParameter(param_style)
            if p_style is None:
                continue
            ligne = doc.GetElement(p_style.AsElementId())
            if ligne is None:
                continue
            nom_style = Element.Name.__get__(ligne)
        except Exception:
            continue
        if not nom_style:
            continue

        # Valeur du parametre sur lequel le schema est bati.
        valeur = _cle_depuis_element(surface, sch, pid)
        if not valeur:
            continue

        connu = relation.get(valeur)
        if connu is None:
            relation[valeur] = nom_style
        elif connu != nom_style:
            # Deux cles differentes produisent la meme valeur DANS CE SCHEMA :
            # anomalie du projet, pas du rapprochement. On garde la premiere et
            # on le signale plutot que de trancher au hasard.
            marque = u"{0} / {1}".format(connu, nom_style)
            if marque not in collisions:
                collisions.append(marque)

    return relation, collisions


def _parametre_par_id(elem, pid):
    """Parametre d'un element designe par l'ID de sa definition."""
    try:
        for p in elem.Parameters:
            if p.Id == pid:
                return p
    except Exception:
        pass
    return None


def _cle_depuis_entree(entree):
    """Forme comparable de la valeur portee par une entree du schema."""
    try:
        st = entree.StorageType
        if st == StorageType.ElementId:
            return u"id:" + str(entree.GetElementIdValue())
        if st == StorageType.String:
            return u"tx:" + (entree.GetStringValue() or u'').strip().lower()
        if st == StorageType.Integer:
            return u"tx:" + unicode(entree.GetIntegerValue())
        if st == StorageType.Double:
            return u"tx:" + unicode(entree.GetDoubleValue())
    except Exception:
        pass
    return None


def _cle_depuis_element(elem, sch, pid, id_si_cle=None):
    """
    Meme valeur, lue sur un element porteur — surface ou ligne de table.

    Si le schema est bati sur la cle de style elle-meme, la valeur est une
    reference : celle de la ligne de table (id_si_cle) quand on lit une ligne,
    celle que porte le parametre quand on lit une surface.
    """
    try:
        if sch.StorageType == StorageType.ElementId and id_si_cle is not None:
            return u"id:" + str(id_si_cle)
        p = _parametre_par_id(elem, pid)
        if p is None:
            return None
        st = p.StorageType
        if st == StorageType.String:
            return u"tx:" + (p.AsString() or u'').strip().lower()
        if st == StorageType.Integer:
            return u"tx:" + unicode(p.AsInteger())
        if st == StorageType.Double:
            return u"tx:" + unicode(p.AsDouble())
        if st == StorageType.ElementId:
            return u"id:" + str(p.AsElementId())
    except Exception:
        pass
    return None


def nom_parametre_schema(doc, sch):
    """Nom lisible du parametre sur lequel le schema est bati."""
    pid = sch.ParameterDefinition
    try:
        pe = doc.GetElement(pid)
        if pe is not None:
            return pe.GetDefinition().Name
    except Exception:
        pass
    try:
        from Autodesk.Revit.DB import LabelUtils, BuiltInParameter
        return LabelUtils.GetLabelFor(BuiltInParameter(pid.IntegerValue))
    except Exception:
        return u"?"


def nom_schema_surfaces(doc, sch):
    """Nom du schema de surfaces auquel ce choix de couleurs est rattache."""
    try:
        el = doc.GetElement(sch.AreaSchemeId)
        return Element.Name.__get__(el) if el is not None else u"?"
    except Exception:
        return u"?"


# ── Ecriture ────────────────────────────────────────────────────────────────

def appliquer_a_un_schema(doc, sch, lignes, couleurs,
                          col_calcul=None, param_style=None, motifs=None):
    """
    Colore les entrees d'UN choix de couleurs.

    DEUX voies de rapprochement, complementaires, dans cet ordre :

      1. La relation observee sur les SURFACES du schema. Chacune porte a la
         fois la valeur du parametre et sa cle de style, qui est unique : la
         correspondance est constatee, jamais supposee. Elle couvre par
         construction toutes les entrees existantes, puisqu'une entree n'existe
         que pour une valeur employee.

      2. La table de style, rapprochee par le nom, RESTREINTE aux lignes dont
         le type de calcul correspond au schema de surfaces. Ce filtre est ce
         qui rend la voie utilisable : plusieurs styles peuvent porter le meme
         nom de surface, mais pas au sein d'un meme type de calcul. Sert aux
         valeurs que les surfaces n'expliquent pas encore.

    Returns:
        dict: compte rendu par schema.
    """
    detail = {
        'titre':        sch.Title,
        'schema':       nom_schema_surfaces(doc, sch),
        'parametre':    nom_parametre_schema(doc, sch),
        'entrees':      0,
        'table':        0,
        'par_surfaces': 0,
        'maj':          0,
        'sans_corr':    [],
        'echecs':       [],
        'filtre':         False,
        'collisions':     [],
        'motifs_absents': [],
    }

    pid = sch.ParameterDefinition

    # 1. Voie principale : la relation observee sur les surfaces du schema.
    #    Une surface porte a la fois la valeur du parametre et sa cle de style,
    #    qui est unique — aucun doublon possible.
    relation, collisions = relation_depuis_surfaces(doc, sch, param_style)
    detail['collisions'] = collisions
    detail['par_surfaces'] = len(relation)

    def _apparence(nom_style):
        """(Color, ElementId de motif ou None) pour un style, ou None."""
        couleur = hex_vers_couleur(couleurs.get(nom_style))
        if couleur is None:
            return None
        nom_motif = (motifs or {}).get(nom_style) or u''
        id_motif = dispo_motifs.get(nom_motif) if nom_motif else None
        if nom_motif and id_motif is None:
            if nom_motif not in detail['motifs_absents']:
                detail['motifs_absents'].append(nom_motif)
        return (couleur, id_motif)

    dispo_motifs = motifs_par_nom(doc) if motifs else {}

    table = {}
    for valeur, nom_style in relation.items():
        app = _apparence(nom_style)
        if app is not None:
            table[valeur] = app

    # 2. Repli, pour ce que les surfaces n'expliquent pas : la table de style,
    #    rapprochee par le nom. Ambigu par nature, d'ou le filtrage par famille
    #    et la priorite donnee a la voie precedente.
    retenues, filtre = lignes_du_schema(doc, sch, lignes, col_calcul)
    detail['filtre'] = filtre
    for elem, nom_style in retenues:
        app = _apparence(nom_style)
        if app is None:
            continue
        valeur = _cle_depuis_element(elem, sch, pid, id_si_cle=elem.Id)
        if valeur and valeur not in table:
            table[valeur] = app

    detail['table'] = len(table)

    entrees = list(sch.GetEntries())
    detail['entrees'] = len(entrees)
    modifiees = False

    for entree in entrees:
        app = table.get(_cle_depuis_entree(entree))
        if app is None:
            # Entree que la table de style ne sait pas expliquer : « (aucun) »,
            # ou une valeur saisie hors nomenclature. On n'y touche pas.
            try:
                detail['sans_corr'].append(entree.GetStringValue()
                                           or entree.Caption)
            except Exception:
                detail['sans_corr'].append(u"?")
            continue
        couleur, id_motif = app
        try:
            entree.Color = couleur
            # Motif applique seulement s'il est configure ET connu du projet :
            # sans reglage, celui deja en place est le bon choix par defaut.
            if id_motif is not None:
                entree.FillPatternId = id_motif
            modifiees = True
            detail['maj'] += 1
        except Exception as ex:
            detail['echecs'].append(u"{0} : {1}".format(entree.Caption, ex))

    if modifiees:
        try:
            sch.SetEntries(entrees)
        except Exception:
            # Repli entree par entree : SetEntries refuse le lot entier des
            # qu'une seule entree lui deplait.
            for entree in entrees:
                try:
                    sch.UpdateEntry(entree)
                except Exception:
                    pass

    return detail


def appliquer_couleurs(doc, lignes, couleurs, col_calcul=None,
                       param_style=None, motifs=None):
    """
    Colore tous les choix de couleurs des surfaces du document.

    Args:
        doc: document Revit ; une transaction doit etre OUVERTE par l'appelant.
        lignes (list): [(element de ligne de style, nom de cle), ...].
        couleurs (dict): { nom de cle: '#RRGGBB' }.
        col_calcul (str): colonne du type de calcul, rapprochee du nom du
            schema de surfaces pour ne retenir que les styles qui le
            concernent. Plusieurs styles peuvent porter le meme nom de surface,
            mais pas au sein d'un meme type de calcul.
        param_style (str): parametre de cle de style porte par les surfaces.
            Ouvre la voie de rapprochement principale, celle observee sur les
            surfaces elles-memes — voir relation_depuis_surfaces.
        motifs (dict): { nom de cle: nom du motif de remplissage }. Un motif
            inconnu du projet est signale et l'entree garde le sien.

    Returns:
        tuple: (nb_entrees_colorees, [details par schema])
    """
    details = []
    total = 0
    if not couleurs:
        return 0, details
    for sch in schemas_surfaces(doc):
        d = appliquer_a_un_schema(doc, sch, lignes or [], couleurs,
                                  col_calcul, param_style, motifs)
        details.append(d)
        total += d['maj']
    return total, details
