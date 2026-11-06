# ViceTuga Bot — página de notícias GTA 6 100% automática

3 vídeos por dia, sozinho: encontra notícias de GTA 6 → escreve guião em PT-PT → voz → vídeo vertical com legendas → publica no Instagram, TikTok e YouTube Shorts via Metricool.

Custo: **€0**. O GitHub faz o vídeo e põe-no numa fila (`queue.json`); uma tarefa agendada do Claude lê a fila e publica pelo Metricool (MCP, funciona no plano Starter).

---

## Passo 1 — Chaves grátis (5 min)

| O quê | Onde | Nome do secret |
|---|---|---|
| **Gemini** (guiões) | https://aistudio.google.com/apikey → *Create API key* | `GEMINI_API_KEY` |
| **Pexels** (vídeos de fundo) | https://www.pexels.com/api/ → conta grátis → *Your API key* | `PEXELS_API_KEY` |

(As contas IG/TikTok/YouTube/Facebook e a marca "Gta 6" no Metricool já estão feitas.)

## Passo 2 — Pôr o código no GitHub (5 min)

1. https://github.com → **New repository** → nome `vicetuga-bot` → **Public** → Create.
   (Público = minutos grátis ilimitados e o Metricool consegue descarregar o vídeo. As chaves ficam secretas na mesma.)
2. **uploading an existing file** → arrasta **todo o conteúdo** da pasta `gta6bot` (descompactada) → *Commit changes*.
   ⚠️ No Mac a pasta `.github` está escondida: no Finder carrega **Cmd + Shift + .** para a veres e arrasta-a também.
3. Confirma que no repositório aparece `.github/workflows/gta6bot.yml`.

## Passo 3 — Colar as chaves (2 min)

Repositório → **Settings → Secrets and variables → Actions → New repository secret** → cria `GEMINI_API_KEY` e `PEXELS_API_KEY`.

Depois **Settings → Actions → General → Workflow permissions → Read and write permissions → Save**.

## Passo 4 — Testar (sem publicar)

1. Separador **Actions** → se pedir, carrega em *I understand… enable workflows*.
2. **ViceTuga Bot → Run workflow** → deixa ✅ *dry_run* → Run.
3. Quando ficar verde (~3 min), abre a execução → em baixo, **Artifacts → video-teste** → descarrega e vê o vídeo.

Se gostares: **Run workflow** outra vez com *dry_run* desligado → o vídeo vai para a fila (`queue.json`) e a tarefa agendada do Claude agenda-o no Metricool.

**A partir daí corre sozinho às 9h17, 13h17 e 19h17.** Não tens de fazer mais nada.

---

## Personalizar (opcional)

Settings → Secrets and variables → Actions → separador **Variables**:

| Variável | Para quê | Exemplo |
|---|---|---|
| `VOICE` | Voz masculina | `pt-PT-DuarteNeural` |
| `BRAND` | Texto em baixo no vídeo | `@VICETUGA • GTA 6 EM PORTUGUÊS` |
| `NETWORKS` | Onde publicar | `instagram,tiktok,youtube,facebook` |

- **Música de fundo:** põe ficheiros `.mp3` sem direitos (ex.: YouTube Audio Library) na pasta `assets/music/`. Escolhe uma ao acaso por vídeo.
- **Mais/menos vídeos por dia:** muda a linha `cron` em `.github/workflows/gta6bot.yml` (ex.: `"17 8,11,14,17,20 * * *"` = 5/dia).

## Como funciona / regras de segurança

- Só publica se houver **notícia nova** dos últimos 2 dias; nunca repete a mesma história (`posted.json`).
- O guião só usa factos da notícia; rumores são ditos como rumores; se nada presta, não publica.
- Sem imagens da Rockstar (evita strikes) — usa vídeos de Miami/neon/carros do Pexels.
- Os vídeos são marcados como conteúdo IA no Instagram e TikTok (voz sintética), como as plataformas exigem.

## Se der erro

Actions → clica na execução vermelha → passo *Gerar e publicar vídeo* → copia as últimas linhas e manda-me.
