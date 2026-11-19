# Clipper — GTA 6 cortes (rodar no seu computador)

Requisitos: Python 3.10+, ffmpeg, `pip install numpy yt-dlp` (upload: `google-api-python-client google-auth-oauthlib`).

1. Baixar o vídeo de gameplay:
   `yt-dlp -f "bv*[height<=1080]+ba/b" -o "videos/%(id)s.%(ext)s" LINK`
2. Achar momentos:
   `python3 clipper.py find videos/ID.mp4 --credit "Nome do streamer" --source-url LINK --n 8`
3. Mandar para o Claude `work/ID/candidates.json` + a pasta `frames/` (ele escreve os `hook` e `title`).
4. Gerar os cortes: `python3 clipper.py render work/ID/candidates.json videos/ID.mp4`
5. Postar (privado por padrão): `python3 upload.py work/ID/clips [--publish-at AAAA-MM-DDTHH:MM:SSZ]`

Todo corte leva "Source: <streamer>" na tela e Credit + link na descrição. Se um streamer pedir remoção, apague o corte.
Upload: a API do YouTube só publica em público depois da auditoria do projeto; antes disso os vídeos ficam privados.
