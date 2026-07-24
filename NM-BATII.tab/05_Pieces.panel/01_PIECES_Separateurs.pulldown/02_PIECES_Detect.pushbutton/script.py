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


#__title__ = 'Lignes → Sép. Pièces'
#__author__ = 'data8bim (d8b)'


"""
NM-BATII — Détection automatique de pièces depuis DWG
Pipeline : rasterisation → flood fill → composantes connexes → contours → Revit

Modes : automatique (toutes les pièces) | point-and-click (une pièce)
"""

import os
import sys
import math
import collections
import json

_lib = os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'lib')
if _lib not in sys.path:
    sys.path.insert(0, _lib)
from utils.config_loader import load_config
from dialogs.dialogs_styles_loader import load as _charger_styles

from pyrevit import revit, DB, UI, forms, script

from System.Windows import Visibility, WindowStartupLocation, MessageBox
from System.Windows.Threading import Dispatcher, DispatcherFrame
from Autodesk.Revit.UI import IExternalEventHandler, ExternalEvent
from Microsoft.Win32 import OpenFileDialog, SaveFileDialog

doc    = revit.doc
uidoc  = revit.uidoc
output = script.get_output()

# --- Contrôle de l'affichage des logs (config.json > activer_logs_scripts) ---
_LOG_ACTIF = False
try:
    _cfg_init  = load_config()
    _LOG_ACTIF = bool(_cfg_init.get('activer_logs_scripts', False))
except Exception:
    pass

if not _LOG_ACTIF:
    try:
        output.close()
    except Exception:
        pass


def _log(msg):
    """Écrit dans le panneau pyRevit uniquement si les logs sont activés."""
    if _LOG_ACTIF:
        output.print_md(msg)


def _linkify(elem_id):
    """Crée un lien cliquable dans les logs, ou retourne l'ID brut si logs désactivés."""
    if _LOG_ACTIF:
        try:
            return output.linkify(elem_id)
        except Exception:
            pass
    return u"#{}".format(elem_id)


# ===========================================================================
# CONSTANTES PARAMÉTRABLES — modifier selon la qualité du DWG
# ===========================================================================

# Résolution de la grille en mètres/pixel (↓ = plus précis, plus lent)
# DWG propre : 0.05  |  DWG standard : 0.10  |  DWG très sale : 0.15
RESOLUTION_M = 0.10

# Pixels de dilatation pour fermer les micro-gaps dans les murs
# Augmenter si des zones qui devraient être fermées ne le sont pas
# Gap en mètres ≈ DILATATION_PIX × RESOLUTION_M × 2
DILATATION_PIX = 2

# Surface minimale d'une pièce (m²) — filtre les artefacts
AIRE_MIN_M2 = 2.0

# Tolérance de simplification des polylignes de contour (mètres)
SIMPLIFIER_TOL_M = 0.10

# Marge autour du DWG pour garantir le flood fill extérieur (mètres)
MARGE_M = 1.0

# Mots-clés EXCLUS : les calques dont le nom contient un de ces termes sont
# ignorés du traitement, même s'ils sont visibles dans la vue.
# Comparaison insensible à la casse et aux accents.
# Tous les autres calques VISIBLES dans la vue active sont traités.
MOTS_CLES_EXCLURE = [
    # Mobilier et équipements
    "meuble", "mobilier", "equipement", "cuisine",
    "rangement", "placard",
    # Sanitaires et fluides
    "sanitaire", "plomberie", "wc", "baignoire", "douche",
    "evier", "lavabo", "robinet",
    # Électricité et réseaux
    "electrique", "electricite", "reseau", "gaine_elec",
    # Annotations et repères
    "cote", "texte", "annotation", "repere", "legende",
    "hachure", "hatch", "dim",
    # Végétation et extérieurs non structurels
    "vegetal", "arbre", "parking",
]

# Taille maximale de grille autorisée (pixels total)
GRILLE_MAX_PX = 5000000

# Longueur minimale (mètres) des courbes DWG retenues par construire_carte_pieces_par_courbe.
# Les hachures DWG (lignes courtes ≈ épaisseur de mur, 5–20 cm) sont rejetées,
# ce qui réduit fortement le volume traité (592 k → ~20-50 k courbes) et
# élimine les éléments Revit parasites qui déclenchent la "Jonction automatique" O(n²).
# Régler à 0 pour désactiver (toutes les courbes conservées).
SEUIL_LONG_M = 0.20

# ===========================================================================
# CONSTANTES INTERNES
# ===========================================================================

CELL_VIDE      = 0   # cellule vide, non visitée
CELL_MUR       = 1   # mur rasterisé
CELL_EXTERIEUR = 2   # marqué extérieur par le flood fill
# Les pièces reçoivent un ID entier >= 3

PIEDS_EN_M = 0.3048  # facteur de conversion


# ===========================================================================
# CONVERSIONS D'UNITÉS
# ===========================================================================

def pied_en_m(v):
    return v * PIEDS_EN_M

def m_en_pied(v):
    return v / PIEDS_EN_M


# ===========================================================================
# EXTRACTION GÉOMÉTRIE DWG
# ===========================================================================

def extraire_courbes_dwg(instance, vue, couches_actives=None, couches_exclues=None, cats_masquees=None):
    """
    Extrait toutes les courbes d'un ImportInstance DWG en coordonnées monde.

    Stratégie correcte pour les ImportInstance :
    - options.View est OBLIGATOIRE pour obtenir la géométrie dans le référentiel
      de la vue active (et non dans un espace local ambigu).
    - On utilise GetSymbolGeometry() + composition explicite des DB.Transform
      pour éviter le double-transform des appels GetInstanceGeometry() récursifs.
    - NOTE : GetSymbolGeometry() ignore options.View → la visibilité des calques
      doit être filtrée via couches_exclues (blacklist) + cats_masquees (fallback
      BYBLOCK), pas via les options Revit.

    couches_actives : set d'int (GraphicsStyleId) — whitelist (None = tout accepter).
    couches_exclues : set d'int (GraphicsStyleId) — blacklist BYLAYER.
    cats_masquees   : set d'int (Category.Id) — blacklist pour objets BYBLOCK/explicite.
    Retourne une liste de DB.Curve en coordonnées monde (pieds Revit).
    """
    options = DB.Options()
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = True   # GetSymbolGeometry ignore View de toute façon
    options.View = vue   # ancre la géométrie dans l'espace monde de la vue

    courbes = []
    try:
        geom_elem = instance.get_Geometry(options)
        if geom_elem is None:
            return courbes

        for obj in geom_elem:
            try:
                if isinstance(obj, DB.GeometryInstance):
                    sym = obj.GetSymbolGeometry()
                    if sym is not None:
                        _extraire_sym(sym, courbes, obj.Transform,
                                      couches_actives, couches_exclues, cats_masquees)
                elif isinstance(obj, DB.Curve):
                    if _couche_autorisee(obj, couches_actives, couches_exclues, cats_masquees):
                        courbes.append(obj)
            except Exception:
                pass

    except Exception as e:
        _log("**Avertissement** extraction géom. : {}".format(str(e)))

    return courbes


def _extraire_sym(geom_elem, courbes, transform_vers_monde,
                  couches_actives, couches_exclues=None, cats_masquees=None):
    """
    Parcourt récursivement la géométrie SYMBOLIQUE (coordonnées locales).
    transform_vers_monde : DB.Transform qui convertit les coords locales → monde.

    Pour les blocs imbriqués (DWG blocks) :
      nouveau_transform = transform_vers_monde * obj.Transform
      (applique d'abord le transform local du bloc, puis le transform vers monde)

    couches_actives : set d'int (GraphicsStyleId) — whitelist.
    couches_exclues : set d'int (GraphicsStyleId) — blacklist BYLAYER.
    cats_masquees   : set d'int (Category.Id) — blacklist BYBLOCK/explicite.
    """
    if geom_elem is None:
        return

    for obj in geom_elem:
        try:
            if isinstance(obj, DB.GeometryInstance):
                try:
                    t_compose = transform_vers_monde * obj.Transform
                except Exception:
                    t_compose = transform_vers_monde
                sym = obj.GetSymbolGeometry()
                if sym is not None:
                    _extraire_sym(sym, courbes, t_compose,
                                  couches_actives, couches_exclues, cats_masquees)

            elif isinstance(obj, DB.Curve):
                if _couche_autorisee(obj, couches_actives, couches_exclues, cats_masquees):
                    try:
                        courbes.append(obj.CreateTransformed(transform_vers_monde))
                    except Exception:
                        courbes.append(obj)

            elif hasattr(obj, 'GetCoordinates'):
                if _couche_autorisee(obj, couches_actives, couches_exclues, cats_masquees):
                    try:
                        pts = list(obj.GetCoordinates())
                        for i in range(len(pts) - 1):
                            try:
                                pt0 = transform_vers_monde.OfPoint(pts[i])
                                pt1 = transform_vers_monde.OfPoint(pts[i + 1])
                                courbes.append(DB.Line.CreateBound(pt0, pt1))
                            except Exception:
                                pass
                    except Exception:
                        pass

        except Exception:
            pass


# Cache {GraphicsStyleId.IntegerValue → Category.Id.IntegerValue}.
# Rempli à la demande durant l'extraction ; évite d'appeler doc.GetElement()
# pour chaque courbe (seuls les IDs non encore vus entraînent un appel API).
# Doit être vidé au début de chaque pipeline (voir _lancer_pipeline).
_cache_gs_a_cat = {}


def _resoudre_cat_id(gs_int_id):
    """
    Résout le Category.Id.IntegerValue d'un GraphicsStyle donné par son IntegerValue.
    Utilise _cache_gs_a_cat pour ne pas répéter doc.GetElement() à chaque courbe.
    Retourne None si impossible.
    """
    if gs_int_id in _cache_gs_a_cat:
        return _cache_gs_a_cat[gs_int_id]
    val = None
    try:
        gs = doc.GetElement(DB.ElementId(gs_int_id))
        if gs is not None and hasattr(gs, 'GraphicsStyleCategory'):
            cat = gs.GraphicsStyleCategory
            if cat is not None:
                val = cat.Id.IntegerValue
    except Exception:
        pass
    _cache_gs_a_cat[gs_int_id] = val
    return val


