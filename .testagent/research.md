# Implementation acceptance inventory

Baseline: immutable published 06.07, factory image 06.05, existing Python/Unicorn checks, no Android app source previously in this repository. No automatic flash, no change to the published 06.07 assets.

Targets: freestanding C firmware core and native adapters; verified binary builder; native Android TV app; offline tests and reproducible artifacts. Existing raw decompilation is analysis input, not complete vendor source. Native heap is approximately 4.4 KiB, no arbitrary unused RAM proven.

The test generator / find-untested-sources / test-gap-analysis / assertion-quality tools are not available in this session. Research, pairing, planning and review are performed inline by the implementation owners. Current representative suites: reproduction/verify_front_hid_candidate.py and verify_diagnostic_candidate.py, existing audit_behavior.py outside the repo. Host C/Java tests exercise pure logic; ARM emulation must exercise compiled code and actual native adapter paths before any candidate is described as ready to flash.

## User requirements (verbatim)

- "Remplacer la zone partagée par une **file de 16 événements copiés**, distinguant clavier, face avant, orientation et événements spéciaux. Préserver l’ordre « orientation puis touche »."
- "Faire passer les rapports clavier et consumer par **un seul gestionnaire de transmission**. Supprimer leur chemin d’envoi direct et retirer un rapport de la file seulement après son acceptation par la pile."
- "Normaliser les résultats en trois états internes : accepté, échec temporaire, indisponible. Corriger les caches des deux faces pour qu’une tentative échouée ne soit pas considérée comme transmise."
- "Prévoir **16 rapports en attente**, avec protection séparée des relâchements clavier et consumer. En saturation, refuser les nouvelles pressions plutôt qu’écraser un relâchement. Si nécessaire, bloquer temporairement le rapport concerné jusqu’à l’acceptation d’un état neutre."
- "Limiter à **deux secondes** la conservation des appuis non envoyés. Réessayer les erreurs temporaires après 20, 50, 100 puis 200 ms, pendant deux secondes maximum. Ensuite, reprendre sur un événement utile, sans boucle permanente."
- "Associer les éléments à une génération de connexion : purger les commandes anciennes lors d’une déconnexion ou d’un changement de téléviseur associé. Après réactivation des notifications, envoyer d’abord l’état neutre. Ne jamais rejouer une commande Alimentation déjà acceptée."
- "Conserver les morceaux de trames UART dans un accumulateur borné de six octets et retrouver l’en-tête `FE` après désynchronisation. Garder les paramètres UART actuels et ne pas inventer de contrôle de checksum."
- "Refuser les index avant **45 à 254**, tout en conservant les touches 0 à 44, le relâchement 255 et les événements spéciaux."
- "Vérifier les quatre touches de couleur sur le matériel ; corriger le doublon bleu/jaune uniquement après confirmation."
- "Comparer le rapport clavier complet lors de la détection des doublons."
- "Protéger brièvement les copies et index avec les primitives critiques natives. Aucun appel Bluetooth, allocation ou attente dans ces sections."
- "Réserver les nouveaux états par **une allocation native unique plafonnée à 640 octets**, sans choisir arbitrairement une adresse RAM. Exiger au moins **768 octets de tas libre après allocation**"
- "Si l’allocation échoue, conserver les chemins 06.07 et signaler que les améliorations ne sont pas actives."
- "Les circuits audio, OTA et bootloader restent ceux d’origine."
- "Ajouter un écran d’apprentissage des boutons, des profils locaux et des actions : ouvrir une application, sélectionner HDMI 1/2, afficher Couchy ou ouvrir les réglages."
- "Proposer un profil pour ton installation : **Rouge → Movix, Vert → HDMI 1, Jaune → HDMI 2, Bleu → réglages de la télécommande**. Ce profil reste désactivé jusqu’à son choix dans l’appli."
- "Autoriser les appuis courts, longs et doubles sur les boutons personnalisés : seuil long de **600 ms**, double appui de **300 ms**, double appui désactivé par défaut."
- "Préserver par défaut navigation, volume, Alimentation, voix et appairage. L’appli ne doit ajouter aucun délai aux touches ordinaires."
- "Intercepter de façon cohérente les événements d’appui et de relâchement avec un service d’accessibilité activé par l’utilisateur ; les touches non configurées passent normalement."
- "Stocker les profils sur la TV, avec export/import JSON versionné et remise à zéro. Aucun contenu d’écran collecté, aucun compte ni serveur nécessaire."
- "Le firmware reste utilisable sans cette appli."
- "Relever les temps de connexion, d’activité UART et de veille avant/après."
- "Préserver initialement puissance radio et temporisations d’origine."
- "Sans mesure électrique, présenter les résultats comme des indicateurs d’activité, pas comme un gain d’autonomie démontré."
- "La construction vérifie le hash d’origine, les octets attendus, les plages modifiées, la taille, les vecteurs et le CRC."
- "Chaque livraison comprend le binaire, l’archive USB, les SHA-256, un changelog anglais court et les résultats de validation."
- "**Aucun flash automatique.** Le seuil batterie natif de 50 % est conservé."

Hardware-dependent acceptance remains explicitly pending until a separate physical test: colors, all physical keys, 30-minute/overnight wake, real heap/stack margins, current consumption and software recovery. Do not replace these with mocked success.
