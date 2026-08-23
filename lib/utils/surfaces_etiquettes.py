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
NM-BATII — Etiquetage des surfaces, logique partagee.

Deux appelants : la fenetre des parametres, qui a besoin de la LISTE des types
d'etiquette du projet pour les proposer, et la palette « Surfaces », qui POSE
les etiquettes juste apres avoir ecrit les cles de style.

IDENTIFICATION PAR « Famille : Type », jamais par ElementId. Meme raison que
pour les couleurs et les motifs : le reglage vit dans config.json, il doit
valoir sur les milliers de projets existants, et un identifiant n'a de sens que
dans le document ou il a ete lu.

JAMAIS DEUX ETIQUETTES. Une surface qui en porte deja une DANS LA VUE n'en
recoit pas une seconde : celle en place est retypee si besoin. C'est ce qui rend
l'option sure a laisser allumee en permanence, et ce qui la fait cooperer avec
l'option native de Revit « Etiqueter au moment du placement » — Revit pose son
type par defaut, on le corrige.

Aucune transaction n'est ouverte ici : l'appelant en fournit une.
"""

from Autodesk.Revit.DB import (
    FilteredElementCollector,
    BuiltInCategory,
    Element,
    FamilySymbol,
    UV,
    LocationPoint,
)

# Separateur d'affichage entre la famille et le type. Espaces compris : c'est
# la forme lisible qui est enregistree telle quelle dans config.json.
SEPARATEUR = u' : '


def _nom_complet(symbole):
    """« Famille : Type » pour un FamilySymbol, ou u'' si illisible."""
    try:
        famille = symbole.Family
        nom_f = Element.Name.__get__(famille) if famille is not None else u''
    except Exception:
        nom_f = u''
    try:
        # Element.Name est implemente en interface explicite : l'acces direct
        # leve AttributeError sur les ElementType en IronPython.
        nom_t = Element.Name.__get__(symbole)
    except Exception:
        return u''
    if not nom_t:
        return u''
    return (nom_f + SEPARATEUR + nom_t) if nom_f else nom_t


def types_etiquettes(doc):
    """
    Types d'etiquette de surface du projet : [(u'Famille : Type', ElementId)].

    Tries par nom, pour que la liste deroulante des parametres soit
    parcourable. Les etiquettes de surface sont des FamilySymbol de la
    categorie OST_AreaTags — la meme que celle du bouton natif « Etiqueter une
    surface ».
    """
    trouves = []
    try:
        collecteur = (FilteredElementCollector(doc)
                      .OfCategory(BuiltInCategory.OST_AreaTags)
                      .WhereElementIsElementType())
    except Exception:
        return []
    for sym in collecteur:
        if not isinstance(sym, FamilySymbol):
            continue
        nom = _nom_complet(sym)
        if nom:
            trouves.append((nom, sym.Id))
    trouves.sort(key=lambda t: t[0].lower())
    return trouves


def type_par_nom(doc, nom):
    """ElementId du type « Famille : Type », ou None s'il manque au projet."""
    cible = (nom or u'').strip()
    if not cible:
        return None
    for n, eid in types_etiquettes(doc):
        if n == cible:
            return eid
    return None


def _point_de_pose(surface):
    """UV du point de definition de la surface, ou None si elle n'est pas placee."""
    try:
        loc = surface.Location
    except Exception:
        return None
    if not isinstance(loc, LocationPoint):
        return None
    try:
        p = loc.Point
        return UV(p.X, p.Y)
    except Exception:
        return None


def _appartient_a_la_vue(surface, vue):
    """
    Vrai si la surface se voit dans ce plan de surface.

    La palette peut avoir des surfaces en attente d'ecriture au moment ou
    l'utilisateur change de plan : elles ont ete posees dans la vue precedente,
    et les etiqueter dans la nouvelle serait les poser au mauvais endroit. Le
    niveau ET le schema de surface doivent donc correspondre.
    """
    try:
        if surface.LevelId != vue.GenLevel.Id:
            return False
    except Exception:
        return False
    try:
        schema = vue.AreaScheme
        if schema is not None and surface.AreaScheme.Id != schema.Id:
            return False
    except Exception:
        pass
    return True


def _surface_de_l_etiquette(tag):
    """Surface portee par une etiquette, ou None."""
    # Area est la propriete specialisee d'AreaTag, SpatialElement celle de sa
    # classe de base. Les deux existent, mais l'une ou l'autre peut echouer
    # selon l'etat de l'etiquette (orpheline, liee...) : on essaie les deux
    # avant de renoncer, car renoncer ici revient a poser un doublon.
    for nom in ('Area', 'SpatialElement'):
        try:
            surf = getattr(tag, nom, None)
        except Exception:
            surf = None
        if surf is not None:
            return surf
    return None


