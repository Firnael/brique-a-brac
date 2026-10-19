# 🧱 Brique-à-Brac

Reconstituer des sets LEGO à partir d'une grosse caisse de pièces en vrac, triées par couleur.

L'app récupère l'inventaire d'un set (Rebrickable) et sort une **liste de collecte par couleur** : on ouvre le sac « gris foncé », on voit toutes les pièces gris foncé à trouver pour ses sets, avec photo, et on les range dans le sac du bon set.

## Fonctionnalités

- **Sets** : ajout par numéro, ou à partir de la photo d'une pièce (Brickognize → sets qui contiennent cette pièce, affinés indice par indice).
- **Priorité** : l'ordre de la liste décide quel set reçoit une pièce commune à plusieurs sets.
- **Collecte** par couleur puis par catégorie, pour tous les sets en cours ou un seul (« Monter ce set »). Alerte sur les couleurs faciles à confondre (Dark Gray / Dark Bluish Gray…).
- **Identifier une pièce** : photo → nom, référence, et si un de ses sets en a besoin.
- **Notice** : PDF officiel LEGO, mis en cache par le serveur.
- **Commande groupée** : une seule wanted list BrickLink avec les manquants de plusieurs sets.

## Lancer

Il faut une clé API Rebrickable (gratuite : rebrickable.com → Settings → API).

```sh
git clone git@github.com:Firnael/brique-a-brac.git && cd brique-a-brac
echo "REBRICKABLE_API_KEY=xxxx" > .env
```

**Avec Docker** (recommandé, ex. sur Proxmox) :

```sh
docker compose up -d                 # http://<ip-de-la-machine>:8642
git pull && docker compose up -d --build   # mise à jour
```

Le conteneur redémarre tout seul (reboot, crash). Autre port : `PORT=8080 docker compose up -d`.

**Sans Docker** : Python 3.12+, aucune dépendance.

```sh
python3 server.py                    # http://<ip-de-la-machine>:8642
```

## Données

Tout est dans le dossier `data/` à côté de `docker-compose.yml`, même avec Docker (ignoré par git) :

- `state.json` : sets, priorité, pièces collectées, sets terminés, indices.
- `backups/` : copie de `state.json` avant la première modif de chaque jour, 14 jours gardés.
- `cache/` : réponses Rebrickable, pages de notices et PDF. Peut être supprimé sans risque.

Sauvegarder = copier `data/state.json`. Changer de machine = copier `data/` dans le nouveau clone avant `docker compose up -d`.

## Sources

- [Rebrickable API](https://rebrickable.com/api/v3/docs/) : inventaires, couleurs, catégories, sets par pièce.
- [Brickognize API](https://api.brickognize.com/docs) : reconnaissance de pièce sur photo (sans clé).
- lego.com : notices de montage.
