# HANDOFF — Canal Chaos Coast (GTA 6 clips). Ler primeiro.

Esta é a passagem de bastão da conversa anterior (sessão na nuvem "GTA6") para uma sessão rodando **no computador do usuário (Windows)**. Leia tudo antes de agir.

## 1. Quem é o usuário e como trabalhar com ele
- Thiago, mora em **Dublin (Irlanda)**, fuso GMT. Fala **português (Brasil)**. Responda em português, direto e curto, sem enrolar.
- Prioridade dele: **máxima automação**. "Tudo que você puder fazer, faça você; me diga só o que depende de mim." Não peça o que dá para resolver sozinho.
- Ele costuma estar na rua, usando o celular. Agora está no computador.
- Ele usa o ChatGPT para guiar tarefas manuais (ex.: credencial Google).
- Este projeto (canal de GTA 6) **não tem relação com o software "Autonomous System"** do repositório onde os arquivos foram parar por acidente. Plano: mover para pasta/repositório próprio do Chaos Coast. Não mexer no resto do Autonomous System.

## 2. Objetivo
Criar um canal de **cortes de GTA 6 em inglês** (lançado em 19/11/2026), postando todos os dias em **YouTube (Shorts), TikTok e Instagram Reels**, com o máximo de automação, e monetizar por anúncios, programas das plataformas e **afiliados/merch**.

## 3. Decisões já tomadas
- **Idioma: inglês** (pesquisa: inglês tem ~2,3x mais horas assistidas que espanhol em streams de GTA 6; CPM de EUA/Reino Unido bem acima da América Latina. Dados de fontes de blog; o RPM real vem do YouTube Studio).
- **Nome do canal: CHAOS COAST.** Tagline: "The wildest GTA 6 moments · daily". (Handles a tentar, nesta ordem: `@chaoscoast`, `@chaoscoastclips`, `@chaoscoast.gta6`, `@chaoscoast6`.)
- **Formato:** cortes verticais 9:16 de gameplay/lives de streamers, com **gancho em texto** nos primeiros 4 s ("No way they put this in the game", "The physics are insane"...), legenda de 3 palavras, e crédito.
- **Fonte dos vídeos:** gameplay/lives de streamers (IShowSpeed, Kai Cenat, TheBurntPeanut sugeridos). O usuário decidiu **não pedir permissão** e considera que streamers querem divulgação. **Mantenha SEMPRE o crédito ("Source: <streamer>") na tela e o link da origem na descrição de todo corte.** O usuário concordou explicitamente com isso. A assistente da conversa anterior deixou claro que o crédito não substitui permissão e que há risco de strike/remoção; se um streamer pedir remoção, apagar o corte. Não afirme que os streamers autorizaram.
- **Textos de TikTok/Instagram:** só escrever quando houver o corte real (tema, gancho), nunca em abstrato.
- **Videos de referência** (5 mp4 do usuário, assistidos por frames): fluxo Claude Code que pesquisa tendências, cria identidade, roteiros, edita e publica; clipper de lives que lê o pico do chat; plugin "sistema de cortes"; skill `/watch` (repositório `bradautomates/claude-video`); agentes por função. Eram vídeos de divulgação, sem código.

## 4. O que já existe (na branch `claude/instalacao-video-gxm1vw` do repositório `thiagocassabsound-blip/autonomous-system-v2`)
| Caminho | O que é | Estado |
|---|---|---|
| `docs/gta6-channel-plan.md` | Plano do canal e pipeline de 8 etapas, restrições reais | pronto |
| `docs/accounts-setup.md` | Ordem de criação das contas, bios, automação por plataforma | pronto |
| `docs/HANDOFF.md` | este arquivo | — |
| `brand/` | avatar.png (800x800), banner.png (2560x1440, título na área segura), .svg, `build.py` + `render.js` para regerar, fontes Anton e Montserrat ExtraBold Italic em `brand/fonts/`, `brand.md` | pronto |
| `clipper/clipper.py` | `find`: acha picos de áudio + mudança de cena e gera `candidates.json` + 3 frames por candidato. `render`: gera corte 9:16 com fundo desfocado, gancho em Anton, crédito, legenda (se houver .srt) e `manifest.json` | **testado só num vídeo sintético** |
| `clipper/captions.py` | legendas em inglês (faster-whisper) por corte | **NÃO testado** (modelo não baixava na nuvem) |
| `clipper/fetch.py` | usa `yt-dlp` para listar vídeos novos dos canais em `channels.txt`, baixar e rodar o `find` | **NÃO testado** (YouTube bloqueado na nuvem) |
| `clipper/upload.py` | envia para o YouTube com a API v3 (título, descrição com Credit + Original, privado por padrão ou `--publish-at`) | **só sintaxe verificada** |
| `clipper/channels.txt` | `@IShowSpeed`, `@KaiCenat`, `@TheBurntPeanut` (links não confirmados) | rascunho |
| `clipper/README.md` | comandos passo a passo | pronto |

