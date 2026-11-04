# Bet Advisor — painel

Painel de estudo do mercado de apostas (6 ligas + competições europeias). Página pública em GitHub Pages (pasta `docs/`).

- `engine/build.py` — vai buscar odds (OddsPapi: Pinnacle + betano.pt; The Odds API: casas internacionais) e resultados (football-data.co.uk), calcula a hipótese real e o ganho esperado, e escreve `docs/data/panel.json` e `docs/data/tracker.json`.
- `.github/workflows/painel.yml` — corre o motor à segunda, quinta e sábado (06:17 UTC) e guarda os dados.
- Segredos necessários: `ODDS_API_KEY`, `ODDSPAPI_KEY`. Só planos gratuitos.

Não é aconselhamento financeiro.
