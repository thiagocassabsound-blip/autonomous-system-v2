# Plano de Implementação - FASE C8.2 — MELHORIAS E POPULAÇÃO DO DASHBOARD

## Objetivo
Atender ao feedback detalhado do usuário para tornar o Dashboard 100% funcional e informativo, tanto no modo MOCK quanto no modo REAL, corrigindo discrepâncias de horário e comportamentos inesperados.

## Alterações Propostas

### 1. População Completa do Modo MOCK
#### [MODIFY] [dashboard_state_manager.py](file:///c:/Users/Cliente/Downloads/fastoolhub.com/autonomous-system-v2/core/dashboard_state_manager.py)
- Expandir o método `_load_mock_data` para incluir dados para as seções que atualmente mostram "Aguardando conexão":
  - **Analytics**: Conversão, Retenção e Receita fictícios.
  - **Financeiro**: Saldo Stripe, Gastos Google Ads e Limiar de Contenção.
  - **Decisões de IA**: Log de decisões recentes (ex: "Ajuste de lance no Ads", "Nova copy aprovada").

### 2. Sincronização de Horário (Relógio)
#### [MODIFY] [dashboard_routes.py](file:///api/routes/dashboard_routes.py)
- Ajustar a exibição do `last_updated` para refletir o fuso horário local do usuário (UTC-3 - Brasília), removendo a confusão causada pelo horário UTC puro.

### 3. Melhorias na Interface e Lógica
#### [MODIFY] [dashboard.html](file:///c:/Users/Cliente/Downloads/fastoolhub.com/autonomous-system-v2/templates/dashboard.html)
- **Modo Autônomo**: Tornar o dropdown interativo (mesmo que apenas visualmente no momento) para remover a sensação de "travado".
- **Overview**: Adicionar um pequeno widget ou linha informativa sobre o "Limiar Financeiro" diretamente no resumo, para que o usuário saiba o limite atual sem ir em configurações.
- **Diferenciação Radar vs Overview**: Ajustar os títulos para que fique claro que a "Visão Geral" é um resumo executivo e a aba "Radar" é o log detalhado.

### 4. Investigação de "Heartbeat" do Radar
- Analisar os logs recentes e o código do `orchestrator.py` para entender por que o radar pode estar rodando em ciclos curtos e sempre resultando em "Não" (provavelmente falta de saldo ou filtros muito restritos).

## Plano de Verificação

### Verificação Manual
1.  **Modo MOCK**: Validar se todos os blocos (Financeiro, Analytics, etc.) agora mostram dados em vez de placeholders.
2.  **Relógio**: Confirmar que o horário "Última Atualização" condiz com o horário local do Brasil.
3.  **Dropdown**: Verificar se o seletor de modo autônomo responde ao clique.
4.  **Overview**: Localizar o novo indicador de Limiar Financeiro.

---
## PLAN_VERSION_HISTORY
- **CREATED_AT**: 2026-03-10
- **STATUS**: COMPLETED (Retrospective Registry)