def _couche_autorisee(obj, couches_actives=None, couches_exclues=None, cats_masquees=None):
    """
    Retourne True si l'objet appartient aux couches autorisées.

    couches_actives : set d'int (GraphicsStyleId.IntegerValue) — whitelist.
                      Vide/None = tout accepter (sauf couches_exclues).
    couches_exclues : set d'int (GraphicsStyleId.IntegerValue) — blacklist.
                      Priorité absolue. Couvre les objets BYLAYER (style = calque).
    cats_masquees   : set d'int (Category.Id.IntegerValue) des calques masqués.
                      Fallback pour les objets BYBLOCK ou à style explicite dont
                      GraphicsStyleId ne correspond pas à l'ID de la sous-catégorie
                      mais dont GraphicsStyle.GraphicsStyleCategory pointe bien
                      vers la sous-catégorie du calque.
    """
    try:
        gid = obj.GraphicsStyleId
        if gid is None:
            return True
        int_id = gid.IntegerValue
        # -1 = ElementId.InvalidElementId → objet sans couche identifiable → accepter
        if int_id < 0:
            return True

        # 1. Vérification rapide par ID de style (objets BYLAYER)
        if couches_exclues and int_id in couches_exclues:
            return False

        # 2. Fallback pour objets BYBLOCK / couleur explicite :
        #    résoudre la Category via le GraphicsStyle element
        if cats_masquees:
            cat_id = _resoudre_cat_id(int_id)
            if cat_id is not None and cat_id in cats_masquees:
                return False

        # 3. Whitelist : si définie, n'accepter que ces couches
        if couches_actives:
            return int_id in couches_actives

        # 4. Pas de whitelist → accepter tout (blacklists déjà vérifiées)
        return True
    except Exception:
        return True  # en cas d'erreur, ne pas bloquer


# ===========================================================================
# BOÎTE ENGLOBANTE
# ===========================================================================

def calculer_bbox_m(courbes):
    """
    Calcule la boîte englobante de toutes les courbes en mètres.
    Retourne (x_min, y_min, x_max, y_max).
    """
    x_min = float('inf')
    y_min = float('inf')
    x_max = float('-inf')
    y_max = float('-inf')

    for c in courbes:
        try:
            for i in [0, 1]:
                pt = c.GetEndPoint(i)
                xm = pied_en_m(pt.X)
                ym = pied_en_m(pt.Y)
                if xm < x_min: x_min = xm
                if ym < y_min: y_min = ym
                if xm > x_max: x_max = xm
                if ym > y_max: y_max = ym
            # Points intermédiaires pour les arcs
            if not isinstance(c, DB.Line):
                for t in [0.25, 0.5, 0.75]:
                    try:
                        pt = c.Evaluate(t, True)
                        xm = pied_en_m(pt.X)
                        ym = pied_en_m(pt.Y)
                        if xm < x_min: x_min = xm
                        if ym < y_min: y_min = ym
                        if xm > x_max: x_max = xm
                        if ym > y_max: y_max = ym
                    except Exception:
                        pass
        except Exception:
            pass

    return x_min, y_min, x_max, y_max


# ===========================================================================
# RASTERISATION
# ===========================================================================

def rasteriser(courbes, bbox_m, resolution_m):
    """
    Rasterise les courbes dans une grille 2D (bytearray).
    Adapte automatiquement la résolution si la grille dépasse GRILLE_MAX_PX.
    Retourne (grille, nb_cols, nb_lignes, x_orig_m, y_orig_m, resolution_eff_m).
    """
    x_min, y_min, x_max, y_max = bbox_m

    # Ajouter marge
    x_min -= MARGE_M
    y_min -= MARGE_M
    x_max += MARGE_M
    y_max += MARGE_M

    # Adapter la résolution si nécessaire
    res = resolution_m
    while True:
        nc = int(math.ceil((x_max - x_min) / res)) + 2
        nl = int(math.ceil((y_max - y_min) / res)) + 2
        if nc * nl <= GRILLE_MAX_PX or res > 1.0:
            break
        res *= 1.5
        _log("**Info** : résolution ajustée à {:.3f} m (grille trop grande)".format(res))

    nb_cols   = int(math.ceil((x_max - x_min) / res)) + 2
    nb_lignes = int(math.ceil((y_max - y_min) / res)) + 2

    grille = bytearray(nb_cols * nb_lignes)

    def marquer_mur(col, ligne):
        if 0 <= col < nb_cols and 0 <= ligne < nb_lignes:
            grille[ligne * nb_cols + col] = CELL_MUR

    def monde_en_px(xm, ym):
        col  = int((xm - x_min) / res)
        lig  = int((ym - y_min) / res)
        return col, lig

    for courbe in courbes:
        _rasteriser_courbe(courbe, monde_en_px, marquer_mur, res)

    return grille, nb_cols, nb_lignes, x_min, y_min, res


def _rasteriser_courbe(courbe, monde_en_px, marquer_mur, res_m):
    """Rasterise une courbe individuelle (ligne → Bresenham, arc → sampling)."""
    try:
        if isinstance(courbe, DB.Line):
            pt0 = courbe.GetEndPoint(0)
            pt1 = courbe.GetEndPoint(1)
            c0, l0 = monde_en_px(pied_en_m(pt0.X), pied_en_m(pt0.Y))
            c1, l1 = monde_en_px(pied_en_m(pt1.X), pied_en_m(pt1.Y))
            _bresenham(c0, l0, c1, l1, marquer_mur)
        else:
            # Arc ou courbe quelconque : échantillonnage
            lon_m = pied_en_m(courbe.Length)
            n = max(2, int(lon_m / res_m) + 1)
            prev = None
            for i in range(n + 1):
                t = float(i) / n
                try:
                    pt = courbe.Evaluate(t, True)
                    col, lig = monde_en_px(pied_en_m(pt.X), pied_en_m(pt.Y))
                    if prev is not None:
                        _bresenham(prev[0], prev[1], col, lig, marquer_mur)
                    prev = (col, lig)
                except Exception:
                    pass
    except Exception:
        pass


def _bresenham(x0, y0, x1, y1, marquer):
    """Algorithme de Bresenham — trace un segment discret dans la grille."""
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        marquer(x0, y0)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


def _pixels_bresenham(x0, y0, x1, y1):
    """
    Génère les pixels (col, lig) d'un segment par l'algorithme de Bresenham.
    Variante générateur de _bresenham — utilisée pour le mapping courbes→pièces.
    """
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        yield (x0, y0)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy


# ===========================================================================
# DILATATION MORPHOLOGIQUE (fermeture des micro-gaps)
# ===========================================================================

def dilater_grille(grille, nb_cols, nb_lignes, rayon):
    """
    Dilate les pixels MUR de `rayon` pixels pour fermer les micro-gaps.
    Stratégie efficace : itère uniquement sur les pixels MUR existants.
    Retourne une nouvelle grille.
    """
    if rayon <= 0:
        return grille

    # Collecter les pixels MUR initiaux (avant dilatation)
    pixels_mur = []
    for lig in range(nb_lignes):
        for col in range(nb_cols):
            if grille[lig * nb_cols + col] == CELL_MUR:
                pixels_mur.append((lig, col))

    nouvelle = bytearray(grille)
    for (lig, col) in pixels_mur:
        for dl in range(-rayon, rayon + 1):
            for dc in range(-rayon, rayon + 1):
                nl = lig + dl
                nc = col + dc
                if 0 <= nl < nb_lignes and 0 <= nc < nb_cols:
                    if nouvelle[nl * nb_cols + nc] == CELL_VIDE:
                        nouvelle[nl * nb_cols + nc] = CELL_MUR

    return nouvelle


# ===========================================================================
# FLOOD FILL EXTÉRIEUR
# ===========================================================================

def flood_fill_exterieur(grille, nb_cols, nb_lignes):
    """
    BFS depuis les 4 bords — marque toutes les cellules VIDE atteignables
    comme CELL_EXTERIEUR. Modifie grille en place.
    """
    file = collections.deque()

    # Amorcer depuis les 4 bordures
    for col in range(nb_cols):
        for lig in [0, nb_lignes - 1]:
            if grille[lig * nb_cols + col] == CELL_VIDE:
                grille[lig * nb_cols + col] = CELL_EXTERIEUR
                file.append((lig, col))

    for lig in range(1, nb_lignes - 1):
        for col in [0, nb_cols - 1]:
            if grille[lig * nb_cols + col] == CELL_VIDE:
                grille[lig * nb_cols + col] = CELL_EXTERIEUR
                file.append((lig, col))

    voisins_4 = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    while file:
        lig, col = file.popleft()
        for dl, dc in voisins_4:
            nl = lig + dl
            nc = col + dc
            if 0 <= nl < nb_lignes and 0 <= nc < nb_cols:
                if grille[nl * nb_cols + nc] == CELL_VIDE:
                    grille[nl * nb_cols + nc] = CELL_EXTERIEUR
                    file.append((nl, nc))


# ===========================================================================
# DÉTECTION DES COMPOSANTES CONNEXES (PIÈCES)
# ===========================================================================

def detecter_composantes(grille, nb_cols, nb_lignes, aire_min_px):
    """
    BFS sur les cellules CELL_VIDE restantes (intérieur après flood fill ext.).
    Retourne list de (id_piece, centroide_px, aire_px).
    Modifie grille en place (marque chaque composante avec son id >= 3).
    """
    composantes = []
    id_courant = 3
    voisins_4 = [(-1, 0), (1, 0), (0, -1), (0, 1)]

    for lig_dep in range(nb_lignes):
        for col_dep in range(nb_cols):
            if grille[lig_dep * nb_cols + col_dep] != CELL_VIDE:
                continue

            # Nouvelle composante connexe
            file = collections.deque()
            file.append((lig_dep, col_dep))
            grille[lig_dep * nb_cols + col_dep] = id_courant

            somme_lig = 0
            somme_col = 0
            aire = 0

            while file:
                lig, col = file.popleft()
                somme_lig += lig
                somme_col += col
                aire += 1

                for dl, dc in voisins_4:
                    nl = lig + dl
                    nc = col + dc
                    if 0 <= nl < nb_lignes and 0 <= nc < nb_cols:
                        if grille[nl * nb_cols + nc] == CELL_VIDE:
                            grille[nl * nb_cols + nc] = id_courant
                            file.append((nl, nc))

            if aire >= aire_min_px:
                centroide = (float(somme_lig) / aire, float(somme_col) / aire)
                composantes.append((id_courant, centroide, aire))

            id_courant += 1

    return composantes


# ===========================================================================
# EXTRACTION DU CONTOUR (arêtes frontière)
# ===========================================================================

def extraire_aretes_contour(grille, nb_cols, nb_lignes, id_piece):
    """
    Pour une composante donnée, retourne toutes les arêtes sur sa frontière.
    Une arête est une frontière entre une cellule de la pièce et une cellule
    qui n'appartient pas à la pièce.
    Retourne list de (x0, y0, x1, y1) en coordonnées pixel (coins de cellules).
    """
    aretes = []

    for lig in range(nb_lignes):
        for col in range(nb_cols):
            if grille[lig * nb_cols + col] != id_piece:
                continue

            # Bord haut : entre (col, lig) et (col+1, lig) en coord coin
            if lig == 0 or grille[(lig - 1) * nb_cols + col] != id_piece:
                aretes.append((col, lig, col + 1, lig))
            # Bord bas
            if lig == nb_lignes - 1 or grille[(lig + 1) * nb_cols + col] != id_piece:
                aretes.append((col, lig + 1, col + 1, lig + 1))
            # Bord gauche
            if col == 0 or grille[lig * nb_cols + (col - 1)] != id_piece:
                aretes.append((col, lig, col, lig + 1))
            # Bord droit
            if col == nb_cols - 1 or grille[lig * nb_cols + (col + 1)] != id_piece:
                aretes.append((col + 1, lig, col + 1, lig + 1))

    return aretes


