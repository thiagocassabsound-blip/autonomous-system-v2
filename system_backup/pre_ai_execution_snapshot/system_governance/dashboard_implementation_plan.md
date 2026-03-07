🎛️ PLANO OFICIAL DE IMPLEMENTAÇÃO DO DASHBOARD (COM CAMADAS)


CAMADA GLOBAL — UI BASE (ESTILO NEUTRO)
UI/UX VISUAL DESIGN: manter dark theme + cards com borda glow + grid responsivo + espaçamento compacto + leitura de alta densidade informacional.

DATA REFRESH SYSTEM: implementar botão Refresh Data para atualizar métricas manualmente além de atualização automática periódica.
MOCK MODE TOGGLE: permitir alternar entre dados simulados e dados reais para testes.

REAL DATA MODE: habilitar coleta de dados reais das integrações Stripe/OpenAI/Ads.
ERROR HANDLING UI: mostrar mensagens amigáveis quando APIs externas falharem.
HISTORY STORAGE: armazenar histórico de métricas por produto para alimentar gráficos analíticos.

⸻

ESTRUTURA FINAL DO DASHBOARD
DASHBOARD SCROLL STRUCTURE: organizar dashboard verticalmente na ordem Header → System Status → Radar Panel → Draft Pipeline → Product Portfolio → Product Analytics → Finance & Resources → Alerts → AI Decisions → System Telemetry.

______

CAMADA 1 — VERDE (CORE SYSTEM CONTROL)
HEADER STRUCTURE: implementar barra superior fixa contendo logo/símbolo do sistema + nome Autonomous System + indicador de status geral do sistema (HEALTHY/DEGRADED/ERROR) + botão Launch Radar/New Product + botão Refresh Data + indicador usuário logado + botão logout + timestamp last system update + indicador modo do sistema (MOCK/REAL) + indicador ambiente (LOCAL/STAGING/PROD).

HEADER DEGRADED ERROR INDICATOR: mostrar mudança visual clara no header quando o sistema estiver DEGRADED ou ERROR (ex.: glow vermelho ou amarelo) para alerta imediato do operador.

LOGIN PAGE IMPROVEMENT: campo password com toggle show/hide (ícone olho) + campo username + botão sign in + validação credenciais + mensagem erro login.

USER SESSION CONTROL: implementar logout seguro + timeout sessão + exibir usuário logado no header.

_______

CAMADA 2 — AZUL (SYSTEM OVERVIEW & STATUS)
SYSTEM STATUS PANEL: manter painel atual porém expandido contendo System Health + Radar Cycles + LLM Budget + API Calls + tempo uptime do sistema + última execução do radar + número total de produtos gerados + número de produtos ativos + número de produtos pausados + número de produtos mortos + consumo total de tokens LLM + custo operacional estimado.

⸻

CAMADA 3 — ROXO (RADAR ENGINE)
RADAR PIPELINE TABLE: manter tabela Latest Opportunities porém expandir colunas para Product ID + Cluster ID + Keyword/Market Pain + Final Score + ICE Score + Demand Score + Competition Score + Trend Growth % + Opportunity Confidence + Emitted Status + Timestamp Detection + Botão Create Product + Botão Discard Opportunity.

RADAR CONTROL PANEL: adicionar painel com botão Launch Radar + campo descrição da dor de mercado + botão Auto Discover + indicador radar running/stopped + indicador radar queue + contador oportunidades detectadas + contador oportunidades rejeitadas + contador oportunidades aprovadas.

⸻

CAMADA 4 — LARANJA (PRODUCT CREATION PIPELINE)
PRODUCT DRAFT PIPELINE: manter tabela Latest Product Drafts porém expandir colunas para Product ID + Product Name + Market Pain + Radar Cluster ID + State + Version + Created At + Days Since Creation + Botão Build Product + Botão Delete Draft + Botão Approve Draft.

⸻

