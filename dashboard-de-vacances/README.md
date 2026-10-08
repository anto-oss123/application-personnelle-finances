# Dashboard de vacances

Outil personnel pour saisir les dépenses en euros et dollars canadiens, suivre le budget quotidien en $CAD, comparer les voyages, simuler un prochain séjour et télécharger deux rapports PDF.

## Publication gratuite

L’application utilise un service web **Render Free** et une base **Neon Free**. Aucun disque payant n’est nécessaire. Les données PostgreSQL restent séparées du serveur éphémère. Les secrets `DATABASE_URL`, `CAP_FRANCE_PASSWORD` et `CAP_FRANCE_SESSION_SECRET` restent uniquement dans la configuration privée du service, jamais dans le dépôt ou le HTML.

Le serveur refuse de démarrer sans connexion privée et base durable lorsque les contrôles d’hébergement sont activés. Les mises à jour utilisent une comparaison atomique de version ; un conflit n’écrase pas les données. La synchronisation interroge la version toutes les trois secondes pendant l’utilisation, sans transférer la sauvegarde complète lorsqu’elle n’a pas changé.

Le service gratuit Render peut prendre environ une minute à se réveiller après une période d’inactivité. Les offres gratuites ont des quotas : aucun abonnement payant ou changement de formule n’est autorisé dans ce projet.

## Lancement local

`python3 server.py` puis ouvrir `http://127.0.0.1:8765`. Sans configuration d’hébergement, les données restent enregistrées dans le navigateur. `index.html` fonctionne aussi directement et sans connexion Internet.

Pour le mode synchronisé, installer `requirements.txt` et configurer les secrets sur le serveur. La variable `RENDER_EXTERNAL_URL` fournit automatiquement l’origine HTTPS de confiance.

L’application existante à la racine du dépôt reste distincte. Tout le Dashboard de vacances est contenu dans ce sous-dossier. Les données de voyages ne sont pas publiées dans GitHub.

## Mise à jour de l’interface

- Le budget total est facultatif (`null` signifie non défini, zéro reste un plafond réel).
- Chaque voyage et chaque opération indiquent une devise locale ; le champ historique `eur` conserve le montant local pour préserver les anciennes sauvegardes.
- L’état JSON version 2 est compatible avec les anciens voyages en EUR. Les prévisions non modifiées de l’ancien modèle sont reconnues ; les prévisions personnalisées sont conservées.
- Les nouveaux brouillons de prévision sont vides. Les postes absents sont signalés comme non renseignés et la projection est partielle.
- Frankfurter fournit les taux publics locaux vers CAD via un proxy authentifié. Le serveur met ces références en cache pendant six heures. Le mode automatique actualise le taux à l’ouverture et pendant l’utilisation, sans modifier les taux mémorisés des opérations existantes.
- L’apparence suit `prefers-color-scheme` par défaut ; le choix manuel est une préférence locale à chaque appareil.
- Les dépenses sont présentées sous forme de fiches sur mobile. La navigation tient compte de la zone de sécurité ; elle se masque pendant les formulaires et le toast ne la recouvre pas.
- Un favicon SVG, des icônes PNG et un manifeste d’application permettent l’ajout à l’écran d’accueil.

## Mise à jour : descriptions, dépenses en attente et rappels

Les noms précédemment utilisés sont proposés dans la saisie, avec un avertissement si le nom normalisé, la date et le montant correspondent à une autre dépense du même voyage. Une seconde validation permet de conserver deux achats réellement distincts.

Le graphique distingue les paiements nets (dont remboursements) et les dépenses engagées/prévues ; un sélecteur natif affiche les montants exacts de chaque jour. Les barres non nulles ont une hauteur minimale pour rester lisibles à côté des grosses dépenses.

L’aperçu regroupe les dépenses à mettre à jour. Une date de rappel facultative est conservée avec chaque dépense et affichée au moment prévu. Le bouton de paiement ouvre la saisie pour vérifier le montant bancaire avant l’enregistrement.

Le rappel peut être exporté au format Calendrier (.ics, avec alerte) sur Mac puis ajouté à un calendrier iCloud. Le partage du lien peut servir à créer un rappel dans l’app Apple, selon les options proposées par l’appareil. Le site n’envoie pas de notifications en arrière-plan ; les rappels Apple ne sont pas synchronisés avec les modifications du Dashboard et doivent être terminés ou modifiés séparément.

Cette mise à jour ne réinitialise aucune donnée et ne modifie pas la structure de la base. Les dépenses sans rappel restent compatibles. Les sauvegardes de vérification et les identifiants restent privés, hors du dépôt.
