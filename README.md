# DIGIPRINT Tarification

Application Streamlit de calcul du **prix de revient** (hors marge) des articles d'une imprimerie numérique, à partir de la base articles Excel (nomenclatures `IMPUT1…50`, gammes `MACH1…20`). Trois pages : **Tarification**, **Paramètres**, **Historique**.

Les données (paramètres, historique, versions importées de la base articles) sont enregistrées dans **Neon PostgreSQL** lorsque l'application est hébergée, ou dans un fichier **SQLite local** sans aucune configuration. Même fonctionnement que VigieFlotte : secret `[neon] url`, repli SQLite.

## Lancer en local

```bash
python -m venv .venv
.venv\Scripts\activate            # Windows  (macOS/Linux : source .venv/bin/activate)
pip install -r requirements.txt
streamlit run app.py
```

Sans secret, la base `data/digiprint.sqlite` est créée au premier lancement, avec les paramètres par défaut. Pour travailler directement sur Neon depuis le poste, copiez `.streamlit/secrets.toml.example` en `.streamlit/secrets.toml` et renseignez l'adresse.


## Utilisation

**Tarification.** Désignation puis nature, par listes à recherche (saisie partielle, sans tenir compte des majuscules ; seules les valeurs de la base sont acceptées). La fiche article et sa nomenclature se chargent automatiquement. Les feuilles de papier, coupes et rainages sont estimés et affichés dans le champ (« Auto : 25 ») ; un nombre saisi remplace l'estimation. Emballage (type, coût unitaire modifiable, nombre de cartons), livraison (distance aller, facturée aller-retour), frais ponctuels. Le prix se recalcule à chaque saisie, avec le détail ligne par ligne ; **Enregistrer** l'ajoute à l'historique, **Fiche Excel** télécharge la fiche avec formules.

**Paramètres.** Papiers (prix du paquet, prix fixé par format, rainage selon le papier), matières et consommables, machines (taux horaires), opérations (ajout libre), emballages, transports, frais additionnels, réglages (arrondi, levée du massicot, grammage de rainage, formats, procédés), base articles (contrôle, consultation, remplacement du classeur, versions), sauvegardes (30 dernières versions restaurables, export/import JSON, valeurs par défaut). Les modifications forment un brouillon enregistré d'un clic ; un enregistrement concurrent d'un autre utilisateur est détecté.

**Historique.** Recherche, période, détail, rechargement dans la tarification, fiche Excel, suppression, export Excel de la liste (une colonne par poste).

## Modèle de calcul

Chaque ligne vaut `quantité × prix unitaire` ; le total est la somme des lignes.

| Poste | Calcul |
|---|---|
| Papier | feuilles A0 de la nomenclature × feuilles par A0 du format de tirage du procédé (SRA3 : 4, offset A1 : 2), arrondi supérieur ; × prix par feuille (prix du paquet ÷ feuilles A0 du paquet ÷ feuilles par A0, ou prix fixé pour le format) |
| Matières, encres et consommables | quantité de nomenclature × quantité commandée × prix d'achat ÷ facteur de conversion |
| Impression, finition | secondes de gamme × quantité ÷ 3 600 × taux horaire |
| Découpe | coupes × coût par coupe. Estimation : levées (feuilles ÷ hauteur de levée) × 2 × (lignes + colonnes de poses). Le temps massicot de la gamme n'est alors pas compté |
| Rainage | rainages par exemplaire × exemplaires × coût du rainage selon le papier le plus épais. Estimation : volets − 1, pli, couverture (4 en dos carré collé, 1 en piqûre), aucun sous le grammage de rainage |
| Emballage | cartons × coût unitaire |
| Transport | distance aller × 2 × coût au km (+ prise en charge éventuelle) |
| Autres frais | frais ponctuels saisis ; frais paramétrés fixes, par exemplaire ou en % du coût de production / du coût avant frais |

Les articles vendus « au lot de 1 000 » se saisissent en exemplaires : la nomenclature est appliquée au nombre de lots. La base inclut dans chaque lot le calage et les plaques (convention du classeur) : une commande de plusieurs lots les compte à chaque lot.



## Architecture

```
app.py                  point d'entrée, navigation
digiprint/              cœur métier, sans Streamlit
  config.py             chemins, constantes, variables d'environnement
  catalogue.py          lecture et contrôle du classeur
  models.py             structures (article, ligne de coût, saisie, résultat)
  defaults.py           valeurs par défaut des paramètres
  parametres.py         schéma, validation, lecture/écriture versionnée
  estimation.py         estimations (poses, coupes, rainages)
  moteur.py             calcul du prix de revient
  stockage.py           Neon PostgreSQL / SQLite (SQLAlchemy), fichiers importés
  historique.py         historique des calculs
  export.py             fiches et historique Excel à formules
  migration.py          copie SQLite local → Neon
ui/                     interface Streamlit (thème, composants, pages)
data/                   base articles livrée (et SQLite local)
static/                 police Schibsted Grotesk (OFL), logo
tests/                  tests pytest (moteur, stockage, interface)
```

