# Assistant de code GENI

L'outil agrège différents scripts :
- geni.py :
    - enregistre la question de l'utilisateur saisie dans le terminal
    - récupère les fichiers, complets ou partiels
    - récupère la structure du projet générée par Aider
    - récupère les messages les plus pertinents enregistrés en base vectorielle
    - concatène le tout pour en faire un prompt et le transmettre à glog.py

- glog.py : 
  - construit un résumé avec un modèle flash
  - lit et écrit dans une base vectorielle, puis appelle ask.py

- ask.py : 
- interroge une IA avec le prompt

## Appel de l'outil

L'utilitaire fonctionne en appelant cette simple commande : `geni`.
Il suffit alors de suivre les instructions du prompt :
- saisir la question
- ajouter un fichier en contexte
- éventuellement, sélectionner les lignes à ajouter en contexte
- si pas de nouveau fichier à ajouter, taper simplement ENTER ou TAB

Le script fait alors les actions suivantes :
- récupère le prompt system, faisant office de mémoire normative
- demande à un modèle Gemini Flash (plus rapide) de faire un résumé tenant compte de la discussion et l'ajoute en contexte
- ajoute le fichier `resume_contexte.yaml` en contexte
- demande à Aider de générer la structure du projet
- récupère en base vectorielle les 3 messages les plus pertinents pour les ajouter au contexte
- genère un prompt sur cette base et le soumet à Gemini (avec un modèle performant si possible)
- enregistre la réponse dans un fichier `dernier_plan.md`
- ajoute cette dernière réponse à l'historique du fichier `historique_global.md`

## TODO :

Revoir le script ask.py :
- est-il encore utile d'ajouter un fichier prompt_system ?
- l'outil appelle un modèle flash, mais c'est un autre modèle qui répond (configuré dans geni ou glog)

Revoir l'articulation des scripts :
- vérifier si la lecture en base et la récupération du résumé se fait bien une seule fois et non dans geni + glog

Créer une boucle agentique qui pourra utiiser des outils au besoin.

Les actions possibles :
- Lister le contenu d'un répertoire
- Lire fichier
- Créer fichier
- Ecrire fichier
- Rechercher
- Exécuter commandes bash
- Fetch du contenu sur le web
- indexer (en utilisant le repo-mùap d'Aider ?)