# ===========================================================================
# CHAÎNAGE DES ARÊTES EN POLYLIGNES FERMÉES
# ===========================================================================

def chainer_en_polylignes(aretes):
    """
    Chaîne des segments (x0,y0,x1,y1) en polylignes fermées.
    Parcours par arêtes non visitées (évite les doublons au niveau des sommets).
    Retourne list de list de (x, y).
    """
    if not aretes:
        return []

    # Déduplication des arêtes et construction du graphe d'adjacence
    adj = {}       # point → liste de points voisins
    ensemble = set()

    for x0, y0, x1, y1 in aretes:
        pt0 = (x0, y0)
        pt1 = (x1, y1)
        cle = (min(pt0, pt1), max(pt0, pt1))
        if cle in ensemble:
            continue
        ensemble.add(cle)
        if pt0 not in adj:
            adj[pt0] = []
        if pt1 not in adj:
            adj[pt1] = []
        adj[pt0].append(pt1)
        adj[pt1].append(pt0)

    polylignes = []
    aretes_restantes = set(ensemble)

    while aretes_restantes:
        # Prendre une arête de départ
        arete_dep = next(iter(aretes_restantes))
        aretes_restantes.discard(arete_dep)

        pt_dep     = arete_dep[0]
        pt_courant = arete_dep[1]
        polyligne  = [pt_dep, pt_courant]

        while True:
            # Chercher une arête non visitée depuis pt_courant
            pt_suivant = None
            for v in adj.get(pt_courant, []):
                cle = (min(pt_courant, v), max(pt_courant, v))
                if cle in aretes_restantes:
                    aretes_restantes.discard(cle)
                    pt_suivant = v
                    break

            if pt_suivant is None:
                # Fermer si possible
                cle_fermeture = (min(pt_courant, pt_dep), max(pt_courant, pt_dep))
                if cle_fermeture in aretes_restantes or pt_suivant == pt_dep:
                    aretes_restantes.discard(cle_fermeture)
                    polyligne.append(pt_dep)
                break

            if pt_suivant == pt_dep:
                polyligne.append(pt_dep)
                break

            polyligne.append(pt_suivant)
            pt_courant = pt_suivant

        if len(polyligne) >= 4:
            polylignes.append(polyligne)

    return polylignes


# ===========================================================================
# SIMPLIFICATION RAMER-DOUGLAS-PEUCKER
# ===========================================================================

def simplifier_rdp(pts, tolerance):
    """
    Simplifie une polyligne (liste de (x,y)) par Ramer-Douglas-Peucker.
    Gère le cas fermé (pts[0] == pts[-1]).
    """
    if len(pts) <= 2:
        return pts

    def dist_pt_seg(px, py, ax, ay, bx, by):
        dx = bx - ax
        dy = by - ay
        if dx == 0 and dy == 0:
            return math.sqrt((px - ax) ** 2 + (py - ay) ** 2)
        t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / float(dx * dx + dy * dy)))
        return math.sqrt((px - (ax + t * dx)) ** 2 + (py - (ay + t * dy)) ** 2)

    def _rdp(segment, eps):
        if len(segment) <= 2:
            return segment
        d_max = 0.0
        i_max = 0
        for i in range(1, len(segment) - 1):
            d = dist_pt_seg(
                segment[i][0], segment[i][1],
                segment[0][0], segment[0][1],
                segment[-1][0], segment[-1][1]
            )
            if d > d_max:
                d_max = d
                i_max = i
        if d_max > eps:
            gauche = _rdp(segment[:i_max + 1], eps)
            droite = _rdp(segment[i_max:], eps)
            return gauche[:-1] + droite
        return [segment[0], segment[-1]]

    est_fermee = (len(pts) > 2 and pts[0] == pts[-1])
    if est_fermee:
        res = _rdp(pts[:-1], tolerance)
        if res:
            res.append(res[0])
        return res
    return _rdp(pts, tolerance)


# ===========================================================================
# CONVERSION PIXEL ↔ COORDONNÉES REVIT
# ===========================================================================

def px_en_revit(col, ligne, x_orig_m, y_orig_m, res_m):
    """Convertit (col, ligne) pixel en (x, y) en pieds Revit."""
    return m_en_pied(x_orig_m + col * res_m), m_en_pied(y_orig_m + ligne * res_m)


# ===========================================================================
# UTILITAIRES REVIT
# ===========================================================================

def obtenir_vue_plan_et_niveau():
    """Retourne (vue ViewPlan, niveau Level) depuis la vue active."""
    vue = uidoc.ActiveView
    if not isinstance(vue, DB.ViewPlan):
        _afficher_message(u"Activez une vue en plan (Floor Plan) avant de lancer ce script.")
        script.exit()
    niveau = vue.GenLevel
    if niveau is None:
        _afficher_message(u"Impossible de déterminer le niveau de la vue active.")
        script.exit()
    return vue, niveau


def collecter_import_instances(vue):
    """Retourne les ImportInstances DWG visibles dans la vue donnée."""
    return list(
        DB.FilteredElementCollector(doc, vue.Id)
        .OfClass(DB.ImportInstance)
        .WhereElementIsNotElementType()
        .ToElements()
    )


def choisir_instance_dwg(vue):
    """Demande à l'utilisateur de choisir un ImportInstance DWG visible dans la vue active."""
    instances = collecter_import_instances(vue)
    if not instances:
        _afficher_message(
            u"Aucun DWG importé ou lié trouvé dans la vue active.\n\n"
            u"Vérifiez que le DWG est visible dans cette vue en plan."
        )
        script.exit()

    noms = {}
    for inst in instances:
        try:
            nom = inst.Category.Name
        except Exception:
            nom = "DWG #{}".format(inst.Id.IntegerValue)
        # Dédoublonner les noms identiques
        cle = nom
        compteur = 1
        while cle in noms:
            cle = "{} ({})".format(nom, compteur)
            compteur += 1
        noms[cle] = inst

    if len(noms) == 1:
        return list(noms.values())[0]

    choix = forms.SelectFromList.show(
        sorted(noms.keys()),
        title="NM-BATII — Sélectionner le DWG à analyser",
        multiselect=False
    )
    if not choix:
        script.exit()
    return noms[choix]


# ===========================================================================
# DÉTECTION ET SÉLECTION DES COUCHES DWG
# ===========================================================================

def scanner_couches_dwg(instance, vue=None):
    """
    Scanne les CALQUES (layers AutoCAD) d'un ImportInstance DWG.

    Un calque DWG est représenté dans Revit comme une SOUS-CATEGORIE de la
    catégorie principale de l'import (instance.Category.SubCategories).

    Retourne un dict trié :
      {nom_calque: (gs_ref, subcat, ids_gs)}
        gs_ref  : GraphicsStyle de référence (pour le nom, toujours non-None)
        subcat  : Category de la sous-catégorie (pour le test de visibilité)
        ids_gs  : set d'ints (GraphicsStyleId.IntegerValue) de ce calque
                  → inclut les styles PROJECTION ET CUT.

    Pourquoi stocker les deux styles :
      Revit assigne à chaque objet géométrique un GraphicsStyleId qui peut être
      le style Projection OU Cut selon son positionnement relatif au plan de coupe
      de la vue. Pour les DWG plan importés dans une vue de niveau, les deux cas
      peuvent se produire. Stocker les deux IDs garantit que _couche_autorisee()
      reconnaît l'objet quel que soit le style utilisé.
    """
    couches = {}   # {nom: (gs_ref, subcat, ids_gs)}

    # --- Méthode principale : sous-catégories de l'import (= calques DWG) ---
    try:
        cat_import = instance.Category
        if cat_import is not None:
            for subcat in cat_import.SubCategories:
                try:
                    nom = subcat.Name
                    gs_proj = subcat.GetGraphicsStyle(DB.GraphicsStyleType.Projection)
                    gs_cut  = subcat.GetGraphicsStyle(DB.GraphicsStyleType.Cut)
                    gs_ref  = gs_proj or gs_cut
                    if gs_ref is None or nom in couches:
                        continue
                    ids_gs = set()
                    if gs_proj is not None:
                        ids_gs.add(gs_proj.Id.IntegerValue)
                    if gs_cut is not None:
                        ids_gs.add(gs_cut.Id.IntegerValue)
                    couches[nom] = (gs_ref, subcat, ids_gs)
                except Exception:
                    pass
    except Exception as e:
        _log("**Avertissement** scan calques (SubCategories) : {}".format(str(e)))

    if couches:
        return dict(sorted(couches.items()))

    # --- Fallback : scan géométrique (si SubCategories ne fonctionne pas) ---
    # Dans le fallback, on n'a pas accès à la subcat directement → on stocke None.
    # Les IDs sont lus directement depuis les objets géométriques → toujours corrects.
    _log("*Fallback : scan géométrique des calques...*")
    options = DB.Options()
    options.ComputeReferences = False
    options.IncludeNonVisibleObjects = True

    def _scan_geo(geom_elem):
        for obj in geom_elem:
            try:
                if isinstance(obj, DB.GeometryInstance):
                    sub = obj.GetSymbolGeometry()
                    if sub:
                        _scan_geo(sub)
                if hasattr(obj, 'GraphicsStyleId'):
                    gid = obj.GraphicsStyleId
                    if gid and gid != DB.ElementId.InvalidElementId:
                        gs = doc.GetElement(gid)
                        if gs:
                            try:
                                sub_cat = gs.GraphicsStyleCategory
                            except Exception:
                                sub_cat = None
                            nom_gs = gs.Name
                            if nom_gs not in couches:
                                couches[nom_gs] = (gs, sub_cat, {gid.IntegerValue})
                            else:
                                couches[nom_gs][2].add(gid.IntegerValue)
            except Exception:
                pass

    try:
        geom_elem = instance.get_Geometry(options)
        if geom_elem:
            for obj in geom_elem:
                try:
                    if isinstance(obj, DB.GeometryInstance):
                        sym = obj.GetSymbolGeometry()
                        if sym:
                            _scan_geo(sym)
                    elif hasattr(obj, 'GraphicsStyleId'):
                        gid = obj.GraphicsStyleId
                        if gid and gid != DB.ElementId.InvalidElementId:
                            gs = doc.GetElement(gid)
                            if gs:
                                try:
                                    sub_cat = gs.GraphicsStyleCategory
                                except Exception:
                                    sub_cat = None
                                nom_gs = gs.Name
                                if nom_gs not in couches:
                                    couches[nom_gs] = (gs, sub_cat, {gid.IntegerValue})
                                else:
                                    # Ajouter l'ID supplémentaire (Projection ou Cut)
                                    couches[nom_gs][2].add(gid.IntegerValue)
                except Exception:
                    pass
    except Exception as e:
        _log("**Avertissement** scan calques (géométrie) : {}".format(str(e)))

    return dict(sorted(couches.items()))