def etiquettes_de_la_vue(doc, vue_id):
    """
    { Id de surface (int) : [AreaTag, ...] } pour les etiquettes de la vue.

    Une LISTE par surface, et non une seule etiquette : un projet peut deja en
    porter plusieurs — posees a la main, ou par une version anterieure de cette
    fonction. etiqueter() garde la premiere et supprime les autres.

    Une premiere version rendait un index vide et posait donc une etiquette de
    plus a chaque changement de style. Trois failles menaient a cet index vide,
    toutes fermees ici — laquelle a joue n'a pas ete tranchee, et n'a pas besoin
    de l'etre :

    1. COLLECTEUR SUR LE DOCUMENT, filtre ensuite sur OwnerViewId, et non
       collecteur borne a la vue. Un collecteur borne a une vue ne rend que ce
       qui y est VISIBLE : une etiquette masquee par un gabarit, un filtre de
       vue ou un « Masquer dans la vue » n'en sortait pas, alors qu'elle
       existait bel et bien.
    2. Filtre par CATEGORIE et non par classe : un filtre de classe leve sur les
       types qu'il ne prend pas en charge, et l'exception tombe a la
       construction du collecteur.
    3. Plus aucun `except` ne rend un index vide. La fonction LEVE si la lecture
       echoue : sans index fiable, ne rien poser vaut mieux que poser des
       doublons, et l'appelant le signale au lieu de l'ignorer.
    """
    par_surface = {}
    collecteur = (FilteredElementCollector(doc)
                  .OfCategory(BuiltInCategory.OST_AreaTags)
                  .WhereElementIsNotElementType())
    for tag in collecteur:
        try:
            if tag.OwnerViewId != vue_id:
                continue
        except Exception:
            continue
        surf = _surface_de_l_etiquette(tag)
        if surf is None:
            continue
        try:
            cle = surf.Id.IntegerValue
        except Exception:
            continue
        par_surface.setdefault(cle, []).append(tag)
    return par_surface


def etiqueter(doc, vue, surfaces, type_id, avec_repere=False, deja_posees=None):
    """
    Pose ou retype l'etiquette des surfaces donnees, dans la vue donnee.

    Args:
        doc: document Revit.
        vue: ViewPlan de destination — une etiquette est propre a une vue.
        surfaces (list): elements Area.
        type_id (ElementId): type d'etiquette a appliquer.
        avec_repere (bool): ligne de repere de l'etiquette.
        deja_posees (dict): resultat de etiquettes_de_la_vue, si l'appelant l'a
            deja lu. Evite de reparcourir la vue a chaque lot.

    Returns:
        dict: compteurs — 'posees', 'retypees', 'doublons', 'ignorees',
            'hors_vue'. Un dictionnaire et non un tuple : la liste des cas a
            compter s'allonge, et une position de plus dans un tuple casse tous
            les appelants en silence.

    Raises:
        Les erreurs de lecture des etiquettes existantes remontent : sans index
        fiable, l'appelant doit renoncer plutot que poser des doublons.
    """
    compteurs = {u'posees': 0, u'retypees': 0, u'doublons': 0,
                 u'ignorees': 0, u'hors_vue': 0}
    if not surfaces or type_id is None or vue is None:
        return compteurs

    existantes = (deja_posees if deja_posees is not None
                  else etiquettes_de_la_vue(doc, vue.Id))

    for surface in surfaces:
        if surface is None:
            continue
        if not _appartient_a_la_vue(surface, vue):
            compteurs[u'hors_vue'] += 1
            continue
        cle = surface.Id.IntegerValue
        tags = existantes.get(cle) or []

        if tags:
            # Deja etiquetee : on corrige le type si besoin, et on ne touche ni
            # a sa position ni a sa rotation — elles ont pu etre ajustees a la
            # main, et les ecraser serait une perte de travail invisible.
            tag = tags[0]
            try:
                if tag.AreaTagType.Id != type_id:
                    tag.AreaTagType = doc.GetElement(type_id)
                    compteurs[u'retypees'] += 1
                if bool(tag.HasLeader) != bool(avec_repere):
                    tag.HasLeader = bool(avec_repere)
            except Exception:
                pass
            # Les etiquettes surnumeraires de CETTE surface sont supprimees :
            # elles font double emploi, et le plan devient illisible. Portee
            # limitee aux surfaces traitees — il n'appartient pas a cette
            # fonction de faire le menage dans le reste de la vue.
            for surnumeraire in tags[1:]:
                try:
                    doc.Delete(surnumeraire.Id)
                    compteurs[u'doublons'] += 1
                except Exception:
                    pass
            existantes[cle] = [tag]
            continue

        point = _point_de_pose(surface)
        if point is None:
            # Surface non placee (contour ouvert, aire nulle) : Revit n'a pas de
            # point ou accrocher l'etiquette. Comptee, pas passee sous silence.
            compteurs[u'ignorees'] += 1
            continue

        try:
            tag = doc.Create.NewAreaTag(vue, surface, point)
        except Exception:
            compteurs[u'ignorees'] += 1
            continue
        if tag is None:
            compteurs[u'ignorees'] += 1
            continue

        try:
            tag.AreaTagType = doc.GetElement(type_id)
        except Exception:
            pass
        try:
            tag.HasLeader = bool(avec_repere)
        except Exception:
            pass
        existantes[cle] = [tag]
        compteurs[u'posees'] += 1

    return compteurs


def resume(compteurs):
    """Phrase de compte rendu, ou u'' s'il n'y a rien a dire."""
    if not compteurs:
        return u""
    bouts = []
    if compteurs.get(u'posees'):
        bouts.append(u"{0} étiquette(s) posée(s)".format(compteurs[u'posees']))
    if compteurs.get(u'retypees'):
        bouts.append(u"{0} retypée(s)".format(compteurs[u'retypees']))
    if compteurs.get(u'doublons'):
        bouts.append(u"{0} doublon(s) supprimé(s)".format(
            compteurs[u'doublons']))
    if compteurs.get(u'ignorees'):
        bouts.append(u"{0} surface(s) non placée(s), sans étiquette".format(
            compteurs[u'ignorees']))
    if compteurs.get(u'hors_vue'):
        bouts.append(u"{0} hors de la vue courante, non étiquetée(s)".format(
            compteurs[u'hors_vue']))
    return (u", ".join(bouts) + u".") if bouts else u""
