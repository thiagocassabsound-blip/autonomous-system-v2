"""
infra/landing/ — Bloco 30: Landing Engine

Subsistema de conversão autônomo governado.
Subordinado integralmente ao Orchestrator.

Pré-condições externas obrigatórias (já aplicadas):
  1. BI-01 corrigido em radar/recommendation_engine.py
  2. _SVC_HANDLER registrado para expansion_recommendation_event

Constitutional guarantees:
  - Nunca altera state.json diretamente
  - Nunca chama StateMachine.transition()
  - Nunca instancia ProductLifeEngine diretamente
  - Nunca chama GuardianEngine
  - Usa receive_event(), não emit_event(), para eventos governados
  - Respeita contenção financeira
  - Nunca ignora STRICT_MODE
"""
