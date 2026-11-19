# Plano: canal de cortes de GTA 6 (inglês), produção e postagem automática

Base: 5 vídeos de referência (frames + textos na tela; áudio não transcrito) + pesquisa de idioma (inglês primeiro).

## 1. O que os vídeos mostram (e o que não mostram)

| Vídeo | Ideia aproveitável |
|---|---|
| 1 (BR, "Claude Code monta o canal") | Fluxo em etapas: pesquisar o que o público busca (autocomplete do YouTube: "gta 6 mapa / carros / segredos") → identidade do canal (nome, logo, capa) → 10 roteiros com gancho → voz, imagens, animação e edição → título, thumbnail e descrição → upload. Formatos de título: Mapa inteiro, Top 5 segredos, Carro mais rápido, Easter eggs, Ilha escondida, Missões secretas, Truques do 1º dia, O que ninguém viu, Grana rápida, Final secreto? |
| 2 (EN, "Claude Clipper") | Clipper de lives: lê o chat ao vivo, detecta pico de mensagens, corta na hora, aplica legenda + facecam, publica em minutos. Só cortar streamers que permitem clipes, dando crédito. Vantagem de quem posta primeiro. |
| 3 (BR, "Sistema de cortes") | Plugin/skill de cortes: assiste a uma live, gera 5 cortes, cada um com título e legenda embutidos (ex.: "TIROTEIO INSANO", "OLHA ISSO"). |
| 4 (BR, skill /watch) | `/watch <link>` baixa o vídeo, extrai frames e transcrição para o Claude "assistir". Repositório `bradautomates/claude-video`. Opções: Gemini (chave grátis), local (yt-dlp + ffmpeg). |
| 5 (BR, 11 habilidades) | Divisão de funções por agente: roteiro, legenda/post, perfil, planejamento, análise de viralidade (destrincha vídeo em padrões e roteiros). |

Limite: são vídeos de divulgação. Mostram a ideia, não o código dos sistemas. A estrutura abaixo é nossa, montada a partir deles.

## 2. Restrições reais (decidem o desenho)

1. **Fonte do vídeo.** Não dá para só baixar vídeos de terceiros e repostar. Duas fontes viáveis:
   - **Footage próprio de GTA 6** (gravação sua do jogo, com comentário/edição próprios). Mais seguro.
   - **Cortes de lives só com permissão por escrito** do streamer, com crédito.
   Verificar a política de conteúdo de fãs da Take-Two/Rockstar antes de monetizar.
2. **Política do YouTube de conteúdo reutilizado/inautêntico.** Postagem em massa de cortes sem edição ou comentário original pode perder a monetização do canal. Cada vídeo precisa de valor próprio (narração, edição, contexto).
3. **API de upload.** O projeto OAuth precisa de auditoria da API do YouTube; sem ela, os uploads ficam privados. A cota padrão (~10.000 unidades/dia, upload ~1.600) permite cerca de 6 envios por dia.
4. **Este ambiente de nuvem.** O YouTube bloqueia download daqui. Baixar e subir vídeos exige rodar no seu computador ou em um servidor com IP aceito. Aqui eu faço roteiro, edição de arquivos que você enviar, e organização.
5. **Sem edição real sem material.** Eu edito arquivos de vídeo recebidos (ffmpeg); não gero gameplay.

## 3. Arquitetura proposta (pipeline diário)

```
[1 Pesquisa] → [2 Roteiro] → [3 Material] → [4 Edição] → [5 Metadados] → [6 Revisão] → [7 Upload] → [8 Análise]
```

1. **Pesquisa (diária):** autocomplete e tendências do YouTube em inglês ("gta 6 ..."), temas em alta, concorrência. Saída: fila priorizada de 10 ideias.
2. **Roteiro:** gancho nos 3 primeiros segundos, estrutura curta (Shorts 20–45 s e vídeos de 6–10 min), tom em inglês nativo.
3. **Material:** clipes do seu footage ou de streamers autorizados (registro de permissões num arquivo `permissions.csv`).
4. **Edição (ffmpeg):** corte, vertical 9:16, legenda palavra por palavra em inglês, título na tela, música livre de direitos, normalização de áudio.
5. **Metadados:** título (até 60 caracteres, com palavra-chave), descrição, tags, thumbnail, capítulos; crédito ao streamer quando houver.
6. **Revisão (checklist automático + sua aprovação no começo):** direitos, legenda sem erro, sem spoiler proibido, sem trechos de terceiros sem permissão. No início, você aprova cada vídeo; depois, só amostras.
7. **Upload:** YouTube Data API v3 com agendamento (ex.: 2 Shorts + 1 vídeo longo por dia).
8. **Análise (semanal):** retenção, CTR, RPM por país no YouTube Studio; o que funcionou vira regra para o passo 1.

## 4. Estrutura de pastas sugerida

```
gta6-channel/
  research/    ideias.json, tendencias.json
  scripts/     roteiros em .md
  raw/         material bruto (+ permissions.csv)
  edits/       vídeos prontos
  meta/        título, descrição, tags, thumbnail
  queue/       agendamento (data, status, link)
  analytics/   resultados semanais
```

## 5. Fases

- **Fase 0 (você, ~1 h):** criar o canal; escolher nome em inglês; decidir a fonte do vídeo; criar projeto Google Cloud e pedir auditoria da API.
- **Fase 1 (eu):** montar pastas, geradores de roteiro/metadados e a edição com ffmpeg; testar com os vídeos que você mandar.
- **Fase 2:** 1 vídeo por dia, com aprovação manual; medir 2 semanas.
- **Fase 3:** automatizar upload agendado e relatórios semanais.

## 6. O que preciso de você

1. De onde virá o vídeo: seu footage, streamers autorizados ou ambos?
2. Nome do canal (inglês) e se já existe.
3. Onde rodar o pipeline (seu computador é o mais simples).
4. Mais vídeos de referência, se quiser complementar.
