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
NM-BATII — Apercu WPF d'une couleur et d'un motif de remplissage Revit.

Un motif Revit n'est pas une image mais une description GEOMETRIQUE : chaque
FillGrid definit une famille de lignes paralleles par son angle, son origine et
son pas. Il n'existe aucune API rendant une vignette ; il faut donc redessiner
les lignes.

Partage entre le dialogue « Ordre et couleurs des styles de surfaces » et la
palette « Surfaces », qui montrent la meme pastille : une seule implementation
de ce rendu, deja peu evident, plutot que deux copies vouees a diverger.
"""

import math

from Autodesk.Revit.DB import FilteredElementCollector, FillPatternElement


def infos_motifs(doc):
    """
    { nom du motif : (est_solide, [grilles]) } pour un document.

    Les grilles sont conservees pour dessiner sans relire le document a chaque
    rafraichissement : une liste de 54 styles se reconstruit a chaque changement
    de filtre.
    """
    infos = {}
    try:
        for fp in FilteredElementCollector(doc).OfClass(FillPatternElement):
            try:
                motif = fp.GetFillPattern()
                infos[motif.Name] = (motif.IsSolidFill, list(motif.GetFillGrids()))
            except Exception:
                continue
    except Exception:
        pass
    return infos


def brosse(hexa):
    """Pinceau uni depuis '#RRGGBB', ou None si la valeur est inexploitable."""
    if not hexa:
        return None
    try:
        from System.Windows.Media import ColorConverter, SolidColorBrush
        return SolidColorBrush(ColorConverter.ConvertFromString(hexa))
    except Exception:
        return None


def pinceau_apercu(hexa, info, largeur, hauteur):
    """
    Pinceau representant l'apparence d'une entree : couleur ET motif.

    Un remplissage plein donne un aplat ; un motif hachure donne des lignes de
    la couleur sur fond blanc, ce qui est bien ce que Revit affiche : la couleur
    porte les traits, pas le fond.

    L'ECHELLE N'EST PAS CELLE DU PLAN. Le pas le plus fin est ramene a quelques
    pixels pour rester lisible dans une pastille de 16 px — sinon un motif dense
    y virerait a l'aplat uni, et un motif large n'y montrerait aucune ligne.
    L'apercu dit la NATURE du motif — plein, hachure simple, croise, son
    inclinaison — pas sa densite reelle.

    Args:
        hexa (str): couleur '#RRGGBB'.
        info (tuple): (est_solide, [grilles]), tel que rendu par infos_motifs.
        largeur, hauteur (float): taille NOMINALE du rendu. Le pinceau etant
            etire pour remplir sa cible, un ecart important inclinerait les
            hachures a tort : passer une taille proche du reel.

    Returns:
        Brush, ou None si la couleur est inexploitable.
    """
    from System.Windows.Media import (DrawingBrush, DrawingGroup, GeometryDrawing,
                                      GeometryGroup, LineGeometry,
                                      RectangleGeometry, Pen, Brushes)
    from System.Windows import Rect, Point

    fond = brosse(hexa)
    if info is None or info[0] or not info[1] or fond is None:
        return fond                      # aplat, ou motif inconnu du projet

    try:
        grilles = info[1]
        rect = Rect(0, 0, largeur, hauteur)
        diag = math.sqrt(largeur * largeur + hauteur * hauteur)

        pas = [abs(g.Offset) for g in grilles if abs(g.Offset) > 1e-9]
        cible = max(4.0, min(largeur, hauteur) / 3.0)
        echelle = (cible / min(pas)) if pas else 1.0

        lignes = GeometryGroup()
        for g in grilles:
            ecart = max(1.0, abs(g.Offset) * echelle)
            angle = g.Angle
            dx, dy = math.cos(angle), math.sin(angle)
            nx, ny = -dy, dx                       # normale a la famille
            ox, oy = g.Origin.U * echelle, g.Origin.V * echelle
            base = ox * nx + oy * ny

            # Bornes : projection des quatre coins sur la normale.
            proj = [rect.Left * nx + rect.Top * ny,
                    rect.Right * nx + rect.Top * ny,
                    rect.Left * nx + rect.Bottom * ny,
                    rect.Right * nx + rect.Bottom * ny]
            k_min = int(math.floor((min(proj) - base) / ecart)) - 1
            k_max = int(math.ceil((max(proj) - base) / ecart)) + 1
            # Garde-fou : un motif tres dense sature le dessin sans rien
            # apprendre de plus.
            if k_max - k_min > 300:
                k_max = k_min + 300

            for k in range(k_min, k_max + 1):
                p = base + k * ecart
                cx, cy = p * nx, p * ny
                lignes.Children.Add(LineGeometry(
                    Point(cx - dx * diag, cy - dy * diag),
                    Point(cx + dx * diag, cy + dy * diag)))

        groupe = DrawingGroup()
        groupe.Children.Add(GeometryDrawing(Brushes.White, None,
                                            RectangleGeometry(rect)))
        groupe.Children.Add(GeometryDrawing(None, Pen(fond, 1.0), lignes))
        groupe.ClipGeometry = RectangleGeometry(rect)
        return DrawingBrush(groupe)
    except Exception:
        return fond                      # un apercu approximatif vaut mieux que rien