**Zero cortes reais foram feitos até agora.** Nenhum vídeo de gameplay foi baixado. Não houve contato com nenhum streamer. Nenhuma conta foi criada ainda.

## 5. Como o fluxo funciona
1. `python clipper/fetch.py` (ou baixar manualmente com `yt-dlp`) → vídeo em `videos/`.
2. `clipper.py find` → `work/<id>/candidates.json` + `frames/`.
3. **A IA olha os frames** e escreve `hook` e `title` de cada candidato (hook em inglês, curto, espanto/curiosidade). Só os candidatos com `hook` preenchido são renderizados.
4. (Opcional) `captions.py` → `.srt`.
5. `clipper.py render` → `work/<id>/clips/clipNN.mp4` + `manifest.json`.
6. `upload.py` → YouTube (privado até a auditoria da API; ou agendado com `--publish-at`).
7. TikTok/Instagram: por enquanto postar pelo app, com texto escrito pela IA para cada corte.

## 6. Estado das contas e dependências (o usuário está fazendo)
- [ ] Gmail do canal (ex.: chaoscoastclips@gmail.com): **a fazer**
- [ ] Canal YouTube Chaos Coast, TikTok e Instagram (conta profissional): **a fazer**
- [ ] Google Cloud: projeto + YouTube Data API v3 + consentimento OAuth (usuário de teste = Gmail do canal) + credencial "App para computador" → `client_secret.json` em `clipper/`: **a fazer**
- [ ] ffmpeg, yt-dlp, numpy no Windows: o usuário "acha que tem ffmpeg"; **verificar** (`ffmpeg -version`, `yt-dlp --version`, `python -c "import numpy"`).
- Gemini API key (opcional, para `/watch` de links do YouTube): chave grátis em aistudio.google.com/apikey. Não necessária se o computador baixar do YouTube.
- Limites: cota padrão da API do YouTube ≈ 6 uploads/dia; uploads só ficam públicos após auditoria da API; em modo de teste o login expira em ~7 dias.

## 7. Próximos passos (ordem)
1. Clonar/usar esta branch na pasta local; instalar o que faltar (winget/pip); conferir `ffmpeg`, `yt-dlp`, `numpy`, `faster-whisper`.
2. Validar `channels.txt` (os links abrem?) e **rodar `fetch.py`**; corrigir erros (fetch/captions/upload ainda não foram provados).
3. Criar os primeiros cortes reais com ganchos; mostrar ao usuário.
4. Quando o `client_secret.json` existir: testar `upload.py` com vídeo privado.
5. Escrever, para cada corte pronto, os textos de YouTube, TikTok e Instagram (adaptados por plataforma, com crédito e link).
6. Montar página de link-in-bio e lista de afiliados (ver abaixo).
7. Mover o projeto para pasta/repositório próprio (fora do Autonomous System).
8. Depois: análise semanal (retenção, CTR, RPM por país) e agendamento diário.

