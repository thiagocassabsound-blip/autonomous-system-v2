from dashboard.dashboard_state_store import DashboardStateStore

class DashboardAPI:
    """
    Exposes data from the DashboardStateStore.
    Provides standard functions that the underlying HTTP server will map to endpoints.
    """
    
    @staticmethod
    def get_system_overview():
        return DashboardStateStore.get_system_overview()

    @staticmethod
    def get_radar():
        return DashboardStateStore.get_radar_opportunities()

    @staticmethod
    def get_products():
        return DashboardStateStore.get_products()

    @staticmethod
    def get_landings():
        return DashboardStateStore.get_landings()

    @staticmethod
    def get_traffic():
        return DashboardStateStore.get_traffic_metrics()

    @staticmethod
    def get_revenue():
        return DashboardStateStore.get_revenue_metrics()

    @staticmethod
    def get_intelligence():
        return DashboardStateStore.get_intelligence_signals()

    @staticmethod
    def get_health():
        return DashboardStateStore.get_system_health()
        
    @staticmethod
    def get_evolution():
        return DashboardStateStore.get_evolution()

    @staticmethod
    def get_finance():
        return DashboardStateStore.get_finance_overview()

    @staticmethod
    def get_infrastructure_health():
        return DashboardStateStore.get_infrastructure_health()

    @staticmethod
    def get_system_accounts_registry():
        return DashboardStateStore.get_system_accounts_registry()
