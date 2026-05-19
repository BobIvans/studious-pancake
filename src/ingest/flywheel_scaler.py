class FlywheelScaler:
    def __init__(self, initial_balance: float = 0.017):
        self.initial_balance = initial_balance
        self.current_phase = 1

    def get_trading_params(self, current_balance_sol: float) -> dict:
        """Динамические параметры в зависимости от роста капитала"""
        
        # Phase 1: Survival (0.017 - 0.1 SOL)
        if current_balance_sol < 0.1:
            return {
                "max_concurrent_trades": 1,
                "jito_tip_pct": 0.50,         # Отдаем 50% профита валидатору для 100% гарантии
                "min_net_profit_sol": 0.001,  # Ищем только верняки
                "allowed_strategies": ["stablecoins", "lst_tokens", "ultra_arb_wrappers", "kamino_receipts", "ultra_arb_yield_stables", "ultra_arb_graduation"], # Нулевой риск + тихие лаунчпады
                "rpc_fallback_enabled": False # ТОЛЬКО JITO
            }
            
        # Phase 2: Momentum (0.1 - 1.0 SOL)
        elif current_balance_sol < 1.0:
            return {
                "max_concurrent_trades": 3,
                "jito_tip_pct": 0.35,         # Снижаем чаевые, забираем больше себе
                "min_net_profit_sol": 0.0005,
                "allowed_strategies": ["stablecoins", "lst_tokens", "ultra_arb_wrappers"],
                "rpc_fallback_enabled": False
            }
            
        # Phase 3: Scaling (1.0+ SOL)
        else:
            return {
                "max_concurrent_trades": 10,
                "jito_tip_pct": 0.25,         # Оптимизированные чаевые
                "min_net_profit_sol": 0.0001,
                "allowed_strategies": "ALL",  # Включаем Pump.fun, Volatility и т.д.
                "rpc_fallback_enabled": True  # Теперь можно рисковать базовым газом
            }