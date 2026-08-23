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
Utilitaire partagé — Disciplines et sous-disciplines (NM-BATII).

Expose la table `disciplines` de config.json, réglée dans l'onglet
« Disciplines » de la fenêtre des paramètres.

    cfg['disciplines'] = {
      "format": {
        "niveaux":                   6,      # profondeur totale (Code Ouvrage)
        "niveaux_code":              3,      # niveaux de tête formant le Code
        "digits_par_niveau":         [1,1,1,1,1,1],
        "longueur_abrev_discipline": [4,3,3,3,3,3],
        "longueur_abrev_ouvrage":    [3,3,3,3,3,3],
        "separateur":                "-",
        "majuscules":                true
      },
      "table": [
        {"code": "500", "code_ouvrage": "500000", "niveau": 1,
         "discipline": "G CLIMATIQUE", "sous_discipline": "",
         "abrev_discipline": "CLIM", "abrev_resolue": "CLIM",
         "abrev_ouvrage": "", "abrev_ouvrage_resolue": ""},
        {"code": "510", "code_ouvrage": "510000", "niveau": 2,
         "discipline": "G CLIMATIQUE", "sous_discipline": "PLOMBERIE SANITAIRE",
         "abrev_discipline": "{sup1}-PLS", "abrev_resolue": "CLIM-PLS",
         "abrev_ouvrage": "", "abrev_ouvrage_resolue": ""},
        {"code": "511", "code_ouvrage": "511000", "niveau": 3,
         "discipline": "G CLIMATIQUE", "sous_discipline": "PLOMBERIE",
         "abrev_discipline": "{sup1}", "abrev_resolue": "CLIM-PLS",
         "abrev_ouvrage": "", "abrev_ouvrage_resolue": ""},
        {"code": "511", "code_ouvrage": "511100", "niveau": 4,
         "discipline": "G CLIMATIQUE", "sous_discipline": "Eau chaude",
         "abrev_discipline": "{sup1}", "abrev_resolue": "CLIM-PLS",
         "abrev_ouvrage": "ECS", "abrev_ouvrage_resolue": "ECS"}
      ]
    }

TROIS RÈGLES suffisent à tout lire :

  • le CODE OUVRAGE est de LONGUEUR FIXE — la somme des tranches de tous les
    niveaux déclarés — et découpé en une tranche par niveau. C'est LUI qui se
    saisit et qui identifie une ligne. Le niveau est le rang de sa dernière
    tranche non nulle : avec six niveaux d'un chiffre, 500000 est un niveau 1,
    510000 un niveau 2, 511000 un niveau 3, 511100 un niveau 4. Le parent
    s'obtient en remettant à zéro la tranche du niveau courant ;

  • le CODE DISCIPLINE en est la TRONCATURE aux `niveaux_code` premiers
    niveaux — 3 caractères pour 3 niveaux d'un chiffre. Il est donc partagé par
    toute une branche : dans le référentiel de référence, 211 couvre 27 lignes.
    Ne jamais s'en servir comme clé : utiliser `code_ouvrage`, ou
    `get_par_code` qui normalise. Au-delà de `niveaux_code`, une ligne classe
    un OUVRAGE sous la dernière sous-discipline ;

  • DEUX CHAÎNES d'abréviation, sur le même principe de GABARIT : `{sup1}` y
    vaut l'abréviation RÉSOLUE du niveau juste au-dessus DANS LA MÊME CHAÎNE,
    `{sup2}` celle d'encore au-dessus, et ainsi de suite sans limite de rang.
    La clé `*_resolue` est ce gabarit une fois les jetons remplacés :
            "CLIM"         →  CLIM       (racine)
            "{sup1}-PLS"   →  CLIM-PLS   (complète)
            "{sup1}"       →  CLIM-PLS   (rien de plus que le dessus)
            "{sup2}-PLS"   →  CLIM-PLS   (SAUTE le niveau juste au-dessus)
            "PLB"          →  PLB        (remplace tout)
    Le rang compte les ancêtres PRÉSENTS dans la table, pas les niveaux du
    code : une branche à trous se numérote comme elle s'affiche, et aucun jeton
    ne peut viser une ligne inexistante. Un rang au-delà de la branche s'efface
    (la fenêtre des paramètres, elle, le signale).
    Tout est écrit dans la cellule : aucune règle de transmission ni de
    non-répétition à deviner. Les longueurs déclarées dans `format` calibrent
    les caractères SIGNIFIANTS — ni les jetons, ni les séparateurs n'y comptent,
    et un gabarit réduit à un jeton en est dispensé. Les deux chaînes :
      – `abrev_discipline` / `abrev_resolue` sur TOUTES les lignes, ouvrages
        compris. Elles disent de quelle discipline et sous-discipline la ligne
        relève — un ouvrage en a forcément une : « distribution d'eau froide
        sanitaire » relève de Génie Climatique / Plomberie. RACINE : le
        niveau 1. Longueurs : `longueur_abrev_discipline` ;
      – `abrev_ouvrage` / `abrev_ouvrage_resolue`, elles aussi sur TOUTES les
        lignes. Elles nomment l'ouvrage. Ce gabarit accepte un SECOND jeton,
        `{dis}`, qui vaut l'abréviation de discipline RÉSOLUE de la MÊME
        ligne — c'est ainsi qu'une chaîne d'ouvrage se raccroche à sa
        discipline, au départ comme en cours de route :
            niveau 1  "{dis}"        →  CLIM      (valeur IMPOSÉE)
            niveau 2  "{sup1}"       →  CLIM
            niveau 3  "{dis}-ECS"    →  CLIM-PLS-ECS (rebase sur la discipline)
        RACINE : le niveau 1, forcé à `{dis}` et non modifiable dans la fenêtre.
        Longueurs : `longueur_abrev_ouvrage`, réglée à tous les niveaux.
    AUCUNE N'EST UNIQUE : le référentiel autorise les doublons. La seule clé
    d'une ligne est son `code_ouvrage`. Les recherches par désignation rendent
    donc une LISTE (`get_tous_par_abrev`, `get_par_abreviation`) ;
    `get_par_abrev` ne rend que la première correspondance, à n'utiliser que si
    l'unicité est garantie par ailleurs. `etiquette()` rend la désignation qui
    s'applique à une ligne, quel que soit son niveau.

