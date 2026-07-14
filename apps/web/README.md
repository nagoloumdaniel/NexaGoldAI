# NexaGold Web

Dashboard Next.js de NexaGold.

## Role

- affiche le tableau de bord de trading IA ;
- lit l'API NestJS via `NEXT_PUBLIC_API_URL` ;
- montre les decisions IA, trades, analytics, modeles et etat systeme ;
- reste en lecture seule dans l'etat actuel.

## Commandes utiles

```bash
npm run dev -- -p 3002
npm run build
npm run lint
npm run typecheck
```

`npm run typecheck` utilise `tsconfig.typecheck.json` pour verifier les sources
et les types de build Next sans dependre du cache de developpement `.next/dev`.
Avec Next 16, `next dev` ecrit dans `.next/dev`; ce dossier peut contenir des
artefacts temporaires pendant qu'un serveur dev tourne.