## 8. Monetização (pesquisa)
- **Afiliados (sem meta de público):** hardware de PS5 (DualSense, headsets, capture cards), GTA 6/PS Plus, merch próprio com a marca Chaos Coast (impressão sob demanda, **sem logos da Rockstar**). Programas citados: Razer, Logitech, Turtle Beach (5%, Impact), Astro (5%), GameStop (1,6–7%), Green Man Gaming/Fanatical (sem taxa publicada), Amazon.ie/UK. Taxas vêm de blogs e divergem; confirmar em cada painel. **Declarar afiliado (#ad)** em cada post. Shorts: link no comentário fixado e na bio; TikTok/IG: link na bio.
- **YouTube Partner:** 1.000 inscritos + 4.000 h ou 10 mi de views de Shorts/90 dias; faixa menor (500 inscritos, sem anúncios). Blog diz que a meta sobe em 02/2027 (confirmar no site oficial).
- **TikTok Creator Rewards:** 10.000 seguidores + 100.000 views/30 dias; **só vídeos > 1 min rendem** (cortes de 25 s não contam).
- **Risco principal:** cortes de terceiros podem ser recusados na monetização por "conteúdo reutilizado". Dar valor próprio (gancho, comentário, edição). Não contar com anúncios no início; afiliados e merch primeiro.
- Políticas: Rockstar pode remover cutscenes isoladas/spoilers; houve strikes em reaction streams. Evitar compilações de cutscenes e spoilers de história.

## 9. Pesquisa de canais/streamers (primeiros dias, Streams Charts)
YouTube dia 1: Windah Basudara, PAULINHO O LOKO, LOUD Coringa, TGG. Horas assistidas: IShowSpeed, DjMaRiiO. Combinado: alanzoka, TheBurntPeanut, IlloJuan. IShowSpeed e Kai Cenat anunciaram playthrough no lançamento. Números mudam de hora em hora.

## 10. Armadilhas conhecidas
- A nuvem bloqueia YouTube/Hugging Face; no computador do usuário isso não existe.
- `drawtext`/`subtitles` do ffmpeg quebram com caminho absoluto no Windows (letra de drive): o `render` já usa nomes relativos e roda dentro de `clips/`; mantenha.
- Legenda: `force_style` usa escala 384x288; MarginV alto joga a legenda para fora da tela (ficou em 60).
- Não colocar e-mail ou dados pessoais do usuário em serviços externos.
- Agendado: lembrete (já disparado) sobre ativar o YouTube na skill `watch`. Skill instalada em `.claude/skills/watch`.

---
## 11. ADENDO (lacunas encontradas depois do primeiro handoff)

**Estilo dos cortes, nas palavras do usuário (siga à risca):**
- "Cortes rápidos que viralizem." Não é preciso grande ideia de roteiro: o trabalho é achar os pontos mais interessantes do gameplay e fazer o corte.
- Em cada corte, escrever **poucas palavras na tela como gancho**, ligadas ao que acontece no vídeo, e só depois mostrar a cena. Exemplos do usuário (inspiração, não copiar): "a física do GTA está incrível", "os gráficos estão incríveis", "o cara tá tirando onda", "não acredito que fizeram isso no jogo".
- Priorizar momentos **engraçados e inesperados** (física, bugs, reações, caos). Evitar cutscenes isoladas e spoilers de história.

**Controle pelo celular:** o usuário quer falar com ESTA sessão pelo celular com o computador ligado e trabalhando. Para isso, ligar o interruptor **Remote Control** no painel da direita desta sessão e testar pelo app Claude (aba Code). O computador precisa ficar ligado, sem suspender, com o Claude Desktop aberto. Se isso ainda não estiver feito, **peça ao usuário que ligue e confirme**.

**Achado do chat local:** o filtro de título "GTA 6/GTA VI" só passou vídeos do TheBurntPeanut. IShowSpeed e Kai Cenat não tiveram nenhum nos últimos 15 vídeos. Lives de GTA 6 costumam estar na aba **/streams** (ou ter título sem "GTA 6"). Teste também `https://www.youtube.com/@IShowSpeed/streams` e `@KaiCenat/streams`, e considere acrescentar outros canais em inglês que apareçam na pesquisa. Nenhum vídeo que não seja gameplay deve passar (ex.: vlogs).

**Pendências de código:** commitar e dar push na mudança do filtro do `fetch.py`. Melhorar a quebra de linha do gancho no render (linhas muito separadas). Testar `captions.py` (primeira execução baixa o modelo Whisper).

**Privacidade:** não colocar o e-mail pessoal do usuário no histórico git nem em serviços externos (o chat local já usa identidade genérica "Chaos Coast").

**Organização:** o conteúdo está dentro do repositório `autonomous-system-v2` só por acidente; o plano é mover para repositório/pasta própria do Chaos Coast. O chat antigo (nuvem) será arquivado; este é o chat oficial do projeto.