`code_ouvrage`, `niveau` et les deux clés `*_resolue` sont redondants avec le
code et la branche, volontairement : un script consommateur lit une seule clé et
n'a jamais à redécouper le code, à remonter la branche ni à connaître le
séparateur. La fenêtre des paramètres les tient cohérents et refuse
d'enregistrer une table qui ne l'est pas.

Les libellés `discipline` et `sous_discipline` sont écrits en MAJUSCULES par la
fenêtre — sauf `sous_discipline` sur une ligne d'ouvrage, où le libellé nomme un
ouvrage réel et garde sa casse de saisie.

Utilisation :

    import utils.disciplines as _disc
    reload(_disc)                       # cache sys.modules de pyRevit
    from utils.disciplines import (
        get_disciplines, get_disciplines_et_sous, get_enfants,
        get_descendants, get_par_code, get_par_abrev, get_parent,
        get_ancetres, est_ouvrage, libelle,
    )

    for d in get_disciplines():
        print(d['abrev_resolue'], d['discipline'])
        for sd in get_descendants(d['code_ouvrage']):
            print('   ' * sd['niveau'], sd['abrev_resolue'], sd['sous_discipline'])

Le `reload()` n'est pas décoratif : pyRevit garde les modules de lib/ en cache
dans son moteur IronPython partagé, et une fonction ajoutée ici resterait
invisible aux scripts appelants jusqu'au redémarrage de Revit.
"""


import re

# Jetons des gabarits, mêmes valeurs que dans la fenêtre des paramètres —
# c'est le contrat entre la saisie et la relecture.
#   {supN} : l'abréviation résolue du N-ième ancêtre dans la même chaîne, en
#            partant du plus proche. Le rang compte les ancêtres PRÉSENTS dans
#            la table, pas les niveaux du code : une branche à trous se
#            numérote comme elle s'affiche ;
#   {dis}  : l'abréviation de discipline résolue de la même ligne. Propre à
#            `abrev_ouvrage`, dont il est la valeur imposée au niveau 1.
JETON_SUP_MODELE = u'{sup%d}'
JETON_SUP1 = JETON_SUP_MODELE % 1
JETON_DIS = u'{dis}'

RE_SUP = re.compile(ur'\{sup(\d+)\}', re.I)
# « {sup} » sans rang : forme d'avant la numérotation, relue comme {sup1}.
RE_SUP_ANCIEN = re.compile(ur'\{sup\}', re.I)
RE_JETON = re.compile(ur'\{sup\d+\}|\{dis\}', re.I)


def canoniser_jetons(txt):
    """« {SUP2} » et « {Sup} » deviennent « {sup2} » et « {sup1} »."""
    return RE_JETON.sub(lambda m: m.group(0).lower(),
                        RE_SUP_ANCIEN.sub(JETON_SUP1, txt or u''))

# Repli utilisé quand config.json n'a pas encore de section `disciplines`.
FORMAT_DEFAUT = {
    u'niveaux':                   6,
    u'niveaux_code':              3,
    u'digits_par_niveau':         [1, 1, 1, 1, 1, 1],
    u'longueur_abrev_discipline': [4, 3, 3, 3, 3, 3],
    u'longueur_abrev_ouvrage':    [3, 3, 3, 3, 3, 3],
    u'separateur':                u'-',
    u'majuscules':                True,
}

# Aucun plafond de profondeur : la hiérarchie descend aussi bas que le
# référentiel le demande. Ni ce module ni la fenêtre des paramètres n'en
# imposent — le décalage d'affichage et les teintes sont calculés, jamais
# déclarés niveau par niveau.


def _section(cfg=None):
    """
    Section `disciplines` de config.json, jamais None.

    L'import de config_loader est fait ICI et non en tête de module : il tire
    `pyrevit`, indisponible hors Revit. Tant que l'appelant passe `cfg`, ce
    module reste donc chargeable et testable en dehors de Revit.
    """
    if cfg is None:
        from utils.config_loader import load_config
        cfg = load_config()
    section = cfg.get(u'disciplines')
    return section if isinstance(section, dict) else {}


def _entier(valeur, defaut):
    try:
        return int(str(valeur).strip())
    except Exception:
        return defaut


# Longueur d'abréviation : le réglage accepte TROIS formes.
#     0      aucun caractère significatif — la cellule ne porte que des
#            jetons ({supN}, {dis}) et des séparateurs ;
#     3      longueur FIXE ;
#     2;5    BORNES mini;maxi, le mini pouvant valoir 0.
# Dans les trois cas jetons et séparateurs restent autorisés et ne comptent
# jamais dans la longueur.
LG_SEP = u';'
LG_MAX = 12


def bornes_longueur(valeur, defaut=3):
    """
    (mini, maxi) de longueur significative, depuis une valeur de réglage.

    Accepte un entier (format stocké antérieur) comme un texte. Une saisie
    incomprise retombe sur `defaut` en longueur fixe : un réglage illisible
    ne doit pas rendre le référentiel inexploitable.
    """
    txt = u'' if valeur is None else unicode(valeur).strip()
    if not txt:
        return (defaut, defaut)
    if LG_SEP in txt:
        gauche, _sep, droite = txt.partition(LG_SEP)
        mini = _entier(gauche.strip(), None)
        maxi = _entier(droite.strip(), None)
        if mini is None or maxi is None:
            return (defaut, defaut)
        if mini > maxi:
            mini, maxi = maxi, mini
        return (max(0, min(mini, LG_MAX)), max(0, min(maxi, LG_MAX)))
    n = _entier(txt, None)
    if n is None:
        return (defaut, defaut)
    n = max(0, min(n, LG_MAX))
    return (n, n)


def _texte_longueur(valeur, defaut=3):
    """Forme canonique du réglage : « 0 », « 3 » ou « 2;5 »."""
    mini, maxi = bornes_longueur(valeur, defaut)
    if mini == maxi:
        return u'{}'.format(mini)
    return u'{}{}{}'.format(mini, LG_SEP, maxi)


def longueur_conforme(utile, valeur, defaut=3):
    """
    True si `utile` — la chaîne réduite à ses caractères significatifs —
    respecte le réglage.

    Un gabarit qui n'a AUCUN caractère significatif (réduit à « {sup1} »)
    est dispensé quel que soit le réglage : il dit « rien de plus que le
    niveau visé », ce qui est une réponse légitime et non une abréviation
    trop courte.
    """
    if not utile:
        return True
    mini, maxi = bornes_longueur(valeur, defaut)
    return mini <= len(utile) <= maxi


def get_format(cfg=None):
    """
    Règles de format, converties au besoin depuis les schémas antérieurs.

    Trois migrations possibles : l'ancien schéma à deux niveaux (longueur_code /
    digits_discipline / longueur_acronyme / longueur_acronyme_sous), le schéma à
    N niveaux sans frontière de Code, et `acronyme_par_niveau` — la longueur
    unique d'avant la séparation des deux chaînes d'abréviation, reprise pour
    les deux. Dans tous les cas la conversion est exacte : sans frontière
    déclarée, tous les niveaux appartiennent au Code, ce qui reproduit le
    comportement d'avant.

    Passer `cfg` évite de relire config.json quand l'appelant l'a déjà en main.
    """
    brut = _section(cfg).get(u'format') or {}
    nb = _entier(brut.get(u'niveaux'), 0)
    digits = brut.get(u'digits_par_niveau')
    lg_disc = (brut.get(u'longueur_abrev_discipline')
               or brut.get(u'acronyme_par_niveau'))
    lg_ouv = (brut.get(u'longueur_abrev_ouvrage')
              or brut.get(u'acronyme_par_niveau'))

    if nb and isinstance(digits, list) and isinstance(lg_disc, list):
        nb = max(1, nb)
        digits = [max(1, _entier(v, 1)) for v in digits][:nb]
        # Les longueurs restent du TEXTE : elles acceptent « 0 », « 3 » ou
        # des bornes « 2;5 ». Les coercer en entier ferait retomber « 2;5 »
        # sur le défaut et perdrait la borne haute.
        lg_disc = [_texte_longueur(v, 3) for v in lg_disc][:nb]
        lg_ouv = [_texte_longueur(v, 3)
                  for v in (lg_ouv if isinstance(lg_ouv, list) else [])][:nb]
    elif brut:
        longueur = _entier(brut.get(u'longueur_code'), 3)
        tete = max(1, min(_entier(brut.get(u'digits_discipline'), 1),
                          longueur - 1))
        nb = 2
        digits = [tete, max(1, longueur - tete)]
        lg_disc = [_texte_longueur(brut.get(u'longueur_acronyme'), 4),
                   _texte_longueur(brut.get(u'longueur_acronyme_sous'), 3)]
        lg_ouv = list(lg_disc)
    else:
        nb = FORMAT_DEFAUT[u'niveaux']
        digits = list(FORMAT_DEFAUT[u'digits_par_niveau'])
        lg_disc = [_texte_longueur(v, 3)
                   for v in FORMAT_DEFAUT[u'longueur_abrev_discipline']]
        lg_ouv = [_texte_longueur(v, 3)
                  for v in FORMAT_DEFAUT[u'longueur_abrev_ouvrage']]

    while len(digits) < nb:
        digits.append(1)
    while len(lg_disc) < nb:
        lg_disc.append(u'3')
    while len(lg_ouv) < nb:
        lg_ouv.append(u'3')

    # Sans frontière déclarée, tout le code est du Code.
    nb_code = _entier(brut.get(u'niveaux_code'), 0) or nb
    nb_code = max(1, min(nb_code, nb))

    return {
        u'niveaux':                   nb,
        u'niveaux_code':              nb_code,
        u'digits_par_niveau':         digits,
        u'longueur_abrev_discipline': lg_disc,
        u'longueur_abrev_ouvrage':    lg_ouv,
        u'longueur_code':             sum(digits[:nb_code]),
        # Longueur FIXE du Code Ouvrage : c'est celle qu'on saisit.
        u'longueur_code_ouvrage':     sum(digits),
        u'separateur':           brut.get(u'separateur',
                                          FORMAT_DEFAUT[u'separateur']) or u'',
        u'majuscules':           bool(brut.get(u'majuscules', True)),
    }


def get_table(cfg=None):
    """
    Table complète, tous niveaux mêlés, triée par Code Ouvrage.

    Le tri est refait ici plutôt que supposé : config.json peut avoir été
    édité à la main, et l'ordre porte la hiérarchie.
    """
    fmt = get_format(cfg)
    # Filtre sur le CODE OUVRAGE : c'est lui l'identifiant. Une entrée venue
    # d'un import Excel n'a que lui, `code` étant recalculé.
    table = [e for e in (_section(cfg).get(u'table') or [])
             if e.get(u'code_ouvrage') or e.get(u'code')]
    return sorted(table, key=lambda e: code_ouvrage(e, fmt=fmt))


def code_ouvrage(code_ou_entree, cfg=None, fmt=None):
    """
    Code Ouvrage normalisé : complété par des zéros jusqu'à sa longueur, qui
    est FIXE — la somme des tranches de tous les niveaux déclarés.

    Accepte une entrée de table (dont la clé `code_ouvrage` est alors utilisée
    directement) ou un code brut. Taper « 5111 » donne donc « 511100 » avec six
    niveaux d'un chiffre.
    """
    if isinstance(code_ou_entree, dict):
        if code_ou_entree.get(u'code_ouvrage'):
            return code_ou_entree[u'code_ouvrage']
        code = code_ou_entree.get(u'code', u'')
    else:
        code = code_ou_entree or u''
    if not code:
        return u''
    fmt = fmt or get_format(cfg)
    return code + u'0' * max(0, fmt[u'longueur_code_ouvrage'] - len(code))


def decouper_code(code, cfg=None, fmt=None):
    """Découpe un Code Ouvrage en une tranche par niveau, ou None s'il est
    vide."""
    fmt = fmt or get_format(cfg)
    plein = code_ouvrage(code, fmt=fmt)
    if not plein:
        return None
    tranches, pos = [], 0
    for largeur in fmt[u'digits_par_niveau']:
        tranches.append(plein[pos:pos + largeur])
        pos += largeur
    return tranches


def get_niveau(code_ou_entree, cfg=None, fmt=None):
    """
    Niveau d'une ligne : rang de la dernière tranche non nulle, 1 au minimum.

    Avec six niveaux d'un chiffre : 500000 → 1, 510000 → 2, 511000 → 3,
    511100 → 4, 511110 → 5, 511111 → 6.

    Accepte une entrée de table (dont la clé `niveau` est alors utilisée
    directement) ou un code brut.
    """
    if isinstance(code_ou_entree, dict) and code_ou_entree.get(u'niveau'):
        return _entier(code_ou_entree[u'niveau'], 1)
    fmt = fmt or get_format(cfg)
    plein = code_ouvrage(code_ou_entree, fmt=fmt)
    if not plein:
        return 1
    niveau, pos = 1, 0
    for rang, largeur in enumerate(fmt[u'digits_par_niveau']):
        if plein[pos:pos + largeur].strip(u'0'):
            niveau = rang + 1
        pos += largeur
    return niveau


def est_ouvrage(code_ou_entree, cfg=None, fmt=None):
    """
    True si la ligne classe un OUVRAGE et non une discipline : son niveau
    dépasse `niveaux_code`.
    """
    fmt = fmt or get_format(cfg)
    return get_niveau(code_ou_entree, fmt=fmt) > fmt[u'niveaux_code']


def code_parent(code, cfg=None, fmt=None):
    """
    Code Ouvrage du parent, ou None au niveau 1 ou pour un code vide.

    Remet à zéro la tranche du niveau courant, ce qui remonte d'un cran sans
    toucher au reste de la branche.
    """
    fmt = fmt or get_format(cfg)
    plein = code_ouvrage(code, fmt=fmt)
    if not plein:
        return None
    niveau = get_niveau(plein, fmt=fmt)
    if niveau <= 1:
        return None
    out, pos = [], 0
    for rang, largeur in enumerate(fmt[u'digits_par_niveau']):
        tranche = plein[pos:pos + largeur]
        pos += largeur
        out.append(tranche if rang < niveau - 1 else u'0' * largeur)
    return u''.join(out)


def prefixe_code(code, cfg=None, fmt=None):
    """
    Partie SIGNIFIANTE du code : ce dont tout descendant hérite, c.-à-d. les
    tranches jusqu'au niveau de la ligne. Les zéros de queue ne distinguent
    rien.
    """
    fmt = fmt or get_format(cfg)
    plein = code_ouvrage(code, fmt=fmt)
    if not plein:
        return u''
    niveau = get_niveau(plein, fmt=fmt)
    return plein[:sum(fmt[u'digits_par_niveau'][:niveau])]


def get_par_code(code, cfg=None):
    """
    Entrée correspondant à ce code, ou None.

    Le code est normalisé en Code Ouvrage avant la recherche : '511', '511000' et
    une entrée complète désignent donc la même ligne. Indispensable, le `code`
    brut n'étant pas unique.
    """
    fmt = get_format(cfg)
    cible = code_ouvrage(code, fmt=fmt)
    if not cible:
        return None
    for entree in get_table(cfg):
        if code_ouvrage(entree, fmt=fmt) == cible:
            return entree
    return None


# Le nom dit ce que fait la fonction ; get_par_code normalise de toute façon.
get_par_code_ouvrage = get_par_code


def resoudre_abrev(gabarit, ancetres, abrev_discipline=None):
    """
    Remplace les jetons d'un gabarit : `{supN}` par le N-ième élément
    d'`ancetres`, `{dis}` par l'abréviation de discipline de la même ligne.

    `ancetres` liste les abréviations RÉSOLUES des ancêtres de la ligne, DU
    PLUS PROCHE AU PLUS LOINTAIN. Un rang qui la dépasse s'efface — c'est la
    fenêtre des paramètres qui le signale, pas ce module. `abrev_discipline` ne
    sert qu'aux gabarits d'abréviation d'OUVRAGE ; laissé à None, `{dis}`
    s'efface aussi.

    Quelques lignes de code, mais c'est LA règle du référentiel : la garder ici
    évite que chaque script consommateur réinvente le remplacement — et se
    trompe de jeton.
    """
    ancetres = ancetres or []

    def _un(m):
        rang = int(m.group(1))
        return ancetres[rang - 1] if 1 <= rang <= len(ancetres) else u''

    sortie = RE_SUP.sub(_un, canoniser_jetons(gabarit))
    return sortie.replace(JETON_DIS, abrev_discipline or u'')


def calculer_abrev(code, cfg=None):
    """
    Recompose l'abréviation de DISCIPLINE résolue en remontant la branche.

    À n'utiliser que sur une table dont `abrev_resolue` manque ou est suspecte
    (config.json édité à la main) : en temps normal, lire la clé stockée, que
    la fenêtre des paramètres tient à jour.
    """
    entree = get_par_code(code, cfg)
    if entree is None:
        return u''
    chaine = []            # ancêtres du plus proche au plus lointain
    resolue = u''
    for maillon in get_ancetres(code, cfg) + [entree]:
        resolue = resoudre_abrev(maillon.get(u'abrev_discipline'), chaine)
        chaine = [resolue] + chaine
    return resolue


def calculer_abrev_ouvrage(code, cfg=None):
    """
    Recompose l'abréviation d'OUVRAGE résolue en remontant la branche.

    Chaque maillon résout `{supN}` sur la chaîne de ses ancêtres et `{dis}` sur
    SA PROPRE abréviation de discipline. Les deux chaînes avancent donc de
    front, et celle de discipline est REJOUÉE ici plutôt que lue dans
    `abrev_resolue` : cette fonction sert justement aux tables dont les clés
    calculées manquent ou sont suspectes.
    """
    entree = get_par_code(code, cfg)
    if entree is None:
        return u''
    chaine_d, chaine_o = [], []
    res_disc, res_ouv = u'', u''
    for maillon in get_ancetres(code, cfg) + [entree]:
        res_disc = resoudre_abrev(maillon.get(u'abrev_discipline'), chaine_d)
        res_ouv = resoudre_abrev(maillon.get(u'abrev_ouvrage'), chaine_o,
                                 res_disc)
        chaine_d = [res_disc] + chaine_d
        chaine_o = [res_ouv] + chaine_o
    return res_ouv


def abrev(entree):
    """Abréviation de discipline RÉSOLUE d'une ligne — celle qu'on affiche."""
    if not isinstance(entree, dict):
        return u''
    return (entree.get(u'abrev_resolue') or u'').strip()


def abrev_ouvrage(entree):
    """
    Abréviation d'ouvrage RÉSOLUE d'une ligne.

    Renseignée sur TOUTES les lignes : au niveau 1 elle vaut l'abréviation de
    discipline (gabarit `{dis}` imposé), et se propage vers le bas tant qu'on
    ne la remplace pas.
    """
    if not isinstance(entree, dict):
        return u''
    return (entree.get(u'abrev_ouvrage_resolue') or u'').strip()


def etiquette(entree, cfg=None, fmt=None):
    """
    Désignation PROPRE à la ligne : l'abréviation de discipline résolue pour
    une discipline, l'abréviation d'ouvrage résolue pour un ouvrage.

    Le niveau doit être testé, et non le contenu des cellules : une ligne
    d'ouvrage porte aussi une abréviation de discipline — celle de sa branche —
    et se replier sur « l'une ou l'autre » rendrait la discipline au lieu du nom
    de l'ouvrage.
    """
    if not isinstance(entree, dict):
        return u''
    if est_ouvrage(entree, cfg, fmt):
        return abrev_ouvrage(entree)
    return abrev(entree)


def get_tous_par_abrev(abreviation_discipline, cfg=None, sous=None,
                       disciplines_seules=False):
    """
    Lignes dont l'abréviation de discipline RÉSOLUE vaut celle-ci — une LISTE.

    Toutes les lignes en portent une : une branche entière répond donc à
    « CLIM-PLS », disciplines et ouvrages mêlés. `disciplines_seules` écarte les
    lignes d'ouvrage quand on cherche la sous-discipline elle-même ; `sous`
    restreint la recherche à la descendance d'un code.

    Comparaison insensible à la casse : le référentiel peut être réglé sans
    forçage des majuscules, alors qu'une abréviation lue dans un nom de fichier
    ou un paramètre Revit arrive dans la casse d'origine.
    """
    cible = (abreviation_discipline or u'').strip().upper()
    if not cible:
        return []
    fmt = get_format(cfg)
    candidats = get_descendants(sous, cfg) if sous else get_table(cfg)
    return [e for e in candidats
            if abrev(e).upper() == cible
            and not (disciplines_seules and est_ouvrage(e, fmt=fmt))]


def get_par_abrev(abreviation_discipline, cfg=None, sous=None,
                  disciplines_seules=False):
    """
    PREMIÈRE ligne portant cette abréviation de discipline, ou None.

    Une abréviation désignant toute une branche, la première ligne est celle du
    plus haut niveau — la table étant triée par Code Ouvrage. Préférer
    `get_tous_par_abrev` dès qu'il faut la branche entière.
    """
    resultats = get_tous_par_abrev(abreviation_discipline, cfg, sous,
                                   disciplines_seules)
    return resultats[0] if resultats else None


def get_par_abreviation(abreviation, cfg=None, sous=None,
                        ouvrages_seuls=False):
    """
    Lignes dont l'abréviation d'OUVRAGE résolue vaut celle-ci — une LISTE, pas
    une entrée : rien n'impose l'unicité.

    Toutes les lignes en portent une, donc une branche entière peut répondre.
    `ouvrages_seuls` écarte les lignes de discipline ; `sous` restreint la
    recherche à la descendance d'un code.
    """
    cible = (abreviation or u'').strip().upper()
    if not cible:
        return []
    fmt = get_format(cfg)
    candidats = get_descendants(sous, cfg) if sous else get_table(cfg)
    return [e for e in candidats
            if abrev_ouvrage(e).upper() == cible
            and not (ouvrages_seuls and not est_ouvrage(e, fmt=fmt))]


def get_parent(code, cfg=None):
    """Entrée du parent direct, ou None au niveau 1."""
    parent = code_parent(code, cfg)
    return get_par_code(parent, cfg) if parent else None


def get_ancetres(code, cfg=None):
    """
    Branche au-dessus d'une ligne, du niveau 1 jusqu'au parent direct.

    Sert à afficher un chemin complet, ou à résoudre les jetons `{supN}` quand la ligne
    vient d'ailleurs que de la table.
    """
    fmt = get_format(cfg)
    par_code = dict((code_ouvrage(e, fmt=fmt), e) for e in get_table(cfg))
    out, courant = [], code
    while True:
        parent = code_parent(courant, fmt=fmt)
        if not parent:
            break
        entree = par_code.get(parent)
        if entree is not None:
            out.append(entree)
        courant = parent
    out.reverse()
    return out


def get_disciplines(cfg=None):
    """Les seules lignes de niveau 1, triées par Code Ouvrage."""
    fmt = get_format(cfg)
    return [e for e in get_table(cfg) if get_niveau(e, fmt=fmt) == 1]


def get_disciplines_et_sous(cfg=None):
    """
    [(code_ouvrage, libelle)] de toute ligne DISCIPLINE (niveau <=
    niveaux_code), dédoublonnée et triée par Code Ouvrage — les combinaisons
    Discipline / Sous-discipline distinctes du référentiel, prêtes pour un
    filtre ou une liste à cocher.

    Une branche peut affiner sa sous-discipline à plusieurs niveaux
    successifs (ex. niveau 2 « PLOMBERIE SANITAIRE », niveau 3
    « PLOMBERIE ») : chacun produit sa propre entrée, `libelle()` les
    distingue déjà. Les lignes d'OUVRAGE (niveau > niveaux_code) sont
    exclues : elles n'introduisent aucune discipline nouvelle, seulement des
    ouvrages sous la dernière sous-discipline de leur branche.
    """
    fmt = get_format(cfg)
    vus = set()
    out = []
    for e in get_table(cfg):
        if get_niveau(e, fmt=fmt) > fmt[u'niveaux_code']:
            continue
        code = code_ouvrage(e, fmt=fmt)
        if not code or code in vus:
            continue
        vus.add(code)
        out.append((code, libelle(e)))
    return out


def get_enfants(code, cfg=None):
    """Enfants DIRECTS d'une ligne (un seul niveau en dessous)."""
    fmt = get_format(cfg)
    niveau = get_niveau(code, fmt=fmt)
    return [e for e in get_descendants(code, cfg)
            if get_niveau(e, fmt=fmt) == niveau + 1]