def _normaliser_chaine(s):
    """Normalise une chaîne pour comparaison insensible casse + accents."""
    s = s.lower()
    remplacements = [
        (u'\xe9', 'e'), (u'\xe8', 'e'), (u'\xea', 'e'), (u'\xeb', 'e'),
        (u'\xe0', 'a'), (u'\xe2', 'a'), (u'\xe4', 'a'),
        (u'\xf4', 'o'), (u'\xf6', 'o'),
        (u'\xf9', 'u'), (u'\xfb', 'u'), (u'\xfc', 'u'),
        (u'\xee', 'i'), (u'\xef', 'i'),
        (u'\xe7', 'c'),
    ]
    for src, dst in remplacements:
        s = s.replace(src, dst)
    return s




def choisir_couches_limites(instance, vue):
    """
    Construit la blacklist des calques DWG à ignorer dans le traitement.

    Règles (par ordre de priorité) :
      1. Calque masqué dans la vue active → ignoré (blacklist).
      2. Nom contient un terme de MOTS_CLES_EXCLURE → ignoré (blacklist).
      3. Tous les autres calques visibles → traités.

    Retourne : tuple (couches_actives, ids_exclues, cats_masquees)
      - couches_actives : set() toujours vide (pas de whitelist).
      - ids_exclues : set d'ints (GraphicsStyleId.IntegerValue Projection+Cut)
        des calques masqués/exclus. Filtre les objets BYLAYER.
      - cats_masquees : set d'ints (Category.Id.IntegerValue) des calques masqués
        uniquement. Filtre les objets BYBLOCK/style explicite via
        _couche_autorisee fallback → _resoudre_cat_id().

    Détection de visibilité :
      - subcat.get_Visible(vue) : méthode principale.
      - vue.GetCategoryHidden(subcat.Id) : double vérification indépendante.
      Les deux sont testés séparément pour couvrir les variantes de comportement
      selon la version Revit et le type d'import DWG.
    """
    _log("**Scan des couches DWG...**")
    toutes = scanner_couches_dwg(instance)

    if not toutes:
        _log("*Aucune couche identifiée — toutes les couches traitées.*")
        return (set(), set(), set())

    noms_tries = sorted(toutes.keys())
    _log("**{}** couche(s) trouvée(s).".format(len(noms_tries)))

    exclure_normes = [_normaliser_chaine(m) for m in MOTS_CLES_EXCLURE]
    ids_exclues  = set()
    cats_masquees = set()
    masquees_noms = []
    exclues_noms  = []

    for nom in noms_tries:
        _gs_ref, subcat, ids_gs = toutes[nom]
        nom_norm = _normaliser_chaine(nom)

        # ── Règle 1 : calque masqué dans la vue ──────────────────────────────
        # Deux méthodes testées indépendamment car get_Visible() peut être
        # unreliable pour les sous-catégories DWG importées selon la version Revit.
        masquee = False
        if subcat is not None:
            try:
                if not subcat.get_Visible(vue):
                    masquee = True
            except Exception:
                pass
            if not masquee:
                try:
                    if bool(vue.GetCategoryHidden(subcat.Id)):
                        masquee = True
                except Exception:
                    pass

        if masquee:
            ids_exclues.update(ids_gs)
            # cats_masquees permet le fallback BYBLOCK dans _couche_autorisee
            if subcat is not None:
                try:
                    cats_masquees.add(subcat.Id.IntegerValue)
                except Exception:
                    pass
            masquees_noms.append(nom)
            continue

        # ── Règle 2 : nom contient un terme EXCLURE ───────────────────────────
        if any(m in nom_norm for m in exclure_normes):
            ids_exclues.update(ids_gs)
            if subcat is not None:
                try:
                    cats_masquees.add(subcat.Id.IntegerValue)
                except Exception:
                    pass
            exclues_noms.append(nom)

    _log("  Masqués ignorés  ({}) : {}".format(
        len(masquees_noms),
        u", ".join([u"`{}`".format(c) for c in masquees_noms]) or u"aucun"))
    _log("  Mot-clé ignorés  ({}) : {}".format(
        len(exclues_noms),
        u", ".join([u"`{}`".format(c) for c in exclues_noms]) or u"aucun"))
    _log("  Traités          ({}) : {}".format(
        len(noms_tries) - len(masquees_noms) - len(exclues_noms),
        u"tous les autres calques visibles"))

    return (set(), ids_exclues, cats_masquees)


# ===========================================================================
# CRÉATION DES ÉLÉMENTS REVIT
# ===========================================================================

def creer_sketch_plane(doc, niveau):
    """Crée un SketchPlane horizontal à l'élévation du niveau (doit être dans une transaction)."""
    elevation = niveau.Elevation
    plan = DB.Plane.CreateByNormalAndOrigin(
        DB.XYZ.BasisZ,
        DB.XYZ(0.0, 0.0, elevation)
    )
    return DB.SketchPlane.Create(doc, plan)


def creer_limites_piece(doc, vue, sketch_plane, pts_revit_pieds):
    """
    Crée les Room Boundary Lines depuis une polyligne en pieds Revit.
    pts_revit_pieds : list de (x_pied, y_pied)
    Retourne le nombre de segments créés.
    """
    if len(pts_revit_pieds) < 3:
        return 0

    z = sketch_plane.GetPlane().Origin.Z
    curves = DB.CurveArray()

    for i in range(len(pts_revit_pieds) - 1):
        x0, y0 = pts_revit_pieds[i]
        x1, y1 = pts_revit_pieds[i + 1]
        longueur = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
        if longueur < 1e-6:   # ignorer les segments dégénérés
            continue
        try:
            curves.Append(DB.Line.CreateBound(
                DB.XYZ(x0, y0, z),
                DB.XYZ(x1, y1, z)
            ))
        except Exception:
            pass

    if curves.Size == 0:
        return 0

    try:
        doc.Create.NewRoomBoundaryLines(sketch_plane, curves, vue)
        return curves.Size
    except Exception as e:
        _log("  *Avertissement séparateurs* : {}".format(str(e)))
        return 0


def creer_piece_revit(doc, niveau, centroide_pieds):
    """Place une pièce Revit au centroïde (x, y) en pieds."""
    x, y = centroide_pieds
    try:
        return doc.Create.NewRoom(niveau, DB.UV(x, y))
    except Exception as e:
        _log("  *Avertissement pièce* : {}".format(str(e)))
        return None


# ===========================================================================
# APPROCHE VECTORIELLE — courbes DWG comme limites de pièces
# ===========================================================================
# Pourquoi cette approche :
#   L'approche raster (pixel → polyligne → simplification) produit toujours un
#   décalage (quantification pixel) et des chanfreins (RDP sur escalier raster).
#   En utilisant directement les courbes DWG originales, on obtient des limites
#   parfaitement coïncidentes avec le DWG, sans décalage ni chanfrein.
#
# Algorithme :
#   1. Pour chaque pixel CELL_MUR dans grille_orig adjacent à un pixel de pièce
#      dans grille (après composantes), on note : pixel_idx → set(id_piece).
#   2. Pour chaque courbe DWG, on parcourt ses pixels (Bresenham) et on regarde
#      si ce pixel est dans le dict ci-dessus → courbe liée à une ou des pièces.
#   3. On crée les Room Boundary Lines directement depuis ces courbes DWG.
# ===========================================================================

def construire_carte_pieces_par_courbe(courbes, grille, grille_orig, nb_cols, nb_lignes,
                                        x_orig_m, y_orig_m, res_m):
    """
    Mappe chaque courbe DWG originale à la ou les pièce(s) dont elle est la limite.

    grille     : grille dilatée APRÈS flood fill + détection composantes (IDs ≥ 3).
    grille_orig: grille AVANT dilatation (CELL_VIDE=0, CELL_MUR=1).

    Retourne : dict {id_piece: [DB.Curve, ...]}

    Optimisations vs version précédente :
    ─────────────────────────────────────
    1. Pré-filtre longueur (SEUIL_LONG_M) : réduit 592 k → 20-50 k courbes.
       Élimine les hachures DWG (≈ épaisseur mur) qui ne sont pas des limites de pièces
       et qui, si elles passaient, créeraient des milliers d'éléments Revit parasites.

    2. Dict pixel_vers_pieces remplacé par une recherche directe :
       Pour chaque pixel Bresenham de la courbe, on vérifie grille_orig[pixel] == CELL_MUR
       PUIS on cherche les IDs de pièces dans le voisinage dans grille.
       → Supprime la passe O(n_pixels_total × rayon²) préliminaire.
       → Un seul parcours des données (meilleure localité de cache).

    3. Bresenham inline (pas de générateur Python) :
       Les générateurs en IronPython 2.7 ont un overhead significatif par `yield`.
       La boucle while inline évite ~3 M appels de yield pour 592 k courbes × 5 px moyen.

    4. Sortie anticipée par pixel : si un pixel CELL_MUR est trouvé sur la courbe,
       on cherche les pièces adjacentes et on continue. Si la courbe ne touche aucun
       pixel CELL_MUR (hachure ou annotation), on ne fait rien (O(curve_len) seulement).
    """
    courbes_par_piece = {}
    rayon = DILATATION_PIX + 1

    # Pré-filtre longueur : élimine les courbes trop courtes (hachures DWG).
    seuil_long_pied = m_en_pied(SEUIL_LONG_M) if SEUIL_LONG_M > 0 else 0.0

    for courbe in courbes:

        # ── Filtre longueur ──────────────────────────────────────────────────
        if seuil_long_pied > 0:
            try:
                if courbe.Length < seuil_long_pied:
                    continue
            except Exception:
                pass   # courbe sans Length → on la garde

        pieces_touchees = set()

        try:
            if isinstance(courbe, DB.Line):
                pt0 = courbe.GetEndPoint(0)
                pt1 = courbe.GetEndPoint(1)
                c0 = int((pied_en_m(pt0.X) - x_orig_m) / res_m)
                l0 = int((pied_en_m(pt0.Y) - y_orig_m) / res_m)
                c1 = int((pied_en_m(pt1.X) - x_orig_m) / res_m)
                l1 = int((pied_en_m(pt1.Y) - y_orig_m) / res_m)

                # ── Bresenham inline ─────────────────────────────────────────
                dx = abs(c1 - c0); dy = abs(l1 - l0)
                sx = 1 if c0 < c1 else -1
                sy = 1 if l0 < l1 else -1
                err = dx - dy
                cx, lx = c0, l0
                while True:
                    if 0 <= cx < nb_cols and 0 <= lx < nb_lignes:
                        # Vérification directe dans grille_orig (pas de dict lookup)
                        if grille_orig[lx * nb_cols + cx] == CELL_MUR:
                            for dl in range(-rayon, rayon + 1):
                                nl = lx + dl
                                if nl < 0 or nl >= nb_lignes:
                                    continue
                                for dc in range(-rayon, rayon + 1):
                                    nc = cx + dc
                                    if 0 <= nc < nb_cols:
                                        id_p = grille[nl * nb_cols + nc]
                                        if id_p >= 3:
                                            pieces_touchees.add(id_p)
                    if cx == c1 and lx == l1:
                        break
                    e2 = 2 * err
                    if e2 > -dy:
                        err -= dy
                        cx += sx
                    if e2 < dx:
                        err += dx
                        lx += sy

            else:
                # Arc ou courbe quelconque : échantillonnage + même logique
                lon_m = pied_en_m(courbe.Length)
                n = max(2, int(lon_m / res_m) + 1)
                for i in range(n + 1):
                    t = float(i) / n
                    try:
                        pt = courbe.Evaluate(t, True)
                        cx = int((pied_en_m(pt.X) - x_orig_m) / res_m)
                        lx = int((pied_en_m(pt.Y) - y_orig_m) / res_m)
                        if 0 <= cx < nb_cols and 0 <= lx < nb_lignes:
                            if grille_orig[lx * nb_cols + cx] == CELL_MUR:
                                for dl in range(-rayon, rayon + 1):
                                    nl = lx + dl
                                    if nl < 0 or nl >= nb_lignes:
                                        continue
                                    for dc in range(-rayon, rayon + 1):
                                        nc = cx + dc
                                        if 0 <= nc < nb_cols:
                                            id_p = grille[nl * nb_cols + nc]
                                            if id_p >= 3:
                                                pieces_touchees.add(id_p)
                    except Exception:
                        pass

        except Exception:
            pass

        for id_p in pieces_touchees:
            if id_p not in courbes_par_piece:
                courbes_par_piece[id_p] = []
            courbes_par_piece[id_p].append(courbe)

    return courbes_par_piece


