# FOOTBALL ANALYST IA

Aplicativo web de **análise estatística de futebol**.  
Ele coleta dados reais de partidas, calcula frequências e um modelo de Poisson, e mostra mercados com porcentagens **estimadas**.  
Não afirma resultado, não chama nada de “aposta certa” e **não inventa estatística**.

## O que o app faz

- Pesquisa mandante, visitante, campeonato e data
- Lista jogos do dia nas principais ligas
- Analisa últimos jogos (até 10 quando a fonte entrega)
- Casa / fora, gols, Over/Under, BTTS, clean sheets
- Confrontos diretos encontrados no histórico coletado
- Escalação, desfalques e notícias **quando a fonte publica**
- xG / finalizações / posse **somente se vierem no JSON da partida**
- Mercados: 1X2, gols, ambas, dupla chance, placares
- Nível de confiança 🟢 ALTA / 🟡 MÉDIA / 🔴 BAIXA com base na amostra
- Análise em lote + filtros + ordenação
- Botão **Atualizar dados** (limpa cache de 3 minutos)

Se faltar dado, a interface mostra:

> Dados insuficientes para esta análise.

## Como executar

Requisito: **Python 3.10+**. Não precisa instalar pacote nenhum.

```bash
cd football-analyst-ia
python3 server.py
```

Abra no celular ou no computador:

```
http://127.0.0.1:8080
```

Outra porta:

```bash
PORT=3000 python3 server.py
```

Acesse pelo IP da máquina na mesma rede para usar no celular.

## Fonte de dados (padrão)

O provedor padrão é a **API JSON pública da ESPN** em `site.web.api.espn.com` (sem chave). A agenda do dia também usa o FotMob nas ligas principais:

- placar / jogos do dia
- times e pesquisa
- calendário da temporada
- últimos 5 jogos no sumário da partida
- escalação e formação quando publicadas
- odds de mercado quando existirem
- notícias
- lesões quando o endpoint devolver lista

Isso **não é um feed oficial da liga**. Pode haver atraso, cobertura incompleta em divisões menores e ausência de xG na maior parte dos jogos.

## API-Football (opcional)

Para enriquecer desfalques e o histórico de 10 jogos:

1. Crie conta em [dashboard.api-football.com](https://dashboard.api-football.com)
2. Copie a chave do plano gratuito (100 req/dia)
3. Crie o arquivo `.env` na pasta do projeto:

```bash
cp .env.example .env
```

4. Preencha:

```
API_FOOTBALL_KEY=cole_a_chave_aqui
API_FOOTBALL_BASE=https://v3.football.api-sports.io
API_FOOTBALL_HEADER=x-apisports-key
```

Se a chave for da **RapidAPI**:

```
API_FOOTBALL_KEY=cole_a_chave_aqui
API_FOOTBALL_BASE=https://api-football-v1.p.rapidapi.com/v3
API_FOOTBALL_HEADER=x-rapidapi-key
```

Reinicie o `server.py`. O backend passa a misturar ESPN + API-Football.  
IDs das duas fontes são diferentes: a ponte é feita **pelo nome do time**.

## Como as porcentagens são calculadas

1. Só entram jogos com **placar conhecido**
2. Frequências amostrais (Over 1.5, 2.5, BTTS, etc.)
3. Taxas de ataque/defesa da temporada (casa/fora quando existirem)
4. Modelo de Poisson independente para placares 0–6
5. Mistura Poisson (55%) + frequência (45%)
6. Confiança sobe com tamanho da amostra, tabela, H2H, escalação; cai se a amostra é curta ou os indicadores se contradizem

As barras **não são odds justas de casa de apostas** e **não são previsão certa**.

## API interna

| Método | Rota | Uso |
| --- | --- | --- |
| GET | `/api/health` | status e se a chave API-Football está carregada |
| GET | `/api/leagues` | ligas mapeadas |
| GET | `/api/search?q=Arsenal` | busca time |
| GET | `/api/fixtures?date=2026-09-19&league=eng.1` | jogos do dia |
| POST | `/api/analyze` | corpo JSON `{home, away, league, date, event_id, refresh}` |
| POST | `/api/analyze-many` | corpo `{games:[{home,away,league,date}]}` |

## Estrutura

```
football-analyst-ia/
  server.py          servidor HTTP
  service.py         orquestra fontes + análise
  analysis.py        motor estatístico
  espn_client.py     cliente ESPN
  apifootball.py     cliente opcional API-Football
  templates/index.html
  static/app.css
  static/app.js
  .env.example
```

## Aviso

O FOOTBALL ANALYST IA é uma ferramenta de leitura estatística.  
Use os números para formar a própria opinião. Não há garantia de resultado.