def get_descendants(code, cfg=None, niveau_max=0):
    """
    Toute la descendance d'une ligne, à tous les niveaux, triée par Code Ouvrage.

    Une ligne n'est pas sa propre descendante. `niveau_max` borne la
    profondeur — passer `niveaux_code` pour rester dans les disciplines et
    écarter les classements d'ouvrage.
    """
    fmt = get_format(cfg)
    tete = prefixe_code(code, fmt=fmt)
    if not tete:
        return []
    niveau = get_niveau(code, fmt=fmt)
    reference = code_ouvrage(code, fmt=fmt)
    out = []
    for entree in get_table(cfg):
        autre = code_ouvrage(entree, fmt=fmt)
        if autre == reference or not autre.startswith(tete):
            continue
        niveau_autre = get_niveau(entree, fmt=fmt)
        if niveau_autre > niveau and (not niveau_max
                                      or niveau_autre <= niveau_max):
            out.append(entree)
    return out


def get_sous_disciplines(code, cfg=None):
    """
    Descendance limitée aux niveaux du Code : les sous-disciplines, sans les
    classements d'ouvrage.
    """
    return get_descendants(code, cfg,
                           niveau_max=get_format(cfg)[u'niveaux_code'])


def get_ouvrages(code, cfg=None):
    """Descendance située AU-DELA des niveaux du Code : les ouvrages."""
    fmt = get_format(cfg)
    return [e for e in get_descendants(code, cfg)
            if get_niveau(e, fmt=fmt) > fmt[u'niveaux_code']]