def _projeter_courbe_sur_z(courbe, z):
    """
    Projette une courbe DWG sur le plan Z donné en conservant sa forme exacte.
    Retourne une DB.Curve projetée, ou None si la courbe est invalide.
    """
    try:
        if isinstance(courbe, DB.Line):
            pt0 = courbe.GetEndPoint(0)
            pt1 = courbe.GetEndPoint(1)
            if pt0.DistanceTo(pt1) < 1e-6:
                return None
            return DB.Line.CreateBound(
                DB.XYZ(pt0.X, pt0.Y, z),
                DB.XYZ(pt1.X, pt1.Y, z)
            )
        elif isinstance(courbe, DB.Arc):
            # Arc : utiliser 3 points (départ, milieu, fin) projetés sur Z
            pt0 = courbe.GetEndPoint(0)
            pt1 = courbe.GetEndPoint(1)
            ptM = courbe.Evaluate(0.5, True)
            p0z = DB.XYZ(pt0.X, pt0.Y, z)
            pMz = DB.XYZ(ptM.X, ptM.Y, z)
            p1z = DB.XYZ(pt1.X, pt1.Y, z)
            # Vérifier que les 3 points ne sont pas colinéaires
            if p0z.DistanceTo(p1z) < 1e-6 or p0z.DistanceTo(pMz) < 1e-6:
                return None
            return DB.Arc.Create(p0z, p1z, pMz)
        else:
            # Courbe générique : tenter de la déplacer sur Z via Transform
            try:
                pt0 = courbe.GetEndPoint(0)
                pt1 = courbe.GetEndPoint(1)
                dz = z - pt0.Z
                if abs(dz) < 1e-9:
                    return courbe  # déjà au bon Z
                translation = DB.Transform.CreateTranslation(DB.XYZ(0, 0, dz))
                return courbe.CreateTransformed(translation)
            except Exception:
                return None
    except Exception:
        return None


def creer_limites_depuis_courbes_dwg(doc, vue, sketch_plane, courbes_dwg):
    """
    Crée les Room Boundary Lines directement depuis les courbes DWG originales.
    Les courbes sont déjà en coordonnées monde Revit (pieds).
    Résultat : limites parfaitement coïncidentes avec le DWG, sans décalage ni chanfrein.
    Retourne le nombre de segments créés.
    """
    if not courbes_dwg:
        return 0

    z = sketch_plane.GetPlane().Origin.Z
    curves = DB.CurveArray()

    for courbe in courbes_dwg:
        try:
            courbe_z = _projeter_courbe_sur_z(courbe, z)
            if courbe_z is not None:
                curves.Append(courbe_z)
        except Exception:
            pass

    if curves.Size == 0:
        return 0

    try:
        doc.Create.NewRoomBoundaryLines(sketch_plane, curves, vue)
        return curves.Size
    except Exception as e:
        _log("  *Avertissement séparateurs DWG* : {}".format(str(e)))
        return 0


# ===========================================================================
# PIPELINE PRINCIPAL
# ===========================================================================

def executer_pipeline(grille, nb_cols, nb_lignes, x_orig_m, y_orig_m, res_m,
                       vue, niveau, point_clic_px=None, grille_orig=None, courbes=None,
                       progress_cb=None):
    """
    Flood fill → composantes → limites DWG vectorielles → création Revit.

    Stratégie prioritaire (approche vectorielle) :
      Pour chaque pièce détectée, les courbes DWG originales adjacentes sont
      utilisées directement comme Room Boundary Lines → zéro décalage, zéro chanfrein.
    Fallback (approche raster) :
      Si aucune courbe DWG n'est trouvée pour une pièce (DWG très lacunaire ou
      couches non filtrées), on revient au contour raster simplifié.

    point_clic_px : (col, ligne) si mode point-and-click, None si mode auto.
    grille_orig   : grille AVANT dilatation (nécessaire pour le mapping vectoriel).
    courbes       : list[DB.Curve] extraites du DWG (coordonnées monde Revit).
    Retourne (nb_pieces_creees, nb_limites_creees).
    """
    # --- Flood fill extérieur ---
    _log("- Flood fill extérieur...")
    if progress_cb: progress_cb(10, u"Flood fill extérieur...")
    flood_fill_exterieur(grille, nb_cols, nb_lignes)

    # --- Détection des composantes ---
    aire_min_px = max(1, int(AIRE_MIN_M2 / (res_m ** 2)))
    _log("- Détection des composantes connexes (seuil : {} px²)...".format(aire_min_px))
    if progress_cb: progress_cb(35, u"Détection des composantes connexes...")
    composantes = detecter_composantes(grille, nb_cols, nb_lignes, aire_min_px)

    if not composantes:
        _log("\n**Aucune zone fermée détectée.**")
        _log("Conseils :\n"
                        "- Augmenter `DILATATION_PIX` (ex : 3 ou 4)\n"
                        "- Réduire `RESOLUTION_M` (ex : 0.05)\n"
                        "- Réduire `AIRE_MIN_M2`\n"
                        "- Vérifier que le DWG contient des contours fermés")
        return 0, 0

    _log("- **{}** zone(s) intérieure(s) détectée(s).".format(len(composantes)))

    # --- Mapping vectoriel : courbes DWG → pièces ---
    # Construit une fois pour toutes les pièces (une seule passe sur grille + courbes).
    courbes_par_piece = {}
    if courbes and grille_orig is not None:
        if progress_cb: progress_cb(55, u"Mapping courbes DWG → pièces...")
        _log("- Mapping courbes DWG → pièces (approche vectorielle)...")
        courbes_par_piece = construire_carte_pieces_par_courbe(
            courbes, grille, grille_orig, nb_cols, nb_lignes,
            x_orig_m, y_orig_m, res_m
        )
        # Compter uniquement les pièces valides (au-dessus du seuil aire_min_px)
        ids_composantes   = set(c[0] for c in composantes)
        nb_avec_courbes   = len([id_p for id_p in courbes_par_piece if id_p in ids_composantes])
        nb_micro_zones    = len(courbes_par_piece) - nb_avec_courbes
        _log(
            "  {}/{} pièce(s) avec courbes DWG identifiées{}.".format(
                nb_avec_courbes, len(composantes),
                " ({} micro-zone(s) ignorée(s) < {:.1f} m²)".format(nb_micro_zones, AIRE_MIN_M2)
                if nb_micro_zones > 0 else ""
            ))

    # --- Filtre mode point-and-click ---
    if point_clic_px is not None:
        col_c, lig_c = point_clic_px
        id_cible = grille[lig_c * nb_cols + col_c]
        composantes = [c for c in composantes if c[0] == id_cible]
        if not composantes:
            _log("**Aucune pièce détectée au point cliqué.**")
            _log("Le point est peut-être dans un mur ou à l'extérieur.")
            return 0, 0
        _log("- Mode point-and-click : 1 pièce ciblée (id={}).".format(id_cible))

    # --- Tolerance de simplification raster (fallback uniquement) ---
    tol_px = max(0.5, SIMPLIFIER_TOL_M / res_m)

    nb_pieces  = 0
    nb_limites = 0

    # =========================================================================
    # COLLECTE ET DÉDUPLICATION DES COURBES DWG
    # =========================================================================
    # Problème sans déduplication :
    #   Un mur entre la pièce A et la pièce B apparaît dans courbes_par_piece[A]
    #   ET dans courbes_par_piece[B]. Itérer les composantes sans dédup crée ce
    #   mur en DOUBLE dans Revit, ce qui :
    #     - double le nombre d'éléments Room Boundary Line,
    #     - aggrave exponentiellement la "Jonction automatique" O(n²) de Revit.
    #
    # Solution : collecter toutes les courbes uniques (via id(courbe)) AVANT la
    # transaction, puis les créer en UN SEUL appel NewRoomBoundaryLines (ou en
    # batches de BATCH_LIMITES si le volume est grand).
    # =========================================================================

    _seen_obj_ids  = set()   # id() Python → unicité d'objet DWG
    _courbes_uniq  = []      # courbes DWG dédupliquées (toutes pièces confondues)
    _ids_avec_dwg  = set()   # ids de composantes ayant au moins une courbe DWG

    for id_piece, _, _ in composantes:
        liste = courbes_par_piece.get(id_piece)
        if not liste:
            continue
        _ids_avec_dwg.add(id_piece)
        for c in liste:
            oid = id(c)
            if oid not in _seen_obj_ids:
                _seen_obj_ids.add(oid)
                _courbes_uniq.append(c)

    _log("- {} courbe(s) DWG uniques à créer ({} composante(s) avec fallback raster).".format(
        len(_courbes_uniq),
        len(composantes) - len(_ids_avec_dwg)
    ))

    if progress_cb: progress_cb(70, u"Création des éléments Revit...")
    with revit.Transaction("NM-BATII : Créer séparateurs et pièces depuis DWG"):

        sketch_plane = creer_sketch_plane(doc, niveau)
        z = sketch_plane.GetPlane().Origin.Z

        # ─── 1. Créer TOUTES les limites DWG en un seul lot (ou par batches) ─
        # Un seul lot → une seule invocation de la "Jonction automatique" Revit.
        # BATCH_LIMITES évite les timeouts sur les très grandes collections.
        if _courbes_uniq:
            if progress_cb: progress_cb(73, u"Création des Room Boundary Lines (DWG)...")
            curves_batch = DB.CurveArray()
            for courbe in _courbes_uniq:
                try:
                    courbe_z = _projeter_courbe_sur_z(courbe, z)
                    if courbe_z is None:
                        continue
                    curves_batch.Append(courbe_z)
                    if curves_batch.Size >= BATCH_LIMITES:
                        try:
                            doc.Create.NewRoomBoundaryLines(sketch_plane, curves_batch, vue)
                            nb_limites += curves_batch.Size
                        except Exception as _be:
                            _log(u"  *Avertissement batch DWG* : {}".format(str(_be)))
                        curves_batch = DB.CurveArray()
                except Exception:
                    pass
            if curves_batch.Size > 0:
                try:
                    doc.Create.NewRoomBoundaryLines(sketch_plane, curves_batch, vue)
                    nb_limites += curves_batch.Size
                except Exception as _be:
                    _log(u"  *Avertissement batch DWG (fin)* : {}".format(str(_be)))
            _log("  [vecteur] {} segment(s) DWG créé(s).".format(nb_limites))

        # ─── 2. Fallback raster pour les pièces sans courbe DWG ──────────────
        # Seulement pour les composantes sans aucune courbe DWG associée.
        composantes_fallback = [c for c in composantes if c[0] not in _ids_avec_dwg]
        if composantes_fallback:
            if progress_cb: progress_cb(82, u"Fallback raster ({} pièce(s))...".format(
                len(composantes_fallback)))
            for id_piece, _, _ in composantes_fallback:
                _log("  [fallback raster] pièce id={} — contour pixélisé.".format(id_piece))
                aretes = extraire_aretes_contour(grille, nb_cols, nb_lignes, id_piece)
                if aretes:
                    polylignes_px = chainer_en_polylignes(aretes)
                    if polylignes_px:
                        polyligne_px  = max(polylignes_px, key=len)
                        polyligne_rdp = simplifier_rdp(polyligne_px, tol_px)
                        if len(polyligne_rdp) >= 3:
                            pts_revit = [px_en_revit(c, l, x_orig_m, y_orig_m, res_m)
                                         for c, l in polyligne_rdp]
                            nb_seg = creer_limites_piece(doc, vue, sketch_plane, pts_revit)
                            if nb_seg > 0:
                                nb_limites += nb_seg
                                _log("  [fallback] {} segment(s) créé(s).".format(nb_seg))

        # ─── 3. Placer les pièces ─────────────────────────────────────────────
        if progress_cb: progress_cb(90, u"Placement des pièces Revit...")
        for id_piece, centroide_px, aire_px in composantes:
            aire_m2 = aire_px * res_m * res_m
            lig_c_px, col_c_px = centroide_px
            centroide_pieds = px_en_revit(col_c_px, lig_c_px, x_orig_m, y_orig_m, res_m)
            piece = creer_piece_revit(doc, niveau, centroide_pieds)
            if piece is not None:
                nb_pieces += 1
                _log("  Pièce {} créée — {:.1f} m²".format(
                    _linkify(piece.Id), aire_m2))

    return nb_pieces, nb_limites