CAMADA 5 — AMARELO (PRODUCT PORTFOLIO CORE)
PRODUCT PORTFOLIO GRID: implementar grid de cards de produtos exibindo todos produtos ativos ou pausados contendo status label (ACTIVE/BETA/BUILDING/OPTIMIZING/PAUSED/DEPLOY_FAILED/MAINTENANCE) + nome do produto + ciclo atual + versão atual + idade do produto em dias + indicador qualidade (Excellent/Good/Poor) + indicador estágio lifecycle + barra de progresso inferior representando estágio.

PRODUCT METRICS BLOCK: dentro de cada card exibir ROI (%) + Conversion Rate (%) + Revenue 24h ($) + Revenue Total ($) + Traffic 24h + CAC estimado + LTV estimado + margem estimada.

PRODUCT ACTION BUTTONS: dentro de cada card adicionar botões Execute/Trigger + Pause/Resume toggle + Analytics + Settings + Delete Product + botão Reevaluation Strategy.

PRODUCT PAUSE CONFIRMATION MODAL: implementar modal confirmação contendo mensagem Confirm Pausing + descrição “This will stop all optimization cycles and traffic for this product. History will be preserved.” + botões Confirm/Cancel.

⸻

CAMADA 6 — VERMELHO (PRODUCT ANALYTICS & LIFECYCLE)
PRODUCT ANALYTICS PANEL: abrir ao clicar Analytics contendo gráficos Revenue Over Time (24h/7d/30d) + Conversion Trend + Traffic Trend + Ads Spend Trend + ROI Trend + gráfico funil conversão + gráfico CAC vs LTV + indicador churn se aplicável.

PRODUCT LIFECYCLE VISUAL: exibir pipeline visual com estágios Idea → Draft → Build → Beta → Optimize → Scale → Maintenance → Kill + highlight estágio atual do produto + indicador tempo em cada estágio.

PRODUCT AGE INDICATOR: exibir idade do produto em dias diretamente no card para avaliação rápida da maturidade do produto.

PRODUCT VERSION TRACKING: manter versão semântica do produto (v1.0 v1.1 v2.0 etc) exibida no card e registrada no histórico.

PRODUCT QUALITY TAG: exibir tag qualidade (Excellent/Good/Average/Poor) baseada em ROI + conversão + estabilidade operacional.

PRODUCT TRAFFIC METRICS: mostrar visitas ou leads gerados pelo produto.

⸻

CAMADA 7 — DOURADO/MARROM (FINANCE & RESOURCE ENGINE)
FINANCE & RESOURCES PANEL: implementar painel financeiro exibindo Stripe Balance atual + Revenue Today + Revenue This Month + Revenue Total + OpenAI Credits Remaining + OpenAI Daily Usage + OpenAI Monthly Forecast + Google Ads Budget Remaining + Ads Spend Today + Ads Spend Monthly Forecast.

RESOURCE FORECAST ENGINE: calcular automaticamente previsão de consumo mensal para OpenAI tokens e Google Ads baseado na média diária atual.

AUTO FUNDING SYSTEM: implementar lógica mostrando transferência automática de receita Stripe para abastecimento OpenAI e Google Ads + mostrar Next Funding Date + Funding Amount + Funding Source.

AUTO FUNDING ALERTS: alertar quando saldo OpenAI ou Ads estiver abaixo do limiar mínimo e mostrar mensagem Auto funding scheduled in X days.

FINANCIAL SAFETY INDICATORS: mostrar indicadores se custos estão ultrapassando receita ou se margem está abaixo de limite saudável.

STRIPE INTEGRATION STATUS: mostrar estado da integração Stripe e último webhook recebido.

OPENAI API STATUS: mostrar status da API OpenAI + limite de tokens + latência média + custo acumulado do dia.

ADS PLATFORM STATUS: mostrar estado da integração Google Ads + campanhas ativas + custo por campanha + conversões.

⸻

