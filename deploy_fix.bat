@echo off
echo Adicionando arquivos criticos...
git add core/dashboard_state_manager.py
git add api/routes/dashboard_routes.py
git add .gitignore
git add global_state.json
git add product_lifecycle_state.json
git add radar_evaluations.json
git add finance_state.json
git add commercial_state.json

echo Realizando commit...
git commit -m "feat: FASE C6.12 e C6.13 - Sync definitivo de persistencia e codigo limpo do state manager"

echo Enviando para a producao (Railway)...
git push

echo.
echo Deploy enviado! Acompanhe o build no painel do Railway.