# ===========================================================================
# HELPERS UI
# ===========================================================================

try:
    from System.Windows.Forms import Application as _WinFormsApp
    def _pump_ui():
        """Rafraîchit l'interface WPF pendant un calcul long (coût CPU minimal)."""
        _WinFormsApp.DoEvents()
except Exception:
    def _pump_ui():
        pass


def _set_revit_owner(window):
    """Attache la fenêtre WPF comme enfant Win32 de la fenêtre principale Revit."""
    try:
        from System.Windows.Interop import WindowInteropHelper
        import System
        helper = WindowInteropHelper(window)
        helper.Owner = uidoc.Application.MainWindowHandle
    except Exception:
        pass


def _centrer_sur_revit(window):
    """
    Centre la fenetre sur la zone de travail de l'ecran hebergeant Revit.

    A brancher sur l'evenement Loaded : la fenetre etant en SizeToContent, sa
    taille n'est connue qu'une fois mesuree. Meme correction DPI que
    _ancrer_a_droite (pixels physiques -> DIP).
    """
    zg = zd = zh = zb = None
    try:
        from pyrevit import HOST_APP as _HOST
        zone = _HOST.proc_screen_workarea
        if zone is not None:
            facteur = 1.0
            try:
                f = _HOST.proc_screen_scalefactor
                if f:
                    facteur = float(f)
            except Exception:
                pass
            if facteur <= 0:
                facteur = 1.0
            zg = zone.Left   / facteur
            zd = zone.Right  / facteur
            zh = zone.Top    / facteur
            zb = zone.Bottom / facteur
    except Exception:
        pass

    if zd is None:
        try:
            from System.Windows import SystemParameters
            wa = SystemParameters.WorkArea
            zg, zd, zh, zb = wa.Left, wa.Right, wa.Top, wa.Bottom
        except Exception:
            return

    try:
        largeur = window.ActualWidth  or window.Width  or 400
        hauteur = window.ActualHeight or window.Height or 200
        gauche = zg + ((zd - zg) - largeur) / 2.0
        haut   = zh + ((zb - zh) - hauteur) / 2.0
        if gauche < zg:
            gauche = zg
        if haut < zh:
            haut = zh
        window.Left = gauche
        window.Top  = haut
    except Exception:
        pass


def _preparer_centrage(window, message=u""):
    """Centre la fenetre sur Revit. Le placement se fait au Loaded, la fenetre
    etant en SizeToContent (taille inconnue avant le rendu)."""
    try:
        window.WindowStartupLocation = WindowStartupLocation.Manual
        window.Loaded += lambda s, e: _centrer_sur_revit(window)
    except Exception:
        pass


def _ancrer_a_droite(window, marge=12):
    """
    Ancre la fenetre au bord droit de la zone de travail de l'ecran hebergeant
    Revit, centree verticalement. A appeler APRES le rendu (ActualWidth connu).

    Piege DPI : proc_screen_workarea est en PIXELS PHYSIQUES alors que
    Left/Top sont en DIP — sans division par le facteur d'echelle la fenetre
    part hors ecran des 125 %.
    """
    zg = zd = zh = zb = None
    try:
        from pyrevit import HOST_APP as _HOST
        zone = _HOST.proc_screen_workarea
        if zone is not None:
            facteur = 1.0
            try:
                f = _HOST.proc_screen_scalefactor
                if f:
                    facteur = float(f)
            except Exception:
                pass
            if facteur <= 0:
                facteur = 1.0
            zg = zone.Left   / facteur
            zd = zone.Right  / facteur
            zh = zone.Top    / facteur
            zb = zone.Bottom / facteur
    except Exception:
        pass

    if zd is None:
        try:
            from System.Windows import SystemParameters
            wa = SystemParameters.WorkArea
            zg, zd, zh, zb = wa.Left, wa.Right, wa.Top, wa.Bottom
        except Exception:
            return

    try:
        largeur = window.ActualWidth  or window.Width  or 540
        hauteur = window.ActualHeight or window.Height or 660
        gauche = zd - largeur - marge
        if gauche < zg:
            gauche = zg
        window.Left = gauche
        haut = zh + ((zb - zh) - hauteur) / 2.0
        if haut < zh:
            haut = zh
        window.Top = haut
    except Exception:
        pass


def _afficher_message(message, titre=u"NM-BATII", owner=None):
    """Affiche un message dans une fenêtre WPF (ResultWindow.xaml)."""
    result_xaml = os.path.join(os.path.dirname(__file__), 'ResultWindow.xaml')
    try:
        win = forms.WPFWindow(result_xaml)
        win.Title = titre
        win.txtMessage.Text = message
        _set_revit_owner(win)
        _preparer_centrage(win, message)   # centre sur Revit, sans saut
        win.btnClose.Click += lambda s, e: win.Close()
        win.ShowDialog()
    except Exception:
        MessageBox.Show(message, titre)


def _afficher_resultat(nb_pieces, nb_limites, owner=None):
    """Affiche la fenêtre WPF de résultat (ResultWindow.xaml)."""
    result_xaml = os.path.join(os.path.dirname(__file__), 'ResultWindow.xaml')
    try:
        win = forms.WPFWindow(result_xaml)
        _msg = u"{} pièce(s) créée(s)\n{} séparateur(s) de pièce créé(s)".format(
            nb_pieces, nb_limites)
        win.txtMessage.Text = _msg
        _set_revit_owner(win)
        _preparer_centrage(win, _msg)   # centre sur Revit, sans saut
        win.btnClose.Click += lambda s, e: win.Close()
        win.ShowDialog()
    except Exception:
        MessageBox.Show(
            u"{} pièce(s) créée(s)\n{} séparateur(s) créé(s)".format(nb_pieces, nb_limites),
            u"NM-BATII — Résultat"
        )


# ===========================================================================
# EXTERNAL EVENT — Revit API depuis la fenêtre non modale
# ===========================================================================

class _PipelineHandler(IExternalEventHandler):
    """
    Délègue les appels Revit API au thread principal Revit (contexte sûr).
    L'action planifiée est exécutée par Revit quand il est en état stable.
    Pattern obligatoire pour les fenêtres non modales (palette) en Revit.
    Voir : https://www.revitapidocs.com/2024/6285066f-4e6e-8aae-3bc3-0d0f6a3dc582.htm
    """

    def __init__(self):
        self._fn = [None]   # mutable — pas de nonlocal en IronPython 2.7

    def planifier(self, fn):
        """Enregistre l'action à exécuter (appelé depuis le thread WPF)."""
        self._fn[0] = fn

    def Execute(self, uiapp):
        """Exécuté par Revit sur le thread principal à un moment sûr."""
        fn = self._fn[0]
        self._fn[0] = None
        if fn:
            try:
                fn()
            except Exception:
                pass   # les erreurs sont gérées à l'intérieur de fn()

    def GetName(self):
        return u"NM-BATII — Détection de pièces"


_action_handler = _PipelineHandler()
_ext_event      = ExternalEvent.Create(_action_handler)


# ===========================================================================
# FENÊTRE DE PROGRESSION
# ===========================================================================

class FenetreProgression(forms.WPFWindow):
    """Fenêtre légère affichant l'avancement du pipeline."""

    def __init__(self, owner=None):
        _xaml = os.path.join(os.path.dirname(__file__), 'ProgressWindow.xaml')
        forms.WPFWindow.__init__(self, _xaml)
        if owner is not None:
            self.Owner = owner

    def mettre_a_jour(self, pct, message, detail=""):
        """Met à jour la barre et rafraîchit l'affichage (CPU minimal)."""
        self.txtStatus.Text    = message
        self.txtCurrent.Text   = detail
        self.progressBar.Value = min(100, max(0, pct))
        _pump_ui()