CAMADA 8 — CINZA ESCURO (SYSTEM INTELLIGENCE & TELEMETRY)
AI DECISION LOG PANEL: implementar painel exibindo decisões automáticas tomadas pela IA como Pause Product + Increase Budget + Change Pricing + Switch Strategy + Kill Product + Start Optimization Cycle + mostrar timestamp + motivo + impacto esperado.

ALERTS PANEL: implementar painel de alertas contendo alertas operacionais como Conversion Drop Alert + Revenue Drop Alert + Deploy Failure Alert + API Failure Alert + Budget Low Alert + OpenAI Credits Low + Ads Budget Low + LLM Token Limit Warning + Auto Funding Triggered.

SYSTEM TELEMETRY PANEL: implementar painel telemetria contendo uso CPU do servidor + uso memória + requests por minuto + tempo resposta médio + erros por minuto + status workers + status scheduler.

SYSTEM OPERATIONS LOG: registrar eventos do sistema como Radar Cycle Started + Opportunity Emitted + Product Built + Optimization Cycle Executed + Ads Campaign Started + Strategy Changed.

⸻


BLOCO 1 — FUNDAÇÃO DO DASHBOARD

(Implementar tudo de uma vez)

Inclui:

CAMADA GLOBAL — UI BASE
ESTRUTURA FINAL DO DASHBOARD
CAMADA 1 — CORE SYSTEM CONTROL

Ou seja:
	•	UI/UX VISUAL DESIGN
	•	GRID do dashboard
	•	estrutura vertical completa
	•	HEADER STRUCTURE
	•	HEADER DEGRADED ERROR INDICATOR
	•	LOGIN PAGE IMPROVEMENT
	•	USER SESSION CONTROL
	•	DATA REFRESH SYSTEM
	•	MOCK MODE TOGGLE
	•	REAL DATA MODE
	•	ERROR HANDLING UI
	•	HISTORY STORAGE

Esse bloco cria:

• layout
• sessão
• header
• base visual
• modo mock/real
• refresh
• tratamento de erro

Sem isso o resto não funciona.

⸻

BLOCO 2 — MOTOR DE DESCOBERTA

(Implementar junto)

CAMADA 2 — SYSTEM STATUS
CAMADA 3 — RADAR ENGINE

Inclui:

SYSTEM STATUS PANEL

RADAR PIPELINE TABLE
RADAR CONTROL PANEL

Esse bloco conecta o dashboard com:
	•	radar engine
	•	estado do sistema
	•	métricas globais

Aqui o dashboard começa a ficar vivo.

⸻

BLOCO 3 — MOTOR DE PRODUTOS

(Implementar junto)

CAMADA 4 — PRODUCT CREATION PIPELINE
CAMADA 5 — PRODUCT PORTFOLIO CORE

Inclui:

PRODUCT DRAFT PIPELINE

PRODUCT PORTFOLIO GRID
PRODUCT METRICS BLOCK
PRODUCT ACTION BUTTONS
PRODUCT PAUSE CONFIRMATION MODAL

Aqui nasce o centro do sistema:

gestão de produtos.

⸻

BLOCO 4 — INTELIGÊNCIA E FINANCEIRO

(Implementar junto)

CAMADA 6
CAMADA 7
CAMADA 8

Inclui:

PRODUCT ANALYTICS PANEL
PRODUCT LIFECYCLE VISUAL
PRODUCT AGE INDICATOR
PRODUCT VERSION TRACKING
PRODUCT QUALITY TAG
PRODUCT TRAFFIC METRICS

FINANCE & RESOURCES PANEL
RESOURCE FORECAST ENGINE
AUTO FUNDING SYSTEM
AUTO FUNDING ALERTS
FINANCIAL SAFETY INDICATORS
STRIPE INTEGRATION STATUS
OPENAI API STATUS
ADS PLATFORM STATUS

AI DECISION LOG PANEL
ALERTS PANEL
SYSTEM TELEMETRY PANEL
SYSTEM OPERATIONS LOG

Aqui entra:

• analytics
• finanças
• alertas
• IA
• telemetria

⸻
