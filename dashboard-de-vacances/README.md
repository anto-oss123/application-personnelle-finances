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