# ===========================================================================
# INTERFACE WPF PRINCIPALE
# ===========================================================================

class FenetrePiecesDetect(forms.WPFWindow):
    """Boite de dialogue principale (non modale) pour la détection de pièces depuis DWG."""

    def __init__(self, vue, niveau, instances, config):
        xaml_path = os.path.join(os.path.dirname(__file__), 'WPFWindow.xaml')
        forms.WPFWindow.__init__(self, xaml_path)
        _charger_styles()

        # Maintient le namespace IronPython en vie via le GC .NET.
        # _module_globals garde l'objet dict en vie (évite la GC du dict).
        # _G est une copie défensive des valeurs : IronPython / pyRevit peut
        # vider les valeurs du dict lors de la finalisation du module
        # (après le retour de IExternalCommand.Execute()). _restaurer_globals()
        # réinjecte ces valeurs avant chaque appel qui en a besoin.
        self._module_globals = globals()
        self._G = dict(globals())
        self._G.setdefault('__file__', __file__)

        # Stocker les références ExternalEvent comme attributs d'instance :
        # garantit leur survie via le GC .NET même après sortie du thread script.
        self._action_handler = _action_handler
        self._ext_event      = _ext_event

        self._vue    = vue
        self._niveau = niveau

        # Config capturée sur le thread UI avant chaque lancement (voir btn_*_Click).
        # _lancer_pipeline s'exécute sur le thread Revit API : il ne peut PAS accéder
        # aux contrôles WPF. On stocke ici la config lue depuis l'interface AVANT
        # de déclencher l'ExternalEvent, puis on la réapplique dans _lancer_pipeline.
        # → Corrige le bug de restauration des globals IronPython (voir _restaurer_globals).
        self._cfg_courant = {}

        # Câbler les événements boutons (non déclarés en XAML)
        self.btn_toutes.Click      += self.btn_toutes_Click
        self.btn_une_piece.Click   += self.btn_une_piece_Click
        self.btn_charger.Click     += self.btn_charger_Click
        self.btn_enregistrer.Click += self.btn_enregistrer_Click
        self.btn_fermer.Click      += lambda s, e: self.Close()

        # Remplir le ComboBox des DWG
        self._instances_map = {}
        for inst in instances:
            try:
                nom = inst.Category.Name
            except Exception:
                nom = "DWG #{}".format(inst.Id.IntegerValue)
            cle = nom
            compteur = 1
            while cle in self._instances_map:
                cle = "{} ({})".format(nom, compteur)
                compteur += 1
            self._instances_map[cle] = inst
            self.cmb_dwg.Items.Add(cle)

        if self._instances_map:
            self.cmb_dwg.SelectedIndex = 0
        else:
            self.lbl_aucun_dwg.Visibility = Visibility.Visible
            self.cmb_dwg.IsEnabled        = False
            self.btn_toutes.IsEnabled     = False
            self.btn_une_piece.IsEnabled  = False

        # ── Cache des contrôles WPF ───────────────────────────────────────────
        # pyRevit's WPFWindow.__getattr__ appelle FindName() à CHAQUE accès
        # self.txt_xxx. FindName parcourt l'arbre visuel à chaque appel. Cacher
        # les références ici élimine cette traversée répétée, ce qui accélère
        # _appliquer_preset (6 accès) et _appliquer_config (8 accès).
        self._c_resolution = self.FindName('txt_resolution')
        self._c_dilatation = self.FindName('txt_dilatation')
        self._c_aire_min   = self.FindName('txt_aire_min')
        self._c_simplifier = self.FindName('txt_simplifier')
        self._c_marge      = self.FindName('txt_marge')
        self._c_grille_max = self.FindName('txt_grille_max')
        self._c_exclure    = self.FindName('txt_exclure')

        # ── Initialisation de TOUS les champs depuis config.json ─────────────
        # Fait en PREMIER pour que txt_inclure et txt_exclure soient toujours
        # remplis (les présets ne modifient que les champs numériques).
        self._appliquer_config(config)

        # ── Présets de qualité ────────────────────────────────────────────────
        # Chargés depuis config.json › detect_pieces_dwg › presets_qualite.
        # L'utilisateur peut ajouter de nouveaux présets en éditant config.json
        # manuellement : chaque entrée est un dict avec les mêmes clés que cfg.
        # Le ComboBox est peuplé ici ; SelectionChanged applique les valeurs.
        self._presets = []   # list[dict] — présets dans l'ordre de config.json
        try:
            presets_cfg = config.get('presets_qualite', [])
            if isinstance(presets_cfg, list):
                for p in presets_cfg:
                    if isinstance(p, dict) and 'nom' in p:
                        self._presets.append(p)
        except Exception:
            pass

        # ── Peuplement du ComboBox des présets ───────────────────────────────
        if self._presets:
            for p in self._presets:
                self.cmb_preset.Items.Add(p['nom'])

            # Sélectionner "Standard" par défaut (préset dont le nom contient
            # "standard", insensible à la casse). Si absent : premier préset.
            idx_std = 0
            for i, p in enumerate(self._presets):
                if u'standard' in p.get('nom', u'').lower():
                    idx_std = i
                    break
            # Câbler l'événement AVANT de fixer SelectedIndex pour que le handler
            # soit actif dès la première sélection (y compris l'init).
            # SelectedIndex = idx_std déclenche SelectionChanged → _appliquer_preset
            # qui surcharge les champs numériques avec les valeurs du préset Standard.
            self.cmb_preset.SelectionChanged += self.cmb_preset_SelectionChanged
            self.cmb_preset.SelectedIndex = idx_std
        else:
            self.cmb_preset.Items.Add(u"(aucun préset dans config.json)")
            self.cmb_preset.IsEnabled = False
            # _appliquer_config a déjà été appelé plus haut

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def _appliquer_config(self, cfg):
        # Utilise les références cachées (self._c_*) pour éviter FindName() répété.
        # Fallback sur les constantes du module pour les clés manquantes.
        self._c_resolution.Text = str(cfg.get('resolution_m',     RESOLUTION_M))
        self._c_dilatation.Text = str(cfg.get('dilatation_pix',   DILATATION_PIX))
        self._c_aire_min.Text   = str(cfg.get('aire_min_m2',      AIRE_MIN_M2))
        self._c_simplifier.Text = str(cfg.get('simplifier_tol_m', SIMPLIFIER_TOL_M))
        self._c_marge.Text      = str(cfg.get('marge_m',          MARGE_M))
        self._c_grille_max.Text = str(cfg.get('grille_max_px',    GRILLE_MAX_PX))
        exclure = cfg.get('mots_cles_exclure', MOTS_CLES_EXCLURE)
        if exclure:
            self._c_exclure.Text = u'\n'.join([u'{}'.format(m) for m in exclure])

    def _lire_config(self):
        def _float(txt, defaut):
            try:   return float(txt.strip())
            except Exception: return defaut

        def _int(txt, defaut):
            try:   return int(txt.strip())
            except Exception: return defaut

        def _mots_cles(txt):
            return [l.strip() for l in txt.splitlines() if l.strip()]

        return {
            'resolution_m':      _float(self._c_resolution.Text, RESOLUTION_M),
            'dilatation_pix':    _int(self._c_dilatation.Text,   DILATATION_PIX),
            'aire_min_m2':       _float(self._c_aire_min.Text,   AIRE_MIN_M2),
            'simplifier_tol_m':  _float(self._c_simplifier.Text, SIMPLIFIER_TOL_M),
            'marge_m':           _float(self._c_marge.Text,      MARGE_M),
            'grille_max_px':     _int(self._c_grille_max.Text,   GRILLE_MAX_PX),
            'mots_cles_exclure': _mots_cles(self._c_exclure.Text),
        }

    @property
    def instance_dwg(self):
        cle = self.cmb_dwg.SelectedItem
        return self._instances_map.get(cle) if cle else None

    # ------------------------------------------------------------------
    # Restauration des globals IronPython
    # ------------------------------------------------------------------

    def _restaurer_globals(self):
        """Réinjecte dans le dict du module les valeurs capturées à l'init.

        Après le retour de IExternalCommand.Execute() (fenêtre non modale),
        pyRevit/IronPython peut vider les valeurs du dict du module (les passer
        à None). Cette méthode les restaure depuis la copie défensive self._G,
        puis rafraîchit les objets Revit depuis pyrevit.revit (toujours dispo).
        """
        g = self._module_globals
        for k, v in self._G.items():
            if g.get(k) is None and v is not None:
                g[k] = v
        try:
            from pyrevit import revit, DB as _DB
            g['doc']   = revit.doc
            g['uidoc'] = revit.uidoc
            g['DB']    = _DB
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Handlers boutons
    # ------------------------------------------------------------------

    def _appliquer_preset(self, preset):
        """
        Applique UNIQUEMENT les paramètres numériques d'un préset dans les TextBox.

        Pourquoi une méthode séparée de _appliquer_config :
          _appliquer_config accède aux globaux du module via les constantes de
          fallback. Dans une fenêtre non-modale, ces globaux peuvent être None
          (nettoyés par IronPython après le retour de IExternalCommand.Execute),
          ce qui lèverait une TypeError silencieuse et annulerait toute la mise
          à jour. Cette méthode n'accède JAMAIS aux globaux : les valeurs de
          fallback sont des littéraux Python purs.

        Utilise les références cachées (self._c_*) : aucun appel FindName().
        """
        try:
            self._c_resolution.Text = str(preset.get('resolution_m',     0.10))
            self._c_dilatation.Text = str(preset.get('dilatation_pix',   2))
            self._c_aire_min.Text   = str(preset.get('aire_min_m2',      2.0))
            self._c_simplifier.Text = str(preset.get('simplifier_tol_m', 0.10))
            self._c_marge.Text      = str(preset.get('marge_m',          1.0))
            self._c_grille_max.Text = str(preset.get('grille_max_px',    5000000))
        except Exception as ex:
            _log(u"  *Avertissement préset* : {}".format(str(ex)))

    def cmb_preset_SelectionChanged(self, sender, args):
        """Applique les valeurs numériques du préset sélectionné dans les champs."""
        idx = self.cmb_preset.SelectedIndex
        if idx < 0 or idx >= len(self._presets):
            return
        self._appliquer_preset(self._presets[idx])

    def btn_charger_Click(self, sender, args):
        self._restaurer_globals()
        dlg = OpenFileDialog()
        dlg.Title  = "Charger une configuration NM-RoomLim"
        dlg.Filter = "Config detection pieces (*.NM-RoomLim)|*.NM-RoomLim|Tous les fichiers (*.*)|*.*"
        if dlg.ShowDialog():
            try:
                with open(dlg.FileName, 'r') as f:
                    cfg = json.load(f)
                self._appliquer_config(cfg)
            except Exception as ex:
                _afficher_message(u"Impossible de charger la configuration :\n{}".format(str(ex)), owner=self)

    def btn_enregistrer_Click(self, sender, args):
        self._restaurer_globals()
        dlg = SaveFileDialog()
        dlg.Title      = "Enregistrer la configuration NM-RoomLim"
        dlg.Filter     = "Config detection pieces (*.NM-RoomLim)|*.NM-RoomLim|Tous les fichiers (*.*)|*.*"
        dlg.DefaultExt = ".NM-RoomLim"
        if dlg.ShowDialog():
            try:
                cfg = self._lire_config()
                with open(dlg.FileName, 'w') as f:
                    json.dump(cfg, f, indent=2, ensure_ascii=False)
            except Exception as ex:
                _afficher_message(u"Impossible d'enregistrer la configuration :\n{}".format(str(ex)), owner=self)

    def btn_toutes_Click(self, sender, args):
        self._restaurer_globals()
        instance = self.instance_dwg
        if instance is None:
            _afficher_message(u"Aucun DWG sélectionné.", owner=self)
            return
        # Capturer la config ICI (thread UI) : les contrôles WPF ne sont
        # accessibles que depuis ce thread. _lancer_pipeline tourne sur le
        # thread Revit API et ne peut pas appeler _lire_config() directement.
        self._cfg_courant = self._lire_config()
        self._appliquer_constantes(self._cfg_courant)
        _inst = [instance]
        _self = [self]
        def _action():
            _self[0]._lancer_pipeline(_inst[0], mode_auto=True)
        self._action_handler.planifier(_action)
        self._ext_event.Raise()

    def btn_une_piece_Click(self, sender, args):
        """Lance la détection sur une pièce cliquée. Reste ouvert pour un nouveau clic."""
        self._restaurer_globals()
        instance = self.instance_dwg
        if instance is None:
            _afficher_message(u"Aucun DWG sélectionné.", owner=self)
            return
        # Même raison que btn_toutes_Click : capturer config sur le thread UI.
        self._cfg_courant = self._lire_config()
        self._appliquer_constantes(self._cfg_courant)
        _inst = [instance]
        _self = [self]
        def _action():
            _self[0]._restaurer_globals()
            pt = None
            try:
                pt = uidoc.Selection.PickPoint(u"Cliquez dans la pièce à détecter")
            except Exception:
                return
            _self[0]._lancer_pipeline(_inst[0], mode_auto=False, point_revit=pt)
        self._action_handler.planifier(_action)
        self._ext_event.Raise()

    # ------------------------------------------------------------------
    # Pipeline
    # ------------------------------------------------------------------

    def _appliquer_constantes(self, cfg):
        global RESOLUTION_M, DILATATION_PIX, AIRE_MIN_M2
        global SIMPLIFIER_TOL_M, MARGE_M, GRILLE_MAX_PX
        global MOTS_CLES_EXCLURE, SEUIL_LONG_M
        RESOLUTION_M      = cfg['resolution_m']
        DILATATION_PIX    = cfg['dilatation_pix']
        AIRE_MIN_M2       = cfg['aire_min_m2']
        SIMPLIFIER_TOL_M  = cfg['simplifier_tol_m']
        MARGE_M           = cfg['marge_m']
        GRILLE_MAX_PX     = cfg['grille_max_px']
        MOTS_CLES_EXCLURE = cfg['mots_cles_exclure']
        # seuil_long_m est un paramètre de perf (pas dans l'UI) — optionnel dans cfg
        if 'seuil_long_m' in cfg:
            SEUIL_LONG_M = float(cfg['seuil_long_m'])

    def _lancer_pipeline(self, instance, mode_auto, point_revit=None):
        """Prépare et exécute le pipeline avec fenêtre de progression."""
        # ─── Restauration des globals IronPython ──────────────────────────────
        # 1. _restaurer_globals() remet les valeurs d'infrastructure qui auraient
        #    été vidées (doc, uidoc, DB) depuis la copie _G prise à l'init.
        # 2. _appliquer_constantes(_cfg_courant) réécrit TOUS les paramètres
        #    métier (MOTS_CLES_EXCLURE, résolution…) depuis la config capturée
        #    sur le thread UI dans btn_*_Click.
        #    ← Sans cette étape, _restaurer_globals restaurerait _G qui contient
        #    les valeurs par défaut du module, ignorant la config utilisateur.
        self._restaurer_globals()
        if self._cfg_courant:
            self._appliquer_constantes(self._cfg_courant)
        vue    = self._vue
        niveau = self._niveau

        prog = FenetreProgression(owner=self)
        prog.Show()

        nb_pieces  = 0
        nb_limites = 0

        try:
            prog.mettre_a_jour(5,  u"Scan des couches DWG...")
            _log(u"\n### Étape 1 — Sélection des couches DWG")
            # Vider le cache GraphicsStyle→Catégorie avant chaque pipeline
            _cache_gs_a_cat.clear()
            couches_actives, ids_exclues, cats_masquees = choisir_couches_limites(instance, vue)

            prog.mettre_a_jour(15, u"Extraction de la géométrie DWG...")
            _log(u"\n### Étape 2 — Extraction géométrie")
            courbes = extraire_courbes_dwg(instance, vue, couches_actives, ids_exclues, cats_masquees)
            _log(u"**{}** courbe(s) extraite(s).".format(len(courbes)))

            if not courbes:
                prog.Close()
                _afficher_message(
                    u"Aucune courbe extraite du DWG.\n\n"
                    u"Causes possibles :\n"
                    u"  - DWG sans géométrie visible dans la vue active\n"
                    u"  - Couches sélectionnées sans géométrie\n"
                    u"  - Format DWG non supporté par Revit",
                    owner=self
                )
                return

            prog.mettre_a_jour(25, u"Calcul de la boîte englobante...")
            bbox_m = calculer_bbox_m(courbes)
            larg_m = bbox_m[2] - bbox_m[0]
            haut_m = bbox_m[3] - bbox_m[1]
            _log(u"**BBox DWG :** {:.1f} × {:.1f} m".format(larg_m, haut_m))

            prog.mettre_a_jour(30, u"Rasterisation ({} m/pixel)...".format(RESOLUTION_M))
            _log(u"\n### Étape 3 — Rasterisation (résolution = {} m)".format(RESOLUTION_M))
            grille, nb_cols, nb_lignes, x_orig_m, y_orig_m, res_eff = rasteriser(
                courbes, bbox_m, RESOLUTION_M
            )
            grille_orig = bytearray(grille)
            _log(u"**Grille :** {} × {} px ({:,} px total)".format(
                nb_cols, nb_lignes, nb_cols * nb_lignes))

            prog.mettre_a_jour(42, u"Dilatation ({} px)...".format(DILATATION_PIX))
            if DILATATION_PIX > 0:
                _log(u"\n### Étape 4 — Dilatation ({} px ≈ {:.0f} cm)".format(
                    DILATATION_PIX, DILATATION_PIX * res_eff * 100))
                grille = dilater_grille(grille, nb_cols, nb_lignes, DILATATION_PIX)

            # Mode point-and-click : convertir le point Revit en pixel
            point_clic_px = None
            if not mode_auto and point_revit is not None:
                xm    = pied_en_m(point_revit.X)
                ym    = pied_en_m(point_revit.Y)
                col_c = int((xm - x_orig_m) / res_eff)
                lig_c = int((ym - y_orig_m) / res_eff)
                if 0 <= col_c < nb_cols and 0 <= lig_c < nb_lignes:
                    point_clic_px = (col_c, lig_c)
                    _log(u"**Point cliqué :** pixel ({}, {})".format(col_c, lig_c))
                else:
                    prog.Close()
                    _afficher_message(u"Le point est en dehors de la zone DWG.", owner=self)
                    return

            prog.mettre_a_jour(50, u"Détection des zones fermées...")
            _log(u"\n### Étape 5 — Pipeline de détection")

            def _cb(pct, msg):
                prog.mettre_a_jour(50 + int(pct * 0.45), msg)

            nb_pieces, nb_limites = executer_pipeline(
                grille, nb_cols, nb_lignes, x_orig_m, y_orig_m, res_eff,
                vue, niveau,
                point_clic_px=point_clic_px,
                grille_orig=grille_orig,
                courbes=courbes,
                progress_cb=_cb
            )

            # Rapport dans le panel de sortie
            _log(u"\n---\n## Rapport final\n")
            _log(u"| Paramètre | Valeur |")
            _log(u"|---|---|")
            _log(u"| Courbes extraites | {} |".format(len(courbes)))
            _log(u"| Résolution effective | {} m |".format(res_eff))
            _log(u"| Grille | {} × {} px |".format(nb_cols, nb_lignes))
            _log(u"| Dilatation | {} px |".format(DILATATION_PIX))
            _log(u"| **Séparateurs créés** | **{}** |".format(nb_limites))
            _log(u"| **Pièces créées** | **{}** |".format(nb_pieces))

            prog.mettre_a_jour(100, u"Terminé.")

        except Exception as e:
            prog.Close()
            _afficher_message(u"Erreur NM-BATII : {}".format(str(e)), owner=self)
            return

        prog.Close()
        _afficher_resultat(nb_pieces, nb_limites, owner=self)


