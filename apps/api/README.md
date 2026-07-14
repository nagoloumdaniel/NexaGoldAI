# NexaGold API

Backend NestJS de NexaGold.

## Role

- expose les endpoints dashboard lus par le frontend ;
- lit PostgreSQL via Prisma ;
- proxifie certaines donnees live du moteur Python (`ENGINE_URL`) ;
- envoie les rapports Telegram quotidiens, hebdomadaires et mensuels ;
- expose `/health` pour verifier l'API et la base.

## Commandes utiles

```bash
npm run start:dev
npm run build
npx tsc --noEmit
npx eslint "{src,apps,libs,test}/**/*.ts"
npm test -- --runInBand
```

## Etat phase 0

Les tests presents sont encore ceux du starter NestJS et ne couvrent pas le metier.
Les routes sensibles ne sont pas encore protegees par une authentification.
Le commentaire dans `src/reports/reports.controller.ts` reste donc valide :
le module JWT/auth est une prochaine etape prioritaire avant toute exposition
reseau.