def libelle(entree, separateur=u' — '):
    """
    Libellé d'affichage d'une entrée, pour une liste déroulante ou un journal.

    Une discipline donne « G CLIMATIQUE », une ligne plus bas
    « G CLIMATIQUE — PLOMBERIE » : le nom de la discipline est repris, faute de
    quoi une liste mêlant plusieurs disciplines serait ambiguë.
    """
    if not isinstance(entree, dict):
        return u''
    nom = (entree.get(u'discipline') or u'').strip()
    sous = (entree.get(u'sous_discipline') or u'').strip()
    if nom and sous:
        return nom + separateur + sous
    return nom or sous


def chemin(code, cfg=None, separateur=u' > '):
    """
    Chemin lisible du niveau 1 jusqu'à la ligne, libellé par libellé.

    « G CLIMATIQUE > PLOMBERIE SANITAIRE > PLOMBERIE ». Plus parlant que
    `libelle` dès que la hiérarchie dépasse deux niveaux.
    """
    entree = get_par_code(code, cfg)
    if entree is None:
        return u''
    morceaux = []
    for ancetre in get_ancetres(code, cfg) + [entree]:
        morceaux.append((ancetre.get(u'sous_discipline') or u'').strip()
                        or (ancetre.get(u'discipline') or u'').strip())
    return separateur.join(m for m in morceaux if m)


def choix_menu(cfg=None, avec_code=True, niveau_max=0):
    """
    Table prête pour une liste déroulante : [(texte, entree), ...].

    `avec_code` préfixe le texte du Code Ouvrage, qui est l'identifiant stable — le
    conserver visible évite d'avoir à rouvrir les paramètres pour savoir quelle
    ligne se cache derrière un libellé. `niveau_max` limite la profondeur
    proposée (0 = tous les niveaux) ; passer `niveaux_code` pour n'offrir que
    les disciplines.
    """
    fmt = get_format(cfg)
    choix = []
    for entree in get_table(cfg):
        niveau = get_niveau(entree, fmt=fmt)
        if niveau_max and niveau > niveau_max:
            continue
        texte = libelle(entree)
        resolue = abrev(entree)
        if resolue:
            texte = u'{} ({})'.format(texte, resolue)
        if avec_code:
            texte = u'{}  {}'.format(code_ouvrage(entree, fmt=fmt), texte)
        choix.append((texte, entree))
    return choix