# ===========================================================================
# CORPS DU SCRIPT
# ===========================================================================

try:
    _log(u"# NM-BATII — Détection de pièces depuis DWG\n")

    # 1. Vérifier que la vue active est une vue en plan
    vue = uidoc.ActiveView
    if not isinstance(vue, DB.ViewPlan):
        _afficher_message(
            u"La vue active n'est pas une vue en plan (Floor Plan).\n\n"
            u"Activez une vue en plan avant de lancer ce script."
        )
        script.exit()

    niveau = vue.GenLevel
    if niveau is None:
        _afficher_message(u"Impossible de déterminer le niveau de la vue active.")
        script.exit()

    # 2. Collecter les DWG visibles dans la vue active
    instances = collecter_import_instances(vue)
    if not instances:
        _afficher_message(
            u"Aucun DWG importé ou lié trouvé dans la vue active.\n\n"
            u"Vérifiez que le DWG est visible dans cette vue en plan."
        )
        script.exit()

    # 3. Charger la configuration par défaut
    try:
        cfg_defaut = load_config().get('detect_pieces_dwg', {})
    except Exception:
        cfg_defaut = {}

    # 4. Palette non modale — ExternalEvent + IExternalEventHandler
    #    self._module_globals = globals() dans __init__ maintient les globals IronPython
    #    en vie via le GC .NET tant que la fenêtre est ouverte.
    #    Les boutons délèguent les appels Revit API via _ext_event.Raise().
    fenetre = FenetrePiecesDetect(vue, niveau, instances, cfg_defaut)
    _set_revit_owner(fenetre)
    fenetre.Show()
    # Apres Show() : ActualWidth/Height sont connus, l'ancrage est exact.
    _ancrer_a_droite(fenetre)

except Exception as e:
    _afficher_message(u"Erreur NM-BATII : {}".format(str(e)))